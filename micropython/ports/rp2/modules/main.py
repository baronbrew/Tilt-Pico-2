# Reserve one contiguous block for TLS *before* anything else fragments the heap. Over time BLE
# scans, tasks and strings scatter long-lived objects so that e.g. 129KB is free but the largest
# free block is only ~7.5KB, and the HTTPS handshake (needs a ~16KB+ contiguous buffer) fails
# with ENOMEM. logToCloud releases this block right before each HTTPS post and re-takes it after.
import gc
TLS_RESERVE_BYTES = 32 * 1024

def alloc_high(size, chunk=2048):
    # Allocate a block near the TOP of the heap. The allocator is first-fit from the bottom, so
    # small objects created while the reserve is released (during a post) fill low holes first
    # and don't end up stranded inside this region, which would stop it being re-reserved.
    # Trick: temporarily fill free memory from the bottom with filler chunks, allocate, free filler.
    gc.collect()
    filler = []
    try:
        while gc.mem_free() > size + 4 * chunk:
            filler.append(bytearray(chunk))
    except MemoryError:
        pass
    try:
        block = bytearray(size)
    except MemoryError:
        block = None
    filler = None
    gc.collect()
    if block is None:
        block = bytearray(size)  # fall back to anywhere; raises MemoryError if no room at all
    return block

tls_reserve = alloc_high(TLS_RESERVE_BYTES)

from RequestParser import RequestParser
from ResponseBuilder import ResponseBuilder
import calibration
import beacon
import decrypt
from PacketReassembler import PacketReassembler
import network, socket, time
import ntptime
import requests
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
import rp2
import gc
import micropython
from machine import Pin
led = Pin("LED", Pin.OUT)
led.value(0)
led_flash_interval = [5, False]
tiltScanList = []          # one entry per Tilt (keyed by mac + uuid), newest first
TILT_MAX_ENTRIES = 16      # hard cap on Tilts kept in memory
TILT_EXPIRE_S = 120        # drop a Tilt not heard from in this many seconds
TILT_SCAN_MIN_GAP_MS = 5000  # skip a new BLE scan if the last one was this recent
last_tilt_scan_ms = None
targetTiltScan = {}
lastLogged = {}
SSID_complete = False
KEY_complete = False
wifi_config_scans = 0
SSID = ''
KEY = ''
tiltColors = [ 'RED', 'GREEN', 'BLACK', 'PURPLE', 'ORANGE', 'BLUE', 'YELLOW', 'PINK' ]
ENOMEM_RETRY_THRESHOLD = 3
consecutive_enomem_errors = 0
checkLoggingCounter = 4
checkConnectionCounter = 1
failed_checks = 0
pico_IP = '0.0.0.0'
TP_ver = 1009
pico_MAC = '00:00:00:00:00'
# Browser-like headers: some ISP gateways' security filters drop requests with no User-Agent
HTTP_HEADERS = {
    "Content-Type" : 'application/x-www-form-urlencoded; charset=utf-8',
    "User-Agent" : 'Mozilla/5.0 (compatible; TiltPico/' + str(TP_ver) + ')',
    "Accept" : '*/*',
    "Accept-Language" : 'en-US,en;q=0.9',
}
FALLBACK_DNS = '8.8.8.8'
# Where this boot's Wi-Fi credentials came from: 'saved' (wifi.json), 'backup' (wifi-backup.json,
# last known good) or 'app' (just received over BLE, not yet proven to work)
creds_source = 'saved'
# iBeacon minor advertised while saved credentials can't connect (router down) and the Pico is
# retrying while listening for new setup from the app. 999 (= needs setup) so the app offers
# Wi-Fi setup; the app will show "needs setup" during an outage, which is intended.
# (999/998 = NTP failed, 999/997 = recover_wifi in progress)
WIFI_WAIT_BEACON_MINOR = 999
# While waiting: listen (Wi-Fi off) for this long, then try to connect for this long
WIFI_WAIT_LISTEN_S = 45
WIFI_WAIT_CONNECT_S = 15
# Keep listening while setup packets from the app arrived within this many seconds
WIFI_SETUP_IDLE_S = 10
# Time allowed for newly received credentials to connect (same as a normal boot: 20s + 10s)
WIFI_NEW_CREDS_CONNECT_S = 30
# Set by tiltscanner: when the last setup packet from the app arrived, and when a full set is in
last_config_packet_ms = None
creds_received = False
# Clock: before the first NTP sync the Pico's clock reads 2021, so anything earlier than
# 2025-01-01 means "not set". Retry NTP every NTP_RETRY_S until set, then re-sync every
# NTP_RESYNC_S to correct crystal drift (~2-3 s/day).
MIN_VALID_TIME = 1735689600
NTP_RETRY_S = 30
NTP_RESYNC_S = 3600
# Connectivity check runs about once a minute. If Wi-Fi stays connected but the internet is
# unreachable for this many checks (~30 min), rejoin Wi-Fi (no reboot) in case the link is stale.
INTERNET_DOWN_REJOIN_CHECKS = 30
last_ntp_sync = 0

