# CAMM-GL II Quick Reference

Condensed reference for the CAMM-GL II instruction set used by the Roland EGX-300
and other Roland CAMM/PNC devices. Source: `PROGRAMMERS_GUIDE.pdf` (115 pages).

References use both the manual's printed page label (e.g. `3-38`) and the
PDF page number (e.g. `PDF 86`) — the latter is what `Read` with `pages=N`
expects. Mapping (verified against the 115-page PDF): manual `1-N` = PDF
`N+6`, manual `2-N` = PDF `N+24`, manual `3-N` = PDF `N+48`, manual `4-N`
= PDF `N+108`.

---

## Concepts

### Two instruction modes (1-2 / PDF 8)
- **mode1**: 1-letter instructions (`H`, `D`, `M`, `I`...) terminated by `CR LF`.
  Compatible with older DXY-GL plotters.
- **mode2**: 2-letter instructions (`PA`, `PU`, `PD`, `VS`...) terminated by `;`.
  Richer, supports scaling/window/character control. **The scripts in this repo
  use mode2 exclusively.**
- **Common (`!XX`) instructions**: 3-char, work in either mode. Terminator follows
  the active mode (`CR LF` or `;`). The scripts use them with `;`.
- From mode1 you can call a single mode2 instruction with `^` prefix (2-24 / PDF 48).

### Syntax (1-3 to 1-7 / PDF 9-13)
- Format: `<instruction><param1>,<param2>...<terminator>`
- Delimiter between instruction and first param can be omitted (`PA5000,5000;`
  is fine). Delimiter between params **cannot** be omitted (use `,` or space).
- `+` sign on numbers is optional. Watch for sign-with-space pitfalls
  (`PA-_300,200` is parsed as 3 params and errors).
- Terminator can be omitted only when another instruction follows immediately.
  Best practice: always terminate.

### Coordinate systems (1-9 / PDF 15)
- **Machine coordinates**: fixed origin on the hardware.
- **Work coordinates**: user-settable origin (tool "home"); X/Y origin and Z0.
  This is what most operations use.
- **User coordinates**: scaled coords set by `IP` + `SC`. Until you call `SC`,
  all coords are in work coordinates.
- Default unit varies by model. EGX-300: **100 machine units = 1 mm** for X/Y.

### Tool up/down model (3-39 / PDF 87, 3-42 / PDF 90, 4-4 / PDF 112)
The CAMM has fixed Z1 (cutting depth) and Z2 (safe height) set once via `!PZ`.
`PU` raises tool to Z2; `PD` lowers to Z1. There is no continuous Z control —
to change cutting depth mid-job, re-issue `!PZ`.

### Defaults set by `IN` (3-22 / PDF 70) and `DF` (3-10 / PDF 58)
`IN` = `DF` + tool up + reset P1/P2 + clear errors. Highlights:
- Coord mode: absolute (`PA`)
- Line type: solid
- Window: full work area
- Hatching: bidirectional, 1% spacing of P1↔P2 diagonal
- Tool size (PT): 0.75 × 0.4 = 0.3 mm
- Spindle: ON
- Error mask: 223

---

## mode2 instructions (Chapter 3, PDF 49–107)

### Movement / drawing
| Code | Name              | Format                  | Notes                                                        | Page |
|------|-------------------|-------------------------|--------------------------------------------------------------|------|
| `PA` | Engrave Absolute  | `PA[x,y,...];`          | Sets absolute mode; with params, moves (engraves if down).   | 3-38 / PDF 86 |
| `PR` | Engrave Relative  | `PR[Δx,Δy,...];`        | Sets relative mode; with params, moves relative.             | 3-40 / PDF 88 |
| `PU` | Tool Up           | `PU[x,y,...];`          | Raises tool. With params, moves *while up*.                  | 3-42 / PDF 90 |
| `PD` | Tool Down         | `PD[x,y,...];`          | Lowers tool. With params, moves *while down* (cutting).      | 3-39 / PDF 87 |
| `AA` | Arc Absolute      | `AA cx,cy,θc[,θd];`     | Arc around (cx,cy), sweep θc°, chord-tol θd° (default 5°).   | 3-2 / PDF 50  |
| `AR` | Arc Relative      | `AR Δcx,Δcy,θc[,θd];`   | Same, center given relative to current position.             | 3-3 / PDF 51  |
| `CI` | Circle            | `CI r[,θd];`            | Full CCW circle, current position is centre.                 | 3-6 / PDF 54  |
| `EA` | Edge Rect Abs     | `EA x,y;`               | Rectangle from current pos to (x,y); returns to start.       | 3-15 / PDF 63 |
| `ER` | Edge Rect Rel     | `ER Δx,Δy;`             | Same, relative.                                              | 3-16 / PDF 64 |
| `RA` | Shade Rect Abs    | `RA x,y;`               | Filled rectangle (uses `FT`/`PT` for hatching).              | 3-43 / PDF 91 |
| `RR` | Shade Rect Rel    | `RR Δx,Δy;`             | Same, relative.                                              | 3-44 / PDF 92 |
| `EW` | Edge Wedge        | `EW r,θ1,θc[,θd];`      | Pie-slice outline.                                           | 3-18 / PDF 66 |
| `WG` | Shade Wedge       | `WG r,θ1,θc[,θd];`      | Filled pie-slice.                                            | 3-57 / PDF 105|

