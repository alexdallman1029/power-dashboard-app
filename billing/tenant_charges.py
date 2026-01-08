import pandas as pd

RATE = 0.13
FEE = 5.43
BASE_KWH = 45.0

def calculate_tenant_charges(
    *,
    kelly_russ_kwh: float,
    airstream_kwh: float,
    ryan_kwh: float,
    marc_kwh: float,
    kitchen_lounge_kwh: float,
    shared_shop_kwh: float,
    rate: float = RATE,
    fee: float = FEE,
    base_kwh: float = BASE_KWH,
) -> pd.DataFrame:
    """
    Returns a dataframe with kWh allocations + $ charges for the billing period.
    All inputs are already billing-period-filtered kWh values.
    """

    kelly_russ_alloc_kwh = (
        kelly_russ_kwh
        + (base_kwh / 7.0) * 2.0
        + (kitchen_lounge_kwh / 5.0) * 2.0
        + (shared_shop_kwh / 7.0) * 2.0
    )

    ryan_alloc_kwh = (
        ryan_kwh
        + (base_kwh / 7.0)
        + (kitchen_lounge_kwh / 5.0)
        + (shared_shop_kwh / 7.0)
    )

    marc_alloc_kwh = (
        marc_kwh
        + (base_kwh / 7.0)
        + (kitchen_lounge_kwh / 5.0)
        + (shared_shop_kwh / 7.0)
    )

    airstream_alloc_kwh = (
        airstream_kwh
        + (base_kwh / 7.0)
        + (kitchen_lounge_kwh / 5.0)
        + (shared_shop_kwh / 7.0)
    )

    def to_dollars(kwh: float) -> float:
        return round(kwh * rate + fee, 2)

    return pd.DataFrame(
        [
            {"Tenant": "Kelly & Russ", "kWh (calc)": kelly_russ_alloc_kwh, "Charge ($)": to_dollars(kelly_russ_alloc_kwh)},
            {"Tenant": "Ryan",         "kWh (calc)": ryan_alloc_kwh,     "Charge ($)": to_dollars(ryan_alloc_kwh)},
            {"Tenant": "Marc",         "kWh (calc)": marc_alloc_kwh,     "Charge ($)": to_dollars(marc_alloc_kwh)},
            {"Tenant": "Airstream",    "kWh (calc)": airstream_alloc_kwh,     "Charge ($)": to_dollars(airstream_alloc_kwh)},
        ]
    )
