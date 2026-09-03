# autocut-simple

A multitrack editor that strips dead air out of remote podcast recordings, for
the case where **each speaker was recorded to their own file** — OBS Source
Record, Riverside, Zoom local recordings, and so on.

It finds where each person is actually talking by looking at the waveform, cuts
the stretches where nobody is, and gives you a proper multitrack editor to
check the result: stacked per-speaker waveforms, playback, per-track VST3
effects, and auto-muting of whoever isn't speaking.

Then it exports either a **DaVinci Resolve timeline** (video podcasts) or a
**finished WAV** (audio podcasts).

Everything runs on your own machine. No cloud, no account, no subscription.

---

## Why this is a standalone app and not a Resolve plugin

DaVinci Resolve's free edition blocks the scripting API — `scriptapp("Resolve")`
returns nothing and a Studio upsell appears instead. There is no way for a
script to drive a timeline in Resolve Free.

So this runs outside Resolve entirely and hands it a finished FCPXML timeline
to import. That works on **every** edition, free included.

---

## Requirements

- **Python 3.10+** with tkinter (bundled on Windows and macOS; on Debian or
  Ubuntu, `sudo apt install python3-tk`)
- **ffmpeg and ffprobe** on your PATH — these do all the audio decoding:
  - Windows: `winget install Gyan.FFmpeg`
  - macOS: `brew install ffmpeg`
  - Linux: `sudo apt install ffmpeg`
- **VST3 plugins** (optional) for the per-track effects
- **WhisperX** (optional) for transcripts

The app checks for ffmpeg at startup and says so plainly if it is missing,
rather than failing later with a stack trace.

## Install

```bash
git clone https://github.com/<you>/autocut-simple.git
cd autocut-simple
pip install -r requirements.txt
```

Then run it:

```bash
python auto_cut/app.py
```

or double-click `launch_autocut.bat` (Windows) / run `./launch_autocut.sh`
(macOS, Linux).

### Transcripts (optional)

