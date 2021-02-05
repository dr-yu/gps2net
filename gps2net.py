#!/usr/bin/env python
import argparse
import logging
import socket
import threading
import sys
import time
import signal
import Queue
import serial
import select
import os
import pynmea2
from pprint import pprint
from BaseHTTPServer import BaseHTTPRequestHandler,HTTPServer
import json



#pip install pynmea2


handler_threads = []
handlers = []

#globalrun = True
gpsdata = {'lat':0,'lon':0 }
#gpsdata[lat]

class StoppableThread(threading.Thread):
    """Thread class with a stop() method. The thread itself has to check
    regularly for the stopped() condition."""

    def __init__(self, **kwargs):
        super(StoppableThread, self).__init__(**kwargs)
        self._stop = threading.Event()

    def stop(self):
        self._stop.set()

    def stopped(self):
        return self._stop.isSet()


class NMEAHandler(object):
    """Abstract superclass for devices that exchange NMEA data"""
    def __init__(self):
        self.queue = Queue.Queue()
        self.running = True
        self.connected = False
        self.nmea_buffer = ''
        self.message_rx_count = 0
        self.message_tx_count = 0

    def send(self, data):
        """Subclasses should override this to transmit data"""
        pass

    def receive(self):
        """Subclasses should override this to receive data"""
        pass

    def close(self):
        """Subclasses should override this to perform shutdown-related tasks"""
        pass

    def put_queue_data(self, data):
        #logging.info("NMEAHandler put_queue_data running: %s, connected: %s, thread: %s" % (self.running, self.connected, handler_thread.name))
        if self.running and self.connected:
            #logging.info("NMEAHandler put_queue_data thread: %s" % (handler_thread.name))
            #print "NMEAHandler put_queue_data"
            self.queue.put(data)

    def stop(self):
        self.running = False
        self.close()
        handlers.remove(self)
 	# TODO: Empty the queue

    def handle(self):
        #print "NMEAHandler handle"
        # Receive data
        try: 
          data = self.receive()
        except Exception as e:
          os._exit(1)

        if data:
           
            #print "NMEAHandler handle data"
            lines = (self.nmea_buffer + data).split('\r')
            self.nmea_buffer = lines.pop()
            # TODO: Checksum?
            for nmea_message in lines:
                nmea_message = nmea_message.strip()
                logging.debug("%s received message: %s" % (self, nmea_message))
                self.message_rx_count += 1
                #print "NMEAHandler handle data message"
 
                for handler in handlers:
                    if handler != self:
                        #print "NMEAHandler handle data message handler"
                        handler.put_queue_data(nmea_message)

        # Transmit data
        while not self.queue.empty():
            data = self.queue.get()
            logging.debug("%s will transmit message: %s" % (self, data))
            self.message_tx_count += 1
            self.send(data + '\r\n')

        time.sleep(0.01)
        #print "1ee11"

    def loop(self):
        while self.running:
            self.handle()


class NMEASerialDevice(NMEAHandler):
    """Opens a serial port with the specified path and baud for receiving NMEA Messages"""
    def __init__(self, device_path, baud_rate):
        #print "NMEASerialDevice init"
        super(NMEASerialDevice, self).__init__()
        #print "Self init"
        self.device = serial.Serial(device_path, baud_rate, timeout=0)
        self.connected = True

    def send(self, data):
        #print "NMEASerialDevice send"
        self.device.write(data)

    def receive(self):
        #print "NMEASerialDevice recieve"
        return self.device.read(1024)

    def close(self):
        #print "NMEASerialDevice close"
        self.device.close()

    def __str__(self):
        return '%s (%s)' % (self.__class__.__name__, self.device.portstr)


class NMEATCPConnection(NMEAHandler):
    """Opens a TCP socket on the specified port for receiving NMEA Messages"""
    def __init__(self, client, address):
        super(NMEATCPConnection, self).__init__()

        self.connected = True
        self.client = client
        self.address = address

    def send(self, data):
        ready = select.select([], [self.client], [], 0)
        if ready[1]:
            self.client.send(data)
            return True
        else:
            return False

    def receive(self):
        ready = select.select([self.client], [], [], 0)
        if ready[0]:
            return self.client.recv(1024)

    def close(self):
        if self.client:
            self.client.close()

    def loop(self):
        while self.running:
            try:
                super(NMEATCPConnection, self).loop()
            except socket.error:
                if self.connected:
                    logging.info('Client %s disconnected' % self.address[0])
                    self.connected = False
                    self.client = None
                    self.address = None
                    self.stop()

    def __str__(self):
        return '%s (%s)' % (self.__class__.__name__, self.address[0])


