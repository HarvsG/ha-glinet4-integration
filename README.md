# ha-glinet-integration
staging repo for an GL-inet integration for homeassistant

## Install
1. Create a new folder in `config/custom_components` called glinet
2. Copy manually, or clone the files in this repo into that folder `git clone https://github.com/HarvsG/ha-glinet-integration.git .` (The `.` at the end is important)
3. Reboot homeassistant
4. Add the new Glinet integration under Devices and services

## Features
- Device tracker for devices connected directly or indirectly to a Gl-inet router

## TODO
- [ ] Auto detect IP for config flow
- [ ] Add switches for wireguard and open vpn (client and server)
- [ ] Support HACS
