"""Config flow for Water Meter."""

import voluptuous as vol

from homeassistant import config_entries
from homeassistant.core import callback
from homeassistant.helpers import selector

from .const import (
    DOMAIN,
    CONF_METERS,
    CONF_METER_NAME,
    CONF_IMPULSE_ENTITY,
    CONF_INITIAL_VALUE,
    CONF_LITERS_PER_IMPULSE,
)


class WaterMeterConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Water Meter."""

    VERSION = 1

    async def async_step_user(self, user_input=None):
        """Handle the initial step — create the integration."""
        if user_input is not None:
            await self.async_set_unique_id("water_meter")
            self._abort_if_unique_id_configured()

            return self.async_create_entry(
                title="Water Meter",
                data={},
                options={CONF_METERS: []},
            )

        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema({}),
            description_placeholders={
                "info": "Wasserzähler-Integration einrichten. Nach der Einrichtung können Zähler über 'Konfigurieren' hinzugefügt werden."
            },
        )

    @staticmethod
    @callback
    def async_get_options_flow(config_entry):
        return WaterMeterOptionsFlow(config_entry)


class WaterMeterOptionsFlow(config_entries.OptionsFlow):
    """Handle options flow — add, remove meters."""

    def __init__(self, config_entry):
        self._entry = config_entry

    async def async_step_init(self, user_input=None):
        """Main options menu."""
        meters = self._entry.options.get(CONF_METERS, [])

        menu_options = ["add_meter"]
        if meters:
            menu_options.append("remove_meter")

        return self.async_show_menu(
            step_id="init",
            menu_options=menu_options,
            description_placeholders={
                "count": str(len(meters)),
            },
        )

    async def async_step_add_meter(self, user_input=None):
        """Add a new water meter."""
        if user_input is not None:
            meters = list(self._entry.options.get(CONF_METERS, []))
            meters.append({
                CONF_METER_NAME: user_input[CONF_METER_NAME],
                CONF_IMPULSE_ENTITY: user_input[CONF_IMPULSE_ENTITY],
                CONF_INITIAL_VALUE: user_input[CONF_INITIAL_VALUE],
                CONF_LITERS_PER_IMPULSE: user_input[CONF_LITERS_PER_IMPULSE],
            })

            return self.async_create_entry(
                title="",
                data={CONF_METERS: meters},
            )

        return self.async_show_form(
            step_id="add_meter",
            data_schema=vol.Schema({
                vol.Required(CONF_METER_NAME): str,
                vol.Required(CONF_IMPULSE_ENTITY): selector.EntitySelector(
                    selector.EntitySelectorConfig(domain="binary_sensor"),
                ),
                vol.Optional(CONF_INITIAL_VALUE, default=0): vol.Coerce(int),
                vol.Optional(CONF_LITERS_PER_IMPULSE, default=1): vol.Coerce(int),
            }),
        )

    async def async_step_remove_meter(self, user_input=None):
        """Remove a meter."""
        meters = list(self._entry.options.get(CONF_METERS, []))

        if user_input is not None:
            name_to_remove = user_input["meter"]
            meters = [m for m in meters if m[CONF_METER_NAME] != name_to_remove]
            return self.async_create_entry(
                title="",
                data={CONF_METERS: meters},
            )

        meter_names = {m[CONF_METER_NAME]: m[CONF_METER_NAME] for m in meters}

        return self.async_show_form(
            step_id="remove_meter",
            data_schema=vol.Schema({
                vol.Required("meter"): vol.In(meter_names),
            }),
        )
