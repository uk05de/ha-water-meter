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
    CONF_VIRTUAL_METERS,
    CONF_BASE_METER,
    CONF_SUBTRACT_METERS,
)


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
                options={CONF_METERS: [], CONF_VIRTUAL_METERS: []},
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
        virtual_meters = self._entry.options.get(CONF_VIRTUAL_METERS, [])

        menu_options = ["add_meter"]
        if meters:
            menu_options.append("remove_meter")
        if len(meters) >= 2:
            menu_options.append("add_virtual_meter")
        if virtual_meters:
            menu_options.append("remove_virtual_meter")

        return self.async_show_menu(
            step_id="init",
            menu_options=menu_options,
            description_placeholders={
                "count": str(len(meters)),
                "virtual_count": str(len(virtual_meters)),
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
                data={
                    CONF_METERS: meters,
                    CONF_VIRTUAL_METERS: list(
                        self._entry.options.get(CONF_VIRTUAL_METERS, [])
                    ),
                },
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
        virtual_meters = list(self._entry.options.get(CONF_VIRTUAL_METERS, []))
        errors = {}

        if user_input is not None:
            name_to_remove = user_input["meter"]
            slug_to_remove = _make_slug(name_to_remove)

            # Check if any virtual meter references this meter
            referencing = [
                vm[CONF_METER_NAME]
                for vm in virtual_meters
                if vm[CONF_BASE_METER] == slug_to_remove
                or slug_to_remove in vm.get(CONF_SUBTRACT_METERS, [])
            ]
            if referencing:
                errors["base"] = "meter_in_use"
            else:
                meters = [m for m in meters if m[CONF_METER_NAME] != name_to_remove]
                return self.async_create_entry(
                    title="",
                    data={
                        CONF_METERS: meters,
                        CONF_VIRTUAL_METERS: virtual_meters,
                    },
                )

        meter_names = {m[CONF_METER_NAME]: m[CONF_METER_NAME] for m in meters}

        return self.async_show_form(
            step_id="remove_meter",
            data_schema=vol.Schema({
                vol.Required("meter"): vol.In(meter_names),
            }),
            errors=errors,
        )

    async def async_step_add_virtual_meter(self, user_input=None):
        """Add a virtual (calculated) meter."""
        meters = self._entry.options.get(CONF_METERS, [])
        errors = {}

        if user_input is not None:
            base_name = user_input[CONF_BASE_METER]
            subtract_names = user_input.get(CONF_SUBTRACT_METERS, [])

            # Validate: base meter must not be in subtract list
            if base_name in subtract_names:
                errors[CONF_SUBTRACT_METERS] = "base_in_subtract"
            elif not subtract_names:
                errors[CONF_SUBTRACT_METERS] = "no_subtract_meters"
            else:
                virtual_meters = list(
                    self._entry.options.get(CONF_VIRTUAL_METERS, [])
                )
                virtual_meters.append({
                    CONF_METER_NAME: user_input[CONF_METER_NAME],
                    CONF_BASE_METER: _make_slug(base_name),
                    CONF_SUBTRACT_METERS: [_make_slug(n) for n in subtract_names],
                })

                return self.async_create_entry(
                    title="",
                    data={
                        CONF_METERS: list(meters),
                        CONF_VIRTUAL_METERS: virtual_meters,
                    },
                )

        meter_names = [m[CONF_METER_NAME] for m in meters]
        meter_options = [
            selector.SelectOptionDict(value=n, label=n) for n in meter_names
        ]

        return self.async_show_form(
            step_id="add_virtual_meter",
            data_schema=vol.Schema({
                vol.Required(CONF_METER_NAME): str,
                vol.Required(CONF_BASE_METER): selector.SelectSelector(
                    selector.SelectSelectorConfig(
                        options=meter_options,
                        mode=selector.SelectSelectorMode.DROPDOWN,
                    ),
                ),
                vol.Required(CONF_SUBTRACT_METERS): selector.SelectSelector(
                    selector.SelectSelectorConfig(
                        options=meter_options,
                        multiple=True,
                        mode=selector.SelectSelectorMode.DROPDOWN,
                    ),
                ),
            }),
            errors=errors,
        )

    async def async_step_remove_virtual_meter(self, user_input=None):
        """Remove a virtual meter."""
        virtual_meters = list(self._entry.options.get(CONF_VIRTUAL_METERS, []))

        if user_input is not None:
            name_to_remove = user_input["meter"]
            virtual_meters = [
                vm for vm in virtual_meters if vm[CONF_METER_NAME] != name_to_remove
            ]
            return self.async_create_entry(
                title="",
                data={
                    CONF_METERS: list(self._entry.options.get(CONF_METERS, [])),
                    CONF_VIRTUAL_METERS: virtual_meters,
                },
            )

        vm_names = {vm[CONF_METER_NAME]: vm[CONF_METER_NAME] for vm in virtual_meters}

        return self.async_show_form(
            step_id="remove_virtual_meter",
            data_schema=vol.Schema({
                vol.Required("meter"): vol.In(vm_names),
            }),
        )
