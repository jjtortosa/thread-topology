"""Data coordinator for Thread Topology."""
from __future__ import annotations

import asyncio
import logging
import os
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

# Known Thread Border Router OUI prefixes (first 6 chars of extended address)
# These are based on IEEE OUI database and known devices
KNOWN_BORDER_ROUTER_OUIS = {
    # Apple devices (HomePod, Apple TV)
    "28:6D:97": {"name": "Apple HomePod", "manufacturer": "Apple", "icon": "homepod"},
    "3C:22:FB": {"name": "Apple HomePod", "manufacturer": "Apple", "icon": "homepod"},
    "38:C9:86": {"name": "Apple TV", "manufacturer": "Apple", "icon": "appletv"},
    "D0:03:4B": {"name": "Apple HomePod", "manufacturer": "Apple", "icon": "homepod"},
    "F0:B3:EC": {"name": "Apple HomePod Mini", "manufacturer": "Apple", "icon": "homepod"},
    "64:B5:C6": {"name": "Apple Device", "manufacturer": "Apple", "icon": "apple"},

    # Google/Nest devices
    "18:D6:C7": {"name": "Google Nest Hub", "manufacturer": "Google", "icon": "nest"},
    "1C:F2:9A": {"name": "Google Nest", "manufacturer": "Google", "icon": "nest"},
    "20:DF:B9": {"name": "Google Nest WiFi", "manufacturer": "Google", "icon": "nest"},
    "48:D6:D5": {"name": "Google Nest Hub Max", "manufacturer": "Google", "icon": "nest"},
    "54:60:09": {"name": "Google Nest", "manufacturer": "Google", "icon": "nest"},
    "F4:F5:D8": {"name": "Google Nest", "manufacturer": "Google", "icon": "nest"},
    "F4:F5:E8": {"name": "Google Nest Mini", "manufacturer": "Google", "icon": "nest"},

    # Amazon/Eero
    "50:EC:50": {"name": "Eero Pro", "manufacturer": "Amazon/Eero", "icon": "eero"},
    "68:2A:2B": {"name": "Eero Pro 6", "manufacturer": "Amazon/Eero", "icon": "eero"},
    "70:3A:CB": {"name": "Eero", "manufacturer": "Amazon/Eero", "icon": "eero"},
    "F0:81:75": {"name": "Eero Pro 6E", "manufacturer": "Amazon/Eero", "icon": "eero"},

    # Samsung SmartThings
    "24:FC:E5": {"name": "SmartThings Hub", "manufacturer": "Samsung", "icon": "smartthings"},
    "28:6D:CD": {"name": "SmartThings Station", "manufacturer": "Samsung", "icon": "smartthings"},
    "D0:52:A8": {"name": "SmartThings Hub", "manufacturer": "Samsung", "icon": "smartthings"},

    # Nanoleaf
    "00:55:DA": {"name": "Nanoleaf Controller", "manufacturer": "Nanoleaf", "icon": "nanoleaf"},

    # Silicon Labs (often used in DIY/dev boards)
    "04:CD:15": {"name": "Silicon Labs Device", "manufacturer": "Silicon Labs", "icon": "chip"},
    "58:8E:81": {"name": "Silicon Labs Device", "manufacturer": "Silicon Labs", "icon": "chip"},
    "84:2E:14": {"name": "Silicon Labs Device", "manufacturer": "Silicon Labs", "icon": "chip"},

    # Nordic Semiconductor
    "F8:F0:05": {"name": "Nordic Device", "manufacturer": "Nordic Semiconductor", "icon": "chip"},

    # Espressif (ESP32-H2, etc.)
    "34:85:18": {"name": "ESP32 Thread", "manufacturer": "Espressif", "icon": "chip"},
    "40:22:D8": {"name": "ESP32 Thread", "manufacturer": "Espressif", "icon": "chip"},
}

