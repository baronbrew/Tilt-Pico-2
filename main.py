from RequestParser import RequestParser
from ResponseBuilder import ResponseBuilder
import calibration
import beacon
import network, socket, time
import ntptime
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
targetTiltScan = {}
lastLogged = {}
wifiSettings = False
SSID_complete = False
KEY_complete = False
SSID = ''
KEY = ''
tiltColors = [ 'RED', 'GREEN', 'BLACK', 'PURPLE', 'ORANGE', 'BLUE', 'YELLOW', 'PINK' ]

async def logToCloud(color, cloudinterval, passedTiltScan):
    global lastLogged
    # Only log if interval has passed
    for config_file in os.listdir():
        if config_file.startswith('config-'):
            config = config_file[:-5]
            if len(config.split('-')) == 3:
                if config.split('-')[2] == color:
                    if lastLogged.get(color, 0) + int(config.split('-')[1]) * 60 >= time.time() + 870:
                        print(color + ' already logged within interval')
                        return False
            elif len(config.split('-')) == 4:
                if config.split('-')[2] + '-' + config.split('-')[3] == color: 
                    if lastLogged.get(color, 0) + int(config.split('-')[1]) * 60 >= time.time() + 870:
                        print(color + ' already logged within interval')
                        return False
    try:
        with open('config-' + cloudinterval + '-' + color + '.json', 'r') as f:
         tiltAppData = ujson.load(f)
    except:
        print('couldnt open json settings file')
        return False
    timeZoneOffsetSec = int(tiltAppData.get('timezoneoffsetsec', '0'))
    unixTimeStampLocal = passedTiltScan.get('timestamp', 0) - timeZoneOffsetSec
    unixFractionOfDay = 115.74 * (unixTimeStampLocal - (int((str(unixTimeStampLocal / 86400)).split('.')[0]) * 86400))
    excelTimeStamp = (str(unixTimeStampLocal / 86400 + 25569)).split('.')[0] + '.' + (str(unixFractionOfDay)).split('.')[0]
    if len(color.split('-')) == 1:
        precal_temp = passedTiltScan.get('major', 0)
        precal_sg = passedTiltScan.get('minor', 0) / 1000
    else:
        precal_temp = passedTiltScan.get('major', 0) / 10
        precal_sg = passedTiltScan.get('minor', 0) / 10000
    tilttempcal = processCalibrationValues(tiltAppData.get('tilttempcal', 'unknown'))
    actualtempcal = processCalibrationValues(tiltAppData.get('actualtempcal', 'unknown'))
    temp = calibration.calibrate_value(tilttempcal, actualtempcal, precal_temp)
    tiltsgcal = processCalibrationValues(tiltAppData.get('tiltSGcal', 'unknown'))
    actualsgcal = processCalibrationValues(tiltAppData.get('actualSGcal', 'unknown'))
    sg = calibration.calibrate_value(tiltsgcal, actualsgcal, precal_sg)
    print(tiltsgcal)
    print(actualsgcal)
    print(sg)
    
    print('Timepoint=' + excelTimeStamp + '&SG=' + str(sg) + '&Temp=' + str(temp) + '&Color=' + tiltAppData.get('color', 'unknown').split('-')[0] + '&Beer=' + tiltAppData.get('beername', 'unknown') + '&Comment=')
    print(tiltAppData.get('color','unknown'))
    while True:
        try:
            print("sending...")
            response = requests.post(tiltAppData.get('cloudurls','unknown'), headers = { "content-type" : 'application/x-www-form-urlencoded; charset=utf-8' }, data = 'Timepoint=' + excelTimeStamp + '&SG=' + str(sg) + '&Temp=' + str(temp) + '&Color=' + tiltAppData.get('color', 'unknown').split('-')[0] + '&Beer=' + tiltAppData.get('beername', 'unknown') + '&Comment=')
            #targetTiltScan['timestamp'] = 0
            print(response.status_code)
            if response.status_code == 200:
                print(response.text)  # Process the successful response
            elif response.status_code == 400:
                print("Expected error from Google Sheets")
            else:
                print(f"Error: HTTP {response.status_code}")  # Handle other errors
        except OSError as e:
            print(f"Error: Network issue or other error: {e}")
        finally:
            if 'response' in locals(): # check to see if response was defined. Prevents an error if the request failed before response was assigned.
                response.close()  # Important: Close the response to free up resources
            lastLogged[color] = time.time()
            print(lastLogged)
            break

