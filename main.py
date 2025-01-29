import beacon
import network, socket, time
import urequests as requests
from time import sleep
import machine
from micropython import const
import uasyncio as asyncio
import aioble.central
import bluetooth
import random
import struct
import sys
import binascii
import ujson
import os
from machine import Pin
led = Pin("LED", Pin.OUT)
led.value(0)
tiltScanList = []
wifiSettings = False
SSID_complete = False
KEY_complete = False
SSID = ''
KEY = ''
tiltColors = [ 'RED', 'GREEN', 'BLACK', 'PURPLE', 'ORANGE', 'BLUE', 'YELLOW', 'PINK' ]

def logToCloud(tiltData):

    while True:

        # Do things here, perhaps measure something using a sensor?

        # ...and then define the headers and payloads
        #headers = "..."
        #payload = "..."

        # Then send it in a try/except block
        try:
            print("sending...")
            response = requests.post("https://dweet.io/dweet/for/tilt-test23", headers = { "content-type" : 'application/x-www-form-urlencoded; charset=utf-8' }, data = 'Timepoint=' + TIME + '&SG=' + SG + '&Temp=' + TEMP + '&Color=' + COLOR + '&Beer=' + BEER + '&Comment=' + COMMENT)
            print(response)
            print("sent (" + str(response.status_code) + "), status = " + str(wlan.status()) )
            response.close()
        except:
            print("could not connect (status =" + str(wlan.status()) + ")")
            if wlan.status() < 0 or wlan.status() >= 3:
                print("trying to reconnect...")
                wlan.disconnect()
                wlan.connect(SSID, KEY)
                if wlan.status() == 3:
                    print('connected')
                else:
                    print('failed')
        break

def saveWiFi(SSID, KEY):
 jsonWiFi = { "SSID" : SSID, "KEY" : KEY }
 try:
  with open('wifi.json', 'w') as f:
   ujson.dump(jsonWiFi, f)
   wifiSettings = True
 except:
        print("Error! Could not save")
        
def saveLogConfig(COLOR, MAC, BEER, COMMENT, isEMAIL, CLOUDURL):
 if isEMAIL == 'true':
    response = asyncio.run(tiltscanner(MAC, COLOR, BEER, COMMENT, CLOUDURL, 500))
    while response == None:
        time.sleep(1)
        response = asyncio.run(tiltscanner(MAC, COLOR, BEER, COMMENT, CLOUDURL, 500))
 jsonLogConfig = { "Color" : COLOR, "Beer" : BEER, "Comment" : COMMENT, "CloudURL" : CLOUDURL }
 try:
  with open('logconfig.json', 'w') as f:
   ujson.dump(jsonLogConfig, f)
 except:
        print("Error! Could not save")
     

