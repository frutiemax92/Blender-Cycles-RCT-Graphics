# Tree Generator: Detailed Specification

Status: proposal. Source brief: [specifications_tree_generator.md](specifications_tree_generator.md).

## 1. Purpose and scope

OpenRCT2 lets players place trees, and most original tree sprites were made
from a trunk, a few branches and a canopy of blobs, spheres and noise. This
feature adds a **procedural tree generator** to the RCT Cycles Graphics add-on.
It builds a tree model that the existing pipeline renders, quantizes and
exports like any hand-made model.

The generator is a modelling aid only. It does not add a new object type,
render path or export format. A generated tree is an ordinary mesh in the
scene, so everything already in the add-on (rig, supersampling, outline,
palette, remaps, alignment check, `object.json`, `.parkobj`) works unchanged.

### 1.1 Goals

The user can:

1. Choose the object size: full tile, full tile centred, quarter tile, or a
   multi-tile large scenery tree.
2. Assign a recolourable (remap 1/2/3) or plain material to each part of the
   tree (trunk, leaves, accent, base) and edit those materials freely
   afterwards.
3. Set the trunk size: height, base radius, top radius, root flare.
4. Set the leaf/canopy size and shape.
5. Set the trunk shape: how straight, bent, leaning or gnarled it is.
6. Set the number of branches, and how they are spread along the trunk.

They can also:

7. Start from presets matching the original game's tree families.
8. Get a different tree from the same settings by changing a seed, and get
   the same tree back from the same seed.
9. Regenerate after changing any setting without losing material edits.

### 1.2 Non-goals (this version)

- Wind or sway animation (the add-on supports animation, but a moving tree
  is a separate feature).
- Leaf-by-leaf geometry. At sprite scale one pixel is about 0.09 Blender
  units (BU), so single leaves are invisible. The canopy is a volume.
- Physically based growth simulation (space colonisation, L-systems with
  grammars). The parameters stay few and readable.
- Withering sprites (`canWither`). Section 11 describes them as a possible
  later phase.

## 2. Reference: what original trees look like

The `examples/` sprites (3x upscaled, four views each) show a small set of
families. The presets in section 7 are based on them.

| Family | Examples | Traits |
|---|---|---|
| Broadleaf | `0.png`, `132.png`, `207.png`, `176.png` | Straight trunk, 2-5 visible branches just under a wide round canopy; canopy roughly as wide as the tile |
| Gnarled | `11.png`, `1050.png`, `200.png` | Thick bent trunk, irregular lumpy canopy, sometimes flat clumps |
| Layered | `1051.png`, `1052.png`, `1053.png` | Thin trunk carrying several separate flat clumps at different heights |
| Conifer | `146.png`, `147.png`, `133.png` | Very tall, thin trunk visible all the way up, drooping branch tiers, pointed tip |
| Columnar | `116.png`, `119.png`, `122.png`, `117.png` | Narrow cypress spindle, trunk visible only at the base |
| Shrub | `101.png`, `110.png`, `129.png`, `174.png` | No visible trunk, dense rounded or conical mass |
| Topiary | `134.png`, `135.png`, `109.png`, `189.png` | Short thick trunk, clean geometric canopy (ball, cone, heart, bell) |
| Weeping | `130.png`, `199.png`, `111.png` | Drooping strands or clumps hanging from branch tips |
| Blossom / accent | `123.png`, `1068.png`, `110.png` | A second colour dotted over the foliage (flowers, berries) |
| Snow | `182.png`, `183.png`, `185.png` | Conifer with white on the upward-facing parts of the foliage |

Shared look:

- Canopies have a ragged, speckled silhouette and strong light/dark
  variation inside, not a smooth sphere.
- Trunks are 2-6 sprite pixels wide, tapered, often with a lighter or
  bluish-grey base.
- A dark one-pixel contour runs around the sprite. The add-on's **Outline
  Darkening** already reproduces it.

## 3. Integration with the existing add-on

### 3.1 New files

| File | Content |
|---|---|
| `rct_cycles_graphics/core/tree.py` | `bpy`-free generator: parameters, presets, seeded randomness, noise, skeleton, blob placement, trunk tube mesh data. Unit-testable with numpy only, like the rest of `core/`. |
| `rct_cycles_graphics/tree_generator.py` | Blender side: `TreeSettings` property group, operators, mesh/metaball building, material roles. |
| `tests/test_core_tree.py` | Unit tests for `core/tree.py`. |

`ui.py` gets a new sub-panel. `__init__.py` adds `"tree_generator"` to
`_module_names`, after `"materials"` because it reuses the remap helpers.

### 3.2 Reused add-on parts

| Existing part | How the generator uses it |
|---|---|
| `materials.set_remap`, `new_remap_material`, `get_remap` | Marking a role's material as recolourable; no new remap code |
| `render.renderable_objects` | Renders the generated mesh as is (any visible, render-enabled object) |
| `properties.small_shape`, `object_type`, `tiles_width/length` | Set by the generator to match the chosen size |
| `flag_small_isTree` / `flag_large_isTree` | Ticked automatically when a tree is added |
| `alignment.clearance_from_height` | Clearance and `height` in `object.json` come from the mesh bounds, as now |
| Outline, palette, dither, supersampling | Unchanged; presets only *suggest* values (section 8.4) |

