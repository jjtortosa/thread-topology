"""Fixtures for Thread Topology tests."""
from __future__ import annotations

import json
import sys
from collections.abc import Generator
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch
import pytest

FIXTURE_DIR = Path(__file__).parent / "fixtures"


# --- Home Assistant stubs --------------------------------------------------
# The integration is tested without Home Assistant installed. Most of HA can be
# a MagicMock, but DataUpdateCoordinator is *subclassed*, and subclassing a
# MagicMock silently turns the subclass into a mock too - every real method
# then resolves to a mock instead of running. Give that one a real class.
#
# conftest is imported before any test module, so the sys.modules.setdefault
# calls in the test modules themselves become no-ops and everyone shares these.


class _StubUpdateFailed(Exception):
    """Stand-in for homeassistant.helpers.update_coordinator.UpdateFailed."""


class _StubDataUpdateCoordinator:
    """Minimal stand-in exposing what the coordinator actually uses."""

    def __init__(self, hass, logger, name=None, update_interval=None, **kwargs):
        self.hass = hass
        self.logger = logger
        self.name = name
        self.update_interval = update_interval
        self.data = None

    def __class_getitem__(cls, item):
        return cls


_update_coordinator_module = MagicMock()
_update_coordinator_module.DataUpdateCoordinator = _StubDataUpdateCoordinator
_update_coordinator_module.UpdateFailed = _StubUpdateFailed

sys.modules.setdefault("homeassistant", MagicMock())
sys.modules.setdefault("homeassistant.core", MagicMock())
sys.modules.setdefault("homeassistant.config_entries", MagicMock())
sys.modules.setdefault("homeassistant.const", MagicMock())
sys.modules.setdefault("homeassistant.helpers", MagicMock())
sys.modules.setdefault("homeassistant.helpers.device_registry", MagicMock())
sys.modules.setdefault(
    "homeassistant.helpers.update_coordinator", _update_coordinator_module
)


@pytest.fixture(scope="session")
def otbr_jsonapi_capture() -> dict:
    """Return a real ot-br-posix JSON:API capture.

    Taken from a live OTBR running the current REST API, with addresses and
    network names anonymized. Structure is untouched - this exists so the
    translation layer is tested against what OTBR actually sends rather than
    what the docs imply it sends.
    """
    with (FIXTURE_DIR / "otbr_jsonapi_capture.json").open(encoding="utf-8") as handle:
        return json.load(handle)


@pytest.fixture
def jsonapi_node_response(otbr_jsonapi_capture: dict) -> dict:
    """Return the camelCase /node response from the live capture."""
    return otbr_jsonapi_capture["node"]


@pytest.fixture
def jsonapi_devices_response(otbr_jsonapi_capture: dict) -> dict:
    """Return the /api/devices collection from the live capture."""
    return otbr_jsonapi_capture["devices"]


@pytest.fixture
def jsonapi_diagnostics_response(otbr_jsonapi_capture: dict) -> list:
    """Return the per-router JSON:API diagnostic items from the live capture."""
    return otbr_jsonapi_capture["diagnostics"]


@pytest.fixture
def mock_otbr_node_response() -> dict:
    """Return mock OTBR node API response."""
    return {
        "BaId": "175B0E832E7217C5C5A630B547C044E4",
        "State": "leader",
        "NumOfRouter": 3,
        "RlocAddress": "fd2a:398d:f276:6b9c:0:ff:fe00:d800",
        "ExtAddress": "1EA5312CFB153F0B",
        "NetworkName": "MyHome1038137341",
        "Rloc16": 55296,
        "LeaderData": {
            "PartitionId": 1055464771,
            "Weighting": 64,
            "DataVersion": 126,
            "StableDataVersion": 159,
            "LeaderRouterId": 54,
        },
        "ExtPanId": "78ACC8F0AE5249C5",
    }


