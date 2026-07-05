#!/usr/bin/env python3
"""Package the add-on into a distributable ``.ankiaddon`` file.

An ``.ankiaddon`` file is just a zip of the *contents* of the add-on folder
(the files must sit at the zip root, not inside a sub-directory). Run:

    python build.py

The archive is written to ``dist/anki-discord-rich-presence.ankiaddon``.
"""

from __future__ import annotations

import os
import zipfile

HERE = os.path.dirname(os.path.abspath(__file__))
SRC = os.path.join(HERE, "addon")
DIST = os.path.join(HERE, "dist")
OUTPUT = os.path.join(DIST, "anki-discord-rich-presence.ankiaddon")

# Never ship these into the archive.
EXCLUDE_DIRS = {"__pycache__"}
EXCLUDE_FILES = {"meta.json", ".DS_Store"}


def build() -> str:
    os.makedirs(DIST, exist_ok=True)
    if os.path.exists(OUTPUT):
        os.remove(OUTPUT)

    files = []
    for root, dirs, names in os.walk(SRC):
        dirs[:] = [d for d in dirs if d not in EXCLUDE_DIRS]
        for name in names:
            if name in EXCLUDE_FILES:
                continue
            abspath = os.path.join(root, name)
            arcname = os.path.relpath(abspath, SRC)
            files.append((abspath, arcname))

    files.sort(key=lambda pair: pair[1])
    with zipfile.ZipFile(OUTPUT, "w", zipfile.ZIP_DEFLATED) as zf:
        for abspath, arcname in files:
            zf.write(abspath, arcname)

    print("Wrote %s" % OUTPUT)
    for _, arcname in files:
        print("  + %s" % arcname)
    return OUTPUT


if __name__ == "__main__":
    build()
