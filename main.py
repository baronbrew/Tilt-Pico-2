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
import gc
from machine import Pin
led = Pin("LED", Pin.OUT)
led.value(0)
led_flash_interval = [5, False]
tiltScanList = []
targetTiltScan = {}
lastLogged = {}
SSID_complete = False
KEY_complete = False
SSID = ''
KEY = ''
tiltColors = [ 'RED', 'GREEN', 'BLACK', 'PURPLE', 'ORANGE', 'BLUE', 'YELLOW', 'PINK' ]

async def logToCloud(color, cloudinterval, passedTiltScan):
    global lastLogged
    print(lastLogged)
    # Only log if interval has passed
    for config_file in os.listdir():
        if config_file.startswith('config-'):
            config = config_file[:-5]
            if len(config.split('_')) == 1:
                if len(config.split('-')) == 3:
                    if config.split('-')[2] == color:
                        if lastLogged.get(color, 0) + int(config.split('-')[1]) * 60 >= time.time():
                            print(color + ' already logged within interval')
                            led.value(0)
                            return False
                elif len(config.split('-')) == 4:
                    if config.split('-')[2] + '-' + config.split('-')[3] == color: 
                        if lastLogged.get(color, 0) + int(config.split('-')[1]) * 60 >= time.time():
                            print(color + ' already logged within interval')
                            led.value(0)
                            return False
            elif len(config.split('_')) == 2:
                if lastLogged.get(color, 0) + int(config.split('-')[1]) * 60 >= time.time():
                            print(color + ' already logged within interval')
                            led.value(0)
                            return False
    try:
        with open('config-' + cloudinterval + '-' + color + '.json', 'r') as f:
         tiltAppData = ujson.load(f)
    except:
        print('couldnt open json settings file for color ' + color)
        led.value(0)
        return False
    excelTimeStamp = convertToExcelTime(int(passedTiltScan.get('timestamp', '0')), int(tiltAppData.get('timezoneoffsetsec', '0')))
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
    if lastLogged.get(color, 0) < 0:
        comment = 'P'
    else:
        comment = ''
    if len(color.split('_')) == 2:
        logColor = color.split('-')[0].split('_')[0] + ':' + color.split('_')[1].upper()
    else:
        logColor = color
    print('Timepoint=' + excelTimeStamp + '&SG=' + str(sg) + '&Temp=' + str(temp) + '&Color=' + logColor.split('-')[0] + '&Beer=' + tiltAppData.get('beername', 'unknown') + '&Comment=' + comment)
    cloudurls = tiltAppData.get('cloudurls', 'unknown').split(',')
    print(cloudurls)
    led.value(1)
    for cloudurl in cloudurls:
     if cloudurl is not '':
        while True:
            try:
                print("sending...")
                print(f"Free memory before HTTPS attempt: {gc.mem_free()} bytes")
                response = requests.post(cloudurl, headers = { "content-type" : 'application/x-www-form-urlencoded; charset=utf-8' }, data = 'Timepoint=' + excelTimeStamp + '&SG=' + str(sg) + '&Temp=' + str(temp) + '&Color=' + logColor.split('-')[0] + '&Beer=' + tiltAppData.get('beername', 'unknown') + '&Comment=' + comment)
                print(response.status_code)
                if response.status_code == 200:
                    print(response.text)  # Process the successful response
                elif response.status_code == 400:
                    print("Bad Request")
                else:
                    print(f"Error: HTTP {response.status_code}")  # Handle other errors
            except OSError as e:
                print(f"Error: Network issue or other error: {e}")
                asyncio.sleep(5)
                machine.soft_reset()
            finally:
                if 'response' in locals(): # check to see if response was defined. Prevents an error if the request failed before response was assigned.
                    response.close()  # Important: Close the response to free up resources
                lastLogged[color] = time.time()
                print(lastLogged)
                break
    led.value(0)

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
    
def convertToExcelTime(gmt_time, timeZoneOffsetSec):
    unixTimeStampLocal = gmt_time - timeZoneOffsetSec
    unixFractionOfDay = 115.74 * (unixTimeStampLocal - int(unixTimeStampLocal / 86400) * 86400)
    if unixFractionOfDay < 0:
        excelDayOnly = int((unixTimeStampLocal / 86400 + 25569) - 1)
        unixFractionOfDay += 10000000
    else:
        excelDayOnly = int(unixTimeStampLocal / 86400 + 25569)
    excelTimeStamp = str(excelDayOnly) + '.' + "{:07d}".format(int(unixFractionOfDay))
    return excelTimeStamp