def processCalibrationValues(cal_points):
        proc_cal_points = []
        try:
            if len(cal_points.split(',')) > 0:
                for cal_point in cal_points.split(','):
                    proc_cal_points.append(float(cal_point))
                return proc_cal_points
            else:
                return proc_cal_points
        except:
            return proc_cal_points
    


def saveWiFi(SSID, KEY):
 jsonWiFi = { "SSID" : SSID, "KEY" : KEY }
 try:
  with open('wifi.json', 'w') as f:
   ujson.dump(jsonWiFi, f)
   wifiSettings = True
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
          UUID = str(binascii.hexlify(result.adv_data[9:25]).decode())
          MAC = str(binascii.hexlify(result.device.addr).decode())
          MAJOR = int(binascii.hexlify(result.adv_data[25:27]), 16)
          MINOR = int(binascii.hexlify(result.adv_data[27:29]), 16)
          TX_POWER = str(int(binascii.hexlify(result.adv_data[29:31]), 16))
          RSSI = result.rssi
          TIMESTAMP = time.time()
          tiltScanList.append({ "uuid" : UUID, "mac" : MAC, "major" : MAJOR, "minor" : MINOR, "tx_power" : TX_POWER, "rssi" : RSSI, "timestamp" : TIMESTAMP })
# HTML template for the webpage
async def webpage():
 return await tiltscanner(1100, 'tilts')

async def startWebserver():
    global tiltScanList
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
        await set_time_from_ntp()
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
                conn.close()
                machine.soft_reset()
            elif requestList[0] == '/sync':
                tiltDataList = requestList[1].split('&')
                tiltObject = {}
                for data in tiltDataList:
                    tiltObject[data.split('=')[0]] = data.split('=')[1]
                await tiltscanner(1100, 'tilts')
                tiltScanList = await sort_objects_by_key_value(tiltScanList, 'rssi')
                await create_settings_file(tiltObject.get('color', 'unknown'), tiltObject)
                await logToCloud(tiltObject.get('color', 'unknown'))
            elif request == '/value?':
                random_value = random.randint(0, 20)
            else:
                await tiltscanner(1100, 'tilts')
                tiltScanList = await sort_objects_by_key_value(tiltScanList, 'rssi')
             
            # Send the HTTP response and close the connection
            conn.send('HTTP/1.0 200 OK\r\nContent-type: application/json\r\n\r\n')
            conn.send(ujson.dumps(tiltScanList))
            tiltScanList.clear()
            conn.close()

        except OSError as e:
            conn.close()
            print('Connection closed')

async def create_settings_file(color, data):
  global tiltColors
  global targetTiltScan
  for tiltScan in tiltScanList:
    if tiltColors[int(tiltScan.get('uuid', 'a495bb1')[6]) - 1] == color.split('-')[0]:
        targetTiltScan = tiltScan
        break
  data['mac'] = targetTiltScan.get('mac', 'unknown')
  if targetTiltScan.get('minor', 0) > 5000:
      data['sg'] = targetTiltScan.get('minor', 1000) / 10000
      data['temp'] = targetTiltScan.get('major', 0) / 10
      data['color'] = tiltColors[int(targetTiltScan.get('uuid', 'a495bb1')[6]) - 1] + '-HD'
  else:
      data['sg'] = targetTiltScan.get('minor', 1000) / 1000
      data['temp'] = targetTiltScan.get('major', 0)
      data['color'] = tiltColors[int(targetTiltScan.get('uuid', 'a495bb1')[6]) - 1]
  for config_file in os.listdir():
        if config_file.startswith('config-'):
            config = config_file[:-5]
            if len(config.split('-')) == 3:
                if config.split('-')[2] == color:
                    delete_file(config_file)
            elif len(config.split('-')) == 4:
                if config.split('-')[2] + '-' + config.split('-')[3] == color:
                    delete_file(config_file)
  try:
    with open('config-' + data['cloudinterval'] + '-' + color + '.json', 'w') as f:
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

async def set_time_from_ntp(retries=3, delay=1):
    attempts = 0
    while attempts < retries:
        try:
            ntptime.host = "pool.ntp.org"  # Or your preferred NTP server
            ntptime.settime()
            print(time.time())
            print(time.localtime())
            return True  # Success!

        except OSError as e:
            attempts += 1
            print(f"NTP synchronization failed (attempt {attempts}/{retries}): {e}")
            if attempts < retries:
                time.sleep(delay)  # Wait before retrying
            else:
                print("NTP synchronization failed after multiple retries.")
            continue # Continue to the next attempt.

    return False  # All attempts failed

