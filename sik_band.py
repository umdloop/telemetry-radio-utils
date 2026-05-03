#!/usr/bin/env python3
"""
SiK Radio Sub-Band Configurator + Status Tool
Configures MIN_FREQ/MAX_FREQ for competition sub-bands (section 3.b.v),
and provides a status read of all current parameters on local and remote radios.

Usage:
  python3 sik_band.py <device> band <low|mid|high>   # Configure a sub-band
  python3 sik_band.py <device> status                 # Show local radio status
  python3 sik_band.py <device> status --remote        # Show remote radio status
  python3 sik_band.py <device> status --both          # Show local + remote status
"""

import serial
import time
import sys
import argparse

BANDS = {
    "low":  {"MIN_FREQ": 902000, "MAX_FREQ": 910000, "label": "900-Low  (902–910 MHz)"},
    "mid":  {"MIN_FREQ": 911000, "MAX_FREQ": 919000, "label": "900-Mid  (911–919 MHz)"},
    "high": {"MIN_FREQ": 920000, "MAX_FREQ": 928000, "label": "900-High (920–928 MHz)"},
}

PARAM_INFO = {
    "FORMAT":        ("S0",  "EEPROM format version (read-only)"),
    "SERIAL_SPEED":  ("S1",  "Serial baud rate (57 = 57600)"),
    "AIR_SPEED":     ("S2",  "Over-air data rate (kbps)"),
    "NETID":         ("S3",  "Network ID — must match on both radios (0–255)"),
    "TXPOWER":       ("S4",  "TX power in dBm (1–20, 20 = 100 mW)"),
    "ECC":           ("S5",  "Error correcting code (0=off, 1=on)"),
    "MAVLINK":       ("S6",  "MAVLink framing (0=raw, 1=mavlink, 2=low-latency)"),
    "OPPRESEND":     ("S7",  "Opportunistic resend (0=off, 1=on)"),
    "MIN_FREQ":      ("S8",  "Frequency hop lower bound (kHz)"),
    "MAX_FREQ":      ("S9",  "Frequency hop upper bound (kHz)"),
    "NUM_CHANNELS":  ("S10", "Number of hopping channels (1–50)"),
    "DUTY_CYCLE":    ("S11", "Max TX duty cycle % (100 = unlimited)"),
    "LBT_RSSI":      ("S12", "Listen-before-talk threshold (0=disabled)"),
    "MANCHESTER":    ("S13", "Manchester encoding (0=off, 1=on)"),
    "RTSCTS":        ("S14", "Hardware flow control RTS/CTS (0=off, 1=on)"),
    "MAX_WINDOW":    ("S15", "Max TX window in ms (0–131)"),
}

BAUD        = 57600
CMD_TIMEOUT = 2.0
GUARD_TIME  = 1.1


def read_response(ser: serial.Serial, timeout: float = CMD_TIMEOUT) -> str:
    response = ""
    deadline = time.time() + timeout
    while time.time() < deadline:
        if ser.in_waiting:
            chunk = ser.read(ser.in_waiting).decode(errors="replace")
            response += chunk
            deadline = time.time() + 0.3   # extend deadline while data is arriving
        else:
            time.sleep(0.05)
    return response.strip()


def send_cmd(ser: serial.Serial, cmd: str, expect: str = "OK") -> tuple[bool, str]:
    ser.write((cmd + "\r\n").encode())
    resp = read_response(ser)
    ok = expect.lower() in resp.lower()
    return ok, resp


def enter_command_mode(ser: serial.Serial) -> bool:
    """1 second of silence is required before AND after sending +++."""
    print("  Waiting guard time before +++ ...")
    ser.reset_input_buffer()
    time.sleep(GUARD_TIME)

    print("  Sending +++")
    ser.write(b"+++")       # no newline — intentional per SiK spec
    time.sleep(GUARD_TIME)

    resp = read_response(ser, timeout=1.5)
    if "OK" in resp:
        print("  ✓ Command mode entered.")
        return True

    print("  No OK received, retrying...")
    ser.reset_input_buffer()
    time.sleep(GUARD_TIME)
    ser.write(b"+++")
    time.sleep(GUARD_TIME)
    resp = read_response(ser, timeout=1.5)
    if "OK" in resp:
        print("  ✓ Command mode entered (retry).")
        return True

    print(f"  ✗ Could not enter command mode. Got: {repr(resp)}")
    return False


def parse_params(raw: str) -> dict[str, str]:
    """Parse ATI5/RTI5 output (format: Sn:NAME=value) into a {NAME: value} dict."""
    params = {}
    for line in raw.splitlines():
        line = line.strip()
        if ":" in line and "=" in line:
            try:
                _, rest = line.split(":", 1)
                key, val = rest.split("=", 1)
                params[key.strip()] = val.strip()
            except ValueError:
                pass
    return params


def detect_band(params: dict[str, str]) -> str:
    try:
        min_f = int(params.get("MIN_FREQ", 0))
        max_f = int(params.get("MAX_FREQ", 0))
    except ValueError:
        return "Unknown"

    for name, cfg in BANDS.items():
        if min_f == cfg["MIN_FREQ"] and max_f == cfg["MAX_FREQ"]:
            return f"{name.upper()} — {cfg['label']}"

    return f"Custom ({min_f}–{max_f} kHz)"