def saveWiFi(SSID, KEY):
 jsonWiFi = { "SSID" : SSID, "KEY" : KEY }
 try:
  with open('wifi.json', 'w') as f:
   ujson.dump(jsonWiFi, f)
 except:
        print("Error! Could not save")
     

async def tiltscanner(SCANLENGTH, SCANFOR):
  global led_flash_interval
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
        if binascii.hexlify(result.adv_data[6:9]) == b'a495bc' and result.rssi > -70:
         led_flash_interval = [1, True]
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
          SSID = SSID.replace('\u0000', '')
          KEY = KEY.replace('\u0000', '')
          saveWiFi(SSID, KEY)
          led_flash_interval = [4, False]
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
          if len(tiltScanList) >= 16:
              break

async def create_settings_file(color, data):
  global tiltColors
  global targetTiltScan
  print(data)
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
                await asyncio.sleep(2)
                machine.reset()
        await asyncio.sleep_ms(10)

def delete_file(filename):
  try:
    os.remove(filename)
    print(f"File '{filename}' deleted successfully.")
    return True
  except OSError as e:
    print(f"Error deleting file '{filename}': {e}")
    return False

async def set_time_from_ntp(retries=10, delay=1):
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
    global led_flash_interval
    reset = False
    try:
        # allow other tasks to run while waiting for data
        raw_request = await reader.read(2048)

        request = RequestParser(raw_request)

        response_builder = ResponseBuilder()

        # filter out api request
        if request.url_match('/'):
            led.value(1)
            try: 
                await asyncio.wait_for(tiltscanner(1010, 'tilts'), timeout=2)    
            except asyncio.TimeoutError:
                print("tiltscanner timed out")
            tiltScanList = await sort_objects_by_key_value(tiltScanList, 'rssi')
            response_builder.set_body_from_dict(tiltScanList)
            tiltScanList.clear() 
        #print(raw_request)
        #print (request.query_string)
        elif request.url_match('/sync'):
            led.value(1)
            try: 
                await asyncio.wait_for(tiltscanner(1010, 'tilts'), timeout=2)    
            except asyncio.TimeoutError:
                print("tiltscanner timed out")
            tiltDataList = request.query_string.split('&')
            tiltObject = {}
            for data in tiltDataList:
                tiltObject[data.split('=')[0]] = data.split('=')[1]
            lastLogged[tiltObject.get('color', 'unknown')] = -900
            await create_settings_file(tiltObject.get('color', 'unknown'), tiltObject)
            tiltScanList = await sort_objects_by_key_value(tiltScanList, 'rssi')
            response_builder.set_body_from_dict(tiltScanList)
        elif request.url_match('/reset'):
            beacon.startiBeacon(999, 999)
            reset = delete_file('wifi.json')

        # try to serve static file
        #response_builder.serve_static_file(request.url, "/api_index.html")

        # build response message
        response_builder.build_response()
        # send reponse back to client
        writer.write(response_builder.response)
        # allow other tasks to run while data being sent
        await writer.drain()
        await writer.wait_closed()
        led.value(0)
        if reset:
            await asyncio.sleep(5)
            machine.soft_reset()

    except OSError as e:
        print('connection error ' + str(e.errno) + " " + str(e))
        
# coroutine that will run led flashing indicators
async def flash_led():
    global led_flash_interval
    counter = 0
    while True:
        if led_flash_interval[1]:
            if counter > led_flash_interval[0]:
                led.toggle()
                counter = 0
            counter += 1
            # 0 second pause to allow other tasks to run
            await asyncio.sleep_ms(50)
        await asyncio.sleep_ms(50)


async def getMac(config_file_prefix):
    try:
        with open(config_file_prefix + '.json', 'r') as f:
         tiltAppData = ujson.load(f)
    except:
        print('couldnt open json settings file')
        led.value(0)
        return False
    return tiltAppData.get('mac','unknown')

