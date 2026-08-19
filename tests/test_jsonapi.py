"""Tests for the current ot-br-posix JSON:API REST support.

These run against a real captured OTBR response (tests/fixtures), because the
differences that broke this integration - renamed fields, hex-string RLOC16s,
booleans where ints were - are exactly the ones a hand-written mock would get
wrong in the same way the code did.
"""
from __future__ import annotations

import asyncio
import json
import sys
import time
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

# Mock homeassistant modules so coordinator can be imported without HA installed
sys.modules.setdefault("homeassistant", MagicMock())
sys.modules.setdefault("homeassistant.core", MagicMock())
sys.modules.setdefault("homeassistant.config_entries", MagicMock())
sys.modules.setdefault("homeassistant.const", MagicMock())
sys.modules.setdefault("homeassistant.helpers", MagicMock())
sys.modules.setdefault("homeassistant.helpers.device_registry", MagicMock())
sys.modules.setdefault("homeassistant.helpers.update_coordinator", MagicMock())

from custom_components.thread_topology import coordinator as coordinator_module  # noqa: E402
from custom_components.thread_topology.coordinator import (  # noqa: E402
    ThreadTopologyCoordinator,
    _guess_transport,
    _link_margin_to_lqi,
    _matter_node_id,
    _parse_node_diagnostics,
    _parse_rloc,
    _translate_child_table,
    _translate_diagnostic,
    _translate_node,
    _translate_route_data,
)


@pytest.fixture
def coordinator() -> ThreadTopologyCoordinator:
    """Return a coordinator with Home Assistant stubbed out."""
    return ThreadTopologyCoordinator(MagicMock(), "http://otbr.invalid:8081")


class TestParseRloc:
    """RLOC16 arrives as a hex string now, but is used in arithmetic."""

    @pytest.mark.parametrize(
        ("value", "expected"),
        [
            ("0xf800", 0xF800),
            ("0xF800", 0xF800),
            ("f800", 0xF800),
            (0xF800, 0xF800),
            (0, 0),
        ],
    )
    def test_parses(self, value, expected):
        assert _parse_rloc(value) == expected

    @pytest.mark.parametrize("value", [None, "", "   ", "not-hex", True, False])
    def test_rejects(self, value):
        assert _parse_rloc(value) is None


class TestLinkMarginToLqi:
    """Link margin to the 0-3 scale, for builds that only send neighbours."""

    @pytest.mark.parametrize(
        ("margin", "expected"),
        [(49, 3), (20, 3), (19, 2), (10, 2), (9, 1), (2, 1), (1, 0), (0, 0)],
    )
    def test_thresholds(self, margin, expected):
        assert _link_margin_to_lqi(margin) == expected

    def test_missing_margin_is_zero(self):
        assert _link_margin_to_lqi(None) == 0


class TestTranslateNode:
    """The /node route survived, but its field names did not."""

    def test_camel_case_fields_are_mapped(self, jsonapi_node_response):
        node = _translate_node(jsonapi_node_response)

        assert node["NetworkName"] == "ot-test-net"
        assert node["ExtAddress"] == "0123456789abcdef"
        assert node["State"] == "router"

    def test_num_of_router_was_renamed_to_router_count(self, jsonapi_node_response):
        """NumOfRouter -> routerCount is a rename, not a case change."""
        assert "NumOfRouter" not in jsonapi_node_response
        assert _translate_node(jsonapi_node_response)["NumOfRouter"] == 2

    def test_rloc16_becomes_an_int(self, jsonapi_node_response):
        assert jsonapi_node_response["rloc16"] == "0xf800"
        assert _translate_node(jsonapi_node_response)["Rloc16"] == 0xF800

    def test_legacy_response_passes_through(self, mock_otbr_node_response):
        """Old OTBR builds already speak PascalCase; do not disturb them."""
        node = _translate_node(mock_otbr_node_response)

        assert node["NetworkName"] == "MyHome1038137341"
        assert node["NumOfRouter"] == 3
        assert node["ExtAddress"] == "1EA5312CFB153F0B"
        assert node["State"] == "leader"

    def test_non_dict_is_safe(self):
        assert _translate_node(None) == {}


