"""
The text behind the Help menu.

Kept as data in its own module because the installed app has no README beside
it - for anyone who gets a built copy rather than the repository, this is the
only documentation there is.
"""

from version import APP_NAME, PROJECT_URL, __version__

QUICK_START = """\
WHAT THIS IS FOR

Recordings where every speaker was captured to their own file - OBS Source
Record, Riverside, local Zoom recordings. Auto-Cut finds where each person is
actually talking, removes the stretches where nobody is, and exports either a
DaVinci Resolve timeline or a finished WAV.


1. ADD YOUR RECORDINGS - HOST FIRST

The order decides which track each speaker lands on: the first file becomes
V1/A1, the second V2/A2, and so on. Use Up to reorder.

All the recordings must start at the same moment. That is what OBS produces.
There is no sync correction, so a file that starts late will stay late.


2. CLICK ANALYZE

Speech is found from the waveform. Each track is normalised, denoised, and run
through a gate that decides talking from not-talking. Neither the normalising
nor the denoising touches your audio - they only inform the decision.

The first run on a file has to decode it, which takes a few minutes for an
hour-long recording. After that it is cached and re-runs are quick.

If WhisperX is installed, transcription starts automatically once the cuts are
ready. You do not have to wait for it - the edit is already usable.

The Model dropdown decides how good and how slow that transcription is. Bigger
is better and much slower: tiny and base suit any laptop, small is a fair
compromise on a processor, and the large models really want an NVIDIA graphics
card. Choosing a large model without one is the most common reason people think
the app has frozen - it has not, it is just going to take hours.


3. SET THE AGGRESSIVENESS

The slider is the shortest pause that gets removed: 0 leaves anything under
three seconds alone, 100 cuts pauses as short as a quarter of a second. The
waveform re-shades as you drag, so you can see what each setting costs before
committing to it.

Turn Auto-cut dead air off if you would rather cut entirely by hand.


4. CHECK IT, AND FIX WHAT IS WRONG

Every speaker has their own waveform lane. Doomed stretches are shaded red.

  click            move the playhead
  drag             select a region
  shift + drag     pan
  mouse wheel      zoom

  q                delete the selection
  w                restore it
  a                mute this lane over the selection
  s                unmute it
  z                undo
  x                clear every hand edit

Monitor: Raw / Edited switches between hearing the original and hearing what
you are about to export - cuts, mutes, levels and effects included.

Auto-mute inactive speaker silences each microphone whenever its owner is not
talking, which removes bleed, breathing and keyboard noise from the idle mic.


5. EFFECTS (OPTIONAL)

Each track has its own VST3 chain, opened with its FX button. Plugin windows
open separately and what you hear updates as you turn a knob.

The installed version comes with a free voice chain already: rnnoise for noise
suppression, ZamGate, ZamComp, ZamEQ2, ZamDynamicEQ, ZaMaximX2 and ZamNoise.
Any VST3 plugin you install yourself shows up beside them.

A sensible starting order for a voice is: rnnoise, then ZamGate, then ZamComp,
then ZamEQ2, with ZaMaximX2 last to catch peaks.

Effects are rendered into the WAV export. They are NOT written into the Resolve
timeline, which points at your untouched original recordings - do that side of
the work in Resolve.


6. EXPORT, FROM THE EXPORT MENU

  Timeline for DaVinci Resolve
      Then in Resolve: File > Import > Timeline > Import AAF, EDL, XML...
      You get two video tracks and two mono audio tracks.

  Finished audio (WAV)
      Cuts, mutes, effects and levels all rendered in. For an audio podcast
      this is the whole job - no round trip through Resolve.

Intro and outro audio, if you set them, are added to the WAV only, and are
never cut or processed.


SAVING

File > Save project keeps your files, edits, levels and effect chains in one
.autocut file. The app also autosaves, and offers to recover after a crash.
"""

SHORTCUTS = """\
EDITING                          TRANSPORT

  q    delete selection            space   play / pause
  w    restore selection
  a    mute lane in selection    PROJECT
  s    unmute lane
  z    undo last edit              Ctrl+N  new project
  x    clear all hand edits        Ctrl+O  open project
                                   Ctrl+S  save project

TIMELINE

  click             move the playhead
  drag              select a region
  shift + drag      pan across the timeline
  mouse wheel       zoom in and out
  double-click      (transcript) seek to that line
"""

TROUBLESHOOTING = """\
"ffmpeg is required" when starting
    Auto-Cut needs ffmpeg to read audio. The installed version ships with its
    own copy, so if you see this, try reinstalling.

No sound during playback
    Playback uses whatever your operating system has set as the default output
    device. Change it in your sound settings and restart Auto-Cut.

The FX window is empty
    The installed version ships its own plugins, so this should not happen -
    try reinstalling. Running from source, only VST3 plugins are found, and
    only in the standard folder for your system. VST2 is not supported.

Transcription never happens
    It needs WhisperX, which is a separate install. Everything else works
    without it - the cuts do not depend on the transcript at all.

Transcription is very slow
    Without an NVIDIA graphics card it runs on the processor, which is slow for
    a long recording. Use a smaller model, or skip it.

Analysis seems stuck
    The first pass on a file decodes the whole recording, which can take a few
    minutes per hour of audio. Watch the LOG panel - it reports each step.

The app closed by itself
    An audio plugin misbehaving can take the whole app down, and Python cannot
    catch that. It is recorded in autocut_crash.log next to the program.
    Sending that file with a bug report helps enormously.
"""

ABOUT = f"""\
{APP_NAME} {__version__}

Removes dead air from multitrack podcast recordings.

Everything runs on your own machine. Nothing is uploaded, and there is no
account or subscription.

Free and open source under the MIT licence.
{PROJECT_URL}

Built on ffmpeg, numpy, sounddevice and pedalboard.
Transcription, when enabled, uses WhisperX.
Bundled effects: rnnoise and ZamPlugins, both open source.

See THIRD-PARTY-NOTICES.txt, installed alongside the program, for the
licences of everything included.
"""
