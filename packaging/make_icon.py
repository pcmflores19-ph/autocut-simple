#!/usr/bin/env python
"""
Turns the logo PNG into the two forms the build needs.

  packaging/autocut.ico        the Windows shell icon, for the .exe and the
                               installer. Multi-resolution: Windows picks the
                               size it wants, and a single large image scaled
                               down by the shell looks noticeably worse in the
                               taskbar than a properly authored small one.
  auto_cut/assets/autocut.png  the tkinter window icon. Tk 8.6 reads PNG
                               natively and iconphoto() works on every
                               platform, where iconbitmap() is Windows-only.

Run directly, or let packaging/build.py call it.
"""

import os
import sys

# Windows uses 16 in the title bar, 32 in the taskbar and alt-tab, 256 in
# large-icon views. The in-between sizes cost a few KB and stop the shell
# having to scale.
ICO_SIZES = [16, 24, 32, 48, 64, 128, 256]

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEFAULT_SOURCE = os.path.join(BASE, "packaging", "logo-source.png")
ICO_PATH = os.path.join(BASE, "packaging", "autocut.ico")
PNG_PATH = os.path.join(BASE, "auto_cut", "assets", "autocut.png")

# The window icon is only ever drawn small; 256 is plenty and keeps the file
# out of the way in the repository.
WINDOW_PNG_SIZE = 256


def make(source=None):
    from PIL import Image

    source = source or DEFAULT_SOURCE
    if not os.path.exists(source):
        raise SystemExit(
            f"Logo not found: {source}\n"
            f"Put the logo there, or pass a path: python make_icon.py <file>")

    image = Image.open(source).convert("RGBA")
    if image.width != image.height:
        # Square it by padding rather than stretching - a squashed logo is
        # obvious in a taskbar.
        side = max(image.size)
        square = Image.new("RGBA", (side, side), (0, 0, 0, 0))
        square.paste(image, ((side - image.width) // 2,
                             (side - image.height) // 2))
        image = square

    os.makedirs(os.path.dirname(ICO_PATH), exist_ok=True)
    os.makedirs(os.path.dirname(PNG_PATH), exist_ok=True)

    image.save(ICO_PATH, format="ICO",
               sizes=[(s, s) for s in ICO_SIZES])
    image.resize((WINDOW_PNG_SIZE, WINDOW_PNG_SIZE),
                 Image.LANCZOS).save(PNG_PATH, format="PNG")

    print(f"wrote {ICO_PATH}  ({', '.join(str(s) for s in ICO_SIZES)})")
    print(f"wrote {PNG_PATH}  ({WINDOW_PNG_SIZE}x{WINDOW_PNG_SIZE})")
    return ICO_PATH, PNG_PATH


if __name__ == "__main__":
    make(sys.argv[1] if len(sys.argv) > 1 else None)
