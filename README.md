# ha-glinet4-integration
A HomeAssistant custom component for GL-iNet routers that uses [their API version 4](https://dev.gl-inet.com/api/).

Working - in alpha, breaking changes very likely.

Contributions are welcome, for ideas see the TODO list below or the various `#TODO`s in the code.

## Features
- Device tracker for devices connected directly or indirectly to a Gl-inet router.
  - Note, modern phones use MAC address randomisation when they connect to WiFi, you will need to disable this for your home wifi only on [android](https://www.howtogeek.com/722653/how-to-disable-random-wi-fi-mac-address-on-android/) and [iphone](https://www.linksys.com/support-article?articleNum=317709)
- Control all configured wireguard and tailscale clients with a switch.
- Reboot your router
- System device sensors including CPU temperature (if supported by your device), CPU load and Uptime
- Coming soon:
  - On/off control of WiFi Networks

## Installation
1. [Install HACS](https://www.youtube.com/watch?v=a4lSlN6EI04)
2. Open the HACS page in home assistant
3. Click the 3 dot menu in the top right
4. Click `Custom repositories`
5. Paste `https://github.com/HarvsG/ha-glinet4-integration`, select type `Integration`
6. Search fo `GL.inet` in HACS and download the latest version
7. Consider restarting Home Assistant
8. Go to Devices and Services and click `Add Integration` and select `GL-iNet`

## Dev set up
1. Set up the vscode homeassistant core [dev setup](https://developers.home-assistant.io/docs/development_environment/)
  - Or you could just use a running install of homeassistant (restarts are required for a lot of changes)
2. Run once to generate directories
3. Create a new directory `/workspaces/glinet`
4. Cntr Shift P, `add folder to workspace` and then add the above folder
5. `cd` into that directory
6. `git clone https://github.com/HarvsG/ha-glinet4-integration.git . `
7. `mkdir -p /workspaces/core/config/custom_components && cd /workspaces/core/config/custom_components`
8. `ln -s /workspaces/glinet/custom_components/glinet`
9. You may need to config a new ssh key inside the container. [Use this](https://docs.github.com/en/authentication/connecting-to-github-with-ssh/adding-a-new-ssh-key-to-your-github-account) - this will be overwitten if you rebuild the container

## TODO
- [ ] Handle all the errors gracefully, including empty client lists that happen after a glinet device restart.
- [ ] Auto detect router IP for config flow - assume it is the default gateway, test an enpoint that doesn't require auth (/model or /hello), fallback to default `192.168.8.1`
- [ ] Add switches for wireguard and open vpn (client and server), done for wireguard client, but we can probably do all programatically rather than repeating boilerplate
  - worth considering you can have multiple clients, most of the API endpoints act on the last used client config. Can we get a list from the API and create switches for all? Maybe (router/vpn/status?)
- [ ] Allow deletion of unhelpful device tracker devices/entities, [docs](https://developers.home-assistant.io/docs/device_registry_index/#removing-devices), [example](https://github.com/home-assistant/core/pull/73293/commits/9c253c6072cf60f92228051d918fd550d38b6ac3)
- [ ] Enable strict type checking with mypy and a github action
- [ ] Add tests - will need to mock the API
- [ ] Detect and create a re-configure entry if the password changes
- [ ] Enable support for `https` as well as `http` and consider enabling it by default.
- [ ] Static type gli4py and then enable static typing on this repo
- [ ] Add features:
  - Upload/Download sensors
  - Internet reachable sensors (remember that API timesout when internet not reachable)
  - Public IP sensor
- [ ] Features under consideration
  - Making changes to the VPN client policies would be cool to automate switching on/off VPN use per device in automations. Useful for bypassing geofilters for example
  - Firmware upgrades https://dev.gl-inet.com/api/#api-firmware (should have warnings)
  - Switch for LED control https://dev.gl-inet.com/api/#api-cloud-PostLedEnable
  - Tethering controls:https://dev.gl-inet.com/api/#api-tethering
  - Modem control (useful for failover internet automations)
  - ?SMS control - maybe a notify platform [see example](https://github.com/home-assistant/core/blob/dev/homeassistant/components/sms/notify.py)
  - Explore using the smarthome BLE endpoints: https://dev.gl-inet.com/api/#api-SmartHome


## Tested on
- Beryl MT3000
- Convexa B1300

## Depends on
https://github.com/HarvsG/gli4py
