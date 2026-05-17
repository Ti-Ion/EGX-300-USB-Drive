#!/usr/bin/env python3
"""
svg2egx.py - Convert SVG files to CAMM-GL II commands for the Roland EGX-300.

This is the main design-to-machine pipeline. Create your design in Inkscape
(or any SVG editor), then convert and send:

Usage:
    python3 svg2egx.py design.svg -o output.camm       # Convert to command file
    python3 svg2egx.py design.svg --send                # Convert and send directly
    python3 svg2egx.py design.svg --preview             # Render interactive HTML viewer
    python3 svg2egx.py design.svg --scale 2.0           # Scale design 2x
    python3 svg2egx.py design.svg --depth 0.3           # Engrave 0.3mm deep
    python3 svg2egx.py design.svg --svg-units px        # Force unit (browser/raw SVGs)

Inkscape workflow:
    1. Create design in Inkscape (mm units recommended)
    2. Convert all objects to paths (Path > Object to Path)
    3. Convert text to paths (Path > Object to Path)
    4. Save as Plain SVG
    5. Run: python3 svg2egx.py design.svg --send

Dependencies:
    pip install svgpathtools    # SVG path parsing
    pip install numpy           # Math (usually already installed)
"""

import argparse
import sys
import math
import os
from pathlib import Path

try:
    from svgpathtools import svg2paths2, Line, CubicBezier, QuadraticBezier, Arc
    HAS_SVGPATHTOOLS = True
except ImportError:
    HAS_SVGPATHTOOLS = False

from egx_send import send_raw
from camm2html import render_html, default_output_path


# --- Configuration ---

DEFAULT_DEVICE = '/dev/usb/lp0'

# Machine parameters for EGX-300
UNITS_PER_MM = 100          # 100 machine units = 1mm (confirm for your machine)
MAX_X_MM = 305              # Maximum X travel in mm
MAX_Y_MM = 230              # Maximum Y travel in mm
SAFE_Z_UP = 500             # Z position when tool is up (5mm above surface)
DEFAULT_DEPTH_MM = 0.2      # Default engraving depth in mm
DEFAULT_FEED_RATE = 10      # Default VS value
CURVE_TOLERANCE = 0.1       # Curve linearization tolerance in mm

# CSS/SVG length units expressed in millimetres per unit.
SVG_UNIT_TO_MM = {
    'mm': 1.0,
    'cm': 10.0,
    'in': 25.4,
    'pt': 25.4 / 72.0,
    'pc': 25.4 / 6.0,
    'px': 25.4 / 96.0,        # CSS reference pixel: 1px = 1/96 in
    'q':  0.25,
}


def parse_svg_length(length_str):
    """Parse an SVG length attribute like '100mm', '3in', '800px', '100'.

    Returns (numeric_value, unit_or_None). Unit is lowercased; None means no
    unit suffix was present. Returns (None, None) if the string is missing,
    empty, malformed, or carries an unrecognised unit.
    """
    if length_str is None:
        return (None, None)
    s = str(length_str).strip()
    if not s:
        return (None, None)

    i = 0
    if s[i] in '+-':
        i += 1
    while i < len(s) and (s[i].isdigit() or s[i] == '.'):
        i += 1
    if i < len(s) and s[i] in 'eE':
        i += 1
        if i < len(s) and s[i] in '+-':
            i += 1
        while i < len(s) and s[i].isdigit():
            i += 1

    try:
        value = float(s[:i])
    except ValueError:
        return (None, None)

    unit = s[i:].strip().lower()
    if unit == '':
        return (value, None)
    if unit in SVG_UNIT_TO_MM:
        return (value, unit)
    return (None, None)


def parse_svg_viewbox(viewbox_str):
    """Parse an SVG viewBox. Returns (min_x, min_y, width, height) or None."""
    if not viewbox_str:
        return None
    parts = viewbox_str.replace(',', ' ').split()
    if len(parts) != 4:
        return None
    try:
        return tuple(float(p) for p in parts)
    except ValueError:
        return None