async def tiltscanner(SCANLENGTH, SCANFOR):
  global led
  global SSID_complete
  global KEY_complete
  global SSID
  global KEY
  SSID_complete = False
  KEY_complete = False
  Part1_complete = False
  Part2_complete = False
  async with aioble.scan(SCANLENGTH, interval_us=500*1000, window_us=500*1000, active=False) as scanner:
    async for result in scanner:
     if SCANFOR == 'wifi_config':
        if binascii.hexlify(result.adv_data[6:9]) == b'a495bc' and result.rssi > -60:
         led.value(1)
         major = int(binascii.hexlify(result.adv_data[22:24]), 16)
         minor = int(binascii.hexlify(result.adv_data[24:26]), 16)
         hex_str = binascii.hexlify(result.adv_data[10:22]).decode('utf-8')
         if binascii.hexlify(result.adv_data[6:10]) == b'a495bc00' and not SSID_complete:
          if minor == 1 and major == 1:
           SSID = bytes.fromhex(hex_str).decode('utf-8')
           print(SSID)
           SSID_complete = True
          elif minor == 1 and major == 2 and not Part1_complete:
           Part1_complete = True
           SSID = SSID.replace('\u0000', '') + bytes.fromhex(hex_str).decode('utf-8')
           print(SSID)
          elif minor == 2 and major == 2:
           SSID = SSID + bytes.fromhex(hex_str).decode('utf-8')
           print(SSID)
           Part1_complete = False
           SSID_complete = True
          elif minor == 1 and major == 3 and not Part1_complete:
           Part1_complete = True
           SSID = SSID.replace('\u0000', '') + bytes.fromhex(hex_str).decode('utf-8')
           print(SSID)
          elif minor == 2 and major == 3 and not Part2_complete:
           Part2_complete = True
           SSID = SSID.replace('\u0000', '') + bytes.fromhex(hex_str).decode('utf-8')
           print(SSID)
          elif minor == 3 and major == 3:
           SSID = SSID.replace('\u0000', '') + bytes.fromhex(hex_str).decode('utf-8')
           print(SSID)
           SSID_complete = True
           Part1_complete = False
           Part2_complete = False
         if binascii.hexlify(result.adv_data[6:10]) == b'a495bc01' and not KEY_complete:
          if minor == 1 and major == 1:
           KEY = bytes.fromhex(hex_str).decode('utf-8')
           print(KEY)
           KEY_complete = True
          elif minor == 1 and major == 2 and not Part1_complete:
           Part1_complete = True
           KEY = KEY.replace('\u0000', '') + bytes.fromhex(hex_str).decode('utf-8')
           print(KEY)
          elif minor == 2 and major == 2:
           KEY = KEY + bytes.fromhex(hex_str).decode('utf-8')
           print(KEY)
           KEY_complete = True
          elif minor == 1 and major == 3 and not Part1_complete:
           Part1_complete = True
           KEY = KEY.replace('\u0000', '') + bytes.fromhex(hex_str).decode('utf-8')
           print(KEY)
          elif minor == 2 and major == 3 and not Part2_complete:
           Part2_complete = True
           KEY = KEY.replace('\u0000', '') + bytes.fromhex(hex_str).decode('utf-8')
           print(KEY)
          elif minor == 3 and major == 3:
           KEY = KEY.replace('\u0000', '') + bytes.fromhex(hex_str).decode('utf-8')
           print(KEY)
           KEY_complete = True
         if SSID_complete and KEY_complete:
          saveWiFi(SSID.replace('\u0000', ''), KEY.replace('\u0000', ''))
          led.value(0)
          break
     if SCANFOR == 'tilts':
      if binascii.hexlify(result.adv_data[9:12]) == b'a495bb' and binascii.hexlify(result.adv_data[13:25]) == b'c5b14b44b5121370f02d74de':
          global tiltColors
          UUID = str(binascii.hexlify(result.adv_data[9:25]).decode())
          COLOR = tiltColors[int(UUID[6]) - 1]
          MAC = str(binascii.hexlify(result.device.addr).decode())
          MAJOR = str(int(binascii.hexlify(result.adv_data[25:27]), 16))
          MINOR = str(int(binascii.hexlify(result.adv_data[27:29]), 16))
          if int(MINOR) > 5000:
              HD = True
          else:
              HD = False
          TX_POWER = str(int(binascii.hexlify(result.adv_data[29:31]), 16))
          RSSI = str(result.rssi)
          tiltScanList.append({ "uuid" : UUID, "hd" : HD, "color" : COLOR, "mac" : MAC, "major" : MAJOR, "minor" : MINOR, "tx_power" : TX_POWER, "rssi" : RSSI })

# HTML template for the webpage
async def webpage():
 return await tiltscanner(1100, 'tilts')