### Coordinate / window
| Code | Name           | Format                       | Notes                                                  | Page |
|------|----------------|------------------------------|--------------------------------------------------------|------|
| `IN` | Initialize     | `IN;`                        | Full reset (see Defaults above). Always safe to start. | 3-22 / PDF 70 |
| `DF` | Default        | `DF;`                        | Reset settings only (no tool-up, no P1/P2 reset).      | 3-10 / PDF 58 |
| `IP` | Input P1, P2   | `IP P1x,P1y[,P2x,P2y];`      | Sets scaling reference points (work coords).           | 3-23 / PDF 71 |
| `SC` | Scaling        | `SC Xmin,Xmax,Ymin,Ymax;`    | Maps P1↔P2 to user coords. `SC;` releases scaling.     | 3-46 / PDF 94 |
| `IW` | Input Window   | `IW LLx,LLy,URx,URy;`        | Clip rectangle. Out-of-window moves don't engrave.     | 3-24 / PDF 72 |
| `IM` | Input Mask     | `IM e;`                      | Error reporting mask (default 223).                    | 3-21 / PDF 69 |

### Tool / motion control
| Code | Name             | Format         | Notes                                                  | Page |
|------|------------------|----------------|--------------------------------------------------------|------|
| `VS` | Velocity Select  | `VS v;`        | XY feed rate (units/range vary by model; integer).     | 3-55 / PDF 103|
| `PT` | Tool Diameter    | `PT d;`        | Tool width for fill spacing. Actual mm = d × 0.4.      | 3-41 / PDF 89 |
| `FT` | Fill Type        | `FT n[,d[,θ]];`| n=1 bidi, 2 unidir, 3 hatch, 4 cross.                  | 3-20 / PDF 68 |
| `LT` | Line Type        | `LT n[,l];`    | Pattern n (-128..+127), pitch l (% of P1↔P2 diagonal). | 3-26 / PDF 74 |

### Character / labelling
| Code | Name                     | Format          | Notes                                                  | Page |
|------|--------------------------|-----------------|--------------------------------------------------------|------|
| `LB` | Label                    | `LB <chars>ETX` | Engrave string. Default terminator ETX (`CHR$(&H03)`). | 3-25 / PDF 73 |
| `DT` | Define Label Terminator  | `DT t;`         | Use a different label terminator.                      | 3-14 / PDF 62 |
| `SI` | Absolute Char Size       | `SI w,h;`       | cm = param × 0.4.                                      | 3-47 / PDF 95|
| `SR` | Relative Char Size       | `SR w,h;`       | % of P1↔P2 spans.                                      | 3-50 / PDF 98|
| `DI` | Absolute Direction       | `DI run,rise;`  | Char direction vector.                                 | 3-11 / PDF 59 |
| `DR` | Relative Direction       | `DR run,rise;`  | Direction as % of P1↔P2 spans.                         | 3-13 / PDF 61 |
| `SL` | Char Slant               | `SL tan(θ);`    | Italic.                                                | 3-48 / PDF 96|
| `ES` | Extra Space              | `ES w[,h];`     | Extra char/line spacing.                               | 3-17 / PDF 65 |
| `CS` | Standard Char Set        | `CS n;`         | Char set #.                                            | 3-9 / PDF 57  |
| `CA` | Alternate Char Set       | `CA n;`         |                                                        | 3-4 / PDF 52  |
| `SS` | Select Standard          | `SS;`           | Switch to standard set.                                | 3-51 / PDF 99|
| `SA` | Select Alternate         | `SA;`           | Switch to alternate.                                   | 3-45 / PDF 93 |
| `SM` | Symbol Mode              | `SM s;`         | Engrave symbol char at each PA/PR/PD point.            | 3-49 / PDF 97|
| `UC` | User Defined Char        | `UC c,Δx,Δy,…;` | Define + draw arbitrary char on 6×16 grid.             | 3-53 / PDF 101|
| `CC` | Char Chord Angle         | `CC θc;`        | Smoothness of arc-font characters (max 45°).           | 3-5 / PDF 53  |
| `CP` | Character Plot           | `CP nx,ny;`     | Move tool by N character cells.                        | 3-7 / PDF 55  |
| `WD` | Write to Display         | `WD <chars>ETX` | Show text on machine LCD (no engraving).               | 3-56 / PDF 104|

### Tick marks
| Code | Format            | Notes                                          | Page |
|------|-------------------|------------------------------------------------|------|
| `TL` | `TL lp[,lm];`     | Set tick lengths (% of P-spans).               | 3-52 / PDF 100|
| `XT` | `XT;`             | Engrave one X-axis tick at current position.   | 3-58 / PDF 106|
| `YT` | `YT;`             | Engrave one Y-axis tick at current position.   | 3-59 / PDF 107|

