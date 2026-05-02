#!/usr/bin/env python3
"""
serial_test.py - MAVLink serial diagnostic for Pixhawk 6C Mini

Usage: python3 serial_test.py [device] [baud]
       Defaults: /dev/ttyUSB0  57600

Requires: pip3 install pyserial pymavlink
"""

import sys
import time
import serial

DEVICE = sys.argv[1] if len(sys.argv) > 1 else "/dev/ttyUSB0"
BAUD   = int(sys.argv[2]) if len(sys.argv) > 2 else 57600
RAW_TEST_DURATION   = 3
MAVLINK_WAIT        = 15
MAVLINK_START_BYTES = {0xFE, 0xFD}


def test_raw_serial(port: str, baud: int) -> bool:
    print(f"\n[1/2] Raw serial test on {port} @ {baud} baud ...")
    try:
        with serial.Serial(port, baud, timeout=1) as ser:
            ser.reset_input_buffer()
            collected = bytearray()
            deadline = time.time() + RAW_TEST_DURATION
            while time.time() < deadline:
                collected.extend(ser.read(256))

            if not collected:
                print("  FAIL: no bytes received — check cable and baud rate")
                return False

            magic_count = sum(1 for b in collected if b in MAVLINK_START_BYTES)
            print(f"  OK  : {len(collected)} bytes, {magic_count} MAVLink start-byte candidates")
            return True

    except serial.SerialException as exc:
        print(f"  FAIL: could not open port — {exc}")
        print("  check: sudo usermod -aG dialout $USER")
        return False


def test_mavlink_heartbeat(port: str, baud: int) -> bool:
    print(f"\n[2/2] Waiting for HEARTBEAT (timeout {MAVLINK_WAIT}s) ...")
    try:
        from pymavlink import mavutil
    except ImportError:
        print("  SKIP: pip3 install pymavlink")
        return False

    try:
        mav = mavutil.mavlink_connection(f"serial:{port}:{baud}", autoreconnect=False)
    except Exception as exc:
        print(f"  FAIL: {exc}")
        return False

    msg = mav.recv_match(type="HEARTBEAT", blocking=True, timeout=MAVLINK_WAIT)
    if msg is None:
        print("  FAIL: no HEARTBEAT — check Pixhawk is powered and SER_TEL1_BAUD matches")
        return False

    ap_type  = mavutil.mavlink.enums["MAV_AUTOPILOT"].get(
                   msg.autopilot, type("x", (), {"name": str(msg.autopilot)})()).name
    veh_type = mavutil.mavlink.enums["MAV_TYPE"].get(
                   msg.type, type("x", (), {"name": str(msg.type)})()).name
    base_mode = msg.base_mode

    print(f"  OK  : sysid={mav.target_system}  compid={mav.target_component}")
    print(f"        autopilot={ap_type}  vehicle={veh_type}")
    print(f"        base_mode=0x{base_mode:02X}  {'ARMED' if base_mode & 0x80 else 'DISARMED'}")

    print("\n  Sampling stream for 3 seconds ...")
    counts: dict[str, int] = {}
    deadline = time.time() + 3
    while time.time() < deadline:
        m = mav.recv_match(blocking=False)
        if m:
            counts[m.get_type()] = counts.get(m.get_type(), 0) + 1

    for msg_type, count in sorted(counts.items(), key=lambda x: -x[1])[:10]:
        print(f"    {msg_type:<35} {count:>4} msgs")

    return True


def main():
    print("=" * 60)
    print(f"MAVLink serial diagnostic  device={DEVICE}  baud={BAUD}")
    print("=" * 60)

    if not test_raw_serial(DEVICE, BAUD):
        sys.exit(1)
    if not test_mavlink_heartbeat(DEVICE, BAUD):
        sys.exit(1)

    print("\nSerial link healthy. Start router:")
    print("  sudo systemctl start mavlink-router-pixhawk")


if __name__ == "__main__":
    main()