async def startWebserver():
    global wifiSettings
    global SSID_complete
    global KEY_complete
    global SSID
    global KEY
    try:
        with open('wifi.json', 'r') as f:
         data = ujson.load(f)
         SSID = data["SSID"]
         KEY = data["KEY"]
         wifiSettings = True
    except:
        wifiSettings = False
        return
    # Connect to WLAN
    wlan = network.WLAN(network.STA_IF)
    wlan.active(True)
    wlan.connect(SSID, KEY)

    # Wait for Wi-Fi connection
    connection_timeout = 30
    while connection_timeout > 0:
        if wlan.status() >= 3:
            break
        connection_timeout -= 1
        print('Waiting for Wi-Fi connection...')
        time.sleep(1)

    # Check if connection is successful
    if wlan.status() != 3 and wifiSettings:
        if delete_file('wifi.json'):
         print("File deleted.")
        else:
          print("Failed to delete file.")
        machine.soft_reset()
    else:
        led.value(1)
        print('Connection successful!')
        network_info = wlan.ifconfig()
        print('Connected to ' + network_info[0])
        ipAddr = ip_to_uint16(network_info[0])
        beacon.startiBeacon(ipAddr[0], ipAddr[1])
        wifiSettings == True

    # Set up socket and start listening
    addr = socket.getaddrinfo('0.0.0.0', 80)[0][-1]
    s = socket.socket()
    s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    s.bind(addr)
    s.listen()

    print('Listening on', addr)
    # Initialize variables
    state = "OFF"
    random_value = 0
    # Main loop to listen for connections
    while True:
        try:
            conn, addr = s.accept()
            print('Got a connection from', addr)
            led.value(0)
            
            # Receive and parse the request
            request = conn.recv(1024)
            request = str(request)
            #print('Request content = %s' % request)

            try:
                request = request.split('\\r\\n')[0]
                request = request.split(' ')[1]
                requestList = request.split('?')
                print('Request:', request)
            except IndexError:
                pass
            # Process the request and update variables
            if requestList[0] == "/reset":
                if delete_file('wifi.json'):
                 conn.send('HTTP/1.0 200 OK\r\nContent-type: application/json\r\n\r\n')
                 conn.send('"status" : "WiFi settings file deleted"')
                else:
                 conn.send('HTTP/1.0 200 OK\r\nContent-type: application/json\r\n\r\n')
                 conn.send('"status" : "Failed to delete WiFi settings file"')
                machine.soft_reset()
            elif requestList[0] == '/sync':
                tiltDataList = requestList[1].split('&')
                tiltObject = {}
                for data in tiltDataList:
                    tiltObject[data.split('=')[0]] = data.split('=')[1]
                tiltObject['timestamp'] = time.time()
                create_settings_file(tiltObject.get('color', 'unknown'), tiltObject)
            elif request == '/value?':
                random_value = random.randint(0, 20)
            
            # Generate HTML response
            await tiltscanner(1100, 'tilts')
             
            # Send the HTTP response and close the connection
            conn.send('HTTP/1.0 200 OK\r\nContent-type: application/json\r\n\r\n')
            conn.send(ujson.dumps(tiltScanList))
            tiltScanList.clear()
            conn.close()

        except OSError as e:
            conn.close()
            print('Connection closed')

def create_settings_file(color, data):
  try:
    with open(color + '.json', 'w') as f:
      f.write(ujson.dumps(data))
    print(f"File '{color}' created successfully.")
  except OSError as e:
    print(f"Error creating file: {e}")
    
def ip_to_uint16(ip_address):

  try:
    # Split the IP address into octets
    octets = ip_address.split(".")

    # Convert octets to integers and pack them into 16-bit integers
    uint16_1 = (int(octets[0]) << 8) | int(octets[1])
    uint16_2 = (int(octets[2]) << 8) | int(octets[3])

    return uint16_1, uint16_2

  except Exception as e:
    print(f"Error converting IP address: {e}")
    return None

async def reset_button_reader():
    while True:
        if rp2.bootsel_button() == 1:
            if delete_file('wifi.json'):
             await asyncio.sleep(0.2)
        await asyncio.sleep_ms(10)

def delete_file(filename):
  try:
    os.remove(filename)
    print(f"File '{filename}' deleted successfully.")
    return True
  except OSError as e:
    print(f"Error deleting file '{filename}': {e}")
    return False

async def main():
 global wifiSettings
 asyncio.create_task(reset_button_reader())
 #await asyncio.sleep(5)#allow time to press reset button before starting server
 while True:
    await startWebserver()
    if wifiSettings == False:
        beacon.startiBeacon(999, 999)
        wifiSettings = True
        while not SSID_complete:
            await tiltscanner(0, 'wifi_config')
        await startWebserver()
        
asyncio.run(main())
