"""
A modal progress window for exports.

Exports already ran on a worker thread with only a small spinner in the status
bar, which left the app fully interactive while it rendered. Editing during an
export is how it crashed: the edit changes the very ranges the render is
walking through.

So this takes a grab. It is the only modal window in the app - FxDialog and the
help windows deliberately are not - because it is the only place where carrying
on would corrupt the result.
"""

import tkinter as tk
from tkinter import ttk

import ui_theme


class ProgressDialog(tk.Toplevel):
    """
    Blocks the main window until the work finishes or is cancelled.

    The worker owns the thread; this only displays and signals. Call `step()`
    from the worker via `root.after` - never touch tkinter from the worker
    thread directly.
    """

    def __init__(self, parent, title="Exporting", message="Working..."):
        super().__init__(parent)
        self.title(title)
        self.configure(background=ui_theme.BG)
        self.resizable(False, False)
        self.transient(parent)

        self.cancelled = False
        self._closed = False

        frame = ttk.Frame(self, style="Panel.TFrame")
        frame.pack(fill="both", expand=True, padx=16, pady=14)

        self.message = ttk.Label(frame, text=message, style="Panel.TLabel",
                                 wraplength=430, justify="left")
        self.message.pack(anchor="w")

        self.bar = ttk.Progressbar(frame, mode="indeterminate", length=440)
        self.bar.pack(fill="x", pady=(10, 6))
        self.bar.start(12)

        self.detail = ttk.Label(frame, text="", style="PanelDim.TLabel",
                                wraplength=430, justify="left")
        self.detail.pack(anchor="w")

        self.cancel_button = ttk.Button(frame, text="Cancel", width=12,
                                        command=self._cancel)
        self.cancel_button.pack(anchor="e", pady=(12, 0))

        # Closing with the X means the same as Cancel - it must never just
        # dismiss the window and leave the render running invisibly.
        self.protocol("WM_DELETE_WINDOW", self._cancel)

        self.update_idletasks()
        self._centre(parent)
        self.grab_set()

    def _centre(self, parent):
        try:
            x = parent.winfo_rootx() + (parent.winfo_width() - self.winfo_width()) // 2
            y = parent.winfo_rooty() + (parent.winfo_height() - self.winfo_height()) // 3
            self.geometry(f"+{max(0, x)}+{max(0, y)}")
        except Exception:
            pass

    # ------------------------------------------------------------ from the UI

    def step(self, text=None, fraction=None):
        """
        Updates the display. `fraction` in 0..1 switches the bar to a real
        measurement; leaving it None keeps it sweeping.
        """
        if self._closed:
            return
        if text is not None:
            self.detail.config(text=text)
        if fraction is not None:
            if str(self.bar["mode"]) != "determinate":
                self.bar.stop()
                self.bar.config(mode="determinate", maximum=1000)
            self.bar["value"] = max(0.0, min(1.0, fraction)) * 1000

    def _cancel(self):
        self.cancelled = True
        self.cancel_button.config(state="disabled")
        self.detail.config(text="Stopping...")

    def close(self):
        """
        Always call this, from a finally - a dialog left holding the grab locks
        the whole app with no way back.
        """
        if self._closed:
            return
        self._closed = True
        try:
            self.grab_release()
        except Exception:
            pass
        try:
            self.bar.stop()
        except Exception:
            pass
        self.destroy()
