"""Number platform for Water Meter — allows manual correction of counter values."""

import logging

from homeassistant.components.number import NumberEntity, NumberMode
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import UnitOfVolume
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import (
    DOMAIN,
    CONF_METERS,
    CONF_METER_NAME,
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
    """Set up water meter number entities for manual correction."""
    meters = entry.options.get(CONF_METERS, [])

    entities = []
    expected_unique_ids = set()

    for meter_config in meters:
        entity = WaterMeterCorrection(meter_config, entry.entry_id)
        entities.append(entity)
        expected_unique_ids.add(entity.unique_id)

    # Remove stale number entities from the entity registry
    ent_reg = er.async_get(hass)
    for reg_entry in er.async_entries_for_config_entry(ent_reg, entry.entry_id):
        if reg_entry.domain == "number" and reg_entry.unique_id not in expected_unique_ids:
            log.info("Removing stale number entity: %s", reg_entry.entity_id)
            ent_reg.async_remove(reg_entry.entity_id)

    async_add_entities(entities)


class WaterMeterCorrection(NumberEntity):
    """Number entity to manually correct water meter reading."""

    _attr_native_min_value = 0
    _attr_native_max_value = 9999999
    _attr_native_step = 1
    _attr_mode = NumberMode.BOX
    _attr_native_unit_of_measurement = UnitOfVolume.LITERS
    _attr_icon = "mdi:water-sync"
    _attr_entity_category = "config"
    _attr_has_entity_name = True

    def __init__(self, config: dict, entry_id: str):
        self._meter_name = config[CONF_METER_NAME]
        slug = _make_slug(self._meter_name)
        self._slug = slug
        self._attr_unique_id = f"water_meter_{slug}_correction"
        self._attr_device_info = {
            "identifiers": {(DOMAIN, f"water_meter_{slug}")},
            "name": f"Wasserzähler {self._meter_name}",
        }
        self._value = 0

    @property
    def name(self) -> str:
        return f"{self._meter_name} Zählerstand"

    @property
    def native_value(self) -> int:
        return self._value

    async def async_added_to_hass(self) -> None:
        """Sync with counter sensor on startup."""
        # Find the counter sensor and read its value
        counter_entity_id = None
        for state in self.hass.states.async_all("sensor"):
            if state.entity_id.endswith(f"{self._slug}_liters"):
                counter_entity_id = state.entity_id
                break

        if counter_entity_id:
            state = self.hass.states.get(counter_entity_id)
            if state and state.state not in ("unknown", "unavailable"):
                self._value = int(float(state.state))

    async def async_set_native_value(self, value: float) -> None:
        """Set new counter value — find and update the counter sensor."""
        new_value = int(value)
        self._value = new_value

        # Use a more direct approach — fire an event that the sensor listens to
        self.hass.bus.async_fire(
            f"{DOMAIN}_set_value",
            {"slug": self._slug, "value": new_value},
        )
        log.info("Correction: %s set to %d L", self._meter_name, new_value)