### 3.3 Scene conventions (unchanged)

- A tile is 4 x 4 BU, centred on the origin; z = 0 is the element base.
- One land step = 16 game z units ≈ 1.633 BU; one clearance unit (8 z) ≈ 0.816 BU.
- Game +x / +y point towards Blender -X / -Y.
- One sprite pixel ≈ 0.09 BU horizontally (a tile's 64-pixel width spans its
  4√2 BU diagonal). Detail smaller than that is wasted. The generator uses
  this value to pick mesh resolution (section 6.6).

## 4. Data model

### 4.1 Where settings live

Settings are stored **per object**, so a `.blend` file can hold several
trees and each one stays editable:

```python
bpy.types.Object.rct_tree = PointerProperty(type=TreeSettings)
```

`TreeSettings.enabled` (bool, hidden) marks an object as a generated tree.
The panel shows the tree settings when the active object has
`rct_tree.enabled`.

### 4.2 Generated object structure

One tree is **one mesh object**, named `RCT Tree` by default, with four
material slots. Each slot has a fixed **role**:

| Slot | Role | Faces |
|---|---|---|
| 0 | Trunk | Trunk and all branches |
| 1 | Leaves | Canopy / foliage |
| 2 | Accent | Flowers, berries, snow (optional, see 6.5) |
| 3 | Base | Root flare, pot or mound (optional) |

Why a single object:

- *Snap to Grid*, bounds, clearance and the render all see one object.
- Material roles stay stable across regenerations: each face gets its
  `material_index` from its role.
- The user can still select faces by material slot to inspect a part.

Regenerating **replaces the mesh data** (`obj.data`) only. Object transform,
modifiers added by the user, material slot assignments and custom
properties are kept. Manual mesh edits are lost on regeneration; the panel
says so and offers **Apply** (section 8.2) to freeze the tree into a plain
mesh.

### 4.3 Parameter table

All lengths are in BU unless marked. "Rel." means relative to trunk height.
Ranges are UI soft limits; the hard limits only prevent degenerate geometry.

#### Size and placement

| Property | Type | Default | Range | Meaning |
|---|---|---|---|---|
| `size` | enum | `FULL` | `FULL`, `FULL_CENTRED`, `QUARTER`, `LARGE` | Footprint. Sets `object_type` / `small_shape` (8.3) |
| `large_width`, `large_length` | int | 2, 2 | 1-4 | Footprint in tiles when `size = LARGE` |
| `height` | float | 6.5 | 0.5-40 | Total tree height including canopy |
| `height_unit` | enum | `BU` | `BU`, `CLEARANCE`, `LAND_STEPS` | Unit shown for `height`. Stored value is always BU |
| `overhang` | float | 1.0 | 0.5-1.5 | Allowed canopy half-width as a multiple of the footprint's half-width (1.0 = canopy fits the tile) |

#### Trunk size

| Property | Type | Default | Range | Meaning |
|---|---|---|---|---|
| `trunk_length` | float (rel.) | 0.55 | 0-1 | Fraction of `height` from the ground to where the trunk ends (the canopy covers the rest). 0 = no visible trunk (shrub) |
| `trunk_base_radius` | float | 0.16 | 0.02-1.5 | Radius at the ground |
| `trunk_top_radius` | float | 0.06 | 0.01-1.5 | Radius at the trunk end |
| `taper_curve` | float | 1.0 | 0.3-3 | Exponent of the base→top radius interpolation (1 linear, >1 thins faster near the base) |
| `root_flare` | float | 0.3 | 0-1.5 | Extra radius at the very base, fading out over `root_flare_height` |
| `root_flare_height` | float (rel.) | 0.08 | 0-0.3 | Height of the flare |
| `trunk_sides` | int | 6 | 3-16 | Ring resolution. 6 is plenty at sprite scale |

#### Trunk shape

| Property | Type | Default | Range | Meaning |
|---|---|---|---|---|
| `straightness` | float | 0.85 | 0-1 | 1 = perfectly straight. Lower values add slow, smooth bends |
| `bend_frequency` | float | 1.5 | 0.5-6 | Number of bends along the trunk |
| `gnarl` | float | 0.0 | 0-1 | Fast, small kinks (old, twisted trees) |
| `lean_angle` | float (deg) | 0 | 0-45 | Overall lean from vertical |
| `lean_direction` | float (deg) | 0 | 0-360 | Lean azimuth, 0 = Blender +X |
| `twist` | float (deg) | 0 | -360-360 | Twist of the bark texture coordinates and of branch azimuths along the trunk |
| `fork_count` | int | 1 | 1-4 | Number of leaders the trunk splits into (1 = no split) |
| `fork_height` | float (rel.) | 0.6 | 0.1-1 | Where the split happens, relative to `trunk_length` |
| `fork_angle` | float (deg) | 25 | 0-70 | Angle of each leader from the parent direction |

