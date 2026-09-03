#!/usr/bin/env python
"""
Auto-Cut - standalone podcast dead-air remover.

Runs outside DaVinci Resolve: measures where each speaker is talking from
their waveform, finds the stretches where nobody is, and writes an FCPXML
timeline containing only the keepers. Import that into Resolve (any edition)
via File > Import > Timeline.

Transcription is a separate, later step. It is by far the slowest part, and the
edit does not depend on it.

Usage: python app.py
"""

import math
import os
import queue
import sys
import threading
import time
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import ui_theme
import vst_host
from app_actions import ActionsMixin
from app_ui import UIBuilderMixin
from audio_export import decode_audio_file, export_audio
from fcpxml_writer import write_fcpxml
from transcript_export import export_alongside
from fx_dialog import FxDialog
from media_probe import probe
from player import SAMPLE_RATE as PLAYER_SAMPLE_RATE, Player
from silence_detector import (aggressiveness_to_min_gap, apply_mute_edits,
                              compute_auto_mutes_from_intervals,
                              compute_keep_ranges_from_intervals, summarize)
import voice_activity
from waveform import extract_peaks_per_speaker, processed_peaks
from whisperx_runner import transcribe

LANE_HEIGHT = 74             # per-speaker waveform lane
RULER_HEIGHT = 18
MIN_VIEW_SECONDS = 2.0       # deepest zoom
ZOOM_STEP = 1.4

METER_WIDTH = 68             # loudness meter columns either side of the waveform
METER_FLOOR_DB = -60.0       # bottom of the meter scale
METER_DECAY = 0.25           # how fast the bar falls back per UI tick
PEAK_HOLD_TICKS = 18         # how long the peak marker sticks before dropping

# Classic three-zone level meter: green while there's headroom, yellow as it
# gets loud, red where clipping is a real risk.
METER_GREEN_MAX_DB = -12.0
METER_YELLOW_MAX_DB = -3.0
METER_GREEN = "#3fbf6f"
METER_YELLOW = "#e8c341"
METER_RED = "#e0503f"
METER_SCALE_TICKS = (0, -6, -12, -24, -40)

LANE_COLORS = ["#57b9a6", "#c9a227", "#7a9ec2", "#c07ab8", "#9ec27a"]


