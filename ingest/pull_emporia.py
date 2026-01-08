# ingest/pull_emporia.py
from __future__ import annotations

import os
import sys
import datetime as dt
from typing import List, Dict, Any, Optional

import pyemvue
from pyemvue.enums import Scale, Unit

from shared.db import get_engine, init_db, upsert_usage_daily, set_kv, upsert_device_aliases


# ------------------------
# Utilities
# ------------------------

def require_env(name: str) -> str:
    val = os.getenv(name)
    if not val:
        raise RuntimeError(f"Missing required environment variable: {name}")
    return val


def parse_days_back(argv: list[str], default: int = 40) -> int:
    """
    Accepts either:
      - python -m ingest.pull_emporia 40
    and tolerates accidental comma-separated input:
      - python -m ingest.pull_emporia 1,2,3  -> uses 1
    """
    if len(argv) <= 1:
        return default

    raw = argv[1].strip()
    if "," in raw:
        raw = raw.split(",", 1)[0].strip()

    try:
        return int(raw)
    except ValueError as e:
        raise RuntimeError(f"days_back must be an integer (e.g., 40). Got: {argv[1]!r}") from e


def ensure_tz_aware_utc(x: dt.datetime) -> dt.datetime:
    if x.tzinfo is None:
        return x.replace(tzinfo=dt.timezone.utc)
    return x.astimezone(dt.timezone.utc)


def safe_int(x: Any, default: int = 0) -> int:
    """
    Convert x to int safely. Handles:
      - None -> default
      - int -> int
      - "123" -> 123
      - "1,2,3" -> 1
      - " 45 " -> 45
    """
    if x is None:
        return default
    if isinstance(x, int):
        return x

    try:
        if isinstance(x, float) and x.is_integer():
            return int(x)
    except Exception:
        pass

    s = str(x).strip()
    if not s:
        return default
    if "," in s:
        s = s.split(",", 1)[0].strip()
    try:
        return int(s)
    except ValueError as e:
        raise ValueError(f"safe_int: cannot convert {x!r} to int") from e


def safe_str(x: Any, default: Optional[str] = None) -> Optional[str]:
    if x is None:
        return default
    s = str(x).strip()
    return s if s else default


# ------------------------
# Emporia channel helpers
# ------------------------

def list_device_channels(devices) -> list:
    channels = []
    for d in devices:
        chs = getattr(d, "channels", None)
        if chs:
            channels.extend(list(chs))
    return channels


def choose_channels(devices, mode: str = "main_only") -> list:
    """
    mode:
      - "main_only": one 'Main' (or first) channel per device
      - "all": all channels
      - "named_only": all channels with a non-empty name, and a clean single integer channel number
    """
    all_channels = list_device_channels(devices)

    if mode == "all":
        return all_channels

    if mode == "named_only":
        selected = []
        for ch in all_channels:
            dg, cn, name = channel_identity(ch)

            # Always include Main aggregate (cn==0)
            if cn == 0:
                selected.append(ch)
                continue

            # Otherwise include only channels with a real name
            if not name or str(name).strip().lower() in {"none", ""}:
                continue

            selected.append(ch)

        # de-dupe by (device_gid, channel_num)
        dedup = {}
        for ch in selected:
            dg, cn, _ = channel_identity(ch)
            dedup[(dg, cn)] = ch
        return [dedup[k] for k in sorted(dedup.keys())]


    # default: main_only
    selected = []
    by_device: dict[Any, list] = {}
    for ch in all_channels:
        dev_gid = getattr(ch, "device_gid", None)
        if dev_gid is None:
            dev_gid = getattr(getattr(ch, "device", None), "device_gid", None)
        by_device.setdefault(dev_gid, []).append(ch)

    for _, chs in by_device.items():
        main = next(
            (c for c in chs if (getattr(c, "name", "") or "").strip().lower() == "main"),
            None,
        )
        selected.append(main if main is not None else chs[0])

    return [c for c in selected if c is not None]