#### Branches

| Property | Type | Default | Range | Meaning |
|---|---|---|---|---|
| `branch_count` | int | 4 | 0-40 | First-level branches on the trunk (and leaders, shared between them) |
| `branch_start` | float (rel.) | 0.55 | 0-1 | Lowest branch, as a fraction of `trunk_length` |
| `branch_end` | float (rel.) | 0.95 | 0-1 | Highest branch, as a fraction of `trunk_length` |
| `branch_angle_base` | float (deg) | 55 | 0-150 | Angle from the trunk for the lowest branch |
| `branch_angle_top` | float (deg) | 30 | 0-150 | Angle from the trunk for the highest branch. >90° droops |
| `branch_length` | float (rel.) | 0.30 | 0-1 | Length of the longest branch |
| `branch_length_profile` | enum | `ROUND` | `ROUND`, `CONICAL`, `INVERTED`, `CONSTANT` | How length varies with height: `sin(πt)`, `1-t`, `t`, `1` |
| `branch_radius_ratio` | float | 0.5 | 0.1-1 | Branch base radius as a fraction of the trunk radius where it starts |
| `branch_curve` | float | 0.2 | -1-1 | Bend along the branch: + curves up, - droops |
| `branch_spread` | enum | `SPIRAL` | `SPIRAL`, `WHORLED`, `RANDOM` | Golden-angle spiral (137.5°), whorls of `whorl_size` per height, or random azimuths |
| `whorl_size` | int | 4 | 2-8 | Branches per whorl when `WHORLED` (conifers) |
| `sub_branches` | int | 0 | 0-8 | Second-level branches per first-level branch |
| `sub_branch_length` | float | 0.5 | 0.1-1 | Second-level length relative to the parent branch |
| `jitter` | float | 0.3 | 0-1 | Random variation applied to angles, lengths and positions |

`branch_count`, `sub_branches` and the canopy clumps (below) together
control visual density. A hard cap of **400 branch segments in total**
keeps regeneration interactive (section 9).

#### Leaves / canopy

| Property | Type | Default | Range | Meaning |
|---|---|---|---|---|
| `canopy_style` | enum | `BLOBS` | see 6.4 | How foliage is built |
| `canopy_shape` | enum | `SPHERE` | `SPHERE`, `ELLIPSOID`, `CONE`, `CYLINDER`, `HEART`, `BELL` | Envelope clumps are confined to (and the solid shape for `TOPIARY`) |
| `canopy_width` | float (rel. to footprint) | 0.9 | 0.1-1.5 | Envelope half-width relative to the footprint half-width, clamped by `overhang` |
| `canopy_height` | float (rel.) | 0.5 | 0.05-1 | Envelope height as a fraction of `height` |
| `canopy_offset` | float (rel.) | 0.0 | -0.3-0.3 | Vertical shift of the envelope (negative lets the canopy hang below the trunk end) |
| `clump_size` | float | 0.9 | 0.1-3 | Mean clump (blob) radius |
| `clump_size_variation` | float | 0.35 | 0-1 | Random ± fraction of `clump_size` |
| `clump_count` | int | 0 | 0-200 | Extra clumps scattered inside the envelope. 0 = clumps only at branch tips |
| `clumps_per_tip` | int | 2 | 1-6 | Clumps placed along the last part of each branch |
| `clump_flatten` | float | 0.0 | 0-0.8 | Vertical squash of each clump (layered trees: 0.5-0.7) |
| `blob_merge` | float | 0.6 | 0-1 | How much neighbouring blobs fuse (metaball threshold); 0 = separate spheres |
| `lumpiness` | float | 0.25 | 0-1 | Noise displacement of the canopy surface along its normal, as a fraction of `clump_size` |
| `lump_scale` | float | 0.35 | 0.05-2 | Feature size of that noise in BU (≈4 sprite pixels at default) |
| `raggedness` | float | 0.3 | 0-1 | Fine, high-frequency displacement that breaks the silhouette into a ragged edge |
| `droop` | float | 0.0 | 0-1 | Pulls the lower half of each clump downwards (weeping trees) |
| `hollow` | float | 0.0 | 0-0.8 | Removes clumps near the trunk axis so inner branches show (layered, gnarled trees) |

#### Accent and base

| Property | Type | Default | Range | Meaning |
|---|---|---|---|---|
| `accent_mode` | enum | `NONE` | `NONE`, `DOTS`, `TOP_FACING` | `DOTS`: small spheres scattered on the canopy (flowers, berries). `TOP_FACING`: canopy faces whose normal points up more than `accent_threshold` move to the accent slot (snow) |
| `accent_amount` | float | 0.15 | 0-1 | Dot density, or the share of faces for `TOP_FACING` |
| `accent_size` | float | 0.1 | 0.04-0.5 | Dot radius (≥ about one sprite pixel) |
| `accent_threshold` | float | 0.6 | 0-1 | Minimum normal z for `TOP_FACING` |
| `base_style` | enum | `NONE` | `NONE`, `MOUND`, `POT`, `ROCKS` | Optional base under the trunk |
| `base_radius` | float | 0.6 | 0.1-2 | Base size |
| `base_height` | float | 0.3 | 0.05-1.5 | Base height |

