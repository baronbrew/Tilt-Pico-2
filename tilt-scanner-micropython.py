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
from machine import Pin
led = Pin("LED", Pin.OUT)

def connect(MAC, TIME, COLOR, BEER, CLOUDURL, COMMENT, SG, TEMP):
    try:
     with open('wifi.json', 'r') as f:
      data = ujson.load(f)
      SSID = data["SSID"]
      KEY = data["KEY"]
    except:
     print('no WiFi credentials saved')
     return
    wlan = network.WLAN(network.STA_IF)
    wlan.active(True)
    wlan.connect(SSID, KEY)

    # Wait for connect or fail
    max_wait = 10
    while max_wait > 0:
        if wlan.status() < 0 or wlan.status() >= 3:
            break
        max_wait -= 1
    print('waiting for connection...')
    time.sleep(5)

    # Handle connection error
    if wlan.status() != 3:
        raise RuntimeError('network connection failed')
    else:
        print('connected')
        status = wlan.ifconfig()
        print( 'ip = ' + status[0] )
        print(wlan.status())

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
            led.off()
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
     

async def tiltscanner(logthisMAC, COLOR, BEER, COMMENT, CLOUDURL, SCANLENGTH):
  async with aioble.scan(SCANLENGTH, interval_us=500*1000, window_us=500*1000, active=False) as scanner:
    async for result in scanner:
     if binascii.hexlify(result.adv_data[9:12]) == b'a495bb' and binascii.hexlify(result.adv_data[13:25]) == b'c5b14b44b5121370f02d74de':
      UUID = str(binascii.hexlify(result.adv_data[9:25]).decode())
      MAC = str(binascii.hexlify(result.device.addr).decode())
      TEMP = str(int(binascii.hexlify(result.adv_data[25:27]), 16))
      SG = str(int(binascii.hexlify(result.adv_data[27:29]), 16))
      BATTW = str(int(binascii.hexlify(result.adv_data[29:31]), 16))
      RSSI = str(result.rssi)
      print(UUID,MAC,TEMP,SG,BATTW,RSSI,sep=',',end='.')
      if logthisMAC == MAC:
          TIME = '8'
          led.on()
          connect(logthisMAC, TIME, COLOR, BEER, CLOUDURL, COMMENT, SG, TEMP)
          return True