@pytest.fixture
def mock_otbr_diagnostics_response() -> list:
    """Return mock OTBR diagnostics API response."""
    return [
        {
            "ExtAddress": "96308C2577D6EA17",
            "Rloc16": 8192,
            "Mode": {"RxOnWhenIdle": 1, "DeviceType": 1, "NetworkData": 1},
            "Connectivity": {
                "ParentPriority": 0,
                "LinkQuality3": 1,
                "LinkQuality2": 0,
                "LinkQuality1": 0,
                "LeaderCost": 1,
                "IdSequence": 38,
                "ActiveRouters": 3,
                "SedBufferSize": 1280,
                "SedDatagramCount": 1,
            },
            "ChildTable": [
                {"ChildId": 24, "Timeout": 12, "Mode": {"RxOnWhenIdle": 0, "DeviceType": 0, "NetworkData": 0}},
            ],
            "IP6AddressList": ["fd2a:398d:f276:6b9c:0:ff:fe00:2000", "fe80::9430:8c25:77d6:ea17"],
        },
        {
            "ExtAddress": "1EA5312CFB153F0B",
            "Rloc16": 55296,
            "Mode": {"RxOnWhenIdle": 1, "DeviceType": 1, "NetworkData": 1},
            "Connectivity": {
                "ParentPriority": 0,
                "LinkQuality3": 1,
                "LinkQuality2": 0,
                "LinkQuality1": 0,
                "LeaderCost": 0,
                "IdSequence": 39,
                "ActiveRouters": 3,
                "SedBufferSize": 1280,
                "SedDatagramCount": 1,
            },
            "ChildTable": [
                {"ChildId": 9, "Timeout": 12, "Mode": {"RxOnWhenIdle": 0, "DeviceType": 0, "NetworkData": 0}},
            ],
            "IP6AddressList": ["fd2a:398d:f276:6b9c:0:ff:fe00:d800", "fe80::1ca5:312c:fb15:3f0b"],
        },
        {
            "ExtAddress": "A4B3C2D1E0F09876",
            "Rloc16": 16384,
            "Mode": {"RxOnWhenIdle": 1, "DeviceType": 1, "NetworkData": 1},
            "Connectivity": {
                "ParentPriority": 0,
                "LinkQuality3": 1,
                "LinkQuality2": 0,
                "LinkQuality1": 0,
                "LeaderCost": 1,
                "IdSequence": 38,
                "ActiveRouters": 3,
                "SedBufferSize": 1280,
                "SedDatagramCount": 1,
            },
            "ChildTable": [
                {"ChildId": 5, "Timeout": 12, "Mode": {"RxOnWhenIdle": 0, "DeviceType": 0, "NetworkData": 0}},
                {"ChildId": 8, "Timeout": 12, "Mode": {"RxOnWhenIdle": 1, "DeviceType": 0, "NetworkData": 0}},
            ],
            "IP6AddressList": ["fd2a:398d:f276:6b9c:0:ff:fe00:4000", "fe80::a4b3:c2d1:e0f0:9876"],
        },
    ]


@pytest.fixture
def mock_matter_devices() -> list:
    """Return mock Matter devices from device registry."""
    return [
        {
            "name": "Meross MS605",
            "model": "Smart Presence Sensor",
            "manufacturer": "Meross",
            "transport": "thread",
        },
        {
            "name": "Aqara Door Sensor P2",
            "model": "Aqara Door and Window Sensor P2",
            "manufacturer": "Aqara",
            "transport": "thread",
        },
        {
            "name": "Eve Motion",
            "model": "Eve Motion",
            "manufacturer": "Eve Systems",
            "transport": "thread",
        },
        {
            "name": "Nuki Smart Lock",
            "model": "Smart Lock",
            "manufacturer": "Nuki",
            "transport": "wifi",
        },
        {
            "name": "SONOFF Switch",
            "model": "WiFi Smart Switch",
            "manufacturer": "SONOFF",
            "transport": "wifi",
        },
    ]


