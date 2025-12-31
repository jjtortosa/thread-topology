"""Fixtures for Thread Topology tests."""
from __future__ import annotations

from collections.abc import Generator
from unittest.mock import AsyncMock, MagicMock, patch
import pytest


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