async def logToCloud(color, cloudinterval, passedTiltScan):
    global lastLogged
    global checkConnectionCounter
    global consecutive_enomem_errors
    if not clock_is_set():
        # Timestamps would be from 2021 (no NTP sync yet); time_keeper() will fix the clock
        print('Clock not synced yet, skipping log for ' + color)
        led.value(0)
        return False
    print(lastLogged)
    # Only log if interval has passed
    for config_file in os.listdir():
        if config_file.startswith('config-'):
            config = config_file[:-5]
            if len(config.split('_')) == 1:
                if len(config.split('-')) == 3:
                    if config.split('-')[2] == color:
                        if lastLogged.get(color, -900) + (int(config.split('-')[1]) - 0) * 60 >= time.time():
                            print(color + ' already logged within interval')
                            led.value(0)
                            gc.collect()
                            return False
                elif len(config.split('-')) == 4:
                    if config.split('-')[2] + '-' + config.split('-')[3] == color: 
                        if lastLogged.get(color, 0) + (int(config.split('-')[1]) - 0) * 60 >= time.time():
                            print(color + ' already logged within interval')
                            led.value(0)
                            gc.collect()
                            return False
            elif len(config.split('_')) == 2:
                if lastLogged.get(color, 0) + (int(config.split('-')[1]) - 0) * 60 >= time.time():
                            print(color + ' already logged within interval')
                            led.value(0)
                            gc.collect()
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
    #print('Timepoint=' + excelTimeStamp + '&SG=' + str(sg) + '&Temp=' + str(temp) + '&Color=' + logColor.split('-')[0] + '&Beer=' + tiltAppData.get('beername', 'unknown') + '&Comment=' + comment)
    cloudurls = tiltAppData.get('cloudurls', 'unknown').split(',')
    print(cloudurls)
    if cloudurls == ['', '', ''] and not tiltAppData.get('logLocally', 'false') == 'true':
        lastLogged[color + ' logging'] = False
        return
    else:
        lastLogged[color + ' logging'] = True
    led.value(1)
    if tiltAppData.get('logLocally', '') == 'true':
        time_sec = time.time() - int(tiltAppData.get('timezoneoffsetsec', '0'))
        time_tuple = time.localtime(time_sec)
        time_string = f"{time_tuple[0]}-{time_tuple[1]:02}-{time_tuple[2]:02} {time_tuple[3]:02}:{time_tuple[4]:02}"
        beername = url_decode(tiltAppData.get('beername', 'unknown'))
        log_to_csv('log.csv', [time_string, excelTimeStamp, str(round(sg,4)),str(round(temp,1)),logColor, beername.split(',')[0], comment], 200, ['Timestamp', 'Timepoint', 'SG', 'Temp', 'Color', 'Beer', 'Comment'])
        lastLogged[color] = time.time()
    if SSID == '' and KEY == '':
        return
    for cloudurl in cloudurls:
     if cloudurl != '':
        # NOTE: MicroPython's locals() returns the module globals, so the old
        # "'response' in locals()" check never closed the socket. Track it explicitly.
        response = None
        try:
            print("sending...")
            post_data = 'Timepoint=' + excelTimeStamp + '&SG=' + str(sg) + '&Temp=' + str(temp) + '&Color=' + logColor.split('-')[0] + '&Beer=' + tiltAppData.get('beername', 'unknown') + '&Comment=' + comment
            # The TLS handshake needs a large *contiguous* block: hand it the reserved block.
            # requests.post is blocking, so no other task can grab the gap before TLS does.
            release_tls_memory()
            print(f"Free memory before HTTPS attempt: {gc.mem_free()} bytes")
            # Pass a fresh copy: requests writes Host/Content-Length/Connection into the dict it's
            # given, so reusing HTTP_HEADERS would send the first post's Content-Length forever (HTTP 400).
            response = requests.post(cloudurl, headers = dict(HTTP_HEADERS), data = post_data, timeout = 30 )
            print(response.status_code)
            if response.status_code == 200 or response.status_code == 400:
                #print(response.text)
                checkConnectionCounter = 1
                consecutive_enomem_errors = 0
                lastLogged[color] = time.time()
                if 'success' in response.text.lower() or 'ok' in response.text.lower():
                    lastLogged[color + ' ' + cloudurl + ' result'] = 'success ' + str(time.time())
                elif response.status_code == 400:
                    #workaround for Google Sheets error
                    lastLogged[color + ' ' + cloudurl + ' result'] = 'success ' + str(time.time())
                else:
                    lastLogged[color + ' ' + cloudurl + ' result'] = 'success_not_in_resp ' + str(time.time())
            else:
                print(f"Error: HTTP {response.status_code}")  # Handle other errors
                lastLogged[color + ' ' + cloudurl + ' result'] = 'error_code_' + str(response.status_code) + ' ' + str(time.time())
                await asyncio.sleep(5)
        except OSError as e:
            print(f"Error: Network issue or other error: {e}")
            lastLogged[color + ' ' + cloudurl + ' result'] = 'error_code_' + str(e) + ' ' + str(time.time())
            if e.args and e.args[0] == 12:
                consecutive_enomem_errors += 1
                gc.collect()
                # Diagnose fragmentation: "max free sz" (in 16-byte blocks) is the largest
                # contiguous free block, which matters more than total free memory for TLS
                print(f"ENOMEM {consecutive_enomem_errors} of {ENOMEM_RETRY_THRESHOLD} (soft reset at {ENOMEM_RETRY_THRESHOLD}):")
                micropython.mem_info()
                if consecutive_enomem_errors >= ENOMEM_RETRY_THRESHOLD:
                    await asyncio.sleep(2)
                    machine.soft_reset()
            else:
                consecutive_enomem_errors = 0
        except Exception as e:
            print(f"Error: unexpected logging error: {e}")
            lastLogged[color + ' ' + cloudurl + ' result'] = 'error_' + str(e) + ' ' + str(time.time())
            consecutive_enomem_errors = 0
        finally:
            if response is not None:
                try:
                    response.close()  # Important: Close the response to free up the socket
                except Exception:
                    pass
            response = None
            reserve_tls_memory()  # take the block back now that TLS has freed it
            print(lastLogged)
    led.value(0)

def release_tls_memory():
    global tls_reserve
    tls_reserve = None
    gc.collect()

def reserve_tls_memory():
    global tls_reserve
    if tls_reserve is None:
        try:
            tls_reserve = alloc_high(TLS_RESERVE_BYTES)
        except MemoryError:
            # Heap too fragmented to get the block back; next post just relies on gc.collect()
            print("Could not re-reserve TLS memory block")
            micropython.mem_info()

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
    days_since_epoch = unixTimeStampLocal // 86400
    seconds_in_day   = unixTimeStampLocal -  days_since_epoch * 86400
    excelDayOnly = days_since_epoch + 25569
    fraction = (seconds_in_day * 10000000 + 43200) // 86400
    if fraction >= 10000000:
        fraction -= 10000000
        excelDayOnly += 1
    return "{}.{:07d}".format(excelDayOnly, fraction)

def saveWiFi(SSID, KEY):
 jsonWiFi = { "SSID" : SSID, "KEY" : KEY }
 try:
  with open('wifi.json', 'w') as f:
   ujson.dump(jsonWiFi, f)
 except:
        print("Error! Could not save")
     

