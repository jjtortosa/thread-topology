"""Data coordinator for Thread Topology."""
from __future__ import annotations

import asyncio
import json
import logging
import os
from datetime import timedelta
from pathlib import Path
from typing import Any
from xml.sax.saxutils import escape as _xml_escape

import aiohttp
import yaml
from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

# Optional import - Matter integration may not be loaded
try:
    from homeassistant.components.matter.helpers import get_matter
    _MATTER_AVAILABLE = True
except ImportError:
    _MATTER_AVAILABLE = False

from .const import (
    API_MODE_JSONAPI,
    API_MODE_LEGACY,
    API_MODE_UNKNOWN,
    CONTENT_TYPE_JSONAPI,
    DEFAULT_SCAN_INTERVAL,
    DEVICE_COLLECTION_ATTRS,
    DIAGNOSTIC_TASK_TIMEOUT,
    DIAGNOSTIC_TYPES,
    DOMAIN,
    ENDPOINT_ACTIONS,
    ENDPOINT_API_DIAGNOSTICS,
    ENDPOINT_DEVICES,
    ENDPOINT_DIAGNOSTICS,
    ENDPOINT_NODE,
    JSONAPI_SCAN_INTERVAL,
    MATTER_NODE_TIMEOUT,
    REQUEST_TIMEOUT,
    ROUTING_ROLES,
    TASK_POLL_INTERVAL,
    TASK_TIMEOUT,
)

_LOGGER = logging.getLogger(__name__)

CUSTOM_ROUTERS_FILE = "custom_routers.yaml"


class OtbrTaskError(Exception):
    """A JSON:API diagnostic task failed, was stopped, or timed out."""

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

# Fallback identification by how an extended address ends.
#
# Anchored to the end of the address, and kept long enough to mean something.
# An earlier version matched these as substrings anywhere in the address and
# included the bare "EA", which labels roughly one address in eighteen as an
# Eero - and did, on hardware that was nothing of the sort.
BORDER_ROUTER_ADDRESS_SUFFIXES = [
    # Suffix, name, manufacturer
    ("EA17", "Eero", "Amazon/Eero"),
]


TRANSPORT_THREAD = "thread"
TRANSPORT_WIFI = "wifi"
TRANSPORT_UNKNOWN = "unknown"

# Manufacturers whose Matter range is Wi-Fi only. Used only as a fallback when
# the node itself has not told us which radio it is on.
WIFI_ONLY_MANUFACTURERS = frozenset({"nuki", "wemo", "lifx"})

# Product names spell it every which way; "wifi" alone misses "Wi-Fi", which is
# how TP-Link's "Smart Wi-Fi Dimmer Switch" was being counted as a Thread device.
_WIFI_NAME_HINTS = ("wi-fi", "wifi", "wi fi")


def _normalize_address(address: str) -> str:
    """Normalize an extended address by stripping separators and uppercasing."""
    return address.replace(":", "").replace("-", "").replace(" ", "").upper()


def _svg_text(value: Any) -> str:
    """Escape a value for safe inclusion as SVG text content.

    Device, network and manufacturer names cross into the SVG straight from the
    Matter registry and OTBR, so they are untrusted. Without escaping, a name
    containing '&' or '<' produces invalid XML that breaks the whole image, and
    a crafted name ('</text><script>...') is a stored-XSS vector once the file
    is served from /local. Truncate the raw value *before* calling this, never
    after, so a multi-character entity like '&amp;' is never sliced in half.
    """
    return _xml_escape("" if value is None else str(value))


def _matter_node_id(identifiers: Any) -> int | None:
    """Find the Matter node id among a device's "matter" identifiers.

    Home Assistant stores more than one: a
    "deviceid_<fabric_hex>-<node_hex>-MatterNodeDevice" and a
    "serial_<serial>". device.identifiers is a *set*, so reading whichever came
    out first picked a different identifier between runs, and whenever it landed
    on the serial - which carries no node id - the device silently lost its
    diagnostics. That is what made Matter device identity flicker restart to
    restart. Only the deviceid form is parsed, so a serial containing a dash
    cannot be mistaken for one.
    """
    for value in identifiers:
        if not isinstance(value, str) or not value.startswith("deviceid_"):
            continue
        parts = value[len("deviceid_"):].split("-")
        if len(parts) < 2:
            continue
        try:
            return int(parts[1], 16)
        except ValueError:
            continue
    return None


def _enum_value(value: Any) -> Any:
    """Unwrap an Enum to its value, leaving plain values alone."""
    return getattr(value, "value", value)


def _parse_node_diagnostics(diagnostics: Any) -> dict[str, Any]:
    """Pull what we need out of a matter-server NodeDiagnostics.

    Read defensively: this crosses a library boundary, and the field holding the
    IP list is spelled "ip_adresses" upstream - the kind of thing that gets
    corrected without warning.
    """
    transport = _enum_value(getattr(diagnostics, "network_type", None))
    transport = str(transport).lower() if transport is not None else TRANSPORT_UNKNOWN

    node_type = _enum_value(getattr(diagnostics, "node_type", None))

    addresses = getattr(diagnostics, "ip_adresses", None)
    if addresses is None:
        addresses = getattr(diagnostics, "ip_addresses", None)

    return {
        "transport": transport,
        "mac_address": getattr(diagnostics, "mac_address", None),
        "ip_addresses": list(addresses) if isinstance(addresses, (list, tuple)) else [],
        "available": bool(getattr(diagnostics, "available", True)),
        "node_type": str(node_type).lower() if node_type is not None else None,
    }


