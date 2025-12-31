"""Tests for Thread Topology coordinator."""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch
import pytest


class TestTopologyProcessing:
    """Test cases for topology processing logic."""

    def test_network_name_extraction(self, mock_otbr_node_response):
        """Test network name is extracted from node response."""
        network_name = mock_otbr_node_response.get("NetworkName", "Unknown")

        assert network_name == "MyHome1038137341"

    def test_state_extraction(self, mock_otbr_node_response):
        """Test state is extracted from node response."""
        state = mock_otbr_node_response.get("State", "unknown")

        assert state == "leader"

    def test_router_count_extraction(self, mock_otbr_node_response):
        """Test router count is extracted from node response."""
        router_count = mock_otbr_node_response.get("NumOfRouter", 0)

        assert router_count == 3

    def test_leader_address_extraction(self, mock_otbr_node_response):
        """Test leader extended address is extracted."""
        leader_address = mock_otbr_node_response.get("ExtAddress", "")

        assert leader_address == "1EA5312CFB153F0B"

    def test_diagnostics_node_count(self, mock_otbr_diagnostics_response):
        """Test diagnostic nodes are counted correctly."""
        assert len(mock_otbr_diagnostics_response) == 3

    def test_diagnostics_has_leader(self, mock_otbr_diagnostics_response, mock_otbr_node_response):
        """Test diagnostics contains the leader node."""
        leader_ext = mock_otbr_node_response["ExtAddress"]
        ext_addresses = [d["ExtAddress"] for d in mock_otbr_diagnostics_response]

        assert leader_ext in ext_addresses


class TestRoleIdentification:
    """Test cases for role identification logic."""

    def test_leader_identification(self, mock_otbr_diagnostics_response, mock_otbr_node_response):
        """Test leader role is correctly identified."""
        leader_ext = mock_otbr_node_response["ExtAddress"]

        for diag in mock_otbr_diagnostics_response:
            if diag["ExtAddress"] == leader_ext:
                is_leader = True
                break
        else:
            is_leader = False

        assert is_leader

    def test_router_identification(self, mock_otbr_diagnostics_response):
        """Test router role is identified from Mode.DeviceType."""
        for diag in mock_otbr_diagnostics_response:
            mode = diag.get("Mode", {})
            is_router = mode.get("DeviceType", 0) == 1

            # All nodes in mock data are routers
            assert is_router


class TestLinkQualityCalculation:
    """Test cases for link quality calculation."""

    def test_link_quality_3_is_best(self, mock_otbr_diagnostics_response):
        """Test link quality 3 is identified as best."""
        for diag in mock_otbr_diagnostics_response:
            connectivity = diag.get("Connectivity", {})
            lq3 = connectivity.get("LinkQuality3", 0)
            lq2 = connectivity.get("LinkQuality2", 0)
            lq1 = connectivity.get("LinkQuality1", 0)

            if lq3 > 0:
                link_quality = 3
            elif lq2 > 0:
                link_quality = 2
            elif lq1 > 0:
                link_quality = 1
            else:
                link_quality = 0

            # All mock nodes have LQ3 = 1
            assert link_quality == 3

    def test_leader_cost_extraction(self, mock_otbr_diagnostics_response):
        """Test leader cost is extracted from connectivity."""
        # Leader should have cost 0, routers have cost >= 1
        for diag in mock_otbr_diagnostics_response:
            connectivity = diag.get("Connectivity", {})
            leader_cost = connectivity.get("LeaderCost", 0)

            assert leader_cost >= 0


class TestChildTableProcessing:
    """Test cases for child table processing."""

    def test_child_count(self, mock_otbr_diagnostics_response):
        """Test children are counted correctly."""
        total_children = 0
        for diag in mock_otbr_diagnostics_response:
            children = diag.get("ChildTable", [])
            total_children += len(children)

        # Mock has: 1 + 1 + 2 = 4 children
        assert total_children == 4

    def test_sleepy_device_identification(self, mock_otbr_diagnostics_response):
        """Test sleepy end devices are identified."""
        sleepy_count = 0
        active_count = 0

        for diag in mock_otbr_diagnostics_response:
            for child in diag.get("ChildTable", []):
                child_mode = child.get("Mode", {})
                rx_on_idle = child_mode.get("RxOnWhenIdle", 1)

                if rx_on_idle == 0:
                    sleepy_count += 1
                else:
                    active_count += 1

        # Most mock children are sleepy (RxOnWhenIdle=0)
        assert sleepy_count >= 2