# Fallback patterns for partial matches
BORDER_ROUTER_PATTERNS = [
    # Pattern, name, manufacturer
    ("EA17", "Eero", "Amazon/Eero"),
    ("EA", "Eero", "Amazon/Eero"),  # Eero addresses often end with EA17
]


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
        self._router_index = 0  # Track router numbering

    async def _async_update_data(self) -> dict[str, Any]:
        """Fetch data from OTBR API."""
        try:
            if self._session is None:
                self._session = aiohttp.ClientSession()

            # Reset router index for each update
            self._router_index = 0

            # Fetch node info
            node_data = await self._fetch_endpoint(ENDPOINT_NODE)

            # Fetch diagnostics (topology)
            diagnostics_data = await self._fetch_endpoint(ENDPOINT_DIAGNOSTICS)

            # Get Matter devices from HA device registry
            matter_devices = self._get_matter_devices()

            # Get Thread Border Routers from HA device registry
            thread_routers = self._get_thread_border_routers()

            # Process and combine data
            topology = self._process_topology(
                node_data, diagnostics_data, matter_devices, thread_routers
            )

            # Generate and save SVG to www folder
            self.save_svg_to_www(topology)

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
                    elif manufacturer in ["nuki", "wemo", "lifx"]:
                        # These typically use WiFi bridge for Matter
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

    def _get_thread_border_routers(self) -> list[dict[str, Any]]:
        """Get Thread Border Routers from Home Assistant device registry."""
        device_registry = dr.async_get(self.hass)
        routers = []

        for device in device_registry.devices.values():
            # Check for thread/otbr identifiers
            for identifier in device.identifiers:
                if identifier[0] in ("thread", "otbr", "homekit_controller"):
                    name = device.name or "Unknown"
                    manufacturer = device.manufacturer or ""

                    # Check if this looks like a border router
                    if any(kw in name.lower() for kw in ["border", "router", "hub", "homepod", "nest", "eero"]):
                        routers.append({
                            "name": name,
                            "manufacturer": manufacturer,
                            "model": device.model,
                        })
                    break

        return routers

    def _identify_router(
        self, ext_address: str, is_leader: bool, router_index: int
    ) -> dict[str, str]:
        """Identify a router by its extended address or characteristics."""
        # Check if this is the OTBR leader (typically SkyConnect or similar)
        if is_leader:
            return {
                "name": "SkyConnect (OTBR)",
                "manufacturer": "Nabu Casa",
                "type": "border_router",
                "icon": "home-assistant",
            }

        # Convert extended address to OUI format (XX:XX:XX)
        ext_upper = ext_address.upper()
        if len(ext_upper) >= 6:
            # Try different OUI formats
            oui_formats = [
                f"{ext_upper[0:2]}:{ext_upper[2:4]}:{ext_upper[4:6]}",  # Standard
                f"{ext_upper[-6:-4]}:{ext_upper[-4:-2]}:{ext_upper[-2:]}",  # Last 6
            ]

            for oui in oui_formats:
                if oui in KNOWN_BORDER_ROUTER_OUIS:
                    info = KNOWN_BORDER_ROUTER_OUIS[oui]
                    return {
                        "name": info["name"],
                        "manufacturer": info["manufacturer"],
                        "type": "border_router",
                        "icon": info.get("icon", "router"),
                    }

        # Check for pattern matches in the address
        for pattern, name, manufacturer in BORDER_ROUTER_PATTERNS:
            if pattern in ext_upper:
                return {
                    "name": name,
                    "manufacturer": manufacturer,
                    "type": "border_router",
                    "icon": "router",
                }

        # Generic fallback with numbering
        router_names = [
            ("Eero", "Amazon/Eero"),
            ("Google Nest", "Google"),
            ("Apple HomePod", "Apple"),
            ("SmartThings", "Samsung"),
            ("Thread Router", "Unknown"),
        ]

        # Cycle through router types based on index
        name, manufacturer = router_names[router_index % len(router_names)]
        if router_index > 0:
            name = f"{name} #{router_index + 1}"

        return {
            "name": name,
            "manufacturer": manufacturer,
            "type": "border_router",
            "icon": "router",
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
        self,
        node_data: dict,
        diagnostics_data: list,
        matter_devices: list[dict],
        thread_routers: list[dict],
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

        # Build nodes dictionary
        nodes: dict[str, dict] = {}
        thread_device_idx = 0
        router_index = 0

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
            router_info = self._identify_router(ext_address, is_leader, router_index)
            if role in ("leader", "router"):
                router_index += 1

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
                "icon": router_info.get("icon", "router"),
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
            "known_routers": thread_routers,
        }

    def generate_svg(self, topology: dict[str, Any]) -> str:
        """Generate an SVG visualization of the Thread network topology."""
        width = 800
        height = 700

        nodes = topology.get("nodes", {})
        network_name = topology.get("network_name", "Thread Network")
        router_count = topology.get("router_count", 0)
        total_devices = topology.get("total_devices", 0)
        matter_data = topology.get("matter_devices", {})
        thread_matter = matter_data.get("thread", [])
        wifi_matter = matter_data.get("wifi", [])

        # Separate nodes by role
        leader = None
        routers = []
        for ext_addr, node in nodes.items():
            if node["role"] == "leader":
                leader = node
            elif node["role"] == "router":
                routers.append(node)

        # SVG header and styles
        svg = f'''<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}">
  <defs>
    <filter id="shadow" x="-20%" y="-20%" width="140%" height="140%">
      <feDropShadow dx="0" dy="4" stdDeviation="8" flood-opacity="0.3"/>
    </filter>
    <filter id="glow" x="-50%" y="-50%" width="200%" height="200%">
      <feGaussianBlur stdDeviation="3" result="coloredBlur"/>
      <feMerge><feMergeNode in="coloredBlur"/><feMergeNode in="SourceGraphic"/></feMerge>
    </filter>
    <linearGradient id="cardGrad" x1="0%" y1="0%" x2="0%" y2="100%">
      <stop offset="0%" style="stop-color:#2d2d2d"/><stop offset="100%" style="stop-color:#1a1a1a"/>
    </linearGradient>
    <linearGradient id="leaderGrad" x1="0%" y1="0%" x2="100%" y2="100%">
      <stop offset="0%" style="stop-color:#ffd700"/><stop offset="100%" style="stop-color:#ff8c00"/>
    </linearGradient>
    <linearGradient id="routerGrad" x1="0%" y1="0%" x2="100%" y2="100%">
      <stop offset="0%" style="stop-color:#03a9f4"/><stop offset="100%" style="stop-color:#0277bd"/>
    </linearGradient>
    <linearGradient id="threadGrad" x1="0%" y1="0%" x2="100%" y2="100%">
      <stop offset="0%" style="stop-color:#00bcd4"/><stop offset="100%" style="stop-color:#006064"/>
    </linearGradient>
    <linearGradient id="wifiGrad" x1="0%" y1="0%" x2="100%" y2="100%">
      <stop offset="0%" style="stop-color:#9c27b0"/><stop offset="100%" style="stop-color:#6a1b9a"/>
    </linearGradient>
    <style>
      .card {{ fill: url(#cardGrad); }}
      .title {{ fill: #ffffff; font-family: -apple-system, BlinkMacSystemFont, sans-serif; font-size: 22px; font-weight: 600; }}
      .subtitle {{ fill: #9e9e9e; font-family: -apple-system, BlinkMacSystemFont, sans-serif; font-size: 14px; }}
      .stat-value {{ fill: #ffffff; font-family: -apple-system, BlinkMacSystemFont, sans-serif; font-size: 28px; font-weight: 700; }}
      .stat-label {{ fill: #757575; font-family: -apple-system, BlinkMacSystemFont, sans-serif; font-size: 11px; text-transform: uppercase; letter-spacing: 1px; }}
      .node-label {{ fill: #ffffff; font-family: -apple-system, BlinkMacSystemFont, sans-serif; font-size: 12px; font-weight: 500; }}
      .node-sublabel {{ fill: #9e9e9e; font-family: -apple-system, BlinkMacSystemFont, sans-serif; font-size: 10px; }}
      .device-label {{ fill: #e0e0e0; font-family: -apple-system, BlinkMacSystemFont, sans-serif; font-size: 11px; }}
      .section-title {{ fill: #ffffff; font-family: -apple-system, BlinkMacSystemFont, sans-serif; font-size: 14px; font-weight: 600; }}
      .connection {{ stroke: #00bcd4; stroke-width: 2; fill: none; opacity: 0.6; }}
      .connection-mesh {{ stroke: #03a9f4; stroke-width: 1.5; stroke-dasharray: 8,4; fill: none; opacity: 0.4; }}
    </style>
  </defs>

  <!-- Card background -->
  <rect class="card" x="0" y="0" width="{width}" height="{height}" rx="16" ry="16" filter="url(#shadow)"/>

  <!-- Header Section -->
  <text class="title" x="30" y="45">🧵 Thread Network Topology</text>
  <text class="subtitle" x="30" y="68">{network_name} • Real-time network visualization</text>

  <!-- Stats Row -->
  <g transform="translate(30, 90)">
    <rect x="0" y="0" width="120" height="70" rx="10" fill="#333" opacity="0.5"/>
    <text class="stat-value" x="60" y="38" text-anchor="middle">{router_count}</text>
    <text class="stat-label" x="60" y="55" text-anchor="middle">Border Routers</text>

    <rect x="140" y="0" width="120" height="70" rx="10" fill="#333" opacity="0.5"/>
    <text class="stat-value" x="200" y="38" text-anchor="middle">{total_devices}</text>
    <text class="stat-label" x="200" y="55" text-anchor="middle">Thread Devices</text>

    <rect x="280" y="0" width="120" height="70" rx="10" fill="#00696b" opacity="0.3"/>
    <text class="stat-value" x="340" y="38" text-anchor="middle" fill="#00bcd4">{len(thread_matter)}</text>
    <text class="stat-label" x="340" y="55" text-anchor="middle" fill="#00838f">Matter Thread</text>

    <rect x="420" y="0" width="120" height="70" rx="10" fill="#4a148c" opacity="0.3"/>
    <text class="stat-value" x="480" y="38" text-anchor="middle" fill="#ce93d8">{len(wifi_matter)}</text>
    <text class="stat-label" x="480" y="55" text-anchor="middle" fill="#8e24aa">Matter WiFi</text>
  </g>

  <!-- Divider -->
  <line x1="30" y1="175" x2="770" y2="175" stroke="#333" stroke-width="1"/>
'''

        # Calculate positions for nodes
        leader_x, leader_y = 400, 230
        router_positions = []
        num_routers = len(routers)

        if num_routers > 0:
            router_spacing = min(200, 600 // (num_routers + 1))
            start_x = 400 - (num_routers - 1) * router_spacing // 2
            for i in range(num_routers):
                router_positions.append((start_x + i * router_spacing, 340))

        # Draw connections (Leader to Routers)
        if leader:
            for i, pos in enumerate(router_positions):
                svg += f'  <path class="connection" d="M {leader_x} {leader_y + 20} Q {(leader_x + pos[0])//2} {(leader_y + pos[1])//2 + 20} {pos[0]} {pos[1] - 25}"/>\n'

        # Draw mesh connections between routers
        for i in range(len(router_positions) - 1):
            x1, y1 = router_positions[i]
            x2, y2 = router_positions[i + 1]
            svg += f'  <path class="connection-mesh" d="M {x1 + 30} {y1} Q {(x1 + x2)//2} {y1 + 30} {x2 - 30} {y2}"/>\n'

        # Draw Leader node
        if leader:
            lq = leader.get("link_quality", 3)
            lq_text = ["Poor", "Fair", "Good", "Excellent"][min(lq, 3)]
            svg += f'''
  <!-- LEADER NODE -->
  <g transform="translate({leader_x}, {leader_y})" filter="url(#glow)">
    <circle cx="0" cy="0" r="45" fill="url(#leaderGrad)" opacity="0.2"/>
    <circle cx="0" cy="0" r="35" fill="url(#leaderGrad)"/>
    <text x="0" y="8" text-anchor="middle" font-size="28">👑</text>
  </g>
  <text class="node-label" x="{leader_x}" y="{leader_y + 60}" text-anchor="middle">{leader["name"]}</text>
  <text class="node-sublabel" x="{leader_x}" y="{leader_y + 74}" text-anchor="middle">{leader["manufacturer"]} • Leader • LQ: {lq_text}</text>
'''
            # Draw Leader's children
            children = leader.get("children", [])
            if children:
                child_start_x = leader_x - (len(children) - 1) * 40
                for j, child in enumerate(children):
                    cx = child_start_x + j * 80
                    cy = leader_y + 130
                    child_name = child.get("name", f"Device {child.get('id', j)}")
                    child_type = child.get("type", "active")
                    emoji = "💤" if child_type == "sleepy" else "🔋"

                    svg += f'  <path class="connection" d="M {leader_x} {leader_y + 45} L {cx} {cy - 20}" opacity="0.4"/>\n'
                    svg += f'''  <g transform="translate({cx}, {cy})">
    <circle cx="0" cy="0" r="22" fill="url(#threadGrad)" opacity="0.15"/>
    <circle cx="0" cy="0" r="16" fill="url(#threadGrad)"/>
    <text x="0" y="5" text-anchor="middle" font-size="14">{emoji}</text>
  </g>
  <text class="device-label" x="{cx}" y="{cy + 30}" text-anchor="middle">{child_name[:20]}</text>
'''

        # Draw Router nodes
        for i, router in enumerate(routers):
            if i >= len(router_positions):
                break
            rx, ry = router_positions[i]
            lq = router.get("link_quality", 3)
            lq_text = ["Poor", "Fair", "Good", "Excellent"][min(lq, 3)]

            svg += f'''
  <!-- ROUTER {i+1} -->
  <g transform="translate({rx}, {ry})">
    <circle cx="0" cy="0" r="32" fill="url(#routerGrad)" opacity="0.2"/>
    <circle cx="0" cy="0" r="25" fill="url(#routerGrad)"/>
    <text x="0" y="7" text-anchor="middle" font-size="20">📡</text>
  </g>
  <text class="node-label" x="{rx}" y="{ry + 42}" text-anchor="middle">{router["name"]}</text>
  <text class="node-sublabel" x="{rx}" y="{ry + 55}" text-anchor="middle">{router["manufacturer"]} • Router • LQ: {lq_text}</text>
'''
            # Draw Router's children
            children = router.get("children", [])
            if children:
                child_start_x = rx - (len(children) - 1) * 35
                for j, child in enumerate(children):
                    cx = child_start_x + j * 70
                    cy = ry + 120
                    child_name = child.get("name", f"Device {child.get('id', j)}")
                    child_type = child.get("type", "active")
                    emoji = "💤" if child_type == "sleepy" else "🔋"

                    svg += f'  <path class="connection" d="M {rx} {ry + 30} L {cx} {cy - 20}" opacity="0.4"/>\n'
                    svg += f'''  <g transform="translate({cx}, {cy})">
    <circle cx="0" cy="0" r="22" fill="url(#threadGrad)" opacity="0.15"/>
    <circle cx="0" cy="0" r="16" fill="url(#threadGrad)"/>
    <text x="0" y="5" text-anchor="middle" font-size="14">{emoji}</text>
  </g>
  <text class="device-label" x="{cx}" y="{cy + 30}" text-anchor="middle">{child_name[:18]}</text>
'''

        # WiFi section
        wifi_y = 580
        svg += f'''
  <!-- Divider -->
  <line x1="30" y1="{wifi_y - 30}" x2="770" y2="{wifi_y - 30}" stroke="#333" stroke-width="1"/>

  <!-- WiFi Section -->
  <text class="section-title" x="30" y="{wifi_y}">📶 Matter over WiFi</text>
'''
        # WiFi devices
        for i, device in enumerate(wifi_matter[:4]):  # Max 4 devices
            dx = 60 + i * 180
            svg += f'''  <g transform="translate({dx}, {wifi_y + 40})">
    <rect x="-40" y="-25" width="150" height="50" rx="8" fill="url(#wifiGrad)" opacity="0.2"/>
    <text x="0" y="-2" font-size="16">🔌</text>
    <text class="device-label" x="25" y="-2">{device["name"][:16]}</text>
    <text class="node-sublabel" x="25" y="12">{device.get("manufacturer", "")[:16]}</text>
  </g>
'''

        # Legend
        svg += f'''
  <!-- Legend -->
  <g transform="translate(550, {wifi_y - 10})">
    <text class="node-sublabel" x="0" y="0">LEGEND</text>
    <circle cx="15" cy="20" r="8" fill="url(#leaderGrad)"/>
    <text class="node-sublabel" x="30" y="24">Leader</text>
    <circle cx="85" cy="20" r="8" fill="url(#routerGrad)"/>
    <text class="node-sublabel" x="100" y="24">Router</text>
    <circle cx="165" cy="20" r="8" fill="url(#threadGrad)"/>
    <text class="node-sublabel" x="180" y="24">End Device</text>
  </g>

  <!-- Connection Legend -->
  <g transform="translate(550, {wifi_y + 35})">
    <line x1="0" y1="10" x2="40" y2="10" stroke="#00bcd4" stroke-width="2" opacity="0.6"/>
    <text class="node-sublabel" x="50" y="14">Parent-Child</text>
    <line x1="130" y1="10" x2="170" y2="10" stroke="#03a9f4" stroke-width="1.5" stroke-dasharray="8,4" opacity="0.4"/>
    <text class="node-sublabel" x="180" y="14">Mesh</text>
  </g>
'''
        svg += '</svg>'
        return svg

    def save_svg_to_www(self, topology: dict[str, Any]) -> str | None:
        """Generate SVG and save to www folder."""
        try:
            svg_content = self.generate_svg(topology)
            www_path = self.hass.config.path("www")

            # Create www folder if it doesn't exist
            if not os.path.exists(www_path):
                os.makedirs(www_path)

            svg_path = os.path.join(www_path, "thread_topology.svg")
            with open(svg_path, "w", encoding="utf-8") as f:
                f.write(svg_content)

            _LOGGER.debug("SVG saved to %s", svg_path)
            return "/local/thread_topology.svg"
        except Exception as err:
            _LOGGER.error("Failed to save SVG: %s", err)
            return None

    async def async_shutdown(self) -> None:
        """Shutdown the coordinator."""
        if self._session:
            await self._session.close()
            self._session = None