def channel_identity(ch) -> tuple[int, int, Optional[str]]:
    """
    Returns (device_gid, channel_num, channel_name) robustly across different PyEmVue object shapes.
    Normalizes aggregate channels like "1,2,3" to channel_num=0, channel_name="Main".
    """
    # Device GID
    device_gid_raw = getattr(ch, "device_gid", None)
    if device_gid_raw is None:
        device_gid_raw = getattr(getattr(ch, "device", None), "device_gid", None)
    device_gid = safe_int(device_gid_raw, default=0)

    # Channel number
    channel_num_raw = getattr(ch, "channel_num", None)
    if channel_num_raw is None:
        channel_num_raw = getattr(ch, "channelNum", None)

    raw_s = str(channel_num_raw).strip() if channel_num_raw is not None else ""
    if "," in raw_s:
        channel_num = 0
        channel_name = "Main"
    else:
        channel_num = safe_int(channel_num_raw, default=0)
        channel_name = safe_str(getattr(ch, "name", None), default=None)

    return device_gid, channel_num, channel_name


def fetch_daily_kwh(
    vue: pyemvue.PyEmVue,
    channel,
    start_utc: dt.datetime,
    end_utc: dt.datetime,
) -> list[tuple[dt.datetime, float]]:
    """
    Fetch daily kWh values for [start_utc, end_utc).
    """
    start_utc = ensure_tz_aware_utc(start_utc)
    end_utc = ensure_tz_aware_utc(end_utc)

    usage_over_time, start_time = vue.get_chart_usage(
        channel,
        start_utc,
        end_utc,
        scale=Scale.DAY.value,
        unit=Unit.KWH.value,
    )

    start_time = ensure_tz_aware_utc(start_time)

    out: list[tuple[dt.datetime, float]] = []
    cursor = start_time
    for val in usage_over_time:
        try:
            kwh = float(val) if val is not None else 0.0
        except Exception:
            kwh = 0.0
        out.append((cursor, kwh))
        cursor = cursor + dt.timedelta(days=1)

    return out


# ------------------------
# Main job
# ------------------------

def main(days_back: int = 40, channel_mode: str = "main_only") -> int:
    """
    Pull daily usage for the last `days_back` days and upsert into SQLite/Postgres via SQLAlchemy.

    Environment variables:
      EMPORIA_USERNAME (required)
      EMPORIA_PASSWORD (required)
      DATABASE_URL (optional; defaults to sqlite:///data/energy.sqlite)
      EMPORIA_CHANNEL_MODE (optional; 'main_only' or 'all')
    """
    username = require_env("EMPORIA_USERNAME")
    password = require_env("EMPORIA_PASSWORD")

    engine = get_engine()
    init_db(engine)

    vue = pyemvue.PyEmVue()
    vue.login(username=username, password=password)

    devices = vue.get_devices()

    alias_rows = []
    for d in devices:
        dg = getattr(d, "device_gid", None)
        if dg is None:
            continue

        name = getattr(d, "device_name", None) or getattr(d, "name", None)
        if not name:
            continue

        alias_rows.append(
            {"device_gid": int(dg), "display_name": str(name).strip()}
        )

    upsert_device_aliases(engine, alias_rows)


    channels = choose_channels(devices, mode=channel_mode)

    if not channels:
        raise RuntimeError("No channels found. Check Emporia account/device setup.")

    end_utc = dt.datetime.now(dt.timezone.utc)
    start_utc = end_utc - dt.timedelta(days=days_back)

    rows: List[Dict[str, Any]] = []

    for ch in channels:
        device_gid, channel_num, channel_name = channel_identity(ch)

        series = fetch_daily_kwh(vue, ch, start_utc, end_utc)
        for day_dt, kwh in series:
            rows.append(
                {
                    "day": day_dt.date(),  # UTC day boundary for now
                    "device_gid": device_gid,
                    "channel_num": channel_num,
                    "channel_name": channel_name,
                    "kwh": kwh,
                }
            )

    n = upsert_usage_daily(engine, rows)
    set_kv(engine, "last_ingested_at_utc", end_utc.isoformat())

    print(
        f"Upserted {n} daily rows across {len(channels)} channel(s). "
        f"Range: {start_utc.date()} to {end_utc.date()} (UTC)"
    )
    return 0


if __name__ == "__main__":
    days_back = parse_days_back(sys.argv, default=40)

    channel_mode = os.getenv("EMPORIA_CHANNEL_MODE", "named_only").strip().lower()
    if channel_mode not in {"named_only", "all"}:
        raise SystemExit("EMPORIA_CHANNEL_MODE must be 'named_only' or 'all'")

    raise SystemExit(main(days_back=days_back, channel_mode=channel_mode))
