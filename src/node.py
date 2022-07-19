from network import Bluetooth
import loractp
import pycom
import gc
import time
import ujson
import _thread

LORA_NODES_DISCOVERED = 0
NODE_NAME = ''

def ble_connection_handler(bt_o):
    events = bt_o.events()
    if events & Bluetooth.CLIENT_CONNECTED:
        print("BLE connected")

    elif events & Bluetooth.CLIENT_DISCONNECTED:
        print("BLE disconnected")

def ble_name_callback(chr, arg1=None):
    global NODE_NAME

    events = chr.events()
    if  events & Bluetooth.CHAR_WRITE_EVENT:
        print("BLE node name write event: {}".format(chr.value().decode('utf-8')))
        NODE_NAME = chr.value().decode('utf-8')
    else:
        print("BLE node name read event")
        return NODE_NAME

def ble_lora_nodes_callback(chr, arg1=None):
    global LORA_NODES_DISCOVERED

    events = chr.events()
    if  events & Bluetooth.CHAR_READ_EVENT:
        print("BLE lora nodes read event")
        return LORA_NODES_DISCOVERED

def setup_ble(node_name):
    bluetooth = Bluetooth()
    bluetooth.set_advertisement(name=node_name, service_uuid=b'36c4919279684969')
    bluetooth.callback(trigger=Bluetooth.CLIENT_CONNECTED | Bluetooth.CLIENT_DISCONNECTED, handler=ble_connection_handler)
    bluetooth.advertise(True)

    service1 = bluetooth.service(uuid=b'ce397c4d744e41ab', isprimary=True)
    char1 = service1.characteristic(uuid=b'0242ac120002a8a3', value=NODE_NAME)
    char1_callback = char1.callback(trigger=Bluetooth.CHAR_READ_EVENT, handler=ble_name_callback)

    service1 = bluetooth.service(uuid=b'ce397c4d744e41ac', isprimary=True)
    char1 = service1.characteristic(uuid=b'0242ac120002a8ad', value=LORA_NODES_DISCOVERED)
    char1_callback = char1.callback(trigger=Bluetooth.CHAR_READ_EVENT, handler=ble_lora_nodes_callback)

def send_hello(ctpc, delay, id):
    while True:
        time.sleep(delay)
        myaddr, rcvraddr, quality, status = ctpc.hello()

def main():
    global NODE_NAME
    ctpc = loractp.CTPendpoint()

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
        print("Received from: {} {}".format(rcvd_data, snd_addr))
        # print("Sender: LoRa connection from {} to me ({}) {} ".format(rcvraddr, myaddr, status))
        time.sleep(5)
        # print("Scanning done!")


if __name__ == "__main__":
    main()
