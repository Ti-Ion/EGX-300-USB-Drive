# EGX-300 Linux Toolkit

A set of Python tools for driving a Roland EGX-300 desktop engraver from Linux via USB-to-parallel cable.

## Reference documentation

The Roland EGX-300 programmer's guide (CAMM-GL II command set) is the
authoritative reference for the commands these tools emit and can be found at: https://downloadcenter.rolanddg.com/contents/manuals/CAMM-GL2_PRO_EN_R1.pdf
As well as the general use guide found at: https://downloadcenter.rolanddg.com/contents/manuals/EGX-300_USE_EN_R3.pdf

## Setup

The Python tools here run in the `egx-env` conda environment on this machine
(svgpathtools, numpy, optional matplotlib are installed there). Activate it
before running any script:

```bash
conda activate egx-env
```

If you're setting things up on a new machine instead:

```bash
# Required for SVG conversion
pip install svgpathtools numpy

# Optional, for preview plots
pip install matplotlib

# Ensure your user can access the device
sudo usermod -aG lp $USER
# Then log out and back in
```

## Tools

| Tool | Purpose |
|------|---------|
| `egx_send.py` | Send raw CAMM-GL II commands, interactive mode, file sending |
| `svg2egx.py` | Convert SVG → CAMM-GL II (main design pipeline) |
| `gcode2egx.py` | Convert G-code → CAMM-GL II (for CAM software output) |
| `camm2html.py` | Render a `.camm` toolpath as an interactive 3D HTML viewer |
| `fetch_three.py` | Download three.min.js into `viewer-output/` (one-time setup for the viewer) |

## Quick Start

```bash
# Test machine communication
python3 egx_send.py "IN;"

# Interactive mode - great for testing
python3 egx_send.py -i

# Convert and engrave an SVG
python3 svg2egx.py design.svg --preview          # Check it first
python3 svg2egx.py design.svg --depth 0.2 --send # Engrave it

# Inspect a .camm file in a 3D browser viewer
python3 camm2html.py toolpath.camm
```

---

## Inspecting toolpaths (`camm2html.py`)

Renders any `.camm` file (the output of `svg2egx.py` / `gcode2egx.py`, or raw
CAMM-GL II you wrote by hand) as a self-contained HTML page you can open in a
browser. The viewer lets you orbit/zoom in 3D, scrub a time window over the
move sequence to see machining order, exaggerate the Z axis to inspect plunges
and lifts, and toggle rapids on/off.

### Usage

```bash
# One-time: fetch the three.js library used by the viewer
python3 fetch_three.py
# -> downloads viewer-output/three.min.js (~600 KB, then works offline)

# Save SVG/G-code conversion as a .camm file first
python3 svg2egx.py design.svg -o design.camm
# (or: python3 gcode2egx.py toolpath.gcode -o toolpath.camm)

# Generate the viewer
python3 camm2html.py design.camm
# -> writes viewer-output/design.html, prints a file:// URL

# Custom output location
python3 camm2html.py design.camm -o /tmp/preview.html
```

The generated HTML references `viewer-output/three.min.js` via a relative path,
so if you move an HTML file keep that library reachable from its new location.
`camm2html.py` will exit with an error if `three.min.js` is missing — re-run
`fetch_three.py` to grab it.

### Viewer controls

- **Drag** to rotate, **shift+drag** to pan, **wheel** to zoom.
- **Window start / end** sliders restrict which segments are drawn — useful for
  stepping through a long job to see machining order (color goes purple → yellow
  across the visible window).
- **Z exaggeration** stretches the Z axis up to 200× so shallow cuts and rapid
  lifts become visible.
- **Show rapids** toggles non-cutting moves; **Ghost full path** keeps a faint
  outline of the whole job visible while the window is restricted.

---

## Workflow 1: Inkscape (Recommended for most work)

This is the most versatile workflow for signs, logos, artwork, and text.

### Steps

1. **Open Inkscape**, set document units to **mm** (File > Document Properties).
   Set the document size to match your material (max 305 x 230 mm).

2. **Design your engraving.** Use shapes, text, bezier paths, imported images
   (traced to vectors), whatever you want.

3. **Convert everything to paths:**
   - Select all (Ctrl+A)
   - Path > Object to Path (Shift+Ctrl+C)
   - For text: this converts each letter into vector outlines

4. **Save as Plain SVG** (File > Save As > Plain SVG).

5. **Convert and preview:**
   ```bash
   python3 svg2egx.py design.svg --preview
   ```

