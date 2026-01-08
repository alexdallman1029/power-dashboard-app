import streamlit as st
import pandas as pd
import plotly.express as px
import datetime as dt
#import sqlite3
from sqlalchemy import text
from shared.db import get_engine
from datetime import datetime
from zoneinfo import ZoneInfo
from PIL import Image

from billing.tenant_charges import calculate_tenant_charges
#---------------------------
# Title and Header
#---------------------------
logo = Image.open("assets/fishdog-24.png")
st.set_page_config(page_title="FishDog Farm Dashboard", layout="wide")

#Center logo and title
left, mid, right = st.columns([3, 3, 3])

with mid:
    st.image(logo, width=350)
    st.title("Data Dashboard")

#---------------------------
# Data
#---------------------------

#only used w/ sqlite
#DB_PATH = "data/energy.sqlite"

FEATURED_GIDS = [417380, 422491, 432058, 432079]

RV_SITES_GID = 417380
POLE_BARN_MAIN_GID = 422491
POLE_BARN_SUB_GID = 432058


RV_SITES = 417380
GROW_BARN = 432079
POLE_BARN_MAIN = 422491
POLE_BARN_SUB = 432058

#---------------------------
# Color Palette
#---------------------------
PALETTE = {
    "color1": "#4c5424",
    "color2": "#ceb82c",
    "color3": "#81c566",
    "color4": "#6e73b6",
    "color5": "#d39f76",
    "color6": "#3d4187",
}

#For plotly charts specifically
px.defaults.color_discrete_sequence = [
    PALETTE["color1"],
    PALETTE["color2"],
    PALETTE["color3"],
    PALETTE["color4"],
    PALETTE["color5"],
    PALETTE["color6"],
]

# -------------------------
# Helpers
# -------------------------

#only used w/ sqlite
#@st.cache_data(ttl=60)
#def load_table(sql: str) -> pd.DataFrame:
    #conn = sqlite3.connect(DB_PATH)
    #df = pd.read_sql_query(sql, conn)
    #conn.close()
    #return df

engine = get_engine()

@st.cache_data(ttl=60)
def query_df(sql: str, params: dict | None = None) -> pd.DataFrame:
    params = params or {}
    with engine.begin() as conn:
        return pd.read_sql_query(text(sql), conn, params=params)
    
#tests
#st.write("DB:", engine.dialect.name)
#st.write("Max day:", query_df("select max(day) as d from usage_daily").iloc[0]["d"])
#st.write("Last ingest:", query_df("select value from kv_store where key='last_ingested_at_utc'").iloc[0]["value"])


def first_of_month(d: dt.date) -> dt.date:
    return dt.date(d.year, d.month, 1)

BILLING_DAY = 27  # Emporia billing cycle day

def last_day_of_month(d: dt.date) -> int:
    next_month = (d.replace(day=28) + dt.timedelta(days=4)).replace(day=1)
    return (next_month - dt.timedelta(days=1)).day

def clamp_day(year: int, month: int, day: int) -> dt.date:
    dmax = last_day_of_month(dt.date(year, month, 1))
    return dt.date(year, month, min(day, dmax))

def billing_period_for_ym(billing_ym: str, billing_day: int = BILLING_DAY) -> tuple[dt.date, dt.date]:
    """
    billing_ym is the Emporia "billing month" label in YYYY-MM.
    For billing_day=27: billing_ym=2026-01 means 2025-12-27 .. 2026-01-26
    """
    y, m = map(int, billing_ym.split("-"))
    period_start = dt.date(y, m, 1)

    prev_month = (period_start - dt.timedelta(days=1)).replace(day=1)
    start = clamp_day(prev_month.year, prev_month.month, billing_day)

    this_billing_day = clamp_day(period_start.year, period_start.month, billing_day)
    end = this_billing_day - dt.timedelta(days=1)

    return start, end


# -------- Get device names from database --------
aliases = query_df(
    "select device_gid, display_name from device_aliases"
)

device_name_map = dict(
    zip(aliases["device_gid"], aliases["display_name"])
)

device_name_map = {int(k): v for k, v in device_name_map.items()}


