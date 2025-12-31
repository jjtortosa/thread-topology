"""Tests for Thread Topology sensors."""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch
import pytest

from custom_components.thread_topology.sensor import (
    ThreadNetworkSensor,
    ThreadTopologyMapSensor,
    ThreadNodeSensor,
)
from custom_components.thread_topology.coordinator import ThreadTopologyCoordinator
from custom_components.thread_topology.const import DEFAULT_OTBR_URL


@pytest.fixture
def mock_coordinator_data():
    """Return mock coordinator data."""
    return {
        "network_name": "MyHome1038137341",
        "state": "leader",
        "leader_address": "1EA5312CFB153F0B",
        "router_count": 2,
        "total_devices": 4,
        "nodes": {
            "1EA5312CFB153F0B": {
                "ext_address": "1EA5312CFB153F0B",
                "rloc16": 55296,
                "role": "leader",
                "name": "SkyConnect (OTBR)",
                "manufacturer": "Nabu Casa",
                "device_type": "border_router",
                "link_quality": 3,
                "leader_cost": 0,
                "children": [
                    {
                        "id": 9,
                        "type": "sleepy",
                        "timeout": 12,
                        "rloc16": 55305,
                        "name": "Meross MS605",
                        "manufacturer": "Meross",
                        "model": "Smart Presence Sensor",
                    }
                ],
                "child_count": 1,
                "connections": [],
                "ip_addresses": [],
            },
            "96308C2577D6EA17": {
                "ext_address": "96308C2577D6EA17",
                "rloc16": 8192,
                "role": "router",
                "name": "Eero Border Router",
                "manufacturer": "Amazon/Eero",
                "device_type": "border_router",
                "link_quality": 3,
                "leader_cost": 1,
                "children": [
                    {
                        "id": 24,
                        "type": "sleepy",
                        "timeout": 12,
                        "rloc16": 8216,
                        "name": "Aqara Door Sensor",
                        "manufacturer": "Aqara",
                        "model": "Door and Window Sensor P2",
                    }
                ],
                "child_count": 1,
                "connections": [],
                "ip_addresses": [],
            },
        },
        "matter_devices": {
            "thread": [
                {"name": "Meross MS605", "manufacturer": "Meross", "model": "Smart Presence Sensor", "transport": "thread"},
                {"name": "Aqara Door Sensor", "manufacturer": "Aqara", "model": "Door and Window Sensor P2", "transport": "thread"},
            ],
            "wifi": [
                {"name": "Nuki Lock", "manufacturer": "Nuki", "model": "Smart Lock", "transport": "wifi"},
            ],
            "total": 3,
        },
    }


@pytest.fixture
def mock_coordinator(hass, mock_coordinator_data):
    """Create mock coordinator."""
    coordinator = MagicMock(spec=ThreadTopologyCoordinator)
    coordinator.data = mock_coordinator_data
    return coordinator


@pytest.fixture
def mock_config_entry():
    """Create mock config entry."""
    entry = MagicMock()
    entry.entry_id = "test_entry_id"
    return entry


class TestThreadNetworkSensor:
    """Test cases for ThreadNetworkSensor."""

    def test_sensor_init(self, mock_coordinator, mock_config_entry):
        """Test sensor initialization."""
        sensor = ThreadNetworkSensor(mock_coordinator, mock_config_entry)

        assert sensor._attr_name == "Thread Network"
        assert sensor._attr_icon == "mdi:lan"
        assert sensor._attr_unique_id == "test_entry_id_network"

    def test_native_value(self, mock_coordinator, mock_config_entry):
        """Test native value returns network name."""
        sensor = ThreadNetworkSensor(mock_coordinator, mock_config_entry)

        assert sensor.native_value == "MyHome1038137341"

    def test_native_value_no_data(self, mock_coordinator, mock_config_entry):
        """Test native value when no data available."""
        mock_coordinator.data = None
        sensor = ThreadNetworkSensor(mock_coordinator, mock_config_entry)

        assert sensor.native_value is None

    def test_extra_state_attributes(self, mock_coordinator, mock_config_entry):
        """Test extra state attributes."""
        sensor = ThreadNetworkSensor(mock_coordinator, mock_config_entry)
        attrs = sensor.extra_state_attributes

        assert attrs["state"] == "leader"
        assert attrs["router_count"] == 2
        assert attrs["total_thread_devices"] == 4
        assert attrs["matter_thread_devices"] == 2
        assert attrs["matter_wifi_devices"] == 1

    def test_extra_state_attributes_no_data(self, mock_coordinator, mock_config_entry):
        """Test extra state attributes when no data."""
        mock_coordinator.data = None
        sensor = ThreadNetworkSensor(mock_coordinator, mock_config_entry)

        assert sensor.extra_state_attributes == {}


