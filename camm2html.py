#!/usr/bin/env python3
"""
camm2html.py - Render a CAMM-GL II toolpath as an interactive 3D HTML viewer.

Parses a .camm file (the output of svg2egx.py / gcode2egx.py) and writes a
self-contained HTML page into viewer-output/, alongside a shared three.min.js.
The viewer lets you orbit/zoom in 3D, scrub a time window over the move
sequence, and see a color gradient over the visible cuts.

Usage:
    python3 camm2html.py toolpath.camm
    python3 camm2html.py toolpath.camm -o viewer/path.html

The viewer depends on three.min.js living in viewer-output/. Run
`python3 fetch_three.py` once to download it (or place a copy there yourself).
"""

import argparse
import json
import os
import re
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
DEFAULT_OUTPUT_DIR = SCRIPT_DIR / 'viewer-output'

UNITS_PER_MM = 100  # CAMM-GL II uses 0.01 mm units on the EGX-300
DEFAULT_Z_DOWN = -20  # machine units (-0.2 mm); overridden by !PZ
DEFAULT_Z_UP = 500    # machine units (5 mm)

THREE_FILENAME = "three.min.js"

# Segment type codes (kept compact in JSON)
CUT, RAPID, PLUNGE, LIFT = 0, 1, 2, 3

CMD_RE = re.compile(r'^(![A-Z]{2}|[A-Z]{2})(.*)$')
_SPLIT_RE = re.compile(r'[;\r\n]+')


def parse_params(s):
    s = s.strip()
    if not s:
        return []
    return [int(p) for p in s.split(',') if p.strip()]


def parse_camm(text):
    """Parse a CAMM-GL II command stream into a sequence of 3D segments.

    Returns a dict ready to embed as JSON:
        positions: flat [x,y,z, x,y,z, ...] in mm (one entry per vertex)
        types:     [t0, t1, ...] one per segment (= len(positions)/3 - 1)
        z_down_mm, z_up_mm: last seen Z heights (mm)
    """
    z_down = DEFAULT_Z_DOWN
    z_up = DEFAULT_Z_UP
    cx, cy, cz = 0, 0, z_up
    pen_down = False
    absolute = True

    positions = []
    types = []

    # 2 decimal places matches the machine resolution (100 units/mm = 0.01 mm).
    def push_initial_vertex():
        if not positions:
            positions.extend([
                round(cx / UNITS_PER_MM, 2),
                round(cy / UNITS_PER_MM, 2),
                round(cz / UNITS_PER_MM, 2),
            ])

    def emit(nx, ny, nz, t):
        nonlocal cx, cy, cz
        push_initial_vertex()
        positions.extend([
            round(nx / UNITS_PER_MM, 2),
            round(ny / UNITS_PER_MM, 2),
            round(nz / UNITS_PER_MM, 2),
        ])
        types.append(t)
        cx, cy, cz = nx, ny, nz

    for raw in _SPLIT_RE.split(text):
        cmd_text = raw.strip()
        if not cmd_text:
            continue
        m = CMD_RE.match(cmd_text)
        if not m:
            continue
        cmd, params_str = m.group(1), m.group(2)
        params = parse_params(params_str)

        if cmd == 'IN':
            cx, cy, cz = 0, 0, z_up
            pen_down = False
            absolute = True
        elif cmd == 'PA':
            absolute = True
        elif cmd == 'PR':
            absolute = False
        elif cmd == '!PZ' and len(params) >= 2:
            z_down, z_up = params[0], params[1]
        elif cmd == 'PU':
            if pen_down:
                emit(cx, cy, z_up, LIFT)
                pen_down = False
            for i in range(0, len(params) - 1, 2):
                px, py = params[i], params[i + 1]
                if not absolute:
                    px, py = cx + px, cy + py
                emit(px, py, z_up, RAPID)
        elif cmd == 'PD':
            if not pen_down:
                emit(cx, cy, z_down, PLUNGE)
                pen_down = True
            for i in range(0, len(params) - 1, 2):
                px, py = params[i], params[i + 1]
                if not absolute:
                    px, py = cx + px, cy + py
                emit(px, py, z_down, CUT)
        # Other commands (VS, !MC, IP, SC, IW, !NR, ...) don't affect geometry.

    return {
        'positions': positions,
        'types': types,
        'z_down_mm': z_down / UNITS_PER_MM,
        'z_up_mm': z_up / UNITS_PER_MM,
    }