def _guess_transport(model: str | None, name: str | None, manufacturer: str | None) -> str:
    """Guess a device's radio when matter-server reported nothing for the node.

    Deliberately never returns "thread". Assuming Thread by default is what put
    Wi-Fi bulbs into the mesh as Thread children; an honest "unknown" keeps them
    out of the topology instead of inventing a place for them.
    """
    haystack = f"{model or ''} {name or ''}".lower()
    if any(hint in haystack for hint in _WIFI_NAME_HINTS):
        return TRANSPORT_WIFI
    if (manufacturer or "").lower() in WIFI_ONLY_MANUFACTURERS:
        return TRANSPORT_WIFI
    return TRANSPORT_UNKNOWN


# --- JSON:API -> legacy translation ----------------------------------------
#
# Current ot-br-posix builds return camelCase fields wrapped in a JSON:API
# envelope. Everything downstream of the fetch layer (_process_topology, the
# sensors, the SVG) reads the legacy flat PascalCase shape, so we translate on
# the way in rather than touching all of it.
#
# The translation is not purely a case change:
#   * Rloc16 is a hex string ("0xf800") here, an int in the legacy API. The
#     downstream code does arithmetic on it, so it must come out as an int.
#   * Mode.FullThreadDevice was renamed deviceTypeFTD, and legacy Mode flags
#     are 0/1 ints rather than booleans.
#   * /node renamed NumOfRouter to routerCount outright.


def _parse_rloc(value: Any) -> int | None:
    """Parse an RLOC16 given as an int or a hex string like '0xf800'."""
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    text = str(value).strip()
    if not text:
        return None
    try:
        return int(text, 16)
    except ValueError:
        return None


def _first(mapping: dict, *names: str, default: Any = None) -> Any:
    """Return the first present, non-None value among `names`."""
    for name in names:
        if mapping.get(name) is not None:
            return mapping[name]
    return default


def _link_margin_to_lqi(margin: Any) -> int:
    """Map a link margin in dB to OpenThread's 0-3 link quality scale."""
    if not isinstance(margin, (int, float)):
        return 0
    if margin >= 20:
        return 3
    if margin >= 10:
        return 2
    if margin >= 2:
        return 1
    return 0


def _translate_mode(mode: Any) -> dict[str, int]:
    """Translate a JSON:API mode object into the legacy Mode shape."""
    if not isinstance(mode, dict):
        return {}

    def flag(*names: str) -> int:
        value = _first(mode, *names)
        return int(bool(value))

    return {
        "RxOnWhenIdle": flag("rxOnWhenIdle", "RxOnWhenIdle"),
        "DeviceType": flag("deviceTypeFTD", "fullThreadDevice", "DeviceType"),
        "NetworkData": flag("fullNetworkData", "NetworkData"),
    }


def _translate_connectivity(connectivity: Any) -> dict[str, int]:
    """Translate a JSON:API connectivity object into the legacy shape.

    This is what the per-node link quality sensors are built from.
    """
    if not isinstance(connectivity, dict):
        return {}

    def num(*names: str) -> int:
        value = _first(connectivity, *names, default=0)
        return int(value) if isinstance(value, (int, float)) else 0

    return {
        "ParentPriority": num("parentPriority", "ParentPriority"),
        "LinkQuality3": num("linkQuality3", "LinkQuality3"),
        "LinkQuality2": num("linkQuality2", "LinkQuality2"),
        "LinkQuality1": num("linkQuality1", "LinkQuality1"),
        "LeaderCost": num("leaderCost", "LeaderCost"),
        "IdSequence": num("idSequence", "IdSequence"),
        "ActiveRouters": num("activeRouters", "ActiveRouters"),
    }


def _translate_route_data(attributes: dict) -> list[dict]:
    """Build the legacy Route.RouteData list.

    Prefers the real route table. Some builds return only routerNeighbors, in
    which case we synthesize equivalent entries with link quality derived from
    the neighbour's link margin.
    """
    route = attributes.get("route")
    entries = route.get("routeData") if isinstance(route, dict) else None

    if isinstance(entries, list):
        return [
            {
                "RouteId": _first(entry, "routeId", "RouteId", default=0),
                "LinkQualityIn": _first(entry, "linkQualityIn", "LinkQualityIn", default=0),
                "LinkQualityOut": _first(entry, "linkQualityOut", "LinkQualityOut", default=0),
                "RouteCost": _first(entry, "routeCost", "RouteCost", default=0),
            }
            for entry in entries
            if isinstance(entry, dict)
        ]

    neighbors = attributes.get("routerNeighbors")
    if not isinstance(neighbors, list):
        return []

    route_data = []
    for neighbor in neighbors:
        if not isinstance(neighbor, dict):
            continue
        peer_rloc = _parse_rloc(_first(neighbor, "rloc16", "addr"))
        lqi = _link_margin_to_lqi(neighbor.get("linkMargin"))
        route_data.append({
            "RouteId": (peer_rloc >> 10) if peer_rloc is not None else 0,
            "LinkQualityIn": lqi,
            "LinkQualityOut": lqi,
            "RouteCost": 0,
        })
    return route_data


