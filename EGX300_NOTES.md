# EGX-300 / Toolkit Notes

Project-specific notes for the Roland EGX-300 desktop engraver and the
Python toolkit in this repo. For the language itself, see
`CAMM-GL2_REFERENCE.md`. For the full source spec, see `PROGRAMMERS_GUIDE.pdf`.

---

## Hardware constants

| What                       | Value                       | Where set in code        |
|----------------------------|-----------------------------|--------------------------|
| Units per mm (X/Y)         | 100                         | `UNITS_PER_MM` in both converters |
| Max travel X               | 305 mm (= 30 500 units)     | `MAX_X_MM`               |
| Max travel Y               | 230 mm (= 23 000 units)     | `MAX_Y_MM`               |
| Origin                     | front-left of bed           | —                        |
| Y direction                | + toward the back           | —                        |
| Z direction                | negative goes into material | —                        |
| Default safe Z (`Z2`)      | 500 (= 5 mm above surface)  | `SAFE_Z_UP`              |
| Device path                | `/dev/usb/lp0`              | `DEFAULT_DEVICE`         |
| Connection                 | USB→parallel; one-way       | —                        |

The "100 units = 1 mm" assumption can be confirmed live with the `OF` instruction
over a serial link (returns `100,100` on this model). Over parallel, you cannot
read the response — trust the constant.

---

## Init / shutdown patterns

### Safe init for testing (no cutting)
```
IN;!MC0;PA;VS10;!PZ0,500;
```
- `IN` resets defaults
- `!MC0` keeps spindle off
- `PA` absolute coords
- `VS10` moderate XY feed
- `!PZ0,500` "down" position is at the surface (Z=0, no plunge), "up" is 5 mm

This is what `egx_send.py --init` and the interactive `init` shortcut send
(`egx_send.py:50` and `:112`).

### Production cut header
```
IN;!MC1;PA;VS<feed>;!PZ<-depth_units>,500;
```
Spindle on, depth set from `--depth`. `svg2egx.py` builds this in
`generate_camm()` (`svg2egx.py:259-263`).

### Standard footer
```
PU;!MC0;PU0,0;
```
Lift, spindle off, return to origin. Both converters emit this.

---

## Coordinate conventions used in this repo

- All Python-side math is in **mm** until the final emission step, which
  multiplies by `UNITS_PER_MM` and casts to `int`.
- SVG Y is flipped: SVG origin is top-left, machine origin is bottom-left.
  `svg2egx.py` mirrors via `svg_height - y` (line 223), but **only if a
  viewBox or height attribute exists** — otherwise the design comes out
  upside-down silently.
- G-code Z is interpreted as a tool-up/down trigger via threshold
  (`gcode2egx.py:_handle_move`), not as a literal Z target. The actual cut
  depth is fixed by the single `!PZ` emitted in the header (`gcode2egx.py:206`).
  Multi-pass roughing is not honoured.

---

## Communication

- Output is **write-only** over `/dev/usb/lp0`. Any `OA`/`OE`/`OS` query in a
  CAMM stream is silently dropped — the machine will respond, but Linux
  receives nothing back.
- `egx_send.py` adds a 50 ms per-line delay (`chunk_delay=0.05`) when sending
  files, to avoid overflowing the parallel port FIFO. Long jobs (10 k+ lines)
  will take noticeably longer than the cut itself.
- The user must be in the `lp` group to write to `/dev/usb/lp0` (README:14-16).

---

## Safety practices baked in

- `interactive_mode` always sends `!MC0;` on exit (`egx_send.py:142`) — but
  only when the loop exits cleanly. An exception during `send_command` will
  skip it.
- `init` sets `!MC0` (spindle off) and `!PZ0,500` (no plunge) — it's
  explicitly designed as a dry-run-friendly initial state.
- `svg2egx.py` warns (but does **not** refuse) on out-of-bounds bbox or
  negative coordinates (`svg2egx.py:303-310`). `gcode2egx.py` doesn't even
  warn — caller must verify.
- README §"Safety / Practical Notes" (lines 275+) documents the
  test-with-tool-up workflow before any real cut.

---

## Material defaults (from README §Common materials)

| Material              | Depth        | VS feed |
|-----------------------|--------------|---------|
| Engraving plastic     | 0.2–0.5 mm   | 10–15   |
| Acrylic               | 0.1–0.3 mm   | 5–10    |
| Brass / aluminum tags | 0.05–0.1 mm  | 3–5     |
| Wood                  | 0.3–0.5 mm   | 8–12    |
| PCB copper isolation  | 0.05–0.15 mm | 3–5     |

VS units on EGX-300 are mm/sec for XY; `!VZ` is mm/sec for Z plunge.

---

## Known issues in the current scripts

These were found by reviewing the scripts against the manual on 2026-05-14.
Listed here so a future session can fix or work around them.

1. **`gcode2egx.py`: parsed `F` feed rate is never emitted as `VS`.**
   Stored in `self.feed_rate` (line 107) but no `commands.append(f"VS...")`.
   Machine uses whatever VS is in effect (default after `IN`).
2. **`gcode2egx.py`: hard-coded `!PZ` header ignores per-operation Z.**
   Cut depth is `threshold + 20 mm` regardless of what the G-code requests
   (`gcode2egx.py:206`). No `--depth` flag on this script.
3. **`svg2egx.py`: assumes 1 SVG unit = 1 mm.** Width/height/viewBox are
   read but only `svg_height` is used (for Y-flip). SVGs in px or with
   non-mm viewBoxes will scale wrong.
4. **`svg2egx.py`: `linearize_arc_segment` is dead code.** Arc handling in
   `load_svg_svgpathtools` (line 208) uses fixed `n_samples = 20`.
5. **Neither script refuses out-of-bounds output**, only warns.
6. **README inline matplotlib example** handles cubic-only and treats
   CURVE4 as endpoint-only — TrueType fonts (quadratics) will look chunky.

---

## Useful PDF page jumps

For when a session needs to read just one section instead of the whole PDF.
PDF page numbers are what the `Read` tool's `pages=N` argument uses.

| Topic                          | PDF pages |
|--------------------------------|-----------|
| Modes & syntax overview        | 8–15      |
| Coordinate / scaling concepts  | 15–17     |
| Tool / character control intro | 18–24     |
| mode1 reference (full)         | 25–48     |
| mode2 reference (full)         | 49–107    |
| Common `!` instructions        | 109–113   |
| `PA` / `PD` / `PR` / `PU`      | 86, 87, 88, 90 |
| `IN` / `DF` / `IP` / `SC` / `IW`| 70, 58, 71, 94, 72 |
| `VS` / `!PZ` / `!VZ` / `!MC`   | 103, 112, 113, 110 |