class TestTranslateDiagnostic:
    """JSON:API diagnostic -> the legacy flat shape _process_topology reads."""

    @pytest.fixture
    def leader(self, jsonapi_diagnostics_response) -> dict:
        return _translate_diagnostic(jsonapi_diagnostics_response[0])

    @pytest.fixture
    def border_router(self, jsonapi_diagnostics_response) -> dict:
        return _translate_diagnostic(jsonapi_diagnostics_response[1])

    def test_connectivity_is_translated(self, leader):
        """Without this the link quality sensors all read zero."""
        assert leader["Connectivity"]["LinkQuality3"] == 1
        assert leader["Connectivity"]["LinkQuality2"] == 0
        assert leader["Connectivity"]["LinkQuality1"] == 0

    def test_leader_cost_is_translated(self, leader, border_router):
        assert leader["Connectivity"]["LeaderCost"] == 0
        assert border_router["Connectivity"]["LeaderCost"] == 1

    def test_device_type_comes_from_device_type_ftd(self, leader):
        """fullThreadDevice was renamed deviceTypeFTD; routers depend on it."""
        assert leader["Mode"]["DeviceType"] == 1
        assert leader["Mode"]["RxOnWhenIdle"] == 1

    def test_mode_flags_are_ints_not_bools(self, leader):
        """Legacy OTBR sent 0/1 and the downstream code compares against ints."""
        for value in leader["Mode"].values():
            assert isinstance(value, int)
            assert not isinstance(value, bool)

    def test_rloc16_is_an_int(self, leader, border_router):
        assert leader["Rloc16"] == 0xE400
        assert border_router["Rloc16"] == 0xF800

    def test_route_data_is_pascal_case(self, border_router):
        route_data = border_router["Route"]["RouteData"]

        assert {"RouteId", "LinkQualityIn", "LinkQualityOut", "RouteCost"} <= set(
            route_data[0]
        )
        assert any(entry["LinkQualityIn"] == 3 for entry in route_data)

    def test_ipv6_addresses_are_mapped(self, leader):
        assert leader["IP6AddressList"]
        assert all(":" in address for address in leader["IP6AddressList"])

    def test_leader_flag_is_captured(self, leader, border_router):
        """OTBR states leadership outright rather than making us guess."""
        assert leader["IsLeader"] is True
        assert border_router["IsLeader"] is False

    def test_border_router_flag_is_captured(self, leader, border_router):
        assert border_router["IsBorderRouter"] is True
        assert leader["IsBorderRouter"] is False

    def test_child_table_is_translated(self, border_router):
        children = border_router["ChildTable"]

        assert len(children) == 1
        assert children[0]["ChildId"] == 2
        assert children[0]["Mode"]["RxOnWhenIdle"] == 0

    def test_child_ext_address_is_preserved(self, border_router):
        """children[] carries the ext address that childTable[] omits."""
        assert border_router["ChildTable"][0]["ExtAddress"] == "aabbccddeeff0011"

    def test_empty_child_table_is_omitted(self, leader):
        assert "ChildTable" not in leader

    def test_non_dict_is_safe(self):
        assert _translate_diagnostic(None) == {}
        assert _translate_diagnostic({"attributes": "nope"}) == {}


class TestChildTableMerging:
    """childTable[] and children[] overlap; both carry useful fields."""

    def test_merges_by_child_id(self):
        result = _translate_child_table({
            "childTable": [{"childId": 2, "timeout": 12, "mode": {"rxOnWhenIdle": False}}],
            "children": [{"childId": 2, "extAddress": "aabb", "rloc16": "0xf802"}],
        })

        assert len(result) == 1
        assert result[0]["ExtAddress"] == "aabb"
        assert result[0]["Timeout"] == 12
        assert result[0]["Rloc16"] == 0xF802

    def test_child_id_derived_from_rloc(self):
        result = _translate_child_table({"children": [{"rloc16": "0xf802"}]})

        assert result[0]["ChildId"] == 2

    def test_children_only(self):
        """children[] keeps its mode flags at the top level, not nested."""
        result = _translate_child_table({
            "children": [{"childId": 5, "rxOnWhenIdle": True, "deviceTypeFTD": False}],
        })

        assert result[0]["Mode"]["RxOnWhenIdle"] == 1
        assert result[0]["Mode"]["DeviceType"] == 0

    def test_missing_sources(self):
        assert _translate_child_table({}) == []