def _translate_child_table(attributes: dict) -> list[dict]:
    """Build the legacy ChildTable from the childTable and children arrays.

    Both may be present and they carry different fields: childTable mirrors the
    legacy TLV, while children additionally exposes each child's extended
    address and RLOC16. We merge them by child id, letting childTable win on
    fields they share.
    """
    rows: dict[Any, dict] = {}
    order: list[Any] = []

    for source in ("children", "childTable"):
        entries = attributes.get(source)
        if not isinstance(entries, list):
            continue
        for entry in entries:
            if not isinstance(entry, dict):
                continue

            rloc = _parse_rloc(entry.get("rloc16"))
            child_id = entry.get("childId")
            if child_id is None and rloc is not None:
                child_id = rloc & 0x1FF

            key = child_id if child_id is not None else f"#{len(order)}"
            row = rows.get(key)
            if row is None:
                row = {"ChildId": child_id if child_id is not None else 0}
                rows[key] = row
                order.append(key)

            # In children[] the mode flags sit at the top level; in
            # childTable[] they are nested under "mode".
            mode_src = entry.get("mode") if isinstance(entry.get("mode"), dict) else entry
            translated_mode = _translate_mode(mode_src)
            if translated_mode:
                row["Mode"] = translated_mode

            if isinstance(entry.get("timeout"), int):
                row["Timeout"] = entry["timeout"]
            if isinstance(entry.get("linkQuality"), int):
                row["LinkQuality"] = entry["linkQuality"]
            if entry.get("extAddress"):
                row["ExtAddress"] = entry["extAddress"]
            if rloc is not None:
                row["Rloc16"] = rloc
            addresses = entry.get("ipv6Addresses")
            if isinstance(addresses, list) and addresses:
                row["IP6AddressList"] = addresses

    return [rows[key] for key in order]


def _translate_diagnostic(item: Any) -> dict[str, Any]:
    """Convert one JSON:API networkDiagnostics item to the legacy flat shape."""
    attributes = item.get("attributes") if isinstance(item, dict) else None
    if not isinstance(attributes, dict):
        return {}

    rloc = _parse_rloc(attributes.get("rloc16"))
    result: dict[str, Any] = {
        "ExtAddress": attributes.get("extAddress", ""),
        "Rloc16": rloc if rloc is not None else 0,
        "IP6AddressList": attributes.get("ipv6Addresses") or [],
    }

    mode = _translate_mode(attributes.get("mode"))
    if mode:
        result["Mode"] = mode

    connectivity = _translate_connectivity(attributes.get("connectivity"))
    if connectivity:
        result["Connectivity"] = connectivity

    route_data = _translate_route_data(attributes)
    if route_data:
        result["Route"] = {"RouteData": route_data}

    child_table = _translate_child_table(attributes)
    if child_table:
        result["ChildTable"] = child_table

    if attributes.get("leaderData"):
        result["LeaderData"] = attributes["leaderData"]

    # Authoritative leader flag - far better than inferring the leader from
    # whichever node happens to be the OTBR we are talking to.
    if attributes.get("isLeader") is not None:
        result["IsLeader"] = bool(attributes["isLeader"])
    if attributes.get("isBorderRouter") is not None:
        result["IsBorderRouter"] = bool(attributes["isBorderRouter"])

    return result


# /node kept its route but renamed its fields; NumOfRouter became routerCount.
_NODE_FIELD_ALIASES = {
    "ExtAddress": ("ExtAddress", "extAddress"),
    "NetworkName": ("NetworkName", "networkName"),
    "NumOfRouter": ("NumOfRouter", "routerCount"),
    "State": ("State", "state"),
    "Rloc16": ("Rloc16", "rloc16"),
    "LeaderData": ("LeaderData", "leaderData"),
    "ExtPanId": ("ExtPanId", "extPanId"),
    "RlocAddress": ("RlocAddress", "rlocAddress"),
}


