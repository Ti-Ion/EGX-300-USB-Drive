#!/usr/bin/env python3
"""
gcode2egx.py - Convert G-code to CAMM-GL II commands for the Roland EGX-300.

This lets you use any CAM software that outputs G-code (FreeCAD, Fusion 360,
FlatCAM for PCBs, etc.) and convert the output to CAMM-GL II for the EGX-300.

Usage:
    python3 gcode2egx.py toolpath.gcode -o output.camm
    python3 gcode2egx.py toolpath.gcode --send
    python3 gcode2egx.py toolpath.gcode --preview

Supported G-code commands:
    G0/G00  - Rapid move        -> PU (pen up move)
    G1/G01  - Linear feed       -> PD (pen down move)
    G2/G02  - CW arc            -> linearized PD segments
    G3/G03  - CCW arc           -> linearized PD segments
    G20     - Inches mode
    G21     - Millimeters mode
    G28     - Home
    G90     - Absolute coordinates
    G91     - Relative coordinates
    M3/M03  - Spindle ON        -> !MC1;
    M5/M05  - Spindle OFF       -> !MC0;
    F       - Feed rate         -> VS
    S       - Spindle speed     (noted but EGX-300 has fixed spindle speed)

Notes:
    - Z movements are interpreted as tool up/down based on threshold
    - G2/G3 arcs are linearized into small line segments
    - The converter ignores unsupported codes gracefully
"""

import argparse
import sys
import math
import re
import os

from egx_send import send_raw


# Machine parameters
UNITS_PER_MM = 100
SAFE_Z_UP = 500
Z_THRESHOLD_MM = 0.0  # Z values above this = tool up, below = tool down
DEFAULT_DEVICE = '/dev/usb/lp0'

_PARAM_RE = re.compile(r'([A-Za-z])([+-]?\d*\.?\d+)')
_PAREN_COMMENT_RE = re.compile(r'\(.*?\)')
_CODE_RE = re.compile(r'([GM])(\d+)', re.IGNORECASE)


