"""Constants for Thread Topology integration."""

DOMAIN = "thread_topology"

# Default OTBR URL (inside HA container network).
# This is the Home Assistant *add-on* hostname. It is only a pre-filled default
# in the config flow; deployments that run OTBR elsewhere (a separate host, a
# reverse proxy) simply type their own URL.
DEFAULT_OTBR_URL = "http://core-openthread-border-router:8081"

# --- API endpoints ---------------------------------------------------------
# ot-br-posix has two REST generations. The legacy one serves flat PascalCase
# documents from /node and /diagnostics. The current one keeps /node (but with
# camelCase keys) and replaces /diagnostics with a JSON:API task workflow.
ENDPOINT_NODE = "/node"
ENDPOINT_DIAGNOSTICS = "/diagnostics"

ENDPOINT_ACTIONS = "/api/actions"
ENDPOINT_DEVICES = "/api/devices"
ENDPOINT_API_DIAGNOSTICS = "/api/diagnostics"

# JSON:API endpoints require this media type on both Accept and Content-Type,
# and respond with it - aiohttp will not decode it as JSON unless we tell it to.
CONTENT_TYPE_JSONAPI = "application/vnd.api+json"

# Which REST generation the configured OTBR speaks. Probed once, then reused.
API_MODE_UNKNOWN = "unknown"
API_MODE_LEGACY = "legacy"
API_MODE_JSONAPI = "jsonapi"

# --- Update intervals ------------------------------------------------------
# Update interval in seconds (legacy API: a single cheap GET).
DEFAULT_SCAN_INTERVAL = 30

# The JSON:API flow asks OTBR to crawl the entire mesh before diagnostics can
# be read. Measured at 60s+ on a 3-device network, and it grows with mesh size,
# so polling it every 30s would queue updates back-to-back forever.
JSONAPI_SCAN_INTERVAL = 180

# --- JSON:API task flow tuning ---------------------------------------------
TASK_POLL_INTERVAL = 0.75
TASK_TIMEOUT = 120
REQUEST_TIMEOUT = 15

# Per-node budget for matter-server diagnostics. That call reaches out over the
# network, so an unreachable node must not be able to stall the whole update.
MATTER_NODE_TIMEOUT = 10

# Attributes for the mesh crawl that populates /api/devices.
DEVICE_COLLECTION_ATTRS = {
    "maxAge": 30,
    "maxRetries": 5,
    "deviceCount": 50,
    "timeout": 60,
}

# Network diagnostic TLVs to request per router.
#
# `mode` and `connectivity` are what make the link-quality sensors work:
# link_quality is derived from Connectivity.LinkQuality1/2/3 and the router
# role from Mode.DeviceType. Omitting them yields nodes that all report LQI 0
# and classify as end devices.
DIAGNOSTIC_TYPES = [
    "extAddress",
    "rloc16",
    "mode",
    "connectivity",
    "route",
    "leaderData",
    "ipv6Addresses",
    "childTable",
    "children",
    "routerNeighbors",
]

DIAGNOSTIC_TASK_TIMEOUT = 25

# Roles in /api/devices worth asking for diagnostics. Some builds leave role
# empty until the mesh crawl finishes, hence the fall back to all devices.
ROUTING_ROLES = frozenset({"router", "leader", "borderrouter"})

# Device types
DEVICE_TYPE_ROUTER = "router"
DEVICE_TYPE_END_DEVICE = "end_device"
DEVICE_TYPE_SLEEPY_END_DEVICE = "sleepy_end_device"
DEVICE_TYPE_LEADER = "leader"

# Attributes
ATTR_EXT_ADDRESS = "ext_address"
ATTR_RLOC16 = "rloc16"
ATTR_ROLE = "role"
ATTR_LINK_QUALITY = "link_quality"
ATTR_CHILD_COUNT = "child_count"
ATTR_ROUTER_COUNT = "router_count"
ATTR_NETWORK_NAME = "network_name"
ATTR_LEADER_COST = "leader_cost"