#### Randomness

| Property | Type | Default | Meaning |
|---|---|---|---|
| `seed` | int | 1 | Drives every random choice |
| `auto_update` | bool | True | Regenerate on every property change |

#### Materials (section 5)

| Property | Type | Meaning |
|---|---|---|
| `material_trunk`, `material_leaves`, `material_accent`, `material_base` | `PointerProperty(bpy.types.Material)` | Material per role |

## 5. Materials

### 5.1 Requirements

- Every role can be **plain** (quantized to the normal palette) or
  **recolourable** with remap 1, 2 or 3, so the player picks the colour in
  game.
- Materials are **ordinary Blender materials**. The user can open them in the
  shader editor and change anything.
- The generator **never overwrites an existing material**. Regeneration only
  re-assigns slots from the role pointers.

### 5.2 Default materials

When a role pointer is empty at generation time, the generator creates a
default material for that role and stores it in the pointer. Defaults are
built from small node setups made for sprite scale:

| Role | Default look | Nodes |
|---|---|---|
| Trunk | Brown bark, slightly lighter/greyer towards the base (like `0.png`) | Principled BSDF; base colour = mix of two browns by a vertical gradient (object Z) and a stretched Noise Texture (bark streaks along the trunk) |
| Leaves | Dark green with strong speckle | Principled BSDF (roughness 0.9); base colour from a ColorRamp driven by a Voronoi texture (cell size ≈ 2 sprite pixels) mixed with Noise; the same Voronoi drives a Bump node for light/dark leaf clusters |
| Accent | Pink blossom (dots) or white snow (top facing) depending on `accent_mode` | Principled BSDF with a flat colour |
| Base | Blue-grey stone | Principled BSDF with Noise colour variation |

Each default exposes its key values on a node group named
`RCT Tree <Role>` (Colour A, Colour B, Speckle Scale, Bump Strength). The
user can tweak those without editing the graph and can still replace the
whole material.

Default materials are named `RCT Tree Trunk`, `RCT Tree Leaves`, and so on.
They are shared between trees unless the user clicks **Make Unique**
(section 8.2).

### 5.3 Recolourable roles

Each role shows a **Colour** dropdown: `Plain`, `Remap 1 (Primary)`,
`Remap 2 (Secondary)`, `Remap 3 (Tertiary)`. It calls
`materials.set_remap(material, n)` on the role's material and reads the
current state back with `materials.get_remap`. Nothing new is needed in the
render or quantization code.

Two consequences of how the add-on quantizes remaps, which the UI must point
out in a tooltip:

1. **Remap pixels are quantized by brightness only.** Hue variation in a
   recolourable leaf material is lost; only light/dark variation survives.
   When a role is switched to a remap, the generator sets the viewport
   preview colour to the ramp colour (as `new_remap_material` does) and
   leaves the node graph alone.
2. **A remap ramp is excluded from plain pixels.** If the leaves use remap 1,
   no plain pixel can use the primary ramp's colours.

Typical uses: blossom accents on remap 1 (player-coloured flowers), leaves on
remap 1 for a "colourful garden tree", the pot on remap 2.

`hasPrimaryColour` and the related `object.json` flags keep being detected
from the rendered sprites, as now.

## 6. Generation algorithm

Everything in 6.1-6.5 lives in `core/tree.py` and returns plain Python /
numpy data. 6.6 is the Blender side.

### 6.1 Determinism

- A single `random.Random(seed)` instance is created per generation and
  split into independent sub-streams per stage (trunk, branches, clumps,
  accent) by seeding each with `hash((seed, stage_name))` computed with a
  stable hash (e.g. `zlib.crc32`), not Python's salted `hash()`. Changing
  `branch_count` therefore does not reshuffle the canopy noise.
- Noise is a small numpy 3D gradient-noise implementation in `core/tree.py`
  with fractal octaves, seeded by the same scheme. `mathutils.noise` is not
  used, so core tests run without Blender and output does not depend on the
  Blender version.
- Same parameters + same seed ⇒ same vertices (up to float rounding) on
  every platform.

### 6.2 Trunk skeleton

The skeleton is a list of **polylines**. Each point stores position, radius
and the index of its parent polyline.

1. **Axis.** Start at the origin (or, for `QUARTER`, at the origin, which is
   the quarter tile's centre in the add-on's convention). Sample
   `n = clamp(8 * bend_frequency, 8, 48)` points up to
   `trunk_length * height`.
2. **Lean.** Rotate the axis by `lean_angle` around the horizontal axis
   perpendicular to `lean_direction`.
