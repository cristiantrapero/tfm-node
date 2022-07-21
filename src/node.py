from network import Bluetooth
import loractp
import pycom
import gc
import time
import ujson
import _thread

NODE_NAME = ''
DISCOVERED_NODES = {}

ctpc = loractp.CTPendpoint()

def ble_connection_handler(bt_o):
    events = bt_o.events()
    if events & Bluetooth.CLIENT_CONNECTED:
        print("BLE connected!")

    elif events & Bluetooth.CLIENT_DISCONNECTED:
        print("BLE disconnected!")

def ble_name_callback(chr, arg1=None):
    global NODE_NAME
    events = chr.events()
    if  events & Bluetooth.CHAR_WRITE_EVENT:
        print("BLE WRITE node name")
        print(chr.value().decode('utf-8'))
        NODE_NAME = chr.value().decode('utf-8')
    else:
        print("BLE READ node name: {}".format(NODE_NAME))
        return NODE_NAME

def ble_lora_nodes_discovered_callback(chr, arg1=None):
    events = chr.events()
    if events & Bluetooth.CHAR_READ_EVENT:
        nodes = get_discovered_nodes()
        print("BLE READ lora nodes {}".format(nodes))
        return nodes

def ble_connect_to_lora_node(chr, arg1=None):
    events = chr.events()
    if events & Bluetooth.CHAR_WRITE_EVENT:
        print("BLE WRITE connect to lora node")
        node_to_connect = chr.value().decode('utf-8')
        print(node_to_connect)
        ctpc.connect(node_to_connect)
    else:
        print("BLE READ connect to lora node")

def get_discovered_nodes():
    global DISCOVERED_NODES
    return ujson.dumps(DISCOVERED_NODES)

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
    char2_callback = char2.callback(trigger=Bluetooth.CHAR_READ_EVENT, handler=ble_lora_nodes_discovered_callback)

    # Service 2: Manage lora conections
    service2 = bluetooth.service(uuid=b'c2bf80e7ba545445', isprimary=True, nbr_chars=1)
    char3 = service2.characteristic(uuid=b'bb73a3bb46c35665')
    char3_callback = char3.callback(trigger=Bluetooth.CHAR_READ_EVENT, handler=ble_connect_to_lora_node)

def send_hello(ctpc, delay, id):
    while True:
        time.sleep(delay)
        myaddr, rcvraddr, quality, status = ctpc.hello()

def main():
    global NODE_NAME
    global DISCOVERED_NODES

    my_lora_mac = ctpc.get_lora_mac()
    my_addr = ctpc.get_my_addr()
    my_node_name = "NODE-{}".format(my_addr)
    NODE_NAME = my_node_name

    setup_ble(my_node_name)

    print("Setup BLE done!")
    print("I'm the node: {}".format(my_node_name))
    print("My lora UID is: {}".format(my_lora_mac))
    print("My addr: {}".format(my_addr))

    gc.enable()

    # Send hello to others nodes in a thread every 10
    _thread.start_new_thread(send_hello, (ctpc, 10, 1))

    # Wait for lora nodes response
    while True:
        # print("Scanning for lora nodes...")
        rcvd_data, snd_addr = ctpc.recvit()
        print("Received from {}: {}".format(snd_addr.decode('utf-8'), rcvd_data))
        # print("Sender: LoRa connection from {} to me ({}) {} ".format(rcvraddr, myaddr, status))
        DISCOVERED_NODES = ctpc.get_discovered_nodes()
        time.sleep(5)
        # print("Scanning done!")


if __name__ == "__main__":
    main()
