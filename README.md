[![Validation with hassfest](https://github.com/hardbyte/ha-evnex/actions/workflows/combined.yaml/badge.svg)](https://github.com/hardbyte/ha-evnex/actions/workflows/combined.yaml)

# Evnex for Home Assistant

A cloud-polling Home Assistant component to expose Evnex Charger information.

Adds a device for the Evnex cloud account, as well as any chargers you have access to. Each charger exposes a switch to control starting and pausing of charging.


## Install

Available as a default integration in HACS.

[![Open your Home Assistant instance and open a repository inside the Home Assistant Community Store.](https://my.home-assistant.io/badges/hacs_repository.svg)](https://my.home-assistant.io/redirect/hacs_repository/?owner=hardbyte&repository=ha-evnex&category=integration)


## Sensors

Each charger device exposes:

- Network status
- Charger status
- Connector status for each connector
- Metered Power/Voltage and Frequency for each metered connection
- Current session information

## Screenshot

![](.github/sensors.png)

## Development

Uses https://github.com/hardbyte/python-evnex
