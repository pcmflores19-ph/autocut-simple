"""
File > Settings. Currently just where WhisperX lives.

Worth a dialog rather than an environment variable because the thing it fixes
is invisible otherwise: a machine can have two WhisperX installations, one of
which cannot use the GPU, and picking the wrong one turns eight minutes of
transcription into several hours with no error to explain it.
"""

import os
import threading
import tkinter as tk
from tkinter import filedialog, ttk

import settings
import ui_theme
import whisperx_runner


class SettingsDialog(tk.Toplevel):
    def __init__(self, parent, log=None):
        super().__init__(parent)
        self.log = log
        self.title("Auto-Cut - Settings")
        self.configure(background=ui_theme.BG)
        self.geometry("720x300")
        self.minsize(600, 260)
        self.transient(parent)

        frame = ttk.Frame(self, style="Panel.TFrame")
        frame.pack(fill="both", expand=True, padx=12, pady=12)

        ttk.Label(frame, text="TRANSCRIPTION",
                  style="PanelDim.TLabel").pack(anchor="w")
        ttk.Label(frame, style="PanelDim.TLabel", justify="left",
                  wraplength=660,
                  text="Auto-Cut finds WhisperX by itself in the usual places. "
                       "If you installed it into its own environment - which is "
                       "the sensible way to do it, and is never on the PATH - "
                       "point at it here.").pack(anchor="w", pady=(2, 10))

        ttk.Label(frame, text="WhisperX program:",
                  style="Panel.TLabel").pack(anchor="w")
        row = ttk.Frame(frame, style="Panel.TFrame")
        row.pack(fill="x", pady=(2, 6))
        self.path_var = tk.StringVar(value=settings.get("whisperx_path") or "")
        entry = ttk.Entry(row, textvariable=self.path_var)
        entry.pack(side="left", fill="x", expand=True)
        ttk.Button(row, text="Browse...", width=11,
                   command=self._browse).pack(side="left", padx=(6, 0))
        ttk.Button(row, text="Find it for me", width=15,
                   command=self._autodetect).pack(side="left", padx=(4, 0))

        ttk.Label(frame, style="PanelDim.TLabel",
                  text="Leave blank to search automatically.").pack(anchor="w")

        self.status = ttk.Label(frame, style="PanelDim.TLabel", justify="left",
                                wraplength=660, text="")
        self.status.pack(anchor="w", pady=(10, 0))

        buttons = ttk.Frame(frame, style="Panel.TFrame")
        buttons.pack(side="bottom", fill="x", pady=(12, 0))
        ttk.Button(buttons, text="Save", width=12, style="Accent.TButton",
                   command=self._save).pack(side="right")
        ttk.Button(buttons, text="Cancel", width=12,
                   command=self.destroy).pack(side="right", padx=(0, 6))
        ttk.Button(buttons, text="Test", width=12,
                   command=self._test).pack(side="left")

        self.bind("<Escape>", lambda e: self.destroy())
        self._describe_current()

    # ---------------------------------------------------------------- helpers

    def _describe_current(self):
        def work():
            try:
                exe, cuda = whisperx_runner.resolve(force=True)
            except Exception as exc:
                self._set_status(f"WhisperX not found. {exc}".split("\n")[0])
                return
            where = "your saved setting" if settings.get("whisperx_path") \
                else "automatic search"
            self._set_status(
                f"Using ({where}):\n{exe}\n\n"
                + ("This one can use your graphics card - transcription will "
                   "be fast." if cuda else
                   "This one runs on the processor only, which is slow for a "
                   "long recording. If you have an NVIDIA card, a different "
                   "install may be able to use it."))
        threading.Thread(target=work, daemon=True).start()

    def _set_status(self, text):
        self.after(0, lambda: self.status.config(text=text))

    def _browse(self):
        initial = os.path.dirname(self.path_var.get()) or os.path.expanduser("~")
        path = filedialog.askopenfilename(
            parent=self, title="Where is whisperx?", initialdir=initial,
            filetypes=[("WhisperX program", "whisperx.exe whisperx"),
                       ("All files", "*.*")])
        if path:
            self.path_var.set(path)

    def _autodetect(self):
        """
        A real search, not the quick one done at startup.

        Startup only looks in a handful of obvious places, because walking the
        disk on every launch would be rude. Here the user has asked, so a
        bounded walk of the likely roots is fair.
        """
        self._set_status("Searching...")

        def work():
            exe = "whisperx.exe" if os.name == "nt" else "whisperx"
            home = os.path.expanduser("~")
            roots = [os.path.join(home, d) for d in
                     ("Documents", "Desktop", "Downloads", "AppData", "miniconda3",
                      "anaconda3", "scoop", "source", "dev", "projects")]
            roots.append(home)
            found = []
            for root in roots:
                if not os.path.isdir(root):
                    continue
                base_depth = root.rstrip(os.sep).count(os.sep)
                for folder, dirs, files in os.walk(root):
                    if folder.count(os.sep) - base_depth > 6:
                        dirs[:] = []
                        continue
                    dirs[:] = [d for d in dirs
                               if not d.startswith(".") and d.lower() not in
                               ("node_modules", "__pycache__", "cache", "temp")]
                    if exe in files:
                        found.append(os.path.join(folder, exe))
                if found:
                    break

            if not found:
                self._set_status("No WhisperX found. Install it, or use "
                                 "Browse if you know where it is.")
                return

            # Prefer one that can actually use the GPU.
            best, best_cuda = found[0], False
            for path in found:
                if whisperx_runner._probe(path):
                    best, best_cuda = path, True
                    break
            self.after(0, lambda: self.path_var.set(best))
            others = f"\n\n({len(found)} found, picked the one that can use "
            self._set_status(
                f"Found:\n{best}\n\n"
                + ("It can use your graphics card." if best_cuda
                   else "It runs on the processor only.")
                + (others + "the GPU.)" if best_cuda and len(found) > 1 else ""))
        threading.Thread(target=work, daemon=True).start()

    def _test(self):
        path = self.path_var.get().strip()
        if not path:
            self._describe_current()
            return
        if not os.path.exists(path):
            self._set_status("That file does not exist.")
            return
        self._set_status("Checking...")

        def work():
            cuda = whisperx_runner._probe(path)
            if cuda is None:
                self._set_status(
                    "Found the program, but could not tell whether it can use "
                    "the GPU. It will still work; it may just be slow.")
            elif cuda:
                self._set_status("Works, and can use your graphics card.")
            else:
                self._set_status(
                    "Works, but runs on the processor only - slow for a long "
                    "recording.")
        threading.Thread(target=work, daemon=True).start()

    def _save(self):
        path = self.path_var.get().strip()
        settings.set_value("whisperx_path", path)
        # Force the next transcription to re-resolve rather than reuse whatever
        # was decided at startup.
        whisperx_runner._resolved = None
        whisperx_runner._device_cache = None
        if self.log:
            try:
                exe, cuda = whisperx_runner.resolve(force=True)
                self.log(f"WhisperX: {exe} ({'GPU' if cuda else 'CPU'})")
            except Exception as exc:
                self.log(f"WhisperX: {exc}".split("\n")[0])
        self.destroy()
