"""Package the add-on into dist/rct_cycles_graphics-<version>.zip.

The zip installs both as a legacy add-on (Edit > Preferences > Add-ons >
Install from Disk) and as a Blender 4.2+ extension.
"""

import pathlib
import re
import zipfile

ROOT = pathlib.Path(__file__).resolve().parent.parent
PACKAGE = ROOT / "rct_cycles_graphics"


def main():
    manifest = (PACKAGE / "blender_manifest.toml").read_text()
    version = re.search(r'^version = "([^"]+)"', manifest, re.M).group(1)
    dist = ROOT / "dist"
    dist.mkdir(exist_ok=True)
    target = dist / "rct_cycles_graphics-{}.zip".format(version)
    with zipfile.ZipFile(target, "w", zipfile.ZIP_DEFLATED) as archive:
        for path in sorted(PACKAGE.rglob("*")):
            if "__pycache__" in path.parts or path.is_dir():
                continue
            archive.write(path, path.relative_to(ROOT))
    print(target)


if __name__ == "__main__":
    main()
