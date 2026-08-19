"""Verify untrusted device names are escaped in SVG and markdown output."""
from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import MagicMock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

# sensor.py subclasses HA base classes at import time, so they must be real
# classes (a MagicMock base triggers a metaclass conflict). conftest only
# stubs what the coordinator needs; provide the rest here.
class _SensorBase:
    pass


class _CoordinatorBase:
    def __class_getitem__(cls, item):
        return cls


_sensor_mod = MagicMock()
_sensor_mod.SensorEntity = _SensorBase
_sensor_mod.SensorStateClass = type("SensorStateClass", (), {"MEASUREMENT": "measurement"})
sys.modules.setdefault("homeassistant.components", MagicMock())
sys.modules["homeassistant.components.sensor"] = _sensor_mod
sys.modules.setdefault("homeassistant.helpers.entity_platform", MagicMock())
sys.modules["homeassistant.helpers.update_coordinator"].CoordinatorEntity = _CoordinatorBase

from custom_components.thread_topology import coordinator as coord  # noqa: E402
from custom_components.thread_topology import sensor as snsr  # noqa: E402


EVIL = '</text><script>alert(1)</script> & <Bath> **b** [x](javascript:void)'


def test_svg_text_escapes_xml():
    out = coord._svg_text(EVIL)
    assert "<script>" not in out
    assert "</text>" not in out
    assert "&lt;" in out and "&amp;" in out
    # Ampersand in an ordinary name must become a valid entity, not raw '&'.
    assert coord._svg_text("Bed & Bath") == "Bed &amp; Bath"


def test_md_escape_neutralizes_inline_markup():
    out = snsr._md_escape(EVIL)
    assert "**b**" not in out          # bold injection defused
    assert "](" not in out             # link injection defused
    assert "<script>" not in out       # angle brackets escaped
    assert snsr._md_escape("**pwn**") == r"\*\*pwn\*\*"
    # A benign name is left readable (no stray backslashes).
    assert snsr._md_escape("Living Room") == "Living Room"


def test_generated_svg_contains_no_raw_injection():
    topology = {
        "network_name": EVIL,
        "router_count": 0,
        "total_devices": 1,
        "matter_devices": {"thread": [], "wifi": [{"name": EVIL, "manufacturer": EVIL}]},
        "nodes": {
            "AA": {
                "role": "leader",
                "name": EVIL,
                "manufacturer": EVIL,
                "link_quality": 3,
                "children": [{"id": 1, "type": "active", "name": EVIL}],
            }
        },
    }
    svg = coord.ThreadTopologyCoordinator.generate_svg.__get__(
        object.__new__(coord.ThreadTopologyCoordinator)
    )(topology)
    assert "<script>" not in svg
    assert "</text><script>" not in svg