6. **Engrave:**
   ```bash
   python3 svg2egx.py design.svg --depth 0.3 --feed 8 --send
   ```

### Tips for Inkscape

- **For filled shapes**, Inkscape will give you the outline path. If you want
  area fills, you'll need hatching — use Extensions > Generate from Path >
  Hatch Fill to create fill lines inside shapes.
- **Trace bitmaps** with Path > Trace Bitmap to convert photos/logos to vectors.
- **Use layers** to organize cuts at different depths — export each layer as
  a separate SVG and engrave with different `--depth` values.
- **Offset your design** from the origin to match where your material sits:
  ```bash
  python3 svg2egx.py design.svg --offset-x 10 --offset-y 10 --send
  ```
- **Non-mm SVGs** (browser exports, raw px, in/cm) — the converter auto-detects
  the unit from the SVG's `viewBox` + `width`. If detection fails it errors out;
  pass `--svg-units {mm,px,in,cm,pt}` to force a unit.

---

## Workflow 2: FreeCAD + Path Workbench (For CAM / precise machining)

Best for precision work, 3D profiling, pocketing, and PCB milling.

### Steps

1. **Design in FreeCAD** (or import a DXF/STEP file).

2. **Switch to the Path Workbench.**

3. **Create a Job:**
   - Set stock dimensions to match your material
   - Set the machine coordinate system appropriately

4. **Add operations:**
   - Profile (follow an outline)
   - Pocket (clear an area)
   - Engrave (V-carve text)
   - Drill (holes)

5. **Set tool and feeds:**
   - Match the cutter diameter to what's in your EGX-300
   - Set appropriate depth of cut and feed rate

6. **Post-process to G-code:**
   - Path > Post Process
   - Use the "grbl" or "linuxcnc" post-processor
   - Save as .gcode

7. **Convert and send:**
   ```bash
   python3 gcode2egx.py toolpath.gcode --preview    # Check first
   python3 gcode2egx.py toolpath.gcode -o job.camm   # Convert
   python3 egx_send.py -f job.camm                    # Send
   ```

---

## Workflow 3: FlatCAM (For PCB isolation milling)

### Steps

1. **Export Gerber files** from your PCB design tool (KiCad, Eagle, etc.).

2. **Open in FlatCAM:**
   - Load the copper layer Gerber
   - Load the drill file (Excellon)
   - Load the board outline Gerber

3. **Generate isolation routing:**
   - Select the copper Gerber
   - Tool > Isolation Routing
   - Set tool diameter to match your V-bit
   - Set cut depth (typically 0.1mm for isolation)

4. **Generate drill file** if needed.

5. **Export as G-code** (CNC Job > Export G-code).

6. **Convert and send:**
   ```bash
   python3 gcode2egx.py board_iso.gcode --z-threshold 0 -o board.camm
   python3 egx_send.py -f board.camm
   ```

---

## Workflow 4: Code / Command Line (Programmatic engraving)

For parametric designs, data-driven engraving, batch production.

### Direct CAMM-GL II

```python
#!/usr/bin/env python3
"""Example: Engrave a grid of rectangles."""

DEVICE = '/dev/usb/lp0'
UNITS = 100  # per mm

def rect(x_mm, y_mm, w_mm, h_mm):
    """Generate commands for a rectangle."""
    x, y, w, h = [int(v * UNITS) for v in (x_mm, y_mm, w_mm, h_mm)]
    return (
        f"PU{x},{y};"
        f"PD{x+w},{y};"
        f"PD{x+w},{y+h};"
        f"PD{x},{y+h};"
        f"PD{x},{y};"
        f"PU;"
    )

commands = "IN;!MC1;PA;VS10;!PZ-20,500;"

# Grid of 5x4 rectangles, 10mm apart
for row in range(4):
    for col in range(5):
        commands += rect(10 + col * 15, 10 + row * 15, 10, 10)

commands += "!MC0;PU0,0;"

with open(DEVICE, 'wb') as dev:
    dev.write(commands.encode('ascii'))
```

### Using Python + matplotlib to generate designs

