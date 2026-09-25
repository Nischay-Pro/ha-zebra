"""Common Zebra device metadata."""

from __future__ import annotations

from homeassistant.config_entries import ConfigEntry
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from . import ZebraCoordinator
from .const import DOMAIN


class ZebraEntity(CoordinatorEntity[ZebraCoordinator]):
    """An entity belonging to one Zebra printer."""

    _attr_has_entity_name = True

    def __init__(self, coordinator: ZebraCoordinator, entry: ConfigEntry, key: str) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{entry.entry_id}_{key}"
        model = str(coordinator.data.get("model") or "Printer")
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry.data["host"])},
            name=f"Zebra {model}",
            manufacturer="Zebra Technologies",
            model=model,
            sw_version=str(coordinator.data.get("firmware") or ""),
            configuration_url=f"http://{entry.data['host']}",
        )
