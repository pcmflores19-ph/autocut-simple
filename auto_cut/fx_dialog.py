"""
Per-track effects: the built-in effects, any VST3 installed on this machine,
and the chain for one speaker's track.

The built-in effects (effects.py, ported from OBS) are edited here with plain
sliders. VST3 plugins are edited through their OWN native GUI - double-click
one in the chain to open it. Rebuilding parameter controls for a VST3 from the
host side was tried and dropped: the reconstructed values did not reliably
match plugin state. Our own effects have no such problem, because we know
exactly what their parameters mean.
"""

import tkinter as tk
from tkinter import messagebox, ttk

import effects
import ui_theme
from vst_host import discover_plugins, open_editor_subprocess


class FxDialog(tk.Toplevel):
    def __init__(self, parent, track_name, chain, on_change=None, log=None,
                 player=None):
        super().__init__(parent)
        self.title(f"Effects - {track_name}")
        self.geometry("720x420")
        self.transient(parent)

        self.chain = chain
        self.on_change = on_change or (lambda: None)
        self.log = log or (lambda msg: None)
        self.player = player        # paused around plugin loads
        self.available = discover_plugins()

        self._build()
        self._refresh_chain()

    # ---------- layout ----------

    @staticmethod
    def _scrolled_listbox(parent, **kwargs):
        """Listbox with vertical and horizontal scrollbars that always show."""
        wrap = ttk.Frame(parent)
        wrap.pack(fill="both", expand=True, padx=8, pady=8)
        vsb = ttk.Scrollbar(wrap, orient="vertical")
        hsb = ttk.Scrollbar(wrap, orient="horizontal")
        box = tk.Listbox(wrap, exportselection=False,
                         yscrollcommand=vsb.set, xscrollcommand=hsb.set, **kwargs)
        vsb.config(command=box.yview)
        hsb.config(command=box.xview)
        box.grid(row=0, column=0, sticky="nsew")
        vsb.grid(row=0, column=1, sticky="ns")
        hsb.grid(row=1, column=0, sticky="ew")
        wrap.rowconfigure(0, weight=1)
        wrap.columnconfigure(0, weight=1)
        return box

    def _build(self):
        self.resizable(True, True)
        self.minsize(560, 320)

        self.rowconfigure(0, weight=1)     # plugin lists
        self.columnconfigure(0, weight=1)

        top = ttk.Frame(self)
        top.grid(row=0, column=0, sticky="nsew", padx=10, pady=10)
        top.rowconfigure(0, weight=1)
        top.columnconfigure(0, weight=1)
        top.columnconfigure(1, weight=1)

        # Available effects (left): the built-in ones first, because they are
        # the ones that are always there and always work.
        avail_frame = ttk.LabelFrame(
            top, text=f"Available  ({len(effects.EFFECTS)} built in, "
                      f"{len(self.available)} VST3)")
        avail_frame.grid(row=0, column=0, sticky="nsew", padx=(0, 5))

        self.avail_list = self._scrolled_listbox(avail_frame, height=10)
        # (kind, key_or_path) parallel to what is shown.
        self.avail_items = []
        for key, label, _fn, _params in effects.EFFECTS:
            self.avail_list.insert("end", label)
            self.avail_items.append(("native", key))
        for name, path in self.available:
            self.avail_list.insert("end", f"{name}   (VST3)")
            self.avail_items.append(("vst3", path))
        self.avail_list.bind("<Double-Button-1>", lambda e: self._add())
        ttk.Button(avail_frame, text="Add to chain  ->",
                   command=self._add).pack(padx=8, pady=(0, 8))

        # Chain (right)
        chain_frame = ttk.LabelFrame(top, text="Chain (signal flows top to bottom)")
        chain_frame.grid(row=0, column=1, sticky="nsew", padx=(5, 0))

        self.chain_list = self._scrolled_listbox(chain_frame, height=10)
        self.chain_list.bind("<Double-Button-1>", lambda e: self._open_editor())

        chain_buttons = ttk.Frame(chain_frame)
        chain_buttons.pack(fill="x", padx=8, pady=(0, 4))
        ttk.Button(chain_buttons, text="Up", width=5,
                   command=lambda: self._move(-1)).pack(side="left")
        ttk.Button(chain_buttons, text="Down", width=6,
                   command=lambda: self._move(1)).pack(side="left", padx=2)
        ttk.Button(chain_buttons, text="Bypass", width=8,
                   command=self._toggle_bypass).pack(side="left", padx=2)
        ttk.Button(chain_buttons, text="Remove", width=8,
                   command=self._remove).pack(side="left")

        self.chain_enabled = tk.BooleanVar(value=self.chain.enabled)
        ttk.Checkbutton(chain_frame, text="Chain active on this track",
                        variable=self.chain_enabled,
                        command=self._toggle_chain).pack(anchor="w", padx=8, pady=(0, 8))

        # Sliders for whichever built-in effect is selected. Empty for a VST3,
        # which has its own window instead.
        self.params_frame = ttk.LabelFrame(self, text="Settings")
        self.params_frame.grid(row=1, column=0, sticky="ew", padx=10, pady=(0, 6))
        self.chain_list.bind("<<ListboxSelect>>", lambda e: self._show_params())

        bottom = ttk.Frame(self)
        bottom.grid(row=2, column=0, sticky="ew", padx=10, pady=(0, 10))
        ttk.Button(bottom, text="Open plugin GUI",
                   command=self._open_editor).pack(side="left")
        ttk.Label(bottom,
                  text="Built-in effects use the sliders above. Double-click a "
                       "VST3 in the chain to open its own window. Changes apply "
                       "live to playback.",
                  foreground="#888").pack(side="left", padx=10)
        ttk.Button(bottom, text="Close", command=self.destroy).pack(side="right")

    # ---------- chain operations ----------

    def _show_params(self):
        """Rebuilds the slider panel for the selected chain entry."""
        for child in self.params_frame.winfo_children():
            child.destroy()

        index = self._selected_index()
        slot = self.chain.slots[index] if index is not None and \
            index < len(self.chain.slots) else None
        if slot is None or not getattr(slot, "is_native", False):
            ttk.Label(self.params_frame,
                      text="Select a built-in effect to change its settings. "
                           "VST3 plugins open their own window.",
                      foreground="#888").pack(anchor="w", padx=8, pady=6)
            return

        _label, _fn, spec = effects.BY_KEY[slot.key]
        grid = ttk.Frame(self.params_frame)
        grid.pack(fill="x", padx=8, pady=6)
        grid.columnconfigure(1, weight=1)

        for row, (name, caption, lo, hi, _default, unit) in enumerate(spec):
            ttk.Label(grid, text=caption, width=15).grid(
                row=row, column=0, sticky="w", pady=1)
            var = tk.DoubleVar(value=float(slot.params.get(name, _default)))
            value_label = ttk.Label(grid, width=11, anchor="e")

            def on_change(_v, s=slot, n=name, v=var, lbl=value_label, u=unit):
                s.params[n] = float(v.get())
                lbl.config(text=f"{v.get():.1f} {u}")
                self.on_change()

            scale = ttk.Scale(grid, from_=lo, to=hi, orient="horizontal",
                              variable=var, command=on_change)
            scale.grid(row=row, column=1, sticky="ew", padx=6)
            value_label.grid(row=row, column=2, sticky="e")
            value_label.config(text=f"{var.get():.1f} {unit}")

    def _selected_index(self):
        sel = self.chain_list.curselection()
        return sel[0] if sel else None

    def _refresh_chain(self):
        keep = self._selected_index()
        self.chain_list.delete(0, "end")
        for slot in self.chain.slots:
            label = f"{slot.name}   [bypassed]" if slot.bypassed else slot.name
            self.chain_list.insert("end", label)
        if keep is not None and keep < self.chain_list.size():
            self.chain_list.selection_set(keep)
        self.on_change()
        if hasattr(self, "params_frame"):
            self._show_params()

    def _add(self):
        sel = self.avail_list.curselection()
        if not sel:
            return
        kind, value = self.avail_items[sel[0]]

        if kind == "native":
            self.chain.add_native(value)
            self.log(f"Added {effects.BY_KEY[value][0]}.")
            self._refresh_chain()
            self._show_params()
            return

        name = self.avail_list.get(sel[0]).split("   (VST3)")[0]
        # Loading a plugin while the audio callback is inside one is a native
        # crash, so playback stops first.
        was_playing = bool(self.player and self.player.is_playing)
        if was_playing:
            self.player.stop()
        try:
            self.chain.add(name, value)
            self.log(f"Added {name}.")
        except Exception as exc:
            messagebox.showerror("Could not load plugin",
                                 f"{name}\n\n{exc}", parent=self)
            return
        finally:
            self._refresh_chain()

    def _remove(self):
        i = self._selected_index()
        if i is None:
            return
        self.log(f"Removed {self.chain.slots[i].name} from the chain.")
        self.chain.remove(i)
        self._refresh_chain()

    def _move(self, delta):
        i = self._selected_index()
        if i is None:
            return
        new_index = self.chain.move(i, delta)
        self._refresh_chain()
        self.chain_list.selection_clear(0, "end")
        self.chain_list.selection_set(new_index)

    def _toggle_bypass(self):
        i = self._selected_index()
        if i is None:
            return
        slot = self.chain.slots[i]
        slot.bypassed = not slot.bypassed
        self._refresh_chain()

    def _toggle_chain(self):
        self.chain.enabled = self.chain_enabled.get()
        self.on_change()

    # ---------- native editor ----------

    def _open_editor(self):
        i = self._selected_index()
        if i is None:
            return
        slot = self.chain.slots[i]

        def done():
            self.log(f"{slot.name}: settings applied.")
            self.on_change()

        def failed(message):
            self.log(f"{slot.name}: could not open plugin GUI - {message}")

        self.log(f"Opening {slot.name} GUI in a separate window "
                 "(close it to apply your changes).")
        open_editor_subprocess(slot, on_done=done, on_error=failed)
