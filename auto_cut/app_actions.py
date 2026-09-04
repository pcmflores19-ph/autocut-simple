"""
Project handling and transcript editing.

Split out of app.py, which holds the cutting/playback logic. These are the
actions the new pages hang off.
"""

import os
import threading
import tkinter as tk
from tkinter import filedialog, messagebox

import project as project_io
import version
from whisperx_runner import (DEFAULT_MODEL, LANGUAGES, language_label,
                             model_label)


class ActionsMixin:

    # ------------------------------------------------------------- project I/O

    def _set_project_path(self, path):
        self.project_path = path
        name = os.path.basename(path) if path else "Untitled project"
        self.root.title(f"{version.APP_NAME}  -  {name}")
        if hasattr(self, "status_label"):
            self.status_label.config(text=name)

    def new_project(self):
        if not messagebox.askokcancel(
                "New project",
                "Start a new project? Any unsaved edits will be lost."):
            return
        self.player.close()
        self.speaker_paths.clear()
        self.files_list.delete(0, "end")
        self.edits.clear()
        self.mute_edits.clear()
        self.edit_history.clear()
        self.track_chains.clear()
        self.transcript = None
        self.intro_path = None
        self.outro_path = None

        # A new project must look like a fresh start. Leaving the previous
        # episode's transcript, log and effects on screen makes it far too
        # easy to believe they belong to the new one.
        self.per_speaker_words = None
        self.per_speaker_speech = None
        self.v3_path = None
        self.scene_edits = []
        self.scenes = []
        self.scene_switching.set(False)
        self.min_shot_seconds.set(2.0)
        self.max_shot_seconds.set(25.0)
        self._speech_levels = None
        self._speech_hop = None
        self._saved_speech = None
        self.auto_mutes = []
        self.speaker_media = []
        self._pending_project = None
        self.whisper_model.set(DEFAULT_MODEL)
        self.model_box.set(model_label(DEFAULT_MODEL))
        self.aggressiveness.set(50)
        self.auto_mute_on.set(False)
        self.auto_cut_on.set(True)

        self._render_transcript()          # clears the transcript panel
        self._build_mixer()                # drops the old per-track FX buttons
        if hasattr(self, "log_text"):
            self.log_text.delete("1.0", "end")

        self._invalidate_analysis()
        self._set_project_path(None)
        self.log("New project.")

    def save_project(self):
        if not getattr(self, "project_path", None):
            return self.save_project_as()
        try:
            project_io.save(self.project_path, self)
        except Exception as exc:
            messagebox.showerror("Could not save", str(exc))
            return
        self.log(f"Saved {os.path.basename(self.project_path)}")

    def save_project_as(self):
        path = filedialog.asksaveasfilename(
            title="Save project", defaultextension=project_io.PROJECT_EXTENSION,
            filetypes=[("auto_cut project", "*" + project_io.PROJECT_EXTENSION),
                       ("All files", "*.*")])
        if not path:
            return
        try:
            path = project_io.save(path, self)
        except Exception as exc:
            messagebox.showerror("Could not save", str(exc))
            return
        self._set_project_path(path)
        self.log(f"Saved {os.path.basename(path)}")

    def open_project(self):
        path = filedialog.askopenfilename(
            title="Open project",
            filetypes=[("auto_cut project", "*" + project_io.PROJECT_EXTENSION),
                       ("All files", "*.*")])
        if not path:
            return
        try:
            data = project_io.load(path)
        except Exception as exc:
            messagebox.showerror("Could not open", str(exc))
            return

        missing = project_io.missing_media(data)
        if missing:
            replacements = self._prompt_relink(missing)
            if replacements is None:
                return
            data = project_io.relink(data, replacements)

        self._apply_project(data)
        self._set_project_path(path)
        self.log(f"Opened {os.path.basename(path)}")

    def _prompt_relink(self, missing):
        """Media has moved since the project was saved - ask where it went."""
        replacements = {}
        for old in missing:
            if not messagebox.askokcancel(
                    "File moved",
                    f"This file is no longer where the project expects:\n\n{old}\n\n"
                    "Locate it?"):
                return None
            new = filedialog.askopenfilename(
                title=f"Locate {os.path.basename(old)}",
                initialfile=os.path.basename(old))
            if not new:
                return None
            replacements[old] = new
        return replacements

    def _apply_project(self, data):
        self.player.close()
        self.speaker_paths = list(data.get("speaker_paths", []))
        self.files_list.delete(0, "end")
        for path in self.speaker_paths:
            self.files_list.insert("end", os.path.basename(path))

        self.aggressiveness.set(int(data.get("aggressiveness", 50)))
        self.auto_mute_on.set(bool(data.get("auto_mute", False)))
        self.edits = [tuple(e) for e in data.get("edits", [])]
        self.mute_edits = [tuple(e) for e in data.get("mute_edits", [])]
        self.edit_history = []
        self.intro_path = data.get("intro_path")
        self.outro_path = data.get("outro_path")
        self.export_stems.set(bool(data.get("export_stems", False)))
        self.transcript = data.get("transcript")
        # Reused by the next analysis pass instead of re-detecting; dropped if
        # the speaker list no longer matches (see _analyze_worker).
        self._saved_speech = [[tuple(iv) for iv in speech]
                              for speech in data.get("speech", [])] or None
        self.auto_cut_on.set(bool(data.get("auto_cut", True)))

        self.v3_path = data.get("v3_path")
        self.min_shot_seconds.set(float(data.get("min_shot_seconds", 2.0)))
        self.max_shot_seconds.set(float(data.get("max_shot_seconds", 25.0)))
        self.scene_edits = [tuple(e) for e in data.get("scene_edits", [])]
        self.scene_switching.set(bool(data.get("scene_switching", False)))
        self._refresh_vodcast_menu()
        # Word timings come back with the project, so reopening does not spend
        # minutes re-transcribing audio that has not changed.
        self.per_speaker_words = data.get("words") or None

        language = data.get("language")
        if language:
            self.language.set(language)
            self.language_box.set(language_label(language))

        model = data.get("whisper_model")
        if model:
            self.whisper_model.set(model)
            self.model_box.set(model_label(model))

        self._pending_project = data      # chains/tracks restored after analysis
        # Intro/outro moved to the Export menu, which has nowhere to show a
        # filename, so the log is where they are reported now.
        for attr in ("intro", "outro"):
            path = getattr(self, f"{attr}_path", None)
            if path:
                self.log(f"{attr.capitalize()}: {os.path.basename(path)}")

        self._invalidate_analysis()
        self._build_mixer()
        self._render_transcript()
        self.log("Project loaded - rebuilding waveforms and audio from cache...")
        self.root.after(100, self._after_project_open)

    def _restore_project_audio_state(self):
        """
        Applies the saved mixer and VST state once tracks exist. Called at the
        end of analysis, since chains attach to loaded tracks.
        """
        data = getattr(self, "_pending_project", None)
        if not data:
            return
        for i, saved in enumerate(data.get("tracks", [])):
            if i < len(self.player.tracks):
                track = self.player.tracks[i]
                track.gain = float(saved.get("gain", 1.0))
                track.muted = bool(saved.get("muted"))
                track.soloed = bool(saved.get("soloed"))

        chains = data.get("chains", [])
        if chains:
            self.track_chains = [project_io._chain_from_dict(c, log=self.log)
                                 for c in chains]
            for track, chain in zip(self.player.tracks, self.track_chains):
                track.chain = chain
        self._pending_project = None
        self._build_mixer()
        self.log("Restored saved mixer and effects.")

    # ------------------------------------------------------- transcript editor

    def _render_transcript(self):
        """Draws the transcript into the editor, one timestamped line each."""
        if not hasattr(self, "transcript_text"):
            return
        self.transcript_text.delete("1.0", "end")
        segments = (self.transcript or {}).get("segments", [])
        if not segments:
            self.transcript_text.insert("1.0",
                                        "Analyze the recordings to produce a transcript.")
            return
        for segment in segments:
            stamp = self._fmt_time(segment["start"])
            self.transcript_text.insert("end", f"[{stamp}] ", ("stamp",))
            self.transcript_text.insert("end", segment.get("text", "") + chr(10))

    def _on_transcript_click(self, event):
        """Double-clicking a line seeks playback to it."""
        index = self.transcript_text.index(f"@{event.x},{event.y}")
        line = int(index.split(".")[0]) - 1
        segments = (self.transcript or {}).get("segments", [])
        if 0 <= line < len(segments):
            start = segments[line]["start"]
            self.playhead = start
            self.player.seek(start)
            self._draw_waveform()
            self.log(f"Seeked to {self._fmt_time(start)}")

    def apply_transcript_edits(self):
        """
        Reads the editor back into the transcript.

        Timings are matched by line order and never re-derived from the text -
        edits change words, not when they were said.
        """
        segments = (self.transcript or {}).get("segments", [])
        if not segments:
            return
        lines = self.transcript_text.get("1.0", "end").rstrip("\n").split("\n")
        if len(lines) != len(segments):
            messagebox.showwarning(
                "Line count changed",
                f"The editor has {len(lines)} lines but the transcript has "
                f"{len(segments)} segments.\n\nEach line maps to one segment, so "
                "lines can't be added or removed here - edit the words instead.")
            return

        changed = 0
        for segment, line in zip(segments, lines):
            text = line.split("] ", 1)[-1].strip() if line.startswith("[") else line.strip()
            if text != segment.get("text", ""):
                segment["text"] = text
                changed += 1
        self.log(f"Applied {changed} transcript edit(s).")