async def tiltscanner(SCANLENGTH, SCANFOR):
  global SSID_complete
  global KEY_complete
  global last_tilt_scan_ms
  SSID_complete = False
  KEY_complete = False
  reassembler_1 = PacketReassembler()
  if SCANFOR == 'tilts':
      if last_tilt_scan_ms is not None and time.ticks_diff(time.ticks_ms(), last_tilt_scan_ms) < TILT_SCAN_MIN_GAP_MS:
          return False  # scanned moments ago; the current list is fresh enough
      last_tilt_scan_ms = time.ticks_ms()
      prune_tilt_list()
  try:
    await _run_scan(SCANLENGTH, SCANFOR, reassembler_1)
  finally:
    if SCANFOR == 'tilts':
      tiltScanList.sort(key=lambda t: t.get('timestamp', 0), reverse=True)  # newest first, sorted in place

def prune_tilt_list():
  # Drop Tilts not heard from within TILT_EXPIRE_S (removes in place, no new list).
  now = time.time()
  i = 0
  while i < len(tiltScanList):
      if now - tiltScanList[i].get('timestamp', 0) > TILT_EXPIRE_S:
          tiltScanList.pop(i)
      else:
          i += 1

def update_tilt_list(uuid, mac, major, minor, tx_power, rssi):
  # Update the existing entry for this Tilt in place (no duplicates, no new dict),
  # or add it, replacing the least recently seen Tilt if the list is full.
  now = time.time()
  for entry in tiltScanList:
      if entry.get('mac') == mac and entry.get('uuid') == uuid:
          entry['major'] = major
          entry['minor'] = minor
          entry['tx_power'] = tx_power
          entry['rssi'] = rssi
          entry['timestamp'] = now
          return
  if len(tiltScanList) >= TILT_MAX_ENTRIES:
      oldest = 0
      for i in range(1, len(tiltScanList)):
          if tiltScanList[i].get('timestamp', 0) < tiltScanList[oldest].get('timestamp', 0):
              oldest = i
      tiltScanList.pop(oldest)
  tiltScanList.append({ "uuid" : uuid, "mac" : mac, "major" : major, "minor" : minor, "tx_power" : tx_power, "rssi" : rssi, "timestamp" : now })

async def _run_scan(SCANLENGTH, SCANFOR, reassembler_1):
  global led_flash_interval
  global SSID_complete
  global KEY_complete
  global SSID
  global KEY
  global wifi_config_scans
  global creds_source
  global last_config_packet_ms
  global creds_received
  Part1_complete = False
  Part2_complete = False
  reassembled_bytes_1 = None
  async with aioble.scan(SCANLENGTH, interval_us=1000*1000, window_us=1000*1000, active=False) as scanner:
    async for result in scanner:
        if binascii.hexlify(result.adv_data[9:11]) == b'a495' or binascii.hexlify(result.adv_data[6:8]) == b'a495':
            if SCANFOR == 'wifi_config':
                if wifi_config_scans > 2000:
                    wifi_config_scans = 0
                    try:
                        with open('wifi-backup.json', 'r') as f:
                            data = ujson.load(f)
                            SSID = data["SSID"]
                            KEY = data["KEY"]
                            SSID_complete = True
                            KEY_complete = True
                            creds_source = 'backup'
                            saveWiFi(SSID, KEY)  # restore wifi.json too, so a reboot doesn't land back in setup mode
                            led_flash_interval = [4, False]
                            break
                    except:
                        print('no WiFi backup file available, will continue to wait for app')
                        break
                wifi_config_scans += 1
                if binascii.hexlify(result.adv_data[9:12]) == b'a495bc' and not binascii.hexlify(result.adv_data[9:13]) == b'a495bc02' or binascii.hexlify(result.adv_data[6:9]) == b'a495bc' and not binascii.hexlify(result.adv_data[9:13]) == b'a495bc02':
                 wifi_config_scans = 0
                 offSet = 0
                 if binascii.hexlify(result.adv_data[9:12]) == b'a495bc':
                  offSet = 3
                 led_flash_interval = [1, True]
                 last_config_packet_ms = time.ticks_ms()  # app is mid-transfer: don't interrupt listening
                 major = int(binascii.hexlify(result.adv_data[22  + offSet : 24  + offSet]), 16)
                 minor = int(binascii.hexlify(result.adv_data[24  + offSet : 26  + offSet]), 16)
                 hex_str = binascii.hexlify(result.adv_data[10  + offSet : 22  + offSet]).decode('utf-8')
                 hex_bytes = binascii.hexlify(result.adv_data[10  + offSet : 22  + offSet])
                 if binascii.hexlify(result.adv_data[6 + offSet : 10 + offSet]) == b'a495bc00' and not SSID_complete:
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
                 if binascii.hexlify(result.adv_data[6 + offSet : 10 + offSet]) == b'a495bc01' and not KEY_complete:
                    reassembled_bytes_1 = reassembler_1.add_packet(hex_bytes, minor, major)
                    if reassembled_bytes_1 is not None:
                      KEY = bytes.fromhex(reassembled_bytes_1).decode('utf-8')
                      print(KEY)
                      KEY_complete = True
                    else:
                      gc.collect()
                 if SSID_complete and KEY_complete:
                    SSID = SSID.replace('\u0000', '')
                    KEY = KEY.replace('\u0000', '')
                    saveWiFi(SSID, KEY)
                    creds_source = 'app'
                    creds_received = True
                    led_flash_interval = [4, False]
                    break
            elif SCANFOR == 'tilts':
                if binascii.hexlify(result.adv_data[9:12]) == b'a495bb' and binascii.hexlify(result.adv_data[13:25]) == b'c5b14b44b5121370f02d74de' or binascii.hexlify(result.adv_data[6:9]) == b'a495bb' and binascii.hexlify(result.adv_data[10:22]) == b'c5b14b44b5121370f02d74de':
                      offSet = 0
                      if binascii.hexlify(result.adv_data[6:9]) == b'a495bb':
                        offSet = -3
                      UUID = str(binascii.hexlify(result.adv_data[9 + offSet : 25 + offSet]).decode())
                      MAC = str(binascii.hexlify(result.device.addr).decode())
                      MAJOR = int(binascii.hexlify(result.adv_data[ 25 + offSet : 27 + offSet ]), 16)
                      MINOR = int(binascii.hexlify(result.adv_data[ 27 + offSet : 29 + offSet ]), 16)
                      TX_POWER = str(int(binascii.hexlify(result.adv_data[ 29 + offSet : 31 + offSet ]), 16))
                      update_tilt_list(UUID, MAC, MAJOR, MINOR, TX_POWER, result.rssi)

