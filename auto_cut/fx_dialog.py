"""
Per-track VST3 chain editor: a popup listing the plugins available on this
machine and the chain for one speaker's track.

Plugins are edited through their OWN native GUI - double-click one in the chain
to open it. Rebuilding parameter controls from the host side was tried and
dropped: the reconstructed values did not reliably match plugin state.
"""

import tkinter as tk
from tkinter import messagebox, ttk

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

        # Available plugins (left)
        avail_frame = ttk.LabelFrame(top, text=f"Available VST3 ({len(self.available)} found)")
        avail_frame.grid(row=0, column=0, sticky="nsew", padx=(0, 5))

        self.avail_list = self._scrolled_listbox(avail_frame, height=10)
        for name, _path in self.available:
            self.avail_list.insert("end", name)
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

        bottom = ttk.Frame(self)
        bottom.grid(row=1, column=0, sticky="ew", padx=10, pady=(0, 10))
        ttk.Button(bottom, text="Open plugin GUI",
                   command=self._open_editor).pack(side="left")
        ttk.Label(bottom,
                  text="Double-click a plugin in the chain to open its own GUI. "
                       "Changes apply live to playback.",
                  foreground="#888").pack(side="left", padx=10)
        ttk.Button(bottom, text="Close", command=self.destroy).pack(side="right")

    # ---------- chain operations ----------

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

    def _add(self):
        sel = self.avail_list.curselection()
        if not sel:
            return
        name, path = self.available[sel[0]]
        # Belt and braces: stop the audio thread before loading, so it cannot
        # be inside pedalboard while the plugin is constructed.
        resume = False
        player = getattr(self, "player", None)
        if player is not None and player.is_playing:
            player.pause()
            resume = True
        try:
            self.chain.add(name, path)
            self.log(f"Added {name} to the chain.")
        except Exception as exc:
            messagebox.showerror("Could not load plugin",
                                 f"{name} failed to load:\n\n{exc}", parent=self)
            return
        finally:
            if resume and player is not None:
                player.play()
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
