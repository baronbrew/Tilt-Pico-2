import bluetooth
import binascii
from micropython import const
import time

_IRQ_SCAN_RESULT = const(5) # The correct way to get the constant

# Create a Bluetooth object.
ble = bluetooth.BLE()
if not ble.active():
    ble.active(True)
print(ble.active())

# Set to store unique device addresses to avoid duplicates.
found_devices = set()

# An event handler function that will be called for each BLE event.
def bt_irq(event, data):
    # Check if the event is a new scan result.
    if event == _IRQ_SCAN_RESULT:
        addr_type, addr, adv_type, rssi, adv_data = data
        
        # Convert the address to a more readable format.
        addr_str = addr.hex()
        data_str = binascii.hexlify(adv_data)
        
        print(f'Device found: {addr_str}, RSSI: {rssi} dBm, Data: {data_str}')

# Register the event handler.
ble.irq(bt_irq)

# Start scanning for devices for 5 seconds.
print("Starting BLE scan for 5 seconds...")
ble.gap_scan(1100, 1000*1000, 1000*1000, False)
time.sleep(1.1)
ble.irq(None)
ble.active(False)