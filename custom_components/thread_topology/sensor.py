"""Sensor platform for Thread Topology."""
from __future__ import annotations

import logging
from typing import Any

from homeassistant.components.sensor import SensorEntity, SensorStateClass
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .coordinator import ThreadTopologyCoordinator

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Thread Topology sensors."""
    coordinator: ThreadTopologyCoordinator = hass.data[DOMAIN][entry.entry_id]

    entities: list[SensorEntity] = [
        ThreadNetworkSensor(coordinator, entry),
        ThreadTopologyMapSensor(coordinator, entry),
    ]

    # Add sensor for each router node
    if coordinator.data:
        for ext_address, node_data in coordinator.data.get("nodes", {}).items():
            entities.append(ThreadNodeSensor(coordinator, entry, ext_address, node_data))

    async_add_entities(entities)


class ThreadNetworkSensor(CoordinatorEntity[ThreadTopologyCoordinator], SensorEntity):
    """Sensor showing Thread network overview."""

    _attr_has_entity_name = True
    _attr_name = "Thread Network"
    _attr_icon = "mdi:lan"

    def __init__(
        self,
        coordinator: ThreadTopologyCoordinator,
        entry: ConfigEntry,
    ) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator)
        self._attr_unique_id = f"{entry.entry_id}_network"
        self._entry = entry

    @property
    def native_value(self) -> str | None:
        """Return the network name."""
        if self.coordinator.data:
            return self.coordinator.data.get("network_name", "Unknown")
        return None

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return additional attributes."""
        if not self.coordinator.data:
            return {}

        data = self.coordinator.data
        matter = data.get("matter_devices", {})

        return {
            "state": data.get("state", "unknown"),
            "router_count": data.get("router_count", 0),
            "total_thread_devices": data.get("total_devices", 0),
            "matter_thread_devices": len(matter.get("thread", [])),
            "matter_wifi_devices": len(matter.get("wifi", [])),
            "leader_address": data.get("leader_address", ""),
        }