# -------- Get last time data were updated --------
last_ingest = query_df(
    "select value from kv_store where key = 'last_ingested_at_utc' limit 1"
)

if not last_ingest.empty:
    utc_ts = last_ingest["value"].iloc[0]

    # Parse ISO string as UTC
    dt_utc = datetime.fromisoformat(utc_ts).replace(tzinfo=ZoneInfo("UTC"))

    # Convert to Pacific Time
    dt_pst = dt_utc.astimezone(ZoneInfo("America/Los_Angeles"))

    # Format: Month Day, Year, Time
    last_updated_str = dt_pst.strftime("%B %d, %Y · %I:%M %p")

else:
    last_updated_str = "Unknown"

st.caption(f"Last updated: {last_updated_str} (PT)")


# -------- Month selector (defaults to current month) --------
today = dt.date.today()
default_month = first_of_month(today)

available_months = query_df(
    """
    select distinct
      case
        when extract(day from day) >= :billing_day
        then to_char(day + interval '1 month', 'YYYY-MM')
        else to_char(day, 'YYYY-MM')
      end as ym
    from usage_daily
    order by ym desc
    """,
    params={"billing_day": BILLING_DAY},
)

raw_months = sorted(available_months["ym"].tolist(), reverse=True)

def ym_to_label(ym: str) -> str:
    d = dt.date.fromisoformat(ym + "-01")
    return d.strftime("%B %Y")   # e.g. "January 2026"

# Build mapping
month_labels = {ym_to_label(ym): ym for ym in raw_months}

# Ensure current month is first
default_ym = default_month.strftime("%Y-%m")
if default_ym not in month_labels.values():
    month_labels = {ym_to_label(default_ym): default_ym, **month_labels}

col_month, col_spacer = st.columns([3, 9])

with col_month:
    month_label = st.selectbox(
        "Month",
        options=list(month_labels.keys()),
        index=0,
    )

month_ym = month_labels[month_label]

period_start, period_end = billing_period_for_ym(month_ym, BILLING_DAY)

# Show the actual billing period for clarity/auditing
st.caption(f"Billing period: {period_start.strftime('%b %d, %Y')} – {period_end.strftime('%b %d, %Y')}")

# -------- Global “as of” / summary --------
global_range = query_df(
    """
    select
      min(day) as min_day,
      max(day) as max_day
    from usage_daily
    where day >= :start
      and day <= :end
    """,
    params={"start": period_start, "end": period_end},
).iloc[0]


as_of = global_range["max_day"]

summary = query_df(
    """
    select
      count(*) as rows,
      count(distinct device_gid) as devices,
      count(distinct channel_num) as device_channels,
      round(sum(kwh)::numeric, 3) as kwh_total
    from usage_daily
    where device_gid = :device_gid
      and channel_num = 0
      and day >= :start
      and day <= :end
    """,
    params={"device_gid": POLE_BARN_MAIN_GID, "start": period_start, "end": period_end},
).iloc[0]


st.header("Total Farm Power Usage")

c1, c2, c3 = st.columns(3)
c1.metric("Total kWh", f"{float(summary['kwh_total'] or 0.0):,.2f}")
c2.metric("Start day", str(global_range["min_day"]))
c3.metric("End day", str(global_range["max_day"]))

st.divider()

# -------- Tenant calculations --------

st.header("Tenant Power")

def get_device_main_kwh(device_gid: int) -> float:
    df = query_df(
        """
        select sum(kwh) as kwh
        from usage_daily
        where device_gid = :device_gid
          and channel_num = 0
          and day >= :start
          and day <= :end
        """,
        params={"device_gid": device_gid, "start": period_start, "end": period_end},
    )
    v = df["kwh"].iloc[0]
    return float(v) if v is not None else 0.0

def get_device_total_kwh_pref_main(device_gid: int) -> float:
    df = query_df(
        """
        select
          sum(case when channel_num = 0 then kwh else 0 end) as kwh_main,
          sum(case when channel_num != 0 then kwh else 0 end) as kwh_sub
        from usage_daily
        where device_gid = :device_gid
          and day >= :start
          and day <= :end
        """,
        params={"device_gid": device_gid, "start": period_start, "end": period_end},
    ).iloc[0]

    main = float(df["kwh_main"] or 0.0)
    sub  = float(df["kwh_sub"] or 0.0)
    return main if main > 0 else sub


