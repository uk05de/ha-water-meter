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
)

log = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up water meter sensors from a config entry."""
    meters = entry.options.get(CONF_METERS, [])

    entities = []
    for meter_config in meters:
        counter = WaterMeterCounter(hass, meter_config, entry.entry_id)
        entities.append(counter)
        entities.append(WaterMeterCubic(counter))

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

        slug = self._meter_name.lower().replace(" ", "_").replace("ä", "ae").replace("ö", "oe").replace("ü", "ue").replace("ß", "ss")
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

    @callback
    def async_write_ha_state(self) -> None:
        """Update when counter updates."""
        super().async_write_ha_state()

    async def async_added_to_hass(self) -> None:
        """Track counter updates."""
        self.async_on_remove(
            async_track_state_change_event(
                self.hass,
                [self._counter.entity_id],
                lambda event: self.async_write_ha_state(),
            )
        )
