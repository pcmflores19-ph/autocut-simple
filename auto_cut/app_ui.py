"""
UI construction for the editor, kept apart from the editing logic in app.py.

Laid out like DaVinci Resolve, because that is where the exported timeline
ends up: transcript and inspector above, the timeline filling the width
beneath them. There is only one page - exporting is a menu, not somewhere you
navigate to.
"""

import tkinter as tk
from tkinter import messagebox, ttk

import help_text
import links
import ui_theme
import version
from whisperx_runner import (DEFAULT_LANGUAGE, DEFAULT_MODEL, LANGUAGES,
                             MODELS, language_label, model_label)

LANE_HEIGHT = 74
RULER_HEIGHT = 18
METER_WIDTH = 68
HSCROLL_HEIGHT = 18        # fixed height for the timeline scrollbar
INSPECTOR_WIDTH = 340


class UIBuilderMixin:
    """Builds every widget. Expects the host class to provide the callbacks."""

    # ------------------------------------------------------------------ shell

    def _build_ui(self):
        ui_theme.apply(self.root)
        self.root.configure(background=ui_theme.BG)

        self._build_menu()

        # One page. Editing is the whole app; exporting is a menu, not a place
        # you navigate to.
        self.page_container = ttk.Frame(self.root)
        self.page_container.pack(fill="both", expand=True)
        self._build_edit_page(self.page_container)

        self._build_status_bar()

    def _build_menu(self):
        menubar = tk.Menu(self.root, background=ui_theme.PANEL,
                          foreground=ui_theme.TEXT, borderwidth=0)

        file_menu = tk.Menu(menubar, tearoff=0, background=ui_theme.PANEL,
                            foreground=ui_theme.TEXT,
                            activebackground=ui_theme.SELECT)
        file_menu.add_command(label="New project", command=self.new_project,
                              accelerator="Ctrl+N")
        file_menu.add_command(label="Open project...", command=self.open_project,
                              accelerator="Ctrl+O")
        file_menu.add_separator()
        file_menu.add_command(label="Save project", command=self.save_project,
                              accelerator="Ctrl+S")
        file_menu.add_command(label="Save project as...",
                              command=self.save_project_as)
        file_menu.add_separator()
        file_menu.add_command(label="Settings...", command=self.open_settings)
        file_menu.add_separator()
        file_menu.add_command(label="Quit", command=self._on_close)
        menubar.add_cascade(label="File", menu=file_menu)
        self._build_export_menu(menubar)
        self._build_help_menu(menubar)
        self._build_support_menu(menubar)

        self.root.config(menu=menubar)
        self.root.bind("<Control-s>", lambda e: self.save_project())
        self.root.bind("<Control-o>", lambda e: self.open_project())
        self.root.bind("<Control-n>", lambda e: self.new_project())

    def _labelled_combo(self, parent, label, values, initial, on_change):
        """A caption and a read-only dropdown on their own row."""
        row = ttk.Frame(parent, style="Panel.TFrame")
        row.pack(fill="x", padx=8, pady=(4, 0))
        ttk.Label(row, text=label, width=9,
                  style="PanelDim.TLabel").pack(side="left")
        box = ttk.Combobox(row, state="readonly", height=24, values=values)
        box.set(initial)
        box.bind("<<ComboboxSelected>>", lambda e: on_change(box.get()))
        box.pack(side="left", fill="x", expand=True)
        return box

    def open_settings(self):
        from settings_dialog import SettingsDialog
        SettingsDialog(self.root, log=self.log)

    def _build_help_menu(self, menubar):
        """
        Help matters more than usual here: an installed copy has no README
        beside it, so for anyone who did not clone the repository this menu is
        the only documentation there is.
        """
        menu = tk.Menu(menubar, tearoff=0, background=ui_theme.PANEL,
                       foreground=ui_theme.TEXT,
                       activebackground=ui_theme.SELECT)
        menu.add_command(label="Quick start",
                         command=lambda: self._show_help(
                             "Quick start", help_text.QUICK_START))
        menu.add_command(label="Keyboard shortcuts", accelerator="F1",
                         command=lambda: self._show_help(
                             "Keyboard shortcuts", help_text.SHORTCUTS))
        menu.add_command(label="Troubleshooting",
                         command=lambda: self._show_help(
                             "Troubleshooting", help_text.TROUBLESHOOTING))
        menu.add_separator()
        menu.add_command(label="Check for updates...",
                         command=self.check_for_updates)
        menu.add_command(label="Project page (opens your browser)",
                         command=self._open_project_page)
        menu.add_separator()
        menu.add_command(label=f"About {version.APP_NAME}",
                         command=lambda: self._show_help(
                             f"About {version.APP_NAME}", help_text.ABOUT))
        menubar.add_cascade(label="Help", menu=menu)

        self.root.bind("<F1>", lambda e: self._show_help(
            "Keyboard shortcuts", help_text.SHORTCUTS))

    def _show_help(self, title, body):
        """A read-only, scrollable, resizable text window."""
        window = tk.Toplevel(self.root)
        window.title(f"{version.APP_NAME} - {title}")
        window.configure(background=ui_theme.BG)
        window.geometry("760x620")
        window.transient(self.root)

        frame = ttk.Frame(window, style="Panel.TFrame")
        frame.pack(fill="both", expand=True, padx=10, pady=10)
        scroll = ttk.Scrollbar(frame, orient="vertical")
        scroll.pack(side="right", fill="y")
        text = tk.Text(frame, wrap="word", yscrollcommand=scroll.set,
                       padx=12, pady=10, **ui_theme.text_options())
        text.pack(side="left", fill="both", expand=True)
        scroll.config(command=text.yview)

        text.insert("1.0", body)
        # Read-only, but still selectable and copyable - disabling the widget
        # outright would stop people copying an error message out of it.
        text.configure(state="disabled")

        ttk.Button(window, text="Close", width=12,
                   command=window.destroy).pack(pady=(0, 10))
        window.bind("<Escape>", lambda e: window.destroy())
        text.focus_set()

    def _open_url(self, url):
        import webbrowser
        webbrowser.open(url)

    def _open_project_page(self):
        self._open_url(version.PROJECT_URL)

    def _open_support_link(self, title, url):
        """
        Opens a Support link, or explains itself if it was never filled in.

        Sending someone to example.com is worse than saying nothing, so an
        unedited placeholder says what it is instead.
        """
        if links.is_placeholder(url):
            messagebox.showinfo(
                title,
                f"This link has not been set up yet." + chr(10) * 2 +
                f"Whoever built this copy needs to put the real {title} "
                f"address into auto_cut/links.py.")
            return
        self._open_url(url)

    def _build_support_menu(self, menubar):
        """Where people can find, and support, the podcast behind the app."""
        menu = tk.Menu(menubar, tearoff=0, background=ui_theme.PANEL,
                       foreground=ui_theme.TEXT,
                       activebackground=ui_theme.SELECT)
        for label, url in links.SUPPORT_MENU:
            if label is None:
                menu.add_separator()
                continue
            menu.add_command(
                label=label,
                command=lambda t=label, u=url: self._open_support_link(t, u))
        # Added last, so it sits to the right of the working menus. Windows
        # will not push it flush against the right edge: MFT_RIGHTJUSTIFY is a
        # legacy flag that themed menu bars no longer honour - setting it
        # succeeds, and the item then stops being drawn at all.
        menubar.add_cascade(label=f"Support {links.PODCAST_NAME}", menu=menu)
    def _build_status_bar(self):
        bar = ttk.Frame(self.root, style="Panel.TFrame")
        bar.pack(side="bottom", fill="x")
        self.status_label = ttk.Label(bar, text="No project", style="PanelDim.TLabel")
        self.status_label.pack(side="left", padx=10, pady=3)
        # Progress and an elapsed clock sit on the right, visible from every
        # page - a long job must never look like nothing is happening.
        self.progress = ttk.Progressbar(bar, mode="indeterminate", length=200)
        self.progress.pack(side="right", padx=10, pady=3)
        self.busy_label = ttk.Label(bar, text="", style="Value.TLabel",
                                    background=ui_theme.PANEL)
        self.busy_label.pack(side="right", padx=4)

    # -------------------------------------------------------------- edit page

    def _build_edit_page(self, parent):
        # A paned window so the timeline can be dragged as large as needed -
        # previously the waveform was squeezed to 92px with no way to grow it.
        # The timeline's scrollbar and zoom controls live OUTSIDE the paned
        # window, pinned to the bottom of the page. Inside it they competed for
        # space with the transcript and camera strip, and dragging the sash down
        # clipped them away entirely. ttk.PanedWindow panes have no minsize, so
        # keeping them out of the pane is the only way to guarantee they stay.
        self.timeline_footer = ttk.Frame(parent, style="Panel.TFrame")
        self.timeline_footer.pack(side="bottom", fill="x", padx=6, pady=(0, 6))

        pane = ttk.PanedWindow(parent, orient="vertical")
        pane.pack(fill="both", expand=True)

        upper = ttk.Frame(pane)
        pane.add(upper, weight=3)
        lower = ttk.Frame(pane)
        pane.add(lower, weight=2)

        self._build_inspector(upper)

        left = ttk.Frame(upper)
        left.pack(side="left", fill="both", expand=True)

        # Transcript, beside the audio rather than on another page.
        transcript = ttk.Frame(left, style="Panel.TFrame")
        transcript.pack(fill="both", expand=True, padx=(6, 3), pady=(0, 6))
        header = ttk.Frame(transcript, style="Panel.TFrame")
        header.pack(fill="x", padx=8, pady=(6, 2))
        ttk.Label(header, text="TRANSCRIPT", style="PanelDim.TLabel").pack(side="left")
        ttk.Label(header, style="PanelDim.TLabel",
                  text="   follows playback - double-click a line to seek"
                  ).pack(side="left")
        ttk.Button(header, text="Save text changes", width=17,
                   command=self.apply_transcript_edits).pack(side="right")
        ttk.Label(header, style="PanelDim.TLabel",
                  text="edits here are only kept once saved  ").pack(side="right")

        body = ttk.Frame(transcript, style="Panel.TFrame")
        body.pack(fill="both", expand=True, padx=8, pady=(0, 8))
        scroll = ttk.Scrollbar(body, orient="vertical")
        scroll.pack(side="right", fill="y")
        self.transcript_text = tk.Text(body, wrap="word", undo=True, height=6,
                                       yscrollcommand=scroll.set,
                                       **ui_theme.text_options())
        self.transcript_text.pack(side="left", fill="both", expand=True)
        scroll.config(command=self.transcript_text.yview)
        self.transcript_text.tag_configure("stamp", foreground=ui_theme.ACCENT)
        self.transcript_text.tag_configure("current", background=ui_theme.SELECT,
                                           foreground="#ffffff")
        self.transcript_text.bind("<Double-Button-1>", self._on_transcript_click)

        # The log used to live on the export page. With that page gone it has
        # to be here: every long job - analysis, transcription, rendering -
        # reports through it, and without it the app looks frozen while it
        # works. Fixed height, so it never steals room from the transcript.
        log_frame = ttk.Frame(left, style="Panel.TFrame")
        log_frame.pack(fill="x", padx=(6, 3), pady=(0, 6))
        ttk.Label(log_frame, text="LOG", style="PanelDim.TLabel").pack(
            anchor="w", padx=8, pady=(6, 2))
        log_body = ttk.Frame(log_frame, style="Panel.TFrame")
        log_body.pack(fill="both", expand=True, padx=8, pady=(0, 8))
        log_scroll = ttk.Scrollbar(log_body, orient="vertical")
        log_scroll.pack(side="right", fill="y")
        self.log_text = tk.Text(log_body, height=6, wrap="word",
                                yscrollcommand=log_scroll.set,
                                **ui_theme.text_options())
        self.log_text.pack(side="left", fill="both", expand=True)
        log_scroll.config(command=self.log_text.yview)

        self._build_timeline(lower)

    def _scrollable(self, parent, width=None):
        """
        A vertically scrolling panel. The inspector outgrew its fixed height and
        silently clipped the mixer - FX buttons included - so anything that can
        overflow lives in one of these now.
        """
        outer = ttk.Frame(parent, style="Panel.TFrame")
        if width:
            outer.configure(width=width)
            outer.pack_propagate(False)

        canvas = tk.Canvas(outer, background=ui_theme.PANEL, highlightthickness=0)
        bar = ttk.Scrollbar(outer, orient="vertical", command=canvas.yview)
        canvas.configure(yscrollcommand=bar.set)
        bar.pack(side="right", fill="y")
        canvas.pack(side="left", fill="both", expand=True)

        inner = ttk.Frame(canvas, style="Panel.TFrame")
        window = canvas.create_window((0, 0), window=inner, anchor="nw")
        inner.bind("<Configure>",
                   lambda e: canvas.configure(scrollregion=canvas.bbox("all")))
        canvas.bind("<Configure>",
                    lambda e: canvas.itemconfig(window, width=e.width))
        # Tagged so the window-wide wheel handler can find the right scroller
        # from whatever widget the pointer happens to be over.
        for widget in (outer, canvas, inner):
            widget._wheel_scrolls = canvas
        return outer, inner

    def _build_inspector(self, parent):
        outer, inspector = self._scrollable(parent, width=INSPECTOR_WIDTH)
        outer.pack(side="right", fill="y", padx=(3, 6), pady=6)

        # --- media
        ttk.Label(inspector, text="MEDIA", style="PanelDim.TLabel").pack(
            anchor="w", padx=8, pady=(8, 2))
        row = ttk.Frame(inspector, style="Panel.TFrame")
        row.pack(fill="x", padx=8)
        self.files_list = tk.Listbox(row, height=3, **ui_theme.listbox_options())
        self.files_list.pack(side="left", fill="both", expand=True)
        buttons = ttk.Frame(row, style="Panel.TFrame")
        buttons.pack(side="right", padx=(4, 0))
        ttk.Button(buttons, text="Add...", width=8,
                   command=self.add_files).pack(fill="x", pady=1)
        ttk.Button(buttons, text="Remove", width=8,
                   command=self.remove_selected).pack(fill="x", pady=1)
        ttk.Button(buttons, text="Up", width=8,
                   command=self.move_up).pack(fill="x", pady=1)

        analyze = ttk.Frame(inspector, style="Panel.TFrame")
        analyze.pack(fill="x", padx=8, pady=(6, 0))
        self.analyze_button = ttk.Button(analyze, text="Analyze", width=11,
                                         style="Accent.TButton",
                                         command=self.start_analysis)
        self.analyze_button.pack(side="left")

        # Language and model get a row each rather than sharing the button's.
        # The inspector is 340px and these dropdowns are wide; crowding three
        # widgets onto one line is how the last label ended up clipped.
        # Both are chosen BEFORE Analyze, because analysis runs the
        # transcription straight after finding the cuts.
        self.language = tk.StringVar(value=DEFAULT_LANGUAGE)
        self.language_box = self._labelled_combo(
            inspector, "Language", [label for label, _ in LANGUAGES],
            language_label(DEFAULT_LANGUAGE),
            lambda value: self._on_language_change(value))

        self.whisper_model = tk.StringVar(value=DEFAULT_MODEL)
        self.model_box = self._labelled_combo(
            inspector, "Model", [label for label, _ in MODELS],
            model_label(DEFAULT_MODEL),
            lambda value: self._on_model_change(value))

        # wraplength, like every other hint in this panel - without it the text
        # is silently clipped at the edge of the inspector rather than wrapping.
        self.analyze_hint = ttk.Label(inspector, style="PanelDim.TLabel",
                                      justify="left",
                                      wraplength=INSPECTOR_WIDTH - 40)
        self.analyze_hint.pack(anchor="w", padx=8, pady=(2, 0))
        self._update_analyze_hint()

        ttk.Separator(inspector).pack(fill="x", padx=8, pady=8)

        # --- cutting
        ttk.Label(inspector, text="DEAD AIR", style="PanelDim.TLabel").pack(
            anchor="w", padx=8)
        self.aggressiveness = tk.IntVar(value=50)
        self.slider = ttk.Scale(inspector, from_=0, to=100, orient="horizontal",
                                variable=self.aggressiveness,
                                command=self._on_slider)
        self.slider.pack(fill="x", padx=8, pady=(2, 0))
        self.aggr_label = ttk.Label(inspector, text="", style="Value.TLabel",
                                    background=ui_theme.PANEL)
        self.aggr_label.pack(anchor="w", padx=8)
        self.aggr_detail = ttk.Label(inspector, text="", style="PanelDim.TLabel",
                                     wraplength=INSPECTOR_WIDTH - 40,
                                     justify="left")
        self.aggr_detail.pack(anchor="w", padx=8)
        self.summary_label = ttk.Label(inspector, text="Analyze to preview cuts.",
                                       style="PanelDim.TLabel",
                                       wraplength=INSPECTOR_WIDTH - 40,
                                       justify="left")
        self.summary_label.pack(anchor="w", padx=8, pady=(2, 6))

        self.auto_cut_on = tk.BooleanVar(value=True)
        ttk.Checkbutton(inspector, text="Auto-cut dead air",
                        style="Panel.TCheckbutton", variable=self.auto_cut_on,
                        command=self._on_auto_cut_toggle).pack(anchor="w", padx=8)

        self.auto_mute_on = tk.BooleanVar(value=False)
        ttk.Checkbutton(inspector, text="Auto-mute inactive speaker",
                        style="Panel.TCheckbutton", variable=self.auto_mute_on,
                        command=self._on_auto_mute_toggle).pack(anchor="w", padx=8)

        ttk.Separator(inspector).pack(fill="x", padx=8, pady=8)

        # --- selection tools
        ttk.Label(inspector, text="SELECTION", style="PanelDim.TLabel").pack(
            anchor="w", padx=8)
        self.selection_label = ttk.Label(inspector, text="Drag across a lane.",
                                         style="PanelDim.TLabel",
                                         wraplength=INSPECTOR_WIDTH - 40,
                                         justify="left")
        self.selection_label.pack(anchor="w", padx=8, pady=(0, 4))

        grid = ttk.Frame(inspector, style="Panel.TFrame")
        grid.pack(fill="x", padx=8)
        self.delete_button = ttk.Button(grid, text="Delete (q)", width=15,
                                        state="disabled",
                                        command=self.delete_selection)
        self.delete_button.grid(row=0, column=0, padx=1, pady=1)
        self.restore_button = ttk.Button(grid, text="Restore (w)", width=15,
                                         state="disabled",
                                         command=self.restore_selection)
        self.restore_button.grid(row=0, column=1, padx=1, pady=1)
        self.mute_button = ttk.Button(grid, text="Mute lane (a)", width=15,
                                      state="disabled",
                                      command=self.mute_selection)
        self.mute_button.grid(row=1, column=0, padx=1, pady=1)
        self.unmute_button = ttk.Button(grid, text="Unmute lane (s)", width=15,
                                        state="disabled",
                                        command=self.unmute_selection)
        self.unmute_button.grid(row=1, column=1, padx=1, pady=1)

        undo_row = ttk.Frame(inspector, style="Panel.TFrame")
        undo_row.pack(fill="x", padx=8, pady=(4, 0))
        ttk.Button(undo_row, text="Undo (z)", width=15,
                   command=self.undo_edit).pack(side="left", padx=1)
        ttk.Button(undo_row, text="Clear all (x)", width=15,
                   command=self.clear_edits).pack(side="left", padx=1)
        self.edits_label = ttk.Label(inspector, text="", style="PanelDim.TLabel")
        self.edits_label.pack(anchor="w", padx=8, pady=(4, 0))

        ttk.Separator(inspector).pack(fill="x", padx=8, pady=8)

        # --- mixer
        ttk.Label(inspector, text="MIXER   (monitoring only)",
                  style="PanelDim.TLabel").pack(anchor="w", padx=8)
        self.mixer_frame = ttk.Frame(inspector, style="Panel.TFrame")
        self.mixer_frame.pack(fill="x", padx=8, pady=(4, 12))

    def _build_timeline(self, parent):
        timeline = ttk.Frame(parent, style="Panel.TFrame")
        timeline.pack(fill="both", expand=True, padx=6, pady=(0, 6))

        # Transport
        transport = ttk.Frame(timeline, style="Panel.TFrame")
        transport.pack(fill="x", padx=6, pady=4)
        ttk.Button(transport, text="|<", width=4,
                   command=self._go_start).pack(side="left")
        ttk.Button(transport, text="<<10s", width=7,
                   command=lambda: self._skip(-10)).pack(side="left", padx=2)
        self.play_button = ttk.Button(transport, text="Play (space)", width=13,
                                      style="Accent.TButton",
                                      command=self.toggle_play)
        self.play_button.pack(side="left", padx=2)
        ttk.Button(transport, text="10s>>", width=7,
                   command=lambda: self._skip(10)).pack(side="left", padx=2)
        ttk.Button(transport, text=">|", width=4,
                   command=self._go_end).pack(side="left")
        ttk.Button(transport, text="Stop", width=6,
                   command=self.stop_audio).pack(side="left", padx=(2, 10))
        self.time_label = ttk.Label(transport, text="0:00 / 0:00",
                                    style="Value.TLabel",
                                    background=ui_theme.PANEL)
        self.time_label.pack(side="left")

        self.edited_mode = tk.BooleanVar(value=True)
        mode = ttk.Frame(transport, style="Panel.TFrame")
        mode.pack(side="right")
        ttk.Radiobutton(mode, text="Edited", variable=self.edited_mode, value=True,
                        command=self._on_mode_change).pack(side="right")
        ttk.Radiobutton(mode, text="Raw", variable=self.edited_mode, value=False,
                        command=self._on_mode_change).pack(side="right", padx=4)
        ttk.Label(mode, text="Monitor:", style="PanelDim.TLabel").pack(side="right",
                                                                      padx=6)

        # Packing order matters here. Tk squeezes whatever was packed LAST when
        # the parent runs out of room, so the fixed-height rows (scrollbar, zoom)
        # are claimed from the bottom FIRST and the waveform is packed last with
        # expand=True. Dragging the pane sash then resizes the waveform and
        # leaves the scrollbar alone - previously it crushed the scrollbar.
        footer = self.timeline_footer
        zoom = ttk.Frame(footer, style="Panel.TFrame")
        zoom.pack(side="bottom", fill="x", padx=6, pady=4)

        hscroll_row = tk.Frame(footer, height=HSCROLL_HEIGHT,
                               background=ui_theme.PANEL)
        hscroll_row.pack(side="bottom", fill="x", padx=6, pady=(4, 0))
        hscroll_row.pack_propagate(False)
        self.hscroll = ttk.Scrollbar(hscroll_row, orient="horizontal",
                                     command=self._on_scroll,
                                     style="Fat.Horizontal.TScrollbar")
        self.hscroll.pack(fill="both", expand=True)

        # Meters flanking the waveform - packed last, so it absorbs the slack.
        wave_row = ttk.Frame(timeline, style="Panel.TFrame")
        wave_row.pack(fill="both", expand=True, padx=6)
        self.track_meters = tk.Canvas(wave_row, width=METER_WIDTH,
                                      height=LANE_HEIGHT + RULER_HEIGHT,
                                      background=ui_theme.TIMELINE_BG,
                                      highlightthickness=0)
        self.track_meters.pack(side="left", fill="y")
        self.master_meter = tk.Canvas(wave_row, width=METER_WIDTH,
                                      height=LANE_HEIGHT + RULER_HEIGHT,
                                      background=ui_theme.TIMELINE_BG,
                                      highlightthickness=0)
        self.master_meter.pack(side="right", fill="y")
        self.canvas = tk.Canvas(wave_row, height=LANE_HEIGHT + RULER_HEIGHT,
                                background=ui_theme.TIMELINE_BG,
                                highlightthickness=0, cursor="hand2")
        self.canvas.pack(side="left", fill="both", expand=True)
        # The waveform is what gives when the pane is resized.
        wave_row.pack_propagate(False)
        self.canvas.bind("<Button-1>", self._on_press)
        self.canvas.bind("<B1-Motion>", self._on_drag)
        self.canvas.bind("<ButtonRelease-1>", self._on_release)
        self.canvas.bind("<Configure>", lambda e: self._draw_waveform())
        self.canvas.bind("<MouseWheel>", self._on_wheel)

        ttk.Button(zoom, text="-", width=3,
                   command=lambda: self._zoom(1.4)).pack(side="left")
        ttk.Button(zoom, text="+", width=3,
                   command=lambda: self._zoom(1 / 1.4)).pack(side="left", padx=2)
        ttk.Button(zoom, text="Fit", width=5,
                   command=self._zoom_fit).pack(side="left")
        self.zoom_label = ttk.Label(zoom, text="", style="PanelDim.TLabel")
        self.zoom_label.pack(side="left", padx=10)
        self.play_hint = ttk.Label(
            zoom, style="PanelDim.TLabel",
            text="click seek   |   drag select   |   shift-drag pan   |   wheel zoom")
        self.play_hint.pack(side="right")

    def _build_export_menu(self, menubar):
        """
        Exporting lives on the menu bar rather than a page of its own.

        It is a thing you do at the end, twice, not a place you spend time - it
        was taking a third of the window to hold two buttons and four options.
        The vars are created here because this is now their only home.
        """
        self.export_stems = tk.BooleanVar(value=False)
        self.export_transcript = tk.BooleanVar(value=True)
        self.intro_path = None
        self.outro_path = None

        menu = tk.Menu(menubar, tearoff=0, background=ui_theme.PANEL,
                       foreground=ui_theme.TEXT,
                       activebackground=ui_theme.SELECT)
        menu.add_command(label="Timeline for DaVinci Resolve (FCPXML)...",
                         command=self.export_fcpxml)
        menu.add_command(label="Finished audio (WAV)...",
                         command=self.export_audio_file)
        menu.add_separator()
        menu.add_checkbutton(label="Also write one WAV stem per speaker",
                             variable=self.export_stems)
        menu.add_checkbutton(
            label="Write the transcript alongside exports (.srt, .vtt, .txt)",
            variable=self.export_transcript)
        menu.add_separator()
        menu.add_command(label="Set intro audio...",
                         command=lambda: self._choose_bookend("intro"))
        menu.add_command(label="Clear intro",
                         command=lambda: self._clear_bookend("intro"))
        menu.add_command(label="Set outro audio...",
                         command=lambda: self._choose_bookend("outro"))
        menu.add_command(label="Clear outro",
                         command=lambda: self._clear_bookend("outro"))
        menubar.add_cascade(label="Export", menu=menu)

        # The two export entries are disabled until there is something to
        # export. Indices 0 and 1, kept here so the enable/disable helper does
        # not have to know the menu's shape.
        self.export_menu = menu
        self.export_menu_entries = (0, 1)
        self._set_export_enabled(False)

    def _set_export_enabled(self, enabled):
        state = "normal" if enabled else "disabled"
        for index in self.export_menu_entries:
            self.export_menu.entryconfig(index, state=state)