### Output (serial only — won't return data over parallel)
| Code | Returns                                 | Page          |
|------|-----------------------------------------|---------------|
| `OA` | Actual position (work coords): `X,Y,T`  | 3-28 / PDF 76 |
| `OC` | Commanded position (user coords)        | 3-29 / PDF 77 |
| `OE` | Error code (clears error)               | 3-30 / PDF 78 |
| `OF` | Machine units per mm                    | 3-31 / PDF 79 |
| `OH` | Hard-clip limits `LLx,LLy,URx,URy`      | 3-32 / PDF 80 |
| `OI` | Model identification string             | 3-33 / PDF 81 |
| `OO` | 8 option/hardware integers              | 3-34 / PDF 82 |
| `OP` | P1, P2 coordinates                      | 3-35 / PDF 83 |
| `OS` | Status byte (see bits below)            | 3-36 / PDF 84 |
| `OW` | Window LL/UR coordinates                | 3-37 / PDF 85 |

**OS status byte bits**: 0=tool down, 1=P1/P2 changed, 2=unused, 3=initialized,
4=ready-to-receive, 5=error occurred, 6/7=unused. Power-on value = 24 (8+16).

---

## Common (`!`) instructions (Chapter 4, PDF 109–113)

| Code  | Name                     | Format               | Notes                                                          | Page |
|-------|--------------------------|----------------------|----------------------------------------------------------------|------|
| `!MC` | Motor Control (spindle)  | `!MC[n];`            | `n=0` → off; any other value (or omitted) → on.                | 4-2 / PDF 110|
| `!NR` | **Not Ready** (pause)    | `!NR;`               | Pauses machine; resumes when operator presses CONT key.        | 4-3 / PDF 111|
| `!PZ` | Set Z1 & Z2              | `!PZ z1[,z2];`       | z1 = cutting depth, z2 = tool-up height (work coords).         | 4-4 / PDF 112|
| `!VZ` | Drill-Down Velocity      | `!VZ vz;`            | Z-axis feed rate, in mm/sec (model-dependent range).           | 4-5 / PDF 113|

> ⚠ The README in this repo previously called `!NR` "No Reset" — wrong. It is
> "Not Ready" / pause.

---

## mode1 instructions (Chapter 2, PDF 25–48)

Less commonly used directly when generating with mode2 converters. Brief list:

| Code | Name           | Format                | Page |
|------|----------------|-----------------------|------|
| `H`  | Home           | `H`                   | 2-2 / PDF 26  |
| `D`  | Draw (down)    | `D x1,y1,...;`        | 2-3 / PDF 27  |
| `M`  | Move (up)      | `M x1,y1,...;`        | 2-4 / PDF 28  |
| `I`  | Relative Draw  | `I Δx1,Δy1,...;`      | 2-5 / PDF 29  |
| `R`  | Relative Move  | `R Δx1,Δy1,...;`      | 2-6 / PDF 30  |
| `L`  | Line Type      | `L p` (p ∈ −5..+5)    | 2-7 / PDF 31  |
| `B`  | Line Scale     | `B l`                 | 2-9 / PDF 33  |
| `X`  | Axis           | `X p,q,r`             | 2-11 / PDF 35 |
| `P`  | Print char     | `P <chars>CR`         | 2-12 / PDF 36 |
| `S`  | Alpha Scale    | `S n`                 | 2-13 / PDF 37 |
| `Q`  | Alpha Rotate   | `Q n` (0..3 = 0/90/180/270°)| 2-14 / PDF 38 |
| `N`  | Mark symbol    | `N n` (1..15)         | 2-15 / PDF 39 |
| `C`  | Circle         | `C x,y,r,θ1,θ2[,θd]`  | 2-16 / PDF 40 |
| `E`  | Relative Circle| `E r,θ1,θ2[,θd]`      | 2-17 / PDF 41 |
| `A`  | Circle Center  | `A x,y`               | 2-18 / PDF 42 |
| `G`  | A+Circle       | `G r,θ1,θ2[,θd]`      | 2-19 / PDF 43 |
| `K`  | Pie wedge      | `K n,l1,l2`           | 2-20 / PDF 44 |
| `T`  | Hatching       | `T n,x,y,d,t`         | 2-22 / PDF 46 |
| `^`  | Call mode2     | `^<mode2 instr>`      | 2-24 / PDF 48 |

---

## Common pitfalls

- **Negative-number spacing**: `PA-300, 200` — the space after `-` makes it read
  as 3 params and errors (1-4 / PDF 10).
- **Missing terminator on last instruction**: machine waits forever for more
  data. Always end your stream with `;` (mode2) or `CR LF` (mode1).
- **`LB` without ETX**: subsequent instructions get engraved as text.
- **Output instructions over parallel**: `OA`/`OE`/etc. need a serial back-channel;
  they're documented as "for serial connection only" (see icons on those pages).
- **Z is fixed by `!PZ`**: there is no per-move Z. Multi-depth jobs require
  re-issuing `!PZ` between operations.
- **Scaling is sticky**: once `SC` is active, every coord is in user units until
  you call `SC;` (no params) to release.