```python
#!/usr/bin/env python3
"""Example: Engrave text using matplotlib font rendering."""
import matplotlib
matplotlib.use('Agg')
from matplotlib.textpath import TextPath
from matplotlib.font_manager import FontProperties

UNITS = 100

def text_to_camm(text, x_mm, y_mm, size_mm, font='sans-serif'):
    """Convert text to CAMM-GL II using matplotlib's font engine."""
    fp = FontProperties(family=font, size=size_mm)
    tp = TextPath((0, 0), text, prop=fp)
    
    commands = ""
    for vertices, codes in tp.iter_segments():
        # codes: 1=MOVETO, 2=LINETO, 3=CURVE3, 4=CURVE4, 79=CLOSEPOLY
        if codes == 1:  # MOVETO
            mx = int((x_mm + vertices[0]) * UNITS)
            my = int((y_mm + vertices[1]) * UNITS)
            commands += f"PU{mx},{my};"
        elif codes == 2:  # LINETO
            mx = int((x_mm + vertices[0]) * UNITS)
            my = int((y_mm + vertices[1]) * UNITS)
            commands += f"PD{mx},{my};"
        elif codes == 4:  # CURVE4 (cubic bezier - 3 points)
            # Simplified: just go to endpoint
            mx = int((x_mm + vertices[4]) * UNITS)
            my = int((y_mm + vertices[5]) * UNITS)
            commands += f"PD{mx},{my};"
        elif codes == 79:  # CLOSEPOLY
            commands += "PU;"
    
    return commands

cmds = "IN;!MC1;PA;VS8;!PZ-30,500;"
cmds += text_to_camm("Hello World", 10, 10, 12)
cmds += "!MC0;PU0,0;"

with open('/dev/usb/lp0', 'wb') as dev:
    dev.write(cmds.encode('ascii'))
```

---

## CAMM-GL II Command Reference (Common commands)

### Movement
| Command | Description | Example |
|---------|-------------|---------|
| `PU` | Pen/tool Up (move without cutting) | `PU1000,2000;` |
| `PD` | Pen/tool Down (move while cutting) | `PD3000,4000;` |
| `PA` | Set Absolute coordinate mode | `PA;` |
| `PR` | Set Relative coordinate mode | `PR;` |

### Machine Control
| Command | Description | Example |
|---------|-------------|---------|
| `IN` | Initialize (reset to defaults) | `IN;` |
| `!MC` | Motor Control (0=off, 1=on) | `!MC1;` |
| `!PZ` | Set Z positions (down, up) | `!PZ-50,500;` |
| `!NR` | Not Ready — pauses machine; resume with CONT key | `!NR;` |
| `VS` | Velocity/feed rate | `VS10;` |

### Coordinate System
| Command | Description | Example |
|---------|-------------|---------|
| `IP` | Set scaling points P1, P2 | `IP0,0,30500,23000;` |
| `SC` | Scale (set user coordinates) | `SC0,305,0,230;` |
| `IW` | Set clipping window | `IW0,0,30500,23000;` |

### Query (may not work via parallel)
| Command | Description |
|---------|-------------|
| `OA` | Output current position |
| `OE` | Output error |
| `OS` | Output status |

---

## Important Safety / Practical Notes

### Before your first real engrave:

1. **Test with tool UP first.** Run your design with `!PZ0,500;` (Z down = 0 = surface
   level, not below) so the tool moves through the path without touching material.
   Watch for unexpected movements or out-of-bounds travel.

2. **Start shallow.** Use `--depth 0.1` for your first real cut. You can always
   make another pass deeper.

3. **Secure your material.** Use double-sided tape or the machine's clamps.

4. **Set your Z origin correctly.** The machine's Z=0 should be at the material
   surface. Use the machine's control panel to jog Z down until the tool just
   touches the surface, then set that as Z0.

5. **Mind the spindle.** `!MC1;` turns it on and it will spin fast. Keep fingers
   clear, and make sure the protective cover is closed (the machine has a safety
   interlock).

6. **Feed rate matters.** Too fast on hard material = broken tool. Start with
   `VS5` (slow) and increase as you gain confidence. Softer materials (plastics,
   wood) can go faster than metals.

### Coordinate system:
- Origin (0,0) is at the front-left of the machine
- X increases to the right (max ~305mm = 30500 units)
- Y increases toward the back (max ~230mm = 23000 units)
- Z: negative values go into the material
- 100 machine units = 1 mm

### Common materials and suggested depths:
- **Engraving plastic (Rowmark etc.):** 0.2-0.5mm depth, VS 10-15
- **Acrylic:** 0.1-0.3mm per pass, VS 5-10
- **Brass/aluminum tags:** 0.05-0.1mm per pass, VS 3-5
- **Wood:** 0.3-0.5mm per pass, VS 8-12
- **PCB copper:** 0.05-0.15mm depth, VS 3-5
