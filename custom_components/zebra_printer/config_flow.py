"""UI setup for Zebra network printers."""

from __future__ import annotations

import voluptuous as vol

from homeassistant import config_entries
from homeassistant.const import CONF_HOST, CONF_PORT

from .api import ZebraClient, ZebraConnectionError
from .const import DEFAULT_PORT, DOMAIN


class ZebraPrinterConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Connect to a Zebra printer through its raw TCP port."""

    VERSION = 1

    async def async_step_user(self, user_input=None):
        """Validate the printer before creating an entry."""
        errors = {}
        if user_input is not None:
            host = user_input[CONF_HOST].strip()
            port = user_input.get(CONF_PORT, DEFAULT_PORT)
            try:
                client = ZebraClient(host, port)
                if await client.get("odometer.total_label_count") is None:
                    raise ZebraConnectionError("No Zebra label counter found")
                if await client.get("ezpl.print_method") is None:
                    raise ZebraConnectionError("No Zebra print method found")
                model = await client.get("device.product_name")
            except ZebraConnectionError:
                errors["base"] = "cannot_connect"
            else:
                await self.async_set_unique_id(host)
                self._abort_if_unique_id_configured()
                return self.async_create_entry(
                    title=f"Zebra {model}" if model else "Zebra Printer",
                    data={CONF_HOST: host, CONF_PORT: port},
                )
        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_HOST): str,
                    vol.Optional(CONF_PORT, default=DEFAULT_PORT): vol.All(int, vol.Range(min=1, max=65535)),
                }
            ),
            errors=errors,
        )