class AutoCutApp(UIBuilderMixin, ActionsMixin):
    def __init__(self, root):
        self.root = root
        root.title("Auto-Cut - Podcast Dead Air Remover")
        root.geometry("1280x860")
        root.minsize(1024, 700)

        self.speaker_paths = []
        self.speaker_media = []
        self.per_speaker_words = None
        self._saved_speech = None        # speech carried in from an opened project
        self.per_speaker_speech = None   # (start, end) speech, measured from the waveform
        self.timeline_duration = 0.0
        self.peaks_list = []
        self.playhead = None
        self.view_start = 0.0
        self.view_span = 0.0
        self.log_queue = queue.Queue()
        self.player = Player()
        self.track_vars = []
        self.track_chains = []       # one vst_host.TrackChain per speaker
        self.fx_buttons = []
        # Hand edits layered on the automatic cuts, in order - later edits win
        # where they overlap, so you can cut, then restore part of that cut.
        self.edits = []              # [("cut"|"restore", start, end)]
        self.auto_mutes = []         # per lane: [(start, end)] where that speaker is idle
        self.mute_edits = []         # [("mute"|"unmute", lane, start, end)], ordered
        self.edit_history = []       # ("cut"|"restore"|"mute", payload) for undo
        self.selection = None        # (start, end, lane_index)
        self._drag_anchor = None
        self._meters = {}            # meter ballistics state, keyed by track/master
        self._tick_job = None
        self._log_job = None
        self._karaoke_index = None   # transcript line currently highlighted
        self.project_path = None
        self.transcript = None       # {"segments": [...]} once analysed
        self._pending_project = None
        self.framing = None
        self._peaks_job = None       # debounce for processed-waveform refresh
        self._peaks_busy = False
        self._autosave_job = None

        self._build_ui()
        self._update_aggr_label()
        self._set_project_path(None)
        self._render_transcript()
        self._poll_log_queue()
        self._tick()
        self._schedule_autosave()
        self.root.after(400, self.offer_recovery)
        root.bind("<space>", self._on_space)
        self._bind_shortcuts(root)
        root.bind_all("<MouseWheel>", self._on_wheel_anywhere)
        root.protocol("WM_DELETE_WINDOW", self._on_close)

    def _on_wheel_anywhere(self, event):
        """
        Routes the wheel: over the waveform it zooms, anywhere
        else it scrolls the panel under the pointer. Binding only the canvases
        left most of the Edit page dead to the wheel.
        """
        widget = event.widget
        if widget is getattr(self, "canvas", None):
            return self._on_wheel(event)

        target = widget
        while target is not None:
            scroller = getattr(target, "_wheel_scrolls", None)
            if scroller is not None:
                scroller.yview_scroll(-1 if event.delta > 0 else 1, "units")
                return "break"
            target = getattr(target, "master", None)
        return None

    def _bind_shortcuts(self, root):
        """
        Single-key editing, so a pass over an episode doesn't mean travelling
        to the inspector for every cut.
        """
        shortcuts = {
            "q": self.delete_selection,
            "w": self.restore_selection,
            "a": self.mute_selection,
            "s": self.unmute_selection,
            "z": self.undo_edit,
            "x": self.clear_edits,
        }
        for key, action in shortcuts.items():
            for variant in (key, key.upper()):
                root.bind(f"<KeyPress-{variant}>",
                          lambda e, act=action: self._run_shortcut(e, act))

    def _run_shortcut(self, event, action):
        # Never steal a keystroke from a text box - the transcript editor is
        # right there and typing "q" in it must type a q.
        if isinstance(event.widget, (tk.Text, tk.Entry, tk.Listbox)):
            return
        action()
        return "break"

    def _on_space(self, event):
        # Don't hijack the spacebar while a button/slider has focus.
        if isinstance(event.widget, (ttk.Button, ttk.Scale, ttk.Checkbutton)):
            return
        self.toggle_play()
        return "break"

    def _on_close(self):
        # Cancel the repeating callbacks first: destroying the window with them
        # still queued makes Tk complain about invalid command names.
        for attr in ("_tick_job", "_log_job", "_autosave_job", "_peaks_job"):
            job = getattr(self, attr, None)
            if job:
                try:
                    self.root.after_cancel(job)
                except Exception:
                    pass
        try:
            import project as project_io
            project_io.clear_autosave()     # closed cleanly, nothing to recover
        except Exception:
            pass
        try:
            self.player.close()
        finally:
            self.root.destroy()

    # ---------- UI ----------

    def log(self, message):
        self.log_queue.put(message)

    def _poll_log_queue(self):
        latest = None
        while True:
            try:
                message = self.log_queue.get_nowait()
            except queue.Empty:
                break
            self.log_text.insert("end", message + "\n")
            self.log_text.see("end")
            latest = message
        # The log panel lives on the Export page, so mirror the newest line
        # into the status bar - otherwise a long job looks like nothing is
        # happening from any other page.
        if latest:
            self._set_status(latest)
        self._log_job = self.root.after(100, self._poll_log_queue)

    def _set_status(self, message):
        if hasattr(self, "status_label"):
            text = message if len(message) < 110 else message[:107] + '...'
            self.status_label.config(text=text)

    def _start_busy(self, message):
        """Runs a clock beside the progress bar, visible from every page."""
        self._busy_since = time.time()
        self._busy_message = message
        self.progress.start(12)
        self._tick_busy()

    def _tick_busy(self):
        if getattr(self, "_busy_since", None) is None:
            return
        elapsed = int(time.time() - self._busy_since)
        minutes, seconds = divmod(elapsed, 60)
        self.busy_label.config(text=f"{self._busy_message}  {minutes}:{seconds:02d}")
        self._busy_job = self.root.after(500, self._tick_busy)

    def _stop_busy(self):
        self._busy_since = None
        job = getattr(self, "_busy_job", None)
        if job:
            try:
                self.root.after_cancel(job)
            except Exception:
                pass
        self.progress.stop()
        self.busy_label.config(text="")

    # ---------- file list ----------

    def add_files(self):
        paths = filedialog.askopenfilenames(
            title="Select speaker recordings",
            filetypes=[("Media files", "*.mp4 *.mkv *.mov *.avi *.wav *.mp3 *.m4a"),
                       ("All files", "*.*")],
        )
        for path in paths:
            if path not in self.speaker_paths:
                self.speaker_paths.append(path)
                self.files_list.insert("end", os.path.basename(path))
        self._invalidate_analysis()
        self._build_mixer()

    def remove_selected(self):
        selection = self.files_list.curselection()
        for index in reversed(selection):
            self.files_list.delete(index)
            del self.speaker_paths[index]
        self._invalidate_analysis()

    def move_up(self):
        selection = self.files_list.curselection()
        if not selection or selection[0] == 0:
            return
        index = selection[0]
        self._swap_tracks(index - 1, index)
        self.files_list.selection_set(index - 1)

    def _swap_tracks(self, a, b):
        """
        Reorders two speakers, carrying their analysis with them.

        This used to call _invalidate_analysis(), which threw away the
        transcript, waveforms and loaded audio - so re-ordering silently
        undid the whole analysis. Everything keyed by track index moves too.
        """
        def swap(seq):
            if seq is not None and max(a, b) < len(seq):
                seq[a], seq[b] = seq[b], seq[a]

        swap(self.speaker_paths)
        swap(self.speaker_media)
        swap(self.per_speaker_words)
        swap(self.per_speaker_speech)
        swap(self.peaks_list)
        swap(self.auto_mutes)
        swap(self.track_chains)
        swap(self.player.tracks)

        # Lane numbers inside hand edits refer to positions, so they move too.
        remap = {a: b, b: a}
        self.mute_edits = [(kind, remap.get(lane, lane), start, end)
                           for kind, lane, start, end in self.mute_edits]
        self.edit_history = [
            (kind, (remap.get(payload[0], payload[0]),) + tuple(payload[1:]))
            if kind in ("mute", "unmute") else (kind, payload)
            for kind, payload in self.edit_history
        ]

        self.files_list.delete(0, "end")
        for path in self.speaker_paths:
            self.files_list.insert("end", os.path.basename(path))

        for track, chain in zip(self.player.tracks, self.track_chains):
            track.chain = chain

        self._build_mixer()
        self._apply_edits()
        self._draw_waveform()
        self.log("Reordered tracks - analysis kept.")

    def _invalidate_analysis(self):
        self.per_speaker_words = None
        self.peaks_list = []
        self.playhead = None
        self._set_export_enabled(False)
        self.summary_label.config(text="Analyze first to preview cuts.")
        self._draw_waveform()

    # ---------- analysis ----------

    def start_analysis(self):
        if not self.speaker_paths:
            messagebox.showwarning("No files", "Add at least one speaker recording first.")
            return
        self.analyze_button.config(state="disabled", text="Analyzing...")
        self._start_busy("Analyzing")
        threading.Thread(target=self._analyze_worker, daemon=True).start()

    def _analyze_worker(self):
        """
        Finds the cuts from the waveform. No transcription happens here.

        Transcribing every track first made you wait tens of minutes before you
        could see a single cut, and tied the edit to how well WhisperX heard
        Taglish. The waveform already carries everything a dead-air pass needs,
        so the edit is ready in the time it takes to decode the audio. Run the
        transcript afterwards, on the Transcript page, once the edit is settled.
        """
        try:
            media = []
            for path in self.speaker_paths:
                self.log(f"Probing {os.path.basename(path)} ...")
                info = probe(path)
                self.log(f"  {info.width}x{info.height} @ {float(info.fps):.3f}fps, "
                         f"{info.duration_seconds:.1f}s")
                media.append(info)

            duration = max(m.duration_seconds for m in media)

            denoiser = voice_activity.find_denoiser()
            if denoiser:
                self.log("Detecting speech (normalize -> rnnoise -> gate). "
                         "Both are analysis only - your audio is not altered.")
            else:
                self.log("Detecting speech. rnnoise was not found, so the gate "
                         "runs on the raw waveform; expect it to be less exact "
                         "on a noisy room.")

            saved = getattr(self, "_saved_speech", None)
            if saved and len(saved) == len(self.speaker_paths):
                self.log("  reusing the speech detected when this project was "
                         "saved (the recordings have not changed)")
                speech_per_speaker = saved
            else:
                speech_per_speaker = [
                    voice_activity.speaking_intervals(path, denoiser,
                                                      duration=duration,
                                                      log=self.log)
                    for path in self.speaker_paths
                ]
            self._saved_speech = None

            self.log("Reading waveforms ...")
            peaks_list = extract_peaks_per_speaker(self.speaker_paths, duration)

            self.log("Preparing audio for playback ...")
            self.player.load(self.speaker_paths)
            self._pending_auto_mutes = [
                compute_auto_mutes_from_intervals(speech, 0.0, duration)
                for speech in speech_per_speaker
            ]

            self.speaker_media = media
            self.per_speaker_speech = speech_per_speaker
            self.timeline_duration = duration
            self.peaks_list = peaks_list
            self.auto_mutes = self._pending_auto_mutes
            self.playhead = None
            self.view_start = 0.0
            self.view_span = duration
            self.log("Analysis complete. Transcribe on the Transcript page "
                     "when you are happy with the edit.")
            self.root.after(0, self._analysis_done)
        except Exception as exc:
            self.log(f"ERROR: {exc}")
            self.root.after(0, lambda: self._analysis_failed(exc))

    # ---------- transcription (separate from the edit) ----------

    def start_transcription(self):
        """
        Transcribes every track. Runs on its own, after the edit.

        Kept apart from analysis on purpose: the cuts come from the waveform and
        are ready in seconds, while this is the slow part. Doing it afterwards
        also means it only runs once, on an edit you have already settled.
        """
        if not self.speaker_paths:
            messagebox.showwarning("No files", "Add at least one speaker recording first.")
            return
        self.analyze_button.config(state="disabled", text="Transcribing...")
        self._start_busy("Transcribing")
        threading.Thread(target=self._transcribe_worker, daemon=True).start()

    def _transcribe_worker(self):
        try:
            # Ollama and WhisperX both want the GPU, and on a 6GB card an 8B
            # model parked in VRAM leaves nothing for large-v2.
            try:
                import ollama_client
                ollama_client.free_vram(log=self.log)
            except Exception:
                pass

            language = self.language.get()
            words_per_speaker = []
            all_segments = []
            for index, path in enumerate(self.speaker_paths):
                data = transcribe(path, language=language, progress=self.log)
                words = data["words"]
                self.log(f"  {len(words)} words, {len(data['segments'])} segments")
                words_per_speaker.append(words)
                # Tag each segment with who said it - the transcript is a
                # deliverable, and "who spoke" is most of its value.
                speaker = os.path.splitext(os.path.basename(path))[0]
                for segment in data["segments"]:
                    entry = dict(segment)
                    entry["speaker"] = speaker
                    entry["track"] = index
                    all_segments.append(entry)
            all_segments.sort(key=lambda s: s["start"])

            self.per_speaker_words = words_per_speaker
            self.transcript = {"language": language, "segments": all_segments}
            self.log("Transcription complete.")
            self.root.after(0, self._transcription_done)
        except Exception as exc:
            self.log(f"ERROR: {exc}")
            self.root.after(0, lambda: self._transcription_failed(exc))

    def _transcription_done(self):
        self._stop_busy()
        self.analyze_button.config(state="normal", text="Analyze")
        self._render_transcript()

    def _transcription_failed(self, exc):
        self._stop_busy()
        self.analyze_button.config(state="normal", text="Analyze")
        messagebox.showerror("Transcription failed", str(exc))

    def _analysis_done(self):
        self._stop_busy()
        self.analyze_button.config(state="normal", text="Analyze")
        # The edit is already usable; transcription runs on from here by itself
        # so the transcript is ready without having to remember to start it.
        # Skipped if words came back with a
        # saved project - re-running would cost minutes and change nothing.
        if not self.per_speaker_words:
            self.root.after(200, self.start_transcription)
        self._set_export_enabled(True)
        # Grow the canvas to fit one lane per speaker.
        lane_total = RULER_HEIGHT + len(self.peaks_list) * LANE_HEIGHT
        self.canvas.config(height=lane_total)
        self.track_meters.config(height=lane_total)
        self.master_meter.config(height=lane_total)
        self._build_mixer()
        self._restore_project_audio_state()
        self._render_transcript()
        self._update_summary()

    def _analysis_failed(self, exc):
        self._stop_busy()
        self.analyze_button.config(state="normal", text="Analyze")
        messagebox.showerror("Analysis failed", str(exc))

    # ---------- preview + export ----------

    def _on_language_change(self, label):
        from whisperx_runner import LANGUAGES
        for text, value in LANGUAGES:
            if text == label:
                if value != self.language.get():
                    self.language.set(value)
                    self.log(f"Language set to {text} - re-run Analyze to "
                             "transcribe in that language.")
                    self._invalidate_analysis()
                break

    def _after_project_open(self):
        """
        Re-runs analysis on open. Transcripts, waveform peaks and decoded audio
        are all cached by file content, so this is quick - and without it an
        opened project looks empty until you notice you have to press Analyze.
        """
        if self.speaker_paths:
            self.start_analysis()

    def _on_slider(self, _value):
        self._update_aggr_label()
        if self.per_speaker_speech:
            self._update_summary()

    def _update_aggr_label(self):
        value = int(self.aggressiveness.get())
        gap = aggressiveness_to_min_gap(value)
        self.aggr_label.config(text=f"{value}/100   ->   cuts silence over {gap:.2f}s")
        self.aggr_detail.config(
            text=f"Any gap where nobody speaks for longer than {gap:.2f} seconds "
                 "is removed.")

    def _current_keep_ranges(self):
        if not self.per_speaker_speech:
            return [], []
        if not self.auto_cut_on.get():
            # Dead-air removal switched off: keep the whole timeline, but still
            # honour hand edits, so Delete/Restore keep working on their own.
            from silence_detector import apply_edits, complement_ranges
            keep = apply_edits([(0.0, self.timeline_duration)], self.edits)
            return keep, complement_ranges(keep, 0.0, self.timeline_duration)
        return compute_keep_ranges_from_intervals(
            self.per_speaker_speech, 0.0, self.timeline_duration,
            int(self.aggressiveness.get()), edits=self.edits,
        )

    def _update_summary(self):
        keep_ranges, gaps = self._current_keep_ranges()
        stats = summarize(gaps, keep_ranges)
        removed = stats["seconds_removed"]
        self.summary_label.config(
            text=(f"{stats['num_cuts']} cuts  |  {removed:.1f}s removed "
                  f"({removed / 60:.1f} min)  |  {stats['num_keep_segments']} segments kept  "
                  f"|  final length ~{(self.timeline_duration - removed) / 60:.1f} min")
        )
        # Keep playback in step with the current cut settings.
        self.player.set_keep_ranges(keep_ranges)
        self._draw_waveform(gaps)

    # ---------- waveform + audio preview ----------

    def _view_bounds(self):
        """Visible time window, clamped to the timeline."""
        span = min(self.view_span, self.timeline_duration)
        span = max(span, MIN_VIEW_SECONDS)
        start = max(0.0, min(self.view_start, self.timeline_duration - span))
        return start, span

    def _time_to_x(self, t, width, start, span):
        return (t - start) / span * width

    @staticmethod
    def _fmt_time(seconds):
        m, s = divmod(int(seconds), 60)
        return f"{m}:{s:02d}"

    def _draw_waveform(self, gaps=None):
        self.canvas.delete("all")
        width = self.canvas.winfo_width()
        if width <= 1:
            return

        if not self.peaks_list or not self.per_speaker_speech:
            self.canvas.create_text(width / 2, (LANE_HEIGHT + RULER_HEIGHT) / 2,
                                    fill="#666", text="Waveform appears after analysis")
            return

        start, span = self._view_bounds()
        if gaps is None:
            _, gaps = self._current_keep_ranges()
        # Computed once per redraw - auto-mute can produce hundreds of regions.
        self._drawn_mutes = self.effective_mutes()

        n_lanes = len(self.peaks_list)
        lanes_bottom = RULER_HEIGHT + n_lanes * LANE_HEIGHT

        # Shade removed stretches across every lane.
        for gap_start, gap_end in gaps:
            if gap_end < start or gap_start > start + span:
                continue
            x0 = self._time_to_x(gap_start, width, start, span)
            x1 = self._time_to_x(gap_end, width, start, span)
            self.canvas.create_rectangle(x0, RULER_HEIGHT, max(x1, x0 + 1), lanes_bottom,
                                         fill="#5a1f1f", outline="")

        # Explicitly restored stretches - marked so a deliberate "uncut" is
        # distinguishable from audio that was simply never cut.
        for kind, r_start, r_end in self.edits:
            if kind != "restore" or r_end < start or r_start > start + span:
                continue
            rx0 = self._time_to_x(r_start, width, start, span)
            rx1 = self._time_to_x(r_end, width, start, span)
            self.canvas.create_rectangle(rx0, lanes_bottom - 3, max(rx1, rx0 + 1),
                                         lanes_bottom, fill="#3f7d4f", outline="")

        # Time ruler.
        self.canvas.create_rectangle(0, 0, width, RULER_HEIGHT, fill="#141414", outline="")
        for i in range(7):
            t = start + span * i / 6
            x = self._time_to_x(t, width, start, span)
            anchor = "w" if i == 0 else ("e" if i == 6 else "center")
            self.canvas.create_text(min(max(x, 2), width - 2), RULER_HEIGHT / 2,
                                    text=self._fmt_time(t), fill="#999",
                                    anchor=anchor, font=("TkDefaultFont", 7))
            if 0 < i < 6:
                self.canvas.create_line(x, RULER_HEIGHT, x, lanes_bottom, fill="#2c2c2c")

        # One lane per speaker.
        for lane_i, peaks in enumerate(self.peaks_list):
            top = RULER_HEIGHT + lane_i * LANE_HEIGHT
            mid = top + LANE_HEIGHT / 2
            color = LANE_COLORS[lane_i % len(LANE_COLORS)]
            if lane_i:
                self.canvas.create_line(0, top, width, top, fill="#333")

            n = len(peaks)
            per_second = n / self.timeline_duration
            for x in range(int(width)):
                t0 = start + (x / width) * span
                t1 = start + ((x + 1) / width) * span
                lo = max(0, int(t0 * per_second))
                hi = min(n, max(lo + 1, int(t1 * per_second)))
                if lo >= n:
                    continue
                amp = float(peaks[lo:hi].max())
                h = amp * (LANE_HEIGHT / 2 - 3)
                self.canvas.create_line(x, mid - h, x, mid + h, fill=color)

            # Hand-muted regions on this speaker's lane.
            for lane, m_start, m_end in self._drawn_mutes:
                if lane != lane_i or m_end < start or m_start > start + span:
                    continue
                mx0 = self._time_to_x(m_start, width, start, span)
                mx1 = self._time_to_x(m_end, width, start, span)
                self.canvas.create_rectangle(mx0, top + 1, max(mx1, mx0 + 1),
                                             top + LANE_HEIGHT - 1,
                                             fill="#3a3a52", outline="#6a6a92", stipple="gray50")

            label = self.audio_track_name(lane_i)
            self.canvas.create_text(6, top + 8, text=label, fill=color, anchor="w",
                                    font=("TkDefaultFont", 7, "bold"))

        # Current drag selection, drawn over everything.
        if self.selection:
            sel_start, sel_end, sel_lane = self.selection
            sx0 = self._time_to_x(sel_start, width, start, span)
            sx1 = self._time_to_x(sel_end, width, start, span)
            top = RULER_HEIGHT + sel_lane * LANE_HEIGHT
            self.canvas.create_rectangle(sx0, top, max(sx1, sx0 + 1), top + LANE_HEIGHT,
                                         outline="#8ab4f8", width=2,
                                         fill="#2a3a52", stipple="gray25")
            for x in (sx0, sx1):
                self.canvas.create_line(x, RULER_HEIGHT, x, lanes_bottom, fill="#8ab4f8")

        if self.playhead is not None and start <= self.playhead <= start + span:
            x = self._time_to_x(self.playhead, width, start, span)
            self.canvas.create_line(x, RULER_HEIGHT, x, lanes_bottom, fill="#ffcc44", width=2)

        self._sync_scrollbar(start, span)
        self.zoom_label.config(
            text=f"showing {self._fmt_time(start)}-{self._fmt_time(start + span)} "
                 f"of {self._fmt_time(self.timeline_duration)}")

    def _sync_scrollbar(self, start, span):
        if self.timeline_duration <= 0:
            return
        self.hscroll.set(start / self.timeline_duration,
                         (start + span) / self.timeline_duration)

    def _on_scroll(self, *args):
        if not self.peaks_list:
            return
        _, span = self._view_bounds()
        if args[0] == "moveto":
            self.view_start = float(args[1]) * self.timeline_duration
        elif args[0] == "scroll":
            amount, unit = float(args[1]), args[2]
            step = span * (0.1 if unit == "units" else 0.9)
            self.view_start += amount * step
        self._draw_waveform()

    def _zoom(self, factor, focus_time=None):
        if not self.peaks_list:
            return
        start, span = self._view_bounds()
        if focus_time is None:
            focus_time = start + span / 2
        new_span = max(MIN_VIEW_SECONDS, min(self.timeline_duration, span * factor))
        # Keep the focus point under the cursor fixed while zooming.
        rel = (focus_time - start) / span if span else 0.5
        self.view_span = new_span
        self.view_start = focus_time - rel * new_span
        self._draw_waveform()

    def _zoom_fit(self):
        self.view_start = 0.0
        self.view_span = self.timeline_duration
        self._draw_waveform()

    def _on_wheel(self, event):
        # Zooms the waveform under the cursor.
        if not self.peaks_list:
            return "break"
        width = max(self.canvas.winfo_width(), 1)
        start, span = self._view_bounds()
        focus = start + (event.x / width) * span
        self._zoom(1 / ZOOM_STEP if event.delta > 0 else ZOOM_STEP, focus)
        return "break"

    def _x_to_time(self, x):
        width = max(self.canvas.winfo_width(), 1)
        start, span = self._view_bounds()
        return max(0.0, min(self.timeline_duration, start + (x / width) * span))

    def _y_to_lane(self, y):
        if y < RULER_HEIGHT:
            return None
        lane = int((y - RULER_HEIGHT) // LANE_HEIGHT)
        return lane if 0 <= lane < len(self.peaks_list) else None

    def _on_press(self, event):
        if not self.peaks_list or not self.per_speaker_speech:
            return
        # Shift-drag pans. The scrollbar thumb gets tiny when zoomed right in,
        # which made panning fiddly.
        if event.state & 0x0001:
            self._pan_anchor = (event.x, self.view_start)
            return
        lane = self._y_to_lane(event.y)
        if lane is None:
            return
        self._drag_anchor = (event.x, self._x_to_time(event.x), lane)

    def _on_drag(self, event):
        pan = getattr(self, "_pan_anchor", None)
        if pan is not None:
            width = max(self.canvas.winfo_width(), 1)
            _, span = self._view_bounds()
            self.view_start = pan[1] - (event.x - pan[0]) / width * span
            self._draw_waveform()
            return
        if self._drag_anchor is None:
            return
        anchor_x, anchor_t, lane = self._drag_anchor
        if abs(event.x - anchor_x) < 3:
            return
        t = self._x_to_time(event.x)
        self.selection = (min(anchor_t, t), max(anchor_t, t), lane)
        self._draw_waveform()
        self._update_edit_labels()

    def _on_release(self, event):
        if getattr(self, "_pan_anchor", None) is not None:
            self._pan_anchor = None
            return
        if self._drag_anchor is None:
            return
        anchor_x, anchor_t, _lane = self._drag_anchor
        self._drag_anchor = None
        # A click (no meaningful drag) seeks instead of selecting.
        if abs(event.x - anchor_x) < 3:
            self.selection = None
            self.playhead = anchor_t
            self.player.seek(anchor_t)
            self._draw_waveform()
            self._update_edit_labels()

    # ---------- hand edits ----------

    def delete_selection(self):
        if not self.selection:
            return
        start, end, _lane = self.selection
        self.edits.append(("cut", start, end))
        self.edit_history.append(("cut", (start, end)))
        self.log(f"Deleted {self._fmt_time(start)}-{self._fmt_time(end)} "
                 f"({end - start:.1f}s)")
        self.selection = None
        self._apply_edits()

    def restore_selection(self):
        """Forces a stretch back into the timeline, overriding automatic cuts."""
        if not self.selection:
            return
        start, end, _lane = self.selection
        self.edits.append(("restore", start, end))
        self.edit_history.append(("restore", (start, end)))
        self.log(f"Restored {self._fmt_time(start)}-{self._fmt_time(end)} "
                 f"({end - start:.1f}s)")
        self.selection = None
        self._apply_edits()

    def _lane_name(self, lane):
        if lane < len(self.player.tracks):
            return self.player.tracks[lane].name
        return f"lane {lane}"

    def mute_selection(self):
        self._add_mute_edit("mute", "Muted")

    def unmute_selection(self):
        """Brings a stretch of one speaker's track back - undoes an auto-mute."""
        self._add_mute_edit("unmute", "Unmuted")

    def _add_mute_edit(self, kind, verb):
        if not self.selection:
            return
        start, end, lane = self.selection
        self.mute_edits.append((kind, lane, start, end))
        self.edit_history.append((kind, (lane, start, end)))
        self.log(f"{verb} {self._lane_name(lane)} {self._fmt_time(start)}-"
                 f"{self._fmt_time(end)} ({end - start:.1f}s)")
        self.selection = None
        self._apply_edits()

    def effective_mutes(self):
        """
        Flattens auto-mutes + hand edits into [(lane, start, end)], which is what
        playback, drawing and export all consume.
        """
        out = []
        for lane in range(len(self.peaks_list)):
            base = (self.auto_mutes[lane]
                    if self.auto_mute_on.get() and lane < len(self.auto_mutes) else [])
            edits = [(k, s, e) for k, l, s, e in self.mute_edits if l == lane]
            for start, end in apply_mute_edits(base, edits):
                out.append((lane, start, end))
        return out

    def _recompute_auto_mutes(self):
        if not self.per_speaker_speech:
            self.auto_mutes = []
            return
        self.auto_mutes = [
            compute_auto_mutes_from_intervals(speech, 0.0, self.timeline_duration)
            for speech in self.per_speaker_speech
        ]

    def _on_auto_cut_toggle(self):
        state = "on" if self.auto_cut_on.get() else "off"
        self.log(f"Dead-air auto-cut: {state}.")
        self._update_summary()

    def _on_auto_mute_toggle(self):
        state = "on" if self.auto_mute_on.get() else "off"
        self.log(f"Auto-mute inactive speaker: {state}.")
        self._apply_edits()

    def undo_edit(self):
        if not self.edit_history:
            return
        kind, payload = self.edit_history.pop()
        if kind in ("mute", "unmute"):
            lane, start, end = payload
            entry = (kind, lane, start, end)
            for i in range(len(self.mute_edits) - 1, -1, -1):
                if self.mute_edits[i] == entry:
                    del self.mute_edits[i]
                    break
        else:
            entry = (kind,) + payload
            # Drop the most recent matching edit, keeping edit order intact.
            for i in range(len(self.edits) - 1, -1, -1):
                if self.edits[i] == entry:
                    del self.edits[i]
                    break
        self.log(f"Undid last {kind}.")
        self._apply_edits()

    def clear_edits(self):
        self.edits.clear()
        self.mute_edits.clear()
        self.edit_history.clear()
        self.selection = None
        self.log("Cleared all hand edits.")
        self._apply_edits()

    def _apply_edits(self):
        """Push mutes to the player and recompute cuts after any hand edit."""
        mutes = self.effective_mutes()
        for i, track in enumerate(self.player.tracks):
            track.mute_ranges = sorted((s, e) for lane, s, e in mutes if lane == i)
        self._update_summary()
        self._update_edit_labels()

    def _update_edit_labels(self):
        if self.selection:
            start, end, lane = self.selection
            name = (self.player.tracks[lane].name
                    if lane < len(self.player.tracks) else f"lane {lane}")
            self.selection_label.config(
                text=f"Selected {self._fmt_time(start)}-{self._fmt_time(end)} "
                     f"({end - start:.1f}s) on {name}")
            state = "normal"
        else:
            self.selection_label.config(text="No selection - drag across a lane to select.")
            state = "disabled"
        self.delete_button.config(state=state)
        self.restore_button.config(state=state)
        self.mute_button.config(state=state)
        self.unmute_button.config(state=state)

        n_cuts = sum(1 for k, _, _ in self.edits if k == "cut")
        n_restores = sum(1 for k, _, _ in self.edits if k == "restore")
        self.edits_label.config(
            text=f"{n_cuts} cut(s), {n_restores} restore(s), "
                 f"{len(self.effective_mutes())} muted region(s)")

    # ---------- transport ----------

    def toggle_play(self, _event=None):
        if not self.player.tracks:
            return
        self.player.toggle()
        self._refresh_transport()

    def stop_audio(self):
        self.player.stop()
        self.playhead = self.player.position
        self._refresh_transport()
        self._draw_waveform()

    def _skip(self, seconds):
        if not self.player.tracks:
            return
        self.player.skip(seconds)
        self.playhead = self.player.position
        self._draw_waveform()

    def _go_start(self):
        self.player.seek(0.0)
        self.playhead = 0.0
        self._draw_waveform()

    def _go_end(self):
        self.player.seek(max(0.0, self.player.duration - 5.0))
        self.playhead = self.player.position
        self._draw_waveform()

    def _on_mode_change(self):
        self.player.edited_mode = bool(self.edited_mode.get())
        self.player.seek(self.player.position)   # resync into a valid segment

    def _refresh_transport(self):
        self.play_button.config(text="Pause" if self.player.is_playing else "Play")

    def _tick(self):
        """Follows the playhead while audio is rolling."""
        if self.player.tracks:
            self._refresh_meters()
            pos = self.player.position
            self.time_label.config(
                text=f"{self._fmt_time(pos)} / {self._fmt_time(self.player.duration)}")
            if self.player.is_playing:
                self.playhead = pos
                self._autoscroll(pos)
                self._draw_waveform()
                self._update_karaoke(pos)
            elif self.play_button.cget("text") == "Pause":
                self._refresh_transport()      # stream ended on its own
        self._tick_job = self.root.after(60, self._tick)

    # ---------- loudness meters ----------

    @staticmethod
    def _to_db(level):
        if level <= 1e-7:
            return METER_FLOOR_DB
        return max(METER_FLOOR_DB, 20.0 * math.log10(level))

    @staticmethod
    def _db_to_fraction(db):
        """Maps dBFS onto 0..1 of the meter's height."""
        return max(0.0, min(1.0, (db - METER_FLOOR_DB) / (0.0 - METER_FLOOR_DB)))

    @staticmethod
    def _level_color(db):
        if db > METER_YELLOW_MAX_DB:
            return METER_RED
        if db > METER_GREEN_MAX_DB:
            return METER_YELLOW
        return METER_GREEN

    def _meter_state(self, key):
        return self._meters.setdefault(key, {"bar": METER_FLOOR_DB,
                                             "peak": METER_FLOOR_DB,
                                             "hold": 0})

    def _update_meter_state(self, key, rms, peak):
        """Applies fall-back ballistics and peak-hold to one meter."""
        state = self._meter_state(key)
        rms_db = self._to_db(rms)
        peak_db = self._to_db(peak)

        # Bar rises instantly, falls gradually - standard meter behaviour.
        if rms_db >= state["bar"]:
            state["bar"] = rms_db
        else:
            state["bar"] += (rms_db - state["bar"]) * METER_DECAY

        if peak_db >= state["peak"]:
            state["peak"] = peak_db
            state["hold"] = PEAK_HOLD_TICKS
        elif state["hold"] > 0:
            state["hold"] -= 1
        else:
            state["peak"] += (peak_db - state["peak"]) * METER_DECAY
        return state

    def _draw_meter(self, canvas, slots, scale=False):
        """
        slots: [(label, top_y, height, state)] - one vertical meter each.
        Bars are drawn in green/yellow/red zones; the number under each bar is
        the held peak in dBFS.
        """
        canvas.delete("all")
        width = int(canvas.winfo_width()) or METER_WIDTH

        for label, top, height, state in slots:
            bar_top = top + 15
            bar_bottom = top + height - 17
            bar_height = max(1, bar_bottom - bar_top)
            x0 = 6
            x1 = width - (26 if scale else 8)

            canvas.create_text(width / 2, top + 8, text=label, fill="#bbb",
                               font=("TkDefaultFont", 7, "bold"))
            canvas.create_rectangle(x0, bar_top, x1, bar_bottom,
                                    fill="#0a0a0a", outline="#3a3a3a")

            def y_for(db):
                return bar_bottom - self._db_to_fraction(db) * bar_height

            # Fill in zones, each clipped to how far the level actually reached.
            level_db = state["bar"]
            zones = [(METER_FLOOR_DB, METER_GREEN_MAX_DB, METER_GREEN),
                     (METER_GREEN_MAX_DB, METER_YELLOW_MAX_DB, METER_YELLOW),
                     (METER_YELLOW_MAX_DB, 0.0, METER_RED)]
            for zone_lo, zone_hi, color in zones:
                if level_db <= zone_lo:
                    break
                top_db = min(level_db, zone_hi)
                y_hi, y_lo = y_for(top_db), y_for(zone_lo)
                if y_lo - y_hi >= 1:
                    canvas.create_rectangle(x0 + 1, y_hi, x1 - 1, y_lo,
                                            fill=color, outline="")

            # Zone boundaries, so you can read where you are at a glance.
            for db in (METER_GREEN_MAX_DB, METER_YELLOW_MAX_DB):
                canvas.create_line(x0, y_for(db), x1, y_for(db), fill="#555")

            if state["peak"] > METER_FLOOR_DB:
                peak_y = y_for(state["peak"])
                canvas.create_line(x0, peak_y, x1, peak_y,
                                   fill=self._level_color(state["peak"]), width=2)

            reading = ("-inf" if state["peak"] <= METER_FLOOR_DB
                       else f"{state['peak']:.1f}")
            canvas.create_text(width / 2, bar_bottom + 9, text=reading,
                               fill=self._level_color(state["peak"]),
                               font=("TkDefaultFont", 8, "bold"))

            if scale:
                for db in METER_SCALE_TICKS:
                    y = y_for(db)
                    canvas.create_line(x1, y, x1 + 3, y, fill="#666")
                    canvas.create_text(x1 + 5, y, text=f"{db}", fill="#888",
                                       anchor="w", font=("TkDefaultFont", 6))

    def _refresh_meters(self):
        if not self.player.tracks:
            return
        height = RULER_HEIGHT + len(self.peaks_list) * LANE_HEIGHT

        # Per-track meters, each aligned with its waveform lane.
        slots = []
        for i, track in enumerate(self.player.tracks):
            state = self._update_meter_state(f"t{i}", track.rms_level, track.peak_level)
            slots.append((f"A{i + 1}", RULER_HEIGHT + i * LANE_HEIGHT,
                          LANE_HEIGHT, state))
        if int(self.track_meters.cget("height")) != height:
            self.track_meters.config(height=height)
        self._draw_meter(self.track_meters, slots)

        # Master meter spans the full lane stack.
        master = self._update_meter_state("master", self.player.master_rms,
                                          self.player.master_peak)
        if int(self.master_meter.cget("height")) != height:
            self.master_meter.config(height=height)
        self._draw_meter(self.master_meter,
                         [("MASTER", RULER_HEIGHT, height - RULER_HEIGHT, master)],
                         scale=True)

    # ---------- waveform follows the effects ----------

    def refresh_waveform_for_chains(self, delay_ms=400):
        """
        Redraws the waveform through the current VST chains.

        Debounced: a chain edit can arrive on every knob turn while a plugin
        editor is open, and re-processing an hour of audio on each one would be
        pointless. The last change within the window wins.
        """
        if self._peaks_job is not None:
            try:
                self.root.after_cancel(self._peaks_job)
            except Exception:
                pass
        self._peaks_job = self.root.after(delay_ms, self._start_peaks_refresh)

    def _start_peaks_refresh(self):
        self._peaks_job = None
        if self._peaks_busy or not self.speaker_paths or not self.timeline_duration:
            return
        if self.player is not None and self.player.is_playing:
            # Redrawing loads a private copy of each plugin, and a plugin load
            # cannot overlap audio processing - the audio thread would have to
            # wait for it and you would hear the gap. Monitoring is the more
            # useful of the two while a knob is being turned, so let playback
            # own the plugins and pick the redraw up once it stops.
            self._peaks_job = self.root.after(500, self._start_peaks_refresh)
            return
        self._peaks_busy = True
        threading.Thread(target=self._peaks_worker, daemon=True).start()

    def _peaks_worker(self):
        try:
            updated = []
            for index, path in enumerate(self.speaker_paths):
                chain = (self.track_chains[index]
                         if index < len(self.track_chains) else None)
                updated.append(processed_peaks(path, chain, self.timeline_duration))
            self.root.after(0, lambda: self._peaks_refreshed(updated))
        except Exception as exc:
            self.log(f"Could not redraw the waveform through the effects: {exc}")
            self.root.after(0, lambda: setattr(self, "_peaks_busy", False))

    def _peaks_refreshed(self, peaks_list):
        self._peaks_busy = False
        if len(peaks_list) != len(self.speaker_paths):
            return
        self.peaks_list = peaks_list
        self._draw_waveform()
        active = sum(1 for chain in self.track_chains if chain.active_slots())
        self.log("Waveform redrawn through "
                 + (f"{active} active effect chain(s)." if active
                    else "the unprocessed audio."))

    # ---------- autosave ----------

    def _schedule_autosave(self):
        """
        Periodic snapshot. It has to be periodic rather than on-exit: a native
        crash - a VST taking the process down, say - runs no Python cleanup, so
        there is no hook to save from.
        """
        import project as project_io

        try:
            if self.speaker_paths:
                project_io.autosave(self)
        except Exception as exc:
            self.log(f"Autosave failed: {exc}")
        self._autosave_job = self.root.after(
            project_io.AUTOSAVE_SECONDS * 1000, self._schedule_autosave)

    def offer_recovery(self):
        """On startup, offer back anything a previous run left behind."""
        import project as project_io

        data = project_io.pending_recovery()
        if not data:
            return
        when = data.get("autosaved_project") or "an unsaved session"
        if not messagebox.askyesno(
                "Recover unsaved work",
                f"Auto-Cut didn't shut down cleanly last time.\n\n"
                f"There's a recovered session from {os.path.basename(str(when))}.\n\n"
                "Restore it?"):
            project_io.clear_autosave()
            return
        try:
            self._apply_project(data)
            self.log("Recovered the session from the last run.")
        except Exception as exc:
            messagebox.showerror("Could not recover", str(exc))






    def speaker_stem(self, index):
        if index >= len(self.speaker_paths):
            return f"track {index + 1}"
        return os.path.splitext(os.path.basename(self.speaker_paths[index]))[0]


    def audio_track_name(self, index):
        """
        Audio tracks are A1, A2... - the same convention as Resolve.

        These used to be labelled with the source filename, which for this
        podcast is "V1_paul"/"V2_michael", so the audio lanes read like video
        tracks and the whole stack looked wrong.
        """
        return f"A{index + 1}  {self.speaker_stem(index)[:14]}"







    # ---------- karaoke transcript ----------

    def _update_karaoke(self, position):
        """Highlights the line being spoken and scrolls it into view."""
        segments = (self.transcript or {}).get("segments", [])
        if not segments:
            return
        index = None
        for i, segment in enumerate(segments):
            if segment["start"] <= position < segment["end"]:
                index = i
                break
        if index is None or index == self._karaoke_index:
            return

        self._karaoke_index = index
        text = self.transcript_text
        text.tag_remove("current", "1.0", "end")
        line = index + 1
        text.tag_add("current", f"{line}.0", f"{line}.end")
        text.see(f"{line}.0")

    def _autoscroll(self, pos):
        """Keeps the playhead in view when zoomed in."""
        start, span = self._view_bounds()
        if span >= self.timeline_duration:
            return
        if pos < start or pos > start + span * 0.95:
            self.view_start = pos - span * 0.25

    # ---------- mixer ----------

    def _build_mixer(self):
        for child in self.mixer_frame.winfo_children():
            child.destroy()
        self.track_vars = []
        self.fx_buttons = []

        # Rows are built from the file list, not from loaded audio, so effects
        # can be set up before (or without) running Analyze.
        names = [os.path.splitext(os.path.basename(p))[0] for p in self.speaker_paths]
        while len(self.track_chains) < len(names):
            self.track_chains.append(vst_host.TrackChain())
        for track, chain in zip(self.player.tracks, self.track_chains):
            track.chain = chain

        if not names:
            ttk.Label(self.mixer_frame, text="Add recordings to see tracks.",
                      style="PanelDim.TLabel").pack(anchor="w")
            return

        for i, name in enumerate(names):
            row = ttk.Frame(self.mixer_frame, style="Panel.TFrame")
            row.pack(fill="x", pady=(4, 0))

            colour = LANE_COLORS[i % len(LANE_COLORS)]
            head = ttk.Frame(row, style="Panel.TFrame")
            head.pack(fill="x")
            # Colour chip matching this speaker's waveform lane and meter.
            tk.Frame(head, background=colour, width=10, height=10).pack(
                side="left", padx=(0, 6))
            ttk.Label(head, text=f"A{i + 1}  {name[:14]}",
                      style="Panel.TLabel").pack(side="left")

            track = self.player.tracks[i] if i < len(self.player.tracks) else None
            vol = tk.DoubleVar(value=(track.gain * 100.0) if track else 100.0)
            muted = tk.BooleanVar(value=bool(track.muted) if track else False)
            soloed = tk.BooleanVar(value=bool(track.soloed) if track else False)
            self.track_vars.append((vol, muted, soloed))

            fx_button = ttk.Button(head, width=9)
            fx_button.config(command=lambda idx=i, b=fx_button: self.open_fx(idx, b))
            fx_button.pack(side="right")
            self.fx_buttons.append(fx_button)

            ttk.Checkbutton(head, text="S", width=3, variable=soloed,
                            style="Panel.TCheckbutton",
                            command=lambda idx=i, v=soloed: self._set_track(idx, soloed=v.get())
                            ).pack(side="right", padx=1)
            ttk.Checkbutton(head, text="M", width=3, variable=muted,
                            style="Panel.TCheckbutton",
                            command=lambda idx=i, v=muted: self._set_track(idx, muted=v.get())
                            ).pack(side="right", padx=1)

            fader = ttk.Frame(row, style="Panel.TFrame")
            fader.pack(fill="x")
            value_label = ttk.Label(fader, text="100%", width=5,
                                    style="PanelDim.TLabel")

            def on_vol(_v, idx=i, var=vol, lbl=value_label):
                lbl.config(text=f"{int(var.get())}%")
                self._set_track(idx, gain=var.get() / 100.0)

            # 0-300%: quiet remote guests often need well over unity.
            ttk.Scale(fader, from_=0, to=300, orient="horizontal", variable=vol,
                      command=on_vol).pack(side="left", fill="x", expand=True)
            value_label.pack(side="left", padx=(4, 0))
            value_label.config(text=f"{int(vol.get())}%")

            self._refresh_fx_button(i)

    def _set_track(self, index, gain=None, muted=None, soloed=None):
        """Mixer changes only apply once audio is loaded; before that they're
        remembered in the widgets and picked up when tracks appear."""
        if index >= len(self.player.tracks):
            return
        track = self.player.tracks[index]
        if gain is not None:
            track.gain = gain
        if muted is not None:
            track.muted = muted
        if soloed is not None:
            track.soloed = soloed

    def _refresh_fx_button(self, index):
        if index >= len(self.fx_buttons):
            return
        chain = self.track_chains[index]
        n = len(chain.slots)
        # Same shape whatever the state, so the tracks read consistently.
        label = f"FX ({n})"
        if n and not chain.enabled:
            label += " off"
        self.fx_buttons[index].config(text=label)

    def open_fx(self, index, _button=None):
        if not vst_host.is_available():
            messagebox.showwarning(
                "pedalboard not installed",
                "VST3 hosting needs the 'pedalboard' package:\n\n"
                "    pip install pedalboard")
            return
        if index >= len(self.player.tracks):
            return
        name = self.player.tracks[index].name

        def on_change():
            self._refresh_fx_button(index)
            self.log(f"{name} chain: {self.track_chains[index].describe()}")
            # Keep the drawn waveform honest about what the chain is doing.
            self.refresh_waveform_for_chains()

        FxDialog(self.root, name, self.track_chains[index],
                 on_change=on_change, log=self.log, player=self.player)

    def _choose_bookend(self, which):
        path = filedialog.askopenfilename(
            title=f"Choose {which} audio",
            filetypes=[("Audio/video", "*.wav *.mp3 *.m4a *.aac *.flac *.ogg *.mp4 *.mov"),
                       ("All files", "*.*")],
        )
        if not path:
            return
        try:
            seconds = len(decode_audio_file(path)) / PLAYER_SAMPLE_RATE
        except Exception as exc:
            messagebox.showerror("Could not read file", str(exc))
            return
        setattr(self, f"{which}_path", path)
        # A menu entry cannot show what is currently chosen, so the log is the
        # only place this is visible now.
        self.log(f"{which.capitalize()}: {os.path.basename(path)} ({seconds:.1f}s)")

    def _clear_bookend(self, which):
        setattr(self, f"{which}_path", None)
        self.log(f"{which.capitalize()} cleared.")

    def export_audio_file(self):
        """Renders the finished audio - the whole deliverable for an audio podcast."""
        keep_ranges, _ = self._current_keep_ranges()
        if not keep_ranges:
            messagebox.showwarning("Nothing to export",
                                   "No audio survived the current settings.")
            return

        default_name = os.path.splitext(os.path.basename(self.speaker_paths[0]))[0] + "_edit.wav"
        path = filedialog.asksaveasfilename(
            title="Save finished audio", defaultextension=".wav",
            initialfile=default_name,
            filetypes=[("WAV audio", "*.wav"), ("All files", "*.*")],
        )
        if not path:
            return

        # Rendering runs a full episode through the plugins in one pass, and
        # pedalboard holds the GIL for its duration - playback would break up
        # underneath it. Stop transport first so the two never overlap.
        self.player.stop()

        self._set_export_enabled(False)
        self._start_busy("Rendering audio")
        threading.Thread(target=self._export_audio_worker,
                         args=(path, keep_ranges), daemon=True).start()

    def _export_audio_worker(self, path, keep_ranges):
        try:
            gains = [t.gain for t in self.player.tracks]
            written, peak = export_audio(
                path, self.speaker_paths, keep_ranges,
                mutes=self.effective_mutes(), chains=self.track_chains,
                gains=gains, stems=self.export_stems.get(),
                intro_path=self.intro_path, outro_path=self.outro_path,
                progress=self.log,
            )
            written += self._write_transcript_files(path, keep_ranges)
            total = sum(e - s for s, e in keep_ranges)
            self.log(f"Exported {total / 60:.1f} min of audio to {len(written)} file(s).")
            self.root.after(0, lambda: self._export_audio_done(written, peak))
        except Exception as exc:
            self.log(f"ERROR exporting audio: {exc}")
            self.root.after(0, lambda: self._export_audio_failed(exc))

    def _export_audio_done(self, written, peak):
        self._stop_busy()
        self._set_export_enabled(True)
        note = ("\n\nThe mix peaked above full scale and was scaled down "
                f"({peak:.2f}x) to avoid clipping." if peak > 1.0 else "")
        messagebox.showinfo("Audio exported",
                            "Wrote:\n" + "\n".join(written) + note)

    def _export_audio_failed(self, exc):
        self.progress.stop()
        self._set_export_enabled(True)
        messagebox.showerror("Export failed", str(exc))

    def export_fcpxml(self):
        keep_ranges, _ = self._current_keep_ranges()
        if not keep_ranges:
            messagebox.showwarning("Nothing to export",
                                   "No segments survived the current settings.")
            return

        default_name = (os.path.splitext(os.path.basename(self.speaker_paths[0]))[0]
                        + "_autocut.fcpxml")
        path = filedialog.asksaveasfilename(
            title="Save FCPXML timeline", defaultextension=".fcpxml",
            initialfile=default_name,
            filetypes=[("FCPXML timeline", "*.fcpxml"), ("All files", "*.*")],
        )
        if not path:
            return

        self.player.stop()          # see export_audio_file: baking holds the GIL

        self._set_export_enabled(False)
        self._start_busy("Exporting timeline")
        threading.Thread(target=self._export_fcpxml_worker,
                         args=(path, keep_ranges), daemon=True).start()

    def _export_fcpxml_worker(self, path, keep_ranges):
        try:
            media = self.speaker_media
            mutes = self.effective_mutes()

            write_fcpxml(path, media, keep_ranges, mutes=mutes)
            self.log(f"Wrote {os.path.basename(path)}")

            extra = self._write_transcript_files(path, keep_ranges)
            self.root.after(0, lambda: self._export_fcpxml_done(path, extra))
        except Exception as exc:
            self.log(f"ERROR writing FCPXML: {exc}")
            self.root.after(0, lambda: self._export_failed(exc))

    def _export_fcpxml_done(self, path, extra):
        self._stop_busy()
        self._set_export_enabled(True)
        note = ("\n\nTranscript written:\n" + "\n".join(os.path.basename(p)
                                                        for p in extra)) if extra else ""
        messagebox.showinfo(
            "Exported",
            f"Saved:\n{path}\n\nIn DaVinci Resolve:\n"
            "File > Import > Timeline > Import AAF, EDL, XML..." + note)

    def _export_failed(self, exc):
        self._stop_busy()
        self._set_export_enabled(True)
        messagebox.showerror("Export failed", str(exc))

    def _write_transcript_files(self, export_path, keep_ranges):
        """
        Writes the transcript next to whatever was exported, timed to the cut
        edit rather than the raw recording.
        """
        if not self.export_transcript.get():
            return []
        segments = (self.transcript or {}).get("segments", [])
        if not segments:
            return []
        written = export_alongside(export_path, segments, keep_ranges)
        for path in written:
            self.log(f"Wrote {os.path.basename(path)}")
        return written


CRASH_LOG = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                         "autocut_crash.log")


