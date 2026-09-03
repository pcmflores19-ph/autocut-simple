#!/usr/bin/env python
"""
Downloads the VST3 plugins that ship with a build, into packaging/vst3/.

Only open-source, redistributable plugins. "Free" on a plugin site nearly
always means free of charge, not free to redistribute - the freeware used
during development (TDR, Soap Voice Cleaner and friends) may not be put inside
an installer without written permission, so none of it is here.

  rnnoise      GPL-3.0   noise suppression. Not a luxury: voice_activity uses
                         it to denoise before gating, and speech detection is
                         measurably worse without it. Bundling it is what makes
                         the auto-cut behave the same on every machine.
  ZamPlugins   GPL-2.0+  a curated six - gate, compressor, EQ, dynamic EQ,
                         limiter, noise reduction. A complete voice chain
                         without burying someone under the ~19 in the archive.

LSP Plugins were the first choice and had to be dropped: despite the LGPL
licence they publish no Windows builds at all, only Linux and FreeBSD.

ZamPlugins is GPL-2.0-OR-LATER (the COPYING file says 2, but every source
header adds "or, at your option, any later version"), so it is compatible with
pedalboard's GPL-3. Plain GPL-2.0-only would not have been.

pedalboard already makes the built application GPL-3, so a GPL plugin adds no
obligation that is not there already.

The binaries are NOT committed - packaging/vst3/ is gitignored. Run this once
before building, or let packaging/build.py do it.
"""

import io
import os
import shutil
import sys
import urllib.request
import zipfile

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT_DIR = os.path.join(BASE, "packaging", "vst3")
LICENSE_DIR = os.path.join(OUT_DIR, "licences")

# Asset names were checked against the GitHub API rather than guessed - the
# first attempt at both of these 404'd.
RNNOISE_URL = ("https://github.com/werman/noise-suppression-for-voice/releases/"
               "download/v1.10/win-rnnoise.zip")

ZAM_URL = ("https://github.com/zamaudio/zam-plugins/releases/download/"
           "4.5/zam-plugins-4.5-win64.zip")

# Exact stems, mono where there is a choice: the tracks this app handles are
# always mono, so the X2 stereo variants would only waste a channel. About
# 11 MB in total.
ZAM_WANTED = [
    "zamgate",          # noise gate - the idle mic
    "zamcomp",          # compressor - evens out a voice
    "zameq2",           # parametric EQ
    "zamdynamiceq",     # dynamic EQ - doubles as a de-esser
    "zamaximx2",        # limiter (stereo-only upstream, still fine)
    "zamnoise",         # broadband noise reduction
]


def _download(url):
    print(f"  downloading {url.rsplit('/', 1)[-1]} ...", flush=True)
    request = urllib.request.Request(
        url, headers={"User-Agent": "autocut-build"})
    with urllib.request.urlopen(request, timeout=300) as response:
        return response.read()


def _extract_vst3(data, wanted=None, limit=None):
    """
    Pulls .vst3 files (or bundle directories) out of a zip into OUT_DIR.

    Returns the names taken. `wanted` filters by substring; without it,
    everything is taken.
    """
    taken = []
    archive = zipfile.ZipFile(io.BytesIO(data))
    for entry in archive.namelist():
        if entry.endswith("/"):
            continue
        lowered = entry.lower()
        if ".vst3" not in lowered:
            continue
        name = os.path.basename(entry.rstrip("/"))
        stem = name.lower().replace(".vst3", "")
        if wanted and stem not in wanted:
            continue
        if limit and len(taken) >= limit:
            break
        # Preserve a bundle's inner structure (Contents/<arch>/Name.vst3);
        # vst_host._resolve_binary relies on it.
        marker = lowered.find(".vst3")
        relative = entry[:marker + 5].split("/")[-1] + entry[marker + 5:]
        target = os.path.join(OUT_DIR, relative.replace("/", os.sep))
        os.makedirs(os.path.dirname(target), exist_ok=True)
        with archive.open(entry) as src, open(target, "wb") as dst:
            shutil.copyfileobj(src, dst)
        taken.append(relative)
    return taken


def verify():
    """
    Loads every bundled plugin, so a broken one is caught here rather than as
    an empty FX window on someone else's machine.
    """
    sys.path.insert(0, os.path.join(BASE, "auto_cut"))
    import vst_host

    found = vst_host.discover_plugins(extra_dirs=[OUT_DIR])
    bundled = [(n, p) for n, p in found if OUT_DIR.lower() in p.lower()]
    if not bundled:
        print("  WARNING: nothing discoverable in packaging/vst3")
        return False

    ok = True
    import pedalboard
    for name, path in bundled:
        try:
            pedalboard.load_plugin(path)
            print(f"  ok    {name}")
        except Exception as exc:
            print(f"  FAIL  {name}: {str(exc)[:80]}")
            ok = False
    return ok


def main():
    os.makedirs(OUT_DIR, exist_ok=True)
    os.makedirs(LICENSE_DIR, exist_ok=True)

    print("rnnoise (GPL-3.0):")
    try:
        taken = _extract_vst3(_download(RNNOISE_URL))
        print(f"  took {len(taken)}: {', '.join(taken) or 'nothing'}")
    except Exception as exc:
        print(f"  FAILED: {exc}")

    print("ZamPlugins (GPL-2.0-or-later):")
    try:
        taken = _extract_vst3(_download(ZAM_URL), wanted=ZAM_WANTED)
        print(f"  took {len(taken)}")
        for name in taken:
            print(f"    {name}")
    except Exception as exc:
        print(f"  FAILED: {exc}")

    print("verifying every bundled plugin loads:")
    verify()
    print(f"\n{OUT_DIR}")


if __name__ == "__main__":
    main()
