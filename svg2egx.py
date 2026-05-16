#!/usr/bin/env python3
"""
svg2egx.py - Convert SVG files to CAMM-GL II commands for the Roland EGX-300.

This is the main design-to-machine pipeline. Create your design in Inkscape
(or any SVG editor), then convert and send:

Usage:
    python3 svg2egx.py design.svg -o output.camm       # Convert to command file
    python3 svg2egx.py design.svg --send                # Convert and send directly
    python3 svg2egx.py design.svg --preview             # Preview paths (matplotlib)
    python3 svg2egx.py design.svg --scale 2.0           # Scale design 2x
    python3 svg2egx.py design.svg --depth 0.3           # Engrave 0.3mm deep

Inkscape workflow:
    1. Create design in Inkscape (mm units recommended)
    2. Convert all objects to paths (Path > Object to Path)
    3. Convert text to paths (Path > Object to Path)
    4. Save as Plain SVG
    5. Run: python3 svg2egx.py design.svg --send

Dependencies:
    pip install svgpathtools    # SVG path parsing
    pip install numpy           # Math (usually already installed)
    pip install matplotlib      # Only needed for --preview
"""

import argparse
import sys
import math
import os

try:
    from svgpathtools import svg2paths2, Line, CubicBezier, QuadraticBezier, Arc
    HAS_SVGPATHTOOLS = True
except ImportError:
    HAS_SVGPATHTOOLS = False

try:
    import xml.etree.ElementTree as ET
    HAS_XML = True
except ImportError:
    HAS_XML = False


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


def linearize_cubic_bezier(p0, p1, p2, p3, tolerance=CURVE_TOLERANCE):
    """Convert a cubic bezier curve to line segments."""
    # Adaptive subdivision based on flatness
    segments = []
    _subdivide_cubic(p0, p1, p2, p3, tolerance * UNITS_PER_MM, segments)
    return segments


def _subdivide_cubic(p0, p1, p2, p3, tolerance, segments):
    """Recursively subdivide a cubic bezier until flat enough."""
    # Flatness test: distance of control points from the line p0-p3
    dx = p3[0] - p0[0]
    dy = p3[1] - p0[1]
    d = math.sqrt(dx * dx + dy * dy)

    if d < 0.001:
        segments.append(p3)
        return

    # Distance of control points from chord
    d1 = abs((p1[0] - p0[0]) * dy - (p1[1] - p0[1]) * dx) / d
    d2 = abs((p2[0] - p0[0]) * dy - (p2[1] - p0[1]) * dx) / d

    if d1 + d2 <= tolerance:
        segments.append(p3)
        return

    # Subdivide at t=0.5 using de Casteljau
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
    # Elevate to cubic: cubic control points from quadratic
    c1 = (p0[0] + 2/3 * (p1[0] - p0[0]), p0[1] + 2/3 * (p1[1] - p0[1]))
    c2 = (p2[0] + 2/3 * (p1[0] - p2[0]), p2[1] + 2/3 * (p1[1] - p2[1]))
    return linearize_cubic_bezier(p0, c1, c2, p2, tolerance)


def linearize_arc_segment(cx, cy, rx, ry, start_angle, sweep_angle, rotation=0,
                          tolerance=CURVE_TOLERANCE):
    """Convert an arc to line segments."""
    # Number of segments based on arc length and tolerance
    approx_radius = max(rx, ry)
    approx_length = abs(sweep_angle) * approx_radius
    n_segments = max(4, int(approx_length / (tolerance * UNITS_PER_MM)))

    points = []
    cos_rot = math.cos(rotation)
    sin_rot = math.sin(rotation)

    for i in range(1, n_segments + 1):
        t = start_angle + sweep_angle * i / n_segments
        # Point on the ellipse
        px = rx * math.cos(t)
        py = ry * math.sin(t)
        # Apply rotation
        x = cx + px * cos_rot - py * sin_rot
        y = cy + px * sin_rot + py * cos_rot
        points.append((x, y))

    return points


def midpoint(a, b):
    return ((a[0] + b[0]) / 2, (a[1] + b[1]) / 2)