class TestRouteDataFallback:
    """Some builds return routerNeighbors instead of a route table."""

    def test_prefers_real_route_data(self):
        result = _translate_route_data({
            "route": {"routeData": [{"routeId": 7, "linkQualityIn": 2,
                                     "linkQualityOut": 3, "routeCost": 1}]},
            "routerNeighbors": [{"rloc16": "0xe400", "linkMargin": 49}],
        })

        assert result == [{"RouteId": 7, "LinkQualityIn": 2,
                           "LinkQualityOut": 3, "RouteCost": 1}]

    def test_synthesizes_from_router_neighbors(self):
        result = _translate_route_data({
            "routerNeighbors": [{"rloc16": "0xe400", "linkMargin": 49}],
        })

        assert result == [{"RouteId": 0xE400 >> 10, "LinkQualityIn": 3,
                           "LinkQualityOut": 3, "RouteCost": 0}]

    def test_no_route_information(self):
        assert _translate_route_data({}) == []


class TestProcessTopologyOnJsonApi:
    """End to end: a live JSON:API capture must produce usable sensor data."""

    @pytest.fixture
    def topology(self, coordinator, jsonapi_node_response,
                 jsonapi_diagnostics_response) -> dict:
        return coordinator._process_topology(
            _translate_node(jsonapi_node_response),
            [_translate_diagnostic(item) for item in jsonapi_diagnostics_response],
            [],
            [],
        )

    def test_network_name(self, topology):
        assert topology["network_name"] == "ot-test-net"

    def test_router_count(self, topology):
        assert topology["router_count"] == 2

    def test_all_nodes_present(self, topology):
        assert len(topology["nodes"]) == 2

    def test_link_quality_is_not_zero(self, topology):
        """The whole point: node sensors report a real LQI."""
        qualities = [node["link_quality"] for node in topology["nodes"].values()]

        assert qualities
        assert all(quality == 3 for quality in qualities)

    def test_exactly_one_leader(self, topology):
        roles = [node["role"] for node in topology["nodes"].values()]

        assert roles.count("leader") == 1

    def test_leader_is_the_node_otbr_named(self, topology):
        """The polled border router is a plain router here, not the leader."""
        leader = next(
            node for node in topology["nodes"].values() if node["role"] == "leader"
        )

        assert leader["ext_address"] == "fedcba9876543210"
        assert topology["leader_address"] == "fedcba9876543210"

    def test_no_node_is_an_end_device(self, topology):
        """Both captured nodes are FTDs; Mode.DeviceType must survive."""
        roles = {node["role"] for node in topology["nodes"].values()}

        assert roles == {"leader", "router"}

    def test_polled_otbr_keeps_its_border_router_name(self, topology):
        local = topology["nodes"]["0123456789abcdef"]

        assert local["role"] == "router"
        assert local["manufacturer"] == "Nabu Casa"

    def test_children_are_counted(self, topology):
        assert sum(node["child_count"] for node in topology["nodes"].values()) == 1

    def test_connections_are_built(self, topology):
        assert any(node["connections"] for node in topology["nodes"].values())

    def test_leader_cost_reaches_the_node(self, topology):
        local = topology["nodes"]["0123456789abcdef"]

        assert local["leader_cost"] == 1


class TestLocalOtbrNaming:
    """custom_routers.yaml must be able to name the polled border router."""

    def test_defaults_to_skyconnect(self, coordinator):
        result = coordinator._identify_router("0123456789abcdef", True)

        assert result["name"] == "SkyConnect (OTBR)"

    def test_custom_router_overrides_the_default(self, coordinator):
        coordinator._custom_routers = [{
            "address": "0123456789ABCDEF",
            "name": "Pi 3B+ Border Router",
            "manufacturer": "Raspberry Pi",
            "icon": "chip",
        }]

        result = coordinator._identify_router("0123456789abcdef", True)

        assert result["name"] == "Pi 3B+ Border Router"
        assert result["manufacturer"] == "Raspberry Pi"

    def test_custom_router_by_oui_prefix(self, coordinator):
        coordinator._custom_routers = [{
            "address": "012345",
            "name": "My OTBR",
            "manufacturer": "DIY",
            "icon": "chip",
        }]

        assert coordinator._identify_router(
            "0123456789abcdef", True
        )["name"] == "My OTBR"

    def test_other_routers_are_unaffected(self, coordinator):
        coordinator._custom_routers = [{
            "address": "0123456789ABCDEF",
            "name": "Pi 3B+ Border Router",
            "manufacturer": "Raspberry Pi",
            "icon": "chip",
        }]

        result = coordinator._identify_router("fedcba9876543210", False)

        assert result["name"] != "Pi 3B+ Border Router"