class ThreadTopologyMapSensor(CoordinatorEntity[ThreadTopologyCoordinator], SensorEntity):
    """Sensor showing Thread topology as formatted text."""

    _attr_has_entity_name = True
    _attr_name = "Thread Topology Map"
    _attr_icon = "mdi:family-tree"

    def __init__(
        self,
        coordinator: ThreadTopologyCoordinator,
        entry: ConfigEntry,
    ) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator)
        self._attr_unique_id = f"{entry.entry_id}_topology_map"
        self._entry = entry

    @property
    def native_value(self) -> str | None:
        """Return device count as state."""
        if self.coordinator.data:
            return str(self.coordinator.data.get("total_devices", 0))
        return None

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return topology as markdown."""
        if not self.coordinator.data:
            return {}

        data = self.coordinator.data
        nodes = data.get("nodes", {})
        leader = data.get("leader_address", "")
        matter = data.get("matter_devices", {})

        # Build topology text with device names
        lines = []
        lines.append(f"## 🧵 Thread Network: {data.get('network_name', 'Unknown')}")
        lines.append("")
        lines.append(f"**Routers:** {data.get('router_count', 0)} | **Thread Devices:** {data.get('total_devices', 0)}")

        # Add Matter summary
        thread_count = len(matter.get("thread", []))
        wifi_count = len(matter.get("wifi", []))
        if thread_count or wifi_count:
            lines.append(f"**Matter:** {thread_count} Thread + {wifi_count} WiFi")
        lines.append("")
        lines.append("---")
        lines.append("")

        # Sort nodes: leader first, then routers
        sorted_nodes = sorted(
            nodes.items(),
            key=lambda x: (0 if x[0] == leader else 1, x[1].get("rloc16", 0))
        )

        for ext_address, node in sorted_nodes:
            role = node.get("role", "unknown")
            name = node.get("name", f"Unknown ({ext_address[-4:].upper()})")
            manufacturer = node.get("manufacturer", "")

            # Role icon and styling
            if role == "leader":
                role_icon = "👑"
                role_label = "Leader"
            elif role == "router":
                role_icon = "📡"
                role_label = "Router"
            else:
                role_icon = "📱"
                role_label = "End Device"

            # Link quality indicator
            lq = node.get("link_quality", 0)
            lq_bar = "█" * lq + "░" * (3 - lq)
            lq_text = ["Poor", "Fair", "Good", "Excellent"][min(lq, 3)]

            lines.append(f"### {role_icon} {name}")
            if manufacturer:
                lines.append(f"*{manufacturer}* • {role_label} • LQ: [{lq_bar}] {lq_text}")
            else:
                lines.append(f"{role_label} • LQ: [{lq_bar}] {lq_text}")
            lines.append("")

            # Add children with device names
            for child in node.get("children", []):
                child_type = child.get("type", "unknown")
                child_name = child.get("name")
                child_manufacturer = child.get("manufacturer", "")
                child_model = child.get("model", "")

                # Child icon based on type
                if child_type == "sleepy":
                    child_icon = "💤"
                    type_label = "Sleepy End Device"
                else:
                    child_icon = "📱"
                    type_label = "End Device"

                if child_name:
                    # We have a name from Matter
                    lines.append(f"   └─ {child_icon} **{child_name}**")
                    if child_manufacturer or child_model:
                        lines.append(f"       *{child_manufacturer}* {child_model}")
                else:
                    # Fallback to RLOC
                    child_rloc = hex(child.get("rloc16", 0))
                    lines.append(f"   └─ {child_icon} {type_label} ({child_rloc})")
                lines.append("")

        # Add Matter WiFi devices section
        wifi_devices = matter.get("wifi", [])
        if wifi_devices:
            lines.append("---")
            lines.append("")
            lines.append("### 📶 Matter over WiFi")
            for device in wifi_devices:
                lines.append(f"- **{device['name']}** ({device.get('manufacturer', '')})")
            lines.append("")

        return {
            "topology_text": "\n".join(lines),
            "nodes": nodes,
            "matter_devices": matter,
            "raw_data": data,
        }


class ThreadNodeSensor(CoordinatorEntity[ThreadTopologyCoordinator], SensorEntity):
    """Sensor for individual Thread node."""

    _attr_has_entity_name = True
    _attr_state_class = SensorStateClass.MEASUREMENT

    def __init__(
        self,
        coordinator: ThreadTopologyCoordinator,
        entry: ConfigEntry,
        ext_address: str,
        node_data: dict,
    ) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator)
        self._ext_address = ext_address
        self._attr_unique_id = f"{entry.entry_id}_node_{ext_address}"

        # Use node name if available
        name = node_data.get("name", f"Node {ext_address[-4:].upper()}")
        self._attr_name = f"Thread {name}"

        role = node_data.get("role", "unknown")
        if role == "leader":
            self._attr_icon = "mdi:crown"
        elif role == "router":
            self._attr_icon = "mdi:router-wireless"
        else:
            self._attr_icon = "mdi:cellphone-wireless"

    @property
    def native_value(self) -> int | None:
        """Return link quality as state."""
        if self.coordinator.data:
            nodes = self.coordinator.data.get("nodes", {})
            node = nodes.get(self._ext_address, {})
            return node.get("link_quality", 0)
        return None

    @property
    def native_unit_of_measurement(self) -> str:
        """Return unit."""
        return "LQI"

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return node attributes."""
        if not self.coordinator.data:
            return {}

        nodes = self.coordinator.data.get("nodes", {})
        node = nodes.get(self._ext_address, {})

        # Build child info with names
        children_info = []
        for child in node.get("children", []):
            child_entry = {
                "rloc16": hex(child.get("rloc16", 0)),
                "type": child.get("type", "unknown"),
            }
            if "name" in child:
                child_entry["name"] = child["name"]
                child_entry["manufacturer"] = child.get("manufacturer", "")
            children_info.append(child_entry)

        return {
            "ext_address": self._ext_address,
            "rloc16": hex(node.get("rloc16", 0)),
            "role": node.get("role", "unknown"),
            "name": node.get("name", "Unknown"),
            "manufacturer": node.get("manufacturer", ""),
            "child_count": node.get("child_count", 0),
            "leader_cost": node.get("leader_cost", 0),
            "children": children_info,
            "connections": node.get("connections", []),
        }
