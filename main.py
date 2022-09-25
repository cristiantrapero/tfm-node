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
    def __init__(self, ctp, wifi, database, node_name):
        """
        Initialize the Node class with the LoRa CTP object, the WiFi object and the node name
        """
        self.ctp = ctp
        self.wifi = wifi
        self.database = database
        self.node_name = node_name

    @WebRoute(GET, '/info')
    def get_node_info(microWebSrv2, request):
        """
        Returns the LoRa node info
        """
        lora_nodes = ctp.get_discovered_nodes_list()
        return request.Response.ReturnOkJSON({
            'wifi_name'     : wifi.get_name(),
            'wifi_ip'       : wifi.get_ip(),
            'lora_uid'      : ctp.get_lora_mac(),
            'address'       : ctp.get_my_addr(),
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
        lora_nodes = ctp.get_discovered_nodes_list()
        return request.Response.ReturnOkJSON({
                "availables"    :   len(lora_nodes),
                "addresses"     :   lora_nodes
            })

    @WebRoute(POST, '/hello')
    def send_hello(microWebSrv2, request):
        """
        Send hello message to the LoRa network
        """
        global LORA_CONNECTED

        LORA_CONNECTED = True
        nodes = ujson.dumps(ctp.get_discovered_nodes()).encode()
        sender, receiver, stats, quality, status = ctp.hello(nodes)
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
        global LORA_CONNECTED

        LORA_CONNECTED = True

        data = request.GetPostedJSONObject()
        try:
            address = data['address'].encode()
            broadcast = data['broadcast']
            ack_required = True

            if broadcast:
                address = ctp.ANY_ADDR
                ack_required = False

            print("Sending message {} to {} -- broadcast {}".format(message, address, broadcast))
            #baton.acquire(1, 3)
            receiver, stats, retransmissions, lora_result, time_to_send = ctp.sendit(address, message, ack_required)
            #baton.release()
            result = "success"
            if lora_result == -1:
                result = "fail"
            LORA_CONNECTED = False

            return request.Response.ReturnJSON(200, {
                "receiver": receiver.decode(),
                "packets" : stats,
                "retransmissions" : retransmissions,
                "status" : result,
                "time_to_send" : time_to_send})
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
        global LORA_CONNECTED

        while True:
            LORA_CONNECTED = True
            baton.acquire()
            sender, stats, receiver, retrans, status = self.ctp.hello()
            baton.release()
            LORA_CONNECTED = False
            sleep(delay)

    def change_led_status(self):
        """
        Thread method to change the LED status
        """
        while True:
            connected_clients = wifi.has_connected_clients()
            if LORA_CONNECTED:
                pycom.rgbled(0x007f00) #green
            elif not LORA_CONNECTED and connected_clients:
                pycom.rgbled(0x0000FF) #blue
            else:
                pycom.rgbled(0x7f0000) #red

            sleep(0.2)

    def receive_lora_data(self):
        """
        Thread method to receive the LoRa node messages
        """
        global LORA_CONNECTED

        while True:
            print("Waiting for data")
            try:
                # baton.acquire()
                LORA_CONNECTED = True
                rcvd_data, snd_addr, time_to_recv = self.ctp.recvit()
                print("Received from {}: {} after {:.2f} seconds".format(snd_addr, rcvd_data, time_to_recv))
                # Save sender and message in file
                database.save_message(snd_addr, rcvd_data)

                LORA_CONNECTED = False
                # baton.release()
            except Exception as ex:
                print("Exception: {}".format(ex))

# Create LoRa CTP endpoint
ctp = loractp.CTPendpoint(debug_send=True, debug_recv=True)
node_name = "NODE-{}".format(ctp.get_my_addr())

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
node = Node(ctp, wifi, database, node_name)

# Send hello to others LoRa nodes in a thread every 60 seconds
_thread.start_new_thread(node.send_lora_hello, (10, 1))

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
mws2.BufferSlotSize = 8*1024
mws2.MaxRequestContentLength = 8*1024*1024
mws2.CORSAllowAll = True
mws2.AllowAllOrigins = True
mws2.StartManaged()

try :
    while mws2.IsRunning:
        sleep(0.100)
except KeyboardInterrupt:
    mws2.Stop()
    print("Stop node")