def linearize_cubic_bezier(p0, p1, p2, p3, tolerance=CURVE_TOLERANCE):
    """Convert a cubic bezier curve to line segments via adaptive subdivision."""
    segments = []
    _subdivide_cubic(p0, p1, p2, p3, tolerance * UNITS_PER_MM, segments)
    return segments


def _subdivide_cubic(p0, p1, p2, p3, tolerance, segments):
    """Recursively subdivide a cubic bezier until flat enough."""
    dx = p3[0] - p0[0]
    dy = p3[1] - p0[1]
    d = math.sqrt(dx * dx + dy * dy)

    if d < 0.001:
        segments.append(p3)
        return

    # Flatness: max perpendicular distance of control points from the chord p0-p3
    d1 = abs((p1[0] - p0[0]) * dy - (p1[1] - p0[1]) * dx) / d
    d2 = abs((p2[0] - p0[0]) * dy - (p2[1] - p0[1]) * dx) / d

    if d1 + d2 <= tolerance:
        segments.append(p3)
        return

    m01 = midpoint(p0, p1)
    m12 = midpoint(p1, p2)
    m23 = midpoint(p2, p3)
    m012 = midpoint(m01, m12)
    m123 = midpoint(m12, m23)
    m0123 = midpoint(m012, m123)

    _subdivide_cubic(p0, m01, m012, m0123, tolerance, segments)
    _subdivide_cubic(m0123, m123, m23, p3, tolerance, segments)


def linearize_quadratic_bezier(p0, p1, p2, tolerance=CURVE_TOLERANCE):
    """Convert a quadratic bezier to a cubic and linearize."""
    c1 = (p0[0] + 2/3 * (p1[0] - p0[0]), p0[1] + 2/3 * (p1[1] - p0[1]))
    c2 = (p2[0] + 2/3 * (p1[0] - p2[0]), p2[1] + 2/3 * (p1[1] - p2[1]))
    return linearize_cubic_bezier(p0, c1, c2, p2, tolerance)


def midpoint(a, b):
    return ((a[0] + b[0]) / 2, (a[1] + b[1]) / 2)


