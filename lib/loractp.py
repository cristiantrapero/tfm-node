"""
LoRa CTP (Content Transfer Protocol)
based on stop & wait like protocol and adapted to a LoRa raw channel

Tested on a LoPy4 quadruple bearer MicroPython enabled development board.

Inspired by https://github.com/arturenault/reliable-transport-protocol by Artur Upton Renault

First version by: Pietro GRC dic2017
Modified by: Pietro GRC apr2020
Modified by: Cristian Trapero sep2022
"""

from network import LoRa
from machine import RTC
import binascii
import gc
import hashlib
import machine
import socket
import struct
import sys
import time
import network
import ujson
import _thread

__version__ = '0'


class CTPendpoint:

    MAX_PKT_SIZE = 230  # Maximum pkt size in LoRa with Spread Factor 7
    HEADER_SIZE  = 20
    PAYLOAD_SIZE = MAX_PKT_SIZE - HEADER_SIZE
    # header structure:
    # 8 bytes: source addr (last 8 bytes)
    # 8 bytes: dest addr (last 8 bytes)
    # 1 byte: flags
    # 3 bytes: checksum
    HEADER_FORMAT  = "!8s8sB3s"
    PAYLOAD_FORMAT = "!202s"

    ITS_DATA_PACKET = False
    ITS_ACK_PACKET  = True
    ANY_ADDR = b'\x00\x00\x00\x00\x00\x00\x00\x00'
    ONE  = 1
    ZERO = 0

    # List of discovered nodes
    DISCOVERED_NODES = {}

    def __init__(self, debug_send=False, debug_recv=False, debug_hard=False):

        # Configure LoRa
        self.lora = LoRa(mode = LoRa.LORA,
                         coding_rate  = LoRa.CODING_4_5,
                         tx_power = 14,
                         sf = 7,
                         bandwidth = LoRa.BW_250KHZ,
                         power_mode = LoRa.ALWAYS_ON)

        # Get lora mac address (device EUI)
        self.lora_mac = binascii.hexlify(network.LoRa().mac()).upper()
        self.my_addr  = self.lora_mac[8:].upper()

        # Create a raw LoRa socket
        self.send = socket.socket(socket.AF_LORA, socket.SOCK_RAW)
        self.recv = socket.socket(socket.AF_LORA, socket.SOCK_RAW)
        self.rtc = RTC()
        self.rtc.init((2022, 9, 25, 00, 00, 0, 0, 0))

        # Set to True for debugging messages
        self.debug_mode_send = debug_send
        self.debug_mode_recv = debug_recv
        self.hard_debug_mode = debug_hard

    #
    # BEGIN: Utility functions
    #

    # Create a packet from the necessary parameters
    def __make_packet(self, s_addr, d_addr, hello, seqnum, ack_required, acknum, pkt_type, is_last, content):
        # s_addr: bytes, d_addr: bytes, hello: boolean, seqnum: int, ack_required: boolean, acknum: int, pkt_type: boolean, is_last: boolean, content: bytes
        if self.hard_debug_mode: print("DEBUG 080:", s_addr, d_addr, hello, seqnum, ack_required, acknum, pkt_type, is_last, content)
        flags = 0
        if seqnum == self.ONE:
            flags = flags | (1<<0)
        if acknum == self.ONE:
            flags = flags | (1<<2)
        if is_last:
            flags = flags | (1<<4)
        if hello:
            flags = flags | (1<<5)
        if pkt_type == self.ITS_ACK_PACKET:
            flags = flags | (1<<6)
        if ack_required:
            flags = flags | (1<<7)

        if self.debug_mode_send: print ("DEBUG 081: Flags: ", flags)

        if (len(content)>0 and (pkt_type == self.ITS_DATA_PACKET)):
            # p = struct.pack(self.PAYLOAD_FORMAT, content)
            p = content
            check = self.__get_checksum(p)
            h = struct.pack(self.HEADER_FORMAT, s_addr, d_addr, flags, check)
            if self.hard_debug_mode: print("DEBUG 096:", h+p)
        else:
            p = b''
            h = struct.pack(self.HEADER_FORMAT, s_addr, d_addr, flags, b'')
            if self.hard_debug_mode: print("DEBUG 100:", h+p)

        return h + p

    # Break a packet into its component parts
    def __unpack(self, packet):
        header  = packet[:self.HEADER_SIZE]
        content = packet[self.HEADER_SIZE:]

        sp, dp, flags, check = struct.unpack(self.HEADER_FORMAT, header)
        seqnum   = self.ONE if ((flags) & 1) & 1 else self.ZERO
        acknum   = self.ONE if (flags >> 2)  & 1 else self.ZERO
        is_last  = (flags >> 4) & 1 == 1
        hello   = (flags >> 5) & 1 == 1
        pkt_type = (flags >> 6) & 1 == 1
        ack_required = (flags >> 7) & 1 == 1

        if (content == b''):
            payload = b''
        else:
            payload = content

        return sp, dp, hello, seqnum, ack_required, acknum, pkt_type, is_last, check, payload

    def __get_checksum(self, data):
        # data: byte -> byte:
        if self.hard_debug_mode: print("DEBUG 123: in get_checksum->", data)
        h = hashlib.sha256(data)
        ha = binascii.hexlify(h.digest())
        if self.hard_debug_mode: print("DEBUG 126: in get_checksum->", ha[-3:])
        return (ha[-3:])

    def __debug_printpacket(self, msg, packet, cont=False):
        sp, dp, hello, seqnum, ack_required, acknum, pkt_type, is_last, check, content = self.__unpack(packet)
        if cont:
            print ("DEBUG {}: s_a: {}, d_a: {}, hello {}, seqn: {}, ack_required: {}, ackn: {}, is-ack: {}, fin: {}, check: {}, cont: {}".format(msg, sp, dp, hello, seqnum, ack_required, acknum, pkt_type, is_last, check, content))
        else:
            print ("DEBUG {}: s_a: {}, d_a: {}, hello {}, seqn: {}, ack_required: {}, ackn: {}, is_ack: {}, fin: {}, check: {}".format(msg, sp, dp, hello, seqnum, ack_required, acknum, pkt_type, is_last, check))

    def __timeout(self, signum, frame):
        raise socket.timeout

    #
    # END: Utility functions
    #

    # Register node in discovered list of nodes
    def __register_node(self, node_name, discovered_node_list):
        # Convert to string
        node_name = node_name.decode('utf-8')
        content = discovered_node_list.decode('utf-8')
        discovered_node_list = []

        if content != 'None':
            discovered_node_list = list(ujson.loads(content).keys())

        if self.debug_mode_recv: print ("DEBUG RECV 293: HELLO received. Registering node: {} {}".format(node_name, discovered_node_list))
        self.DISCOVERED_NODES[node_name] = discovered_node_list

        if self.debug_mode_recv: print ("DEBUG RECV 296: DISCOVERED_NODES: {}".format(self.DISCOVERED_NODES))

    def _csend(self, payload, the_sock, sndr_addr, rcvr_addr, ack_required=True, hello=False):

        global_time_t0 = time.time()
        # Shortening addresses to last 8 bytes to save space in packet
        sndr_addr = sndr_addr[8:]
        rcvr_addr = rcvr_addr[:8]
        if self.debug_mode_send: print ("DEBUG SEND 148: sndr_addr, rcvr_addr", sndr_addr, rcvr_addr)

        # computing payload (content) size as "totptbs" = total packets to be sent
        if (len(payload)==0): print ("WARNING csend: payload size == 0... continuing")
        totptbs = int(len(payload) / self.PAYLOAD_SIZE)
        if ((len(payload) % self.PAYLOAD_SIZE)!=0): totptbs += 1

        if self.debug_mode_send: print ("DEBUG SEND 155: Total packages to be send: ", totptbs)  ###
        timeout_value = 5

        # Initialize stats counters
        FAILED         = 0
        stats_psent    = 0
        stats_retrans  = 0

        # RTT estimators
        timeout_time   =  1    # 1 second
        estimated_rtt  = -1
        dev_rtt        =  1
        the_sock.settimeout(5)      # 5 seconds initial timeout... LoRa is slow

        # stop and wait
        seqnum = self.ZERO
        acknum = self.ONE

        # Enabling garbage collection
        gc.enable()
        gc.collect()
        for cp in range(totptbs):

            if self.debug_mode_send: print ("DEBUG SEND 178: Packet counter: ", cp)  ###
            last_pkt = True if (cp == (totptbs-1)) else False

            # Getting a block of max self.PAYLOAD_SIZE from "payload"
            blocktbs = payload[0:self.PAYLOAD_SIZE]  # Taking self.PAYLOAD_SIZE bytes ToBeSent
            payload  = payload[self.PAYLOAD_SIZE:]   # Shifting the input string

            packet = self.__make_packet(sndr_addr, rcvr_addr, hello, seqnum, ack_required, acknum, self.ITS_DATA_PACKET, last_pkt, blocktbs)
            if self.debug_mode_send: self.__debug_printpacket("DEBUG SEND 186: sending packet", packet)

            # trying 3 times
            keep_trying = 3
            while (keep_trying > 0):

                try:
                    time.sleep((3-keep_trying)) ###
                    the_sock.setblocking(True)
                    send_time = time.time()
                    the_sock.send(packet)

                    if ack_required:
                        # waiting for the ack
                        the_sock.settimeout(timeout_value)  ###
                        if self.debug_mode_send: print("DEBUG SEND 200: waiting ACK")
                        ack = the_sock.recv(self.HEADER_SIZE)
                        recv_time = time.time()
                        if self.debug_mode_send: print("DEBUG SEND 203: received ack", ack)

                        # self.__unpack packet information
                        try:
                            ack_saddr, ack_daddr, hello, ack_seqnum, ack_required, ack_acknum, ack_is_ack, ack_final, ack_check, ack_content = self.__unpack(ack)
                        except Exception as e:
                            print("ERROR ACKKKKKKKK 208:", e)
                            
                        if (rcvr_addr == self.ANY_ADDR) or (rcvr_addr == b''):
                            rcvr_addr = ack_saddr       # in case rcvr_addr was self.ANY_ADDR and payload needs many packets

                        # Check if valid...
                        if (ack_is_ack) and (ack_acknum == seqnum) and (sndr_addr == ack_daddr) and (rcvr_addr == ack_saddr):
                            stats_psent   += 1
                            # No more need to retry
                            break
                        else:
                            # Received packet not valid
                            if self.debug_mode_send: print ("ERROR SEND: ACK received not valid")
                    else:
                        # No need to wait for ACK
                        break
                except socket.timeout:
                    if self.debug_mode_send: print("EXCEPTION!! Socket timeout: ", time.time())

                if self.debug_mode_send: self.__debug_printpacket("re-sending packet", packet)
                if self.debug_mode_send: print ("DEBUG SEND 222: attempt number: ", keep_trying)
                stats_psent   += 1
                stats_retrans += 1
                keep_trying   -= 1
                if(keep_trying == 0):
                    FAILED = -1
                    break

            # Check if last packet or failed to send a packet...
            if last_pkt or (FAILED<0): break

            # RTT calculations
            sample_rtt = recv_time - send_time
            if estimated_rtt == -1:
                estimated_rtt = sample_rtt
            else:
                estimated_rtt = estimated_rtt * 0.875 + sample_rtt * 0.125
            dev_rtt = 0.75 * dev_rtt + 0.25 * abs(sample_rtt - estimated_rtt)
            timeout_value = (estimated_rtt + 4 * dev_rtt)
            if self.debug_mode_send: print ("DEBUG SEND 241: setting timeout to", estimated_rtt + 4 * dev_rtt)

            # Increment sequence and ack numbers
            seqnum = (seqnum + self.ONE) % 2    # self.ONE if seqnum == self.ZERO else self.ZERO
            acknum = (acknum + self.ONE) % 2    # self.ONE if acknum == self.ZERO else self.ZERO

        if self.debug_mode_send: print ("DEBUG SEND 247: RETURNING tsend")
        if self.debug_mode_send: print ("DEBUG SEND 248: Retrans: ", stats_retrans)

        # KN: Enabling garbage collection
        gc.enable()
        gc.collect()
        payload = ""
        blocktbs = []
        payload  = []
        packet = ""
        global_time_t1 = time.time()
        time_to_send = global_time_t1 - global_time_t0
        if self.debug_mode_send: print("DEBUG SEND 255: time to send {:.4f} seconds".format(time_to_send))
        return rcvr_addr, stats_psent, stats_retrans, FAILED, time_to_send

    def _crecv(self, the_sock, my_addr, snd_addr):
        global_time_t0 = time.time()

        # Shortening addresses to last 8 bytes
        my_addr  = my_addr[8:]
        snd_addr = snd_addr[:8]
        ack_required = True
        if self.debug_mode_recv: print ("DEBUG RECV 264: my_addr, snd_addr: ", my_addr, snd_addr)

        # Buffer storing the received data to be returned
        rcvd_data = b''
        last_check = 0

        next_acknum = self.ONE
        the_sock.settimeout(5)

        if (snd_addr == self.ANY_ADDR) or (snd_addr == b''): SENDER_ADDR_KNOWN = False
        self.p_resend = 0   ###

        # Enabling garbage collection
        gc.enable()
        gc.collect()
        while True:
            try:
                the_sock.setblocking(True)
                packet = the_sock.recv(self.MAX_PKT_SIZE)
                if self.debug_mode_recv: print ("DEBUG RECV 283: packet received: ", packet)
                inp_src_addr, inp_dst_addr, hello, inp_seqnum, inp_ackrequired, inp_acknum, is_ack, last_pkt, check, content = self.__unpack(packet)
                if self.debug_mode_recv: print ("DEBUG RECV 286: inp_src_addr {}, inp_dst_addr {}, hello {}, inp_seqnum {}, inp_acknum {}, is_ack {}, last_pkt {}, check {}, content {}".format(inp_src_addr, inp_dst_addr, hello, inp_seqnum, inp_acknum, is_ack, last_pkt, check, content))

                # If destination address is broadcast and mensage hello, then no send acknowledgement package
                if (hello):
                    ack_required = False
                    self.__register_node(inp_src_addr, content)

                # getting sender address, if unknown, with the first packet
                if (not SENDER_ADDR_KNOWN):
                    snd_addr = inp_src_addr
                    SENDER_ID_KNOWN = True
                # Checking if a "valid" packet... i.e., either for me or broadcast
                if (inp_dst_addr != my_addr) and (inp_dst_addr != self.ANY_ADDR):
                    if self.debug_mode_recv: print("RECV DISCARDED received packet not for me!!")
                    continue
            except socket.timeout:
                if self.debug_mode_recv: print ("RECV EXCEPTION!! Socket timeout: ", time.time())
                continue
            except Exception as e:
                print (" RECV EXCEPTION!! Packet not valid: ", e)
                continue

            if self.debug_mode_recv: print("DEBUG RECV 300: get_checksum(content)", self.__get_checksum(content))
            checksum_OK = (check == self.__get_checksum(content))

            if (checksum_OK) and (next_acknum == inp_acknum) and (snd_addr == inp_src_addr):
                rcvd_data += content
                last_check = check

                if ack_required:
                    # Sending ACK
                    next_acknum = (inp_acknum + self.ONE) % 2
                    ack_segment = self.__make_packet(my_addr, inp_src_addr, hello, inp_seqnum, ack_required, next_acknum, self.ITS_ACK_PACKET, last_pkt, b'')
                    if self.debug_mode_recv: print ("DEBUG RECV 310: Forwarded package", self.p_resend)   ###
                    self.p_resend = self.p_resend + 1   ###
                    the_sock.setblocking(False)
                    the_sock.send(ack_segment)
                    if self.debug_mode_recv: print("DEBUG RECV 314: Sent ACK", ack_segment)
                    if (last_pkt):
                        break
                else:
                    break
            elif (checksum_OK) and (last_check == check) and (snd_addr == inp_src_addr):
                # KN: Handlig ACK lost
                rcvd_data += content

                if ack_required:
                    # KN: Re-Sending ACK
                    next_acknum = (inp_acknum + self.ZERO) % 2
                    ack_segment = self.__make_packet(my_addr, inp_src_addr, hello, inp_seqnum, ack_required, next_acknum, self.ITS_ACK_PACKET, last_pkt, b'')
                    self.p_resend = self.p_resend -1 #CHANGED
                    if self.debug_mode_recv: print ("DEBUG RECV 325: Forwarded package", self.p_resend)   ###
                    the_sock.setblocking(False)
                    the_sock.send(ack_segment)
                    if self.debug_mode_recv: print("DEBUG RECV 328: re-sending ACK", ack_segment)
                    if (last_pkt):
                        break
                else:
                    break
            else:
                if self.debug_mode_recv: print ("DEBUG RECV 332: packet not valid", packet)

        # KN: Enabling garbage collection
        last_check = 0
        packet = ""
        content = ""
        gc.enable()
        gc.collect()
        global_time_t1 = time.time()
        time_to_recv = global_time_t1 - global_time_t0
        if self.debug_mode_send: print("DEBUG SEND 255: time to send {:.4f} seconds".format(time_to_recv))
        return rcvd_data, snd_addr, time_to_recv

    def connect(self, dest=ANY_ADDR):
        print("loractp: connecting to... ", dest)
        rcvr_addr, stats_psent, stats_retrans, FAILED, time_to_send = self._csend(b"CONNECT", self.send, self.lora_mac, dest)
        return self.my_addr, rcvr_addr, stats_psent, stats_retrans, FAILED, time_to_send

    def hello(self, dest=ANY_ADDR):
        if self.debug_mode_send: print("loractp: send hello to... ", dest)
        nodes = b'None'
        nodes_list = self.get_discovered_nodes_list()

        if len(nodes_list) > 0:
            nodes = ujson.dumps(dict.fromkeys(nodes_list, '')).encode('utf-8')

        rcvr_addr, stats_psent, stats_retrans, FAILED, time_to_send = self._csend(nodes, self.send, self.lora_mac, dest, ack_required=False, hello=True)
        return self.my_addr, rcvr_addr, stats_psent, stats_retrans, FAILED

    def listen(self, sender=ANY_ADDR):
        print("loractp: listening for...", sender)
        rcvd_data, snd_addr, time_to_recv = self._crecv(self.recv, self.lora_mac, sender)
        if (rcvd_data==b"CONNECT"):
            return self.my_addr, snd_addr, 0
        else:
            return self.my_addr, snd_addr, -1

    def sendit(self, addr=ANY_ADDR, payload=b'', ack_required=True):
        rcvr_addr, stats_psent, stats_retrans, FAILED, time_to_send = self._csend(payload, self.send, self.lora_mac, addr, ack_required)
        return rcvr_addr, stats_psent, stats_retrans, FAILED, time_to_send

    def recvit(self, addr=ANY_ADDR):
        rcvd_data, snd_addr, time_to_recv = self._crecv(self.recv, self.lora_mac, addr)
        return rcvd_data, snd_addr, time_to_recv

    def get_lora_mac(self):
        return (self.lora_mac).decode('utf-8')

    def get_my_addr(self):
        return (self.my_addr).decode('utf-8')

    def get_discovered_nodes(self):
        return self.DISCOVERED_NODES

    def get_discovered_nodes_list(self):
        return list(self.DISCOVERED_NODES.keys())