class TestUnidentifiedRouterNaming:
    """An unrecognised router must not be given a made-up vendor.

    The old fallback picked a name from a rotating list by iteration order, so
    the first unidentified router became "Eero / Amazon-Eero" no matter what it
    actually was - which is how an IKEA air quality monitor ended up presented
    as an Eero on the topology map.
    """

    INVENTED = {"Eero", "Google Nest", "Apple HomePod", "SmartThings"}

    def test_named_after_its_address(self, coordinator):
        result = coordinator._identify_router("6a57f823187e197b", False)

        assert result["name"] == "Thread Router 197B"

    def test_manufacturer_is_not_invented(self, coordinator):
        result = coordinator._identify_router("6a57f823187e197b", False)

        assert result["manufacturer"] == "Unknown"

    @pytest.mark.parametrize(
        "ext_address",
        [
            "6a57f823187e197b",
            "0011223344556677",
            "ffffffffffffffff",
            "1234567890abcdef",
        ],
    )
    def test_no_address_yields_a_vendor_name(self, coordinator, ext_address):
        result = coordinator._identify_router(ext_address, False)

        assert result["name"] not in self.INVENTED
        assert result["manufacturer"] not in {"Amazon/Eero", "Google", "Apple", "Samsung"}

    def test_distinct_addresses_get_distinct_names(self, coordinator):
        """Names come from the address, so they no longer depend on ordering."""
        first = coordinator._identify_router("aaaaaaaaaaaa1111", False)["name"]
        second = coordinator._identify_router("bbbbbbbbbbbb2222", False)["name"]

        assert first != second

    def test_same_address_is_stable_regardless_of_call_order(self, coordinator):
        """The old rotation gave the same node different names run to run."""
        coordinator._identify_router("cccccccccccc3333", False)
        repeated = coordinator._identify_router("aaaaaaaaaaaa1111", False)["name"]
        first = coordinator._identify_router("aaaaaaaaaaaa1111", False)["name"]

        assert repeated == first

    def test_empty_address_does_not_crash(self, coordinator):
        assert coordinator._identify_router("", False)["name"]

    def test_known_oui_still_wins(self, coordinator):
        """Real identification must survive; only the invented fallback goes."""
        result = coordinator._identify_router("286D970123456789", False)

        assert result["manufacturer"] == "Apple"


class TestAddressSuffixIdentification:
    """Suffix matching must be anchored, not a substring search.

    The rule was previously `"EA" in ext_address`, which labels roughly one
    address in eighteen as an Eero.
    """

    def test_eero_suffix_is_identified(self, coordinator):
        result = coordinator._identify_router("96308C2577D6EA17", False)

        assert result["name"] == "Eero"
        assert result["manufacturer"] == "Amazon/Eero"

    def test_suffix_match_is_case_insensitive(self, coordinator):
        assert coordinator._identify_router(
            "96308c2577d6ea17", False
        )["name"] == "Eero"

    @pytest.mark.parametrize(
        "ext_address",
        [
            "EA17000000000000",  # at the start
            "0000EA1700000000",  # in the middle
            "00000000000000EA",  # bare "EA" at the end
            "12EA345678901234",  # bare "EA" in the middle
            "6A57F823187E197B",  # the real leader on the dev network
        ],
    )
    def test_unanchored_matches_are_rejected(self, coordinator, ext_address):
        result = coordinator._identify_router(ext_address, False)

        assert result["name"] != "Eero"
        assert result["manufacturer"] != "Amazon/Eero"
        assert result["name"].startswith("Thread Router ")


class TestTransportGuess:
    """Fallback used only when a Matter node reports no interfaces."""

    @pytest.mark.parametrize(
        "model",
        [
            "Smart Wi-Fi Dimmer Switch",   # TP-Link: the hyphen defeated "wifi"
            "Smart WiFi Plug",
            "Smart Wi Fi Bulb",
        ],
    )
    def test_recognises_wifi_spellings(self, model):
        assert _guess_transport(model, "Kitchen light", "TP-Link") == "wifi"

    def test_recognises_wifi_only_manufacturers(self):
        assert _guess_transport("Smart Lock", "Front door", "Nuki") == "wifi"

    @pytest.mark.parametrize(
        ("model", "manufacturer"),
        [
            ("Smart RGBTW Bulb", "Leedarson"),
            ("ALPSTUGA air quality monitor", "IKEA of Sweden"),
            ("Shelly 1 Mini Gen3", "Shelly"),
            (None, None),
        ],
    )
    def test_never_claims_thread_without_evidence(self, model, manufacturer):
        """Defaulting to Thread is what put Wi-Fi bulbs in the mesh."""
        assert _guess_transport(model, "Some device", manufacturer) != "thread"

    def test_unrecognised_is_unknown(self):
        assert _guess_transport("Smart RGBTW Bulb", "Light", "Leedarson") == "unknown"