async def sort_objects_by_key_value(objects, key):
    if not objects:  # Handle empty list case
        return []

    try:  # Try to access the key and convert to numeric for all objects.
        # This will raise a KeyError if the key doesn't exist, or a TypeError if the value isn't comparable.
        test_value = objects[0][key]
        if not isinstance(test_value, (int, float)): # Check if values are numeric.
            test_value = float(test_value) # Attempt conversion. Will throw ValueError if not possible

    except (KeyError, TypeError, ValueError):
        return objects  # Return original if any object is missing the key or not numerically comparable.

    return sorted(objects, key=lambda obj: obj.get(key, 0), reverse=True) # Sort, using 0 as default value if key is missing.





# coroutine to handle HTTP request
async def handle_request(reader, writer):
    global tiltScanList
    try:
        # allow other tasks to run while waiting for data
        raw_request = await reader.read(2048)

        request = RequestParser(raw_request)

        response_builder = ResponseBuilder()

        # filter out api request
        if request.url_match('/'):
            await tiltscanner(1100, 'tilts')
            tiltScanList = await sort_objects_by_key_value(tiltScanList, 'rssi')
            response_builder.set_body_from_dict(tiltScanList)
            tiltScanList.clear()
            
        #print(raw_request)
        #print (request.query_string)
        else:
            tiltDataList = request.query_string.split('&')
            tiltObject = {}
            for data in tiltDataList:
                tiltObject[data.split('=')[0]] = data.split('=')[1]
            await tiltscanner(1100, 'tilts')
            tiltScanList = await sort_objects_by_key_value(tiltScanList, 'rssi')
            await create_settings_file(tiltObject.get('color', 'unknown'), tiltObject)
            response_builder.set_body_from_dict(tiltScanList)

        # try to serve static file
        #response_builder.serve_static_file(request.url, "/api_index.html")

        # build response message
        response_builder.build_response()
        # send reponse back to client
        writer.write(response_builder.response)
        # allow other tasks to run while data being sent
        await writer.drain()
        await writer.wait_closed()

    except OSError as e:
        print('connection error ' + str(e.errno) + " " + str(e))
        
# coroutine that will run as the neopixel update task
async def neopixels():

    counter = 0
    while True:
        if counter % 1000 == 0:
            counter = 0
        counter += 1
        # 0 second pause to allow other tasks to run
        await asyncio.sleep(0)

# main coroutine to boot async tasks
async def main():
    global config_files
    global tiltScanList
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
        await set_time_from_ntp()
        network_info = wlan.ifconfig()
        print('Connected to ' + network_info[0])
        ipAddr = ip_to_uint16(network_info[0])
        beacon.startiBeacon(ipAddr[0], ipAddr[1])
        wifiSettings == True
    # start web server task
    print('Setting up webserver...')
    server = asyncio.start_server(handle_request, "0.0.0.0", 80)
    asyncio.create_task(server)

    # start top 4 neopixel updating task
    asyncio.create_task(neopixels())

    # main task to control automatic logging
    counter = 0
    while True:
        if counter % 30000 == 0:
            led.toggle()
            await tiltscanner(1100, 'tilts')
            for tiltScan in tiltScanList:
                for config_file in os.listdir():
                    if config_file.startswith('config-'):
                        config = config_file[:-5]
                        if config.split('-')[2] == tiltColors[int(tiltScan.get('uuid', 'a495bb1')[6]) - 1]:
                            if tiltScan.get('minor', 'unknown') > 5000:
                                await logToCloud(tiltColors[int(tiltScan.get('uuid', 'a495bb1')[6]) - 1] + '-HD', config_file.split('-')[1], tiltScan)
                            else:
                                await logToCloud(tiltColors[int(tiltScan.get('uuid', 'a495bb1')[6]) - 1], config_file.split('-')[1], tiltScan)
            
            tiltScanList.clear()
        counter += 1
        # 0 second pause to allow other tasks to run
        await asyncio.sleep(0)


# start asyncio task and loop
try:
    # start the main async tasks
    asyncio.run(main())
finally:
    # reset and start a new event loop for the task scheduler
    asyncio.new_event_loop()
