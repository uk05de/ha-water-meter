# Water Meter — CLAUDE.md

## Project
- HA Custom Integration for tracking water consumption via impulse sensors
- Repo: uk05de/ha-water-meter
- Replaces fragile YAML setup (counters, automations, template sensors, utility meters)
- HACS compatible

## Architecture
- Custom HA integration with config flow (UI-based, no YAML)
- Listens to binary_sensor impulses (off→on = 1 liter)
- RestoreEntity: counter survives HA restarts
- Number entity for manual correction of counter value
- Communication between number and sensor via HA event bus
- Virtual (calculated) meters: base meter minus subtraction meters, delta-based tracking
- Stale entity cleanup on reload (entity registry)

## Hardware Setup
- Optical sensors on water meters detect rotating disc
- Sensors connected to Shelly 1 (with addon)
- 1 impulse = 1 liter (configurable via liters_per_impulse)
- Two meters: Hauptwasserzähler (main) and Gartenwasserzähler (garden)
- Hauswasser = Hauptwasser - Gartenwasser (calculated via virtual meter)

## Key Files
- custom_components/water_meter/__init__.py — Integration setup
- custom_components/water_meter/config_flow.py — Config flow + options flow (add/remove meters + virtual meters)
- custom_components/water_meter/sensor.py — Counter sensor (L) + cubic meter sensor (m³), impulse listener, virtual meters
- custom_components/water_meter/number.py — Manual correction number entity
- custom_components/water_meter/const.py — Constants
- custom_components/water_meter/strings.json — German UI strings
- custom_components/water_meter/manifest.json — Integration metadata (version here!)

## Per Meter Entities (physical)
- Sensor: {name} (L) — total_increasing, device_class water, RestoreEntity
- Sensor: {name} (m³) — total_increasing, derived from liter counter
- Number: {name} Zählerstand — for manual correction, entity_category config

## Per Virtual Meter Entities
- Sensor: {name} (L) — total_increasing, device_class water, RestoreEntity, delta-based
- Sensor: {name} (m³) — total_increasing, derived from virtual liter counter
- No correction number entity (correct source meters instead)

## Config Flow
- Step 1: Create integration (no parameters needed)
- Options flow: add/remove meters, add/remove virtual meters
- Per meter: name, impulse binary_sensor (entity selector), initial value (L), liters per impulse
- Per virtual meter: name, base_meter (select), subtract_meters (multi-select)
- Removing a physical meter referenced by a virtual meter is blocked (error shown)

## Virtual Meter — Delta-Based Tracking
- Owns its own _total_liters, persisted via RestoreEntity
- On restart: restores last value, records current source values as baseline (no delta)
- On source change: computes delta from last seen value, applies +/- to own counter
- Prevents jumps/peaks/resets on HA restart
- state_class: total_increasing is correct (value never decreases in normal operation)

## Known Limitation
- Impulses during HA downtime are lost (Shelly sends ON/OFF, but HA isn't listening)
- This cannot be solved without firmware-level counting on the Shelly
- The counter value can be manually corrected via the number entity if drift is noticed

## Important Notes
- Version is in manifest.json (custom integration, not addon)
- state_class: total_increasing — HA energy dashboard compatible
- The correction number entity fires a bus event (water_meter_set_value) that the sensor listens to
- Utility meters for daily/weekly/monthly should be created by user via HA UI helpers
- Slug generation: lowercase, spaces→_, ä→ae, ö→oe, ü→ue, ß→ss
- _make_slug helper is defined in config_flow.py, sensor.py, and number.py (same logic)