class NMEADecode(NMEAHandler):
    def __init__(self):
        super(NMEADecode, self).__init__()
        self.connected = True

    def send(self, data):
        global gpsdata

        msg = pynmea2.parse(data)
        dataarr=data.split(',')


        #print(msg.latitude)
        #print(repr(msg))
        #print([msg])
        #print data
        #print (vars(msg))
        #pprint(vars(msg))
        #print(msg.sentence_type)

        if dataarr[0] == '$GNRMC':
            times = str(dataarr[1])
            dates = dataarr[9]
            lats  = dataarr[3]
            lons  = dataarr[5]
            gpsdata['lat'] = (float(lats[0]+lats[1])+(float(lats[2]+lats[3]+lats[4]+lats[5]+lats[6]+lats[7]+lats[8]))/60)
            gpsdata['lon'] = (float(lons[0]+lons[1]+lons[2])+((float(lons[3]+lons[4]+lons[5]+lons[6]+lons[7]+lons[8]+lons[9]))/60))
            gpsdata['hspeed_kn'] = dataarr[7]
            gpsdata['hspeed_kph'] = float(dataarr[7]) * 1.852
            gpsdata['iso8601date'] = '20'+dates[4]+dates[5]+'-'+dates[0]+dates[1]+'-'+dates[2]+dates[3]+'T'+times[0]+times[1]+':'+times[2]+times[3]+':'+times[4]+times[5]+'+00:00'

            #print("================================")
            #
            #print(data)
            #print(dataarr[3])
            #zprint(times)
            #print(repr(msg))

            #print("")

    def loop(self):
        #print "NMEADecode loop"
        logging.info("Decode handler running in thread: %s" % (handler_thread.name))
        while 1:
            while not self.queue.empty():
                data = self.queue.get()
                logging.debug("%s will transmit message: %s" % (self, data))
                self.message_tx_count += 1
                #self.send(data + '\r\n')
                self.send(data)

            #logging.info("Decode handler running in thread: %s" % (handler_thread.name))
            #time.sleep(1)
            time.sleep(0.01)

class HttpProcessor(BaseHTTPRequestHandler):
    def do_GET(self):
        global gpsdata
        self.send_response(200)
        #self.send_header('content-type','text/html')
        self.send_header('content-type','application/json')
        self.end_headers()
        #self.wfile.write("hello !")
        self.wfile.write(json.dumps(gpsdata))

def listen_on_port(port):
        logging.info("Listening on port %s" % port)
        backlog = 5

        listen_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        listen_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        listen_socket.bind(('0.0.0.0', port))
        listen_socket.setblocking(0)
        listen_socket.settimeout(0)
        listen_socket.listen(backlog)

        while 1:
            try:
                client, address = listen_socket.accept()

                handler = NMEATCPConnection(client, address)
                handler_thread = StoppableThread(target=handler.loop)
                handler_thread.daemon = True
                handler_thread.start()
                handler_threads.append(handler_thread)
                handlers.append(handler)

                logging.info('Client %s connected to port %s' % (address[0], port))

            except socket.error:
                time.sleep(0.5)


def thread_cleanup(signal, frame):
    for handler in handlers:
        handler.stop()

    for thread in handler_threads:
        thread.stop()
        logging.info('Cleaning up thread: %s' % thread.name)
        #################################################################################
    #global globalrun
    #globalrun = False
    httpserv.shutdown()
    sys.exit(0)


def show_stats(signal, frame):
    for handler in handlers:
        logging.info("%s TX: %d RX: %d" % (handler, handler.message_tx_count, handler.message_rx_count))


signal.signal(signal.SIGINT, thread_cleanup)
signal.signal(signal.SIGUSR1, show_stats)

def init_ser():
        handler = NMEASerialDevice(device, baud)
        handler_thread = StoppableThread(target=handler.loop)
        handler_thread.daemon = True
        handler_thread.start()
        handler_threads.append(handler_thread)
        handlers.append(handler)
        logging.info("Serial handler for %s running in thread: %s" % (uart_device, handler_thread.name))
   

#def thread_function():
#    global globalrun
#    global gpsdata
#    while globalrun:
#        logging.info("lat: %s, lon: %s" % (gpsdata['lat'], gpsdata['lon']))
#
#        #print (json.dumps(gpsdata))
#        time.sleep(1)
#
#    #logging.info("Thread %s: starting", name)
#    #rand = random.randint(20, 30)
#    #time.sleep(5)
#    #logging.info("Thread %s: finishing", name)




if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='Multiplexes and forwards NMEA streams from serial ports and TCP sockets.', formatter_class=argparse.ArgumentDefaultsHelpFormatter)
    parser.add_argument('--loglevel', help='Set log level to DEBUG, INFO, WARNING, or ERROR', default='INFO')
    parser.add_argument('--logfile', help='Log file to append to.',)
    parser.add_argument('--uart', help='File descriptor of UART to connect to proxy.', metavar="DEVICE[,BAUD]", action='append', default=[])
    parser.add_argument('--tcp', help='Listening ports to open for proxy.', type=int)

    args = parser.parse_args()
    log_level = args.loglevel
    log_file = args.logfile
    uart_devices = args.uart
    tcp_port = args.tcp

    numeric_log_level = getattr(logging, log_level.upper(), None)
    if not isinstance(numeric_log_level, int):
        raise ValueError('Invalid log level: %s' % log_level)
    logging.basicConfig(level=numeric_log_level, format='%(asctime)s %(levelname)s:%(message)s', filename=log_file)

    for uart_device in uart_devices:
        if ',' in uart_device:
            device, baud = uart_device.split(',')
        else:
            device = uart_device
            baud = 115200
        init_ser()


    #x = threading.Thread(target=thread_function, args=())
    #x.start()

    httpserv = HTTPServer(('',8080),HttpProcessor)
    y = threading.Thread(target=httpserv.serve_forever, args=())
    #y = threading.Thread(target=start_http_server, args=())
    y.start()

   
    handler = NMEADecode()
    handler_thread = StoppableThread(target=handler.loop)
    handler_thread.daemon = True
    handler_thread.start()
    handler_threads.append(handler_thread)
    handlers.append(handler)



    if tcp_port:
        listen_on_port(tcp_port)
    else:
        while 1:
            time.sleep(1)