class TestEndDeviceMatching:
    """Children are matched on identity, never by position."""

    THREAD_BUTTON = {
        "name": "Bedroom BILRESA button",
        "model": "BILRESA dual button",
        "manufacturer": "IKEA of Sweden",
        "transport": "thread",
        "ext_address": "AABBCCDDEEFF0011",
        "ip_addresses": ["fd00:1234:5678:9abc::5"],
    }
    WIFI_BULB = {
        "name": "Print Farm Light 1",
        "model": "Smart RGBTW Bulb",
        "manufacturer": "Leedarson",
        "transport": "wifi",
        "ext_address": None,
        "ip_addresses": [],
    }
    UNKNOWN_DEVICE = {
        "name": "Mystery device",
        "model": None,
        "manufacturer": None,
        "transport": "unknown",
        "ext_address": None,
        "ip_addresses": [],
    }

    @pytest.fixture
    def devices(self) -> list[dict]:
        # Wi-Fi bulb first: it is what positional matching used to pick.
        return [self.WIFI_BULB, self.UNKNOWN_DEVICE, self.THREAD_BUTTON]

    def test_matches_on_child_ext_address(self, coordinator, devices):
        match = coordinator._match_end_device(devices, set(), "0a799b2bd2123f8f")

        assert match is None  # not this address

        match = coordinator._match_end_device(devices, set(), "aabbccddeeff0011")

        assert match["name"] == "Bedroom BILRESA button"

    def test_ext_address_match_is_case_insensitive(self, coordinator, devices):
        match = coordinator._match_end_device(devices, set(), "AA:BB:CC:DD:EE:FF:00:11")

        assert match["name"] == "Bedroom BILRESA button"

    def test_matches_on_shared_ipv6(self, coordinator, devices):
        match = coordinator._match_end_device(
            devices, set(), None, ["fd00:1234:5678:9abc::5"]
        )

        assert match["name"] == "Bedroom BILRESA button"

    def test_unidentifiable_child_is_left_unnamed(self, coordinator, devices):
        """Previously returned the first unclaimed device - a Wi-Fi bulb."""
        assert coordinator._match_end_device(devices, set()) is None

    def test_never_returns_a_non_thread_device(self, coordinator, devices):
        for ext in (None, "ffffffffffffffff"):
            match = coordinator._match_end_device(devices, set(), ext)
            assert match is None or match["transport"] == "thread"

    def test_claimed_devices_are_skipped(self, coordinator, devices):
        claimed = {"AABBCCDDEEFF0011"}

        assert coordinator._match_end_device(
            devices, claimed, "aabbccddeeff0011"
        ) is None


class TestManifest:
    """Startup ordering is declared in the manifest, not in code."""

    @pytest.fixture
    def manifest(self) -> dict:
        path = (
            Path(__file__).parent.parent
            / "custom_components" / "thread_topology" / "manifest.json"
        )
        return json.loads(path.read_text(encoding="utf-8"))

    def test_matter_is_set_up_first(self, manifest):
        """Our first poll otherwise runs before Matter has any devices.

        after_dependencies, not dependencies: Matter is optional enrichment and
        the integration must still load without it.
        """
        assert "matter" in manifest["after_dependencies"]
        assert "matter" not in manifest["dependencies"]


