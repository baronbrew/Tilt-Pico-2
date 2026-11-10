#!/usr/bin/env bash

# Check if a firmware file was provided
if [ -z "$1" ]; then
    echo "Usage: ./flash_pico.sh <path_to_firmware.uf2>"
    exit 1
fi

FIRMWARE="$1"

if [ ! -f "$FIRMWARE" ]; then
    echo "Error: File '$FIRMWARE' not found."
    exit 1
fi

echo "Searching for Pico W (RPI-RP2)..."

# Detect mount path for macOS or Linux
PICO_PATH=""
if [ -d "/Volumes/RPI-RP2" ]; then
    PICO_PATH="/Volumes/RPI-RP2"
else
    # Searches standard Linux mount directories
    PICO_PATH=$(find /media /run/media -maxdepth 3 -name "RPI-RP2" 2>/dev/null | head -n 1)
fi

if [ -z "$PICO_PATH" ]; then
    echo "Error: Pico W not found!"
    echo "Ensure your Pico W is in BOOTSEL mode (hold BOOTSEL button while plugging in)."
    exit 1
fi

echo "Found Pico W at: $PICO_PATH"
echo "Copying $FIRMWARE..."

cp "$FIRMWARE" "$PICO_PATH/" && sync

echo "Flash complete! The Pico W will reboot automatically."
