"""Indoor temperature/humidity. The frontend never knows which provider is active."""
from __future__ import annotations

import logging
import random
from abc import ABC, abstractmethod
from dataclasses import dataclass

log = logging.getLogger(__name__)


@dataclass
class SensorReading:
    temperature_c: float
    humidity_pct: float
    available: bool = True


class SensorProvider(ABC):
    @abstractmethod
    def read(self) -> SensorReading:
        """Return the latest reading. Raise if the sensor is unreachable."""


class MockSensorProvider(SensorProvider):
    """Slowly drifting fake values so the UI looks alive during development."""

    def __init__(self):
        self._temp = 22.4
        self._hum = 47.0

    def read(self) -> SensorReading:
        self._temp = min(25.0, max(20.0, self._temp + random.uniform(-0.1, 0.1)))
        self._hum = min(60.0, max(35.0, self._hum + random.uniform(-0.3, 0.3)))
        return SensorReading(round(self._temp, 1), round(self._hum))


def get_sensor_provider(settings) -> SensorProvider:
    if settings.hardware_mode == "raspberrypi":
        # Phase 6 will return BME280SensorProvider here, with imports done lazily
        # so this file still loads on a Mac.
        log.warning("BME280 provider not implemented yet, using mock sensor")
    return MockSensorProvider()
