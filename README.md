<p align="center">
  <picture>
    <source media="(prefers-color-scheme: dark)" srcset="custom_components/ultimate_govee/brand/dark_logo.png">
    <img src="custom_components/ultimate_govee/brand/logo.png" alt="Ultimate Govee" width="480">
  </picture>
</p>

<p align="center">
  <a href="https://github.com/hacs/integration"><img alt="HACS" src="https://img.shields.io/badge/HACS-Custom-41BDF5.svg?style=flat-square"></a>
  <img alt="Home Assistant" src="https://img.shields.io/badge/Home%20Assistant-2026.10%2B-41BDF5.svg?style=flat-square">
  <a href="https://github.com/constructorfleet/hacs-ultimate-govee/releases"><img alt="Release" src="https://img.shields.io/github/v/release/constructorfleet/hacs-ultimate-govee?style=flat-square"></a>
  <img alt="License" src="https://img.shields.io/github/license/constructorfleet/hacs-ultimate-govee?style=flat-square">
</p>

# Ultimate Govee

A Home Assistant custom integration for Govee lights, switches, sensors, fans,
humidifiers, purifiers, dehumidifiers, heaters, ice makers, kettles and more.

The integration controls devices through Govee's cloud (AWS IoT MQTT) and,
when available, directly over the local network. It is the Home Assistant
successor to [`ultimate-govee`](https://github.com/constructorfleet/ultimate-govee)
and reuses the opcode work from that project plus
[`homebridge-govee`](https://github.com/homebridge-plugins/homebridge-govee).

## Features

- Cloud login with automatic token refresh and reauthentication.
- AWS IoT command and status transport with mutual TLS.
- LAN discovery and control for devices that expose the local UDP API.
- Lights with brightness, RGB, colour temperature and effects.
- Switches and multi-gang outlets, including per-gang entities.
- Fans, ceiling fans, purifiers, humidifiers, dehumidifiers and heaters.
- Sensors for temperature, humidity, PM2.5, CO2, air quality, battery,
  filter life and outlet power metering.
- Binary sensors for leaks, presence, contacts, water tanks and ice baskets.
- Ice size, night light, display, child lock and UV controls where supported.
- Optional buttons for Govee tap-to-runs / one-click scenes.
- Per-device opt-out: ignored devices are removed from Home Assistant.
- Diagnostics download with credentials and device identifiers redacted.

## Installation

### HACS

1. Open HACS in Home Assistant.
2. Go to **Integrations**, open the three-dot menu and choose
   **Custom repositories**.
3. Add `https://github.com/constructorfleet/hacs-ultimate-govee` as an
   **Integration**.
4. Install **Ultimate Govee** and restart Home Assistant.

### Manual

Copy `custom_components/ultimate_govee` into your Home Assistant
`config/custom_components` directory and restart.

## Configuration

1. Go to **Settings → Devices & services → Add integration**.
2. Search for **Ultimate Govee**.
3. Enter the email address and password for your Govee Home account.

The integration creates one config entry per Govee account. Use the entry's
**Configure** button to:

- ignore devices, which removes their Home Assistant devices and entities;
- enable or disable light-effect fetching;
- enable optional tap-to-run buttons;
- enable or disable LAN and cloud transports;
- tune the polling and LAN discovery intervals.

## Supported devices

Device support is driven by the reverse-engineered protocol tables in
[`docs/reference`](docs/reference). Devices that are not recognised still get a
power switch, so new models can be used before a dedicated profile is added.

| Family | Examples |
| --- | --- |
| Lights | H6001, H6002, H6054, H6083, H6110, H6159, H6199, H70xx |
| Switches and outlets | H5001, H5080, H5082, H5083, H5086, H5089, H5160 |
| Fans | H7100, H7101, H7102, H7105, H7106, H7107, H7111 |
| Ceiling fans | H1310, H1370, R1310 |
| Humidifiers | H7140, H7141, H7142, H7143, H7160 |
| Purifiers | H7120, H7121, H7122, H7123, H7124, H7126 |
| Dehumidifiers | H7150, H7151, H7152 |
| Heaters | H7130, H7131, H7132, H7133, H7134, H7135, H7137 |
| Ice makers | H7172, H717D, H8120, H8121, H8122 |
| Kettles | H7170, H7171, H7173, H7175 |
| Sensors | H5051, H5054, H5075, H5106, H5140, H5127, H5181 |

## Troubleshooting

- **Cannot connect during setup** — confirm the credentials work in the Govee
  Home app. Govee may reject logins from a new region until the account has
  signed in from the app.
- **Devices are missing** — reload the integration after adding a device to
  your Govee account. Unknown models appear as power switches.
- **LAN control is not detected** — ensure Home Assistant can send and receive
  UDP on ports 4001-4003 and that the device is on the same subnet.
- **Diagnostics** — download them from the integration entry. Account tokens,
  topics, Wi-Fi names and certificate material are redacted.

## Development

This project targets Python 3.14 and Home Assistant 2026.10 or newer.

```bash
uv venv --python 3.14 .venv
uv pip install --python .venv/bin/python -e . --group dev
.venv/bin/ruff check custom_components tests
.venv/bin/ruff format --check custom_components tests
.venv/bin/python -m pytest
```

## Licence

GPL-3.0-or-later. The protocol tables are derived from the GPL-licensed
`ultimate-govee` project.
