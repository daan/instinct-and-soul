import network

wlan = network.WLAN(network.STA_IF)
wlan.active(True)

for ssid, bssid, channel, rssi, authmode, hidden in wlan.scan():
    print(ssid, rssi)
