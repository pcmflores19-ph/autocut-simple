"""
Settings that belong to this computer rather than to an episode.

Projects already save everything about a recording - files, edits, levels,
effect chains. What they cannot save is where WhisperX lives, because that is
a property of the machine: copy a project to another computer and the path
would be wrong.

Small and best-effort by design. A settings file that cannot be read must never
stop the app starting; it just falls back to defaults.
"""

import json
import os

APP_DIR_NAME = "AutoCut"
FILE_NAME = "settings.json"

DEFAULTS = {
    # Blank means "find it yourself". A path here is a deliberate override for
    # someone who installed WhisperX somewhere unusual - which is common,
    # because installing it into its own virtualenv is the sensible way to do
    # it and that is never on the PATH.
    "whisperx_path": "",
}


def config_dir():
    if os.name == "nt":
        base = os.environ.get("APPDATA") or os.path.expanduser("~")
        return os.path.join(base, APP_DIR_NAME)
    base = os.environ.get("XDG_CONFIG_HOME") or os.path.expanduser("~/.config")
    return os.path.join(base, APP_DIR_NAME.lower())


def config_path():
    return os.path.join(config_dir(), FILE_NAME)


_cache = None


def load(force=False):
    """Every setting, defaults filled in for anything missing."""
    global _cache
    if _cache is not None and not force:
        return _cache

    values = dict(DEFAULTS)
    try:
        with open(config_path(), "r", encoding="utf-8") as f:
            stored = json.load(f)
        if isinstance(stored, dict):
            # Only keys we know about: an old or hand-edited file should not be
            # able to inject anything unexpected.
            for key in DEFAULTS:
                if key in stored:
                    values[key] = stored[key]
    except Exception:
        pass                     # missing or unreadable is the normal case
    _cache = values
    return _cache


def get(key):
    return load().get(key, DEFAULTS.get(key))


def set_value(key, value):
    """Writes one setting through to disk. Returns True if it was saved."""
    values = load()
    values[key] = value
    try:
        os.makedirs(config_dir(), exist_ok=True)
        with open(config_path(), "w", encoding="utf-8") as f:
            json.dump(values, f, indent=2)
        return True
    except Exception:
        return False             # read-only profile, locked file, full disk
