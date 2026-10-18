# RCT Cycles Graphics

A Blender add-on for rendering [OpenRCT2](https://openrct2.io) object sprites
with **Cycles**, in the visual style of the original RollerCoaster Tycoon 2
graphics. It is a modern successor to the Blender 2.79-only
[RCT Graphics Helper](https://github.com/OpenRCT2/Blender-RCT-Graphics).

- Works with Blender 4.2 LTS and newer (tested on Blender 5.1).
- No ImageMagick or other external tools: palette quantization, dithering,
  outlines, trimming, `object.json` and `.parkobj` packing are all done in
  Python/numpy inside Blender.
- Sprite offsets are computed from the same paint anchors OpenRCT2 uses, so
  the `images` table never needs hand-editing.

See [specifications.md](specifications.md) for the original goals.

## Installing

1. Run `python3 tools/build_zip.py` (or download a release zip).
2. In Blender: *Edit > Preferences > Get Extensions > Install from Disk...*
   (or *Add-ons > Install from Disk...*), pick the zip and enable
   **RCT Cycles Graphics**.
3. Optional: in the add-on preferences, set the **OpenRCT2 User Folder**
   (the folder holding `object/`) to copy built `.parkobj` files there.

## Quick start

1. Save your `.blend` file (the output folder is relative to it by default).
2. Open the sidebar (`N`) in the 3D viewport and choose the **RCT** tab.
3. Click **Initialize / Repair Scene**. This creates the camera, the lights
   and a wireframe tile grid, and configures Cycles. It also removes the
   default scene's light.
4. Pick the **Object Type**, model the object on the grid and click
   **Render Sprites**.
5. The output folder now holds `images/NNNN.png`, `images.json` and, after
   **Build .parkobj**, `object.json` and `<id>.parkobj`.

## Scene conventions

| | |
|---|---|
| Tile | 4 x 4 Blender units, centred on the origin |
| Height | one land step (16 game z units) = 4/sqrt(6) ~ 1.633 BU; one clearance unit (8 z) ~ 0.816 BU |
| Ground | z = 0 is the element's base height |
| Views | image *k* is the object seen with the camera turned by 90° x *k*, the image the game draws for direction *k* |

These are the same as in the original add-on, so existing models keep their
scale.

## Object types

**Small scenery.** Four images per frame (one per direction). The *Shape*
setting (full, three quarters, half, quarter, centred, centred without walls)
selects the paint anchor the game uses, and the matching `shape` and flags in
`object.json`. Animated objects store the still frame in images 0-3 and frame
*k* at `4 + 4k + direction`, with `SMALL_SCENERY_FLAG_VISIBLE_WHEN_ZOOMED`,
`frameOffsets` and `animationMask` generated for you.

**Large scenery.** Set the footprint width/length. Tiles extend from the
origin tile towards -X / -Y (game +x / +y). The whole object is rendered once
per view, then split per tile using Cycles' *Position* pass. Each tile sprite
is anchored on its own tile, exactly like `Paint.LargeScenery.cpp`. Images
0-3 hold the whole object as preview; tile *s* uses `4 + 4s + direction`. The
`tiles` list is written to `object.json`.

**Walls.** Model the wall on the tile's **+X edge** (outlined by the grid
helper). As in the original game, walls have only two images, one per screen
orientation (0 and 1). *Sloped* adds images 2-5, rendered with a temporary
shear of one land step. *Double Sided* adds images 6-11 with the back face for
the near edges.

**Flags.** The *Object Export* panel shows checkboxes for the `object.json`
flags of the selected type, taken from OpenRCT2's object readers. Small
scenery is *Stackable* (`isStackable`) and *Rotatable* by default; without
`isStackable` the game refuses to raise the object with Shift or stack it.
The other options are *Requires Flat Surface*, *Prohibit Walls*, *No
Supports*, *Allow Supports Above*, *Coloured Supports*, *Tree* and *Can Be
Watered*. Large scenery has *Supports* and *Allow Supports Above* (applied to
every tile), *Photogenic* and *Tree*; walls have *Transparent*. Every flag is
written, unticked ones as `false`, so unticking a box also clears the flag in
an existing `object.json`. Flags that need extra sprites (withering, glass,
doors, fountains, ...) are not offered; add them by hand to `object.json` and
they survive re-exports.

## Recolourable materials

In the *Recolourable Materials* panel, add a Remap 1/2/3 material or turn the
active material into one. Pixels of a remap material are quantized by
brightness into the game's remap ramp (primary 243-254, secondary 202-213,
tertiary 46-57), so the material's own colour does not matter. Those ramps
are then excluded from plain pixels. `hasPrimaryColour` and the related flags
are detected from the rendered sprites. Each remap writes its own coverage
AOV, so edges between two remap materials are never mistaken for a third.