async def create_settings_file(color, data, targetTiltScan):
  global tiltColors
  print(color, data['color'], targetTiltScan['uuid'])
  data['mac'] = targetTiltScan.get('mac', 'unknown')
  if data['mac'] == 'unknown':
      if len(color.split('_')) == 2:
          data['mac'] = color.split('_')[1]
  if targetTiltScan.get('minor', 0) > 5000:
      data['sg'] = targetTiltScan.get('minor', 1000) / 10000
      data['temp'] = targetTiltScan.get('major', 0) / 10
  else:
      data['sg'] = targetTiltScan.get('minor', 1000) / 1000
      data['temp'] = targetTiltScan.get('major', 0)
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
    with open('config-' + data['cloudinterval'] + '-' + data['color'] + '.json', 'w') as f:
      f.write(ujson.dumps(data))
    print(f'File "{data['color']}" created successfully.')
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
            delete_file('wifi.json')
            delete_file('wifi-backup.json')
            await asyncio.sleep(2)
            p = machine.Pin(23, machine.Pin.OUT)
            p.value(0)
            time.sleep(2)
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

def clock_is_set():
    return time.time() > MIN_VALID_TIME

async def set_time_from_ntp(retries=3, delay=2):
    # Sync the clock once (with a few quick retries). Never resets on failure: time_keeper()
    # keeps retrying in the background.
    global tiltScanList, last_ntp_sync, last_tilt_scan_ms
    was_set = clock_is_set()
    for attempt in range(1, retries + 1):
        try:
            ntptime.host = "pool.ntp.org"  # Or your preferred NTP server
            ntptime.settime()
            last_ntp_sync = time.time()
            print(f"Clock synced via NTP: {time.localtime()}")
            if not was_set:
                # First sync jumps the clock forward from 2021, which would make every
                # entry look years old. Clear the list (and allow an immediate rescan).
                tiltScanList.clear()
                last_tilt_scan_ms = None
            return True
        except Exception as e:  # OSError (no internet / DNS) or a malformed reply
            print(f"NTP sync failed (attempt {attempt}/{retries}): {e}")
            if attempt < retries:
                await asyncio.sleep(delay)  # don't block BLE / web server while waiting
    return False

async def time_keeper():
    # Background task. Covers (1) Wi-Fi up before the internet after a power outage: keep
    # retrying until the first sync succeeds, and (2) clock drift: re-sync periodically.
    while True:
        if clock_is_set() and time.time() - last_ntp_sync < NTP_RESYNC_S:
            await asyncio.sleep(60)
            continue
        if network.WLAN(network.STA_IF).isconnected():
            if not clock_is_set():
                ensure_dns()  # DNS may have been unreachable at boot too
            # one try per pass: ntptime blocks for up to ~1s per attempt
            if not await set_time_from_ntp(retries=1):
                await asyncio.sleep(NTP_RETRY_S)
        else:
            await asyncio.sleep(NTP_RETRY_S)