def _translate_node(node_data: Any) -> dict[str, Any]:
    """Normalize a /node response to the legacy PascalCase key names.

    Original keys are preserved; canonical ones are added alongside, so this is
    a no-op on OTBR builds that already speak PascalCase.
    """
    if not isinstance(node_data, dict):
        return {}

    result = dict(node_data)
    for canonical, aliases in _NODE_FIELD_ALIASES.items():
        value = _first(node_data, *aliases)
        if value is not None:
            result[canonical] = value

    rloc = _parse_rloc(result.get("Rloc16"))
    if rloc is not None:
        result["Rloc16"] = rloc

    return result


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
        self._custom_routers: list[dict[str, str]] = self._load_custom_routers()
        self._api_mode = API_MODE_UNKNOWN
        # Last known Matter identity per node. A node's MAC and radio are
        # stable facts, so remembering them keeps names on the map when
        # matter-server is briefly unable to answer.
        self._matter_node_cache: dict[int, dict[str, Any]] = {}

    def _load_custom_routers(self) -> list[dict[str, str]]:
        """Load user-defined border routers from custom_routers.yaml."""
        config_dir = Path(__file__).parent
        yaml_path = config_dir / CUSTOM_ROUTERS_FILE

        if not yaml_path.exists():
            return []

        try:
            with open(yaml_path, encoding="utf-8") as f:
                data = yaml.safe_load(f)

            if not data or "routers" not in data:
                return []

            routers = []
            for entry in data["routers"]:
                address = entry.get("address", "")
                name = entry.get("name", "Custom Router")
                manufacturer = entry.get("manufacturer", "Unknown")
                icon = entry.get("icon", "router")

                if not address:
                    _LOGGER.warning("Skipping custom router entry with no address")
                    continue

                routers.append({
                    "address": _normalize_address(address),
                    "name": name,
                    "manufacturer": manufacturer,
                    "icon": icon,
                })

            _LOGGER.info("Loaded %d custom router(s) from %s", len(routers), yaml_path)
            return routers

        except yaml.YAMLError as err:
            _LOGGER.error("Error parsing %s: %s", yaml_path, err)
            return []
        except OSError as err:
            _LOGGER.error("Error reading %s: %s", yaml_path, err)
            return []

    async def _async_update_data(self) -> dict[str, Any]:
        """Fetch data from OTBR API."""
        try:
            if self._session is None:
                self._session = aiohttp.ClientSession()

            # Reset router index for each update
            self._router_index = 0

            # Fetch node info. Field names differ between REST generations, so
            # normalize before anything downstream reads it.
            node_data = _translate_node(await self._fetch_endpoint(ENDPOINT_NODE))

            # Fetch diagnostics (topology)
            diagnostics_data = await self._fetch_diagnostics()

            # Get Matter devices from HA device registry
            matter_devices = await self._async_get_matter_devices()

            # Get Thread Border Routers from HA device registry
            thread_routers = self._get_thread_border_routers()

            # Process and combine data
            topology = self._process_topology(
                node_data, diagnostics_data, matter_devices, thread_routers
            )

            # Generate and save SVG to www folder
            await self.save_svg_to_www(topology)

            return topology

        except aiohttp.ClientError as err:
            raise UpdateFailed(f"Error communicating with OTBR: {err}") from err
        except TimeoutError as err:
            raise UpdateFailed(f"Timeout communicating with OTBR: {err}") from err
        except OtbrTaskError as err:
            raise UpdateFailed(f"OTBR diagnostic task failed: {err}") from err

    async def _fetch_endpoint(self, endpoint: str) -> Any:
        """Fetch data from a specific OTBR endpoint."""
        url = f"{self.otbr_url}{endpoint}"
        async with self._session.get(
            url, timeout=aiohttp.ClientTimeout(total=REQUEST_TIMEOUT)
        ) as response:
            response.raise_for_status()
            # OTBR serves JSON:API routes as application/vnd.api+json, which
            # aiohttp refuses to decode unless we stop it checking.
            return await response.json(content_type=None)

    # --- diagnostics fetching ----------------------------------------------

    async def _fetch_diagnostics(self) -> list[dict[str, Any]]:
        """Fetch mesh diagnostics, auto-detecting which REST API is served.

        Legacy builds answer GET /diagnostics directly. Current builds return
        404 there and require a JSON:API task workflow instead. We probe once
        and remember, but re-probe if a legacy OTBR is later upgraded.
        """
        if self._api_mode != API_MODE_JSONAPI:
            try:
                data = await self._fetch_endpoint(ENDPOINT_DIAGNOSTICS)
            except aiohttp.ClientResponseError as err:
                if err.status != 404:
                    raise
                _LOGGER.info(
                    "OTBR has no legacy /diagnostics endpoint (404); "
                    "using the JSON:API task workflow"
                )
                self._set_api_mode(API_MODE_JSONAPI)
            else:
                self._set_api_mode(API_MODE_LEGACY)
                return data if isinstance(data, list) else [data]

        return await self._fetch_diagnostics_jsonapi()

    def _set_api_mode(self, mode: str) -> None:
        """Record which REST generation the OTBR speaks.

        The JSON:API flow makes OTBR crawl the whole mesh, which takes longer
        than the legacy poll interval, so stretch the interval to match.
        """
        if self._api_mode == mode:
            return

        self._api_mode = mode
        _LOGGER.debug("OTBR API mode set to %s", mode)

        if mode != API_MODE_JSONAPI:
            return

        slower = timedelta(seconds=JSONAPI_SCAN_INTERVAL)
        if self.update_interval is not None and self.update_interval < slower:
            _LOGGER.info(
                "Raising scan interval to %ss: the JSON:API mesh crawl takes "
                "longer than the configured %ss",
                JSONAPI_SCAN_INTERVAL,
                int(self.update_interval.total_seconds()),
            )
            self.update_interval = slower

    async def _fetch_diagnostics_jsonapi(self) -> list[dict[str, Any]]:
        """Run the three-step JSON:API diagnostic workflow."""
        # 1. Ask OTBR to crawl the mesh, which is what populates /api/devices.
        task_id = await self._post_action({
            "type": "updateDeviceCollectionTask",
            "attributes": DEVICE_COLLECTION_ATTRS,
        })
        await self._wait_for_task(task_id, "device collection")

        # 2. Learn which devices are worth querying.
        payload = await self._fetch_json(ENDPOINT_DEVICES)
        devices = payload.get("data") or []
        routers = [
            device for device in devices
            if str((device.get("attributes") or {}).get("role") or "").lower()
            in ROUTING_ROLES
        ]
        if not routers:
            # Some builds leave role empty until the crawl settles.
            _LOGGER.debug("No routing-role devices reported; querying all %d", len(devices))
            routers = devices

        _LOGGER.debug("Device collection: %d total, %d routing", len(devices), len(routers))

        # 3. Ask each router for its diagnostics, concurrently.
        results = await asyncio.gather(
            *(self._fetch_router_diagnostic(device) for device in routers)
        )

        diagnostics = [
            translated
            for item in results
            if item and (translated := _translate_diagnostic(item))
        ]

        if not diagnostics:
            raise OtbrTaskError(
                f"no diagnostics returned by any of {len(routers)} device(s)"
            )

        _LOGGER.debug(
            "Collected diagnostics from %d/%d router(s)", len(diagnostics), len(routers)
        )
        return diagnostics

    async def _fetch_router_diagnostic(self, device: dict) -> dict | None:
        """Request and collect one router's network diagnostic."""
        device_id = device.get("id")
        try:
            task_id = await self._post_action({
                "type": "getNetworkDiagnosticTask",
                "attributes": {
                    "destination": device_id,
                    "types": DIAGNOSTIC_TYPES,
                    "timeout": DIAGNOSTIC_TASK_TIMEOUT,
                },
            })
            task = await self._wait_for_task(task_id, f"diagnostic {device_id}")

            # The finished task points at the stored diagnostic document.
            relationships = task.get("relationships") or {}
            result_ref = (relationships.get("result") or {}).get("data") or {}
            diagnostic_id = result_ref.get("id")
            if not diagnostic_id:
                _LOGGER.debug("Task for %s produced no diagnostic result", device_id)
                return None

            payload = await self._fetch_json(f"{ENDPOINT_API_DIAGNOSTICS}/{diagnostic_id}")
            return payload.get("data")
        except (TimeoutError, aiohttp.ClientError, OtbrTaskError) as err:
            # One unreachable router should not fail the whole update.
            _LOGGER.debug("Skipping diagnostics for %s: %s", device_id, err)
            return None

    async def _fetch_json(self, endpoint: str) -> dict[str, Any]:
        """GET a JSON:API endpoint."""
        url = f"{self.otbr_url}{endpoint}"
        async with self._session.get(
            url,
            headers={"Accept": CONTENT_TYPE_JSONAPI},
            timeout=aiohttp.ClientTimeout(total=REQUEST_TIMEOUT),
        ) as response:
            response.raise_for_status()
            return await response.json(content_type=None)

    async def _post_action(self, task: dict[str, Any]) -> str:
        """POST a task to /api/actions and return its id."""
        url = f"{self.otbr_url}{ENDPOINT_ACTIONS}"
        async with self._session.post(
            url,
            data=json.dumps({"data": [task]}),
            headers={
                "Accept": CONTENT_TYPE_JSONAPI,
                "Content-Type": CONTENT_TYPE_JSONAPI,
            },
            timeout=aiohttp.ClientTimeout(total=REQUEST_TIMEOUT),
        ) as response:
            response.raise_for_status()
            payload = await response.json(content_type=None)

        data = payload.get("data")
        items = data if isinstance(data, list) else [data]
        if not items or not isinstance(items[0], dict) or not items[0].get("id"):
            raise OtbrTaskError(f"{ENDPOINT_ACTIONS} returned no task id")
        return items[0]["id"]

    async def _wait_for_task(self, task_id: str, label: str) -> dict[str, Any]:
        """Poll a task until it completes."""
        loop = asyncio.get_running_loop()
        deadline = loop.time() + TASK_TIMEOUT

        while loop.time() < deadline:
            await asyncio.sleep(TASK_POLL_INTERVAL)
            try:
                payload = await self._fetch_json(f"{ENDPOINT_ACTIONS}/{task_id}")
            except (TimeoutError, aiohttp.ClientError):
                continue  # transient; try again on the next poll

            item = payload.get("data") or payload
            status = str((item.get("attributes") or {}).get("status") or "").lower()
            if status == "completed":
                return item
            if status in ("stopped", "failed"):
                raise OtbrTaskError(f"task '{label}' {status}")

        raise OtbrTaskError(f"task '{label}' timed out after {TASK_TIMEOUT}s")

    async def _async_get_matter_devices(self) -> list[dict[str, Any]]:
        """Get Matter devices from Home Assistant device registry.

        Each device is annotated with the radio it is actually on and, for
        Thread devices, its extended address (EUI-64), so that downstream
        matching can key on hardware identity rather than iteration order.
        """
        device_registry = dr.async_get(self.hass)
        matter_devices = []

        diagnostics_by_node = await self._async_matter_node_diagnostics()

        for device in device_registry.devices.values():
            matter_identifiers = [
                value for domain, value in device.identifiers if domain == "matter"
            ]
            if not matter_identifiers:
                continue

            # Respect a name the user set in Home Assistant; device.name is the
            # factory name, which is identical across two of the same product.
            name = device.name_by_user or device.name or "Unknown"

            # Match the registry entry to its Matter node. Every matter
            # identifier is considered, because they arrive in arbitrary order.
            node_id = _matter_node_id(matter_identifiers)
            diagnostics: dict[str, Any] = (
                diagnostics_by_node.get(node_id, {}) if node_id is not None else {}
            )

            mac_address = diagnostics.get("mac_address")

            # Only guess the radio if matter-server told us nothing at all.
            transport = diagnostics.get("transport") or _guess_transport(
                device.model, name, device.manufacturer
            )

            matter_devices.append({
                "name": name,
                "model": device.model,
                "manufacturer": device.manufacturer,
                "identifiers": list(device.identifiers),
                "transport": transport,
                "ext_address": _normalize_address(mac_address) if mac_address else None,
                "ip_addresses": diagnostics.get("ip_addresses", []),
                "available": diagnostics.get("available"),
                "node_type": diagnostics.get("node_type"),
            })

        return matter_devices

    async def _async_matter_node_diagnostics(self) -> dict[int, dict[str, Any]]:
        """Ask matter-server for per-node diagnostics, keyed by node id.

        This is the same source Home Assistant's own Matter device page uses.
        An earlier implementation read GeneralDiagnostics.NetworkInterfaces from
        cached cluster attributes to stay synchronous, but that attribute is
        unreliable for battery powered sleepy end devices: their MAC address
        came and went between updates, and every name matched from it went with
        it. This method is async, which is what let us stop doing that.
        """
        if not _MATTER_AVAILABLE:
            return {}

        try:
            matter_client = get_matter(self.hass).matter_client
            nodes = list(matter_client.get_nodes())
        # IndexError covers get_matter() indexing into hass.data["matter"]
        # before the Matter integration has finished setting up - a restart
        # race that would otherwise fail the whole update over what is only
        # optional enrichment.
        except (KeyError, IndexError, StopIteration, AttributeError) as err:
            _LOGGER.debug("Matter client not available: %s", err)
            return dict(self._matter_node_cache)

        async def fetch(node: Any) -> tuple[int, dict[str, Any]] | None:
            node_id = getattr(node, "node_id", None)
            if node_id is None:
                return None
            try:
                diagnostics = await asyncio.wait_for(
                    matter_client.node_diagnostics(node_id=node_id),
                    timeout=MATTER_NODE_TIMEOUT,
                )
            except Exception as err:  # noqa: BLE001 - one node must not fail the update
                _LOGGER.debug("No Matter diagnostics for node %s: %s", node_id, err)
                return None
            return node_id, _parse_node_diagnostics(diagnostics)

        results = await asyncio.gather(*(fetch(node) for node in nodes))
        by_node = {node_id: data for node_id, data in filter(None, results)}

        # Keep what a node last told us. Otherwise a node that goes quiet for
        # one update drops its extended address, and every name matched from
        # it disappears from the map until it answers again.
        self._matter_node_cache.update(by_node)
        merged = dict(self._matter_node_cache)

        _LOGGER.debug(
            "Matter diagnostics: %d/%d node(s) reported, %d known in total",
            len(by_node), len(nodes), len(merged),
        )
        return merged

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
        self, ext_address: str, is_local_otbr: bool
    ) -> dict[str, str]:
        """Identify a router by its extended address or characteristics.

        `is_local_otbr` marks the border router this integration polls, which
        is named directly rather than guessed at from its OUI. Note this is a
        separate question from which node holds Thread leadership.
        """
        ext_normalized = _normalize_address(ext_address)

        # Check custom routers first (user-defined in custom_routers.yaml).
        # These take precedence over every built-in guess, including the name
        # for the border router we poll - plenty of OTBRs are not SkyConnects.
        for custom in self._custom_routers:
            custom_addr = custom["address"]
            # Exact full match, OUI prefix match (first 6 hex chars), or substring
            if (
                ext_normalized == custom_addr
                or (len(custom_addr) == 6 and ext_normalized[:6] == custom_addr)
                or (len(custom_addr) > 6 and custom_addr in ext_normalized)
            ):
                return {
                    "name": custom["name"],
                    "manufacturer": custom["manufacturer"],
                    "type": "border_router",
                    "icon": custom.get("icon", "router"),
                }

        # The OTBR we talk to, if the user has not named it themselves
        if is_local_otbr:
            return {
                "name": "SkyConnect (OTBR)",
                "manufacturer": "Nabu Casa",
                "type": "border_router",
                "icon": "home-assistant",
            }

        # Convert extended address to OUI format (XX:XX:XX)
        if len(ext_normalized) >= 6:
            # Try different OUI formats
            oui_formats = [
                f"{ext_normalized[0:2]}:{ext_normalized[2:4]}:{ext_normalized[4:6]}",
                f"{ext_normalized[-6:-4]}:{ext_normalized[-4:-2]}:{ext_normalized[-2:]}",
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

        # Check for a known address suffix. Anchored, not a substring search.
        for suffix, name, manufacturer in BORDER_ROUTER_ADDRESS_SUFFIXES:
            if ext_normalized.endswith(suffix):
                return {
                    "name": name,
                    "manufacturer": manufacturer,
                    "type": "border_router",
                    "icon": "router",
                }

        # Nothing identified it. Name the node after its own address instead of
        # guessing a vendor: this used to pick one from a list by iteration
        # order, so the first unrecognised router was labelled "Eero / Amazon"
        # regardless of what it actually was. A wrong-but-confident label is
        # worse than an honest one, and custom_routers.yaml exists to supply
        # the real name.
        suffix = ext_normalized[-4:] if ext_normalized else "unknown"
        return {
            "name": f"Thread Router {suffix}",
            "manufacturer": "Unknown",
            "type": "border_router",
            "icon": "router",
        }

    def _match_end_device(
        self,
        matter_devices: list[dict],
        claimed_ext_addresses: set[str],
        child_ext_address: str | None = None,
        child_ip6_addresses: list[str] | None = None,
    ) -> dict[str, Any] | None:
        """Try to match an end device with a Matter device.

        Matching is on identity only - the child's extended address, or failing
        that an overlap between its IPv6 addresses and a Matter device's. If
        neither identifies it, the child stays unnamed.

        There used to be a positional fallback here that handed out "the next
        unclaimed Thread device", which is how a Wi-Fi bulb ended up labelled as
        a Thread child of the border router. Current OTBR builds report each
        child's extended address, so the guess is no longer needed, and an
        unnamed child beats a confidently wrong one.
        """
        thread_devices = [
            d for d in matter_devices if d["transport"] == TRANSPORT_THREAD
        ]

        def unclaimed(device: dict) -> bool:
            ext = device.get("ext_address")
            return not ext or ext not in claimed_ext_addresses

        # Exact match on the child's own extended address.
        if child_ext_address:
            wanted = _normalize_address(child_ext_address)
            for device in thread_devices:
                if device.get("ext_address") == wanted and unclaimed(device):
                    return device

        # Otherwise match on a shared IPv6 address.
        if child_ip6_addresses:
            child_ip_set = {ip.lower() for ip in child_ip6_addresses}
            for device in thread_devices:
                if not unclaimed(device):
                    continue
                for ip in device.get("ip_addresses", []):
                    if ip.lower() in child_ip_set:
                        return device

        return None

    def _process_topology(
        self,
        node_data: dict,
        diagnostics_data: list,
        matter_devices: list[dict],
        thread_routers: list[dict],
    ) -> dict[str, Any]:
        """Process raw OTBR data into topology structure."""
        # /node describes the border router we are polling, which is not
        # necessarily the Thread leader - it may well be a plain router.
        local_ext_address = node_data.get("ExtAddress", "")
        network_name = node_data.get("NetworkName", "Unknown")
        num_routers = node_data.get("NumOfRouter", 0)
        state = node_data.get("State", "unknown")

        # Fall back to the polled OTBR until a node claims leadership.
        leader_ext_address = local_ext_address

        # Separate Thread and WiFi Matter devices
        # Devices whose radio we could not determine land in neither bucket -
        # counting them as Thread is what inflated the mesh device count.
        thread_matter = [d for d in matter_devices if d["transport"] == TRANSPORT_THREAD]
        wifi_matter = [d for d in matter_devices if d["transport"] == TRANSPORT_WIFI]

        # Build a lookup table: normalized ext_address -> Matter device.
        # This lets us match Thread mesh nodes to Matter devices by EUI-64
        # instead of by iteration order (which is what the old code did).
        matter_by_ext_addr: dict[str, dict] = {
            d["ext_address"]: d for d in thread_matter if d.get("ext_address")
        }

        # Track which Matter devices we've already bound to a router/leader so
        # we don't double-assign them when matching child end-devices.
        claimed_ext_addresses: set[str] = set()

        # Build nodes dictionary
        nodes: dict[str, dict] = {}
        local_ext_normalized = _normalize_address(local_ext_address)

        for diag in diagnostics_data:
            ext_address = diag.get("ExtAddress", "")
            ext_normalized = _normalize_address(ext_address)
            rloc16 = diag.get("Rloc16", 0)

            # Determine device role
            mode = diag.get("Mode", {})
            is_router = mode.get("DeviceType", 0) == 1
            is_local_otbr = bool(local_ext_normalized) and ext_normalized == local_ext_normalized

            # Current OTBR builds state outright which node holds leadership.
            # Legacy builds do not, so assume the OTBR we polled is the leader,
            # which is what this integration has always done.
            diag_is_leader = diag.get("IsLeader")
            is_leader = is_local_otbr if diag_is_leader is None else diag_is_leader
            if is_leader:
                leader_ext_address = ext_address

            if is_leader:
                role = "leader"
            elif is_router:
                role = "router"
            else:
                role = "end_device"

            # Try to match this router/leader to a Matter device by EUI-64.
            # If found, that device's friendly name overrides the OUI-based
            # router_info name (which only knows about a hardcoded list of OUIs).
            matter_self_match = matter_by_ext_addr.get(ext_normalized)
            if matter_self_match:
                claimed_ext_addresses.add(ext_normalized)

            # Get router identification (OUI lookup / custom_routers.yaml)
            router_info = self._identify_router(ext_address, is_local_otbr)

            # Override OUI-based name with Matter device name if we matched.
            if matter_self_match:
                node_name = matter_self_match["name"]
                node_manufacturer = (
                    matter_self_match["manufacturer"] or router_info["manufacturer"]
                )
            else:
                node_name = router_info["name"]
                node_manufacturer = router_info["manufacturer"]

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

            # Get children and try to match with Matter devices. Matching is on
            # identity - the child's own extended address where OTBR reports it,
            # otherwise a shared IPv6 address. A child we cannot identify is
            # left unnamed rather than assigned a plausible-looking device.
            child_table = diag.get("ChildTable", [])
            children = []
            for child in child_table:
                child_id = child.get("ChildId", 0)
                child_mode = child.get("Mode", {})
                child_type = "sleepy" if child_mode.get("RxOnWhenIdle", 1) == 0 else "active"

                # Legacy OTBR omits both of these; current builds report the
                # extended address in the children[] array.
                child_ip_list = child.get("IP6AddressList") or None

                matter_match = self._match_end_device(
                    matter_devices,
                    claimed_ext_addresses,
                    child.get("ExtAddress"),
                    child_ip_list,
                )
                if matter_match and matter_match.get("ext_address"):
                    claimed_ext_addresses.add(matter_match["ext_address"])

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
                "name": node_name,
                "manufacturer": node_manufacturer,
                "device_type": router_info["type"],
                "icon": router_info.get("icon", "router"),
                "link_quality": link_quality,
                "leader_cost": leader_cost,
                "children": children,
                "child_count": len(children),
                "connections": connections,
                "ip_addresses": diag.get("IP6AddressList", []),
            }

        # Surface any Matter Thread devices we never matched to the mesh,
        # so they show up in the visualizer as "offline" rather than just
        # disappearing. Old code did this implicitly via positional matching;
        # we make it explicit.
        unmatched_thread = [
            d for d in thread_matter
            if d.get("ext_address") and d["ext_address"] not in claimed_ext_addresses
        ]
        # Also include Matter Thread devices with no ext_address known
        # (e.g., matter-server hadn't populated diagnostics yet).
        unmatched_thread.extend(
            d for d in thread_matter if not d.get("ext_address")
        )

        # Log a summary so users can debug matching from HA logs.
        _LOGGER.debug(
            "Thread topology match summary: %d mesh nodes, %d Thread Matter devices, "
            "%d claimed by ext_address, %d unmatched",
            len(nodes), len(thread_matter), len(claimed_ext_addresses),
            len(unmatched_thread),
        )

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
                "unmatched_thread": unmatched_thread,
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
        for node in nodes.values():
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
  <text class="subtitle" x="30" y="68">{_svg_text(network_name)} • Real-time network visualization</text>

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
  <text class="node-label" x="{leader_x}" y="{leader_y + 60}" text-anchor="middle">{_svg_text(leader["name"])}</text>
  <text class="node-sublabel" x="{leader_x}" y="{leader_y + 74}" text-anchor="middle">{_svg_text(leader["manufacturer"])} • Leader • LQ: {lq_text}</text>
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
  <text class="device-label" x="{cx}" y="{cy + 30}" text-anchor="middle">{_svg_text(child_name[:20])}</text>
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
  <text class="node-label" x="{rx}" y="{ry + 42}" text-anchor="middle">{_svg_text(router["name"])}</text>
  <text class="node-sublabel" x="{rx}" y="{ry + 55}" text-anchor="middle">{_svg_text(router["manufacturer"])} • Router • LQ: {lq_text}</text>
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
  <text class="device-label" x="{cx}" y="{cy + 30}" text-anchor="middle">{_svg_text(child_name[:18])}</text>
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
    <text class="device-label" x="25" y="-2">{_svg_text(device["name"][:16])}</text>
    <text class="node-sublabel" x="25" y="12">{_svg_text(device.get("manufacturer", "")[:16])}</text>
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

    def _write_svg(self, svg_content: str) -> str:
        """Write the SVG to the www folder. Runs in an executor thread."""
        www_path = self.hass.config.path("www")
        os.makedirs(www_path, exist_ok=True)

        svg_path = os.path.join(www_path, "thread_topology.svg")
        with open(svg_path, "w", encoding="utf-8") as f:
            f.write(svg_content)

        return svg_path

    async def save_svg_to_www(self, topology: dict[str, Any]) -> str | None:
        """Generate SVG and save to www folder."""
        try:
            svg_content = self.generate_svg(topology)

            # Creating directories and writing the file blocks; doing it inline
            # stalls the event loop on every update and Home Assistant logs a
            # warning asking for a bug report.
            svg_path = await self.hass.async_add_executor_job(
                self._write_svg, svg_content
            )

            _LOGGER.debug("SVG saved to %s", svg_path)
            return "/local/thread_topology.svg"
        except Exception as err:  # noqa: BLE001 - the map is optional; never fail the update over it
            _LOGGER.error("Failed to save SVG: %s", err)
            return None

    async def async_shutdown(self) -> None:
        """Shutdown the coordinator."""
        if self._session:
            await self._session.close()
            self._session = None