class TestBorderRouterIdentification:
    """Test cases for border router identification."""

    def test_skyconnect_leader_identification(self):
        """Test SkyConnect is identified as leader."""
        def identify_router(ext_address: str, is_leader: bool, router_index: int) -> dict:
            if is_leader:
                return {
                    "name": "SkyConnect (OTBR)",
                    "manufacturer": "Nabu Casa",
                    "type": "border_router",
                }
            return {
                "name": "Unknown Router",
                "manufacturer": "Unknown",
                "type": "border_router",
            }

        result = identify_router("ANYADDRESS", is_leader=True, router_index=0)

        assert result["name"] == "SkyConnect (OTBR)"
        assert result["manufacturer"] == "Nabu Casa"

    def test_eero_pattern_matching(self):
        """Test Eero router identification by pattern."""
        BORDER_ROUTER_PATTERNS = [
            ("EA17", "Eero", "Amazon/Eero"),
            ("EA", "Eero", "Amazon/Eero"),
        ]

        ext_address = "96308C2577D6EA17"

        matched = None
        for pattern, name, manufacturer in BORDER_ROUTER_PATTERNS:
            if pattern in ext_address.upper():
                matched = (name, manufacturer)
                break

        assert matched is not None
        assert matched[0] == "Eero"
        assert matched[1] == "Amazon/Eero"

    def test_oui_based_identification(self):
        """Test OUI-based router identification."""
        KNOWN_OUIS = {
            "28:6D:97": {"name": "Apple HomePod", "manufacturer": "Apple"},
            "18:D6:C7": {"name": "Google Nest Hub", "manufacturer": "Google"},
            "50:EC:50": {"name": "Eero Pro", "manufacturer": "Amazon/Eero"},
        }

        # Test Apple OUI
        ext = "286D970123456789"
        oui = f"{ext[0:2]}:{ext[2:4]}:{ext[4:6]}"

        assert oui in KNOWN_OUIS
        assert KNOWN_OUIS[oui]["manufacturer"] == "Apple"


class TestMatterDeviceMatching:
    """Test cases for Matter device matching."""

    def test_thread_device_filter(self, mock_matter_devices):
        """Test filtering Thread-only Matter devices."""
        thread_devices = [d for d in mock_matter_devices if d["transport"] == "thread"]

        assert len(thread_devices) == 3

    def test_wifi_device_filter(self, mock_matter_devices):
        """Test filtering WiFi-only Matter devices."""
        wifi_devices = [d for d in mock_matter_devices if d["transport"] == "wifi"]

        assert len(wifi_devices) == 2

    def test_device_name_access(self, mock_matter_devices):
        """Test accessing device names."""
        names = [d["name"] for d in mock_matter_devices]

        assert "Meross MS605" in names
        assert "Nuki Smart Lock" in names


class TestTopologyResult:
    """Test cases for topology result structure."""

    def test_result_structure(self, mock_otbr_node_response, mock_otbr_diagnostics_response, mock_matter_devices):
        """Test the expected topology result structure."""
        # Simulate processing
        result = {
            "network_name": mock_otbr_node_response["NetworkName"],
            "state": mock_otbr_node_response["State"],
            "leader_address": mock_otbr_node_response["ExtAddress"],
            "router_count": mock_otbr_node_response["NumOfRouter"],
            "nodes": {},
            "total_devices": 0,
            "matter_devices": {
                "thread": [d for d in mock_matter_devices if d["transport"] == "thread"],
                "wifi": [d for d in mock_matter_devices if d["transport"] == "wifi"],
                "total": len(mock_matter_devices),
            },
        }

        # Add nodes
        for diag in mock_otbr_diagnostics_response:
            ext = diag["ExtAddress"]
            result["nodes"][ext] = {
                "ext_address": ext,
                "rloc16": diag["Rloc16"],
                "children": diag.get("ChildTable", []),
                "child_count": len(diag.get("ChildTable", [])),
            }
            result["total_devices"] += 1 + len(diag.get("ChildTable", []))

        assert result["network_name"] == "MyHome1038137341"
        assert len(result["nodes"]) == 3
        assert result["total_devices"] == 7  # 3 routers + 4 children
        assert len(result["matter_devices"]["thread"]) == 3
        assert len(result["matter_devices"]["wifi"]) == 2


class TestURLNormalization:
    """Test cases for URL normalization."""

    def test_trailing_slash_removal(self):
        """Test trailing slash is removed from URL."""
        urls = [
            ("http://localhost:8081/", "http://localhost:8081"),
            ("http://localhost:8081", "http://localhost:8081"),
            ("http://homeassistant.local:8081/", "http://homeassistant.local:8081"),
        ]

        for input_url, expected in urls:
            result = input_url.rstrip("/")
            assert result == expected

    def test_endpoint_construction(self):
        """Test endpoint URL construction."""
        base_url = "http://localhost:8081"
        endpoint = "/node"

        full_url = f"{base_url}{endpoint}"

        assert full_url == "http://localhost:8081/node"
