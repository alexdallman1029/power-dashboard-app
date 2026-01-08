from __future__ import annotations

import os
from datetime import datetime, timezone
from typing import Iterable, Mapping, Any

from sqlalchemy import (
    create_engine,
    MetaData,
    Table,
    Column,
    String,
    Date,
    Float,
    DateTime,
    Integer,
    select,
    text,
)
from sqlalchemy.engine import Engine

# Correct dialect imports
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.dialects.postgresql import insert as pg_insert


# ---------- Engine ----------

def get_engine() -> Engine:
    db_url = os.getenv("DATABASE_URL", "sqlite:///data/energy.sqlite")
    return create_engine(db_url, future=True)


# ---------- Schema ----------

metadata = MetaData()

device_aliases = Table(
    "device_aliases",
    metadata,
    Column("device_gid", Integer, primary_key=True),
    Column("display_name", String(200), nullable=False),
    Column("updated_at", DateTime(timezone=True), nullable=False),
)


usage_daily = Table(
    "usage_daily",
    metadata,
    Column("day", Date, primary_key=True),
    Column("device_gid", Integer, primary_key=True),
    Column("channel_num", Integer, primary_key=True),
    Column("channel_name", String(200), nullable=True),
    Column("kwh", Float, nullable=False),
    Column("updated_at", DateTime(timezone=True), nullable=False),
)

kv_store = Table(
    "kv_store",
    metadata,
    Column("key", String(100), primary_key=True),
    Column("value", String(500), nullable=False),
    Column("updated_at", DateTime(timezone=True), nullable=False),
)


def init_db(engine: Engine) -> None:
    metadata.create_all(engine)


# ---------- Helpers ----------

def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def set_kv(engine: Engine, key: str, value: str) -> None:
    now = utcnow()
    dialect = engine.dialect.name

    if dialect == "postgresql":
        stmt = pg_insert(kv_store).values(
            key=key, value=value, updated_at=now
        ).on_conflict_do_update(
            index_elements=[kv_store.c.key],
            set_={"value": value, "updated_at": now},
        )
    else:
        stmt = sqlite_insert(kv_store).values(
            key=key, value=value, updated_at=now
        ).on_conflict_do_update(
            index_elements=[kv_store.c.key],
            set_={"value": value, "updated_at": now},
        )

    with engine.begin() as conn:
        conn.execute(stmt)


def get_kv(engine: Engine, key: str) -> str | None:
    with engine.begin() as conn:
        return conn.execute(
            select(kv_store.c.value).where(kv_store.c.key == key)
        ).scalar_one_or_none()


def upsert_usage_daily(engine: Engine, rows: Iterable[Mapping[str, Any]]) -> int:
    rows_list = list(rows)
    if not rows_list:
        return 0

    now = utcnow()
    rows_list = [{**r, "updated_at": r.get("updated_at", now)} for r in rows_list]

    dialect = engine.dialect.name
    pk_cols = [usage_daily.c.day, usage_daily.c.device_gid, usage_daily.c.channel_num]

    if dialect == "postgresql":
        stmt = pg_insert(usage_daily).values(rows_list).on_conflict_do_update(
            index_elements=pk_cols,
            set_={
                "kwh": text("EXCLUDED.kwh"),
                "channel_name": text("EXCLUDED.channel_name"),
                "updated_at": text("EXCLUDED.updated_at"),
            },
        )
    else:
        stmt = sqlite_insert(usage_daily).values(rows_list).on_conflict_do_update(
            index_elements=pk_cols,
            set_={
                "kwh": text("excluded.kwh"),
                "channel_name": text("excluded.channel_name"),
                "updated_at": text("excluded.updated_at"),
            },
        )

    with engine.begin() as conn:
        conn.execute(stmt)

    return len(rows_list)


def upsert_device_aliases(engine: Engine, rows: Iterable[Mapping[str, Any]]) -> int:
    rows_list = list(rows)
    if not rows_list:
        return 0

    now = utcnow()
    rows_list = [{**r, "updated_at": r.get("updated_at", now)} for r in rows_list]

    dialect = engine.dialect.name

    if dialect == "postgresql":
        stmt = pg_insert(device_aliases).values(rows_list).on_conflict_do_update(
            index_elements=[device_aliases.c.device_gid],
            set_={
                "display_name": text("EXCLUDED.display_name"),
                "updated_at": text("EXCLUDED.updated_at"),
            },
        )
    else:
        stmt = sqlite_insert(device_aliases).values(rows_list).on_conflict_do_update(
            index_elements=[device_aliases.c.device_gid],
            set_={
                "display_name": text("excluded.display_name"),
                "updated_at": text("excluded.updated_at"),
            },
        )

    with engine.begin() as conn:
        conn.execute(stmt)

    return len(rows_list)