class GCodeParser:
    """Parse G-code and convert to CAMM-GL II commands."""

    def __init__(self, z_threshold=Z_THRESHOLD_MM):
        self.z_threshold = z_threshold
        self.absolute = True
        self.inches = False
        self.x = 0.0
        self.y = 0.0
        self.z = 10.0  # Start with tool up
        self.feed_rate = 10
        self.tool_down = False
        self.commands = []
        self.paths = []  # For preview: list of (points, is_cut) tuples
        self._current_path = []

    def _to_machine(self, val_mm):
        """Convert mm value to machine units."""
        return int(val_mm * UNITS_PER_MM)

    def _parse_params(self, line):
        """Extract letter-value pairs from a G-code line."""
        return {m.group(1).upper(): float(m.group(2)) for m in _PARAM_RE.finditer(line)}

    def _scale(self, val):
        """Scale value based on inches/mm mode."""
        if self.inches:
            return val * 25.4  # Convert inches to mm
        return val

    def _handle_move(self, params, is_rapid):
        """Handle G0 (rapid) or G1 (feed) moves."""
        new_x = self.x
        new_y = self.y
        new_z = self.z

        if 'X' in params:
            if self.absolute:
                new_x = self._scale(params['X'])
            else:
                new_x = self.x + self._scale(params['X'])

        if 'Y' in params:
            if self.absolute:
                new_y = self._scale(params['Y'])
            else:
                new_y = self.y + self._scale(params['Y'])

        if 'Z' in params:
            if self.absolute:
                new_z = self._scale(params['Z'])
            else:
                new_z = self.z + self._scale(params['Z'])

        if 'F' in params:
            self.feed_rate = max(1, int(params['F'] / 60))  # G-code F is mm/min, VS is different

        # Z changed - determine tool up/down transition
        if new_z != self.z:
            was_down = self.z <= self.z_threshold
            now_down = new_z <= self.z_threshold

            if was_down and not now_down:
                self.commands.append("PU;")
                self.tool_down = False
                if self._current_path:
                    self.paths.append((list(self._current_path), True))
                    self._current_path = []
            elif not was_down and now_down:
                # Plunge: don't emit PD yet; the next XY move converts to PD.
                self.tool_down = True

        self.z = new_z

        # XY movement
        if new_x != self.x or new_y != self.y:
            mx = self._to_machine(new_x)
            my = self._to_machine(new_y)

            if is_rapid or not self.tool_down:
                self.commands.append(f"PU{mx},{my};")
                if self._current_path:
                    self.paths.append((list(self._current_path), False))
                self._current_path = [(new_x, new_y)]
            else:
                self.commands.append(f"PD{mx},{my};")
                self._current_path.append((new_x, new_y))

            self.x = new_x
            self.y = new_y

    def _handle_arc(self, params, clockwise):
        """Handle G2/G3 arc moves by linearizing."""
        if 'X' not in params and 'Y' not in params:
            return

        # End point
        if self.absolute:
            end_x = self._scale(params.get('X', self.x))
            end_y = self._scale(params.get('Y', self.y))
        else:
            end_x = self.x + self._scale(params.get('X', 0))
            end_y = self.y + self._scale(params.get('Y', 0))

        # Center offset (I, J are always relative to current position)
        ci = self._scale(params.get('I', 0))
        cj = self._scale(params.get('J', 0))
        cx = self.x + ci
        cy = self.y + cj

        # Calculate start and end angles
        start_angle = math.atan2(self.y - cy, self.x - cx)
        end_angle = math.atan2(end_y - cy, end_x - cx)
        radius = math.sqrt(ci * ci + cj * cj)

        # Calculate sweep
        if clockwise:
            sweep = start_angle - end_angle
            if sweep <= 0:
                sweep += 2 * math.pi
            sweep = -sweep
        else:
            sweep = end_angle - start_angle
            if sweep <= 0:
                sweep += 2 * math.pi

        arc_length = abs(sweep * radius)
        n_segments = max(4, int(arc_length / 0.2))  # ~0.2 mm chord

        for i in range(1, n_segments + 1):
            t = i / n_segments
            angle = start_angle + sweep * t
            px = cx + radius * math.cos(angle)
            py = cy + radius * math.sin(angle)

            mx = self._to_machine(px)
            my = self._to_machine(py)

            if self.tool_down:
                self.commands.append(f"PD{mx},{my};")
                self._current_path.append((px, py))
            else:
                self.commands.append(f"PU{mx},{my};")

        self.x = end_x
        self.y = end_y

    def parse_file(self, filepath):
        """Parse a G-code file and generate CAMM-GL II commands."""
        # Header
        self.commands.append("IN;")
        self.commands.append("PA;")
        self.commands.append(f"!PZ{self._to_machine(-abs(self.z_threshold) - 20)},{SAFE_Z_UP};")

        with open(filepath, 'r') as f:
            for line in f:
                line = line.strip()

                if ';' in line:
                    line = line[:line.index(';')]
                if '(' in line:
                    line = _PAREN_COMMENT_RE.sub('', line)
                line = line.strip()

                if not line:
                    continue

                params = self._parse_params(line)

                code_match = _CODE_RE.match(line)
                if not code_match:
                    # Bare coordinate line — continuation of previous G mode.
                    if 'X' in params or 'Y' in params or 'Z' in params:
                        self._handle_move(params, False)
                    continue

                code_letter = code_match.group(1).upper()
                code_num = int(code_match.group(2))

                if code_letter == 'G':
                    if code_num == 0:
                        self._handle_move(params, is_rapid=True)
                    elif code_num == 1:
                        self._handle_move(params, is_rapid=False)
                    elif code_num == 2:
                        self._handle_arc(params, clockwise=True)
                    elif code_num == 3:
                        self._handle_arc(params, clockwise=False)
                    elif code_num == 20:
                        self.inches = True
                    elif code_num == 21:
                        self.inches = False
                    elif code_num == 28:
                        self.commands.append("PU0,0;")
                        self.x = 0
                        self.y = 0
                    elif code_num == 90:
                        self.absolute = True
                        self.commands.append("PA;")
                    elif code_num == 91:
                        self.absolute = False
                        self.commands.append("PR;")

                elif code_letter == 'M':
                    if code_num == 3 or code_num == 4:
                        self.commands.append("!MC1;")
                    elif code_num == 5:
                        self.commands.append("!MC0;")

        # Footer
        self.commands.append("PU;")
        self.commands.append("!MC0;")
        self.commands.append("PU0,0;")

        # Finalize paths for preview
        if self._current_path:
            self.paths.append((list(self._current_path), self.tool_down))

    def get_commands(self):
        return '\n'.join(self.commands)

    def print_info(self):
        all_x = []
        all_y = []
        for path, is_cut in self.paths:
            for x, y in path:
                all_x.append(x)
                all_y.append(y)

        if all_x:
            print(f"G-code conversion info:")
            print(f"  Commands generated: {len(self.commands)}")
            print(f"  Toolpath segments: {len(self.paths)}")
            cut_paths = sum(1 for _, is_cut in self.paths if is_cut)
            print(f"  Cutting segments: {cut_paths}")
            print(f"  Bounding box:")
            print(f"    X: {min(all_x):.1f} to {max(all_x):.1f} mm")
            print(f"    Y: {min(all_y):.1f} to {max(all_y):.1f} mm")
            print(f"    Size: {max(all_x)-min(all_x):.1f} x {max(all_y)-min(all_y):.1f} mm")

    def preview(self):
        try:
            import matplotlib.pyplot as plt
        except ImportError:
            print("matplotlib required for preview: pip install matplotlib")
            return

        fig, ax = plt.subplots(figsize=(10, 8))

        for path, is_cut in self.paths:
            if len(path) < 2:
                continue
            xs = [p[0] for p in path]
            ys = [p[1] for p in path]
            if is_cut:
                ax.plot(xs, ys, 'b-', linewidth=1.0)
            else:
                ax.plot(xs, ys, 'r--', linewidth=0.3, alpha=0.4)

        ax.set_xlabel('X (mm)')
        ax.set_ylabel('Y (mm)')
        ax.set_title('G-code → EGX-300 Toolpath Preview')
        ax.set_aspect('equal')
        ax.grid(True, alpha=0.3)
        plt.tight_layout()
        plt.show()