class SVGToCAMM:
    """Convert SVG paths to CAMM-GL II commands."""

    def __init__(self, scale=1.0, offset_x=0, offset_y=0, depth_mm=DEFAULT_DEPTH_MM,
                 feed_rate=DEFAULT_FEED_RATE, mirror_y=True, svg_units='auto'):
        self.scale = scale
        self.offset_x = offset_x * UNITS_PER_MM
        self.offset_y = offset_y * UNITS_PER_MM
        self.depth_mm = depth_mm
        self.feed_rate = feed_rate
        self.mirror_y = mirror_y  # SVG Y-axis is inverted vs machine
        self.svg_units = svg_units
        self.user_unit_mm = None
        self.svg_height_user = 0.0
        self._user_to_units = 1.0  # combined user-unit → machine-unit multiplier; set on load
        self.paths = []
        self.bounds = None

    def load_svg_svgpathtools(self, filepath):
        """Load SVG using svgpathtools (recommended)."""
        paths, attributes, svg_attributes = svg2paths2(filepath)

        viewbox = parse_svg_viewbox(svg_attributes.get('viewBox', ''))
        width_val, width_unit = parse_svg_length(svg_attributes.get('width'))
        height_val, height_unit = parse_svg_length(svg_attributes.get('height'))

        self.user_unit_mm = self._resolve_user_unit_mm(viewbox, width_val, width_unit)
        self._user_to_units = self.user_unit_mm * self.scale * UNITS_PER_MM

        if viewbox is not None:
            self.svg_height_user = viewbox[3]
        elif height_val is not None:
            self.svg_height_user = height_val
        elif self.mirror_y:
            raise ValueError(
                "Cannot determine SVG height for Y-axis mirroring: SVG has "
                "neither a viewBox nor a height attribute. Add a viewBox to "
                "the source file."
            )
        else:
            self.svg_height_user = 0.0

        convert = self._convert_point
        for path in paths:
            if len(path) == 0:
                continue

            points = [convert(path[0].start.real, path[0].start.imag)]
            for segment in path:
                if isinstance(segment, Line):
                    points.append(convert(segment.end.real, segment.end.imag))

                elif isinstance(segment, CubicBezier):
                    p0 = convert(segment.start.real, segment.start.imag)
                    p1 = convert(segment.control1.real, segment.control1.imag)
                    p2 = convert(segment.control2.real, segment.control2.imag)
                    p3 = convert(segment.end.real, segment.end.imag)
                    points.extend(linearize_cubic_bezier(p0, p1, p2, p3))

                elif isinstance(segment, QuadraticBezier):
                    p0 = convert(segment.start.real, segment.start.imag)
                    p1 = convert(segment.control.real, segment.control.imag)
                    p2 = convert(segment.end.real, segment.end.imag)
                    points.extend(linearize_quadratic_bezier(p0, p1, p2))

                elif isinstance(segment, Arc):
                    # Fixed-sample fallback; svgpathtools' Arc lacks the rx/ry
                    # parameterization linearize_arc_segment expects.
                    n_samples = 20
                    for i in range(1, n_samples + 1):
                        pt = segment.point(i / n_samples)
                        points.append(convert(pt.real, pt.imag))

            self.paths.append(points)

        self._compute_bounds()

    def _resolve_user_unit_mm(self, viewbox, width_val, width_unit):
        """Return the number of millimetres represented by one SVG user unit."""
        if self.svg_units != 'auto':
            if self.svg_units not in SVG_UNIT_TO_MM:
                raise ValueError(
                    f"Unknown --svg-units '{self.svg_units}'. "
                    f"Supported: {', '.join(sorted(SVG_UNIT_TO_MM))}."
                )
            return SVG_UNIT_TO_MM[self.svg_units]

        # viewBox + physical width: the two together pin the user-unit scale.
        if viewbox is not None and width_unit is not None and width_val is not None:
            vb_width = viewbox[2]
            if vb_width <= 0:
                raise ValueError(f"Invalid viewBox width: {vb_width}")
            return (width_val * SVG_UNIT_TO_MM[width_unit]) / vb_width

        # No viewBox but width carries a physical unit: 1 user unit == 1 of that unit.
        if viewbox is None and width_unit is not None:
            return SVG_UNIT_TO_MM[width_unit]

        reasons = []
        if viewbox is None:
            reasons.append("no viewBox")
        if width_val is None:
            reasons.append("no width attribute")
        elif width_unit is None:
            reasons.append("width attribute has no unit (e.g. width='800' instead of width='800mm')")
        raise ValueError(
            f"Cannot determine SVG unit scale ({'; '.join(reasons)}). "
            f"Re-export the SVG with an explicit viewBox and unit-bearing width, "
            f"or pass --svg-units {{{','.join(sorted(SVG_UNIT_TO_MM))}}} to override."
        )

    def _convert_point(self, x, y):
        """Convert SVG user-unit coordinates to machine units."""
        # SVG origin is top-left with Y down; machine origin is bottom-left with
        # Y up. Mirror around the SVG height (in user units) before scaling.
        if self.mirror_y:
            y = self.svg_height_user - y
        return (x * self._user_to_units + self.offset_x,
                y * self._user_to_units + self.offset_y)

    def _compute_bounds(self):
        """Compute bounding box of all paths."""
        min_x = min_y = float('inf')
        max_x = max_y = float('-inf')
        for path in self.paths:
            for x, y in path:
                if x < min_x: min_x = x
                if x > max_x: max_x = x
                if y < min_y: min_y = y
                if y > max_y: max_y = y

        if min_x == float('inf'):
            return
        self.bounds = {
            'min_x': min_x, 'max_x': max_x,
            'min_y': min_y, 'max_y': max_y,
            'width_mm': (max_x - min_x) / UNITS_PER_MM,
            'height_mm': (max_y - min_y) / UNITS_PER_MM,
        }

    def generate_camm(self):
        """Generate CAMM-GL II command string from loaded paths."""
        if not self.paths:
            print("Warning: No paths found in SVG!", file=sys.stderr)
            return ""

        z_down = int(-self.depth_mm * UNITS_PER_MM)
        lines = [
            "IN;",                              # Initialize
            "!MC1;",                            # Spindle ON
            "PA;",                              # Absolute coordinates
            f"VS{self.feed_rate};",             # Feed rate
            f"!PZ{z_down},{SAFE_Z_UP};",        # Z down=cut depth, Z up=safe
        ]

        for path in self.paths:
            if len(path) < 2:
                continue
            x0, y0 = path[0]
            lines.append(f"PU{int(x0)},{int(y0)};")
            for x, y in path[1:]:
                lines.append(f"PD{int(x)},{int(y)};")
            lines.append("PU;")

        lines.append("!MC0;")       # Spindle OFF
        lines.append("PU0,0;")      # Return to origin

        return '\n'.join(lines)

    def print_info(self):
        """Print information about the loaded design."""
        if not self.bounds:
            print("No paths loaded.")
            return

        print(f"Design info:")
        print(f"  Paths: {len(self.paths)}")
        total_points = sum(len(p) for p in self.paths)
        print(f"  Total points: {total_points}")
        if self.user_unit_mm is not None:
            origin = 'forced' if self.svg_units != 'auto' else 'auto'
            print(f"  SVG unit scale: 1 user unit = {self.user_unit_mm:.4f} mm ({origin})")
        print(f"  Bounding box:")
        print(f"    X: {self.bounds['min_x']/UNITS_PER_MM:.1f} to {self.bounds['max_x']/UNITS_PER_MM:.1f} mm")
        print(f"    Y: {self.bounds['min_y']/UNITS_PER_MM:.1f} to {self.bounds['max_y']/UNITS_PER_MM:.1f} mm")
        print(f"    Size: {self.bounds['width_mm']:.1f} x {self.bounds['height_mm']:.1f} mm")

        # Safety check
        max_x_mm = self.bounds['max_x'] / UNITS_PER_MM
        max_y_mm = self.bounds['max_y'] / UNITS_PER_MM
        if max_x_mm > MAX_X_MM or max_y_mm > MAX_Y_MM:
            print(f"\n  *** WARNING: Design exceeds machine limits! ***")
            print(f"  Machine max: {MAX_X_MM} x {MAX_Y_MM} mm")
        if self.bounds['min_x'] < 0 or self.bounds['min_y'] < 0:
            print(f"\n  *** WARNING: Design has negative coordinates! ***")
            print(f"  Use --offset-x / --offset-y to shift the design.")

