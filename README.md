# ha-glinet4-integration
A HomeAssistant custom component for GL-inet routers that uses [their API] version 4(https://dev.gl-inet.com/api/).

Working - in alpha, breaking changes very likely.

Contributions are welcome, for ideas see the TODO list below or the various `#TODO`s in the code.

## Features
- Device tracker for devices connected directly or indirectly to a Gl-inet router.
  - Note, modern phones use MAC address randomisation when they connect to WiFi, you will need to disable this for your home wifi only on [android](https://www.howtogeek.com/722653/how-to-disable-random-wi-fi-mac-address-on-android/) and [iphone](https://www.linksys.com/support-article?articleNum=317709)
- Control all configured wireguard clients with a switch.

## Installation
1. Create a new folder in `config/custom_components` called glinet
2. Copy manually, or clone the files in this repo into that folder `git clone https://github.com/HarvsG/ha-glinet-integration.git . ` (The `.` at the end is important)
3. Reboot homeassistant
4. Add the new Glinet integration under Devices and services
5. Edit the host path with you router IP - ensure you keep the `http://`
6. Add your router admin page login password (not your WIFI password). Placeholder is GL-inet's default `goodlife`, but this shoudld be changed.

## Dev set up
1. Set up the vscode homeassistant core [dev setup](https://developers.home-assistant.io/docs/development_environment/)
  - Or you could just use a running install of homeassistant (restarts are required for a lot of changes)
2. Run once to generate directories
3. create a `config/custom_components/glinet` directory
4. `git clone https://github.com/HarvsG/ha-glinet-integration.git . `
5. Note, the vscode git tracker will track the parent repo (ha core), but command line git will still work within the `glinet` dir
6. You may need to config a new ssh key inside the container. [Use this](https://docs.github.com/en/authentication/connecting-to-github-with-ssh/adding-a-new-ssh-key-to-your-github-account) - this will be overwitten if you rebuild the container

## TODO
- [ ] Auto detect router IP for config flow - assume it is the default gateway, test an enpoint that doesn't require auth (/model or /hello), fallback to default `192.168.8.1`
- [ ] Add switches for wireguard and open vpn (client and server), done for wireguard client, but we can probably do all programatically rather than repeating boilerplate
  - worth considering you can have multiple clients, most of the API endpoints act on the last used client config. Can we get a list from the API and create switches for all? Maybe (router/vpn/status?)
- [ ] Support HACS - lets get some more features working first
- [ ] Allow deletion of unhelpful device tracker devices/entities, [docs](https://developers.home-assistant.io/docs/device_registry_index/#removing-devices), [example](https://github.com/home-assistant/core/pull/73293/commits/9c253c6072cf60f92228051d918fd550d38b6ac3)
- [ ] Clean, comment and refactor code
- [ ] Add tests - will need to mock the API
- [ ] Allow reconfig for password changes - currently have to delete and re-add integration
- [ ] Look into using `https` instead of `http`
- [ ] Add features:
  - Upload/Download sensors
  - Internet reachable sensors (remember that API timesout when internet not reachable)
  - Public IP sensor
  - Diagnostic sensors for stats in (/router/status) such as uptime, LAN IP and memory useage
- [ ] Consider features
  - Making changes to the VPN client policies would be cool to automate switching on/off VPN use per device in automations. Useful for bypassing geofilters for example
  - Firmware upgrades https://dev.gl-inet.com/api/#api-firmware (should have warnings)
  - Switch for LED control https://dev.gl-inet.com/api/#api-cloud-PostLedEnable
  - Router reboot button (/router/reboot) might be useful for some automations
  - ?custom ping sensor(s)
  - Tethering controls:https://dev.gl-inet.com/api/#api-tethering
  - Modem control (useful for failover internet automations)
  - ?SMS control - maybe a notify platform [see example](https://github.com/home-assistant/core/blob/dev/homeassistant/components/sms/notify.py)
  - Explore using the smarthome BLE endpoints: https://dev.gl-inet.com/api/#api-SmartHome


## Tested on
- Beryl MT3000
- Convexa B1300

## Depends on
https://github.com/HarvsG/gli4py