def main():
    parser = argparse.ArgumentParser(
        description='Convert G-code to CAMM-GL II for Roland EGX-300',
        epilog="""
Supports G-code from: FreeCAD Path, Fusion 360, FlatCAM (PCBs),
  Carbide Create, Estlcam, and other standard G-code generators.
        """)
    parser.add_argument('gcode_file', help='Input G-code file')
    parser.add_argument('-o', '--output', help='Output .camm command file')
    parser.add_argument('--send', action='store_true', help='Send directly')
    parser.add_argument('-d', '--device', default=DEFAULT_DEVICE)
    parser.add_argument('--preview', action='store_true', help='Show preview')
    parser.add_argument('--z-threshold', type=float, default=Z_THRESHOLD_MM,
                        help='Z threshold for tool up/down (mm, default: 0)')
    parser.add_argument('--dry-run', action='store_true')

    args = parser.parse_args()

    if not os.path.exists(args.gcode_file):
        print(f"ERROR: File not found: {args.gcode_file}")
        sys.exit(1)

    converter = GCodeParser(z_threshold=args.z_threshold)
    print(f"Parsing {args.gcode_file}...")
    converter.parse_file(args.gcode_file)
    converter.print_info()

    if args.preview:
        converter.preview()
        return

    camm = converter.get_commands()

    if args.output:
        with open(args.output, 'w') as f:
            f.write(camm)
        print(f"Saved to {args.output}")
        print(f"  Send with: python3 egx_send.py -f {args.output}")

    if args.send or args.dry_run:
        if args.dry_run:
            print("\n--- DRY RUN ---")
            print(camm)
        else:
            print(f"\nSending to {args.device}...")
            confirm = input("Confirm? (y/n): ").strip().lower()
            if confirm == 'y':
                send_raw(args.device, camm)
                print("Sent.")
            else:
                print("Cancelled.")

    if not args.output and not args.send and not args.dry_run:
        cmd_lines = camm.split('\n')
        if len(cmd_lines) <= 20:
            print(camm)
        else:
            for line in cmd_lines[:8]:
                print(f"  {line}")
            print(f"  ... ({len(cmd_lines) - 16} more lines) ...")
            for line in cmd_lines[-8:]:
                print(f"  {line}")


if __name__ == '__main__':
    main()
