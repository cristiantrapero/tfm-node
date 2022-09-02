from network import LoRa
import socket
import machine
import time
import binascii
import network

def run(post_body):


    # initialize LoRa in LORA mode
    lora = LoRa(mode=LoRa.LORA)
    loramac = binascii.hexlify(network.LoRa().mac())
#    loramac = "LORAMAC"
    
    # PM: extracting data to be sent from passed POST body 
    blks = post_body.split("&")
    tbs = str(loramac)
    for i in blks:
        v = i.split("=")
        tbs += ","+v[1]

    # PM: sending data on a raw LoRa socket 
    s = socket.socket(socket.AF_LORA, socket.SOCK_RAW)
    s.setblocking(True)
    print('Sending... '+tbs)
    s.send(tbs)
    s.setblocking(False)

    # PM: creating web page to be returned
    r_content = "<h1>Message sent via LoRa</h1>\n"
    r_content += "\n"
    r_content += tbs + "\n"
    r_content += "\n"
    r_content += "<p><a href='/'>Back to home</a></p>\n"

    return r_content
