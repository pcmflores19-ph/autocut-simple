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
        options = dict(ui_theme.listbox_options())
        options.update(kwargs)
        box = tk.Listbox(wrap, exportselection=False,
                         yscrollcommand=vsb.set, xscrollcommand=hsb.set,
                         **options)
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

        # Built-in effects and VST3 plugins get a box each. Tagging one list
        # with "(VST3)" on every row was noise - the split says it once.
        left = ttk.Frame(top)
        left.grid(row=0, column=0, sticky="nsew", padx=(0, 5))
        left.rowconfigure(0, weight=0)
        left.rowconfigure(1, weight=1)
        left.columnconfigure(0, weight=1)

        builtin_frame = ttk.LabelFrame(left, text="Effects")
        builtin_frame.grid(row=0, column=0, sticky="nsew", pady=(0, 6))
        self.builtin_list = self._scrolled_listbox(
            builtin_frame, height=len(effects.EFFECTS))
        for _key, label, _fn, _params in effects.EFFECTS:
            self.builtin_list.insert("end", label)
        self.builtin_list.bind("<Double-Button-1>", lambda e: self._add_builtin())
        self.builtin_list.bind(
            "<<ListboxSelect>>",
            lambda e: self.vst_list.selection_clear(0, "end"))
        ttk.Button(builtin_frame, text="Add to chain  ->",
                   command=self._add_builtin).pack(padx=8, pady=(0, 8))

        vst_frame = ttk.LabelFrame(
            left, text=f"VST3 plugins ({len(self.available)} found)")
        vst_frame.grid(row=1, column=0, sticky="nsew")
        self.vst_list = self._scrolled_listbox(vst_frame, height=6)
        for name, _path in self.available:
            self.vst_list.insert("end", name)
        self.vst_list.bind("<Double-Button-1>", lambda e: self._add_vst())
        self.vst_list.bind(
            "<<ListboxSelect>>",
            lambda e: self.builtin_list.selection_clear(0, "end"))
        ttk.Button(vst_frame, text="Add to chain  ->",
                   command=self._add_vst).pack(padx=8, pady=(0, 8))

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
        """Rebuilds the settings panel for whatever is selected in the chain."""
        for child in self.params_frame.winfo_children():
            child.destroy()

        index = self._selected_index()
        slot = self.chain.slots[index] if index is not None and \
            index < len(self.chain.slots) else None
        if slot is None or not getattr(slot, "is_native", False):
            ttk.Label(self.params_frame,
                      text="Select an effect to change its settings. "
                           "VST3 plugins open their own window.",
                      style="PanelDim.TLabel").pack(anchor="w", padx=8, pady=6)
            return

        _label, _fn, spec = effects.BY_KEY[slot.key]
        grid = ttk.Frame(self.params_frame, style="Panel.TFrame")
        grid.pack(fill="x", padx=8, pady=6)
        grid.columnconfigure(1, weight=1)

        for row, (name, caption, lo, hi, default, unit) in enumerate(spec):
            ttk.Label(grid, text=caption, width=16, style="Panel.TLabel").grid(
                row=row, column=0, sticky="w", pady=2)

            var = tk.DoubleVar(value=float(slot.params.get(name, default)))
            entry_var = tk.StringVar(value=f"{var.get():g}")

            def commit(value, s=slot, n=name, v=var, ev=entry_var,
                       lo=lo, hi=hi):
                value = max(lo, min(hi, float(value)))
                s.params[n] = value
                v.set(value)
                ev.set(f"{value:g}")
                self.on_change()

            def on_slide(_v, v=var, c=commit):
                c(v.get())

            def on_typed(_e=None, ev=entry_var, c=commit, v=var):
                # A slider is fine for a rough sweep and hopeless for "-18".
                try:
                    c(float(ev.get()))
                except ValueError:
                    ev.set(f"{v.get():g}")      # put back what it was
                return "break"

            scale = ttk.Scale(grid, from_=lo, to=hi, orient="horizontal",
                              variable=var, command=on_slide)
            scale.grid(row=row, column=1, sticky="ew", padx=8)

            entry = ttk.Entry(grid, textvariable=entry_var, width=7,
                              justify="right")
            entry.grid(row=row, column=2, sticky="e")
            entry.bind("<Return>", on_typed)
            entry.bind("<FocusOut>", on_typed)

            ttk.Label(grid, text=unit, width=5,
                      style="PanelDim.TLabel").grid(row=row, column=3,
                                                    sticky="w", padx=(4, 0))

        ttk.Button(grid, text="Reset to defaults", width=18,
                   command=lambda s=slot: self._reset_params(s)).grid(
                       row=len(spec), column=1, sticky="w", padx=8, pady=(8, 2))

    def _reset_params(self, slot):
        slot.params = dict(effects.defaults(slot.key))
        self.on_change()
        self._show_params()

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

    def _add_builtin(self):
        sel = self.builtin_list.curselection()
        if not sel:
            return
        key = effects.EFFECTS[sel[0]][0]
        self.chain.add_native(key)
        self.log(f"Added {effects.BY_KEY[key][0]}.")
        self._refresh_chain()
        # Select what was just added, so its sliders appear straight away.
        self.chain_list.selection_clear(0, "end")
        self.chain_list.selection_set(len(self.chain.slots) - 1)
        self._show_params()

    def _add_vst(self):
        sel = self.vst_list.curselection()
        if not sel:
            return
        name, path = self.available[sel[0]]
        # Loading a plugin while the audio callback is inside one is a native
        # crash, so playback stops first.
        if self.player and self.player.is_playing:
            self.player.stop()
        try:
            self.chain.add(name, path)
            self.log(f"Added {name}.")
        except Exception as exc:
            messagebox.showerror("Could not load plugin",
                                 f"{name}\n\n{exc}", parent=self)
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
