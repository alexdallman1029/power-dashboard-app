from shared.db import get_engine, init_db, upsert_device_aliases

DEVICE_NAMES = [
    {"device_gid": 417380, "display_name": "RV Sites"},
    {"device_gid": 422491, "display_name": "Pole Barn Main"},
    {"device_gid": 431597, "display_name": "Starlink"},
    {"device_gid": 432058, "display_name": "Pole Barn Sub"},
    {"device_gid": 432079, "display_name": "Grow Barn"},
]

def main():
    engine = get_engine()
    init_db(engine)
    n = upsert_device_aliases(engine, DEVICE_NAMES)
    print(f"Upserted {n} device aliases.")

if __name__ == "__main__":
    main()