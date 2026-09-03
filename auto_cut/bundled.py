"""
Locating things that move when the app is frozen into an executable.

Run from source, ffmpeg comes off the PATH and the plugin editor is a Python
script. Inside a PyInstaller build neither is true: ffmpeg ships beside the
executable, and there is no Python interpreter to hand a script to.

Everything here is a no-op when running from source, so there is exactly one
code path to reason about.
"""

import os
import shutil
import sys


def frozen():
    return getattr(sys, "frozen", False)


def _bundle_dir():
    """
    Where our own files live. For a PyInstaller one-folder build that is the
    directory holding the executable; _MEIPASS covers the one-file case too.
    """
    if not frozen():
        return os.path.dirname(os.path.abspath(__file__))
    return getattr(sys, "_MEIPASS", os.path.dirname(sys.executable))


def tool(name):
    """
    Full path to a bundled command-line tool, or its bare name.

    Bundled copies win over anything on the PATH: the build ships a known-good
    ffmpeg, and picking up some other version a user happens to have installed
    is how you get bug reports that cannot be reproduced.
    """
    exe = name + (".exe" if os.name == "nt" else "")
    candidate = os.path.join(_bundle_dir(), "ffmpeg", exe)
    if os.path.exists(candidate):
        return candidate
    candidate = os.path.join(_bundle_dir(), exe)
    if os.path.exists(candidate):
        return candidate
    return name          # from source: whatever is on the PATH


def have_tool(name):
    path = tool(name)
    return os.path.isabs(path) or shutil.which(path) is not None


# --------------------------------------------------------- plugin editor

# A frozen app has no interpreter to run plugin_editor.py with - sys.executable
# is the app itself, so the obvious command would just start a second copy of
# the whole editor. Instead the executable re-launches itself behind this flag
# and app.main() hands straight over to the plugin editor.
EDITOR_FLAG = "--plugin-editor"


def editor_command(plugin_path, state_file=None):
    """The argv for opening one plugin's window in a separate process."""
    if frozen():
        cmd = [sys.executable, EDITOR_FLAG, plugin_path]
    else:
        script = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                              "plugin_editor.py")
        cmd = [sys.executable, script, plugin_path]
    if state_file:
        cmd.append(state_file)
    return cmd
