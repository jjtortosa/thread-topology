"""Tests for Thread Topology coordinator."""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch
import pytest
import aiohttp

from custom_components.thread_topology.coordinator import ThreadTopologyCoordinator
from custom_components.thread_topology.const import DEFAULT_OTBR_URL


class TestThreadTopologyCoordinator:
    """Test cases for ThreadTopologyCoordinator."""

    @pytest.fixture
    def coordinator(self, hass):
        """Create coordinator instance."""
        return ThreadTopologyCoordinator(hass, DEFAULT_OTBR_URL)

    @pytest.mark.asyncio
    async def test_coordinator_init(self, hass):
        """Test coordinator initialization."""
        coordinator = ThreadTopologyCoordinator(hass, DEFAULT_OTBR_URL)

        assert coordinator.otbr_url == DEFAULT_OTBR_URL.rstrip("/")
        assert coordinator._session is None
        assert coordinator.update_interval.total_seconds() == 60

    @pytest.mark.asyncio
    async def test_coordinator_custom_url(self, hass):
        """Test coordinator with custom URL."""
        custom_url = "http://192.168.1.100:8081/"
        coordinator = ThreadTopologyCoordinator(hass, custom_url)

        assert coordinator.otbr_url == "http://192.168.1.100:8081"

    @pytest.mark.asyncio
    async def test_process_topology(
        self,
        hass,
        mock_otbr_node_response,
        mock_otbr_diagnostics_response,
    ):
        """Test topology processing."""
        coordinator = ThreadTopologyCoordinator(hass, DEFAULT_OTBR_URL)

        with patch.object(coordinator, "_get_matter_devices", return_value=[]):
            with patch.object(coordinator, "_get_thread_border_routers", return_value=[]):
                result = coordinator._process_topology(
                    mock_otbr_node_response,
                    mock_otbr_diagnostics_response,
                    [],
                    []
                )

        assert result["network_name"] == "MyHome1038137341"
        assert result["state"] == "leader"
        assert result["router_count"] == 3
        assert result["leader_address"] == "1EA5312CFB153F0B"
        assert len(result["nodes"]) == 3
        assert result["total_devices"] == 7  # 3 routers + 4 children

    @pytest.mark.asyncio
    async def test_process_topology_identifies_leader(
        self,
        hass,
        mock_otbr_node_response,
        mock_otbr_diagnostics_response,
    ):
        """Test that leader node is correctly identified."""
        coordinator = ThreadTopologyCoordinator(hass, DEFAULT_OTBR_URL)

        with patch.object(coordinator, "_get_matter_devices", return_value=[]):
            with patch.object(coordinator, "_get_thread_border_routers", return_value=[]):
                result = coordinator._process_topology(
                    mock_otbr_node_response,
                    mock_otbr_diagnostics_response,
                    [],
                    []
                )

        leader_node = result["nodes"]["1EA5312CFB153F0B"]
        assert leader_node["role"] == "leader"
        assert leader_node["name"] == "SkyConnect (OTBR)"

    @pytest.mark.asyncio
    async def test_process_topology_identifies_routers(
        self,
        hass,
        mock_otbr_node_response,
        mock_otbr_diagnostics_response,
    ):
        """Test that router nodes are correctly identified."""
        coordinator = ThreadTopologyCoordinator(hass, DEFAULT_OTBR_URL)

        with patch.object(coordinator, "_get_matter_devices", return_value=[]):
            with patch.object(coordinator, "_get_thread_border_routers", return_value=[]):
                result = coordinator._process_topology(
                    mock_otbr_node_response,
                    mock_otbr_diagnostics_response,
                    [],
                    []
                )

        router_node = result["nodes"]["96308C2577D6EA17"]
        assert router_node["role"] == "router"
        assert router_node["device_type"] == "border_router"

    @pytest.mark.asyncio
    async def test_process_topology_counts_children(
        self,
        hass,
        mock_otbr_node_response,
        mock_otbr_diagnostics_response,
    ):
        """Test that children are correctly counted."""
        coordinator = ThreadTopologyCoordinator(hass, DEFAULT_OTBR_URL)

        with patch.object(coordinator, "_get_matter_devices", return_value=[]):
            with patch.object(coordinator, "_get_thread_border_routers", return_value=[]):
                result = coordinator._process_topology(
                    mock_otbr_node_response,
                    mock_otbr_diagnostics_response,
                    [],
                    []
                )

        # Node with 2 children
        node_with_2_children = result["nodes"]["A4B3C2D1E0F09876"]
        assert node_with_2_children["child_count"] == 2
        assert len(node_with_2_children["children"]) == 2

    @pytest.mark.asyncio
    async def test_process_topology_identifies_sleepy_devices(
        self,
        hass,
        mock_otbr_node_response,
        mock_otbr_diagnostics_response,
    ):
        """Test that sleepy end devices are correctly identified."""
        coordinator = ThreadTopologyCoordinator(hass, DEFAULT_OTBR_URL)

        with patch.object(coordinator, "_get_matter_devices", return_value=[]):
            with patch.object(coordinator, "_get_thread_border_routers", return_value=[]):
                result = coordinator._process_topology(
                    mock_otbr_node_response,
                    mock_otbr_diagnostics_response,
                    [],
                    []
                )

        leader_node = result["nodes"]["1EA5312CFB153F0B"]
        child = leader_node["children"][0]
        assert child["type"] == "sleepy"

    @pytest.mark.asyncio
    async def test_process_topology_with_matter_devices(
        self,
        hass,
        mock_otbr_node_response,
        mock_otbr_diagnostics_response,
        mock_matter_devices,
    ):
        """Test topology processing with Matter device matching."""
        coordinator = ThreadTopologyCoordinator(hass, DEFAULT_OTBR_URL)

        result = coordinator._process_topology(
            mock_otbr_node_response,
            mock_otbr_diagnostics_response,
            mock_matter_devices,
            []
        )

        # Check Matter devices are separated
        assert "matter_devices" in result
        assert len(result["matter_devices"]["thread"]) == 3
        assert len(result["matter_devices"]["wifi"]) == 2

    @pytest.mark.asyncio
    async def test_link_quality_calculation(
        self,
        hass,
        mock_otbr_node_response,
        mock_otbr_diagnostics_response,
    ):
        """Test link quality is correctly calculated."""
        coordinator = ThreadTopologyCoordinator(hass, DEFAULT_OTBR_URL)

        with patch.object(coordinator, "_get_matter_devices", return_value=[]):
            with patch.object(coordinator, "_get_thread_border_routers", return_value=[]):
                result = coordinator._process_topology(
                    mock_otbr_node_response,
                    mock_otbr_diagnostics_response,
                    [],
                    []
                )

        # All nodes in mock have LinkQuality3 = 1, so LQ should be 3
        for node in result["nodes"].values():
            assert node["link_quality"] == 3

    @pytest.mark.asyncio
    async def test_identify_router_leader(self, hass):
        """Test leader router identification."""
        coordinator = ThreadTopologyCoordinator(hass, DEFAULT_OTBR_URL)

        result = coordinator._identify_router("1EA5312CFB153F0B", is_leader=True, router_index=0)

        assert result["name"] == "SkyConnect (OTBR)"
        assert result["manufacturer"] == "Nabu Casa"
        assert result["type"] == "border_router"

    @pytest.mark.asyncio
    async def test_identify_router_non_leader(self, hass):
        """Test non-leader router identification."""
        coordinator = ThreadTopologyCoordinator(hass, DEFAULT_OTBR_URL)

        result = coordinator._identify_router("96308C2577D6EA17", is_leader=False, router_index=1)

        assert result["type"] == "border_router"

    @pytest.mark.asyncio
    async def test_coordinator_shutdown(self, hass):
        """Test coordinator shutdown closes session."""
        coordinator = ThreadTopologyCoordinator(hass, DEFAULT_OTBR_URL)
        coordinator._session = AsyncMock()

        await coordinator.async_shutdown()

        coordinator._session.close.assert_called_once()
        assert coordinator._session is None