def main():
    parser = argparse.ArgumentParser(
        description='Convert SVG to CAMM-GL II commands for Roland EGX-300',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
    # Convert and save command file:
    python3 svg2egx.py logo.svg -o logo.camm

    # Preview before engraving:
    python3 svg2egx.py logo.svg --preview

    # Convert, offset, and send directly:
    python3 svg2egx.py logo.svg --offset-x 10 --offset-y 10 --send

    # Adjust depth and speed:
    python3 svg2egx.py logo.svg --depth 0.5 --feed 5 -o logo.camm
        """)
    parser.add_argument('svg_file', help='Input SVG file')
    parser.add_argument('-o', '--output', help='Output .camm command file')
    parser.add_argument('--send', action='store_true',
                        help='Send directly to machine')
    parser.add_argument('-d', '--device', default=DEFAULT_DEVICE,
                        help=f'Device path (default: {DEFAULT_DEVICE})')
    parser.add_argument('--preview', action='store_true',
                        help='Render an interactive 3D HTML viewer into viewer-output/ '
                             '(requires three.min.js — run `python3 fetch_three.py` once)')
    parser.add_argument('--scale', type=float, default=1.0,
                        help='Scale factor (default: 1.0)')
    parser.add_argument('--offset-x', type=float, default=0,
                        help='X offset in mm (default: 0)')
    parser.add_argument('--offset-y', type=float, default=0,
                        help='Y offset in mm (default: 0)')
    parser.add_argument('--depth', type=float, default=DEFAULT_DEPTH_MM,
                        help=f'Engraving depth in mm (default: {DEFAULT_DEPTH_MM})')
    parser.add_argument('--feed', type=int, default=DEFAULT_FEED_RATE,
                        help=f'Feed rate / VS value (default: {DEFAULT_FEED_RATE})')
    parser.add_argument('--svg-units',
                        choices=['auto'] + sorted(SVG_UNIT_TO_MM),
                        default='auto',
                        help='Override the unit of one SVG user unit. '
                             'Default auto-detects from viewBox + width; pass '
                             'an explicit unit if auto-detection errors out '
                             'or is wrong for your source.')
    parser.add_argument('--dry-run', action='store_true',
                        help='Show commands without sending')
    parser.add_argument('--info-only', action='store_true',
                        help='Show design info and exit')

    args = parser.parse_args()

    if not HAS_SVGPATHTOOLS:
        print("ERROR: svgpathtools is required.")
        print("Install with: pip install svgpathtools")
        sys.exit(1)

    if not os.path.exists(args.svg_file):
        print(f"ERROR: File not found: {args.svg_file}")
        sys.exit(1)

    # Load and convert
    converter = SVGToCAMM(
        scale=args.scale,
        offset_x=args.offset_x,
        offset_y=args.offset_y,
        depth_mm=args.depth,
        feed_rate=args.feed,
        svg_units=args.svg_units,
    )

    print(f"Loading {args.svg_file}...")
    try:
        converter.load_svg_svgpathtools(args.svg_file)
    except ValueError as e:
        print(f"ERROR: {e}", file=sys.stderr)
        sys.exit(1)
    converter.print_info()

    if args.info_only:
        return

    # Generate commands
    camm_commands = converter.generate_camm()

    if not camm_commands:
        print("No commands generated. Check your SVG has paths.")
        sys.exit(1)

    if args.preview:
        svg_path = Path(args.svg_file)
        out_html = default_output_path(svg_path.stem)
        try:
            render_html(camm_commands, out_html, title=svg_path.name)
        except FileNotFoundError as e:
            print(f"ERROR: {e}", file=sys.stderr)
            sys.exit(1)
        print(f"\nWrote viewer to {out_html}")
        print(f"Open: file://{out_html.resolve()}")
        return

    # Output
    if args.output:
        with open(args.output, 'w') as f:
            f.write(camm_commands)
        print(f"Saved to {args.output}")
        print(f"  Send with: python3 egx_send.py -f {args.output}")

    if args.send or args.dry_run:
        if args.dry_run:
            print("\n--- DRY RUN ---")
            print(camm_commands)
        else:
            print(f"\nSending to {args.device}...")
            confirm = input("Confirm send? (y/n): ").strip().lower()
            if confirm == 'y':
                send_raw(args.device, camm_commands)
                print("Sent successfully.")
            else:
                print("Cancelled.")

    if not args.output and not args.send and not args.dry_run:
        print("\nGenerated commands (use -o to save or --send to engrave):")
        # Show first/last few lines
        cmd_lines = camm_commands.split('\n')
        if len(cmd_lines) <= 20:
            print(camm_commands)
        else:
            for line in cmd_lines[:8]:
                print(f"  {line}")
            print(f"  ... ({len(cmd_lines) - 16} more lines) ...")
            for line in cmd_lines[-8:]:
                print(f"  {line}")


if __name__ == '__main__':
    main()
