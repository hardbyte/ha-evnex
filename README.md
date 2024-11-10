[![Validation with hassfest](https://github.com/hardbyte/ha-evnex/actions/workflows/combined.yaml/badge.svg)](https://github.com/hardbyte/ha-evnex/actions/workflows/combined.yaml)

# Evnex for Home Assistant

A cloud-polling Home Assistant component to expose Evnex Charger information.

Adds a device for the Evnex cloud account, as well as any chargers you have access to. Each charger exposes a switch to control starting and pausing of charging.


## Install

Available as an integration in HACS.

[![Open your Home Assistant instance and open a repository inside the Home Assistant Community Store.](https://my.home-assistant.io/badges/hacs_repository.svg)](https://my.home-assistant.io/redirect/hacs_repository/?owner=hardbyte&repository=ha-evnex&category=integration)


Since version `0.6.0` this integration requires Pydantic >2.0, some versions of Home Assistant may not have this version 
available, you may need to install it manually e.g. with `pip install -U pydantic`.


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

