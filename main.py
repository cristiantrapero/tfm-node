from network import WLAN
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
import posthandler # PM: code to be executed to handle a POST


DISCOVERED_NODES = {}
SENDING_DATA = False
BLE_CONNECTED = False
LORA_CONNECTED = False

HOST = '192.168.4.1'
PORT = 80
WEB_PAGES_HOME_DIR = 'www' # Directory where webpage files are stored

ctpc = loractp.CTPendpoint(debug_send=False, debug_recv=False)

# This is for semaphore
baton = _thread.allocate_lock()

# Enable garbage collector
gc.enable()

class Server:

    def __init__(self, node_name):
        """ HTTP server constructor """
        self.host = HOST
        self.port = PORT
        self.www_dir =  WEB_PAGES_HOME_DIR
        self.node_name = node_name

        # Config WiFi with static IP
        wlan = WLAN()
        wlan.init(mode=WLAN.AP, ssid=node_name, auth=None, channel=10, antenna=WLAN.INT_ANT)
        wlan.ifconfig(config=(self.host, '255.255.255.0', '192.168.4.1', '8.8.8.8'))

        print("WiFi name: {}".format(node_name))
        print("WiFi AP IP: {}".format(self.host))
        print("Setup WiFi done!")

    def start(self):
        """ Attempts to aquire the socket and launch the server """
        self.socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)

        try:
            print("Launching HTTP server on: {}:{}".format(self.host, self.port))
            self.socket.bind((self.host, self.port))
            print("Server successfully acquired the socket: {}:{}".format(self.host, self.port))
            self._wait_for_connections()

        except Exception as e:
            print("Error: Could not acquire socket: {}:{}\n".format(self.host, self.port))
            print(e)
            self.shutdown()
            sys.exit(1)

    def shutdown(self):
        """ Shut down the server """
        try:
            print("Shutting down the server")
            s.socket.shutdown(socket.SHUT_RDWR)

        except Exception as e:
            print("Error: Could not shut down the socket")
            print(e)

    def _gen_headers(self,  code):
        """ Generates HTTP response Headers. """

        # determine response code
        h = ''

        if (code == 200):
            h = 'HTTP/1.1 200 OK\n'
        elif(code == 404):
            h = 'HTTP/1.1 404 Not Found\n'

        # write further headers
        # current_date = time.strftime("%a, %d %b %Y %H:%M:%S", time.localtime())
        # PM: should find an alternative for LoPys
        current_date = '2 Septiembre 2022'
        h += 'Date: ' + current_date +'\n'
        h += 'Server: Simple-Python-HTTP-Server\n'
        h += 'Connection: close\n\n'  # signal that the conection will be closed after completing the request

        return h

    def _wait_for_connections(self):
        """ Main loop awaiting connections """
        while True:
            print("Awaiting new connection")
            self.socket.listen(3) # maximum number of queued connections

            conn, addr = self.socket.accept()
            # conn - socket to client
            # addr - clients address

            print("Got connection from client:", addr)

            data = conn.recv(4092) #receive data from client
            treq = bytes.decode(data) #decode it to treq

            #determine request method  (HEAD and GET are supported) (PM: added support to POST )
            request_method = treq.split(' ')[0]
            print("Method: ", request_method)
            print("Full HTTP message: -->")
            print(treq)
            print("<--")

            treqhead = treq.split("\r\n\r\n")[0]
            treqbody = treq[len(treqhead):].lstrip() # PM: makes easier to handle various types of newlines
            print("only the HTTP body: -->")
            print(treqbody)
            print("<--")

            # split on space "GET /file.html" -into-> ('GET','file.html',...)
            file_requested = treq.split(' ')
            file_requested = file_requested[1] # get 2nd element

            #Check for URL arguments. Disregard them
            file_requested = file_requested.split('?')[0]  # disregard anything after '?'

            if (file_requested == '/'):  # in case no file is specified by the browser
                file_requested = '/index.html' # load index.html by default
            elif (file_requested == '/favicon.ico'):  # most browsers ask for this file...
                file_requested = '/index.html' # ...giving them index.html instead

            file_requested = self.www_dir + file_requested
            print("Serving web page [",file_requested,"]")

            # GET method
            if (request_method == 'GET') | (request_method == 'HEAD'):

                ## Load file content
                try:
                    file_handler = open(file_requested,'rb')
                    if (request_method == 'GET'):  #only read the file when GET
                        response_content = file_handler.read() # read file content
                    file_handler.close()

                    response_headers = self._gen_headers(200)

                except Exception as e: #in case file was not found, generate 404 page
                    print ("Warning, file not found. Serving response code 404\n", e)
                    response_headers = self._gen_headers(404)

                    if (request_method == 'GET'):
                        response_content = b"<html><body><p>Error 404: File not found</p></body></html>"

                server_response =  response_headers.encode() # return headers for GET and HEAD
                if (request_method == 'GET'):
                    server_response +=  response_content  # return additional conten for GET only

                conn.send(server_response)
                print("Closing connection with client")
                conn.close()

            # POST method
            elif (request_method == 'POST'):

                ## Load file content
                try:
                    if (file_requested.find("execposthandler") != -1):
                        print("... PM: running python code")
                        if (len(treqbody) > 0 ):
                            print((treqbody))
                            response_content = posthandler.run(treqbody)
                        else:
                            print("... PM: empty POST received")
                            response_content = b"<html><body><p>Error: EMPTY FORM RECEIVED</p><p>Python HTTP server</p></body></html>"
                    else:
                        file_handler = open(file_requested,'rb')
                        response_content = file_handler.read() # read file content
                        file_handler.close()

                    response_headers = self._gen_headers( 200)

                except Exception as e: #in case file was not found, generate 404 page
                    print ("Warning, file not found. Serving response code 404\n", e)
                    response_headers = self._gen_headers( 404)
                    response_content = b"<html><body><p>Error 404: File not found</p><p>Python HTTP server</p></body></html>"


                server_response =  response_headers.encode() # return headers
                server_response +=  response_content  # return additional content

                conn.send(server_response)
                print("Closing connection with client")
                conn.close()

            else:
                print("Unknown HTTP request method:", request_method)

