#!/usr/bin/env python3
"""Client mode: a keyboard plugged into the player PC (or a Flirc or other IR receiver that types like one) is the TV's
remote. FieldStation42's own remote (fs42/pi/remote_controller.py) decides what each key does: up and down change the
channel, left and right the volume, digits type a channel number, Home the guide, Backspace the last channel, M mute.
This only finds the keyboards, and keeps finding them as they are plugged in and out.

Not FieldStation42's "all devices" mode: that also takes the PC's power and sleep buttons from the host, and says
"no devices" every 5 seconds while no keyboard is plugged in. Here a keyboard is a device with arrow keys and Enter.
A keyboard is grabbed, so what is typed on it doesn't also reach the login prompt on the screen underneath.

Needs /dev/input in the container (docker-compose.client.yml); the supervisor starts this only when it is there.
"""
import glob
import os
import select
import sys
import time

EV_KEY, KEY_ENTER, KEY_UP, KEY_DOWN = 1, 28, 103, 108      # linux/input-event-codes.h


def is_keyboard(caps):
    """caps: an evdev device's capabilities(). Arrows and Enter: a keyboard or a remote, not a power button."""
    keys = caps.get(EV_KEY, [])
    return KEY_ENTER in keys and KEY_UP in keys and KEY_DOWN in keys


def main():
    try:
        from evdev import InputDevice
        sys.path.insert(0, os.path.join(os.getcwd(), "fs42", "pi"))
        import remote_controller as rc
    except ImportError as e:
        print(f"remote: keyboards can't be used with this image ({e})", flush=True)
        sys.exit(78)                                    # the supervisor's "refused": not started again
    rc.KEY_MAPPINGS.pop("exit", None)                   # Esc would stop the remote for good
    rc.KEY_MAPPINGS.pop("power_stop", None)             # it switches systemd services, which a container doesn't have

    keyboards, others = {}, set()                      # path -> InputDevice; (path, inode) of devices that aren't keyboards
    while True:
        paths = glob.glob("/dev/input/event*")
        for path in paths:
            if path in keyboards:
                continue
            try:
                seen = (path, os.stat(path).st_ino)    # a number can come back as another device after an unplug
                if seen in others:
                    continue
                dev = InputDevice(path)
                if not is_keyboard(dev.capabilities()):
                    dev.close()
                    others.add(seen)
                    continue
                dev.grab()
            except OSError:
                continue
            keyboards[path] = dev
            print(f"remote: listening to {dev.name}", flush=True)
        others = {s for s in others if s[0] in paths}
        if not keyboards:
            time.sleep(2)
            continue
        ready, _, _ = select.select(list(keyboards.values()), [], [], 2)
        for dev in ready:
            try:
                for event in dev.read():
                    rc.handle_key_event(event)
            except OSError:
                print(f"remote: {dev.name} was unplugged", flush=True)
                keyboards.pop(dev.path, None)
                try:
                    dev.close()
                except OSError:
                    pass


if __name__ == "__main__":
    main()
