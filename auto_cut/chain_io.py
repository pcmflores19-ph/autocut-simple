"""
Turning an effect chain into JSON and back.

Lifted out of project.py because two things now need it: a saved project, and a
saved preset. Keeping one implementation means a preset and a project can never
drift into slightly different shapes - which they would, because nobody
remembers to change two serialisers.

The one thing this does that project.py did not is find a VST3 again when its
path has moved. A project is reopened on the machine that wrote it, so an
absolute path was good enough; a preset is meant to outlive the machine, and
plugin folders differ between installs.

Not to be confused with TrackChain.snapshot(), which looks similar and is for
something else entirely: it drops bypassed slots, because it exists to render
audio offline. Serialising with it would silently discard the bypassed EQ
someone deliberately kept.
"""

import base64
import os


def to_dict(chain):
    """A chain as plugin paths plus each plugin's own serialized state."""
    if chain is None:
        return {"enabled": True, "slots": []}
    slots = []
    for slot in chain.slots:
        if getattr(slot, "is_native", False):
            # A built-in effect is just a key and some numbers - no plugin
            # state to serialise, and it can never fail to reload.
            slots.append({"kind": "native", "key": slot.key,
                          "name": slot.name, "bypassed": slot.bypassed,
                          "params": dict(slot.params)})
            continue
        try:
            raw = base64.b64encode(slot.plugin.raw_state).decode("ascii")
        except Exception:
            raw = None      # plugin can't serialize; it'll load at defaults
        slots.append({"kind": "vst3", "name": slot.name, "path": slot.path,
                      "bypassed": slot.bypassed, "raw_state": raw})
    return {"enabled": bool(chain.enabled), "slots": slots}


def _find_plugin(name, path, log=None):
    """
    Where this plugin lives now, or None.

    The saved path first, because it is exact. Failing that, the display name
    against whatever is installed - `discover_plugins` builds its names the
    same way, so a plugin that merely moved is found again rather than dropped.
    """
    if path and os.path.exists(path):
        return path
    try:
        import vst_host
        for display_name, found in vst_host.discover_plugins():
            if display_name == name:
                if log:
                    log(f"{name}: found at a new location")
                return found
    except Exception:
        pass
    return None


def from_dict(data, log=None):
    """Rebuilds a chain, skipping plugins that no longer load."""
    import vst_host

    chain = vst_host.TrackChain()
    chain.enabled = bool(data.get("enabled", True))
    for entry in data.get("slots", []):
        if entry.get("kind") == "native":
            try:
                slot = chain.add_native(entry["key"], entry.get("params"))
                slot.bypassed = bool(entry.get("bypassed"))
            except Exception as exc:
                if log:
                    log(f"Effect skipped: {entry.get('name', '?')} ({exc})")
            continue
        name = entry.get("name", "?")
        path = _find_plugin(name, entry.get("path"), log)
        if not path:
            if log:
                log(f"Plugin missing, skipped: {name}")
            continue
        try:
            slot = chain.add(name, path)
        except Exception as exc:
            if log:
                log(f"Plugin failed to load, skipped: {name} ({exc})")
            continue
        slot.bypassed = bool(entry.get("bypassed"))
        raw = entry.get("raw_state")
        if raw:
            try:
                slot.apply_state(base64.b64decode(raw))
            except Exception as exc:
                if log:
                    log(f"{name}: saved settings could not be restored ({exc})")
    return chain