def get_channel_kwh(device_gid: int, channel_name: str) -> float:
    df = query_df(
        """
        select sum(kwh) as kwh
        from usage_daily
        where device_gid = :device_gid
          and day >= :start
          and day <= :end
          and lower(trim(coalesce(channel_name,''))) = lower(trim(:channel_name))
        """,
        params={
            "device_gid": device_gid,
            "start": period_start,
            "end": period_end,
            "channel_name": channel_name,
        },
    )
    v = df["kwh"].iloc[0]
    return float(v) if v is not None else 0.0


def billing_ym_expr(billing_day: int = BILLING_DAY) -> str:
    return f"""
    case
      when extract(day from day) >= {billing_day}
      then to_char(day + interval '1 month', 'YYYY-MM')
      else to_char(day, 'YYYY-MM')
    end
    """


def monthly_channel_kwh(device_gid: int, channel_name: str, months: list[str]) -> pd.DataFrame:
    ym_expr = billing_ym_expr()

    df = query_df(
        f"""
        select
          {ym_expr} as ym,
          sum(kwh) as kwh
        from usage_daily
        where device_gid = :device_gid
          and lower(trim(coalesce(channel_name,''))) = lower(trim(:channel_name))
          and {ym_expr} = any(:months)
        group by ym
        """,
        params={"device_gid": device_gid, "channel_name": channel_name, "months": months},
    )

    base = pd.DataFrame({"ym": months})
    out = base.merge(df, on="ym", how="left").fillna({"kwh": 0.0})
    out["kwh"] = out["kwh"].astype(float)
    return out

def monthly_device_total_pref_main(device_gid: int, months: list[str]) -> pd.DataFrame:
    ym_expr = billing_ym_expr()

    df = query_df(
        f"""
        select
          {ym_expr} as ym,
          sum(case when channel_num = 0 then kwh else 0 end) as kwh_main,
          sum(case when channel_num != 0 then kwh else 0 end) as kwh_sub
        from usage_daily
        where device_gid = :device_gid
          and {ym_expr} = any(:months)
        group by ym
        """,
        params={"device_gid": device_gid, "months": months},
    )

    base = pd.DataFrame({"ym": months})
    out = base.merge(df, on="ym", how="left").fillna({"kwh_main": 0.0, "kwh_sub": 0.0})
    out["kwh_main"] = out["kwh_main"].astype(float)
    out["kwh_sub"]  = out["kwh_sub"].astype(float)
    out["kwh"] = out.apply(lambda r: r["kwh_main"] if r["kwh_main"] > 0 else r["kwh_sub"], axis=1)
    return out[["ym", "kwh"]]


def monthly_device_main_kwh(device_gid: int, months: list[str]) -> pd.DataFrame:
    ym_expr = billing_ym_expr()

    df = query_df(
        f"""
        select
          {ym_expr} as ym,
          sum(case when channel_num = 0 then kwh else 0 end) as kwh
        from usage_daily
        where device_gid = :device_gid
          and {ym_expr} = any(:months)
        group by ym
        """,
        params={"device_gid": device_gid, "months": months},
    )

    base = pd.DataFrame({"ym": months})
    out = base.merge(df, on="ym", how="left").fillna({"kwh": 0.0})
    out["kwh"] = out["kwh"].astype(float)
    return out


def monthly_device_total_for_chart(device_gid: int, months: list[str]) -> pd.DataFrame:
    """
    Returns a 2-col DF: ym, kwh_total_for_device
    Uses main (channel 0) if it exists; otherwise uses sub total.
    """
    df = monthly_device_total_pref_main(device_gid, months).copy()
    df = df.rename(columns={"kwh": "kwh_total"})
    return df

# --- Pull kWh from DB (month-filtered) ---
rv_total = get_device_total_kwh_pref_main(RV_SITES_GID)
pole_sub_total = get_device_total_kwh_pref_main(POLE_BARN_SUB_GID)
pole_main_total = get_device_main_kwh(POLE_BARN_MAIN_GID)