class TestMatterNodeId:
    """A Matter device carries several identifiers, in a set.

    Reading "the first" one picked a different identifier between processes.
    Whenever it landed on the serial, the device lost its diagnostics entirely -
    which is what made names and Thread counts flicker across restarts.
    """

    DEVICE_ID = "deviceid_9DEA92C0F9B67B5E-0000000000000057-MatterNodeDevice"
    SERIAL_ID = "serial_1035970000189A08"

    def test_finds_the_node_id(self):
        assert _matter_node_id([self.DEVICE_ID]) == 0x57

    @pytest.mark.parametrize(
        "identifiers",
        [
            (DEVICE_ID, SERIAL_ID),
            (SERIAL_ID, DEVICE_ID),
        ],
    )
    def test_order_does_not_matter(self, identifiers):
        assert _matter_node_id(identifiers) == 0x57

    def test_real_identifier_set(self):
        """The set ordering is exactly what used to decide this."""
        assert _matter_node_id({self.DEVICE_ID, self.SERIAL_ID}) == 0x57

    def test_serial_alone_yields_nothing(self):
        assert _matter_node_id([self.SERIAL_ID]) is None

    def test_a_serial_containing_a_dash_is_not_parsed_as_a_node_id(self):
        """Only the deviceid form is parsed, so this cannot be misread."""
        assert _matter_node_id(["serial_ABC-DEF"]) is None

    def test_unparseable_node_segment(self):
        assert _matter_node_id(["deviceid_FABRIC-NOTHEX-MatterNodeDevice"]) is None

    def test_no_identifiers(self):
        assert _matter_node_id([]) is None


class TestParseNodeDiagnostics:
    """Reading matter-server's NodeDiagnostics across a library boundary."""

    @staticmethod
    def _enum(value):
        return SimpleNamespace(value=value)

    def _diagnostics(self, **overrides):
        base = SimpleNamespace(
            node_id=87,
            network_type=self._enum("thread"),
            node_type=self._enum("sleepy_end_device"),
            network_name="ha-thread-0d68",
            ip_adresses=["fd00:1234:5678:9abc::5"],
            mac_address="0a:79:9b:2b:d2:12:3f:8f",
            available=True,
        )
        for key, value in overrides.items():
            setattr(base, key, value)
        return base

    def test_unwraps_enums(self):
        parsed = _parse_node_diagnostics(self._diagnostics())

        assert parsed["transport"] == "thread"
        assert parsed["node_type"] == "sleepy_end_device"

    def test_accepts_a_plain_string_network_type(self):
        parsed = _parse_node_diagnostics(self._diagnostics(network_type="wifi"))

        assert parsed["transport"] == "wifi"

    def test_reads_the_upstream_misspelled_ip_field(self):
        """python-matter-server spells the field "ip_adresses"."""
        parsed = _parse_node_diagnostics(self._diagnostics())

        assert parsed["ip_addresses"] == ["fd00:1234:5678:9abc::5"]

    def test_reads_the_field_if_upstream_corrects_the_spelling(self):
        diagnostics = self._diagnostics()
        del diagnostics.ip_adresses
        diagnostics.ip_addresses = ["fd00::2"]

        assert _parse_node_diagnostics(diagnostics)["ip_addresses"] == ["fd00::2"]

    def test_mac_address_is_passed_through(self):
        parsed = _parse_node_diagnostics(self._diagnostics())

        assert parsed["mac_address"] == "0a:79:9b:2b:d2:12:3f:8f"

    def test_availability_is_captured(self):
        assert _parse_node_diagnostics(self._diagnostics(available=False))["available"] is False

    def test_missing_fields_do_not_raise(self):
        parsed = _parse_node_diagnostics(SimpleNamespace())

        assert parsed["transport"] == "unknown"
        assert parsed["mac_address"] is None
        assert parsed["ip_addresses"] == []


