# ha-glinet-integration
staging repo for an GL-inet integration for homeassistant

## Install
1. Create a new folder in `config/custom_components` called glinet
2. Copy manually, or clone the files in this repo into that folder `git clone https://github.com/HarvsG/ha-glinet-integration.git .` (The `.` at the end is important)
3. Reboot homeassistant
4. Add the new Glinet integration under Devices and services

## Features
- Device tracker for devices connected directly or indirectly to a Gl-inet router
- Control a configured wireguard client with a switch

## TODO
- [ ] Auto detect router IP for config flow - assume it is the default gateway, test an enpoint that doesn't require auth (/model or /hello), fallback to default `192.168.8.1`
- [ ] Add switches for wireguard and open vpn (client and server), done for wireguard client, but we can probably do all programatically rather than repeating boilerplate
  - worth considering you can have multiple clients, most of the API endpoints act on the last used client config. Can we get a list from the API and create switches for all? Maybe (router/vpn/status?)
- [ ] Support HACS - lets get some more features working first
- [ ] Allow deletion of unhelpful device tracker devices/entities
- [ ] Clean, comment and refactor code
- [ ] Add tests - will need to mock the API
- [ ] Add features:
  - Upload/Download sensors
  - Internet reachable sensors (remember that API timesout when internet not reachable)
  - Public IP sensor
  - Sensor for firmware version (/hello)
  - Diagnostic sensors for stats in (/router/status) such as uptime, LAN IP and memory useage
- [ ] Consider features
  - Firmware upgrades https://dev.gl-inet.com/api/#api-firmware (should have warnings)
  - Switch for LED control https://dev.gl-inet.com/api/#api-cloud-PostLedEnable
  - Router reboot button (/router/reboot) might be useful for some automations
  - ?custom ping sensor(s)
  - Tethering controls:https://dev.gl-inet.com/api/#api-tethering
  - Modem control (useful for failover internet automations
  - ?SMS control - maybe a notify platform
  - Explore using the smarthome BLE endpoints: https://dev.gl-inet.com/api/#api-SmartHome
  

## Tested on
- Beryl MT3000
- Convexa B1300

## Depends on
https://github.com/HarvsG/gli_py