3. **Bends.** Add a horizontal offset
   `(1 - straightness) * 0.15 * height * fbm(t * bend_frequency)` in x and y
   (two noise channels), with `t` the normalised height. The offset is 0 at
   `t = 0` so the base stays on the anchor.
4. **Gnarl.** Add `gnarl * 0.5 * trunk_base_radius * fbm(t * 12)` kinks.
5. **Radius.** `r(t) = lerp(base, top, t ** taper_curve)
   + root_flare * base * smoothstep(1, 0, t / root_flare_height)`.
6. **Fork.** If `fork_count > 1`, the axis stops at `fork_height`, and
   `fork_count` leaders continue from there to the trunk end. Leader
   azimuths are evenly spaced plus jitter; each leans `fork_angle` away from
   the parent direction, with radius `r / sqrt(fork_count)`, which keeps the
   cross-section area roughly constant.

### 6.3 Branches

1. **Emission heights.** Spread `branch_count` positions between
   `branch_start` and `branch_end` along the trunk (or along the leaders,
   round-robin). With `jitter`, positions move by up to half a slot.
2. **Azimuth.** `SPIRAL`: `i * 137.5° + twist * t + jitter`. `WHORLED`:
   groups of `whorl_size` at the same height, evenly spaced, each group
   rotated by half a step. `RANDOM`: uniform.
3. **Pitch.** Angle from the parent axis =
   `lerp(branch_angle_base, branch_angle_top, t)` ± jitter.
4. **Length.** `branch_length * height * profile(t) * (1 ± jitter)` where
   `profile` is the selected `branch_length_profile`. Lengths are clipped so
   branch tips stay inside the canopy envelope widened by one `clump_size`.
5. **Curve.** Each branch is a 4-6 point polyline. Each successive segment
   rotates towards +Z (`branch_curve > 0`) or −Z (`< 0`) by
   `branch_curve * 30°`.
6. **Radius.** Starts at `branch_radius_ratio * r_parent(t)` and tapers to
   35 % at the tip. Branches thinner than **0.03 BU** (about a third of a
   pixel) are still generated for the clumps, but get no tube mesh: they
   would only make noise in the sprite.
7. **Sub-branches.** Repeat steps 1-6 on each first-level branch with
   `sub_branches`, using the branch as the parent and `sub_branch_length`.
   Only two levels exist.

The outputs are the polylines plus the list of **branch tips**: the end
point and direction of every branch with no children, plus the trunk or
leader ends.

### 6.4 Canopy (leaves)

The canopy is a set of **blobs** (centre, radius, flatten), later turned into
a surface. `canopy_style` picks how blobs are placed:

| Style | Placement | Used by presets |
|---|---|---|
| `BLOBS` | `clumps_per_tip` blobs along the last 40 % of each tip branch, plus `clump_count` blobs sampled inside the envelope (Poisson-disc, min distance `0.6 * clump_size`). All blobs are clipped to the envelope | Broadleaf, Gnarled, Shrub, Blossom |
| `LAYERS` | One flattened blob cluster per first-level branch tip (`clump_flatten` ≥ 0.5) | Layered |
| `TIERS` | For conifers: per whorl, a ring of elongated, drooping blobs along each branch. Ring radius follows the cone envelope | Conifer, Snow |
| `COLUMN` | Blobs stacked along the trunk axis, radius following the envelope profile, high `raggedness` | Columnar |
| `TOPIARY` | No blobs. The envelope shape itself is the canopy surface, with low lumpiness | Topiary |
| `STRANDS` | Chains of small blobs hanging from each tip, length `droop * height` | Weeping |
| `NONE` | No foliage (dead tree, bare trunk sculpture) | — |

Envelope shapes are signed-distance functions in `core/tree.py`: sphere,
ellipsoid, cone, cylinder, heart (two spheres and a cone), bell. The
envelope is centred at height
`trunk_length * height + canopy_offset * height`, scaled to `canopy_width`
and `canopy_height`, and clamped by the footprint (6.7).

`hollow` removes blobs whose horizontal distance from the trunk axis is
below `hollow * envelope_radius`. `droop` moves each blob centre down by
`droop * radius * 0.5` and stretches it vertically.

### 6.5 Accent

- `DOTS`: Poisson-disc points sampled on the final canopy surface (after
  displacement), each getting a small low-poly sphere (icosphere level 1)
  with radius `accent_size`, assigned to slot 2. They sit half buried so
  they read as coloured spots, not as floating balls.
- `TOP_FACING`: no extra geometry. Canopy faces with normal z ≥
  `accent_threshold`, thinned by a noise mask to `accent_amount`, are moved
  to slot 2 (snow on top of conifer tiers).

### 6.6 Mesh building (Blender side)

1. **Trunk and branches.** Each polyline becomes a tube: rings of
   `trunk_sides` vertices with parallel-transport frames (no flips on
   bends) and a cap at the tips. Branch tubes start inside the parent tube,
   so no welding is needed: intersecting closed tubes render correctly in
   Cycles. UVs: u around the ring (with `twist`), v along the length in BU,
   so bark textures keep their scale.
