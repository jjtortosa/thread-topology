"""Data coordinator for Thread Topology."""
from __future__ import annotations

import asyncio
import logging
from datetime import timedelta
from typing import Any

import aiohttp

from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .const import (
    DEFAULT_SCAN_INTERVAL,
    DOMAIN,
    ENDPOINT_DIAGNOSTICS,
    ENDPOINT_NODE,
)

_LOGGER = logging.getLogger(__name__)

# Known Thread Border Router manufacturers/identifiers
KNOWN_BORDER_ROUTERS = {
    # Eero routers often have EA in their extended address
    "eero": ["eero", "amazon"],
    # Apple devices
    "apple": ["apple", "homepod"],
    # Google devices
    "google": ["google", "nest"],
    # SkyConnect / Home Assistant
    "skyconnect": ["nabu casa", "home assistant", "silicon labs"],
}


class ThreadTopologyCoordinator(DataUpdateCoordinator[dict[str, Any]]):
    """Coordinator to fetch Thread topology data from OTBR."""

    def __init__(
        self,
        hass: HomeAssistant,
        otbr_url: str,
        scan_interval: int = DEFAULT_SCAN_INTERVAL,
    ) -> None:
        """Initialize the coordinator."""
        super().__init__(
            hass,
            _LOGGER,
            name=DOMAIN,
            update_interval=timedelta(seconds=scan_interval),
        )
        self.otbr_url = otbr_url.rstrip("/")
        self._session: aiohttp.ClientSession | None = None

    async def _async_update_data(self) -> dict[str, Any]:
        """Fetch data from OTBR API."""
        try:
            if self._session is None:
                self._session = aiohttp.ClientSession()

            # Fetch node info
            node_data = await self._fetch_endpoint(ENDPOINT_NODE)

            # Fetch diagnostics (topology)
            diagnostics_data = await self._fetch_endpoint(ENDPOINT_DIAGNOSTICS)

            # Get Matter devices from HA device registry
            matter_devices = self._get_matter_devices()

            # Process and combine data
            topology = self._process_topology(node_data, diagnostics_data, matter_devices)

            return topology

        except aiohttp.ClientError as err:
            raise UpdateFailed(f"Error communicating with OTBR: {err}") from err
        except asyncio.TimeoutError as err:
            raise UpdateFailed(f"Timeout communicating with OTBR: {err}") from err

    async def _fetch_endpoint(self, endpoint: str) -> Any:
        """Fetch data from a specific OTBR endpoint."""
        url = f"{self.otbr_url}{endpoint}"
        async with self._session.get(url, timeout=aiohttp.ClientTimeout(total=10)) as response:
            response.raise_for_status()
            return await response.json()

    def _get_matter_devices(self) -> list[dict[str, Any]]:
        """Get Matter devices from Home Assistant device registry."""
        device_registry = dr.async_get(self.hass)
        matter_devices = []

        for device in device_registry.devices.values():
            # Check if device has matter identifier
            for identifier in device.identifiers:
                if identifier[0] == "matter":
                    # Determine transport type based on model name
                    model = (device.model or "").lower()
                    manufacturer = (device.manufacturer or "").lower()
                    name = device.name or "Unknown"

                    # Detect WiFi vs Thread transport
                    transport = "thread"  # Default to Thread
                    if "wifi" in model or "wifi" in name.lower():
                        transport = "wifi"
                    elif manufacturer in ["nuki"]:
                        # Nuki uses WiFi bridge for Matter
                        transport = "wifi"

                    matter_devices.append({
                        "name": name,
                        "model": device.model,
                        "manufacturer": device.manufacturer,
                        "identifiers": list(device.identifiers),
                        "transport": transport,
                    })
                    break

        return matter_devices

    def _identify_router(self, ext_address: str, is_leader: bool) -> dict[str, str]:
        """Try to identify a router by its characteristics."""
        # Check if this is the OTBR leader (SkyConnect)
        if is_leader:
            return {
                "name": "SkyConnect (OTBR)",
                "manufacturer": "Nabu Casa",
                "type": "border_router",
            }

        # For non-leader routers, likely Eero or other border routers
        # Most home setups use Eero, Google, or Apple as additional TBRs
        return {
            "name": "Eero Border Router",
            "manufacturer": "Amazon/Eero",
            "type": "border_router",
        }

    def _match_end_device(
        self, parent_rloc: int, child_idx: int, matter_devices: list[dict]
    ) -> dict[str, Any] | None:
        """Try to match an end device with a Matter device."""
        # Get Thread-only Matter devices
        thread_devices = [d for d in matter_devices if d["transport"] == "thread"]

        # Simple heuristic: assign devices based on order
        # In a real implementation, you'd need to query Matter fabric data
        if child_idx < len(thread_devices):
            return thread_devices[child_idx]

        return None

    def _process_topology(
        self, node_data: dict, diagnostics_data: list, matter_devices: list[dict]
    ) -> dict[str, Any]:
        """Process raw OTBR data into topology structure."""
        # Get leader info
        leader_ext_address = node_data.get("ExtAddress", "")
        network_name = node_data.get("NetworkName", "Unknown")
        num_routers = node_data.get("NumOfRouter", 0)
        state = node_data.get("State", "unknown")

        # Separate Thread and WiFi Matter devices
        thread_matter = [d for d in matter_devices if d["transport"] == "thread"]
        wifi_matter = [d for d in matter_devices if d["transport"] == "wifi"]

        # Track which Matter devices we've assigned
        assigned_thread_devices = []

        # Build nodes dictionary
        nodes: dict[str, dict] = {}
        thread_device_idx = 0

        for diag in diagnostics_data:
            ext_address = diag.get("ExtAddress", "")
            rloc16 = diag.get("Rloc16", 0)

            # Determine device role
            mode = diag.get("Mode", {})
            is_router = mode.get("DeviceType", 0) == 1
            is_leader = ext_address == leader_ext_address

            if is_leader:
                role = "leader"
            elif is_router:
                role = "router"
            else:
                role = "end_device"

            # Get router identification
            router_info = self._identify_router(ext_address, is_leader)

            # Get connectivity info
            connectivity = diag.get("Connectivity", {})
            leader_cost = connectivity.get("LeaderCost", 0)

            # Get best link quality (3 = best, 0 = none)
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

            # Get children and try to match with Matter devices
            child_table = diag.get("ChildTable", [])
            children = []
            for child in child_table:
                child_id = child.get("ChildId", 0)
                child_mode = child.get("Mode", {})
                child_type = "sleepy" if child_mode.get("RxOnWhenIdle", 1) == 0 else "active"

                # Try to match with a Matter device
                matter_match = None
                if thread_device_idx < len(thread_matter):
                    matter_match = thread_matter[thread_device_idx]
                    assigned_thread_devices.append(matter_match)
                    thread_device_idx += 1

                child_info = {
                    "id": child_id,
                    "type": child_type,
                    "timeout": child.get("Timeout", 0),
                    "rloc16": rloc16 + child_id,
                }

                if matter_match:
                    child_info["name"] = matter_match["name"]
                    child_info["manufacturer"] = matter_match["manufacturer"]
                    child_info["model"] = matter_match["model"]

                children.append(child_info)

            # Get route data for connections
            route = diag.get("Route", {})
            route_data = route.get("RouteData", [])
            connections = []
            for rd in route_data:
                if rd.get("RouteCost", 255) < 255:
                    connections.append({
                        "router_id": rd.get("RouteId", 0),
                        "lq_out": rd.get("LinkQualityOut", 0),
                        "lq_in": rd.get("LinkQualityIn", 0),
                        "cost": rd.get("RouteCost", 0),
                    })

            nodes[ext_address] = {
                "ext_address": ext_address,
                "rloc16": rloc16,
                "role": role,
                "name": router_info["name"],
                "manufacturer": router_info["manufacturer"],
                "device_type": router_info["type"],
                "link_quality": link_quality,
                "leader_cost": leader_cost,
                "children": children,
                "child_count": len(children),
                "connections": connections,
                "ip_addresses": diag.get("IP6AddressList", []),
            }

        return {
            "network_name": network_name,
            "state": state,
            "leader_address": leader_ext_address,
            "router_count": num_routers,
            "nodes": nodes,
            "total_devices": len(nodes) + sum(n["child_count"] for n in nodes.values()),
            "matter_devices": {
                "thread": thread_matter,
                "wifi": wifi_matter,
                "total": len(matter_devices),
            },
        }

    async def async_shutdown(self) -> None:
        """Shutdown the coordinator."""
        if self._session:
            await self._session.close()
            self._session = None