## Anti-aliasing and the RCT look

Blender Internal used to anti-alias only the inside of objects, leaving a hard
silhouette. This add-on reproduces that with Cycles:

- **Supersampling** (3x3 by default) renders every sprite pixel as point
  samples on a grid of sub-pixels. A pixel takes the face under its centre
  sub-pixel and averages only the sub-pixels on that same face (same flat
  normal, same plane, same remap). Textures and shading are anti-aliased,
  but edges between faces never mix two faces' colours. Mixed edge pixels
  would otherwise show as dotted seams in game wherever one sprite overlaps
  another, e.g. on stacked or repeated base blocks.
- The silhouette follows the same centre sample, as a rasterizer would: a
  pixel is opaque when its centre hits the object (with at least the **alpha
  threshold** of opacity), so two adjacent tiles split boundary pixels
  between them exactly. Edges stay crisp and keep the object's own colour,
  with no dark or light fringe.
- With supersampling **Off**, Cycles' box pixel filter (width 1.0 by default)
  anti-aliases everything, and pixels at least 50% covered become opaque.
  Edges between faces then blend.
- **Blend Edges with Background** reproduces the dark fringe of RCT1-style
  graphics instead.
- **Outline Darkening** darkens the sprite's rim by *N* shades along each
  pixel's own palette ramp. This is the dark contour of original sprites
  such as the trees, and it keeps recolourable pixels recolourable.
- Lights rotate with the camera and are calibrated on the original base
  block sprite: right face brightest, top medium, left darkest. Strengths are
  adjustable under *Render & Colour*.
- Dithering: Floyd-Steinberg (strength adjustable), ordered (Bayer) or none.
  Error is never diffused between plain and recolourable pixels.
- Palette: full, grey only (vehicles) or a custom selection of colour ramps.

## Alignment: no more editing offsets by hand

Misaligned stacks of walls, base blocks or roofs had two causes in the past:
offsets estimated from trimmed images, and models that do not exactly fill
their cell. The add-on handles both:

1. **Exact offsets.** The camera reproduces the game's projection
   (`screen = (y - x, (x + y)/2 - z)`) and is framed so that tile corners fall
   on pixel corners. Each sprite's offset is measured from the paint anchor
   that `Paint.SmallScenery.cpp`, `Paint.LargeScenery.cpp` or `Paint.Wall.cpp`
   uses for the chosen type and shape. A model that fills its cell therefore
   always tiles without gaps or overlaps.
2. **Check Alignment** (also run after each render by default) compares the
   model's bounds with the tile edges and clearance units, in game units. For
   example: *"x: -X side is 1.2 game units (0.150 BU) short of the tile
   edge"*, or *"top at 16.7 z units; stacking needs a multiple of 8"*. It then
   composites the rendered sprites the way the game repeats them (3 copies
   along x, along y, and stacked by the clearance height; wall runs for
   walls), draws them over a ground grid, reports pinholes, and opens the
   result as `alignment_preview.png` / the *RCT Alignment Preview* image.
3. **Snap to Grid** fixes the model automatically. It scales and moves the
   selected objects (or everything rendered) so their bounds fill the tile
   cell (the +X edge for walls, one 2 x 2 BU quadrant centred on the origin
   for quarter tile objects) and a whole number of clearance units.

Horizontal findings only matter for objects meant to tile: a tree is not
supposed to fill its tile.

## Development

```
python3 -m unittest discover tests                                    # core (numpy only)
blender -b --factory-startup --python tests/blender_tests.py          # end-to-end, renders with Cycles
blender --command extension validate rct_cycles_graphics              # manifest check
```

`rct_cycles_graphics/core` is free of `bpy` and holds the palette,
quantization, projection, job layouts, alignment and JSON logic. The Blender
side (`scene_setup.py`, `render.py`, `materials.py`, `operators.py`,
`alignment_tools.py`, `ui.py`) drives Cycles and the UI.

## Credits

Palette values and paint anchors come from the OpenRCT2 source code. Scene
scale and lighting directions follow the original RCT Graphics Helper by
Olivier Wervers.