class TestMatterDeviceCollection:
    """Building the Matter device list from matter-server diagnostics.

    The sleepy end device below is the real failure this replaced: its MAC was
    read from cached GeneralDiagnostics cluster attributes, which come and go
    for battery devices, so the child's name flickered in and out of the map.
    """

    IDENTIFIER = "deviceid_9DEA92C0F9B67B5E-0000000000000057-MatterNodeDevice"
    SERIAL = "serial_1035970000189A08"
    NODE_ID = 0x57

    @pytest.fixture
    def registry_device(self):
        # Both identifiers, in a set, exactly as Home Assistant stores them.
        return SimpleNamespace(
            identifiers={("matter", self.IDENTIFIER), ("matter", self.SERIAL)},
            name="BILRESA dual button",
            name_by_user="Bedroom BILRESA button",
            model="BILRESA dual button",
            manufacturer="IKEA of Sweden",
        )

    @pytest.fixture
    def wired(self, coordinator, monkeypatch, registry_device):
        monkeypatch.setattr(coordinator_module, "_MATTER_AVAILABLE", True)
        registry = MagicMock()
        registry.devices.values.return_value = [registry_device]
        monkeypatch.setattr(coordinator_module.dr, "async_get", lambda hass: registry)
        return coordinator

    def _install_client(self, monkeypatch, node_diagnostics, node_ids=(NODE_ID,)):
        client = MagicMock()
        client.get_nodes.return_value = [
            SimpleNamespace(node_id=node_id) for node_id in node_ids
        ]
        client.node_diagnostics = node_diagnostics
        monkeypatch.setattr(
            coordinator_module,
            "get_matter",
            lambda hass: SimpleNamespace(matter_client=client),
            raising=False,
        )

    async def test_thread_device_is_fully_resolved(self, wired, monkeypatch):
        async def node_diagnostics(node_id):
            assert node_id == self.NODE_ID
            return SimpleNamespace(
                network_type=SimpleNamespace(value="thread"),
                node_type=SimpleNamespace(value="sleepy_end_device"),
                ip_adresses=["fd00::5"],
                mac_address="0a:79:9b:2b:d2:12:3f:8f",
                available=True,
            )

        self._install_client(monkeypatch, node_diagnostics)

        devices = await wired._async_get_matter_devices()

        assert len(devices) == 1
        assert devices[0]["transport"] == "thread"
        assert devices[0]["ext_address"] == "0A799B2BD2123F8F"
        assert devices[0]["available"] is True

    async def test_user_assigned_name_wins(self, wired, monkeypatch):
        async def node_diagnostics(node_id):
            return SimpleNamespace(
                network_type=SimpleNamespace(value="thread"),
                mac_address="0a:79:9b:2b:d2:12:3f:8f",
            )

        self._install_client(monkeypatch, node_diagnostics)

        devices = await wired._async_get_matter_devices()

        assert devices[0]["name"] == "Bedroom BILRESA button"

    async def test_falls_back_when_a_node_reports_nothing(self, wired, monkeypatch):
        """The device still appears, without an invented Thread membership."""
        async def node_diagnostics(node_id):
            raise RuntimeError("node unreachable")

        self._install_client(monkeypatch, node_diagnostics)

        devices = await wired._async_get_matter_devices()

        assert len(devices) == 1
        assert devices[0]["ext_address"] is None
        assert devices[0]["transport"] == "unknown"

    async def test_a_hanging_node_cannot_stall_the_update(self, wired, monkeypatch):
        """node_diagnostics reaches over the network; it must be bounded."""
        monkeypatch.setattr(coordinator_module, "MATTER_NODE_TIMEOUT", 0.05)

        async def node_diagnostics(node_id):
            await asyncio.sleep(30)

        self._install_client(monkeypatch, node_diagnostics)

        started = time.monotonic()
        devices = await wired._async_get_matter_devices()
        elapsed = time.monotonic() - started

        # Unbounded, this would sit here for 30 seconds holding up the update.
        assert elapsed < 5
        assert len(devices) == 1
        assert devices[0]["ext_address"] is None

    async def test_one_slow_node_does_not_lose_the_others(self, wired, monkeypatch):
        """Nodes are fetched concurrently, each with its own budget."""
        monkeypatch.setattr(coordinator_module, "MATTER_NODE_TIMEOUT", 0.05)

        async def node_diagnostics(node_id):
            if node_id != self.NODE_ID:
                await asyncio.sleep(30)
            return SimpleNamespace(
                network_type=SimpleNamespace(value="thread"),
                mac_address="0a:79:9b:2b:d2:12:3f:8f",
            )

        self._install_client(
            monkeypatch, node_diagnostics, node_ids=(0x99, self.NODE_ID, 0x98)
        )

        started = time.monotonic()
        devices = await wired._async_get_matter_devices()
        elapsed = time.monotonic() - started

        assert elapsed < 5
        assert devices[0]["ext_address"] == "0A799B2BD2123F8F"

    @pytest.mark.parametrize(
        "error",
        [
            IndexError("list index out of range"),
            KeyError("matter"),
            StopIteration(),
            AttributeError("adapter"),
        ],
    )
    async def test_survives_matter_client_errors(self, wired, monkeypatch, error):
        """get_matter() raced the Matter integration's setup and blew up."""
        monkeypatch.setattr(
            coordinator_module,
            "get_matter",
            MagicMock(side_effect=error),
            raising=False,
        )

        devices = await wired._async_get_matter_devices()

        assert len(devices) == 1
        assert devices[0]["transport"] == "unknown"

    async def test_identity_survives_a_node_going_quiet(self, wired, monkeypatch):
        """A node that misses one update must not lose its name on the map."""
        async def answering(node_id):
            return SimpleNamespace(
                network_type=SimpleNamespace(value="thread"),
                mac_address="0a:79:9b:2b:d2:12:3f:8f",
            )

        self._install_client(monkeypatch, answering)
        first = await wired._async_get_matter_devices()
        assert first[0]["ext_address"] == "0A799B2BD2123F8F"

        async def silent(node_id):
            raise RuntimeError("no answer")

        self._install_client(monkeypatch, silent)
        second = await wired._async_get_matter_devices()

        assert second[0]["ext_address"] == "0A799B2BD2123F8F"
        assert second[0]["transport"] == "thread"

    async def test_identity_survives_matter_going_away(self, wired, monkeypatch):
        async def answering(node_id):
            return SimpleNamespace(
                network_type=SimpleNamespace(value="thread"),
                mac_address="0a:79:9b:2b:d2:12:3f:8f",
            )

        self._install_client(monkeypatch, answering)
        await wired._async_get_matter_devices()

        monkeypatch.setattr(
            coordinator_module,
            "get_matter",
            MagicMock(side_effect=IndexError("list index out of range")),
            raising=False,
        )
        devices = await wired._async_get_matter_devices()

        assert devices[0]["ext_address"] == "0A799B2BD2123F8F"

    async def test_no_matter_integration_at_all(self, coordinator, monkeypatch):
        monkeypatch.setattr(coordinator_module, "_MATTER_AVAILABLE", False)
        registry = MagicMock()
        registry.devices.values.return_value = []
        monkeypatch.setattr(coordinator_module.dr, "async_get", lambda hass: registry)

        assert await coordinator._async_get_matter_devices() == []



