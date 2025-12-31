"""Constants for Thread Topology integration."""

DOMAIN = "thread_topology"

# Default OTBR URL (inside HA container network)
DEFAULT_OTBR_URL = "http://core-openthread-border-router:8081"

# API endpoints
ENDPOINT_NODE = "/node"
ENDPOINT_DIAGNOSTICS = "/diagnostics"

# Update interval in seconds
DEFAULT_SCAN_INTERVAL = 30

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