class SVGToCAMM:
    """Convert SVG paths to CAMM-GL II commands."""

    def __init__(self, scale=1.0, offset_x=0, offset_y=0, depth_mm=DEFAULT_DEPTH_MM,
                 feed_rate=DEFAULT_FEED_RATE, mirror_y=True):
        self.scale = scale
        self.offset_x = offset_x * UNITS_PER_MM
        self.offset_y = offset_y * UNITS_PER_MM
        self.depth_mm = depth_mm
        self.feed_rate = feed_rate
        self.mirror_y = mirror_y  # SVG Y-axis is inverted vs machine
        self.paths = []           # List of paths, each path is list of (x, y) points
        self.bounds = None

    def load_svg_svgpathtools(self, filepath):
        """Load SVG using svgpathtools (recommended)."""
        paths, attributes, svg_attributes = svg2paths2(filepath)

        # Get SVG dimensions for Y-axis flipping
        viewbox = svg_attributes.get('viewBox', '')
        width = svg_attributes.get('width', '')
        height = svg_attributes.get('height', '')

        # Parse viewBox or dimensions
        svg_height = 0
        if viewbox:
            parts = viewbox.split()
            if len(parts) == 4:
                svg_height = float(parts[3])
        elif height:
            svg_height = float(''.join(c for c in height if c.isdigit() or c == '.') or '0')

        for path in paths:
            if len(path) == 0:
                continue

            points = []
            for segment in path:
                if isinstance(segment, Line):
                    if not points:
                        points.append(self._convert_point(
                            segment.start.real, segment.start.imag, svg_height))
                    points.append(self._convert_point(
                        segment.end.real, segment.end.imag, svg_height))

                elif isinstance(segment, CubicBezier):
                    if not points:
                        points.append(self._convert_point(
                            segment.start.real, segment.start.imag, svg_height))
                    p0 = self._convert_point(segment.start.real, segment.start.imag, svg_height)
                    p1 = self._convert_point(segment.control1.real, segment.control1.imag, svg_height)
                    p2 = self._convert_point(segment.control2.real, segment.control2.imag, svg_height)
                    p3 = self._convert_point(segment.end.real, segment.end.imag, svg_height)
                    line_points = linearize_cubic_bezier(p0, p1, p2, p3)
                    points.extend(line_points)

                elif isinstance(segment, QuadraticBezier):
                    if not points:
                        points.append(self._convert_point(
                            segment.start.real, segment.start.imag, svg_height))
                    p0 = self._convert_point(segment.start.real, segment.start.imag, svg_height)
                    p1 = self._convert_point(segment.control.real, segment.control.imag, svg_height)
                    p2 = self._convert_point(segment.end.real, segment.end.imag, svg_height)
                    line_points = linearize_quadratic_bezier(p0, p1, p2)
                    points.extend(line_points)

                elif isinstance(segment, Arc):
                    # Linearize arc
                    if not points:
                        points.append(self._convert_point(
                            segment.start.real, segment.start.imag, svg_height))
                    # Sample points along the arc
                    n_samples = 20
                    for i in range(1, n_samples + 1):
                        t = i / n_samples
                        pt = segment.point(t)
                        points.append(self._convert_point(pt.real, pt.imag, svg_height))

            if points:
                self.paths.append(points)

        self._compute_bounds()

    def _convert_point(self, x, y, svg_height):
        """Convert SVG coordinates to machine coordinates."""
        # SVG uses top-left origin with Y going down
        # Machine uses bottom-left origin with Y going up
        if self.mirror_y and svg_height > 0:
            y = svg_height - y

        # Scale from SVG units (assumed mm if document is set up in mm) to machine units
        mx = x * UNITS_PER_MM * self.scale + self.offset_x
        my = y * UNITS_PER_MM * self.scale + self.offset_y

        return (mx, my)

    def _compute_bounds(self):
        """Compute bounding box of all paths."""
        all_x = []
        all_y = []
        for path in self.paths:
            for x, y in path:
                all_x.append(x)
                all_y.append(y)

        if all_x:
            self.bounds = {
                'min_x': min(all_x), 'max_x': max(all_x),
                'min_y': min(all_y), 'max_y': max(all_y),
                'width_mm': (max(all_x) - min(all_x)) / UNITS_PER_MM,
                'height_mm': (max(all_y) - min(all_y)) / UNITS_PER_MM,
            }

    def generate_camm(self):
        """Generate CAMM-GL II command string from loaded paths."""
        if not self.paths:
            print("Warning: No paths found in SVG!", file=sys.stderr)
            return ""

        z_down = int(-self.depth_mm * UNITS_PER_MM)
        lines = []

        # Header
        lines.append(f"IN;")                       # Initialize
        lines.append(f"!MC1;")                      # Spindle ON
        lines.append(f"PA;")                        # Absolute coordinates
        lines.append(f"VS{self.feed_rate};")        # Feed rate
        lines.append(f"!PZ{z_down},{SAFE_Z_UP};")  # Z positions

        # Generate toolpaths
        for path in self.paths:
            if len(path) < 2:
                continue

            # Move to start of path with tool up
            x0, y0 = path[0]
            lines.append(f"PU{int(x0)},{int(y0)};")

            # Engrave along path with tool down
            for x, y in path[1:]:
                lines.append(f"PD{int(x)},{int(y)};")

            # Lift tool at end of path
            lines.append("PU;")

        # Footer
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

    def preview(self):
        """Show a matplotlib preview of the toolpaths."""
        try:
            import matplotlib.pyplot as plt
        except ImportError:
            print("matplotlib is required for preview: pip install matplotlib")
            return

        fig, ax = plt.subplots(1, 1, figsize=(10, 8))

        for i, path in enumerate(self.paths):
            xs = [p[0] / UNITS_PER_MM for p in path]
            ys = [p[1] / UNITS_PER_MM for p in path]
            ax.plot(xs, ys, linewidth=0.8)

        ax.set_xlabel('X (mm)')
        ax.set_ylabel('Y (mm)')
        ax.set_title('EGX-300 Toolpath Preview')
        ax.set_aspect('equal')
        ax.grid(True, alpha=0.3)

        # Show machine limits
        ax.axhline(y=0, color='r', linestyle='--', alpha=0.3)
        ax.axvline(x=0, color='r', linestyle='--', alpha=0.3)
        ax.axhline(y=MAX_Y_MM, color='r', linestyle='--', alpha=0.3)
        ax.axvline(x=MAX_X_MM, color='r', linestyle='--', alpha=0.3)

        plt.tight_layout()
        plt.show()


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
                        help='Show matplotlib preview')
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
    )

    print(f"Loading {args.svg_file}...")
    converter.load_svg_svgpathtools(args.svg_file)
    converter.print_info()

    if args.info_only:
        return

    if args.preview:
        converter.preview()
        return

    # Generate commands
    camm_commands = converter.generate_camm()

    if not camm_commands:
        print("No commands generated. Check your SVG has paths.")
        sys.exit(1)

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
                with open(args.device, 'wb') as dev:
                    dev.write(camm_commands.encode('ascii'))
                    dev.flush()
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