airstream_kwh = get_channel_kwh(POLE_BARN_MAIN_GID, "Airstream")
ryan_kwh = get_channel_kwh(RV_SITES_GID, "Ryan")
marc_kwh = get_channel_kwh(RV_SITES_GID, "Marc")
kelly_russ_kwh = get_channel_kwh(RV_SITES_GID, "Kelly & Russ")

# Derived buckets
kitchen_raw = pole_sub_total - rv_total
shared_raw = pole_main_total - pole_sub_total - airstream_kwh

kitchen_lounge_kwh = kitchen_raw
shared_shop_kwh = max(0.0, pole_main_total - pole_sub_total - airstream_kwh)

# --- Calculate charges (math in billing.tenant_charges.py) ---
results = calculate_tenant_charges(
    kelly_russ_kwh=kelly_russ_kwh,
    airstream_kwh=airstream_kwh,
    ryan_kwh=ryan_kwh,
    marc_kwh=marc_kwh,
    kitchen_lounge_kwh=kitchen_lounge_kwh,
    shared_shop_kwh=shared_shop_kwh,
)

#Show results
cols = st.columns(len(results))

for col, (_, row) in zip(cols, results.iterrows()):
    with col:
        st.metric(
            label=row[0],
            value=f"${row[2]:,.2f}",
            delta=None
        )
        st.caption(f"{row[1]:,.1f} kWh")


st.subheader("Monthly Power Usage over Time")

# ---- choose the last 12 billing months up through the selected month ----
months_for_chart = [m for m in raw_months if m <= month_ym][:12]
months_for_chart = list(reversed(months_for_chart))  # oldest -> newest

# ---- monthly kWh inputs (these match the arguments you already pass to calculate_tenant_charges) ----
m_ryan = monthly_channel_kwh(RV_SITES_GID, "Ryan", months_for_chart).rename(columns={"kwh": "ryan_kwh"})
m_marc = monthly_channel_kwh(RV_SITES_GID, "Marc", months_for_chart).rename(columns={"kwh": "marc_kwh"})
m_kelr = monthly_channel_kwh(RV_SITES_GID, "Kelly & Russ", months_for_chart).rename(columns={"kwh": "kelly_russ_kwh"})
m_air  = monthly_channel_kwh(POLE_BARN_MAIN_GID, "Airstream", months_for_chart).rename(columns={"kwh": "airstream_kwh"})

m_rv_total   = monthly_device_total_pref_main(RV_SITES_GID, months_for_chart).rename(columns={"kwh": "rv_total"})
m_pole_sub   = monthly_device_total_pref_main(POLE_BARN_SUB_GID, months_for_chart).rename(columns={"kwh": "pole_sub_total"})
m_pole_main0 = monthly_device_main_kwh(POLE_BARN_MAIN_GID, months_for_chart).rename(columns={"kwh": "pole_main_total"})

# ---- derive Kitchen/Lounge + Shared Shop monthly kWh exactly like your single-month math ----
base = pd.DataFrame({"ym": months_for_chart})
m = (
    base.merge(m_ryan, on="ym")
        .merge(m_marc, on="ym")
        .merge(m_kelr, on="ym")
        .merge(m_air, on="ym")
        .merge(m_rv_total, on="ym")
        .merge(m_pole_sub, on="ym")
        .merge(m_pole_main0, on="ym")
)

m["kitchen_lounge_kwh"] = (m["pole_sub_total"] - m["rv_total"]).clip(lower=0.0)
m["shared_shop_kwh"] = (m["pole_main_total"] - m["pole_sub_total"] - m["airstream_kwh"]).clip(lower=0.0)

# ---- Compute monthly $ by reusing calculate_tenant_charges for each month ----
rows = []
for _, r in m.iterrows():
    monthly_results = calculate_tenant_charges(
        kelly_russ_kwh=float(r["kelly_russ_kwh"]),
        airstream_kwh=float(r["airstream_kwh"]),
        ryan_kwh=float(r["ryan_kwh"]),
        marc_kwh=float(r["marc_kwh"]),
        kitchen_lounge_kwh=float(r["kitchen_lounge_kwh"]),
        shared_shop_kwh=float(r["shared_shop_kwh"]),
    ).copy()

    monthly_results["ym"] = r["ym"]
    rows.append(monthly_results)

