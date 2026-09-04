# Auto-Cut

**Removes the dead air from your podcast recordings, automatically.**

If you record a podcast where each person is on their own audio file — OBS,
Riverside, Zoom, StreamYard — Auto-Cut listens to each track, finds the long
silences where nobody is talking, and cuts them out. What normally takes an
evening of dragging clips around takes a couple of minutes.

Then it hands you either a **DaVinci Resolve timeline** to finish your video, or
a **finished audio file** ready to upload.

Everything happens on your own computer. No account, no subscription, nothing
uploaded anywhere.

---

## Download

### [⬇ Download Auto-Cut for Windows](../../releases/latest)

Open the file you downloaded and click through the installer. That's it — you
don't need to install anything else first.

> **Windows will show a blue warning box** saying *"Windows protected your PC"*.
> This is normal. It appears for any program whose author hasn't paid Microsoft
> for a certificate — a few hundred dollars a year, hard to justify for a free
> tool.
>
> To continue: click **More info**, then **Run anyway**.

Windows only for now. About 100 MB.

---

## How to use it

### 1. Add your recordings

Click **Add...** and pick each person's audio or video file.

**Put the host first.** The order matters — the first file becomes track 1, the
second becomes track 2, and so on.

Everyone's recording must start at the same moment, which is what OBS and
Riverside give you automatically.

### 2. Click Analyze

Auto-Cut listens to every track and works out when each person is speaking.

The first time you do this on a file it has to read the whole recording, so give
it a few minutes for an hour-long episode. After that it's quick. Watch the
**LOG** panel on the left — it says what it's doing.

### 3. Choose how aggressive to be

The **DEAD AIR** slider decides how long a pause has to be before it gets cut.

- Slide **left** — only removes long, obvious silences
- Slide **right** — tightens everything up, cutting even short pauses

The waveform updates as you drag, shading the doomed sections red, so you can
see exactly what you're about to lose before committing to it.

### 4. Listen, and fix anything wrong

Each person gets their own waveform lane. Click anywhere to jump there, press
**space** to play.

If Auto-Cut got something wrong, drag across the waveform to select it, then:

| To do this | Press |
|---|---|
| Cut the selected part | `q` |
| Put it back | `w` |
| Silence one person there | `a` |
| Unsilence them | `s` |
| Undo | `z` |

Tick **Auto-mute inactive speaker** to silence each microphone whenever its
owner isn't talking. That removes background noise, breathing and keyboard
clatter from whoever is listening.

### 5. Make it sound better (optional)

Every track has an **FX** button. Auto-Cut comes with free studio effects
already installed:

| Effect | What it does |
|---|---|
| rnnoise | Removes background hiss, fans, air conditioning |
| ZamGate | Silences the mic between sentences |
| ZamComp | Evens out someone who goes loud and quiet |
| ZamEQ2 | Adjusts tone — more warmth, less boominess |
| ZamDynamicEQ | Tames harsh "s" sounds |
| ZaMaximX2 | Stops the loudest moments distorting |

A good starting order for a voice: **rnnoise → ZamGate → ZamComp → ZamEQ2 →
ZaMaximX2**.

### 6. Export

From the **Export** menu:

**Making a video podcast?** Choose *Timeline for DaVinci Resolve*. Then in
Resolve: `File ▸ Import ▸ Timeline ▸ Import AAF, EDL, XML...` — your cut episode
appears, ready to colour and add graphics to.

**Making an audio podcast?** Choose *Finished audio (WAV)*. Everything is
already applied — cuts, effects, levels. Upload it and you're done.

You can add intro and outro music from the same menu.

---

## Saving your work

**File ▸ Save project** keeps your recordings, your edits and your effect
settings together, so you can come back later. Auto-Cut also saves as you go,
and offers to recover everything if it ever crashes.

---

## If something goes wrong

**No sound when I press play**
Auto-Cut uses whatever speakers Windows is set to. Change it in Windows sound
settings, then restart Auto-Cut.

**Analyze seems stuck**
The first pass on a long recording genuinely takes a few minutes. The LOG panel
shows what is happening — if it is still moving, it is still working.

**It cut something it shouldn't have**
Drag across that part of the waveform and press `w` to put it back. Or move the
DEAD AIR slider left, and it will be less aggressive everywhere.

**It closed by itself**
An audio effect can occasionally crash the program. There is a file called
`autocut_crash.log` in the folder where Auto-Cut is installed — sending that
makes it far easier to work out why.

---

## Transcripts (optional, and fiddly)

Auto-Cut can transcribe your episode and write subtitle files alongside your
export.

**This part is not included in the installer.** The speech recognition engine it
uses is several gigabytes, and most people don't need it. Setting it up means
installing Python and running a command — if that sentence means nothing to you,
ask someone technical to do it once, or simply skip it. Everything else works
perfectly without it.

Instructions are in [docs/DEVELOPERS.md](docs/DEVELOPERS.md).

---

## Support the podcast

Auto-Cut was built to make [Behind The Science
Podcast](https://www.facebook.com/btspodcastph) easier to produce, and it's free
for anyone else to use.

If it saves you time, you can support the show:

- ☕ [Buy me a coffee](https://buymeacoffee.com/podcastmesm)
- ▶ [YouTube](https://www.youtube.com/@marineearthscience)
- 🎧 [Spotify](https://open.spotify.com/show/4NTLrSfceKjpFvZWflzBJj)
- 📘 [Facebook](https://www.facebook.com/btspodcastph)

---

## For developers

Source, build instructions and the reasoning behind the design:
[docs/DEVELOPERS.md](docs/DEVELOPERS.md).

Auto-Cut includes GPL-licensed components, so the program as distributed is
covered by the **GNU General Public License version 3**. See
`THIRD-PARTY-NOTICES.txt`, installed alongside the program, for details and for
how to request the source code.
