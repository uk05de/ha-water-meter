"""Sensor platform for Water Meter."""

import logging

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorStateClass,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import UnitOfVolume
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import device_registry as dr, entity_registry as er
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.event import async_track_state_change_event
from homeassistant.helpers.restore_state import RestoreEntity

from .const import (
    DOMAIN,
    CONF_METERS,
    CONF_METER_NAME,
    CONF_IMPULSE_ENTITY,
    CONF_INITIAL_VALUE,
    CONF_LITERS_PER_IMPULSE,
    CONF_VIRTUAL_METERS,
    CONF_BASE_METER,
    CONF_SUBTRACT_METERS,
)

log = logging.getLogger(__name__)


def _make_slug(name: str) -> str:
    """Generate slug from meter name."""
    return (
        name.lower()
        .replace(" ", "_")
        .replace("ä", "ae")
        .replace("ö", "oe")
        .replace("ü", "ue")
        .replace("ß", "ss")
    )


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up water meter sensors from a config entry."""
    meters = entry.options.get(CONF_METERS, [])
    virtual_meters = entry.options.get(CONF_VIRTUAL_METERS, [])

    entities = []
    expected_unique_ids = set()

    # Physical meters
    for meter_config in meters:
        counter = WaterMeterCounter(hass, meter_config, entry.entry_id)
        entities.append(counter)
        expected_unique_ids.add(counter.unique_id)

        cubic = WaterMeterCubic(counter)
        entities.append(cubic)
        expected_unique_ids.add(cubic.unique_id)

    # Virtual meters
    for vm_config in virtual_meters:
        vcounter = WaterMeterVirtualCounter(hass, vm_config, entry.entry_id)
        entities.append(vcounter)
        expected_unique_ids.add(vcounter.unique_id)

        vcubic = WaterMeterVirtualCubic(vcounter)
        entities.append(vcubic)
        expected_unique_ids.add(vcubic.unique_id)

    # Remove stale sensor entities from the entity registry
    ent_reg = er.async_get(hass)
    for reg_entry in er.async_entries_for_config_entry(ent_reg, entry.entry_id):
        if reg_entry.domain == "sensor" and reg_entry.unique_id not in expected_unique_ids:
            log.info("Removing stale sensor entity: %s", reg_entry.entity_id)
            ent_reg.async_remove(reg_entry.entity_id)

    # Remove stale devices from the device registry
    expected_device_ids = set()
    for meter_config in meters:
        slug = _make_slug(meter_config[CONF_METER_NAME])
        expected_device_ids.add((DOMAIN, f"water_meter_{slug}"))
    for vm_config in virtual_meters:
        slug = _make_slug(vm_config[CONF_METER_NAME])
        expected_device_ids.add((DOMAIN, f"water_meter_{slug}"))

    dev_reg = dr.async_get(hass)
    for device in dr.async_entries_for_config_entry(dev_reg, entry.entry_id):
        if not device.identifiers & expected_device_ids:
            log.info("Removing stale device: %s", device.name)
            dev_reg.async_remove_device(device.id)

    async_add_entities(entities)


class WaterMeterCounter(SensorEntity, RestoreEntity):
    """Water meter counter in liters — listens to impulse binary sensor."""

    _attr_device_class = SensorDeviceClass.WATER
    _attr_state_class = SensorStateClass.TOTAL_INCREASING
    _attr_native_unit_of_measurement = UnitOfVolume.LITERS
    _attr_has_entity_name = True
    _attr_icon = "mdi:water-pump"

    def __init__(self, hass: HomeAssistant, config: dict, entry_id: str):
        self._hass = hass
        self._meter_name = config[CONF_METER_NAME]
        self._impulse_entity = config[CONF_IMPULSE_ENTITY]
        self._liters_per_impulse = config.get(CONF_LITERS_PER_IMPULSE, 1)
        self._initial_value = config.get(CONF_INITIAL_VALUE, 0)
        self._total_liters = 0
        self._unsub = None

        slug = _make_slug(self._meter_name)
        self.slug = slug
        self._attr_unique_id = f"water_meter_{slug}_liters"
        self._attr_device_info = {
            "identifiers": {(DOMAIN, f"water_meter_{slug}")},
            "name": f"Wasserzähler {self._meter_name}",
            "manufacturer": "Shelly",
            "model": "Impulszähler",
        }

    @property
    def name(self) -> str:
        return f"{self._meter_name} (L)"

    @property
    def native_value(self) -> int:
        return self._total_liters

    async def async_added_to_hass(self) -> None:
        """Restore state and start listening for impulses."""
        await super().async_added_to_hass()

        # Restore previous value
        last_state = await self.async_get_last_state()
        if last_state is not None and last_state.state not in ("unknown", "unavailable"):
            self._total_liters = int(float(last_state.state))
            log.info("Restored %s: %d L", self._meter_name, self._total_liters)
        elif self._initial_value > 0:
            self._total_liters = self._initial_value
            log.info("Initialized %s: %d L (initial value)", self._meter_name, self._total_liters)

        # Listen for impulse state changes
        self._unsub = async_track_state_change_event(
            self._hass,
            [self._impulse_entity],
            self._handle_impulse,
        )

        # Listen for manual correction events
        self._unsub_correction = self._hass.bus.async_listen(
            f"{DOMAIN}_set_value",
            self._handle_correction,
        )

        log.info("Listening for impulses on %s", self._impulse_entity)

    async def async_will_remove_from_hass(self) -> None:
        """Stop listening."""
        if self._unsub:
            self._unsub()
            self._unsub = None
        if self._unsub_correction:
            self._unsub_correction()
            self._unsub_correction = None

    @callback
    def _handle_impulse(self, event) -> None:
        """Handle impulse from binary sensor (off → on = 1 liter)."""
        new_state = event.data.get("new_state")
        old_state = event.data.get("old_state")

        if old_state is None or new_state is None:
            return

        # Only count off → on transitions
        if old_state.state == "off" and new_state.state == "on":
            self._total_liters += self._liters_per_impulse
            self.async_write_ha_state()
            log.debug("%s: impulse → %d L", self._meter_name, self._total_liters)

    @callback
    def _handle_correction(self, event) -> None:
        """Handle manual correction from number entity."""
        if event.data.get("slug") == self.slug:
            new_value = event.data.get("value", 0)
            self._total_liters = max(0, new_value)
            self.async_write_ha_state()
            log.info("%s: manually corrected to %d L", self._meter_name, self._total_liters)


class WaterMeterCubic(SensorEntity):
    """Water meter in cubic meters — derived from liter counter."""

    _attr_device_class = SensorDeviceClass.WATER
    _attr_state_class = SensorStateClass.TOTAL_INCREASING
    _attr_native_unit_of_measurement = UnitOfVolume.CUBIC_METERS
    _attr_has_entity_name = True
    _attr_icon = "mdi:water-pump"

    def __init__(self, counter: WaterMeterCounter):
        self._counter = counter
        self._attr_unique_id = f"water_meter_{counter.slug}_m3"
        self._attr_device_info = counter._attr_device_info

    @property
    def name(self) -> str:
        return f"{self._counter._meter_name} (m³)"

    @property
    def native_value(self) -> float:
        return round(self._counter._total_liters / 1000, 3)

    @property
    def should_poll(self) -> bool:
        return False

    async def async_added_to_hass(self) -> None:
        """Track counter updates."""
        @callback
        def _update(event) -> None:
            self.async_write_ha_state()

        self.async_on_remove(
            async_track_state_change_event(
                self.hass,
                [self._counter.entity_id],
                _update,
            )
        )


class WaterMeterVirtualCounter(SensorEntity, RestoreEntity):
    """Virtual water meter — calculates base minus subtractors using delta tracking."""

    _attr_device_class = SensorDeviceClass.WATER
    _attr_state_class = SensorStateClass.TOTAL_INCREASING
    _attr_native_unit_of_measurement = UnitOfVolume.LITERS
    _attr_has_entity_name = True
    _attr_icon = "mdi:water-pump"

    def __init__(self, hass: HomeAssistant, config: dict, entry_id: str):
        self._hass = hass
        self._meter_name = config[CONF_METER_NAME]
        self._base_slug = config[CONF_BASE_METER]
        self._subtract_slugs = config.get(CONF_SUBTRACT_METERS, [])
        self._total_liters = 0
        self._unsubs = []

        # Map source entity_id → last seen liter value (None = not yet seen)
        self._last_seen: dict[str, int | None] = {}
        # Map source entity_id → "base" or "subtract"
        self._source_roles: dict[str, str] = {}

        slug = _make_slug(self._meter_name)
        self.slug = slug
        self._attr_unique_id = f"water_meter_{slug}_liters"
        self._attr_device_info = {
            "identifiers": {(DOMAIN, f"water_meter_{slug}")},
            "name": f"Wasserzähler {self._meter_name}",
            "manufacturer": "Water Meter",
            "model": "Berechneter Zähler",
        }

    @property
    def name(self) -> str:
        return f"{self._meter_name} (L)"

    @property
    def native_value(self) -> int:
        return self._total_liters

    def _find_entity_id_for_slug(self, slug: str) -> str | None:
        """Find the entity_id of a physical counter sensor by its slug."""
        target_unique_id = f"water_meter_{slug}_liters"
        ent_reg = er.async_get(self._hass)
        return ent_reg.async_get_entity_id("sensor", DOMAIN, target_unique_id)

    async def async_added_to_hass(self) -> None:
        """Restore state and start listening to source meters."""
        await super().async_added_to_hass()

        # Restore previous value
        last_state = await self.async_get_last_state()
        if last_state is not None and last_state.state not in ("unknown", "unavailable"):
            self._total_liters = int(float(last_state.state))
            log.info("Restored virtual %s: %d L", self._meter_name, self._total_liters)

        # Find source entity IDs and set up tracking
        all_source_entities = []

        base_entity_id = self._find_entity_id_for_slug(self._base_slug)
        if base_entity_id:
            self._source_roles[base_entity_id] = "base"
            self._last_seen[base_entity_id] = None
            all_source_entities.append(base_entity_id)
            log.info("Virtual %s: base → %s", self._meter_name, base_entity_id)
        else:
            log.warning("Virtual %s: base meter '%s' not found", self._meter_name, self._base_slug)

        for sub_slug in self._subtract_slugs:
            sub_entity_id = self._find_entity_id_for_slug(sub_slug)
            if sub_entity_id:
                self._source_roles[sub_entity_id] = "subtract"
                self._last_seen[sub_entity_id] = None
                all_source_entities.append(sub_entity_id)
                log.info("Virtual %s: subtract → %s", self._meter_name, sub_entity_id)
            else:
                log.warning("Virtual %s: subtract meter '%s' not found", self._meter_name, sub_slug)

        if all_source_entities:
            unsub = async_track_state_change_event(
                self._hass,
                all_source_entities,
                self._handle_source_change,
            )
            self._unsubs.append(unsub)

    async def async_will_remove_from_hass(self) -> None:
        """Stop listening."""
        for unsub in self._unsubs:
            unsub()
        self._unsubs.clear()

    @callback
    def _handle_source_change(self, event) -> None:
        """Handle state change of a source meter — apply delta."""
        new_state = event.data.get("new_state")
        if new_state is None or new_state.state in ("unknown", "unavailable"):
            return

        entity_id = event.data.get("entity_id")
        if entity_id not in self._source_roles:
            return

        try:
            new_value = int(float(new_state.state))
        except (ValueError, TypeError):
            return

        last = self._last_seen.get(entity_id)

        if last is None:
            # First time seeing this source after restart — just record baseline
            self._last_seen[entity_id] = new_value
            log.debug("Virtual %s: baseline %s = %d L", self._meter_name, entity_id, new_value)
            return

        delta = new_value - last
        self._last_seen[entity_id] = new_value

        if delta == 0:
            return

        role = self._source_roles[entity_id]
        if role == "base":
            self._total_liters += delta
        else:
            self._total_liters -= delta

        self._total_liters = max(0, self._total_liters)
        self.async_write_ha_state()
        log.debug(
            "Virtual %s: %s %s delta=%+d → %d L",
            self._meter_name, role, entity_id, delta, self._total_liters,
        )


class WaterMeterVirtualCubic(SensorEntity):
    """Virtual water meter in cubic meters — derived from virtual liter counter."""

    _attr_device_class = SensorDeviceClass.WATER
    _attr_state_class = SensorStateClass.TOTAL_INCREASING
    _attr_native_unit_of_measurement = UnitOfVolume.CUBIC_METERS
    _attr_has_entity_name = True
    _attr_icon = "mdi:water-pump"

    def __init__(self, counter: WaterMeterVirtualCounter):
        self._counter = counter
        self._attr_unique_id = f"water_meter_{counter.slug}_m3"
        self._attr_device_info = counter._attr_device_info

    @property
    def name(self) -> str:
        return f"{self._counter._meter_name} (m³)"

    @property
    def native_value(self) -> float:
        return round(self._counter._total_liters / 1000, 3)

    @property
    def should_poll(self) -> bool:
        return False

    async def async_added_to_hass(self) -> None:
        """Track counter updates."""
        @callback
        def _update(event) -> None:
            self.async_write_ha_state()

        self.async_on_remove(
            async_track_state_change_event(
                self.hass,
                [self._counter.entity_id],
                _update,
            )
        )
