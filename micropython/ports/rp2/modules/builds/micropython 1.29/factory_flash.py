#!/usr/bin/env python3
import argparse
import os
import sys
import time
import shutil
import platform
import subprocess

def find_pico_mount():
    """Scans for the mounted RPI-RP2 drive across OS platforms"""
    system = platform.system()
    
    if system == "Darwin":  # macOS
        path = "/Volumes/RPI-RP2"
        return path if os.path.exists(path) else None
        
    elif system == "Linux":  # Linux
        for search_dir in ["/media", "/run/media"]:
            if os.path.exists(search_dir):
                for root, dirs, _ in os.walk(search_dir):
                    if os.path.basename(root) == "RPI-RP2":
                        return root
        return None
        
    elif system == "Windows":  # Windows
        try:
            cmd = "powershell -Command \"Get-Volume | Where-FileSystemLabel -eq 'RPI-RP2' | Select-Object -ExpandProperty DriveLetter\""
            out = subprocess.check_output(cmd, shell=True).decode('utf-8').strip()
            if out:
                return f"{out}:\\"
        except Exception:
            pass
        return None

def parse_cli_args():
    parser = argparse.ArgumentParser(
        description="Factory Batch Auto-Flasher Daemon for Raspberry Pi Pico W."
    )
    parser.add_argument(
        "firmware",
        metavar="FIRMWARE_FILE",
        type=str,
        help="Path to the target .uf2 firmware file (e.g., build/app_v1.0.uf2)"
    )
    return parser.parse_args()

def kill_macos_notifications():
    """Kills NotificationCenter to instantly dismiss any popped-up eject warnings."""
    # Wait half a second for macOS to register the abrupt disk disconnect
    time.sleep(0.5)
    subprocess.run(
        ["killall", "NotificationCenter"], 
        check=False, 
        stdout=subprocess.DEVNULL, 
        stderr=subprocess.DEVNULL
    )

def copy_with_retry(src, dest_dir, max_attempts=5, initial_delay=0.4):
    """Standard file copy with retry logic for fresh mounts."""
    filename = os.path.basename(src)
    dest_file = os.path.join(dest_dir, filename)

    for attempt in range(1, max_attempts + 1):
        try:
            shutil.copy(src, dest_file)
            return True
        except (PermissionError, OSError) as e:
            if attempt < max_attempts:
                print(f"             [WAIT] OS drive mounting... retrying ({attempt}/{max_attempts})")
                time.sleep(initial_delay * attempt)
            else:
                raise e

def main():
    args = parse_cli_args()
    firmware_path = os.path.abspath(args.firmware)

    if not os.path.isfile(firmware_path):
        print(f"[!] Error: Firmware file not found at path:\n    '{firmware_path}'")
        sys.exit(1)

    firmware_filename = os.path.basename(firmware_path)
    system = platform.system()

    print("==================================================")
    print("   FACTORY BATCH FLASHER — 100% HANDS-FREE WORKFLOW")
    print("==================================================")
    print(f"Target Firmware: {firmware_path}")
    if system == "Darwin":
        print("macOS Auto-Kill: Enabled (Clears eject popups from Process Manager)")
    print("Status:          Waiting for Board #1...\n")

    board_count = 0
    last_flashed_path = None

    while True:
        pico_path = find_pico_mount()

        if pico_path and pico_path != last_flashed_path:
            board_count += 1
            print(f"[Board #{board_count}] Pico W detected at {pico_path}")
            
            time.sleep(0.3)  # Let OS settle mount
            print(f"             Writing {firmware_filename}...")
            
            try:
                copy_with_retry(firmware_path, pico_path, max_attempts=5, initial_delay=0.4)
                
                # Audio chime feedback
                sys.stdout.write('\a')
                sys.stdout.flush()
                
                print(f"             [SUCCESS] Flashed & rebooted!")
                last_flashed_path = pico_path

                # Kill NotificationCenter on macOS to erase the disk warning
                if system == "Darwin":
                    kill_macos_notifications()

            except Exception as e:
                print(f"             [FAILED] Write error: {e}")

        elif not pico_path and last_flashed_path:
            print(f"             Board removed. Ready for Board #{board_count + 1}...\n")
            last_flashed_path = None

        time.sleep(0.2)

if __name__ == "__main__":
    main()
