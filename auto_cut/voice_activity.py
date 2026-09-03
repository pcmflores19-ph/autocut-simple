"""
Finds who is speaking when, from the waveform alone.

This used to be derived from WhisperX word timestamps, which meant you had to
sit through a transcription of every track before you could see a single cut.
It also made the cuts only as good as the transcript: a misheard Taglish phrase
or a dropped word moved the edit. The waveform already knows where speech is,
and it knows immediately.

The analysis chain, per track:

  1. NORMALIZE - the recordings come from different rooms, mics and Meet
     sessions, so one speaker's silence can sit louder than another's speech.
     Levelling them first means a single threshold means the same thing on
     every track.
  2. DENOISE with rnnoise - room tone, fan noise and laptop hum are what a
     plain energy gate mistakes for talking. Stripping them makes the gap
     between speech and silence wide and obvious.
  3. THRESHOLD - an adaptive gate with hysteresis over short frames.

Steps 1 and 2 exist ONLY to make the decision. Nothing here is baked into the
track: what comes back is a list of time ranges. The audio you hear, edit and
export is untouched by any of it - the user's own VST chain remains the only
thing that ever changes the sound.
"""

import numpy as np

from player import SAMPLE_RATE, decode_to_pcm

FRAME_SECONDS = 0.020        # 20ms frames, 10ms hop - fine enough to catch
HOP_SECONDS = 0.010          # word boundaries without chasing every glottal stop

# Speech is normalized to this RMS before thresholding. Well below full scale,
# so the loud moments have headroom and nothing clips into the denoiser.
TARGET_RMS = 0.12

# Where the gate sits between the measured noise floor and the measured speech
# level. 0.30 puts it nearer the floor, which is right after denoising: the
# floor is genuinely quiet, so the risk is clipping soft speech, not letting
# noise through.
THRESHOLD_FRACTION = 0.30
MIN_MARGIN_DB = 8.0          # never gate less than this above the noise floor
ABSOLUTE_FLOOR_DB = -55.0    # nothing quieter than this is ever speech

# rnnoise doesn't attenuate room tone, it removes it - the quiet parts come back
# as true digital silence, so the measured "noise floor" is the -180 dB clamp
# and floor-relative maths stops meaning anything. This keeps the gate a fixed
# distance BELOW the speech level, which stays meaningful either way.
BELOW_SPEECH_DB = 20.0

# Hysteresis: once speech has started it takes a bigger drop to end it, so
# ordinary dips inside a word don't chop it in half.
RELEASE_DB = 5.0

# Speech separated by less than this is treated as one region. Without it the
# gate flickers: a lip smack or a dip inside a word closes and reopens it, and
# a single 20ms blip in the middle of a long silence splits that silence into
# two halves that are each too short to cut. Merging first, then discarding the
# stragglers, is what stops one stray sample protecting five seconds of dead
# air - and it is far gentler than simply demanding long speech regions, which
# throws away real one-word answers ("oo", "tama").
# Each detected region is widened by this before anything else. A word does not
# start at full volume - "s", "f", "h" and a soft first syllable climb past the
# gate a moment after the sound actually began, and the tail of a word fades
# below it before the word is over. Detecting from energy alone therefore always
# lands slightly INSIDE the word at both ends, and cutting there clips the first
# or last letter. Widening first means the speech regions bracket the whole word.
ONSET_GUARD_SECONDS = 0.10

HANGOVER_SECONDS = 0.15
MIN_SPEECH_SECONDS = 0.20    # shorter than this, after merging, is not a word


def _load(path):
    """The track as mono float32, straight off the decode cache."""
    samples = np.memmap(decode_to_pcm(path), dtype=np.int16, mode="r")
    return np.asarray(samples, dtype=np.float32) / 32768.0


def _frame_levels(samples):
    """RMS per frame, in dBFS. Returns (levels_db, hop_seconds)."""
    frame = int(FRAME_SECONDS * SAMPLE_RATE)
    hop = int(HOP_SECONDS * SAMPLE_RATE)
    if samples.size < frame:
        return np.zeros(0, dtype=np.float32), HOP_SECONDS

    count = 1 + (samples.size - frame) // hop
    # A strided view: no copy, so an hour of audio costs nothing extra here.
    frames = np.lib.stride_tricks.as_strided(
        samples, shape=(count, frame),
        strides=(samples.strides[0] * hop, samples.strides[0]),
        writeable=False,
    )
    rms = np.sqrt(np.mean(np.square(frames, dtype=np.float64), axis=1))
    return 20.0 * np.log10(np.maximum(rms, 1e-9)), HOP_SECONDS


