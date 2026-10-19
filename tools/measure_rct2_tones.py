"""Print the shade table of the vanilla RCT2 trees used by core/tone.py.

Usage: python tools/measure_rct2_tones.py <RCT2 install folder>

For each tree: the share of each shade (0 darkest to 11 lightest) over the
four views, without the rim pixels and with them, and the mean HSV
saturation without the rim. Snow-covered trees are left out.
"""

import pathlib
import sys

import numpy as np

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from rct_cycles_graphics.core import palette, postprocess, rct2dat, tone  # noqa: E402


def measure(path):
    obj = rct2dat.read_small_scenery(path)
    interior_counts = np.zeros(tone.SHADE_COUNT)
    all_counts = np.zeros(tone.SHADE_COUNT)
    interior_colours = []
    for sprite in obj.images[:4]:
        opaque = sprite.indices != palette.TRANSPARENT
        interior = opaque & ~postprocess.edge_pixels(opaque)
        for mask, counts in ((interior, interior_counts), (opaque, all_counts)):
            positions = tone._POSITION_OF[sprite.indices[mask]]
            counts += np.bincount(positions[positions >= 0], minlength=tone.SHADE_COUNT)
        interior_colours.append(palette.PALETTE[sprite.indices[interior]].astype(np.float32))
    saturation = tone.saturation(np.concatenate(interior_colours))
    return interior_counts / interior_counts.sum(), all_counts / all_counts.sum(), saturation


def main():
    objdata = rct2dat.find_objdata(sys.argv[1])
    if objdata is None:
        sys.exit("No ObjData folder in {}".format(sys.argv[1]))
    print("RCT2_TREES = (")
    for code, name in rct2dat.VANILLA_TREES:
        if code in tone.SNOW_TREES:
            continue
        interior, rim_included, saturation = measure(rct2dat.find_object(objdata, code))
        print('    ("{}", "{}",'.format(code, name))
        print("     ({}),".format(", ".join("{:.4f}".format(v) for v in interior)))
        print("     ({}),".format(", ".join("{:.4f}".format(v) for v in rim_included)))
        print("     {:.3f}),".format(saturation))
    print(")")


if __name__ == "__main__":
    main()