def _start_crash_log():
    """
    Keeps a record of native crashes, which are the ones that actually happen
    here: a VST misbehaving inside pedalboard kills the interpreter outright,
    no Python traceback and no chance for try/except. Until now that output
    died with the console window and there was nothing left to diagnose.

    faulthandler writes the C-level stack of every thread straight to this
    file, so the offending plugin and the thread it was called from survive
    the crash. Returns the open handle, which must stay open for the life of
    the process.
    """
    try:
        handle = open(CRASH_LOG, "a", encoding="utf-8")
    except OSError:
        return None
    stamp = time.strftime("%Y-%m-%d %H:%M:%S")
    handle.write(chr(10) + "===== autocut started " + stamp + " =====" + chr(10))
    handle.flush()
    import faulthandler
    faulthandler.enable(file=handle, all_threads=True)
    return handle


def _check_ffmpeg():
    """
    ffmpeg and ffprobe do all the decoding. Without them nothing works, and the
    failure used to surface as a bare FileNotFoundError deep inside a worker
    thread - useless to someone who has just downloaded this.
    """
    import shutil
    missing = [tool for tool in ("ffmpeg", "ffprobe") if not shutil.which(tool)]
    if not missing:
        return True
    messagebox.showerror(
        "ffmpeg is required",
        f"Could not find {' and '.join(missing)} on your PATH." + chr(10) * 2 +
        "Auto-Cut uses ffmpeg to read and write audio, so it cannot run "
        "without it." + chr(10) * 2 +
        "Windows:  winget install Gyan.FFmpeg" + chr(10) +
        "macOS:    brew install ffmpeg" + chr(10) +
        "Linux:    sudo apt install ffmpeg" + chr(10) * 2 +
        "Then reopen a terminal so the new PATH takes effect.")
    return False


def main():
    log_handle = _start_crash_log()

    root = tk.Tk()
    root.withdraw()
    if not _check_ffmpeg():
        return
    root.deiconify()
    AutoCutApp(root)
    try:
        root.mainloop()
    except BaseException:
        # A Python-level crash: record it too, then re-raise so the exit code
        # and console output are unchanged.
        if log_handle:
            import traceback
            traceback.print_exc(file=log_handle)
            log_handle.flush()
        raise


if __name__ == "__main__":
    main()
