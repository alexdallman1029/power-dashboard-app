import os
import pyemvue

def require_env(name: str) -> str:
    val = os.getenv(name)
    if not val:
        raise RuntimeError(f"Missing required environment variable: {name}")
    return val

def main():
    vue = pyemvue.PyEmVue()
    vue.login(username=require_env("EMPORIA_USERNAME"),
              password=require_env("EMPORIA_PASSWORD"))

    devices = vue.get_devices()

    print("\n=== DEVICE + CHANNEL INVENTORY ===\n")
    for d in devices:
        dg = getattr(d, "device_gid", None)
        name = getattr(d, "device_name", None) or getattr(d, "name", None) or "Unnamed device"
        print(f"Device: {name}  device_gid={dg}")

        channels = getattr(d, "channels", []) or []
        for ch in channels:
            ch_num = getattr(ch, "channel_num", None)
            if ch_num is None:
                ch_num = getattr(ch, "channelNum", None)
            ch_name = getattr(ch, "name", None)
            print(f"  - channel_num={ch_num}  name={ch_name}")

        print()

if __name__ == "__main__":
    main()
