# PROJECT CHARTER — thread_topology / modern OTBR JSON:API

Status: **delivered and verified in production** (created and completed 2026-07-27)

## 1. What is the one thing this must do?

Home Assistant must expose **live Thread link-quality sensor entities** — one per
mesh node, whose *state* is that node's LQI (0–3) — sourced from the OTBR at
`192.168.1.144:8081`, updating on a schedule, usable in automations.

## 2. What would be wrong if we shipped "working" software without it?

The integration loading without error, entities appearing, and every
`link_quality` reading **0** — because the JSON:API translator we are porting
from the JS visualizer never emits `Connectivity`. Green config entry, dead
sensors. That is the specific failure mode this charter exists to prevent.

Second failure of the same kind: the network sensor showing
`network_name: Unknown`, `router_count: 0`, and no node flagged as leader,
because `/node` now returns camelCase and `_process_topology` reads PascalCase.

## 3. What is explicitly off-limits as a workaround?

- Shipping with `link_quality` hardcoded, defaulted, or derived from anything
  other than real OTBR diagnostic data.
- Dropping the legacy `/diagnostics` path. Auto-detect must keep working on
  older OTBR builds.
- Requiring the user to hand-edit files inside the HA container to deploy.
  Deployment is HACS.
- Widening scope into the SVG generator, sensor platform, or Matter matching.
  The change is scoped to the **fetch layer + response key handling**.

## 4. Deployment target and backup location

- **Target:** HA Container `core-2026.7.4` at `192.168.1.25`, integration
  installed via **HACS** from `TeeJS/thread-topology` (currently pinned to
  commit `ddd858c`, tracking default branch). Deploy = commit → push → HACS
  update → restart HA.
- **Backup:** source is covered by git in this repo. Before the HACS update +
  restart, take a **full HA backup** so the live `/config` state is recoverable.

## 5. How will we verify it is done?

1. Config entry `01KSBAQ2H0JE4QWQGR899FYM0B` reaches state `loaded`
   (it has never once loaded since it was created 2026-05-23).
2. `sensor.thread_network` reports `network_name = ha-thread-0d68`,
   `router_count = 2` (not `Unknown` / `0`).
3. At least one `ThreadNodeSensor` exists with a **non-zero** numeric LQI state.
4. Exactly one node is flagged `role: leader`; others `router` / `end_device` —
   not everything collapsing to `end_device`.
5. Update cycles complete without overlapping (task flow measured ~48 s).
6. `pytest` green, including new tests driven by a real captured OTBR response.

---

## Outcome (2026-07-27)

Delivered in `TeeJS/thread-topology` PR #2, merged as `622d30a`, deployed via
HACS (`ddd858c` -> `622d30a`) after a full HA backup, and verified live.

| Criterion | Result |
|---|---|
| 1. Entry `loaded` | Yes - first successful load since it was created |
| 2. Network sensor | `ha-thread-0d68`, `router_count: 2` |
| 3. Non-zero LQI | Both node sensors report `3` |
| 4. One leader | `6a57f823187e197b`, the other node a `router` |
| 5. No overlapping updates | Scan interval auto-raised 30s -> 180s |
| 6. Tests green | 130 passing |

The failure mode named in section 2 was real and would have shipped: the JS
reference implementation this was ported from never requests the `mode` or
`connectivity` diagnostic TLVs, because the visualizer draws edges from route
data instead. Porting it faithfully would have produced loaded entities
reporting LQI 0 for every node. `/node` had also silently moved to camelCase
and renamed `NumOfRouter` to `routerCount`, which had been breaking leader
detection, network name and router count independently of the 404.

Also fixed along the way: the polled border router now honours
`custom_routers.yaml` instead of being hardcoded to "SkyConnect (OTBR)", and
the SVG write moved off the event loop.

### Fixed after the first deployment

Restarting Home Assistant put the entry into `setup_retry` with
`list index out of range`. `get_matter()` indexes into `hass.data["matter"]`,
which is still empty if the Matter integration has not finished setting up, and
`_get_matter_devices` caught `KeyError, StopIteration, AttributeError,
ImportError` but not `IndexError` - so a race over what is only optional
enrichment failed the entire update. It self-healed on retry, but recurred
whenever Matter lost the race. `IndexError` is now caught, with a test that
reproduces the original failure.

### Unidentified routers are no longer given invented vendors

`_identify_router`'s last-resort fallback chose a name from a rotating list
(`Eero`, `Google Nest`, `Apple HomePod`, `SmartThings`) by iteration order, so
the first unrecognised router was labelled "Eero / Amazon-Eero" whatever it
was. On this network that presented an IKEA air quality monitor as an Eero, and
the label changed run to run as ordering shifted. Unidentified nodes are now
named after their own address (`Thread Router 197B`) with manufacturer
`Unknown`; `custom_routers.yaml` remains the way to supply a real name.

