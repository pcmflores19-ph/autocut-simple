"""
The number beside a slider, typed rather than only dragged.

A slider is good for a rough sweep and hopeless for an exact value: dragging to
2.0s, or to -18 dB, or to exactly 100%, is a fight against a few pixels. Every
slider in Wavefield therefore shows its value in a box you can type into, and
the two stay in step - drag and the box follows, type and the slider moves.

One helper rather than one per panel, because the fiddly parts (clamping to the
slider's range, restoring the old value when the typing is nonsense, and not
looping when each side updates the other) are worth getting right once.
"""

import tkinter as tk
from tkinter import ttk


def attach(parent, variable, low, high, on_commit=None, fmt=None, width=6,
           style="Value.TEntry"):
    """
    Builds the entry for `variable` and keeps it in step with its slider.

    Returns the widget unpacked, so the caller places it whichever way that
    panel is laid out. `on_commit` is called with the new value only when a
    typed number is accepted - the slider's own command already fires while
    dragging, and calling it twice makes work happen twice.
    """
    if fmt is None:
        fmt = (lambda v: f"{int(round(v))}") if isinstance(variable, tk.IntVar) \
            else (lambda v: f"{v:g}")

    text = tk.StringVar(value=fmt(variable.get()))
    entry = ttk.Entry(parent, textvariable=text, width=width, justify="right",
                      style=style)

    updating = {"busy": False}

    def follow(*_args):
        # Always, even while the box has focus: the value only changes here
        # because the slider moved or the app set it, and both are real changes
        # the box would otherwise sit there contradicting. Skipped only during
        # our own write below, which would otherwise reformat mid-commit.
        if updating["busy"]:
            return
        try:
            text.set(fmt(variable.get()))
        except tk.TclError:
            pass

    variable.trace_add("write", follow)

    def commit(_event=None):
        try:
            value = float(text.get().strip().rstrip("%s "))
        except ValueError:
            text.set(fmt(variable.get()))       # put back what it was
            return "break"
        value = max(low, min(high, value))
        # FocusOut fires after Return, so without this every commit happens
        # twice - and on the mixer that means reapplying the gain twice.
        unchanged = abs(value - float(variable.get())) < 1e-9
        updating["busy"] = True
        try:
            variable.set(int(round(value)) if isinstance(variable, tk.IntVar)
                         else value)
        finally:
            updating["busy"] = False
        text.set(fmt(value))
        if on_commit and not unchanged:
            on_commit(value)
        return "break"

    entry.bind("<Return>", commit)
    entry.bind("<KP_Enter>", commit)
    entry.bind("<FocusOut>", commit)
    return entry
