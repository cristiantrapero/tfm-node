# Una solución basada en LoRa para comunicaciones multimedia en entornos extremos
The main objective of this work will be to develop a communications system that allows multimedia traffic of any size to be sent over long distances using the **LoRa RAW** (pure LoRa, no LoRaWAN) channel.

# WiFi version
![WiFi version](https://upload.wikimedia.org/wikipedia/commons/thumb/a/ae/WiFi_Logo.svg/320px-WiFi_Logo.svg.png)

This is implemented for the __Pycom LoPy 4__. The LoPy setups a BLE server to be able to connect to an Android application to manage the sending of multimedia files and once receive, it is forwarded to another LoPy 4.

# How to setup the application
1. Install **NojeJS** depending on the operating system you have using https://nodejs.org/es/download/ or with NVM https://github.com/nvm-sh/nvm
2. Install the **Pymakr tool** for Atom as described here: https://docs.pycom.io/gettingstarted/software/atom/
3. Clone this repository: `git clone https://github.com/cristiantrapero/tfm-node.git`
4. Open this project in Atom
5. Connect the LoPy 4 to the computer USB
6. Select `Upload project to device`
7. Wait until load the project in the LoPy 4
8. Open the `main.py` file in the Atom editor and select `Run selected file` in the Pymakr bar.
9. Connect the Android application to the sender node and take the image and send it. The application is located in: https://github.com/cristiantrapero/tfm-android

# Files
The repository is structured as follow:

- boot.py: Disables WiFi to avoid interferences.
- main.py: Main function. Setup BLE, LoRa and all necessary to run the node.
- `lib`: LoRaCTP protocol library.
  - loractp.py: Contains the Lora Content Transfer Protocol (loractp) with his API.

## Firmware versions
LoPy4 firmware version:
- Pycom MicroPython: **1.20.2.r6 [v1.11-c5a0a97]** released at 2021-10-28.
- Pybytes Version: **1.7.1**

Pysense v1.0 firmware version:
- DFU version: **0.0.8** available at https://docs.pycom.io/updatefirmware/expansionboard/