def locate_three_js():
    """Return the vendored three.min.js in viewer-output/.

    Raises FileNotFoundError if missing so library callers can present their
    own error; main() catches and translates to a CLI-friendly message.
    """
    path = DEFAULT_OUTPUT_DIR / THREE_FILENAME
    if not path.exists():
        raise FileNotFoundError(
            f"{path} not found. Run `python3 fetch_three.py` to download it."
        )
    return path


def relative_import_path(output_html, three_js_path):
    """Path used in the HTML's `import` statement, relative to the HTML file."""
    rel = os.path.relpath(three_js_path, start=output_html.parent)
    # ES module specifiers must start with ./ or ../ for relative paths.
    if not rel.startswith(('.', '/')):
        rel = './' + rel
    return rel


HTML_TEMPLATE = r"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>EGX-300 Toolpath: __TITLE__</title>
<style>
  html, body { margin: 0; padding: 0; height: 100%; overflow: hidden;
               background: #111; color: #eee;
               font: 13px/1.4 system-ui, -apple-system, sans-serif; }
  #c { position: fixed; inset: 0; display: block; }
  #panel { position: fixed; top: 12px; left: 12px; background: rgba(20,20,22,0.85);
           padding: 10px 14px; border-radius: 8px; width: 460px;
           box-sizing: border-box; border: 1px solid #2a2a2e; }
  #panel h1 { font-size: 13px; font-weight: 600; margin: 0 0 8px;
              opacity: 0.9; letter-spacing: 0.02em;
              white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
  .row { display: flex; align-items: center; gap: 8px; margin: 6px 0;
         font-size: 12px; min-width: 0; }
  .row label { flex: 0 0 110px; opacity: 0.75; }
  .row input[type=range] { flex: 1 1 auto; min-width: 0; }
  input.num { font-variant-numeric: tabular-nums; font: inherit;
              flex: 0 0 64px; width: 64px; text-align: right;
              background: #1a1a1c; color: #eee; border: 1px solid #333;
              border-radius: 4px; padding: 2px 4px; box-sizing: border-box; }
  input.num:focus { outline: none; border-color: #5599ff; }
  input.num::-webkit-outer-spin-button,
  input.num::-webkit-inner-spin-button { -webkit-appearance: none; margin: 0; }
  input.num[type=number] { -moz-appearance: textfield; }
  #legend { position: fixed; bottom: 12px; left: 12px; background: rgba(20,20,22,0.85);
            padding: 8px 12px; border-radius: 8px; font-size: 11px;
            border: 1px solid #2a2a2e; }
  .swatch { display: inline-block; width: 12px; height: 12px; vertical-align: middle;
            margin-right: 4px; border-radius: 2px; }
  #help { position: fixed; bottom: 12px; right: 12px; opacity: 0.5; font-size: 11px;
          background: rgba(20,20,22,0.85); padding: 6px 10px; border-radius: 8px;
          border: 1px solid #2a2a2e; }
</style>
</head>
<body>
<canvas id="c"></canvas>
<div id="panel">
  <h1>EGX-300 Toolpath &mdash; __TITLE__</h1>
  <div class="row"><label>Window start</label>
    <input id="winStart" type="range" min="0" max="100" value="0">
    <input id="winStartNum" class="num" type="number" min="0" max="100" value="0"></div>
  <div class="row"><label>Window end</label>
    <input id="winEnd" type="range" min="0" max="100" value="100">
    <input id="winEndNum" class="num" type="number" min="0" max="100" value="100"></div>
  <div class="row"><label>Z exaggeration</label>
    <input id="zExag" type="range" min="1" max="50" value="1">
    <input id="zExagNum" class="num" type="number" min="1" max="200" value="1"></div>
  <div class="row"><label><input id="showRapid" type="checkbox" checked> Show rapids</label></div>
  <div class="row"><label><input id="showBg" type="checkbox" checked> Ghost full path</label></div>
  <div class="row"><span id="stats" style="opacity:0.7; font-size:11px;"></span></div>
</div>
<div id="legend">
  <span class="swatch" style="background:#e83e8c"></span>start &nbsp;
  <span class="swatch" style="background:#21908d"></span>middle &nbsp;
  <span class="swatch" style="background:#fde725"></span>end &nbsp; | &nbsp;
  <span class="swatch" style="background:#666"></span>rapid (desaturated)
</div>
<div id="help">drag = rotate &middot; shift+drag = pan &middot; wheel = zoom</div>

<script>window.TOOLPATH = __DATA__;</script>
<script src="__THREE_PATH__"></script>
<script>
__VIEWER_JS__
</script>
</body>
</html>
"""


VIEWER_JS = r"""
(() => {
  const data = window.TOOLPATH;
  const positions = data.positions;
  const types = data.types;
  const nVerts = positions.length / 3;
  const nSegs = types.length;
  if (nSegs === 0) {
    document.body.insertAdjacentHTML('beforeend',
      '<div style="position:fixed;inset:0;display:flex;align-items:center;justify-content:center;">No segments parsed from this .camm file.</div>');
    return;
  }

  // Pre-build LineSegments arrays: each segment = 2 consecutive vertices.
  const segPos = new Float32Array(nSegs * 2 * 3);
  const segType = new Uint8Array(nSegs);
  for (let i = 0; i < nSegs; i++) {
    const a = i * 3, b = (i + 1) * 3;
    segPos[i*6+0] = positions[a+0];
    segPos[i*6+1] = positions[a+1];
    segPos[i*6+2] = positions[a+2];
    segPos[i*6+3] = positions[b+0];
    segPos[i*6+4] = positions[b+1];
    segPos[i*6+5] = positions[b+2];
    segType[i] = types[i];
  }
  const segColor = new Float32Array(nSegs * 2 * 3);

  // Bounds
  let minX=Infinity, maxX=-Infinity, minY=Infinity, maxY=-Infinity;
  for (let i = 0; i < nVerts; i++) {
    const x = positions[i*3], y = positions[i*3+1];
    if (x < minX) minX = x; if (x > maxX) maxX = x;
    if (y < minY) minY = y; if (y > maxY) maxY = y;
  }
  const cx = (minX + maxX) / 2, cy = (minY + maxY) / 2;
  const sizeXY = Math.max(maxX - minX, maxY - minY, 50);

  // Three.js setup
  const canvas = document.getElementById('c');
  const renderer = new THREE.WebGLRenderer({canvas, antialias: true});
  renderer.setPixelRatio(window.devicePixelRatio);
  renderer.setSize(window.innerWidth, window.innerHeight);

  const BG = 0x111111;
  const scene = new THREE.Scene();
  scene.background = new THREE.Color(BG);

  const camera = new THREE.PerspectiveCamera(45, window.innerWidth/window.innerHeight, 0.1, 10000);
  camera.up.set(0, 0, 1);

  // Hand-rolled orbit controls (rotate/pan/zoom) so we don't need OrbitControls.js.
  let theta = -Math.PI/3, phi = Math.PI/3, radius = sizeXY * 1.4;
  const target = new THREE.Vector3(cx, cy, 0);
  function updateCam() {
    const x = target.x + radius * Math.sin(phi) * Math.cos(theta);
    const y = target.y + radius * Math.sin(phi) * Math.sin(theta);
    const z = target.z + radius * Math.cos(phi);
    camera.position.set(x, y, z);
    camera.lookAt(target);
  }
  let dragging = false, panning = false, lx = 0, ly = 0;
  canvas.addEventListener('mousedown', e => {
    if (e.button !== 0) return;
    if (e.shiftKey) panning = true;
    else dragging = true;
    lx = e.clientX; ly = e.clientY;
  });
  window.addEventListener('mouseup', () => { dragging = false; panning = false; });
  window.addEventListener('mousemove', e => {
    if (!dragging && !panning) return;
    const dx = e.clientX - lx, dy = e.clientY - ly;
    lx = e.clientX; ly = e.clientY;
    if (dragging) {
      theta -= dx * 0.005;
      phi = Math.max(0.05, Math.min(Math.PI - 0.05, phi - dy * 0.005));
    } else {
      const right = new THREE.Vector3(-Math.sin(theta), Math.cos(theta), 0);
      const upv = new THREE.Vector3(0, 0, 1);
      const f = radius * 0.0015;
      target.addScaledVector(right, -dx * f);
      target.addScaledVector(upv, dy * f);
    }
    updateCam(); render();
  });
  canvas.addEventListener('wheel', e => {
    e.preventDefault();
    radius *= Math.exp(e.deltaY * 0.001);
    radius = Math.max(1, Math.min(sizeXY * 20, radius));
    updateCam(); render();
  }, {passive: false});

  // Reference geometry: machine bed + grid + axis lines.
  const machineW = 305, machineH = 230;
  const bedGeo = new THREE.PlaneGeometry(machineW, machineH);
  const bedMat = new THREE.MeshBasicMaterial({color: 0x1a1a1c, transparent: true,
                                              opacity: 0.6, side: THREE.DoubleSide});
  const bed = new THREE.Mesh(bedGeo, bedMat);
  bed.position.set(machineW/2, machineH/2, 0);
  scene.add(bed);

  const grid = new THREE.GridHelper(Math.max(machineW, machineH),
                                    Math.round(Math.max(machineW, machineH)/10),
                                    0x303034, 0x252528);
  grid.rotateX(Math.PI/2);
  grid.position.set(machineW/2, machineH/2, 0.01);
  scene.add(grid);

  function axisLine(from, to, color) {
    const g = new THREE.BufferGeometry().setFromPoints(
      [from, to].map(p => new THREE.Vector3(...p)));
    return new THREE.Line(g, new THREE.LineBasicMaterial({color}));
  }
  scene.add(axisLine([0,0,0], [25,0,0], 0xff5555)); // X red
  scene.add(axisLine([0,0,0], [0,25,0], 0x55ff55)); // Y green
  scene.add(axisLine([0,0,0], [0,0,25], 0x5599ff)); // Z blue

  // Background ("ghost") line: every segment, faint.
  const bgGeo = new THREE.BufferGeometry();
  bgGeo.setAttribute('position', new THREE.BufferAttribute(segPos, 3));
  const bgMat = new THREE.LineBasicMaterial({color: 0x444448, transparent: true, opacity: 0.4});
  const bgLines = new THREE.LineSegments(bgGeo, bgMat);
  scene.add(bgLines);

  // Foreground line: per-vertex colors, recomputed when window changes.
  const fgGeo = new THREE.BufferGeometry();
  fgGeo.setAttribute('position', new THREE.BufferAttribute(segPos, 3));
  fgGeo.setAttribute('color', new THREE.BufferAttribute(segColor, 3));
  const fgMat = new THREE.LineBasicMaterial({vertexColors: true});
  const fgLines = new THREE.LineSegments(fgGeo, fgMat);
  scene.add(fgLines);

  // Viridis-ish gradient stops: [t, [r,g,b]]
  const stops = [
    [0.00, [0.910, 0.243, 0.549]],
    [0.25, [0.229, 0.322, 0.546]],
    [0.50, [0.127, 0.567, 0.551]],
    [0.75, [0.369, 0.788, 0.382]],
    [1.00, [0.992, 0.906, 0.144]],
  ];
  function gradient(t) {
    if (t <= 0) return stops[0][1];
    if (t >= 1) return stops[stops.length-1][1];
    for (let i = 0; i < stops.length - 1; i++) {
      const a = stops[i], b = stops[i+1];
      if (t <= b[0]) {
        const k = (t - a[0]) / (b[0] - a[0]);
        return [
          a[1][0]*(1-k) + b[1][0]*k,
          a[1][1]*(1-k) + b[1][1]*k,
          a[1][2]*(1-k) + b[1][2]*k,
        ];
      }
    }
    return [1,1,1];
  }

  // Hidden segments are painted to match the scene background.
  const HIDDEN_R = ((BG >> 16) & 0xff) / 255;
  const HIDDEN_G = ((BG >>  8) & 0xff) / 255;
  const HIDDEN_B = ( BG        & 0xff) / 255;

  // State + UI
  let zExag = 1, winStart = 0, winEnd = nSegs;
  let showRapid = true, showBg = true;

  // Matches Python-side RAPID=1, PLUNGE=2, LIFT=3 (CUT=0 is the only "ish-not").
  function isRapidish(t) { return t === 1 || t === 2 || t === 3; }

  function updateColors() {
    const span = Math.max(1, winEnd - winStart - 1);
    for (let i = 0; i < nSegs; i++) {
      const inWin = (i >= winStart && i < winEnd);
      const rapid = isRapidish(segType[i]);
      let r, g, b;
      if (inWin && (showRapid || !rapid)) {
        const f = (i - winStart) / span;
        const c = gradient(f);
        if (rapid) {
          // Desaturate rapids toward gray so cuts pop.
          r = c[0]*0.35 + 0.5*0.65;
          g = c[1]*0.35 + 0.5*0.65;
          b = c[2]*0.35 + 0.5*0.65;
        } else {
          r = c[0]; g = c[1]; b = c[2];
        }
      } else {
        r = HIDDEN_R; g = HIDDEN_G; b = HIDDEN_B;
      }
      const o = i * 6;
      segColor[o+0] = r; segColor[o+1] = g; segColor[o+2] = b;
      segColor[o+3] = r; segColor[o+4] = g; segColor[o+5] = b;
    }
    fgGeo.attributes.color.needsUpdate = true;
    bgLines.visible = showBg;
  }

  function applyZExag() {
    fgLines.scale.set(1, 1, zExag);
    bgLines.scale.set(1, 1, zExag);
  }

  // Wire up controls
  const $ = id => document.getElementById(id);
  const winStartEl = $('winStart'), winEndEl = $('winEnd'), zExagEl = $('zExag');
  const winStartNum = $('winStartNum'), winEndNum = $('winEndNum'), zExagNum = $('zExagNum');
  const showRapidEl = $('showRapid'), showBgEl = $('showBg');
  const statsEl = $('stats');

  // Range/number pairs: each shares min/max and stays in sync.
  const pairs = [
    [winStartEl, winStartNum, 0, nSegs],
    [winEndEl,   winEndNum,   0, nSegs],
    [zExagEl,    zExagNum,    1, 200],   // slider tops out at 50; box accepts up to 200
  ];
  for (const [slider, num, min, max] of pairs) {
    slider.min = min; slider.max = max;
    num.min = min;    num.max = max;
  }
  winEndEl.value = nSegs; winEndNum.value = nSegs;

  function clampNum(num, min, max) {
    let v = parseFloat(num.value);
    if (!isFinite(v)) v = min;
    v = Math.max(min, Math.min(max, Math.round(v)));
    num.value = v;
    return v;
  }

  function refresh() {
    const a = +winStartEl.value, b = +winEndEl.value;
    winStart = Math.min(a, b);
    winEnd = Math.max(a, b);
    zExag = +zExagEl.value;
    showRapid = showRapidEl.checked;
    showBg = showBgEl.checked;
    statsEl.textContent = `${nSegs.toLocaleString()} segments • showing ${(winEnd - winStart).toLocaleString()}`;
    applyZExag();
    updateColors();
    render();
  }

  for (const [slider, num, min, max] of pairs) {
    slider.addEventListener('input', () => { num.value = slider.value; refresh(); });
    // Update slider while typing; clamp on blur/Enter so partial values aren't reset mid-edit.
    num.addEventListener('input', () => {
      const v = parseFloat(num.value);
      if (isFinite(v)) {
        slider.value = Math.max(min, Math.min(+slider.max, v));
        refresh();
      }
    });
    num.addEventListener('change', () => {
      const v = clampNum(num, min, max);
      slider.value = Math.max(+slider.min, Math.min(+slider.max, v));
      refresh();
    });
  }
  [showRapidEl, showBgEl].forEach(el => el.addEventListener('input', refresh));

  function render() { renderer.render(scene, camera); }
  window.addEventListener('resize', () => {
    renderer.setSize(window.innerWidth, window.innerHeight);
    camera.aspect = window.innerWidth / window.innerHeight;
    camera.updateProjectionMatrix();
    render();
  });

  updateCam();
  refresh();
})();
"""


def default_output_path(stem):
    """Default location for a generated viewer: viewer-output/<stem>.html."""
    return DEFAULT_OUTPUT_DIR / (stem + '.html')


def render_html(camm_text, out_path, title=None):
    """Render CAMM-GL II command text as an interactive HTML viewer.

    Parses `camm_text`, builds the standalone HTML page, and writes it to
    `out_path` (parent directories are created as needed). The page imports
    three.min.js via a relative path, so the vendored copy in viewer-output/
    must exist — a missing copy raises FileNotFoundError.

    Returns the parsed data dict (positions/types/z heights) so callers can
    print segment counts or warn on empty input without re-parsing.
    """
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    data = parse_camm(camm_text)
    three_js = locate_three_js()
    three_path = relative_import_path(out_path.resolve(), three_js)

    html = (HTML_TEMPLATE
            .replace('__TITLE__', title or out_path.stem)
            .replace('__DATA__', json.dumps(data, separators=(',', ':')))
            .replace('__THREE_PATH__', three_path)
            .replace('__VIEWER_JS__', VIEWER_JS))
    out_path.write_text(html)
    return data


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('camm_file', help='Input .camm file')
    ap.add_argument('-o', '--output', help='Output HTML (default: viewer-output/<input>.html)')
    args = ap.parse_args()

    in_path = Path(args.camm_file)
    if not in_path.exists():
        print(f"ERROR: file not found: {in_path}", file=sys.stderr)
        sys.exit(1)

    out_path = Path(args.output) if args.output else default_output_path(in_path.stem)

    try:
        data = render_html(in_path.read_text(), out_path, title=in_path.name)
    except FileNotFoundError as e:
        print(f"ERROR: {e}", file=sys.stderr)
        sys.exit(1)

    n_seg = len(data['types'])
    print(f"Parsed {n_seg} segments from {in_path}")
    if n_seg == 0:
        print("WARNING: no PU/PD commands found.", file=sys.stderr)
    print(f"Wrote viewer to {out_path}")
    print(f"Open: file://{out_path.resolve()}")


if __name__ == '__main__':
    main()