monthly_all = pd.concat(rows, ignore_index=True)

monthly_all = monthly_all.rename(columns={
    monthly_all.columns[0]: "Tenant",
    monthly_all.columns[1]: "kWh",
    monthly_all.columns[2]: "$",
})

# ---- UI controls ----
tenant_col, tenant_col2 = st.columns([3,9])

with tenant_col:
    tenant_choice = st.selectbox(
        "Tenant", 
        options=sorted(monthly_all["Tenant"].unique().tolist()), 
        index=0
        )

view = st.segmented_control(
    "View",
    options=["kWh", "$"],
    default="kWh",
)

# ---- chart dataframe ----
chart_df = monthly_all.loc[monthly_all["Tenant"] == tenant_choice, ["ym", "kWh", "$"]].copy()
chart_df["Month"] = pd.to_datetime(chart_df["ym"] + "-01").dt.strftime("%b %Y")

y_col = "kWh" if view == "kWh" else "$"
y_title = "kWh (billing month)" if view == "kWh" else "Charge ($, billing month)"
text_fmt = "%{text:.0f}" if view == "kWh" else "$%{text:,.0f}"

if y_col == "$":
    bar_color = "#ceb82c"
else:
    bar_color = "#3d4187"


fig_tenant = px.bar(
    chart_df,
    x="Month",
    y=y_col,
    text=y_col,
)

fig_tenant.update_traces(
    marker_color=bar_color,
    texttemplate=text_fmt,
    textposition="outside",
    cliponaxis=False,
    hovertemplate=(
        "<b>%{x}</b><br>"
        "Usage: %{customdata[0]:,.1f} kWh<br>"
        "Charge: $%{customdata[1]:,.2f}<extra></extra>"
    ),
    customdata=chart_df[["kWh", "$"]].values,
)

fig_tenant.update_layout(
    xaxis_title="",
    yaxis_title=y_title,
    margin=dict(l=10, r=10, t=10, b=10),
)

st.plotly_chart(fig_tenant, use_container_width=True)

st.divider()

# -------- Per-device totals and per-channel tables --------
st.header("All Power Usage")

#used w/ sqlite
#placeholders = ",".join(["?"] * len(FEATURED_GIDS))

device_totals = query_df(
    """
    select
      device_gid,
      round(sum(case when channel_num = 0 then kwh else 0 end)::numeric, 3) as kwh_main,
      round(sum(case when channel_num != 0 then kwh else 0 end)::numeric, 3) as kwh_sub,
      round(
        (
          case
            when sum(case when channel_num = 0 then kwh else 0 end) > 0
            then sum(case when channel_num = 0 then kwh else 0 end)
            else sum(case when channel_num != 0 then kwh else 0 end)
          end
        )::numeric
      , 3) as kwh_device,
      count(distinct case when channel_num != 0 then channel_num end) as channels,
      min(day) as start_day,
      max(day) as end_day
    from usage_daily
    where day >= :start
      and day <= :end
      and device_gid = any(:gids)
    group by device_gid
    order by device_gid
    """,
    params={"start": period_start, "end": period_end, "gids": FEATURED_GIDS},
)


# Reorder
device_totals["__order"] = device_totals["device_gid"].apply(
    lambda x: FEATURED_GIDS.index(int(x)) if int(x) in FEATURED_GIDS else 999
)
device_totals = device_totals.sort_values("__order").drop(columns="__order")


if device_totals.empty:
    st.warning("No data found for that month.")
    st.stop()


