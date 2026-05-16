#!/usr/bin/env python3
"""
egx_send.py - Send CAMM-GL II commands to the Roland EGX-300 via USB parallel.

Usage:
    python3 egx_send.py "PU1000,1000;"              # Send a single command string
    python3 egx_send.py -f commands.txt              # Send commands from a file
    python3 egx_send.py -i                           # Interactive mode
    python3 egx_send.py --init                       # Initialize the machine
    python3 egx_send.py --home                       # Send tool to origin

Options:
    -d, --device    Device path (default: /dev/usb/lp0)
    -f, --file      Read commands from a file
    -i, --interactive   Interactive REPL mode
    --init          Send initialization sequence
    --home          Move tool to home position (0,0) with tool up
    --dry-run       Print commands without sending to machine
"""

import sys
import argparse
import time


DEFAULT_DEVICE = '/dev/usb/lp0'


def send_raw(device_path, data, dry_run=False):
    """Send raw bytes to the device."""
    if dry_run:
        print(f"[DRY RUN] Would send: {data}")
        return
    with open(device_path, 'wb') as dev:
        dev.write(data.encode('ascii'))
        dev.flush()


def send_command(device_path, command, dry_run=False):
    """Send a CAMM-GL II command string."""
    # Ensure the command doesn't have trailing whitespace issues
    command = command.strip()
    if not command:
        return
    send_raw(device_path, command, dry_run)


def init_sequence(device_path, dry_run=False):
    """Send a safe initialization sequence."""
    commands = "IN;!MC0;PA;VS10;!PZ0,500;"
    print("Sending initialization sequence...")
    print("  IN;      - Initialize to defaults")
    print("  !MC0;    - Spindle OFF")
    print("  PA;      - Absolute coordinate mode")
    print("  VS10;    - Set moderate feed rate")
    print("  !PZ0,500; - Z down=0 (surface), Z up=500 (5mm safe)")
    send_command(device_path, commands, dry_run)
    print("Done.")


def home_sequence(device_path, dry_run=False):
    """Move tool to home with spindle off."""
    commands = "!MC0;PU0,0;"
    print("Sending home sequence (spindle off, move to 0,0)...")
    send_command(device_path, commands, dry_run)
    print("Done.")


def send_file(device_path, filepath, dry_run=False, chunk_delay=0.05):
    """Send commands from a file, line by line."""
    with open(filepath, 'r') as f:
        lines = f.readlines()

    total = len([l for l in lines if l.strip() and not l.strip().startswith('#')])
    sent = 0

    for line in lines:
        line = line.strip()
        if not line or line.startswith('#'):
            continue
        send_command(device_path, line, dry_run)
        sent += 1
        if sent % 100 == 0:
            print(f"  Sent {sent}/{total} lines...")
        if chunk_delay > 0 and not dry_run:
            time.sleep(chunk_delay)

    print(f"Sent {sent} command lines from {filepath}")


def interactive_mode(device_path, dry_run=False):
    """Interactive REPL for sending commands."""
    print("=" * 60)
    print("EGX-300 Interactive Mode")
    print("=" * 60)
    print(f"Device: {device_path}")
    print(f"Dry run: {dry_run}")
    print()
    print("Quick commands:")
    print("  init     - Initialize machine")
    print("  home     - Move to origin (tool up, spindle off)")
    print("  on       - Spindle ON  (!MC1;)")
    print("  off      - Spindle OFF (!MC0;)")
    print("  up       - Tool up (PU;)")
    print("  pos      - Request position (OA;) - may not work via parallel")
    print("  quit     - Exit")
    print()
    print("Or type any CAMM-GL II command (e.g. PU1000,1000;)")
    print("-" * 60)

    shortcuts = {
        'init': 'IN;!MC0;PA;VS10;!PZ0,500;',
        'home': '!MC0;PU0,0;',
        'on': '!MC1;',
        'off': '!MC0;',
        'up': 'PU;',
        'pos': 'OA;',
    }

    while True:
        try:
            cmd = input("egx> ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\nExiting.")
            break

        if not cmd:
            continue
        if cmd.lower() == 'quit' or cmd.lower() == 'exit':
            break

        # Check shortcuts
        if cmd.lower() in shortcuts:
            actual = shortcuts[cmd.lower()]
            print(f"  -> {actual}")
            send_command(device_path, actual, dry_run)
        else:
            send_command(device_path, cmd, dry_run)

    # Safety: spindle off on exit
    print("Safety: sending spindle OFF...")
    send_command(device_path, '!MC0;', dry_run)


def main():
    parser = argparse.ArgumentParser(
        description='Send CAMM-GL II commands to Roland EGX-300')
    parser.add_argument('command', nargs='?', help='Command string to send')
    parser.add_argument('-d', '--device', default=DEFAULT_DEVICE,
                        help=f'Device path (default: {DEFAULT_DEVICE})')
    parser.add_argument('-f', '--file', dest='filepath',
                        help='Read commands from file')
    parser.add_argument('-i', '--interactive', action='store_true',
                        help='Interactive mode')
    parser.add_argument('--init', action='store_true',
                        help='Send initialization sequence')
    parser.add_argument('--home', action='store_true',
                        help='Move tool to home')
    parser.add_argument('--dry-run', action='store_true',
                        help='Print commands without sending')

    args = parser.parse_args()

    if args.init:
        init_sequence(args.device, args.dry_run)
    elif args.home:
        home_sequence(args.device, args.dry_run)
    elif args.interactive:
        interactive_mode(args.device, args.dry_run)
    elif args.filepath:
        send_file(args.device, args.filepath, args.dry_run)
    elif args.command:
        send_command(args.device, args.command, args.dry_run)
        print("Sent.")
    else:
        parser.print_help()


if __name__ == '__main__':
    main()