Transcription uses [WhisperX](https://github.com/m-bain/whisperX), which is a
far heavier install than the app itself. Cutting works fine without it.

```bash
pip install whisperx
```

Auto-Cut finds it on your PATH. If it lives in its own virtualenv — a good
idea, since it pulls in torch — point at it directly:

```bash
export AUTOCUT_WHISPERX=/path/to/venv/bin/whisperx   # Windows: set AUTOCUT_WHISPERX=...
```

All 100 Whisper languages are available. Whisper transcribes all of them, but
WhisperX only ships word-level *alignment* models for about 40. Without
alignment the word timings are coarse — which now only makes the karaoke
highlight less precise, since the cuts come from the waveform rather than from
the transcript.

Your NVIDIA GPU is used when there is one, with a CPU fallback otherwise. CPU
transcription of an hour-long track is slow, so pick a smaller model if that is
your situation. Force the choice with `AUTOCUT_DEVICE=cpu` or `cuda`.

---

## Usage

1. **Add each speaker's recording — host first.** The order decides which track
   each speaker lands on: first is V1/A1, second V2/A2, and so on.

2. **Analyze.** Speech is found from the waveform, not from a transcript. Each
   track is normalised, denoised with rnnoise, and run through an adaptive
   gate. *Both of those steps exist only to make the decision — neither is
   baked into your audio.* Decoded audio is cached, so re-runs are quick.

   If WhisperX is installed, transcription follows on automatically. The cuts
   do not wait for it.

3. **Aggressiveness slider (0–100)** sets the shortest pause that gets cut,
   from 3.0s (conservative) down to 0.25s (aggressive). The scale is geometric:
   real pauses cluster near half a second, so a linear slider would do almost
   nothing for most of its travel.

4. **Check the edit.** Every speaker gets their own waveform lane, with the
   doomed stretches shaded red and redrawn live as you move the slider. Click
   to seek, drag to select, shift-drag to pan, wheel to zoom.

   | Action | Key |
   |---|---|
   | Delete selection | `q` |
   | Restore selection | `w` |
   | Mute lane in selection | `a` |
   | Unmute lane | `s` |
   | Undo | `z` |
   | Clear all edits | `x` |

5. **Auto-mute inactive speaker** silences each mic while its owner isn't
   talking, which removes bleed, breathing and keyboard noise.

6. **Effects (FX).** Each track has its own VST3 chain. Plugin windows open in
   a separate process, and turning a knob is audible immediately.

7. **Export**, from the Export menu:
   - **Timeline for DaVinci Resolve** — then `File ▸ Import ▸ Timeline ▸
     Import AAF, EDL, XML…`. You get two video tracks and two mono audio
     tracks, pointing at your original recordings, carrying the cuts, mutes and
     levels.
   - **Finished audio (WAV)** — cuts, mutes, effects and levels all rendered
     in. For an audio podcast this is the entire deliverable, with no round
     trip through Resolve.

---

## How the cut logic works

Per track, for analysis only:

1. **Normalise.** Recordings come from different rooms, mics and calls, so one
   person's silence can sit louder than another's speech. The level is taken
   from the 95th percentile of frame energy rather than overall RMS — most of a
   podcast track is one person *not* talking, so overall RMS mostly measures how
   quiet their room is, and normalising by it would amplify the quietest
   recording the most.
2. **Denoise** with rnnoise. Room tone and fan noise are what a plain energy
   gate mistakes for talking.
3. **Gate** with hysteresis, then merge speech separated by less than 0.15s.

That merge matters more than any threshold. Without it the gate flickers, and a
single 20ms blip in the middle of a long silence splits it into two halves each
too short to cut.

Detected regions are then widened by 0.10s at each end, and a further 0.25s is
kept around every cut. A word does not start at full volume — "s", "f" and soft
first syllables cross the gate slightly after the sound began — so cutting at
the detected boundary clips the first or last letter.

Finally, a stretch is removed only if **every** speaker is silent through it.

---

## FCPXML structure (why it looks the way it does)

Resolve's FCPXML importer decides the track layout itself, using heuristics you
cannot control from the file. Getting two clean tracks took a series of
hand-written import tests. What they showed:

- Speaker 0 goes in the **primary storyline**; everyone else is a **connected
  clip** on lane N. That yields V1/A1, V2/A2 and nothing else. Hanging every
  speaker off a base `<gap>` instead also works, but the gap itself imports as
  an empty V1.
- Each speaker needs a **unique audio role** (`dialogue.<name>`). With one
  shared `dialogue` role, Resolve loses track of whose audio is whose once the
  timeline fragments into many cut segments, and scatters it across tracks.
- Mono sources must be **declared** mono. Claiming `audioChannels="2"` for a
  mono file caused the same scattering.
- Host and guest are split on the **union** of both their mute boundaries, so
  their pieces line up one to one and each guest piece can hang off the host
  piece it sits over. A connected clip's `offset` is measured in its parent
  clip's local time, not timeline time.

Camera switching was attempted and removed. Doing it properly needs Resolve's
scripting API to enable and disable clips on a timeline it already owns —
exactly what the free edition blocks. Every attempt to express it in FCPXML
added clips that Resolve then redistributed on import.

---

## Layout

| File | Role |
|---|---|
| `auto_cut/app.py` | Application and entry point |
| `auto_cut/app_ui.py` | Widget construction |
| `auto_cut/app_actions.py` | Project I/O and transcript editing |
| `auto_cut/voice_activity.py` | Finds speech from the waveform |
| `auto_cut/silence_detector.py` | Merges speakers, computes keep ranges |
| `auto_cut/player.py` | Multitrack playback (memory-mapped PCM, live mixing) |
| `auto_cut/waveform.py` | Waveform peaks via ffmpeg |
| `auto_cut/vst_host.py` | VST3 discovery and per-track effect chains |
| `auto_cut/fcpxml_writer.py` | Writes the Resolve timeline |
| `auto_cut/audio_export.py` | Renders the finished WAV |
| `auto_cut/whisperx_runner.py` | Optional transcription |
| `auto_cut/project.py` | Save, open, autosave |

---

## Known limits

- **Speakers must start together.** All recordings are assumed to share a
  timeline origin, which is what OBS Source Record produces. There is no drift
  correction and no sync offset.
- Plugin editor windows are raised to the front only on Windows. The plugins
  themselves work everywhere.
- Video is never re-encoded, and there is no video preview — the waveform is
  the editing surface.

## Licence

MIT — see [LICENSE](LICENSE).
