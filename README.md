# w3mo

`w3mo` is a local-first web dashboard for Belkin WeMo switches and dimmers. It runs on your own Ubuntu box, discovers devices on your LAN with `pywemo`, lets you toggle power and dimmer brightness from a browser, and adds local scheduling without any cloud dependency.

## Features

- FastAPI backend with a responsive single-page dashboard
- LAN discovery with `pywemo`
- Manual device enrollment by IP address or hostname when SSDP discovery misses a device
- Per-device controls for on, off, refresh, and dimmer brightness
- Device metadata display including IP, model, firmware, MAC, and Insight metrics when available
- Local schedule engine for:
  - countdown timers
  - daily schedules
  - weekday-specific schedules
  - optional auto-off durations
  - dimmer brightness schedules
- Live countdowns and a next-24-hours timeline
- Defensive error handling for offline devices, partial discovery, reconnect attempts, and command failures

## Project Layout

```text
w3mo/
├── app/
│   ├── api/
│   ├── services/
│   ├── static/
│   ├── templates/
│   ├── config.py
│   └── main.py
├── data/
├── requirements.txt
└── README.md
```

## Requirements

- Ubuntu 22.04+ or another modern Linux distribution
- Python 3.11+ recommended
- A LAN where your WeMo devices are reachable from the machine running `w3mo`

Python 3.13 may work, but if you hit dependency issues, use Python 3.11 or 3.12 first.

## Install

```bash
git clone <YOUR_REPO_URL> w3mo
cd w3mo
python3 -m venv .venv
source .venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt
```

## Run

```bash
cd w3mo
source .venv/bin/activate
uvicorn app.main:app --host 0.0.0.0 --port 8000
```

Open the dashboard in a browser:

- Local machine: `http://127.0.0.1:8000`
- Another device on your LAN: `http://YOUR_SERVER_IP:8000`

## How To Use

When the app starts, it can automatically scan the LAN for WeMo devices. The dashboard then shows each discovered switch or dimmer as a card with its state, health, metadata, and available controls.

### Device discovery

- Click `Refresh Devices` to run discovery again
- Click `Refresh States` to poll current state from already-known devices
- If a device is not discovered automatically, add its IP address or hostname in the `Manual Devices` section

Manual devices are stored locally in `data/manual_addresses.json` and reused on future discovery runs.

### Device control

- `Turn On` sends an on command
- `Turn Off` sends an off command
- `Refresh` polls the current device state
- Dimmers show a brightness slider and `Apply Brightness`

Brightness controls are only shown for devices that support dimming through `pywemo`.

### Scheduler

The scheduler is local to this app and runs while the FastAPI process is running.

Use `Run Now For Duration` for timer-style actions such as:

- turning on a fan now for 30 minutes
- turning a switch off after 10 minutes
- setting a dimmer brightness now, then turning it off later

Use `Daily At Time` for recurring automation such as:

- turn driveway lights on at 7:30 PM
- set a dimmer to 40% at 10:00 PM
- turn a fan on weekdays at noon for 20 minutes

Scheduler notes:

- `Turn Off` daily schedules do not use auto-off duration
- brightness scheduling only appears when the selected device is a dimmer
- active timers show live countdowns in the scheduler list
- the `Next 24 Hours` panel shows upcoming scheduled runs and auto-off events

Schedules are stored locally in `data/schedules.json`.

## Configuration

The app uses environment variables for configuration.

### Supported environment variables

- `WEMO_APP_TITLE`
- `WEMO_HOST`
- `WEMO_PORT`
- `WEMO_LOG_LEVEL`
- `WEMO_STARTUP_DISCOVERY`
- `WEMO_DEVICE_POLL_SECONDS`
- `WEMO_DISCOVERY_TIMEOUT`
- `WEMO_DISCOVERY_MAX_ENTRIES`
- `WEMO_MANUAL_ADDRESSES`

Example:

```bash
export WEMO_APP_TITLE="Driveway and Fan Control"
export WEMO_STARTUP_DISCOVERY=true
export WEMO_DEVICE_POLL_SECONDS=20
uvicorn app.main:app --host 0.0.0.0 --port 8000
```

## Network And Firewall Notes

WeMo discovery depends on SSDP/UPnP multicast on your local network. If discovery is unreliable:

- make sure the server and devices are on the same LAN or VLAN
- allow multicast and SSDP traffic on your network gear
- avoid client isolation on Wi-Fi networks
- add devices manually by IP or hostname when SSDP is blocked or inconsistent

If you access the dashboard from another machine, make sure Ubuntu allows inbound TCP traffic on the port you choose, usually `8000`.

## Troubleshooting

### No devices found

- confirm the WeMo device is powered on and on the same network
- try `Refresh Devices`
- add the device manually by IP
- check that multicast discovery is not blocked by your router or firewall

### Device shows offline or commands fail

- verify the IP address has not changed
- use `Refresh States`
- run discovery again
- some devices need reconnect attempts after sleeping or brief network interruptions

### Schedules are not running

- the `uvicorn` process must still be running
- verify the server time and timezone are correct
- confirm the device is still reachable

### Brightness controls do not appear

- only WeMo dimmer models expose brightness through `pywemo`
- regular on/off switches will not show brightness controls in the device card or scheduler editor

## Run On Boot With systemd

For a machine that should keep schedules alive across reboots, run the app under `systemd`.

Example service file:

```ini
[Unit]
Description=w3mo WeMo Dashboard
After=network-online.target
Wants=network-online.target

[Service]
User=<USER>
WorkingDirectory=<APP_DIR>
Environment="WEMO_HOST=0.0.0.0"
Environment="WEMO_PORT=8000"
ExecStart=<APP_DIR>/.venv/bin/uvicorn app.main:app --host 0.0.0.0 --port 8000
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
```

Then:

```bash
sudo cp w3mo.service.example /etc/systemd/system/w3mo.service
sudo systemctl daemon-reload
sudo systemctl enable --now w3mo
sudo systemctl status w3mo
```

## Assumptions And Limits

- The app targets WeMo switch-style devices and dimmers supported by `pywemo`
- The scheduler is local and not pushed into the device itself
- Schedules only execute while the app process is running
- SSDP discovery can be unreliable on some networks, so manual addressing is included intentionally
- The app uses polling and explicit refresh instead of relying on local event subscription callbacks

## Source Of Truth

This project is built around the `pywemo` API and behavior documented here:

https://pywemo.github.io/pywemo/pywemo.html
