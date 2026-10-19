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
   **Preview on Grass** reads the grass tile from RCT2's `Data/g1.dat` and the
   trees to compare with from `ObjData`: it
   finds the RCT2 folder through OpenRCT2's `config.ini` (`game_path`), or
   set the **RCT2 Folder** preference yourself.

## Quick start

1. Save your `.blend` file (the output folder is relative to it by default).
2. Open the sidebar (`N`) in the 3D viewport and choose the **RCT** tab.
3. Click **Initialize / Repair Scene**. This creates the camera, the lights
   and a wireframe tile grid, and configures Cycles. It also removes the
   default scene's light.
4. Pick the **Object Type**, model the object on the grid and click
   **Render Sprites**.
5. The output folder now holds `images/NNNN.png`, `images.json` and, after
   **Build .parkobj** (which renders the sprites again first), `object.json`
   and `<id>.parkobj`.

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

## Tree generator

The *Tree Generator* panel builds procedural trees in the style of the
original game's trees: a tapered trunk, branches, and a canopy of merged,
noise-displaced blobs. A generated tree is an ordinary mesh, so it renders,
quantizes and exports like any other model. See
[tree_generator_specification.md](tree_generator_specification.md) for the
full design.

1. Pick a **preset** (Broadleaf, Birch, Gnarled Oak, Layered, Conifer, Snowy
   Conifer, Cypress, Shrub, Flowering Shrub, Topiary Ball/Cone/Heart,
   Weeping, Blossom, Palm, Hair Palm, Hair Broadleaf, Leafy Broadleaf, Rosette Broadleaf, Bare) and click **Add Tree**. The tree's
   footprint follows the scene's current object type and shape. The add-on
   then sets the object type to match and ticks the *Tree* flag.
2. Select the tree to edit it. Settings are stored on the object, so a
   `.blend` file can hold several editable trees. With *Auto Update* the mesh
   is rebuilt on every change. The same settings and **seed** always give the
   same tree; the refresh button picks a new seed.

| Section | Settings |
|---|---|
| Size | Footprint (full tile, full tile centred, quarter tile, large W x L), height (in BU, clearance units or land steps), overhang |
| Trunk | Length (where the trunk ends), base and top radius, taper, root flare, sides |
| Trunk Shape | Straightness, bend frequency, gnarl, lean and lean direction, twist, forks |
| Branches | Count, start/end height, bottom/top angle, length and length profile, radius ratio, curve, spread (spiral, whorled, random), sub-branches, jitter |
| Leaves | Style (blobs, layers, needles, hair, leaf instances, tiers, column, topiary, strands, none), envelope shape, width/height/offset, clump size and variation, extra clumps, clumps per tip, flatten, merge, lumpiness, raggedness, droop, hollow, needle length/width/spacing/angle/droop/rows, hair source/strands/length/angle/flatten/droop/width/children, leaf shape/width/fold/bend/twist/irregularity/face up, mesh resolution |
| Accent and Base | Dots (flowers, berries) or top-facing faces (snow); mound, pot or rocks base |

**Materials.** The tree has four material slots: trunk, leaves, accent and
base. Missing ones get shared default materials (`RCT Tree Leaves`, ...).
Their main values are exposed on an `RCT Tree <Role>` node group: Colour A,
Colour B, Speckle Scale and Bump Strength. Any material can be picked for a
role, or dropped straight into its slot; regenerating never replaces it.
Each role's **Colour** dropdown makes its material plain or Remap 1/2/3 (for
example player-coloured blossom or leaves). Remember that remap pixels keep
only their brightness. **Make Unique** copies the shared materials so edits
stay on one tree.

**Footprint and look.** The canopy is limited to the footprint's half-width
times *Overhang*. The original trees reach the tile's corners, so most
presets use an overhang of about 1.4; the panel notes when a canopy spills
into neighbouring tiles. It warns above about 13 BU for small scenery, where
the game's bounding box stops, and shows a **Match Scene** button if the
scene's object type no longer matches the tree. **Use Suggested Look**
applies the preset's outline setting.

