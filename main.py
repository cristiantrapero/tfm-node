from network            import WLAN
from time               import sleep
from lib.MicroWebSrv2   import *
import loractp
import pycom
import gc
import time
import ujson
import _thread
import socket
import database

# Set the LED to green
global LORA_CONNECTED
LORA_CONNECTED = False

# This is for semaphore
baton = _thread.allocate_lock()

# Enable garbage collector
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
        print("WiFi {} enabled with IP: {}".format(self.name, self.ip))

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

    def clients_list(self):
        """
        Returns a list of connected clients
        """
        clients = []
        for client in self.wlan.ap_tcpip_sta_list():
            # Add only the IP address
            clients.append(client[1])
        return clients

class Node:
    def __init__(self, ctpc, wifi, database, node_name):
        """
        Initialize the Node class with the LoRa CTPC object, the WiFi object and the node name
        """
        self.ctpc = ctpc
        self.wifi = wifi
        self.database = database
        self.node_name = node_name

    @WebRoute(GET, '/info')
    def get_node_info(microWebSrv2, request):
        """
        Returns the LoRa node info
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
            'clients'       : wifi.clients_list()
        })

    @WebRoute(GET, '/nodes')
    def get_discovered_nodes(microWebSrv2, request):
        """
        Returns the LoRa discovered nodes
        """
        lora_nodes = ctpc.get_discovered_nodes()
        return request.Response.ReturnOkJSON({
            'nodes' : {
                        "availables"    :   len(lora_nodes),
                        "addresses"     :   lora_nodes
            }})

    @WebRoute(POST, '/hello')
    def send_hello(microWebSrv2, request):
        """
        Send hello message to the LoRa network
        """
        LORA_CONNECTED = True
        myaddr, rcvraddr, quality, status = ctpc.hello()
        LORA_CONNECTED = False
        if status == 0:
            return request.Response.ReturnJSON(200, {"status" : "success"})
        else:
            return request.Response.ReturnJSON(200 ,{"status" : "fail"})

    @WebRoute(GET, '/messages')
    def get_messages(microWebSrv2, request):
        """
        Returns the LoRa messages
        """
        return request.Response.ReturnFile('/flash/database.json')

    @WebRoute(POST, '/messages')
    def send_message(microWebSrv2, request):
        """
        Send a message to the LoRa node
        """
        data = request.GetPostedJSONObject()
        content = request.Content
        print(content)

        try:
            address = data['address'].encode()
            message = ujson.dumps(data['message']).encode()
            broadcast = data['broadcast']
            ack_required = True

            if broadcast:
                address = ctpc.ANY_ADDR
                ack_required = False

            print("Sending message {} to {} -- broadcast {}".format(message, address, broadcast))
            #baton.acquire(1, 3)
            addr, quality, lora_result = ctpc.sendit(address, message, ack_required)
            #baton.release()
            result = "sucess"
            if lora_result == -1:
                result = "fail"
            request.Response.ReturnOkJSON({"status" : result})
            gc.collect()
        except Exception as ex:
            print(ex)
            return request.Response.ReturnJSON(500, {"status" : "You have to send a JSON with address, message and broadcast"})

    @WebRoute(DELETE, '/messages')
    def delete_messages(microWebSrv2, request):
        """
        Delete the messages
        """
        database.delete_messages()
        return request.Response.ReturnOkJSON({"status" : "success"})

    def send_lora_hello(self, delay, id):
        """
        Thread method to send a hello message to the LoRa network
        """
        while True:
            LORA_CONNECTED = True
            baton.acquire()
            myaddr, rcvraddr, quality, status = self.ctpc.hello()
            baton.release()
            LORA_CONNECTED = False
            sleep(delay)

    def change_led_status(self):
        """
        Thread method to change the LED status
        """
        while True:
            connected_clients = wifi.has_connected_clients()
            if not LORA_CONNECTED and not connected_clients:
                pycom.rgbled(0x7f0000) #red
            if not LORA_CONNECTED and connected_clients:
                pycom.rgbled(0x0000FF) #blue
            if LORA_CONNECTED:
                pycom.rgbled(0x007f00) #green
            sleep(1)

    def receive_lora_data(self):
        """
        Thread method to receive the LoRa node messages
        """
        while True:
            try:
                # baton.acquire()
                LORA_CONNECTED = True
                rcvd_data, snd_addr = self.ctpc.recvit()
                print("Received from {}: {}".format(snd_addr, rcvd_data))
                # Save sender and message in file
                database.save_message(snd_addr, rcvd_data)

                LORA_CONNECTED = False
                # baton.release()
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

# Waits for WiFi complete
print ("Waiting for WiFi to be available...")
sleep(5)

# Initialize the database
database = database.FileHandler()

# Create Node
node = Node(ctpc, wifi, database, node_name)

# Send hello to others LoRa nodes in a thread every 60 seconds
_thread.start_new_thread(node.send_lora_hello, (60, 1))

# Change LED status every second
_thread.start_new_thread(node.change_led_status, ())

# Thread for receive LoRa data
_thread.start_new_thread(node.receive_lora_data, ())

# Enable Webserver
# Instanciates the MicroWebSrv2 class
mws2 = MicroWebSrv2()

# For embedded MicroPython, use a very light configuration
mws2.SetEmbeddedConfig()

# Set server parameters
mws2.MaxRequestContentLength = 2*1024*1024
mws2.RequestsTimeoutSec = 10
mws2.StartManaged()

try :
    while mws2.IsRunning:
        sleep(0.5)
except KeyboardInterrupt:
    mws2.Stop()
    print("Stop node")
