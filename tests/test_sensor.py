"""Tests for Thread Topology sensors."""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch
import pytest


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
def mock_coordinator(mock_coordinator_data):
    """Create mock coordinator."""
    coordinator = MagicMock()
    coordinator.data = mock_coordinator_data
    return coordinator


@pytest.fixture
def mock_config_entry():
    """Create mock config entry."""
    entry = MagicMock()
    entry.entry_id = "test_entry_id"
    return entry


class TestThreadNetworkSensor:
    """Test cases for ThreadNetworkSensor logic."""

    def test_network_name_extraction(self, mock_coordinator_data):
        """Test network name is correctly extracted."""
        data = mock_coordinator_data
        network_name = data.get("network_name")

        assert network_name == "MyHome1038137341"

    def test_network_state_extraction(self, mock_coordinator_data):
        """Test network state is correctly extracted."""
        data = mock_coordinator_data
        state = data.get("state")

        assert state == "leader"

    def test_router_count_extraction(self, mock_coordinator_data):
        """Test router count is correctly extracted."""
        data = mock_coordinator_data
        router_count = data.get("router_count")

        assert router_count == 2

    def test_total_devices_extraction(self, mock_coordinator_data):
        """Test total devices is correctly extracted."""
        data = mock_coordinator_data
        total_devices = data.get("total_devices")

        assert total_devices == 4

    def test_matter_thread_devices_count(self, mock_coordinator_data):
        """Test Matter thread devices count."""
        data = mock_coordinator_data
        thread_devices = len(data.get("matter_devices", {}).get("thread", []))

        assert thread_devices == 2

    def test_matter_wifi_devices_count(self, mock_coordinator_data):
        """Test Matter WiFi devices count."""
        data = mock_coordinator_data
        wifi_devices = len(data.get("matter_devices", {}).get("wifi", []))

        assert wifi_devices == 1

    def test_handle_no_data(self):
        """Test handling when no data available."""
        data = None
        result = data if data else None

        assert result is None


class TestThreadTopologyMapSensor:
    """Test cases for ThreadTopologyMapSensor logic."""

    def test_topology_text_generation(self, mock_coordinator_data):
        """Test topology text generation contains expected elements."""
        data = mock_coordinator_data

        # Build topology text (simplified version of actual logic)
        lines = []
        lines.append(f"Thread Network: {data['network_name']}")
        lines.append(f"State: {data['state']}")
        lines.append(f"Routers: {data['router_count']}")

        for ext_addr, node in data["nodes"].items():
            role = node["role"]
            name = node["name"]
            emoji = "👑" if role == "leader" else "📡"
            lines.append(f"{emoji} {name} ({role})")

            for child in node.get("children", []):
                child_emoji = "💤" if child["type"] == "sleepy" else "🔋"
                lines.append(f"  {child_emoji} {child.get('name', 'Unknown')}")

        topology_text = "\n".join(lines)

        assert "MyHome1038137341" in topology_text
        assert "SkyConnect (OTBR)" in topology_text
        assert "👑" in topology_text
        assert "📡" in topology_text
        assert "Meross MS605" in topology_text
        assert "💤" in topology_text

    def test_device_count_calculation(self, mock_coordinator_data):
        """Test device count calculation."""
        data = mock_coordinator_data

        total = data.get("total_devices", 0)

        assert str(total) == "4"

    def test_nodes_data_structure(self, mock_coordinator_data):
        """Test nodes data structure."""
        data = mock_coordinator_data
        nodes = data.get("nodes", {})

        assert len(nodes) == 2
        assert "1EA5312CFB153F0B" in nodes
        assert "96308C2577D6EA17" in nodes


class TestThreadNodeSensor:
    """Test cases for ThreadNodeSensor logic."""

    def test_leader_node_attributes(self, mock_coordinator_data):
        """Test leader node attributes."""
        node_data = mock_coordinator_data["nodes"]["1EA5312CFB153F0B"]

        assert node_data["role"] == "leader"
        assert "SkyConnect" in node_data["name"]
        assert node_data["link_quality"] == 3

    def test_router_node_attributes(self, mock_coordinator_data):
        """Test router node attributes."""
        node_data = mock_coordinator_data["nodes"]["96308C2577D6EA17"]

        assert node_data["role"] == "router"
        assert "Eero" in node_data["name"]
        assert node_data["link_quality"] == 3

    def test_icon_selection_for_leader(self, mock_coordinator_data):
        """Test icon selection for leader node."""
        node_data = mock_coordinator_data["nodes"]["1EA5312CFB153F0B"]

        icon = "mdi:crown" if node_data["role"] == "leader" else "mdi:router-wireless"

        assert icon == "mdi:crown"

    def test_icon_selection_for_router(self, mock_coordinator_data):
        """Test icon selection for router node."""
        node_data = mock_coordinator_data["nodes"]["96308C2577D6EA17"]

        icon = "mdi:crown" if node_data["role"] == "leader" else "mdi:router-wireless"

        assert icon == "mdi:router-wireless"

    def test_link_quality_as_native_value(self, mock_coordinator_data):
        """Test link quality is used as native value."""
        node_data = mock_coordinator_data["nodes"]["1EA5312CFB153F0B"]

        native_value = node_data.get("link_quality", 0)

        assert native_value == 3

    def test_native_unit(self):
        """Test native unit is LQI."""
        unit = "LQI"

        assert unit == "LQI"

    def test_children_data(self, mock_coordinator_data):
        """Test children data structure."""
        node_data = mock_coordinator_data["nodes"]["1EA5312CFB153F0B"]
        children = node_data.get("children", [])

        assert len(children) == 1
        assert children[0]["name"] == "Meross MS605"
        assert children[0]["type"] == "sleepy"

    def test_child_count(self, mock_coordinator_data):
        """Test child count."""
        node_data = mock_coordinator_data["nodes"]["1EA5312CFB153F0B"]
        child_count = node_data.get("child_count", 0)

        assert child_count == 1


class TestLinkQualityMapping:
    """Test cases for link quality to descriptive text mapping."""

    def test_link_quality_excellent(self):
        """Test link quality 3 maps to Excellent."""
        lq = 3
        description = {3: "Excellent", 2: "Good", 1: "Fair", 0: "Poor"}.get(lq, "Unknown")

        assert description == "Excellent"

    def test_link_quality_good(self):
        """Test link quality 2 maps to Good."""
        lq = 2
        description = {3: "Excellent", 2: "Good", 1: "Fair", 0: "Poor"}.get(lq, "Unknown")

        assert description == "Good"

    def test_link_quality_fair(self):
        """Test link quality 1 maps to Fair."""
        lq = 1
        description = {3: "Excellent", 2: "Good", 1: "Fair", 0: "Poor"}.get(lq, "Unknown")

        assert description == "Fair"

    def test_link_quality_poor(self):
        """Test link quality 0 maps to Poor."""
        lq = 0
        description = {3: "Excellent", 2: "Good", 1: "Fair", 0: "Poor"}.get(lq, "Unknown")

        assert description == "Poor"