def normalize(samples):
    """
    Scales the track so its speech sits at TARGET_RMS.

    The level is taken from the 95th percentile of frame energy rather than the
    overall RMS: most of a podcast track is one person NOT talking, so overall
    RMS mostly measures how quiet their room is, and normalizing by it would
    amplify the quietest recording the most - exactly backwards.
    """
    levels_db, _ = _frame_levels(samples)
    if levels_db.size == 0:
        return samples
    speech_db = float(np.percentile(levels_db, 95))
    speech_rms = 10.0 ** (speech_db / 20.0)
    if speech_rms <= 1e-6:
        return samples
    gain = TARGET_RMS / speech_rms
    peak = float(np.abs(samples).max()) or 1.0
    gain = min(gain, 0.99 / peak)          # headroom for the denoiser
    return samples * np.float32(gain)


def find_denoiser(plugins=None):
    """The rnnoise VST3 path, or None if it isn't installed on this machine."""
    if plugins is None:
        import vst_host
        plugins = vst_host.discover_plugins()
    for name, path in plugins:
        if "rnnoise" in name.lower():
            return path
    return None


def denoise(samples, plugin_path, log=None):
    """
    Runs the track through rnnoise for analysis purposes only.

    Its own chain and its own plugin instance - never the user's live chain,
    which belongs to the audio callback.
    """
    import vst_host
    chain = vst_host.TrackChain()
    try:
        chain.add("rnnoise", plugin_path)
        return chain.process(samples, SAMPLE_RATE, reset=True)
    except Exception as exc:
        if log:
            log(f"  rnnoise unavailable ({exc}); detecting on the raw waveform")
        return samples


def _gate(levels_db, hop_seconds):
    """Frame levels -> (start, end) speech intervals, via an adaptive gate."""
    if levels_db.size == 0:
        return [], -90.0, -90.0

    floor_db = float(np.percentile(levels_db, 10))
    speech_db = float(np.percentile(levels_db, 95))

    open_db = floor_db + THRESHOLD_FRACTION * max(speech_db - floor_db, 0.0)
    open_db = max(open_db, floor_db + MIN_MARGIN_DB, ABSOLUTE_FLOOR_DB,
                  speech_db - BELOW_SPEECH_DB)
    close_db = open_db - RELEASE_DB

    intervals = []
    start = None
    for i, level in enumerate(levels_db):
        if start is None:
            if level >= open_db:
                start = i
        elif level < close_db:
            intervals.append((start * hop_seconds,
                              (i + FRAME_SECONDS / hop_seconds) * hop_seconds))
            start = None
    if start is not None:
        intervals.append((start * hop_seconds,
                          (levels_db.size + FRAME_SECONDS / hop_seconds) * hop_seconds))

    intervals = [(max(0.0, s - ONSET_GUARD_SECONDS), e + ONSET_GUARD_SECONDS)
                 for s, e in intervals]
    intervals = _merge_close(intervals, HANGOVER_SECONDS)
    intervals = [(s, e) for s, e in intervals if e - s >= MIN_SPEECH_SECONDS]
    return intervals, floor_db, open_db


def _merge_close(intervals, max_gap):
    """Joins intervals separated by less than `max_gap`."""
    if not intervals:
        return []
    out = [list(intervals[0])]
    for start, end in intervals[1:]:
        if start - out[-1][1] <= max_gap:
            out[-1][1] = max(out[-1][1], end)
        else:
            out.append([start, end])
    return [tuple(iv) for iv in out]


def speaking_intervals(path, denoiser_path=None, duration=None, log=None):
    """
    Returns (start, end) ranges where this speaker is talking, found from the
    waveform. `denoiser_path` is rnnoise; without it the gate still works, just
    less cleanly on a noisy room.

    Neither the normalization nor the denoising touches the file or the audio
    the app plays and exports - they shape a throwaway copy used to decide.
    """
    import os
    name = os.path.basename(path)
    if log:
        log(f"  {name}: reading waveform")
    samples = _load(path)

    if log:
        log(f"  {name}: normalizing for analysis")
    work = normalize(samples)

    if denoiser_path:
        if log:
            log(f"  {name}: denoising for analysis (not baked in)")
        work = denoise(work, denoiser_path, log=log)

    levels_db, hop = _frame_levels(work)
    intervals, floor_db, gate_db = _gate(levels_db, hop)

    if duration:
        intervals = [(max(0.0, s), min(duration, e)) for s, e in intervals
                     if s < duration]
    talk = sum(e - s for s, e in intervals)
    if log:
        log(f"  {name}: noise floor {floor_db:.1f} dB, gate {gate_db:.1f} dB, "
            f"{len(intervals)} speech regions, {talk:.0f}s of speech")
    return intervals
