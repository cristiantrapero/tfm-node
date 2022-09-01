# boot.py -- run on boot-up
from network import WLAN

# Disable Wi-Fi
wlan = WLAN()
wlan.deinit()