class TestThreadTopologyMapSensor:
    """Test cases for ThreadTopologyMapSensor."""

    def test_sensor_init(self, mock_coordinator, mock_config_entry):
        """Test sensor initialization."""
        sensor = ThreadTopologyMapSensor(mock_coordinator, mock_config_entry)

        assert sensor._attr_name == "Thread Topology Map"
        assert sensor._attr_icon == "mdi:family-tree"
        assert sensor._attr_unique_id == "test_entry_id_topology_map"

    def test_native_value(self, mock_coordinator, mock_config_entry):
        """Test native value returns device count."""
        sensor = ThreadTopologyMapSensor(mock_coordinator, mock_config_entry)

        assert sensor.native_value == "4"

    def test_topology_text_contains_network_name(self, mock_coordinator, mock_config_entry):
        """Test topology text contains network name."""
        sensor = ThreadTopologyMapSensor(mock_coordinator, mock_config_entry)
        attrs = sensor.extra_state_attributes

        assert "MyHome1038137341" in attrs["topology_text"]

    def test_topology_text_contains_leader(self, mock_coordinator, mock_config_entry):
        """Test topology text contains leader info."""
        sensor = ThreadTopologyMapSensor(mock_coordinator, mock_config_entry)
        attrs = sensor.extra_state_attributes

        assert "SkyConnect (OTBR)" in attrs["topology_text"]
        assert "Leader" in attrs["topology_text"]
        assert "👑" in attrs["topology_text"]

    def test_topology_text_contains_router(self, mock_coordinator, mock_config_entry):
        """Test topology text contains router info."""
        sensor = ThreadTopologyMapSensor(mock_coordinator, mock_config_entry)
        attrs = sensor.extra_state_attributes

        assert "Eero Border Router" in attrs["topology_text"]
        assert "Router" in attrs["topology_text"]
        assert "📡" in attrs["topology_text"]

    def test_topology_text_contains_children(self, mock_coordinator, mock_config_entry):
        """Test topology text contains child devices."""
        sensor = ThreadTopologyMapSensor(mock_coordinator, mock_config_entry)
        attrs = sensor.extra_state_attributes

        assert "Meross MS605" in attrs["topology_text"]
        assert "Aqara Door Sensor" in attrs["topology_text"]
        assert "💤" in attrs["topology_text"]

    def test_topology_text_contains_wifi_section(self, mock_coordinator, mock_config_entry):
        """Test topology text contains WiFi section."""
        sensor = ThreadTopologyMapSensor(mock_coordinator, mock_config_entry)
        attrs = sensor.extra_state_attributes

        assert "Matter over WiFi" in attrs["topology_text"]
        assert "Nuki Lock" in attrs["topology_text"]

    def test_topology_text_contains_link_quality(self, mock_coordinator, mock_config_entry):
        """Test topology text contains link quality indicators."""
        sensor = ThreadTopologyMapSensor(mock_coordinator, mock_config_entry)
        attrs = sensor.extra_state_attributes

        assert "LQ:" in attrs["topology_text"]
        assert "Excellent" in attrs["topology_text"]

    def test_raw_data_in_attributes(self, mock_coordinator, mock_config_entry):
        """Test raw data is included in attributes."""
        sensor = ThreadTopologyMapSensor(mock_coordinator, mock_config_entry)
        attrs = sensor.extra_state_attributes

        assert "nodes" in attrs
        assert "matter_devices" in attrs
        assert "raw_data" in attrs


class TestThreadNodeSensor:
    """Test cases for ThreadNodeSensor."""

    def test_sensor_init_leader(self, mock_coordinator, mock_config_entry, mock_coordinator_data):
        """Test sensor initialization for leader node."""
        node_data = mock_coordinator_data["nodes"]["1EA5312CFB153F0B"]
        sensor = ThreadNodeSensor(
            mock_coordinator,
            mock_config_entry,
            "1EA5312CFB153F0B",
            node_data
        )

        assert "SkyConnect" in sensor._attr_name
        assert sensor._attr_icon == "mdi:crown"

    def test_sensor_init_router(self, mock_coordinator, mock_config_entry, mock_coordinator_data):
        """Test sensor initialization for router node."""
        node_data = mock_coordinator_data["nodes"]["96308C2577D6EA17"]
        sensor = ThreadNodeSensor(
            mock_coordinator,
            mock_config_entry,
            "96308C2577D6EA17",
            node_data
        )

        assert "Eero" in sensor._attr_name
        assert sensor._attr_icon == "mdi:router-wireless"

    def test_native_value(self, mock_coordinator, mock_config_entry, mock_coordinator_data):
        """Test native value returns link quality."""
        node_data = mock_coordinator_data["nodes"]["1EA5312CFB153F0B"]
        sensor = ThreadNodeSensor(
            mock_coordinator,
            mock_config_entry,
            "1EA5312CFB153F0B",
            node_data
        )

        assert sensor.native_value == 3

    def test_native_unit(self, mock_coordinator, mock_config_entry, mock_coordinator_data):
        """Test native unit is LQI."""
        node_data = mock_coordinator_data["nodes"]["1EA5312CFB153F0B"]
        sensor = ThreadNodeSensor(
            mock_coordinator,
            mock_config_entry,
            "1EA5312CFB153F0B",
            node_data
        )

        assert sensor.native_unit_of_measurement == "LQI"

    def test_extra_state_attributes(self, mock_coordinator, mock_config_entry, mock_coordinator_data):
        """Test extra state attributes."""
        node_data = mock_coordinator_data["nodes"]["1EA5312CFB153F0B"]
        sensor = ThreadNodeSensor(
            mock_coordinator,
            mock_config_entry,
            "1EA5312CFB153F0B",
            node_data
        )
        attrs = sensor.extra_state_attributes

        assert attrs["ext_address"] == "1EA5312CFB153F0B"
        assert attrs["role"] == "leader"
        assert attrs["name"] == "SkyConnect (OTBR)"
        assert attrs["child_count"] == 1
        assert len(attrs["children"]) == 1

    def test_children_include_names(self, mock_coordinator, mock_config_entry, mock_coordinator_data):
        """Test children include device names."""
        node_data = mock_coordinator_data["nodes"]["1EA5312CFB153F0B"]
        sensor = ThreadNodeSensor(
            mock_coordinator,
            mock_config_entry,
            "1EA5312CFB153F0B",
            node_data
        )
        attrs = sensor.extra_state_attributes

        child = attrs["children"][0]
        assert child["name"] == "Meross MS605"
        assert child["manufacturer"] == "Meross"
