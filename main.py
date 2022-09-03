from network        import WLAN
from time           import sleep
from MicroWebSrv2   import *
import loractp
import pycom
import gc
import time
import ujson
import ucrypto
import math
import _thread
import socket
import sys


global LORA_CONNECTED
LORA_CONNECTED = False

# This is for semaphore
baton = _thread.allocate_lock()

gc.enable()

class WiFi:
    def __init__(self, name, ip):
        """
        Initialize the WiFi class
        """
        self.name = name
        self.ip = ip
        self.wlan = WLAN()

    def enable(self):
        """
        Enable WiFi AP
        """
        self.wlan.init(mode=WLAN.AP, ssid=self.name, auth=None, channel=10, antenna=WLAN.INT_ANT)
        self.wlan.ifconfig(config=(self.ip, '255.255.255.0', self.ip, '8.8.8.8'))
        print("WiFi enabled with IP: {}".format(self.ip))

    def get_ip(self):
        """
        Returns the IP address of the WiFi interface
        """
        return self.ip

    def get_name(self):
        """
        Returns the name of the WiFi network
        """
        return self.name

    def has_connected_clients(self):
        """
        Returns True if there are connected clients
        """
        return self.wlan.isconnected()

    def ap_sta_list(self):
        """
        Returns a list of connected clients
        """
        clients = []
        for client in self.wlan.ap_tcpip_sta_list():
            clients.append(client[1])
        return clients

class Node:
    def __init__(self, ctpc, wifi, node_name):
        self.ctpc = ctpc
        self.wifi = wifi
        self.node_name = node_name

    @WebRoute(GET, '/info')
    def get_node_info(microWebSrv2, request):
        """
        Returns the node info
        """
        lora_nodes = ctpc.get_discovered_nodes()
        return request.Response.ReturnOkJSON({
            'wifi_name'     : wifi.get_name(),
            'wifi_ip'       : wifi.get_ip(),
            'lora_uid'      : ctpc.get_lora_mac(),
            'address'       : ctpc.get_my_addr(),
            'nodes'         : {
                                "availables"    :   len(lora_nodes),
                                "addresses"     :   lora_nodes
                            },
            'clients'       : wifi.ap_sta_list()
        })

    @WebRoute(GET, '/nodes')
    def get_discovered_nodes(microWebSrv2, request):
        """
        Returns the LoRa discovered nodes
        """
        lora_nodes = ctpc.get_discovered_nodes()
        request.Response.ReturnOkJSON({
            'nodes' : {
                        "availables"    :   len(lora_nodes),
                        "addresses"     :   lora_nodes
            }})

    @WebRoute(GET, '/hello')
    def send_hello(microWebSrv2, request):
        """
        Send a hello message to the LoRa network
        """
        LORA_CONNECTED = True
        myaddr, rcvraddr, quality, status = ctpc.hello()
        LORA_CONNECTED = False
        print(myaddr, rcvraddr, quality, status)
        if status == 0:
            request.Response.ReturnOkJSON({"status" : "success"})
        else:
            request.Response.ReturnOkJSON({"status" : "fail"})

    @WebRoute(GET, '/message')
    def get_messages(microWebSrv2, request):
        """
        Returns the LoRa messages
        """
        return request.Response.ReturnOkJSON({"message" : "test"})

    @WebRoute(POST, '/message', 'message')
    def send_message(microWebSrv2, request):
        """
        Send a message to the LoRa node
        """
        data = request.GetPostedJSONObject()
        try:
            address = data['address'].encode()
            message = ujson.dumps(data['message']).encode()
            broadcast = data['broadcast']

            if broadcast:
                address = ctpc.ANY_ADDR

            print("Sending message {} to {} -- broadcast {}".format(message, address, broadcast))
            #baton.acquire()
            addr, quality, result = ctpc.sendit(address, message)
            #baton.release()
            request.Response.ReturnOkJSON({"status" : result})
        except Exception as ex:
            print(ex)
            request.Response.ReturnJSON(500, {"status" : "You have to send a JSON with address, message and broadcast"})


    def send_lora_hello(self, delay, id):
        """
        Thread to end a hello message to the LoRa network
        """
        while True:
            LORA_CONNECTED = True
            myaddr, rcvraddr, quality, status = self.ctpc.hello()
            LORA_CONNECTED = False
            time.sleep(delay)

    def change_led_status(self):
        """
        Thread to change the LED status
        """
        while True:
            connected_clients = wifi.has_connected_clients()
            if not LORA_CONNECTED and not connected_clients:
                pycom.rgbled(0x7f0000) #red
            if not LORA_CONNECTED and connected_clients:
                pycom.rgbled(0x0000FF) #blue
            if LORA_CONNECTED and not connected_clients:
                pycom.rgbled(0xFFFF00) #yellow
            if LORA_CONNECTED and connected_clients:
                pycom.rgbled(0x007f00) #green
            time.sleep(1)

    def receive_lora_data(self):
        """
        Thread to receive the LoRa node messages
        """
        while True:
            try:
                #baton.acquire()
                LORA_CONNECTED = True
                rcvd_data, snd_addr = self.ctpc.recvit()
                print("Received from {}: {}".format(snd_addr.decode('utf-8'), rcvd_data))
                LORA_CONNECTED = False
                #baton.release()
            except Exception as ex:
                print("Exception: {}".format(ex))

# Create LoRa CTPC endpoint
ctpc = loractp.CTPendpoint(debug_send=False, debug_recv=False)
node_name = "NODE-{}".format(ctpc.get_my_addr())
print("\n=========================")
print("LoRa node: {}".format(node_name))
print("=========================\n")

# Enable WiFi
wifi = WiFi(node_name, '192.168.4.1')
wifi.enable()

# Wait for WiFi complete
sleep(5)

# Create Node
node = Node(ctpc, wifi, node_name)

# Send hello to others lora nodes in a thread every 60 seconds
_thread.start_new_thread(node.send_lora_hello, (60, 1))

# Change LED status every second
_thread.start_new_thread(node.change_led_status, ())

# Thread for receive LoRa data
_thread.start_new_thread(node.receive_lora_data, ())

# Enable Webserver
# Instanciates the MicroWebSrv2 class
mws2 = MicroWebSrv2()

# Loads the PyhtmlTemplate module globally and configure it,
pyhtmlMod = mws2.LoadModule('PyhtmlTemplate')
pyhtmlMod.ShowDebug = True

# For embedded MicroPython, use a very light configuration,
mws2.SetEmbeddedConfig()
mws2.StartManaged()

try :
    while mws2.IsRunning:
        sleep(1)
except KeyboardInterrupt:
    mws2.Stop()
    print("Stop node")
