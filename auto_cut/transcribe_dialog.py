"""
Asks what to transcribe with, immediately before doing it.

Language and model used to live in the inspector, chosen at some earlier point
and then acted on by a different button - which meant the two most consequential
settings in the app were set far away from the thing they affected, and changing
either silently threw away the analysis. Asking here puts the choice next to the
consequence, and lets the warning about slow models appear at the moment it
matters rather than in a log nobody is reading.
"""

import tkinter as tk
from tkinter import ttk

import ui_theme
import version
from whisperx_runner import (LANGUAGES, MODELS, device, language_label,
                             model_label)


class TranscribeDialog(tk.Toplevel):
    """Modal. Sets `result` to (language_code, model_name), or None."""

    def __init__(self, parent, language, model):
        super().__init__(parent)
        self.title(f"{version.APP_NAME} - Transcribe")
        self.configure(background=ui_theme.BG)
        self.resizable(False, False)
        self.transient(parent)
        self.result = None

        frame = ttk.Frame(self, style="Panel.TFrame")
        frame.pack(fill="both", expand=True, padx=14, pady=12)

        ttk.Label(frame, style="PanelDim.TLabel", justify="left",
                  wraplength=420,
                  text="WhisperX writes the transcript and the subtitles. It "
                       "runs once over every recording, so a long episode "
                       "takes a while."
                  ).pack(anchor="w", pady=(0, 10))

        ttk.Label(frame, text="Language", style="Panel.TLabel").pack(anchor="w")
        self.language_box = ttk.Combobox(
            frame, state="readonly", width=40,
            values=[label for label, _ in LANGUAGES])
        self.language_box.set(language_label(language))
        self.language_box.pack(fill="x", pady=(2, 10))

        ttk.Label(frame, text="Model", style="Panel.TLabel").pack(anchor="w")
        self.model_box = ttk.Combobox(
            frame, state="readonly", width=40,
            values=[label for label, _ in MODELS])
        self.model_box.set(model_label(model))
        self.model_box.pack(fill="x", pady=(2, 4))
        self.model_box.bind("<<ComboboxSelected>>", lambda e: self._advise())

        self.advice = ttk.Label(frame, style="PanelDim.TLabel", justify="left",
                                wraplength=420, text="")
        self.advice.pack(anchor="w", pady=(0, 8))

        buttons = ttk.Frame(frame, style="Panel.TFrame")
        buttons.pack(fill="x", pady=(6, 0))
        ttk.Button(buttons, text="Transcribe", width=14,
                   style="Accent.TButton",
                   command=self._accept).pack(side="right")
        ttk.Button(buttons, text="Cancel", width=10,
                   command=self.destroy).pack(side="right", padx=(0, 6))

        self.bind("<Escape>", lambda e: self.destroy())
        self.bind("<Return>", lambda e: self._accept())
        self._advise()

        self.update_idletasks()
        self._centre(parent)
        self.grab_set()
        self.model_box.focus_set()

    def _centre(self, parent):
        x = parent.winfo_rootx() + (parent.winfo_width() - self.winfo_width()) // 2
        y = parent.winfo_rooty() + (parent.winfo_height() - self.winfo_height()) // 3
        self.geometry(f"+{max(0, x)}+{max(0, y)}")

    def _chosen(self):
        language = next((code for label, code in LANGUAGES
                         if label == self.language_box.get()), None)
        model = next((name for label, name in MODELS
                      if label == self.model_box.get()), None)
        return language, model

    def _advise(self):
        """
        Warns about the combination that wastes the most time.

        A large model on the processor is hours rather than minutes, and the
        only sign of it is that nothing appears to be happening.
        """
        _language, model = self._chosen()
        if model and model.startswith("large") and device() == "cpu":
            self.advice.configure(
                text="This computer has no usable graphics card for WhisperX, "
                     "so a large model will take hours. A smaller one is far "
                     "quicker and usually good enough.")
        else:
            self.advice.configure(text="")

    def _accept(self):
        language, model = self._chosen()
        if not language or not model:
            return
        self.result = (language, model)
        self.destroy()


def ask(parent, language, model):
    """Shows the dialog and returns (language, model), or None if cancelled."""
    dialog = TranscribeDialog(parent, language, model)
    parent.wait_window(dialog)
    return dialog.result