def get_discovered_nodes():
    global DISCOVERED_NODES
    DISCOVERED_NODES = ctpc.get_discovered_nodes()
    return ujson.dumps(DISCOVERED_NODES)

def send_lora_hello(ctpc, delay, id):
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
        time.sleep(1)

def receive_lora_data():
    while True:
        try:
            baton.acquire()
            rcvd_data, snd_addr = ctpc.recvit()
            baton.release()
            print("Received from {}: {}".format(snd_addr.decode('utf-8'), rcvd_data))
            print("Discovered nodes: ", get_discovered_nodes())
        except Exception as ex:
            print("Exception: {}".format(ex))

def random_in_range(l=0,h=1000):
    r1 = ucrypto.getrandbits(32)
    r2 = ((r1[0]<<24)+(r1[1]<<16)+(r1[2]<<8)+r1[3])/4294967295.0
    return math.floor(r2*h+l)

def main():
    # Setup node data and http server
    my_lora_mac = ctpc.get_lora_mac()
    my_addr = ctpc.get_my_addr()
    node_name = "NODE-{}".format(my_addr)

    print("I'm the node: {}".format(node_name))
    print("My LoRa UID is: {}".format(my_lora_mac))
    print("My address: {}".format(my_addr))

    # Send hello to others lora nodes in a thread every 60 seconds
    _thread.start_new_thread(send_lora_hello, (ctpc, 60, 1))

    # Change LED status every second
    _thread.start_new_thread(change_led_status, ())

    # Thread for receive LoRa data
    _thread.start_new_thread(receive_lora_data, ())

    # Setup the web server
    server = Server(node_name)
    server.start()
    gc.enable()

    while True:
        time.sleep(1)
        gc.collect()

if __name__ == "__main__":
    main()
