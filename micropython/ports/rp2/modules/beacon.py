import struct
import ubluetooth as bt
from micropython import const

MANUFACTURER_ID         = const(0x004C)
DEVICE_TYPE             = const(0x02)
DATA_LENGTH             = const(0x15)
BR_EDR_NOT_SUPPORTED    = const(0x04)
FLAG_BROADCAST          = const(0x01)
MANUFACTURER_DATA       = const(0xFF)

def convert_tx_power(dbm):
    return dbm + 0xFF + 1

class iBeacon():
    def __init__(self, ble, uuid, major, minor, tx_power):
        # Setup BLE
        self.ble = ble
        self.ble.active(False)
        self.ble.active(True)
        print("BLE Activated")

        self.uuid = uuid
        self.major = major
        self.minor = minor
        self.tx_power = convert_tx_power(tx_power)
        self.adv_payload = self.create_payload()


    def create_payload(self):
        payload = bytearray()
            
        #Set advertising flag
        value    = struct.pack('B', BR_EDR_NOT_SUPPORTED)
        payload += struct.pack('BB', len(value) + 1, FLAG_BROADCAST) + value

        # Set advertising data
        value    = struct.pack('<H2B', MANUFACTURER_ID, DEVICE_TYPE, DATA_LENGTH) 
        value   += self.uuid
        value   += struct.pack(">2HB", self.major, self.minor, self.tx_power)
        payload += struct.pack('BB', len(value) + 1, MANUFACTURER_DATA) + value

        return payload


    def advertise(self, interval_us=1000000):
        print("Advertising: " + str(self.adv_payload))
        self.ble.gap_advertise(None)
        self.ble.gap_advertise(interval_us, adv_data=self.adv_payload, connectable=False)


    def update(self, major, minor, advertise_interval):
        self.ble.active(False)

        self.major = major
        self.minor = minor
        self.adv_payload = self.create_payload()

        self.ble.active(True)
        self.advertise(advertise_interval)


def startiBeacon(major, minor):
    beacon = iBeacon(
        ble         = bt.BLE(), 
        uuid        = bytearray((
                        0xa4, 0x95, 0xbc, 0x02, 0xc5, 0xb1, 0x4b, 0x44, 
                        0xb5, 0x12, 0x13, 0x70, 0xf0, 0x2d, 0x74, 0xde
                    )),
        major       = major,
        minor       = minor,
        tx_power    = -59,
    )

    beacon.advertise()
    
def stopiBeacon():
    bt.BLE().gap_advertise(None)