2. **Canopy surface.**
   - With `blob_merge > 0`, the blobs become elements of a temporary
     metaball object (`MetaBall`, type `ELLIPSOID` when flattened). Its
     `threshold` comes from `blob_merge` and its `resolution` from the
     sprite pixel size (default 0.12 BU; render resolution = viewport
     resolution). The metaball is evaluated through the depsgraph into a
     mesh, merged into the tree mesh, then deleted. It never appears in the
     outliner.
   - With `blob_merge = 0`, each blob is an icosphere (subdivision 2-3
     depending on radius) and blobs are not merged.
   - `TOPIARY` evaluates its envelope SDF with the same metaball path (one
     element per primitive) for a clean surface.
3. **Displacement.** Canopy vertices move along their normals by
   `lumpiness * clump_size * fbm(p / lump_scale)` +
   `raggedness * 0.1 * fbm(p / (lump_scale * 0.25))`, using the core noise.
   This gives the ragged, speckled silhouette of the original sprites.
4. **Shading.** The canopy is shaded flat. Flat facets give the
   light/dark speckle under the add-on's lighting. They also let
   **supersampling** resolve each tiny face separately, so the canopy
   interior stays crisp instead of blurring. Trunk tubes are shaded smooth.
5. **Material indices** are assigned from roles (4.2). Missing role
   materials are created (5.2).
6. The result replaces `obj.data`. The old mesh datablock is removed if no
   other object uses it.

### 6.7 Footprint and size limits

Half-widths available for the canopy envelope (before `overhang`):

| `size` | Footprint | Half-width | Anchor | Add-on setting written |
|---|---|---|---|---|
| `FULL` | 1 x 1 tile | 2.0 BU | Tile centre | `object_type = SMALL`, `small_shape = FULL` |
| `FULL_CENTRED` | 1 x 1 tile | 2.0 BU | Tile centre | `small_shape = FULL_CENTRED` |
| `QUARTER` | ¼ tile | 1.0 BU | Origin (quadrant centre) | `small_shape = QUARTER` |
| `LARGE` | W x L tiles | `min(W, L) * 2.0` BU | Footprint centre, i.e. offset `(-(W-1)*2, -(L-1)*2)` from the origin tile | `object_type = LARGE`, `tiles_width = W`, `tiles_length = L` |

Rules:

- Envelope half-width = `canopy_width * half_width`, capped at
  `overhang * half_width`. With `overhang > 1` the panel warns that the
  canopy reaches into neighbouring tiles. The game may draw neighbouring
  scenery over that part, since the paint bounding box covers the object's
  own tile only.
- Trunk base radius + root flare is clamped to `0.8 * half_width`.
- Height: the game clamps a small scenery bounding box to 128 z units
  (`Paint.SmallScenery.cpp`: `boundBox.length.z = height - 4`, capped at
  128), about 13 BU. Taller trees still render, but depth sorting is wrong
  above that line. The panel shows a warning beyond 13 BU for small scenery.
- `LARGE` trees are split per tile by the existing Position-pass splitter;
  the generator only centres the tree on the footprint.

## 7. Presets

Presets are dictionaries in `core/tree.py` (`PRESETS: dict[str, dict]`).
Choosing one writes every listed parameter; parameters a preset omits get
their defaults. Each preset also carries a suggested outline and default
material colours.

| Preset | Key settings | Modelled on |
|---|---|---|
| Broadleaf | `trunk_length 0.5`, `branch_count 4`, `branch_start 0.7`, `canopy_style BLOBS`, `canopy_shape SPHERE`, `canopy_width 0.95`, `lumpiness 0.25` | `0.png`, `132.png` |
| Birch | Broadleaf with thin pale trunk (`trunk_base_radius 0.1`), `canopy_shape ELLIPSOID`, light leaves | `176.png` |
| Gnarled Oak | `straightness 0.4`, `gnarl 0.6`, `fork_count 2`, `trunk_base_radius 0.3`, `lumpiness 0.5`, `hollow 0.3` | `11.png`, `1050.png` |
| Layered | `trunk_length 0.8`, `branch_count 5`, `canopy_style LAYERS`, `clump_flatten 0.6`, `hollow 0.4` | `1051.png`, `1053.png` |
| Conifer | `height 11`, `trunk_length 1.0`, `branch_spread WHORLED`, `branch_count 24`, `branch_length_profile CONICAL`, `branch_curve -0.4`, `canopy_style TIERS`, `canopy_shape CONE` | `146.png`, `147.png` |
| Snowy Conifer | Conifer + `accent_mode TOP_FACING`, white accent | `182.png`, `185.png` |
| Cypress | `height 9`, `trunk_length 0.1`, `canopy_style COLUMN`, `canopy_width 0.35`, `raggedness 0.6` | `116.png`, `122.png` |
| Shrub | `height 2.5`, `trunk_length 0`, `branch_count 0`, `clump_count 25`, `canopy_shape ELLIPSOID` | `101.png`, `129.png` |
| Flowering Shrub | Shrub + `accent_mode DOTS` | `110.png`, `174.png` |
| Topiary Ball / Cone / Heart | `trunk_length 0.4`, thick trunk, `canopy_style TOPIARY`, matching `canopy_shape`, `lumpiness 0.05`, bright leaves | `134.png`, `135.png`, `109.png` |
| Weeping | `branch_angle_top 70`, `branch_curve -0.6`, `canopy_style STRANDS`, `droop 0.6` | `130.png`, `199.png` |
| Blossom | Broadleaf, `straightness 0.5`, `accent_mode DOTS`, `accent_amount 0.5`, accent on remap 1 | `123.png` |
| Palm | `trunk_length 0.9`, `straightness 0.6`, `lean_angle 10`, `branch_count 8` from the very top (`branch_start 0.98`), `branch_curve -0.7`, `canopy_style STRANDS` with flattened blobs | Tropical theme |
| Bare | `canopy_style NONE`, `sub_branches 3` | Dead tree |