def render_device_section(device_gid: int):
    device_name = device_name_map.get(device_gid, f"Device {device_gid}")

    d = device_totals.loc[device_totals["device_gid"] == device_gid]
    if d.empty:
        st.subheader(device_name)
        st.info("No data for this device in the selected billing period.")
        return

    drow = d.iloc[0]

    st.subheader(device_name)
    st.metric("Device kWh", f"{float(drow['kwh_device'] or 0.0):,.2f}")

    # ---- Monthly totals chart (last 12 billing months) ----
    months_for_device_chart = raw_months[:12]
    months_for_device_chart = list(reversed(months_for_device_chart))  # oldest -> newest

    mdf = monthly_device_total_for_chart(int(device_gid), months_for_device_chart)

    # Label months nicely
    mdf["Month"] = pd.to_datetime(mdf["ym"] + "-01").dt.strftime("%b %Y")
    mdf["kWh"] = mdf["kwh_total"].astype(float)

    DEVICE_COLORS = {
        RV_SITES: "#3d4187",
        GROW_BARN: "#81c566",
        POLE_BARN_MAIN: "#ceb82c",
        POLE_BARN_SUB: "#6e73b6",
}

    fig_dev = px.bar(
        mdf,
        x="Month",
        y="kWh",
        text="kWh",
    )
    fig_dev.update_traces(
        marker_color=DEVICE_COLORS.get(int(device_gid), "#3d4187"),
        texttemplate="%{text:.0f}",
        textposition="outside",
        cliponaxis=False,
    )
    fig_dev.update_layout(
        xaxis_title="",
        yaxis_title="kWh (billing month)",
        margin=dict(l=10, r=10, t=10, b=10),
    )

    st.plotly_chart(fig_dev, use_container_width=True)


    # ---- Balance like Emporia  ----
    main_kwh = float(drow["kwh_main"] or 0.0)
    sub_kwh = float(drow["kwh_sub"] or 0.0)
    if main_kwh > 0:
        bal = main_kwh - sub_kwh
        st.caption(f"Subchannels: {sub_kwh:,.2f} kWh · Balance: {bal:,.2f} kWh")

    # ---- Channel details (exclude Main) ----
    try:
        channels_df = query_df(
            """
            select
            channel_num,
            coalesce(nullif(trim(channel_name), ''), 'Unnamed') as channel_name,
            round(sum(kwh)::numeric, 3) as kwh
            from usage_daily
            where device_gid = :device_gid
            and day >= :start
            and day <= :end
            and channel_num != 0
            group by channel_num, channel_name
            having sum(kwh) is not null
            order by kwh desc
            """,
            params={"device_gid": int(device_gid), "start": period_start, "end": period_end},
        )

    except Exception as e:
        st.error(f"Channel query failed for {device_name}: {e}")
        return

    channels_df = channels_df[channels_df["channel_name"] != "Unnamed"].copy()
    channels_df = channels_df.rename(columns={"channel_name": "Channel", "kwh": "kWh (billing period)"})
    channels_df = channels_df[["Channel", "kWh (billing period)"]]

    with st.expander("Channel details", expanded=False):
        st.dataframe(channels_df, use_container_width=True, hide_index=True)

    channels_df = query_df(
        """
        select
        channel_num,
        coalesce(nullif(trim(channel_name), ''), 'Unnamed') as channel_name,
        round(sum(kwh)::numeric, 3) as kwh
        from usage_daily
        where device_gid = :device_gid
        and day >= :start
        and day <= :end
        and channel_num != 0
        group by channel_num, channel_name
        having sum(kwh) is not null
        order by kwh desc
        """,
        params={"device_gid": int(device_gid), "start": period_start, "end": period_end},
    )


    channels_df = channels_df[channels_df["channel_name"] != "Unnamed"].copy()
    channels_df = channels_df.rename(columns={"channel_name": "Channel", "kwh": "kWh (billing period)"})
    channels_df = channels_df[["Channel", "kWh (billing period)"]]


# Row 1: RV Sites | Grow Barn
col_left, col_right = st.columns(2)
with col_left:
    render_device_section(RV_SITES)
with col_right:
    render_device_section(GROW_BARN)

st.divider()

# Row 2: Pole Barn Main | Pole Barn Sub
col_left, col_right = st.columns(2)
with col_left:
    render_device_section(POLE_BARN_MAIN)
with col_right:
    render_device_section(POLE_BARN_SUB)


