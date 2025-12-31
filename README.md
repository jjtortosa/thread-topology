# Thread Network Topology for Home Assistant

[![hacs_badge](https://img.shields.io/badge/HACS-Custom-41BDF5.svg)](https://github.com/hacs/integration)
[![GitHub Release](https://img.shields.io/github/release/jjtortosa/thread-topology.svg)](https://github.com/jjtortosa/thread-topology/releases)
[![License](https://img.shields.io/github/license/jjtortosa/thread-topology.svg)](LICENSE)

A Home Assistant custom integration that visualizes your Thread network topology, similar to the Zigbee network map. See your Thread Border Routers, end devices, and their connections at a glance.

![Thread Topology Map](images/topology-map.png)

## Features

- **Visual Topology Map**: See your entire Thread network structure in a markdown card
- **Device Identification**: Automatically identifies border routers (SkyConnect, Eero, Apple, Google)
- **Matter Integration**: Links Thread devices with their Matter device names from Home Assistant
- **Link Quality Indicators**: Visual representation of connection quality (Poor/Fair/Good/Excellent)
- **WiFi vs Thread**: Separates Matter devices by transport type
- **Real-time Updates**: Polls OTBR every 60 seconds for network changes

## What You'll See

```
🧵 Thread Network: MyHome

Routers: 2 | Thread Devices: 4
Matter: 3 Thread + 2 WiFi

---

👑 SkyConnect (OTBR)
Nabu Casa • Leader • LQ: [███] Excellent

   └─ 💤 Smart Presence Sensor
       Meross Smart Presence Sensor

📡 Eero Border Router
Amazon/Eero • Router • LQ: [███] Excellent

   └─ 💤 Aqara Door and Window Sensor P2
       Aqara Aqara Door and Window Sensor P2

---

📶 Matter over WiFi
- Smart Lock (Nuki)
- WiFi Smart Switch (SONOFF)
```

## Requirements

- Home Assistant 2024.1.0 or newer
- OpenThread Border Router (OTBR) addon running
- Thread network with at least one border router

## Installation

### HACS (Recommended)

1. Open HACS in Home Assistant
2. Click the three dots menu → **Custom repositories**
3. Add `https://github.com/jjtortosa/thread-topology` as an **Integration**
4. Search for "Thread Network Topology" and install
5. Restart Home Assistant

### Manual Installation

1. Download the latest release from GitHub
2. Copy `custom_components/thread_topology` to your Home Assistant `config/custom_components/` directory
3. Restart Home Assistant

## Configuration

1. Go to **Settings** → **Devices & Services**
2. Click **+ Add Integration**
3. Search for "Thread Network Topology"
4. Enter your OTBR URL (default: `http://core-openthread-border-router:8081`)
5. Click **Submit**

### Default OTBR URLs

| Setup | URL |
|-------|-----|
| Home Assistant OS with OTBR addon | `http://core-openthread-border-router:8081` |
| Docker OTBR | `http://localhost:8081` or `http://<docker-host>:8081` |
| Standalone OTBR | `http://<otbr-ip>:8081` |

## Sensors Created

| Sensor | Description |
|--------|-------------|
| `sensor.thread_network` | Network name and overview stats |
| `sensor.thread_topology_map` | Full topology as markdown text |
| `sensor.thread_<router_name>` | One sensor per router with link quality |

## Dashboard Card

Add a Markdown card to display the topology:

```yaml
type: markdown
title: Thread Network
content: "{{ state_attr('sensor.thread_topology_map', 'topology_text') }}"
```

## How It Works

1. **OTBR API**: Fetches network data from `/node` and `/diagnostics` endpoints
2. **Device Registry**: Queries Home Assistant's device registry for Matter devices
3. **Smart Matching**: Maps Thread extended addresses to Matter device names
4. **Transport Detection**: Identifies WiFi vs Thread based on device model/manufacturer

## Supported Border Routers

The integration automatically identifies:
- **Nabu Casa SkyConnect** (OTBR leader)
- **Amazon Eero** mesh routers
- **Apple HomePod** / HomePod Mini
- **Google Nest** Hub / WiFi
- Other Thread Border Routers

## Troubleshooting

### "Cannot connect to OTBR"
- Ensure the OpenThread Border Router addon is running
- Check if the URL is correct (try accessing it in your browser)
- Verify network connectivity between HA and OTBR

### Devices not showing names
- The integration matches Thread devices with Matter devices in HA
- Ensure your Matter devices are properly configured in Home Assistant
- WiFi-based Matter devices won't appear in the Thread topology

### Missing end devices
- Sleepy end devices may take time to appear after joining
- Try refreshing the data by reloading the integration

## Contributing

Contributions are welcome! Please feel free to submit a Pull Request.

## License

This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details.

## Credits

- Built for the Home Assistant community
- Inspired by the Zigbee network map functionality
- Uses the OpenThread Border Router REST API

## Support

- [GitHub Issues](https://github.com/jjtortosa/thread-topology/issues)
- [Home Assistant Community](https://community.home-assistant.io/)