The tests check every preset (section 10). The table is a starting point;
the values will be tuned against the example sprites during implementation.

## 8. User interface and operators

### 8.1 Panel

New sub-panel **Tree Generator** (`RCT_PT_tree`) under `RCT_PT_main`, placed
after *Recolourable Materials*. Collapsed by default.

```
Tree Generator
  [Preset: Broadleaf        v] [Add Tree]

  (when the active object is a generated tree)
  Seed [ 1 ] [dice]   [x] Auto Update   [Regenerate]
  ▸ Size         Footprint, Height (+unit), Overhang
  ▸ Trunk        Length, Base/Top Radius, Taper, Root Flare, Sides
  ▸ Trunk Shape  Straightness, Bend Frequency, Gnarl, Lean, Twist, Fork
  ▸ Branches     Count, Start/End, Angles, Length + Profile, Curve,
                 Spread, Sub-branches, Jitter
  ▸ Leaves       Style, Shape, Width/Height/Offset, Clump Size/Variation,
                 Clumps, Flatten, Merge, Lumpiness, Raggedness, Droop, Hollow
  ▸ Accent/Base  Mode, Amount, Size; Base Style, Radius, Height
  ▸ Materials    per role: [material picker] [Colour: Plain/Remap 1-3 v]
                 [Make Unique]
  Stats: 3 412 faces · 1.6 clearance units… · fits tile ✓
  [Load Preset] [Apply (freeze mesh)]
```

The sub-sections use `layout.panel()` collapsible headers (Blender 4.1+,
fine for the 4.2 minimum). Warnings (overhang, height cap, branch cap
reached) appear as `ERROR`-icon labels in the stats area.

### 8.2 Operators

| Operator | `bl_idname` | Behaviour |
|---|---|---|
| Add Tree | `rct_graphics.tree_add` | Creates `RCT Tree` at the origin from the selected preset, makes it active, ticks the `isTree` flag, writes the size settings (8.3). Initializes the rig first if it is missing. Undoable |
| Regenerate | `rct_graphics.tree_regenerate` | Rebuilds the active tree's mesh from its settings |
| Randomize Seed | `rct_graphics.tree_randomize` | Sets a new random seed and regenerates |
| Load Preset | `rct_graphics.tree_load_preset` | Applies a preset to the active tree, keeping its materials and seed |
| Make Unique | `rct_graphics.tree_make_unique` | Copies the shared role materials so this tree's edits don't affect other trees |
| Apply | `rct_graphics.tree_apply` | Sets `rct_tree.enabled = False`; the mesh stays and becomes a plain mesh that can be sculpted or edited. Confirmation popup |

### 8.3 Coupling with scene-wide settings

The size setting overlaps with the scene's `object_type` / `small_shape` /
footprint. Rules:

- **Add Tree** and changing a tree's `size` write the scene settings and
  report it in the status bar ("Object type set to Small Scenery, Full
  Tile").
- If the scene settings are later changed by hand so they no longer match
  the tree, the Tree panel shows a mismatch warning with a **Match Scene**
  button. Settings are not silently overwritten in either direction.
- With several generated trees in the scene, only the active one drives the
  scene settings. All visible trees are rendered, as the add-on renders
  every visible object.

### 8.4 Render look suggestions

Presets carry suggested values for `outline_shades` (2 for most trees, 1 for
topiary) and `palette_mode`. The Tree panel shows **Use Suggested Look**
when the scene differs. The generator never changes render settings without
that click, because they are scene-wide and may have been tuned.

### 8.5 Auto update

With `auto_update`, every `TreeSettings` property's `update` callback
regenerates the mesh. Dragging a slider fires many updates, so a regeneration
is skipped when the previous one finished less than 50 ms ago. A
`bpy.app.timers` callback then runs the last skipped request, so the final
slider value always wins.

## 9. Performance budget

| Item | Budget |
|---|---|
| Regeneration (default Broadleaf) | < 150 ms on a mid-range CPU |
| Regeneration (Conifer, the heaviest preset) | < 400 ms |
| Face count (default) | 2 000 - 8 000; hard warning above 50 000 |
| Branch segments | Capped at 400 (warning when reached) |
| Metaball resolution | Never finer than 0.06 BU (≈ ⅔ pixel) |

Render time is not a concern: sprites are tiny, and the existing samples
and supersampling settings apply.

## 10. Testing

### 10.1 Core unit tests (`tests/test_core_tree.py`, numpy only)

- **Determinism**: same parameters and seed give identical skeleton, blobs
  and tube vertices; a different seed gives a different result.
- **Stage independence**: changing `branch_count` leaves the trunk axis
  unchanged.
- **Straightness**: `straightness = 1`, `lean = 0`, `gnarl = 0` gives a trunk
  axis with x = y = 0 everywhere.
- **Taper**: radius never increases with height above the root flare.
- **Branch count**: number of first-level branches = `branch_count`, and
  sub-branches = `branch_count * sub_branches`, up to the segment cap.
- **Bounds**: for every size, all blob extents stay within
  `overhang * half_width` horizontally (plus displacement amplitude) and
  within `height` vertically.
- **Envelope SDFs**: known points inside/outside each shape.
- **Presets**: every preset produces non-empty trunk and canopy data (except
  `NONE` canopies and trunkless shrubs), within the performance caps.
- **Noise**: output in the expected range, continuous, seed-dependent.

### 10.2 Blender end-to-end tests (`tests/blender_tests.py`)

- Add a tree for each preset; the object has 4 material slots and every face
  index is valid.
- Regenerating keeps user-edited materials (change the leaf colour,
  regenerate, check the material is the same datablock with the same value).
- Setting the leaves to remap 1 then rendering a Broadleaf as small scenery
  gives 4 sprites with primary-remap pixels, and `object.json` has
  `hasPrimaryColour`.
- `QUARTER` and `LARGE 2x2` trees render with the expected sprite counts
  (4, and 4 + 4 x 4).
- Apply turns the tree into a plain mesh that is no longer regenerated.
- No temporary metaball objects or orphan meshes are left after 20
  regenerations.

## 11. Optional later phase: withering

OpenRCT2 supports `canWither` small scenery: with that flag,
`Paint.SmallScenery.cpp` adds 4 to the image index once the element passes
the first age threshold and 4 more past the second. A withering object thus
needs images 0-3 (healthy), 4-7 (withering) and 8-11 (withered). The
generator could produce those stages:

- Stage 1: remove 40 % of canopy blobs (seeded), shift leaf brightness
  down, and add an optional brown accent.
- Stage 2: remove 80 % of blobs, so mostly bare branches remain.

This needs a new job layout in `core/jobs.py` (three still "variants"
instead of animation frames), a `canWither` flag checkbox, and a rule that
withering and animation exclude each other. It is listed separately because
it is the only part that touches the render jobs.

## 12. Delivery plan

One commit per feature, matching the project's history:

1. **Core tree skeleton**: `core/tree.py` parameters, seeded noise,
   trunk/branch skeleton, envelopes, blob placement, presets;
   `tests/test_core_tree.py`.
2. **Tree generator object and panel**: `TreeSettings`, tube mesh,
   icosphere canopy, displacement, Add/Regenerate/Randomize, panel, size
   coupling.
3. **Metaball canopy and canopy styles**: merged blobs, layers, tiers,
   column, topiary, strands, accent and base.
4. **Tree materials and remap roles**: default node-group materials, role
   pointers, Colour dropdowns, Make Unique, Apply.
5. **Tree presets tuned against original sprites, docs and Blender
   tests**: README section, end-to-end tests.
6. *(Optional)* **Withering sprites**.

## 13. Acceptance criteria

- From a fresh scene: *Initialize*, *Add Tree (Broadleaf)*, *Render
  Sprites*, *Build .parkobj* produces a tree object that loads in OpenRCT2,
  is placed as a tree (`isTree`), and looks like the same family as
  `examples/0.png` at 1:1 zoom.
- Every parameter listed in the brief (size, recolourable and plain
  materials, trunk start/end size, leaf size, trunk straightness, branch
  count) is available in the panel and changes the result visibly.
- Material edits survive regeneration, preset changes and file reload.
- Same settings and seed give the same sprites on Linux, Windows and macOS.
- All new unit and Blender tests pass, and existing tests still pass.

## 14. Open questions

1. **Large trees**: are multi-tile trees wanted in the first version, or is
   small scenery (full/quarter) enough? Large adds little code, but the
   original game has almost no large trees.
2. **Half and three-quarter shapes**: left out because no original tree uses
   them. Should they be offered anyway?
3. **Geometry Nodes alternative**: the canopy and trunk could be built with a
   Geometry Nodes group instead of Python. That gives a live modifier and
   no regeneration step, but makes the generator hard to unit-test and tied
   to node API changes between Blender versions. This spec recommends
   Python; confirm.
4. **Wind animation**: worth a follow-up spec (vertex sway rendered as
   animation frames)?