class TestBorderRouterIdentification:
    """Test cases for border router identification."""

    @pytest.fixture
    def coordinator(self, hass):
        """Create coordinator instance."""
        return ThreadTopologyCoordinator(hass, DEFAULT_OTBR_URL)

    def test_identify_skyconnect_as_leader(self, coordinator):
        """Test SkyConnect is identified as leader."""
        result = coordinator._identify_router("ANYADDRESS", is_leader=True, router_index=0)
        assert "SkyConnect" in result["name"]

    def test_identify_eero_router(self, coordinator):
        """Test Eero router identification by address pattern."""
        result = coordinator._identify_router("96308C2577D6EA17", is_leader=False, router_index=1)
        # This address contains "EA17" which matches Eero pattern
        assert result["type"] == "border_router"
        assert "Eero" in result["name"] or result["manufacturer"] == "Amazon/Eero"


class TestMatterDeviceMatching:
    """Test cases for Matter device matching."""

    @pytest.fixture
    def coordinator(self, hass):
        """Create coordinator instance."""
        return ThreadTopologyCoordinator(hass, DEFAULT_OTBR_URL)

    def test_match_end_device_with_matter(self, coordinator, mock_matter_devices):
        """Test matching end devices with Matter devices."""
        thread_devices = [d for d in mock_matter_devices if d["transport"] == "thread"]

        result = coordinator._match_end_device(8192, 0, mock_matter_devices)

        assert result is not None
        assert result["name"] == "Meross MS605"

    def test_match_end_device_no_match(self, coordinator):
        """Test matching when no Matter devices available."""
        result = coordinator._match_end_device(8192, 0, [])

        assert result is None
