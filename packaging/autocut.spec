# PyInstaller spec for Auto-Cut.
#
# Build from the repository root:
#     pyinstaller packaging/autocut.spec --noconfirm
#
# Produces dist/AutoCut/ - a one-folder build. Deliberately not one-file:
# a single .exe unpacks itself to a temp directory on every launch, which is
# slow and is exactly the behaviour antivirus heuristics flag.
#
# ffmpeg is copied in from FFMPEG_DIR so the installed app has no external
# dependencies at all. WhisperX is NOT bundled and never will be - it pulls in
# torch and CUDA, several gigabytes, for a feature that is optional.

import os
import shutil

BASE = os.path.abspath(os.path.join(SPECPATH, ".."))
SRC = os.path.join(BASE, "auto_cut")

# Where to find ffmpeg.exe / ffprobe.exe to ship. Override with the
# AUTOCUT_FFMPEG_DIR environment variable.
FFMPEG_DIR = os.environ.get("AUTOCUT_FFMPEG_DIR", r"C:\ffmpeg\bin")


def _ffmpeg_binaries():
    """(source, dest) pairs for the two ffmpeg tools, if we can find them."""
    found = []
    for name in ("ffmpeg", "ffprobe"):
        exe = name + (".exe" if os.name == "nt" else "")
        path = os.path.join(FFMPEG_DIR, exe)
        if not os.path.exists(path):
            path = shutil.which(name) or ""
        if path and os.path.exists(path):
            found.append((path, "ffmpeg"))
        else:
            print(f"WARNING: {exe} not found - the build will need ffmpeg on "
                  f"the user's PATH. Set AUTOCUT_FFMPEG_DIR to bundle it.")
    return found


def _bundled_plugins():
    """
    The open-source voice chain from fetch_plugins.py, if it has been run.

    Shipping rnnoise is not cosmetic: voice_activity uses it to denoise before
    gating, so without it the auto-cut is measurably worse on a machine that
    has no copy installed.
    """
    source = os.path.join(SPECPATH, "vst3")
    if not os.path.isdir(source):
        print("WARNING: packaging/vst3 is empty - run fetch_plugins.py to "
              "bundle the plugins, or the FX window will be empty on a "
              "clean machine.")
        return []
    return [(source, "vst3")]


a = Analysis(
    [os.path.join(SRC, "app.py")],
    pathex=[SRC],                  # flat sibling imports: `import ui_theme`
    binaries=_ffmpeg_binaries(),
    datas=[
        (os.path.join(SPECPATH, "THIRD-PARTY-NOTICES.txt"), "."),
        (os.path.join(SPECPATH, "FFMPEG-LICENSE.txt"), "."),
        (os.path.join(BASE, "LICENSE"), "."),
        # The window icon. The `icon=` on EXE below is the shell icon for the
        # .exe file itself and does nothing for the tkinter window.
        (os.path.join(SRC, "assets"), "assets"),
    ] + _bundled_plugins(),
    # These are reached only through the frozen re-launch or lazily inside
    # functions, so PyInstaller's import scan does not see them.
    hiddenimports=[
        "plugin_editor",
        "sounddevice",
        "pedalboard",
    ],
    hookspath=[],
    runtime_hooks=[],
    # WhisperX and friends stay external. Excluding them keeps an accidental
    # torch install in the build environment from adding gigabytes.
    excludes=[
        "torch", "torchaudio", "torchvision", "whisperx", "transformers",
        "matplotlib", "scipy", "pandas", "IPython", "pytest",
    ],
    noarchive=False,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="Wavefield",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,                     # UPX compression is another antivirus trigger
    console=False,                 # a GUI app: no console window behind it
    icon=os.path.join(SPECPATH, "autocut.ico")
         if os.path.exists(os.path.join(SPECPATH, "autocut.ico")) else None,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    name="Wavefield",
)