`BORDER_ROUTER_PATTERNS` was the other half of the same problem: it matched the
bare substring `EA` anywhere in an extended address and called the result an
Eero, which fits roughly one address in eighteen. Suffix matching is now
anchored to the end of the address and the bare `EA` entry is gone, leaving only
the specific `EA17` ending that the original comment actually described.

### The "13 Matter Thread devices vs 3 mesh nodes" gap, resolved

The mesh crawl was right; the Matter count was wrong.

Transport was guessed from strings: `"wifi" in model`, plus a three-name
manufacturer allowlist, defaulting to Thread. TP-Link's model reads "Smart
**Wi-Fi** Dimmer Switch" - hyphenated, so the test never fired - and Leedarson,
Sciener and Shelly are not in the allowlist. Every Matter device therefore
defaulted to Thread, giving "13 Thread + 0 Wi-Fi" against a true split of 5 and
8. Of those 5 Thread devices only 2 were online, which together with the OTBR
is exactly the 3 nodes the crawl reported.

Transport now comes from the node's own `GeneralDiagnostics.NetworkInterfaces`
interface type. The string heuristic survives only as a fallback for nodes that
report no interfaces, and it can no longer return "thread" - an honest
"unknown" keeps a device out of the topology rather than inventing a place for
it in the mesh.

That misclassification also fed the child matcher, which handed out "the next
unclaimed Thread device" positionally and so labelled the border router's child
as a Leedarson Wi-Fi bulb that was offline at the time. Children are now matched
on identity only - extended address, else shared IPv6 - and an unidentifiable
child is left unnamed. Verified against the live network: matter-server reports
the real child's MAC as `0a:79:9b:2b:d2:12:3f:8f`, matching the extended
address OTBR reports for it exactly.

Device names now prefer `name_by_user` over `name`, so renames made in Home
Assistant are respected. Both of this network's air quality monitors carry the
same factory name, which made the map ambiguous about which one it was showing.

### Why Matter device identity flickered between restarts

Making the above honest exposed a bug that had been masked all along: Matter
devices kept losing their identity from one restart to the next, so the child's
name and the Thread device count changed for no visible reason.

The cause was identifier selection. A Matter device carries more than one
`matter` identifier - a `deviceid_<fabric>-<node>-MatterNodeDevice` and a
`serial_<serial>` - and `device.identifiers` is a **set**. The code read
whichever came out first and stopped. Python randomises string hashing per
process, so a different identifier won on each start, and whenever the serial
won there was no node id to parse, the device silently got no diagnostics, and
every name and radio derived from it vanished. Only the `deviceid` form is
parsed now, so a serial containing a dash cannot be mistaken for one either.

Demonstrated rather than argued: with the old "first identifier wins" logic the
tests fail under `PYTHONHASHSEED` 1, 5 and 6 and pass under 0, 2, 3, 4, 7, 8, 9
and 12345. With the fix every seed passes.

An earlier reading of this blamed cached `GeneralDiagnostics.NetworkInterfaces`
attributes being unreliable for sleepy end devices. That was wrong - matter-server
was reporting the device correctly the whole time.

### Matter is now set up before this integration polls

The identifier fix was necessary but not sufficient: restarts still produced a
degraded first snapshot. The Matter integration finished setting up at
`03:14:40` while this integration had already run its first poll, so no Matter
device had an identity yet, and with a 180s interval that snapshot stood for
three minutes before the next poll corrected it. Once Matter is up, every node
answers - `Matter diagnostics: 15/15 node(s) reported`.

`after_dependencies: ["matter"]` in the manifest is Home Assistant's mechanism
for exactly this, and is the right one here rather than `dependencies`: Matter
is optional enrichment and the integration must still load without it.

A node's last known identity is also remembered now. A MAC and a radio are
stable facts, so a node that misses one update no longer drops its extended
address and take every name matched from it off the map.

### Matter identity now comes from matter-server, not cached cluster attributes

Independently worth doing, and done at the same time. `_get_matter_devices`
read each node's MAC and radio from cached cluster attributes, with a comment
explaining that it did so to stay synchronous. The method is now async - it is
only ever called from `_async_update_data`, which already was - and awaits
`matter_client.node_diagnostics()` per node, concurrently, each bounded by
`MATTER_NODE_TIMEOUT` so an unreachable node cannot stall an update. That call
returns `network_type` directly, so the radio is read rather than inferred, and
the `chip.clusters` and `base64` imports are gone entirely.
