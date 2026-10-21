"""UI setup for Zebra network printers."""

from __future__ import annotations

import asyncio

import voluptuous as vol

from homeassistant import config_entries
from homeassistant.const import CONF_HOST, CONF_PORT

from .api import ZebraClient, ZebraConnectionError
from .const import DEFAULT_PORT, DOMAIN
from .discovery import async_discover_printers

_MANUAL_ENTRY = "__manual__"


class ZebraPrinterConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Connect to a Zebra printer through its raw TCP port."""

    VERSION = 1

    async def async_step_user(self, user_input=None):
        """Discover Zebra printers, with a manual setup fallback."""
        if user_input is None and not getattr(self, "_discovery_attempted", False):
            self._discovery_attempted = True
            discovered_hosts = await async_discover_printers(self.hass)
            configured_hosts = {
                str(entry.data.get(CONF_HOST, "")).casefold()
                for entry in self._async_current_entries()
            }
            new_discovered_hosts = [
                host
                for host in discovered_hosts
                if host.casefold() not in configured_hosts
            ]
            models = await asyncio.gather(
                *(self._async_discovered_model(host) for host in new_discovered_hosts)
            )
            self._discovered_hosts = {
                host: model
                for host, model in zip(new_discovered_hosts, models)
                if model is not None
            }
            if self._discovered_hosts:
                return await self.async_step_discovered()
            if not discovered_hosts:
                discovery_error = "no_printers_found"
            elif not new_discovered_hosts:
                discovery_error = "all_printers_configured"
            else:
                discovery_error = "no_compatible_printers_found"
            return self.async_show_form(
                step_id="user",
                data_schema=self._manual_schema(),
                errors={"base": discovery_error},
            )

        if user_input is None:
            return self.async_show_form(
                step_id="user",
                data_schema=self._manual_schema(),
            )

        return await self._async_create_entry(
            user_input[CONF_HOST].strip(),
            user_input.get(CONF_PORT, DEFAULT_PORT),
            step_id="user",
        )

    async def async_step_discovered(self, user_input=None):
        """Add a selected discovered printer or use manual setup."""
        if not getattr(self, "_discovered_hosts", None):
            return await self.async_step_user()

        if user_input is not None:
            host = user_input[CONF_HOST]
            if host == _MANUAL_ENTRY:
                return self.async_show_form(
                    step_id="user",
                    data_schema=self._manual_schema(),
                )
            return await self._async_create_entry(
                host,
                DEFAULT_PORT,
                step_id="discovered",
            )

        return self.async_show_form(
            step_id="discovered",
            data_schema=self._discovered_schema(),
        )

    @staticmethod
    def _manual_schema() -> vol.Schema:
        """Return the manual host and port form."""
        return vol.Schema(
            {
                vol.Required(CONF_HOST): str,
                vol.Optional(CONF_PORT, default=DEFAULT_PORT): vol.All(
                    int, vol.Range(min=1, max=65535)
                ),
            }
        )

    def _discovered_schema(self) -> vol.Schema:
        """Return the discovered printer selector."""
        options = {
            host: f"{model} ({host})"
            for host, model in sorted(self._discovered_hosts.items())
        }
        options[_MANUAL_ENTRY] = "Enter host manually"
        return vol.Schema({vol.Required(CONF_HOST): vol.In(options)})

    async def _async_discovered_model(self, host: str) -> str | None:
        """Return the model when a discovered host passes the SGD checks."""
        try:
            return await self._async_get_printer_model(host, DEFAULT_PORT)
        except ZebraConnectionError:
            return None

    async def _async_get_printer_model(self, host: str, port: int) -> str:
        """Verify a Zebra printer and return its reported model."""
        client = ZebraClient(host, port)
        if await client.get("odometer.total_label_count") is None:
            raise ZebraConnectionError("No Zebra label counter found")
        if await client.get("ezpl.print_method") is None:
            raise ZebraConnectionError("No Zebra print method found")
        return await client.get("device.product_name") or "Zebra Printer"

    async def _async_create_entry(self, host: str, port: int, *, step_id: str):
        """Validate a printer and create its config entry."""
        errors = {}
        try:
            model = await self._async_get_printer_model(host, port)
        except ZebraConnectionError:
            errors["base"] = "cannot_connect"
            schema = (
                self._discovered_schema()
                if step_id == "discovered"
                else self._manual_schema()
            )
            return self.async_show_form(
                step_id=step_id,
                data_schema=schema,
                errors=errors,
            )

        await self.async_set_unique_id(host)
        self._abort_if_unique_id_configured()
        return self.async_create_entry(
            title=f"Zebra {model}" if model != "Zebra Printer" else model,
            data={CONF_HOST: host, CONF_PORT: port},
        )
