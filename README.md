# EGX-300 Linux Toolkit

Python tools for driving a Roland EGX-300 desktop engraver from Linux over a USB-to-parallel cable. Convert SVG or G-code to CAMM-GL II, send jobs to the machine, and preview toolpaths in the browser.

As of now ONLY the SVG workflow has been tested. G-code is still Work In Progress. 

## Reference

- Roland EGX-300 programmer's guide (CAMM-GL II): https://downloadcenter.rolanddg.com/contents/manuals/CAMM-GL2_PRO_EN_R1.pdf
- EGX-300 user guide: https://downloadcenter.rolanddg.com/contents/manuals/EGX-300_USE_EN_R3.pdf
- Condensed in-repo command reference: [CAMM-GL2_REFERENCE.md](CAMM-GL2_REFERENCE.md)
- Hardware constants, init/shutdown patterns, materials chart: [EGX300_NOTES.md](EGX300_NOTES.md)

## Setup

```bash
pip install -r requirements.txt
python3 fetch_three.py    # one-time, downloads three.min.js for --preview

# Give your user write access to the parallel device
sudo usermod -aG lp $USER
# Then log out and back in
```

Default device is `/dev/usb/lp0`; override with `--device` on any tool.

## Tools

| Tool | Purpose |
|------|---------|
| `egx_send.py` | Send CAMM-GL II to the machine — single command, interactive REPL, or `.camm` file |
| `svg2egx.py` | SVG → CAMM-GL II (with `--preview` for an interactive 3D HTML viewer) |
| `gcode2egx.py` | G-code → CAMM-GL II (FreeCAD Path, FlatCAM, etc.) |
| `camm2html.py` | Render an existing `.camm` toolpath as an interactive 3D HTML viewer |
| `fetch_three.py` | One-time download of `three.min.js` for the viewer |

## Quick start

```bash
# Test communication with the machine
python3 egx_send.py "IN;"

# Interactive REPL, useful for jogging and testing
python3 egx_send.py -i

# Convert and engrave an SVG
python3 svg2egx.py design.svg --preview            # opens 3D viewer in viewer-output/
python3 svg2egx.py design.svg --depth 0.2 --send   # engrave

# Re-view a saved .camm file
python3 svg2egx.py design.svg -o design.camm
python3 camm2html.py design.camm                    # → viewer-output/design.html
```

---

## SVG workflow (Inkscape)

For signs, logos, artwork, text.

1. **Set up the document.** Units → mm. Size ≤ 305 × 230 mm (machine bed).
2. **Design freely.** Shapes, text, beziers, traced bitmaps — anything that becomes a path.
3. **Convert to paths.** Select all, then **Path → Object to Path** (Shift+Ctrl+C). Text becomes outlines.
4. **Save as Plain SVG** (File → Save As → Plain SVG).
5. **Preview, then send:**
   ```bash
   python3 svg2egx.py design.svg --preview            # writes viewer-output/design.html
   python3 svg2egx.py design.svg --depth 0.3 --feed 8 --send
   ```
   `--preview` prints a `file://` URL — open it to inspect the 3D toolpath, scrub the move window, and exaggerate Z to see plunges.

### Tips

- **Filled shapes.** Inkscape gives you outlines only. For solid fills, use **Extensions → Generate from Path → Hatch Fill** to create hatch lines inside each shape.
- **Multi-depth jobs.** Split your design across layers, export each as its own SVG, engrave with different `--depth` values.
- **Position on the bed.** `--offset-x 10 --offset-y 10` shifts everything 10 mm in from the origin.
- **Non-mm SVGs.** `svg2egx.py` auto-detects the unit from `viewBox` + `width`. If detection fails, force it with `--svg-units {mm,px,in,cm,pt}`.

---

## G-code workflow

Any CAM tool that emits G-code — FreeCAD Path (grbl/linuxcnc post-processor), FlatCAM (PCB isolation), etc.

```bash
python3 gcode2egx.py toolpath.gcode --preview
python3 gcode2egx.py toolpath.gcode -o job.camm
python3 egx_send.py -f job.camm
```

`gcode2egx.py` treats Z as a binary up/down trigger via threshold (`--z-threshold`, default 0 mm) rather than honoring per-move Z. Set actual cut depth on the machine or by hand-editing the emitted `!PZ` header. Multi-pass roughing from G-code is not respected — split it into separate jobs at different depths.

---

## Toolpath viewer (`camm2html.py`)

Renders a `.camm` file as a self-contained HTML page: orbit/zoom in 3D, scrub a window over the move sequence, exaggerate Z to inspect plunges, toggle rapids.

Both converters call this directly via `--preview`, so you only need `camm2html.py` on its own when re-viewing a saved `.camm` (or a `.camm` produced elsewhere).

```bash
python3 fetch_three.py                       # one-time, ~600 KB
python3 camm2html.py design.camm             # → viewer-output/design.html
python3 camm2html.py design.camm -o /tmp/preview.html
```

The HTML loads `three.min.js` via a relative path, so if you move the file keep the library reachable. Both `--preview` and `camm2html.py` error out if `three.min.js` is missing — rerun `fetch_three.py` to grab it.

**Controls:** drag = rotate, shift+drag = pan, wheel = zoom. Window start/end sliders restrict which segments are drawn (color sweeps purple → yellow across the visible range). Z-exaggeration goes up to 200× so shallow cuts and lifts become visible. "Ghost full path" keeps a faint outline of the whole job while the window is restricted.

---

## Before your first real cut

1. **Dry-run with the tool up.** Run with `!PZ0,500;` (Z-down = surface, no plunge) so the tool traces the path without touching material. Watch for surprise moves or out-of-bounds travel — `svg2egx.py` warns but does not refuse them.
2. **Start shallow.** `--depth 0.1` for first cuts; add deeper passes if needed.
3. **Set Z=0 at the material surface.** Jog Z down on the machine until the tool just touches, then zero it.
4. **Secure your material.** Double-sided tape or the bed clamps.
5. **Slow feeds on hard material.** Start with `VS5` (~5 mm/s) on metals; plastics and wood tolerate faster.
6. **Spindle on = `!MC1;`.** Keep the cover closed — there's a safety interlock.

### Coordinate system

- Origin (0, 0) at the front-left of the bed
- X → right, max ≈ 305 mm (30 500 machine units)
- Y → back, max ≈ 230 mm (23 000 machine units)
- Z negative → into material
- 100 machine units = 1 mm

Suggested depths and feeds per material live in [EGX300_NOTES.md](EGX300_NOTES.md).