# coroutine to handle HTTP request
async def handle_request(reader, writer):
    global tiltScanList
    global led_flash_interval
    global TP_ver
    global checkConnectionCounter
    global checkLoggingCounter  # /sync sets this to 5 so the next loggingController pass logs immediately
    reset = False
    try:
        # allow other tasks to run while waiting for data
        raw_request = await reader.read(2048)
        request = RequestParser(raw_request)
        response_builder = ResponseBuilder()
        checkConnectionCounter = 1

        # filter out api request
        if request.url_match('/'):
            led.value(1)
            try: 
                await asyncio.wait_for(tiltscanner(1010, 'tilts'), timeout=2)    
            except asyncio.TimeoutError:
                print("tiltscanner timed out")
            response_builder.set_body_from_dict(tiltScanList)
            #print(raw_request)
        elif request.url_match('/sync'):
            led.value(1)
            tiltDataList = request.query_string.split('&')
            #print (tiltDataList)
            tiltObject = {}
            for data in tiltDataList:
                if len(data.split('=')) > 2:
                    dataKey = data.split('=')[0]
                    newData = data.replace(dataKey + '=','')
                    tiltObject[dataKey] = newData
                    #print(tiltObject) #for brewfather url with = sign
                else:
                    tiltObject[data.split('=')[0]] = data.split('=')[1]
            lastLogged[tiltObject.get('color', 'unknown')] = -900
            print(lastLogged)
            try: 
                await asyncio.wait_for(tiltscanner(3030, 'tilts'), timeout=4)
                status = 'success: scanning finished'
            except asyncio.TimeoutError:
                status = 'fail: scanning timed out'
            returnedTiltScanList = tiltScanList
            print([status,len(returnedTiltScanList)])
            if status == 'success: scanning finished' or len(returnedTiltScanList) > 0:
              for tiltScan in returnedTiltScanList:
                if tiltScan.get('minor', 0) < 5000 and len(tiltObject.get('color', 'unknown').split('-')) == 1:
                    print(tiltScan.get('mac', 'unknown') + ' ' + tiltObject.get('mac', 'unknown'))
                    if tiltColors[int(tiltScan.get('uuid', 'a495bb1')[6]) - 1] == tiltObject.get('color', 'unknown'):
                        status = 'success: found target color ' + tiltObject.get('color', 'unknown') + ' in scan'
                        await create_settings_file(tiltObject.get('color', 'unknown'), tiltObject, tiltScan)
                        checkLoggingCounter = 5
                        break
                    elif tiltScan.get('mac', 'unknown') == tiltObject.get('mac', 'unknown'):
                        status = 'success: found target color ' + tiltObject.get('color', 'unknown') + ' in scan'
                        await create_settings_file(tiltObject.get('color', 'unknown'), tiltObject, tiltScan)
                        checkLoggingCounter = 5
                        break
                    else:
                        status = 'fail: color ' + tiltObject.get('color', 'unknown') + ' not found in scan'
                        #client should try scanning again
                elif tiltScan.get('minor', 0) >= 5000 and len(tiltObject.get('color', 'unknown').split('-')) == 2:
                    if tiltColors[int(tiltScan.get('uuid', 'a495bb1')[6]) - 1] + '-HD' == tiltObject.get('color', 'unknown'):
                        status = 'success: found target color ' + tiltObject.get('color', 'unknown') + ' in scan'
                        await create_settings_file(tiltObject.get('color', 'unknown'), tiltObject, tiltScan)
                        checkLoggingCounter = 5
                        break
                    elif tiltScan.get('mac', 'unknown') == tiltObject.get('mac', 'unknown'):
                        status = 'success: found target color ' + tiltObject.get('color', 'unknown') + ' in scan'
                        await create_settings_file(tiltObject.get('color', 'unknown'), tiltObject, tiltScan)
                        checkLoggingCounter = 5
                        break
                    else:
                        status = 'fail: color ' + tiltObject.get('color', 'unknown') + ' not found in scan'
                        #client should try scanning again
            response_builder.set_body_from_dict({ 'status' : status})
        elif request.url_match('/reset'):
            beacon.startiBeacon(999, 999)
            reset = delete_file('wifi.json')
            reset = delete_file('wifi-backup.json')
        elif request.url_match('/lastlogged'):
            response_builder.set_body_from_dict(lastLogged)
        elif request.url_match('/remove_config_file'):
            tiltColorRequested = request.query_string.split('=')[1]
            for config_file in os.listdir():
                if config_file.startswith('config-'):
                    if config_file[10:-5] == tiltColorRequested:
                        delete_file(config_file)
                        response_builder.set_body_from_dict({ 'result' : 'Success: ' + config_file + ' removed'})
                        lastLogged[tiltColorRequested + ' logging'] = False
                    elif tiltColorRequested == 'all':
                        delete_file(config_file)
                        lastLogged[tiltColorRequested + ' logging'] = False
            if tiltColorRequested == 'all':
                response_builder.set_body_from_dict({ 'result' : 'Success: all colors removed'})
        elif request.url_match('/remove_log_file'):
            try:
                os.stat('log.csv')
                if delete_file('log.csv'):
                    response_builder.set_body_from_dict({ 'result' : 'Success: log.csv removed'})
                else:
                    response_builder.set_body_from_dict({ 'result' : 'Fail: log.csv not removed'})
            except:
                response_builder.set_body_from_dict({ 'result' : 'Fail: log.csv not found'})
        elif request.url_match('/log.csv'):
            try:
                file_size = os.stat("log.csv")[6]
            except OSError:
                # If file doesn't exist, send a 404 Not Found error
                writer.write(b'HTTP/1.0 404 Not Found\r\n\r\nFile not found.')
                await writer.drain()
                writer.close()
                await writer.wait_closed()
                print("Client disconnected, file not found.")
                return

            # These headers tell the browser to download the file as 'log.csv'
            writer.write(b'HTTP/1.0 200 OK\r\n')
            writer.write(b'Content-Type: text/csv\r\n')
            writer.write(f'Content-Length: {file_size}\r\n'.encode('utf-8'))
            writer.write(b'Content-Disposition: attachment; filename="log.csv"\r\n')
            writer.write(b'\r\n') # An empty line is required to end the headers
            await writer.drain() # Wait for the headers to be sent

            # --- Stream the raw CSV file ---
            # This method is memory-efficient and reads the file in small chunks
            with open("log.csv", "rb") as f:
                while True:
                    chunk = f.read(1024) # Read 1KB at a time
                    if not chunk:
                        break # End of file
                    writer.write(chunk)
                    await writer.drain() # Wait for the chunk to be sent
            
            writer.close()
            await writer.wait_closed()
            print("Client disconnected, file sent.")
            led.value(0)
            return
        elif request.url_match('/info'):
            temp_f = get_pico_temperature()
            config_files = []
            for config_file in os.listdir():
                if config_file.startswith('config-'):
                    config_files.append(config_file)
            response_builder.set_body_from_dict({'ip_address' : pico_IP, 'tilt_pico_version' : TP_ver,'tilt_pico_temperature_f' : temp_f, 'tilt_pico_mac_address' : pico_MAC, 'tilt_pico_configuration_files' : config_files, 'clock_synced' : clock_is_set(), 'last_time_sync' : last_ntp_sync })
        # try to serve static file
        else:
            response_builder.serve_static_file(request.url)
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
            p = machine.Pin(23, machine.Pin.OUT)
            p.value(0)
            time.sleep(2)
            machine.reset()
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

def copy_file(source_path, destination_path):
    global SSID
    global KEY
    try:
        with open(source_path, 'rb') as source_file:
            with open(destination_path, 'wb') as destination_file:
                while True:
                    chunk = source_file.read(512)  # Read in chunks (e.g., 512 bytes)
                    if not chunk:
                        break
                    destination_file.write(chunk)
        print(f"File '{source_path}' copied to '{destination_path}' successfully.")
    except Exception as e:
        print(f"Error copying file: {e}, will save wifi.json instead")
        saveWiFi(SSID, KEY)

