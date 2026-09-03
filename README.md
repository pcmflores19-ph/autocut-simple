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

## What you need

| | Required? | Why |
|---|---|---|
| Python 3.10 or newer | yes | the app is written in it |
| ffmpeg + ffprobe | yes | reads and writes all the audio |
| VST3 plugins | optional | only for the per-track effects |
| WhisperX | optional | only for transcripts — cutting works without it |
| NVIDIA GPU | optional | makes transcription much faster |

Runs on Windows, macOS and Linux.

## Installation

If you have never used Python or the command line before, follow this from the
top — it takes about ten minutes, most of it waiting for downloads.

### 1. Install Python

Download it from [python.org/downloads](https://www.python.org/downloads/).

> **On Windows, tick "Add python.exe to PATH" on the first screen of the
> installer.** It is off by default, and without it every command below fails
> with "python is not recognized". If you have already installed Python and hit
> that error, run the installer again, choose Modify, and enable it.

On Debian or Ubuntu you also need tkinter, which is packaged separately:

```bash
sudo apt install python3 python3-pip python3-tk
```

Check it worked — open a new terminal (PowerShell on Windows) and run:

```bash
python --version
```

You should see `Python 3.10` or higher. On macOS and Linux you may need
`python3` instead of `python` in every command here.

### 2. Install ffmpeg

This does all the audio decoding. Auto-Cut cannot run without it.

```bash
winget install Gyan.FFmpeg     # Windows
brew install ffmpeg            # macOS  (needs https://brew.sh)
sudo apt install ffmpeg        # Debian / Ubuntu
```

**Close your terminal and open a new one afterwards**, so it picks up the
change, then check:

```bash
ffmpeg -version
```

### 3. Download Auto-Cut

Either clone it, if you have git:

```bash
git clone https://github.com/<you>/autocut-simple.git
cd autocut-simple
```

or, without git: click the green **Code** button at the top of this page,
choose **Download ZIP**, unzip it somewhere sensible, and `cd` into the folder.

### 4. Install the Python dependencies

```bash
pip install -r requirements.txt
```

Three packages, no compiler needed.

### 5. Run it

```bash
python auto_cut/app.py
```

Or just double-click **`launch_autocut.bat`** on Windows. On macOS and Linux,
`./launch_autocut.sh` (you may need `chmod +x launch_autocut.sh` once).

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

Pick the model from the **Model** dropdown next to Analyze. Bigger is more
accurate and much slower: `tiny` and `base` are usable on any laptop, `small`
is a good compromise on a processor, and the `large` models really want an
NVIDIA card. The app warns you if you pick a large model without one, because
that combination looks exactly like the app having frozen.

All 100 Whisper languages are available. Whisper transcribes all of them, but
WhisperX only ships word-level *alignment* models for about 40. Without
alignment the word timings are coarse — which now only makes the karaoke
highlight less precise, since the cuts come from the waveform rather than from
the transcript.

Your NVIDIA GPU is used when there is one, with a CPU fallback otherwise. CPU
transcription of an hour-long track is slow, so pick a smaller model if that is
your situation. Force the choice with `AUTOCUT_DEVICE=cpu` or `cuda`.

---

## Included effects

The Windows installer ships a small, open-source voice chain so the FX window
is not empty on a fresh install:

| Plugin | Use |
|---|---|
| rnnoise | noise suppression |
| ZamGate | gate the idle microphone |
| ZamComp | compressor |
| ZamEQ2 | parametric EQ |
| ZamDynamicEQ | dynamic EQ, doubles as a de-esser |
| ZaMaximX2 | limiter |
| ZamNoise | broadband noise reduction |

Any VST3 you have installed yourself appears alongside them, and takes priority
if it has the same name.

rnnoise earns its place twice over: the speech detection uses it to denoise
each track before gating, so the cuts themselves are better for it being there.

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

## Troubleshooting

**"python is not recognized" / "command not found"**
Python is not on your PATH. On Windows, re-run the Python installer, choose
Modify, and tick "Add python.exe to PATH". On macOS and Linux, try `python3`.

**"ffmpeg is required" when the app starts**
ffmpeg is not installed, or your terminal was open before you installed it.
Close every terminal window, open a new one, and check with `ffmpeg -version`.

**`ModuleNotFoundError: No module named 'tkinter'`**
Linux only — tkinter is packaged separately: `sudo apt install python3-tk`.

**No sound during playback**
`sounddevice` uses your system's default output device. Change it in your OS
sound settings, then restart the app.

**No plugins in the FX window**
Auto-Cut looks in the standard VST3 folders for your platform. VST2 plugins are
not supported — only VST3. If you keep plugins somewhere unusual, they will not
be found automatically.

**"WhisperX was not found"**
Transcription is optional, so you can ignore this. To enable it, either
`pip install whisperx` or set `AUTOCUT_WHISPERX` to the full path of the
executable (see [Transcripts](#transcripts-optional)).

**Transcription is extremely slow**
You have no NVIDIA GPU, so it is running on the CPU. Use a smaller Whisper
model, or skip transcription — the cuts do not depend on it.

**The app closed unexpectedly**
Look at `auto_cut/autocut_crash.log`. Native crashes inside an audio plugin
cannot be caught by Python, so they are recorded there instead. Including that
file in a bug report helps a great deal.

---

## Known limits

- **Speakers must start together.** All recordings are assumed to share a
  timeline origin, which is what OBS Source Record produces. There is no drift
  correction and no sync offset.
- Plugin editor windows are raised to the front only on Windows. The plugins
  themselves work everywhere.
- Video is never re-encoded, and there is no video preview — the waveform is
  the editing surface.

## Contributing

Bug reports and pull requests are welcome. For a bug, the most useful things to
include are your operating system, what you were doing, and the contents of
`auto_cut/autocut_crash.log` if the app closed unexpectedly.

## Updates

**Help > Check for updates** asks GitHub whether there is a newer release.
Nothing is checked automatically and nothing is downloaded or installed for
you - the app makes no network requests at all unless you ask it to.

## Licence

MIT — see [LICENSE](LICENSE). You can use, modify and share this freely,
including commercially. It comes with no warranty.