def print_status(label: str, params: dict[str, str]) -> None:
    band  = detect_band(params)
    width = 60

    print()
    print("─" * width)
    print(f"  {label}")
    print("─" * width)
    print(f"  {'Parameter':<16} {'Reg':<5} {'Value':<12} Description")
    print(f"  {'─'*14:<16} {'─'*4:<5} {'─'*10:<12} {'─'*28}")

    for name, value in params.items():
        reg, desc = PARAM_INFO.get(name, ("?", "Unknown parameter"))
        marker = " ◄" if name in ("MIN_FREQ", "MAX_FREQ") else ""
        print(f"  {name:<16} {reg:<5} {value:<12} {desc}{marker}")

    min_f = int(params.get("MIN_FREQ", 0))
    max_f = int(params.get("MAX_FREQ", 0))
    bw    = max_f - min_f

    print()
    print(f"  Active band : {band}")
    if bw > 8000:
        print(f"  ⚠  WARNING: Bandwidth is {bw} kHz — exceeds the 8 MHz competition limit!")
    else:
        print(f"  Bandwidth   : {bw} kHz  ✓ (≤ 8 MHz limit)")
    print("─" * width)


def run_status(ser: serial.Serial, show_local: bool, show_remote: bool) -> bool:
    if not enter_command_mode(ser):
        return False

    if show_local:
        print("\n  Reading local radio (ATI5)...")
        ok, resp = send_cmd(ser, "ATI5", expect="S0")
        if not ok:
            print(f"  ✗ ATI5 failed: {repr(resp)}")
        else:
            params = parse_params(resp)
            if params:
                print_status("LOCAL RADIO", params)
            else:
                print(f"  Raw response:\n{resp}")

    if show_remote:
        print("\n  Reading remote radio (RTI5)...")
        ok, resp = send_cmd(ser, "RTI5", expect="S0")
        if not ok:
            print(f"  ✗ RTI5 failed — is the remote radio connected? Got: {repr(resp)}")
        else:
            params = parse_params(resp)
            if params:
                print_status("REMOTE RADIO", params)
            else:
                print(f"  Raw response:\n{resp}")

    send_cmd(ser, "ATO", expect="")
    return True


def configure_band(ser: serial.Serial, band: str) -> bool:
    band = band.lower()
    if band not in BANDS:
        print(f"  ✗ Unknown band '{band}'. Choose from: {', '.join(BANDS)}")
        return False

    cfg = BANDS[band]
    print(f"\n  Target band : {cfg['label']}")
    print(f"  MIN_FREQ    : {cfg['MIN_FREQ']} kHz")
    print(f"  MAX_FREQ    : {cfg['MAX_FREQ']} kHz")

    if not enter_command_mode(ser):
        return False

    print("\n  Current parameters:")
    _, resp = send_cmd(ser, "ATI5", expect="S0")
    params   = parse_params(resp)
    cur_band = detect_band(params)
    print(f"  Current band: {cur_band}")

    if (params.get("MIN_FREQ") == str(cfg["MIN_FREQ"]) and
            params.get("MAX_FREQ") == str(cfg["MAX_FREQ"])):
        print("  ✓ Radio is already configured for this band. No changes needed.")
        send_cmd(ser, "ATO", expect="")
        return True

    steps = [
        (f"ATS8={cfg['MIN_FREQ']}", "Setting MIN_FREQ"),
        (f"ATS9={cfg['MAX_FREQ']}", "Setting MAX_FREQ"),
        ("AT&W",                    "Writing to EEPROM"),
    ]

    for cmd, label in steps:
        print(f"\n  {label}: {cmd}")
        ok, resp = send_cmd(ser, cmd)
        print(f"    → {resp}")
        if not ok:
            print(f"  ✗ Expected OK from '{cmd}'. Aborting.")
            return False

    print("\n  Rebooting radio (ATZ)...")
    ser.write(b"ATZ\r\n")
    time.sleep(2.0)

    print(f"\n  ✓ Radio configured for {cfg['label']}")
    print("  Power-cycle if the remote radio does not reconnect.")
    return True


def main():
    parser = argparse.ArgumentParser(
        description="SiK Radio sub-band configurator and status tool",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python3 sik_band.py /dev/ttyUSB0 status              # local radio status
  python3 sik_band.py /dev/ttyUSB0 status --remote     # remote radio status
  python3 sik_band.py /dev/ttyUSB0 status --both       # both radios
  python3 sik_band.py /dev/ttyUSB0 band low            # set 900-Low (902–910 MHz)
  python3 sik_band.py /dev/ttyUSB0 band mid            # set 900-Mid (911–919 MHz)
  python3 sik_band.py /dev/ttyUSB0 band high           # set 900-High (920–928 MHz)
        """
    )
    parser.add_argument("device", help="Serial device, e.g. /dev/ttyUSB0 or /dev/ttyTELEM")

    subparsers = parser.add_subparsers(dest="command", required=True)

    status_p = subparsers.add_parser("status", help="Read and display radio parameters")
    status_group = status_p.add_mutually_exclusive_group()
    status_group.add_argument("--remote", action="store_true", help="Show remote radio only")
    status_group.add_argument("--both",   action="store_true", help="Show both local and remote radios")

    band_p = subparsers.add_parser("band", help="Configure a competition sub-band")
    band_p.add_argument("band", choices=["low", "mid", "high"], help="Target sub-band")

    args = parser.parse_args()

    print(f"\nOpening {args.device} at {BAUD} baud...")
    try:
        ser = serial.Serial(args.device, BAUD, timeout=1)
    except serial.SerialException as e:
        print(f"ERROR: Cannot open {args.device}: {e}")
        sys.exit(1)

    with ser:
        if args.command == "status":
            show_remote = args.remote or args.both
            show_local  = not args.remote or args.both
            success = run_status(ser, show_local, show_remote)
        else:
            success = configure_band(ser, args.band)

    sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()