def log_to_csv(filename: str, data: list, max_size_kb: int = 180, header: list = None):
    max_bytes = max_size_kb * 1024
    line_to_add = ','.join(map(str, data)) + '\n'
    line_to_add_bytes = len(line_to_add.encode('utf-8'))

    file_exists = False
    file_size = 0
    try:
        file_size = os.stat(filename)[6]
        file_exists = True
    except OSError:
        pass

    if not file_exists and header:
        header_line = ','.join(map(str, header)) + '\n'
        with open(filename, 'w') as f:
            f.write(header_line)
        file_size = os.stat(filename)[6]

    if file_size + line_to_add_bytes > max_bytes:
        # Trim down to 75% of the cap (not just under it) so the full-file rewrite happens
        # once every few hundred rows instead of on every row: far less flash wear.
        temp_filename = filename + '.tmp'
        bytes_to_trim = (file_size + line_to_add_bytes) - (max_bytes * 3 // 4)
        bytes_trimmed = 0

        try:
            with open(filename, 'r') as f_in, open(temp_filename, 'w') as f_out:
                # --- MODIFICATION START ---
                # 1. Read the header from the original file.
                header_line = f_in.readline()

                # 2. Immediately write the header to the new temporary file.
                f_out.write(header_line)

                # 3. Now, loop through the rest of the lines (the data) to trim them.
                for data_line in f_in:
                    if bytes_trimmed < bytes_to_trim:
                        bytes_trimmed += len(data_line.encode('utf-8'))
                        continue # Skip this old data line
                    f_out.write(data_line)
                # --- MODIFICATION END ---
            
            os.remove(filename)
            os.rename(temp_filename, filename)
        except OSError as e:
            print(f"Error during file trimming: {e}")
            try:
                os.remove(temp_filename)
            except OSError:
                pass
            return

    try:
        with open(filename, 'a') as f:
            f.write(line_to_add)
    except OSError as e:
        print(f"Error writing to file: {e}")

def url_decode(s):
    decoded_chars = []
    i = 0
    while i < len(s):
        char = s[i]
        if char == '+':
            decoded_chars.append(' ')
            i += 1
        elif char == '%':
            hex_code = s[i+1:i+3]
            try:
                decoded_chars.append(chr(int(hex_code, 16)))
                i += 3
            except ValueError:
                decoded_chars.append('%')
                i += 1
        else:
            decoded_chars.append(char)
            i += 1
    return "".join(decoded_chars)

async def loggingController(period = 5, scanlength = 3030):
    global checkLoggingCounter
    if checkLoggingCounter % 5 == 0:
        try: 
            await asyncio.wait_for(tiltscanner(scanlength, 'tilts'), timeout=4)    
        except asyncio.TimeoutError:
            print("tiltscanner timed out")
        savedTiltScanList = tiltScanList[:]
        for tiltScan in savedTiltScanList:
            for config_file in os.listdir():
                if config_file.startswith('config-'):
                    config = config_file[:-5]
                    configMac = await getMac(config)
                    if len(config.split('_')) == 1:
                        if config.split('-')[2] + configMac == tiltColors[int(tiltScan.get('uuid', 'a495bb1')[6]) - 1] + tiltScan.get('mac', 'unknown'):
                            if tiltScan.get('minor', 'unknown') > 5000:
                                print(f"Free memory before check logging: {gc.mem_free()} bytes")
                                await logToCloud(tiltColors[int(tiltScan.get('uuid', 'a495bb1')[6]) - 1] + '-HD', config_file.split('-')[1], tiltScan)
                            else:
                                print(f"Free memory before check logging: {gc.mem_free()} bytes")
                                await logToCloud(tiltColors[int(tiltScan.get('uuid', 'a495bb1')[6]) - 1], config_file.split('-')[1], tiltScan)
                    elif len(config.split('_')) == 2:
                        if config.split('_')[1] == tiltScan.get('mac', 'unknown'):
                            if tiltScan.get('minor', 'unknown') > 5000:
                                print(f"Free memory before check logging: {gc.mem_free()} bytes")
                                await logToCloud(tiltColors[int(tiltScan.get('uuid', 'a495bb1')[6]) - 1] + '-HD' + '_' + tiltScan.get('mac', 'unknown'), config_file.split('-')[1], tiltScan) 
                            else:
                                print(f"Free memory before check logging: {gc.mem_free()} bytes")
                                await logToCloud(tiltColors[int(tiltScan.get('uuid', 'a495bb1')[6]) - 1] + '_' + tiltScan.get('mac', 'unknown'), config_file.split('-')[1], tiltScan)
            checkLoggingCounter = 0
    checkLoggingCounter += 1
    # 0 second pause to allow other tasks to run
    await asyncio.sleep(period)
    led.value(0)

def get_pico_temperature():
    sensor_temp = machine.ADC(4)
    conversion_factor = 3.3 / (65535)
    reading = sensor_temp.read_u16() * conversion_factor
    temperature_celsius = 27 - (reading - 0.706) / 0.001721
    temperature_fahrenheit = (temperature_celsius * 1.8) + 32
    return round(temperature_fahrenheit, 1)

def get_pico_mac_address():
    wlan = network.WLAN(network.STA_IF)
    wlan.active(True)
    mac_bytes = wlan.config('mac')
    return binascii.hexlify(mac_bytes, ':').decode().upper()

def ensure_dns(test_host='pool.ntp.org'):
    # Some ISP gateways (e.g. Verizon) run a local DNS proxy that intermittently fails
    # for IoT clients. Only if lookup through the DHCP-provided DNS fails, switch to a
    # public resolver. network.ipconfig(dns=) changes DNS without disabling DHCP
    # (unlike wlan.ifconfig((...)), which would pin a static IP and stop lease renewal).
    try:
        socket.getaddrinfo(test_host, 123)
        print('DNS OK via current server')
        return True
    except OSError as e:
        print(f'DNS lookup failed ({e}), trying fallback DNS {FALLBACK_DNS}')
    original_dns = None
    try:
        original_dns = network.ipconfig('dns')
        network.ipconfig(dns=FALLBACK_DNS)
        socket.getaddrinfo(test_host, 123)
        print('DNS OK via fallback server')
        return True
    except Exception as e:
        # Both failed - most likely the internet itself is down (e.g. modem still booting).
        # Go back to the router's DNS rather than pinning the fallback for no reason.
        print(f'Fallback DNS also failed: {e}; keeping router DNS')
        if original_dns:
            try:
                network.ipconfig(dns=original_dns)
            except Exception:
                pass
        return False

import machine
import time
import network

def broadcast_ip(wlan):
    # Advertise the Pico's IP to the app over iBeacon; only meaningful once DHCP has assigned one
    global pico_IP
    pico_IP = wlan.ifconfig()[0]
    ipAddr = ip_to_uint16(pico_IP)
    if ipAddr is not None and pico_IP != '0.0.0.0':
        beacon.startiBeacon(ipAddr[0], ipAddr[1])

def recover_wifi(ssid, password, max_attempts=3):
    for attempt in range(max_attempts):
        print(f"Recovery attempt {attempt + 1}/{max_attempts}")
        wlan = network.WLAN(network.STA_IF)
        networks_found = len(wlan.scan())  # scan once; each scan blocks for ~2s
        print(f"networks available: {networks_found}")
        if networks_found > 0:
            beacon.startiBeacon(999, 997) #notify app with iBeacon if possible
        if attempt == 0:           # Level 1: Normal reconnect
            wlan.connect(ssid, password)
        elif attempt == 1:         # Level 2: Soft WiFi reset
            wlan.active(False)
            time.sleep(1)
            wlan.active(True)
            time.sleep(1)
            wlan.connect(ssid, password)
        else:                     # Level 3: Full power cycle
            p = machine.Pin(23, machine.Pin.OUT)
            p.value(0)
            time.sleep(2)
            machine.reset()                # Force a clean reboot after power cycle
        
        # Check if connected
        start = time.time()
        while time.time() - start < 12:
            if wlan.isconnected():
                print("Successfully reconnected!")
                broadcast_ip(wlan)  # previously sent before connecting, which advertised 0.0.0.0
                return True
            time.sleep(1)
    
    print("Recovery failed")
    return False

async def finish_wifi_setup(wlan):
    # Runs once Wi-Fi is up (first try or after recover_wifi): DNS check, clock sync, IP beacon
    print(f"Connected to {SSID}, checking DNS")
    ensure_dns()
    print("syncing time with NTP")
    if not await set_time_from_ntp():
        # e.g. Wi-Fi came back before the modem after a power outage. Previously this
        # soft-reset in a loop; now time_keeper() retries and logging waits for the clock.
        print(f"NTP sync failed; retrying every {NTP_RETRY_S}s in the background, logging paused until then")
    print("Connected to Wi-Fi")
    persist_wifi_credentials()
    broadcast_ip(wlan)
    print(f"IP address: {pico_IP}")  # Print the IP address

def file_exists(filename):
    try:
        os.stat(filename)
        return True
    except OSError:
        return False

def persist_wifi_credentials():
    # Credentials just proved good, so make sure both copies exist. Previously the backup was
    # only written when credentials came from the app in this boot, and a successful
    # recover_wifi() left wifi.json deleted - so a router outage could strand the Pico
    # waiting for the app with nothing to restore from.
    if not file_exists('wifi.json'):
        saveWiFi(SSID, KEY)
    if creds_source == 'app' or not file_exists('wifi-backup.json'):
        copy_file('wifi.json', 'wifi-backup.json')

async def try_wifi_connect(wlan, ssid, password, timeout_s):
    # Wi-Fi is only switched on while connecting; otherwise it stays off so BLE has the radio
    wlan.active(True)
    wlan.config(pm=0)
    wlan.connect(ssid, password)
    for _ in range(timeout_s * 10):
        if wlan.isconnected():
            return True
        await asyncio.sleep_ms(100)
    print(f"Could not connect to '{ssid}' (status {wlan.status()})")
    wlan.disconnect()  # abort the background join before turning Wi-Fi off
    wlan.active(False)
    await asyncio.sleep_ms(200)
    return False

async def listen_for_app_credentials(min_listen_s):
    # Listen (Wi-Fi off) for credentials from the app for at least min_listen_s, and never cut
    # off a transfer in progress: keep listening while setup packets keep arriving.
    # Returns True if a complete new set arrived (already saved to wifi.json by tiltscanner).
    global SSID, KEY, wifi_config_scans, last_config_packet_ms, creds_received
    # tiltscanner builds multi-part SSIDs by appending to the global, so start from empty
    saved_ssid, saved_key = SSID, KEY
    SSID, KEY = '', ''
    wifi_config_scans = 0  # don't let the scanner fall back to wifi-backup.json mid-wait
    last_config_packet_ms = None
    creds_received = False
    start = time.ticks_ms()
    task = asyncio.create_task(tiltscanner(0, 'wifi_config'))
    while not creds_received:
        await asyncio.sleep_ms(250)
        now = time.ticks_ms()
        receiving = last_config_packet_ms is not None and time.ticks_diff(now, last_config_packet_ms) < WIFI_SETUP_IDLE_S * 1000
        if not receiving and time.ticks_diff(now, start) >= min_listen_s * 1000:
            break
        if task.done() and not creds_received:
            # scanner returned early without credentials; keep listening
            task = asyncio.create_task(tiltscanner(0, 'wifi_config'))
    if not task.done():
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass
    if creds_received:
        return True
    if last_config_packet_ms is not None:
        print("Setup from app started but did not complete")
    SSID, KEY = saved_ssid, saved_key
    return False

async def wait_for_wifi_or_new_credentials(wlan, password):
    # Saved credentials have connected before, so failing now most likely means the router is
    # down (power outage, gateway rebooting). Keep them and keep retrying, but between retries
    # listen for new credentials from the app so the user can still set up a different network.
    # Returns the (decrypted) password that finally connected.
    #
    # Wi-Fi and BLE share the CYW43 chip and antenna. (Re)activating BLE while a Wi-Fi join is in
    # progress can hang the chip, and an active join/scan for a missing AP starves BLE airtime so
    # the app can't see the beacon or deliver credentials. So listening runs with Wi-Fi fully
    # off - the same conditions as first-time setup mode - and reconnect attempts are suspended
    # while the app is sending.
    global SSID, KEY, creds_source, led_flash_interval
    wlan.disconnect()
    wlan.active(False)
    await asyncio.sleep_ms(500)
    print(f"Wi-Fi '{SSID}' unavailable: advertising 999/{WIFI_WAIT_BEACON_MINOR} and listening for setup from app")
    beacon.startiBeacon(999, WIFI_WAIT_BEACON_MINOR)
    attempt = 0
    while True:
        # Re-assert every cycle: tiltscanner switches blinking off when it receives credentials
        led_flash_interval = [10, True]
        old_ssid, old_key, old_source = SSID, KEY, creds_source
        print(f"Listening {WIFI_WAIT_LISTEN_S}s for Wi-Fi setup from app (Wi-Fi off)")
        if await listen_for_app_credentials(WIFI_WAIT_LISTEN_S):
            print(f"New Wi-Fi credentials received from app for '{SSID}', connecting")
            new_password = decrypt.decrypt_aes_cbc(KEY)
            if await try_wifi_connect(wlan, SSID, new_password, WIFI_NEW_CREDS_CONNECT_S):
                print("Connected with new credentials")
                led_flash_interval = [10, False]
                led.value(0)
                return new_password
            # Most likely a typo: keep the last good network and go straight back to listening
            # so the user can resend from the app
            print(f"New credentials failed; keeping '{old_ssid}' and listening again")
            SSID, KEY, creds_source = old_ssid, old_key, old_source
            saveWiFi(SSID, KEY)
            continue
        attempt += 1
        print(f"Retry {attempt}: connecting to '{SSID}'")
        if await try_wifi_connect(wlan, SSID, password, WIFI_WAIT_CONNECT_S):
            print("Wi-Fi is back")
            led_flash_interval = [10, False]
            led.value(0)
            return password

# main coroutine to boot async tasks
async def main():
    global led_flash_interval
    global config_files
    global tiltScanList
    global SSID_complete
    global KEY_complete
    global SSID
    global KEY
    global wifi_config_scans
    global pico_IP
    global pico_MAC
    global checkConnectionCounter
    global failed_checks
    # start updating task
    asyncio.create_task(reset_button_reader())
    # LED blink task runs for the whole session; it only blinks while led_flash_interval[1] is True
    # (= waiting for Wi-Fi credentials / not connected)
    asyncio.create_task(flash_led())
    try:
        with open('wifi.json', 'r') as f:
         data = ujson.load(f)
         SSID = data["SSID"]
         KEY = data["KEY"]
    except:
        led_flash_interval = [10, True]
        beacon.startiBeacon(999, 999)
        wifi_config_scans = 2000
        while not SSID_complete and not KEY_complete:
            print('Waiting for wifi SSID and KEY from app...')
            await loggingController()
            await tiltscanner(0, 'wifi_config')
            await asyncio.sleep_ms(100)
    led_flash_interval = [10, False]
    led.value(0)
    beacon.stopiBeacon()
    # Connect to WLAN
    wlan = network.WLAN(network.STA_IF)
    wlan.active(True)
    wlan.config(pm=0)
    mac_bytes = wlan.config('mac')
    pico_MAC = binascii.hexlify(mac_bytes, ':').decode().upper()
    decryptedKEY = decrypt.decrypt_aes_cbc(KEY)
    if not wlan.isconnected():
        print(f"Connecting to {SSID}...")
        wlan.connect(SSID, decryptedKEY)  # Connect to the network
        # Wait for connection with timeout
        timeout = 20  # seconds
        for _ in range(timeout * 10):  # Check every 100ms
            if wlan.isconnected():
                break
            await asyncio.sleep_ms(100)  # Non-blocking delay
    if wlan.isconnected():
        beacon.stopiBeacon()
        await finish_wifi_setup(wlan)
        led.value(0)
    else:
        beacon.stopiBeacon()
        print("Connection failed, trying again.")
        timeout = 10  # seconds
        for _ in range(timeout * 10):  # Check every 100ms
            if wlan.isconnected():
                break
            await asyncio.sleep_ms(100)  # Non-blocking delay
        if wlan.isconnected():
            # Connected during the extra wait: don't delete wifi.json or force recovery
            await finish_wifi_setup(wlan)
        elif creds_source == 'app':
            # Credentials just entered in the app have never worked (most likely a typo): drop
            # them and go back to setup mode. On reboot the last good network, if any, is
            # restored from wifi-backup.json.
            print(f"New credentials for {SSID} failed (status {wlan.status()}), returning to setup mode")
            delete_file('wifi.json')
            await asyncio.sleep(2)
            p = machine.Pin(23, machine.Pin.OUT)
            p.value(0)
            time.sleep(2)
            machine.reset()
        else:
            # Saved credentials that worked before: never delete them just because the network
            # is down. Retry until it's back (or the user sends new credentials from the app).
            decryptedKEY = await wait_for_wifi_or_new_credentials(wlan, decryptedKEY)
            await finish_wifi_setup(wlan)

    # start web server task
    print('Setting up webserver...')
    server = asyncio.start_server(handle_request, "0.0.0.0", 80)
    asyncio.create_task(server)
    # keep the clock synced (retry if the internet wasn't up at boot; hourly drift correction)
    asyncio.create_task(time_keeper())

    # main task to control automatic logging
    while True:
       await loggingController()
       checkConnectionCounter += 1
       print(f"Checking connection in {checkConnectionCounter} out of 10")
       if checkConnectionCounter % 10 == 0:
           print("checking WiFi connection")
           try:
                response = requests.get("http://clients3.google.com/generate_204", headers = { "User-Agent" : HTTP_HEADERS["User-Agent"] }, timeout=10)
                status_code = response.status_code
                response.close()
                # Anything other than 204 means a captive portal / ISP block page answered
                if status_code != 204:
                    raise OSError(f"connectivity check returned HTTP {status_code}, expected 204")
                checkConnectionCounter = 1
                failed_checks = 0
                gc.collect()
           except Exception as e:
                failed_checks += 1
                print(f"Request Error {failed_checks} of 3: {e}")
                checkConnectionCounter = 1
                if failed_checks >= 3:
                    if wlan.isconnected():
                        # Wi-Fi is fine, the internet isn't (modem rebooting, ISP outage).
                        # Rebooting the Pico can't fix that, so keep running and keep checking.
                        print(f"Wi-Fi connected but internet unreachable ({failed_checks} failed checks); not resetting")
                        if failed_checks % INTERNET_DOWN_REJOIN_CHECKS == 0:
                            # Long outage: rejoin Wi-Fi (no reboot) in case the link went stale,
                            # e.g. the router rebooted and our DHCP lease/IP is no longer valid
                            print("Rejoining Wi-Fi after extended internet outage")
                            wlan.disconnect()
                            await asyncio.sleep(1)
                            wlan.connect(SSID, decryptedKEY)
                            for _ in range(200):  # up to 20s
                                if wlan.isconnected():
                                    break
                                await asyncio.sleep_ms(100)
                            if wlan.isconnected():
                                broadcast_ip(wlan)  # IP may have changed
                                print(f"Rejoined Wi-Fi, IP address: {pico_IP}")
                    if not wlan.isconnected():
                        # Wi-Fi itself is down: escalate (its last level reboots into the
                        # wait-for-Wi-Fi / listen-for-app mode)
                        number_flashes = 0
                        while True:
                            led.toggle()
                            time.sleep(0.05)
                            number_flashes += 1
                            if number_flashes > 100:
                                break
                        led.value(0)
                        if recover_wifi(SSID, decryptedKEY):
                            failed_checks = 0  # recovered without a reboot; start counting afresh
                    
                    
# start asyncio task and loop
try:
    # start the main async tasks
    asyncio.run(main())
except Exception as e:
            print(f"\nFATAL ERROR: {e}")
            time.sleep(10)
            machine.reset() # hard reset
finally:
    # reset and start a new event loop for the task scheduler
    asyncio.new_event_loop()
