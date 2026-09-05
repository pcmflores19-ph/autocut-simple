"""
Named effect chains, saved once and reused on every episode.

Setting up a voice chain is fiddly and the answer barely changes between
episodes: the same compressor, the same gate, roughly the same numbers for the
same microphone. Rebuilding it each time is the sort of repetition that makes
people give up on the feature.

Kept in its own file next to settings.json rather than inside it, because
settings.load() only returns keys it already knows about (see its DEFAULTS) and
would silently drop anything else. A separate file also means a preset library
survives a settings file being deleted, and the other way round.

Same JSON as a project's chain, via chain_io, so a preset and a project can
never disagree about what an effect chain looks like.
"""

import json
import os

import chain_io
import settings

FILE_NAME = "fx_presets.json"
FORMAT_VERSION = 1


def path():
    return os.path.join(settings.config_dir(), FILE_NAME)


def _read():
    """Every preset, as {name: chain_dict}. Never raises."""
    try:
        # utf-8-sig for the same reason settings.py uses it: a file that has
        # been near a Windows tool may carry a byte order mark.
        with open(path(), "r", encoding="utf-8-sig") as handle:
            data = json.load(handle)
    except Exception:
        return {}
    presets = data.get("presets") if isinstance(data, dict) else None
    return presets if isinstance(presets, dict) else {}


def _write(presets):
    try:
        os.makedirs(settings.config_dir(), exist_ok=True)
        # Written to a temporary file first: a half-written preset library is
        # worse than none, and this file is rewritten on every save.
        temp = path() + ".tmp"
        with open(temp, "w", encoding="utf-8") as handle:
            json.dump({"version": FORMAT_VERSION, "presets": presets},
                      handle, indent=2)
        os.replace(temp, path())
        return True
    except Exception:
        return False


def names():
    """Preset names, in a stable order for a menu."""
    return sorted(_read().keys(), key=str.lower)


def save(name, chain):
    """
    Stores `chain` under `name`, replacing any preset of that name.

    The chain's own enabled flag is deliberately not saved: whether a track's
    effects are switched on belongs to that track, not to the recipe. Loading a
    preset should never silently mute or unmute a track.
    """
    name = (name or "").strip()
    if not name:
        return False
    data = chain_io.to_dict(chain)
    data.pop("enabled", None)
    presets = _read()
    presets[name] = data
    return _write(presets)


def load(name, log=None):
    """
    Rebuilds the named preset as a fresh TrackChain, or None if unknown.

    Missing VST3 plugins are skipped with a note rather than failing the whole
    preset - a chain of five effects where one plugin was uninstalled is still
    worth four effects.
    """
    data = _read().get(name)
    if data is None:
        return None
    return chain_io.from_dict(dict(data, enabled=True), log=log)


def delete(name):
    presets = _read()
    if name not in presets:
        return False
    del presets[name]
    return _write(presets)


def describe(name):
    """A one-line summary for a menu or a confirmation, without loading it."""
    data = _read().get(name)
    if not data:
        return ""
    slots = data.get("slots", [])
    if not slots:
        return "empty"
    return " -> ".join(slot.get("name", "?") for slot in slots)