**Hair leaves.** The *Hair* style renders the leaves as Blender particle
hair, for fine, bushy fronds such as the RCT2 palms. The strands grow from
the branches (like fronds, *Flatten* keeps them beside the branch), from
the branch tips (tufts), from the canopy surface, from all through the
canopy volume, or out of clumps placed as in the Blobs style (lumpy, bushy
crowns such as Hair Broadleaf). On strands, the leaves material shades
each strand from Colour A at the root to Colour B at the tip, with no
speckle, so it reads as one stroke; a few wide strands (about two sprite
pixels) look cleaner than many thin ones. *Strand Shadows* lets strands
shade each other and the trunk; raise the scene's *Ambient* light (Hair
Broadleaf's suggested look uses 1.5) to lift the shadowed side. Each strand is straight,
tilted down by *Strand Droop* and kept inside the overhang and the tree
height. *Children* adds rendered strands around each one, with *Child
Spread*, *Clump* and *Roughness*. The hair lives on a child object,
`RCT Tree Hair`, whose hidden emitter mesh has one tiny triangle per strand;
it uses the leaves material and is removed when you pick another style.
Delete it together with the tree (*Delete Hierarchy*). Deep shadow between
strands can quantize to dark reds and browns; restricting the palette to
the leaf and bark ramps (Hair Broadleaf's suggested look) keeps it green.

**Leaf instances.** The *Leaf Instances* style builds the crown out of
copies of one small leaf mesh, as the original sprites do. Each copy is
bent, twisted and jittered differently, so the leaves never repeat
exactly. The leaves sit where hair strands would grow: the *Grow From*,
count, size, angle, flatten and droop settings are shared with the Hair
style (the panel renames them *Leaves*, *Leaf Size*, and so on). *Leaf
Shape* picks a narrow blade, an oval leaf, a sprig of three blades, a
rosette (two rings of broad, round-tipped petals around a darker centre,
like a green flower head, facing outwards along its stem), or a **Custom Object**. A
custom *Leaf Object* is read in its own axes: root at the origin, growing
along +X, upper face towards +Z. It is scaled so its farthest vertex is 1
from the origin, and its modifiers apply. **Make Leaf Object** copies the
current built-in shape into such an object, so you can start from it and
edit it. Hide it from renders, and click
*Regenerate* after editing it. *Fold* lifts the leaf's edges about its
midrib, so the two halves catch the light differently. *Bend* curls the leaf
down, *Twist* twists it at random, and *Irregularity* changes each leaf's
width and bend and jitters its vertices. *Face Up* turns the upper faces
towards the sky. The leaves material shades each leaf like a strand, from
Colour A at the root to Colour B at the tip, with its own brightness.
*Leaf Shadows* (the hair's *Strand Shadows*) stops leaves shading each
other; leaves and trunk share one object, so the whole tree stops casting
shadows. Leafy Broadleaf uses about 3,000 long, narrow blades in the Hair Broadleaf
crown. Rosette Broadleaf uses 200 large rosettes of very different sizes, each up
to about 20 pixels across, so the crown's outline stays lumpy.

**Apply (Freeze Mesh)** turns the tree into a plain mesh for manual editing.
Until then, regenerating replaces manual mesh edits.

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
- With supersampling **Off**, Cycles' box pixel filter (one pixel wide)
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

## Matching the tones of the original trees

The original trees sit low on the palette ramps: most of their pixels use the
four darkest shades of a ramp, and the top shades are kept for a few
highlights. Getting that from lighting and materials alone means a lot of
trial and error. Tick **Match RCT2 Tones** under *Render & Colour* instead
(*Use Suggested Look* turns it on for generated trees).

- Every pixel moves along its own colour ramp until the object's shades are
  spread like those of the 33 vanilla RCT2 trees (snow-covered ones aside).
  Hues stay yours: an autumn tree stays orange, only its shading changes.
- One curve is fitted over all views and frames, so every rotation gets the
  same correction. The curve is smooth, so the render's own shading is kept.
- Rim pixels are left out of the fit; *Outline Darkening* still adds the
  contour on top.
- **Strength** blends between the plain render (0) and the full match (1).
  **Match Saturation** also nudges plain colours' saturation towards the
  originals, by at most -15% / +25%.
- After every render, the section shows the shades the sprites use next to
  the RCT2 trees' (average shade, dark / mid / light shares), with or without
  matching.

Light and materials then shape the object; you no longer need them to set
its exposure. Matching cannot invent shadow detail, though: if the ambient
light fills every crevice, the darks come out as flat patches.

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

**Preview on Grass** (just under **Render Sprites**) renders the sprites
again and shows them as the game would: each of the four views stands on a patch
of the game's grass with gridlines (`SPR_TERRAIN_GRASS_GRID` from `g1.dat`),
with *Tiles Around* rings of tiles around the footprint, enlarged by *Zoom*.
Up to four of RCT2's own trees (*Compare with RCT2 trees*, read from the
install's `ObjData/*.DAT`) stand beside the object on the same screen row,
placed with the game's paint offsets, so the generated sprites can be
compared with the originals in every view.
The result opens as `terrain_preview.png` / the *RCT Terrain Preview* image
(in a new window when no Image Editor is open). Without `g1.dat` a stand-in
grass tile in the game's palette is used.

## Development

```
python3 -m unittest discover tests                                    # core (numpy only)
blender -b --factory-startup --python tests/blender_tests.py          # end-to-end, renders with Cycles
blender --command extension validate rct_cycles_graphics              # manifest check
```

`rct_cycles_graphics/core` is free of `bpy` and holds the palette,
quantization, projection, job layouts, alignment, JSON and tree generation
logic. The Blender side (`scene_setup.py`, `render.py`, `materials.py`,
`operators.py`, `tree_generator.py`, `alignment_tools.py`, `ui.py`) drives
Cycles and the UI.

## Credits

Palette values and paint anchors come from the OpenRCT2 source code. Scene
scale and lighting directions follow the original RCT Graphics Helper by
Olivier Wervers.