class TestSvgWriting:
    """The SVG write must stay off the event loop."""

    def test_write_svg_creates_the_directory_and_file(self, coordinator, tmp_path):
        www = tmp_path / "www"
        coordinator.hass.config.path.return_value = str(www)

        written = coordinator._write_svg("<svg/>")

        assert Path(written) == www / "thread_topology.svg"
        assert Path(written).read_text(encoding="utf-8") == "<svg/>"

    def test_write_svg_tolerates_an_existing_directory(self, coordinator, tmp_path):
        www = tmp_path / "www"
        www.mkdir()
        coordinator.hass.config.path.return_value = str(www)

        assert coordinator._write_svg("<svg/>")

    async def test_save_svg_delegates_to_the_executor(self, coordinator):
        """Home Assistant warns if file I/O runs inline on the event loop."""
        calls = []

        async def fake_executor(func, *args):
            calls.append((func, args))
            return "/config/www/thread_topology.svg"

        coordinator.hass.async_add_executor_job = fake_executor

        result = await coordinator.save_svg_to_www({"nodes": {}})

        assert result == "/local/thread_topology.svg"
        assert calls and calls[0][0] == coordinator._write_svg

    async def test_save_svg_survives_a_write_failure(self, coordinator):
        async def failing_executor(func, *args):
            raise OSError("read-only filesystem")

        coordinator.hass.async_add_executor_job = failing_executor

        assert await coordinator.save_svg_to_www({"nodes": {}}) is None


class TestProcessTopologyStillHandlesLegacy:
    """The legacy path must keep working on older OTBR builds."""

    @pytest.fixture
    def topology(self, coordinator, mock_otbr_node_response,
                 mock_otbr_diagnostics_response) -> dict:
        return coordinator._process_topology(
            _translate_node(mock_otbr_node_response),
            mock_otbr_diagnostics_response,
            [],
            [],
        )

    def test_network_name(self, topology):
        assert topology["network_name"] == "MyHome1038137341"

    def test_link_quality(self, topology):
        assert all(
            node["link_quality"] == 3 for node in topology["nodes"].values()
        )

    def test_leader_falls_back_to_the_polled_otbr(self, topology):
        """No IsLeader flag on legacy builds, so the OTBR is assumed leader."""
        leaders = [
            address for address, node in topology["nodes"].items()
            if node["role"] == "leader"
        ]

        assert leaders == ["1EA5312CFB153F0B"]

    def test_total_devices(self, topology):
        assert topology["total_devices"] == 7
