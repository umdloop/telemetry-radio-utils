# MAVLink Telemetry Setup

Pixhawk 6C Mini → USB-serial → Jetson → UDP → QGroundControl

---

## Hardware path

```
Pixhawk 6C Mini TELEM1 (JST-GH 6-pin)
  → USB-serial adapter (FTDI or CP210x)
  → Jetson /dev/ttyUSB0
  → mavlink-router
  → UDP over network
  → QGroundControl on base station
```

---

## Files

| File | Purpose |
|---|---|
| `mavlink-router.conf` | Router config: serial in, UDP out |
| `mavlink-router-pixhawk.service` | Systemd service |
| `serial_test.py` | Serial diagnostic: raw bytes then MAVLink heartbeat |

---

## Jetson setup

### 1. Build and install mavlink-router
```bash
cd mavlink-router
meson setup build && ninja -C build
sudo ninja -C build install
```

### 2. Install config
```bash
sudo mkdir -p /etc/mavlink-router
sudo cp mavlink-router.conf /etc/mavlink-router/main.conf
```

Edit `main.conf` and set `Address` under `[UdpEndpoint qgc]` to the base station IP.

### 3. Serial permissions
```bash
sudo usermod -aG dialout $USER
```
Log out and back in for the group change to take effect.

### 4. Test serial before starting the service
```bash
pip3 install pyserial pymavlink
python3 serial_test.py /dev/ttyUSB0 57600
```

### 5. Install and start the service
```bash
sudo cp mavlink-router-pixhawk.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable mavlink-router-pixhawk
sudo systemctl start mavlink-router-pixhawk
sudo journalctl -u mavlink-router-pixhawk -f
```

---

## QGroundControl (base station)

QGC listens on UDP 14550 by default — no extra config needed when using `Mode = Normal` in the conf.

If you switch to server mode (`UdpEndpoint qgc_server` block):
> QGC → Application Settings → Comm Links → Add → UDP → port 14551 → Jetson IP

---

## Gotchas

- **Baud rate**: default is 57600 on TELEM1. Check `SER_TEL1_BAUD` in QGC params and match it in `mavlink-router.conf`.
- **Device path**: CP210x → `/dev/ttyUSB0`, direct Pixhawk USB → `/dev/ttyACM0`. Update `Device` in the conf and `BindsTo`/`After` in the service file if using ACM.
- **Firewall**: `sudo ufw allow 14550/udp` on the Jetson.
- **Network**: both machines must be on the same subnet, or routing must be configured.
