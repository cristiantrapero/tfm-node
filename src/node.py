from network import Bluetooth
import loractp
import pycom
import gc
import time
import ujson
import ucrypto
import math
import _thread

NODE_NAME = ''
DISCOVERED_NODES = {}
SENDING_DATA = False
BLE_CONNECTED = False
LORA_CONNECTED = False

ctpc = loractp.CTPendpoint(debug_send=False, debug_recv=False)

# This is for semap
baton = _thread.allocate_lock()

# Enable garbage collector
gc.enable()

def ble_connection_handler(bt_o):
    global BLE_CONNECTED
    events = bt_o.events()
    if events & Bluetooth.CLIENT_CONNECTED:
        print("BLE connected!")
        BLE_CONNECTED = True

    elif events & Bluetooth.CLIENT_DISCONNECTED:
        print("BLE disconnected!")
        BLE_CONNECTED = False

def ble_name_callback(chr, data):
    global NODE_NAME
    events, value = data
    if  events & Bluetooth.CHAR_WRITE_EVENT:
        print("BLE WRITE node name")
        try:
            NODE_NAME = value.decode('utf-8')
            print(NODE_NAME)
        except Excection as ex:
            print(ex)
    else:
        print("BLE READ node name: {}".format(NODE_NAME))
        return NODE_NAME

def ble_lora_nodes_discovered_callback(chr, data=None):
    events = chr.events()
    if events & Bluetooth.CHAR_READ_EVENT:
        nodes = get_discovered_nodes()
        print("BLE READ lora nodes {}".format(nodes))
        return nodes

def ble_send_data_over_lora_callback(chr, data):
    global SENDING_DATA
    global LORA_CONNECTED
    events, value = data
    if events & Bluetooth.CHAR_WRITE_EVENT:
        SENDING_DATA = True
        LORA_CONNECTED = True
        try:
            node_to_connect = value
            value = random_in_range()
            message = ujson.dumps({'value': value, 'node': NODE_NAME}).encode()
            print('Send value {} to node {}'.format(value, node_to_connect))
            # baton.acquire()
            addr, quality, result = ctpc.sendit(node_to_connect, message)
            # baton.release()
            print('Result after send: {}, {}, {}'.format(addr, quality, result))

        except Exception as ex:
            print("Exception: {}".format(ex))
            LORA_CONNECTED = False
        SENDING_DATA = False
        LORA_CONNECTED = False
    else:
        print("BLE READ connect to lora node")

def get_discovered_nodes():
    global DISCOVERED_NODES
    return ujson.dumps(DISCOVERED_NODES)

def random_in_range(l=0,h=1000):
    r1 = ucrypto.getrandbits(32)
    r2 = ((r1[0]<<24)+(r1[1]<<16)+(r1[2]<<8)+r1[3])/4294967295.0
    return math.floor(r2*h+l)

def setup_ble(node_name):
    bluetooth = Bluetooth()
    bluetooth.set_advertisement(name=node_name, service_uuid=b'3d93cce6b7311212')
    bluetooth.callback(trigger=Bluetooth.CLIENT_CONNECTED | Bluetooth.CLIENT_DISCONNECTED, handler=ble_connection_handler)
    bluetooth.advertise(True)

    # Service 1: Obtain node data
    # nbr_chars indicate the number of characteristics to include
    service1 = bluetooth.service(uuid=b'21f89e3146781221', isprimary=True, nbr_chars=2)
    # Characteristic 1: Node name
    char1 = service1.characteristic(uuid=b'fc9dbf8be8903223', value=NODE_NAME)
    char1_callback = char1.callback(trigger=Bluetooth.CHAR_READ_EVENT, handler=ble_name_callback)
    # Characteristic 2: Get discovered lora nodes
    char2 = service1.characteristic(uuid=b'608b5e89c2ba4334')
    char2_callback = char2.callback(trigger=Bluetooth.CHAR_READ_EVENT | Bluetooth.CHAR_WRITE_EVENT, handler=ble_lora_nodes_discovered_callback)

    # Service 2: Manage lora conections
    service2 = bluetooth.service(uuid=b'c2bf80e7ba545445', isprimary=True, nbr_chars=1)
    char3 = service2.characteristic(uuid=b'bb73a3bb46c35665')
    char3_callback = char3.callback(trigger=Bluetooth.CHAR_WRITE_EVENT, handler=ble_send_data_over_lora_callback)

def send_hello(ctpc, delay, id):
    global SENDING_DATA
    while True:
        time.sleep(delay)
        if not SENDING_DATA:
            myaddr, rcvraddr, quality, status = ctpc.hello()

def change_led_status():
    while True:
        if not LORA_CONNECTED and not BLE_CONNECTED:
            pycom.rgbled(0x7f0000) #red
        if not LORA_CONNECTED and BLE_CONNECTED:
            pycom.rgbled(0x0000FF) #blue
        if LORA_CONNECTED and not BLE_CONNECTED:
            pycom.rgbled(0xFFFF00) #yellow
        if LORA_CONNECTED and BLE_CONNECTED:
            pycom.rgbled(0x007f00) #green
            # for cycle in range(5):
            #     pycom.rgbled(0x007f00) #green
            #     time.sleep(0.1)
            #     pycom.rgbled(0x000000) #off
        time.sleep(1)

def receive_data():
    global LORA_CONNECTED
    while True:
        try:
            baton.acquire()
            rcvd_data, snd_addr = ctpc.recvit()
            baton.release()
            print("Received from {}: {}".format(snd_addr.decode('utf-8'), rcvd_data))
            DISCOVERED_NODES = ctpc.get_discovered_nodes()
            print("Discovered nodes: ", DISCOVERED_NODES)
        except Exception as ex:
            print("Exception: {}".format(ex))

def main():
    global NODE_NAME
    global DISCOVERED_NODES

    my_lora_mac = ctpc.get_lora_mac()
    my_addr = ctpc.get_my_addr()
    NODE_NAME = "NODE-{}".format(my_addr)

    setup_ble(NODE_NAME)

    print("Setup BLE done!")
    print("I'm the node: {}".format(NODE_NAME))
    print("My lora UID is: {}".format(my_lora_mac))
    print("My addr: {}".format(my_addr))

    gc.enable()

    # Send hello to others nodes in a thread every 60 seconds
    _thread.start_new_thread(send_hello, (ctpc, 60, 1))

    # Change LED status every second
    _thread.start_new_thread(change_led_status, ())

    # Thread for receive the data
    _thread.start_new_thread(receive_data, ())

    while True:
        time.sleep(1)
        gc.collect()

if __name__ == "__main__":
    main()
