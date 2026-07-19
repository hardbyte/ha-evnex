# Evnex for Home Assistant

A cloud-polling integration for [Evnex](https://evnex.io) EV chargers. It adds a
device for your Evnex cloud account and one for each charger you can access, and
lets you start or pause charging from Home Assistant.

## What you get

Each charger exposes:

- Network and charger status
- Per-connector status
- Metered power, voltage, frequency, and grid power
- Current session energy, cost, and timing
- A **Charge now** switch, per-connector availability switches, a maximum-current
  slider, and a **Stop charging session** button

## Sign-in

Log in with your Evnex account. Accounts with multi-factor authentication are
supported: you'll be prompted for a code from your authenticator app during
setup. Your password is not stored — if a session ever needs renewing, Home
Assistant asks you to sign in again.

## Install

1. Install **Evnex EV Charger** from HACS.
2. Restart Home Assistant.
3. Add the integration from **Settings → Devices & Services** and sign in.

To try pre-release builds, enable **Show beta versions** for this integration in
HACS.

## Links

- [Documentation and source](https://github.com/hardbyte/ha-evnex)
- [Report an issue](https://github.com/hardbyte/ha-evnex/issues)
- Built on the [python-evnex](https://github.com/hardbyte/python-evnex) library