# main coroutine to boot async tasks
async def main():
    global led_flash_interval
    global config_files
    global tiltScanList
    global SSID_complete
    global KEY_complete
    global SSID
    global KEY
    try:
        with open('wifi.json', 'r') as f:
         data = ujson.load(f)
         SSID = data["SSID"]
         KEY = data["KEY"]
    except:
        led_flash_interval = [10, True]
        asyncio.create_task(flash_led())
        beacon.startiBeacon(999, 999)
        while not SSID_complete and not KEY_complete:
            print('Waiting for wifi SSID and KEY from app...')
            await tiltscanner(0, 'wifi_config')
    led_flash_interval = [10, False]
    led.value(0)
    beacon.stopiBeacon()
    # Connect to WLAN
    wlan = network.WLAN(network.STA_IF)
    wlan.active(True)
    if not wlan.isconnected():
        print(f"Connecting to {SSID}...")
        wlan.connect(SSID, KEY)  # Connect to the network
        # Wait for connection with timeout
        timeout = 20  # seconds
        for _ in range(timeout * 10):  # Check every 100ms
            if wlan.isconnected():
                break
            await asyncio.sleep_ms(100)  # Non-blocking delay
    if wlan.isconnected():
        print(f"Connected to {SSID}, syncing time with NTP")
        if not await set_time_from_ntp():
            beacon.startiBeacon(999, 998) # can't connect to NTP error beacon
            time.sleep(5)
            machine.reset()
        print("Connected to Wi-Fi")
        print(f"IP address: {wlan.ifconfig()}")  # Print the IP address
        ipAddr = ip_to_uint16(wlan.ifconfig()[0])
        beacon.startiBeacon(ipAddr[0], ipAddr[1])
        led.value(0)
    elif not wlan.isconnected():
        print("Connection failed, trying again.")
        timeout = 10  # seconds
        for _ in range(timeout * 10):  # Check every 100ms
            if wlan.isconnected():
                break
            await asyncio.sleep_ms(100)  # Non-blocking delay
        print("Still not connected, resetting") 
        beacon.startiBeacon(999, 997) #notify app
        if delete_file('wifi.json'):
                await asyncio.sleep(5)
                machine.reset()
    else:
        machine.reset()
        
    # start web server task
    print('Setting up webserver...')
    server = asyncio.start_server(handle_request, "0.0.0.0", 80)
    asyncio.create_task(server)

    # start updating task
    asyncio.create_task(reset_button_reader())

    # main task to control automatic logging
    counter = 0
    while True:
        if counter % 10000 == 0:
            try: 
                await asyncio.wait_for(tiltscanner(1010, 'tilts'), timeout=2)    
            except asyncio.TimeoutError:
                print("tiltscanner timed out")
            for tiltScan in tiltScanList:
                for config_file in os.listdir():
                    if config_file.startswith('config-'):
                        config = config_file[:-5]
                        configMac = await getMac(config)
                        if len(config.split('_')) == 1:
                            if config.split('-')[2] + configMac == tiltColors[int(tiltScan.get('uuid', 'a495bb1')[6]) - 1] + tiltScan.get('mac', 'unknown'):
                                if tiltScan.get('minor', 'unknown') > 5000:
                                    await logToCloud(tiltColors[int(tiltScan.get('uuid', 'a495bb1')[6]) - 1] + '-HD', config_file.split('-')[1], tiltScan)
                                else:
                                    await logToCloud(tiltColors[int(tiltScan.get('uuid', 'a495bb1')[6]) - 1], config_file.split('-')[1], tiltScan)
                        elif len(config.split('_')) == 2:
                            if config.split('_')[1] == tiltScan.get('mac', 'unknown'):
                                if tiltScan.get('minor', 'unknown') > 5000:
                                    await logToCloud(tiltColors[int(tiltScan.get('uuid', 'a495bb1')[6]) - 1] + '-HD' + '_' + tiltScan.get('mac', 'unknown'), config_file.split('-')[1], tiltScan) 
                                else:
                                    await logToCloud(tiltColors[int(tiltScan.get('uuid', 'a495bb1')[6]) - 1] + '_' + tiltScan.get('mac', 'unknown'), config_file.split('-')[1], tiltScan)
                tiltScanList.clear()
                counter = 0
        counter += 1
        # 0 second pause to allow other tasks to run
        await asyncio.sleep(0)
        led.value(0)


# start asyncio task and loop
try:
    # start the main async tasks
    asyncio.run(main())
finally:
    # reset and start a new event loop for the task scheduler
    asyncio.new_event_loop()
