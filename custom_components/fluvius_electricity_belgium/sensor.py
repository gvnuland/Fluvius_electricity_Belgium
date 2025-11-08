from __future__ import annotations

from homeassistant.components.sensor import SensorEntity, SensorDeviceClass, SensorStateClass
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import ENERGY_KILO_WATT_HOUR
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN, DEFAULT_NAME
from . import FluviusCoordinator

import logging

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback):
    """Set up sensor platform from a config entry. Adds consumption, injection and net sensors."""
    coordinator: FluviusCoordinator = hass.data[DOMAIN][entry.entry_id]
    name = entry.data.get("name", DEFAULT_NAME)
    async_add_entities(
        [
            FluviusConsumptionSensor(coordinator, name),
            FluviusInjectionSensor(coordinator, name),
            FluviusNetSensor(coordinator, name),
        ],
        True,
    )


class FluviusBaseEnergySensor(SensorEntity):
    """Base sensor for Fluvius energy values."""

    _attr_device_class = SensorDeviceClass.ENERGY
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_native_unit_of_measurement = ENERGY_KILO_WATT_HOUR

    def __init__(self, coordinator: FluviusCoordinator, name: str, kind: str):
        """Initialize the sensor."""
        self.coordinator = coordinator
        self.kind = kind  # 'consumption' or 'injection' or 'net'
        self._attr_name = f"{name} {kind.capitalize()}"
        self._attr_unique_id = f"fluvius_{coordinator.meter_id or 'default'}_{kind}"
        self._attr_native_value = None

    @property
    def available(self) -> bool:
        return self.coordinator.last_update_success

    async def async_update(self):
        """Request the coordinator to refresh."""
        await self.coordinator.async_request_refresh()


class FluviusConsumptionSensor(FluviusBaseEnergySensor):
    """Sensor that sums consumption readings (dc == 1)."""

    def __init__(self, coordinator: FluviusCoordinator, name: str):
        super().__init__(coordinator, name, "consumption")

    @property
    def native_value(self):
        data = self.coordinator.data or []
        if not data:
            return None

        total = 0.0
        try:
            for day in data:
                for reading in day.get("v", []):
                    if not isinstance(reading, dict):
                        continue
                    val = reading.get("v")
                    if val is None:
                        continue
                    if reading.get("dc", 1) == 1:
                        total += float(val)
            return round(total, 3)
        except Exception as err:
            _LOGGER.debug("Error parsing Fluvius consumption data: %s", err)
            return None


class FluviusInjectionSensor(FluviusBaseEnergySensor):
    """Sensor that sums injection readings (dc == 2)."""

    def __init__(self, coordinator: FluviusCoordinator, name: str):
        super().__init__(coordinator, name, "injection")

    @property
    def native_value(self):
        data = self.coordinator.data or []
        if not data:
            return None

        total = 0.0
        try:
            for day in data:
                for reading in day.get("v", []):
                    if not isinstance(reading, dict):
                        continue
                    val = reading.get("v")
                    if val is None:
                        continue
                    if reading.get("dc", 0) == 2:
                        total += float(val)
            return round(total, 3)
        except Exception as err:
            _LOGGER.debug("Error parsing Fluvius injection data: %s", err)
            return None


class FluviusNetSensor(FluviusBaseEnergySensor):
    """Sensor providing net consumption (consumption - injection)."""

    def __init__(self, coordinator: FluviusCoordinator, name: str):
        super().__init__(coordinator, name, "net")

    @property
    def native_value(self):
        data = self.coordinator.data or []
        if not data:
            return None

        cons = 0.0
        inj = 0.0
        try:
            for day in data:
                for reading in day.get("v", []):
                    if not isinstance(reading, dict):
                        continue
                    val = reading.get("v")
                    if val is None:
                        continue
                    dc = reading.get("dc", 0)
                    if dc == 1:
                        cons += float(val)
                    elif dc == 2:
                        inj += float(val)
            net = cons - inj
            return round(net, 3)
        except Exception as err:
            _LOGGER.debug("Error parsing Fluvius net data: %s", err)
            return None

