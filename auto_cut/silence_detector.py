"""
Turns per-speaker speech intervals into a single set of "keep" time ranges, by
merging every speaker's speech into one "someone is talking" timeline and
cutting only where *everyone* is silent for longer than a threshold.

Where those intervals come from is deliberately not this module's business -
see voice_activity, which measures them from the waveform.
"""

# Aggressiveness is exposed to the user as a 0-100 slider. 0 = conservative
# (only cut long silences), 100 = aggressive (cut almost any pause).
#
# The top of the range is a deliberate "barely touch it" setting: 3s pauses are
# rare (measured over a real episode the silences run 0.46s median, 1.39s at the
# 95th percentile), so 0 removes only the handful of genuinely dead stretches.
# The bottom is set to those real pauses rather than to the old word-timestamp
# figures, which exaggerated the gaps because words are reported more tightly
# than speech actually stops.
MIN_GAP_SECONDS_AT_0 = 3.0
MIN_GAP_SECONDS_AT_100 = 0.25

# Kept on either side of a cut so words aren't clipped. Generous on purpose:
# a slightly long pause is invisible, a clipped first letter is not.
#
# Capped at a share of the gap, so a short pause is still trimmed rather than
# being swallowed whole by its own padding - at the aggressive end of the slider
# the gaps being cut are shorter than two full paddings.
PADDING_SECONDS = 0.25
PADDING_MAX_SHARE = 0.35     # of the gap, per side

# Keep segments shorter than this are dropped entirely - they're usually just
# the padding left over around a cut (e.g. a 4-frame sliver at the tail), not
# real content, and they'd litter the timeline with unusable clips.
MIN_KEEP_SECONDS = 0.30


def aggressiveness_to_min_gap(aggressiveness):
    """
    Slider position -> the shortest pause that gets cut.

    Geometric rather than linear, because the pauses are not spread evenly.
    Nearly all of them are short - 0.46s at the median, 1.39s at the 95th
    percentile - so a linear 3.0s..0.25s slider does almost nothing for its
    first two thirds and then changes the edit drastically at the very end.
    Stepping by a constant ratio instead spreads the useful range across the
    whole travel, which is the same reason volume and frequency controls are
    not linear either.
    """
    aggressiveness = max(0, min(100, aggressiveness))
    t = aggressiveness / 100.0
    ratio = MIN_GAP_SECONDS_AT_100 / MIN_GAP_SECONDS_AT_0
    return MIN_GAP_SECONDS_AT_0 * (ratio ** t)


def _merge_intervals(intervals):
    """Merges overlapping/touching (start, end) tuples, sorted by start."""
    if not intervals:
        return []
    intervals = sorted(intervals, key=lambda iv: iv[0])
    merged = [list(intervals[0])]
    for start, end in intervals[1:]:
        last = merged[-1]
        if start <= last[1]:
            last[1] = max(last[1], end)
        else:
            merged.append([start, end])
    return [tuple(iv) for iv in merged]


def find_silence_gaps(speaking_intervals, timeline_start, timeline_end, min_gap_seconds):
    """
    Returns (gap_start, gap_end) ranges, at least min_gap_seconds long, where
    nobody is speaking, clipped to [timeline_start, timeline_end].
    """
    gaps = []
    cursor = timeline_start
    for start, end in speaking_intervals:
        start = max(start, timeline_start)
        end = min(end, timeline_end)
        if start > cursor:
            gap_len = start - cursor
            if gap_len >= min_gap_seconds:
                gaps.append((cursor, start))
        cursor = max(cursor, end)
        if cursor >= timeline_end:
            break
    if cursor < timeline_end:
        gap_len = timeline_end - cursor
        if gap_len >= min_gap_seconds:
            gaps.append((cursor, timeline_end))
    return gaps


def gaps_to_keep_ranges(gaps, timeline_start, timeline_end, padding_seconds=PADDING_SECONDS,
                        min_keep_seconds=MIN_KEEP_SECONDS):
    """
    Inverts silence gaps (shrunk by padding, so a little breathing room is
    kept around each cut) into the ranges that should survive in the edit.
    """
    # Shrink each gap by padding on both sides; a gap that's fully consumed
    # by padding is dropped (too short to actually cut).
    padded_gaps = []
    for start, end in gaps:
        pad = min(padding_seconds, (end - start) * PADDING_MAX_SHARE)
        padded_start = start + pad
        padded_end = end - pad
        if padded_end > padded_start:
            padded_gaps.append((padded_start, padded_end))

    keep_ranges = []
    cursor = timeline_start
    for gap_start, gap_end in padded_gaps:
        if gap_start > cursor:
            keep_ranges.append((cursor, gap_start))
        cursor = max(cursor, gap_end)
    if cursor < timeline_end:
        keep_ranges.append((cursor, timeline_end))
    return [(s, e) for s, e in keep_ranges if e - s >= min_keep_seconds]


def subtract_ranges(ranges, removals, min_keep_seconds=MIN_KEEP_SECONDS):
    """
    Removes `removals` from `ranges`, splitting entries where a removal lands in
    the middle. Used for hand-picked deletions on top of the automatic cuts.
    """
    if not removals:
        return list(ranges)

    removals = _merge_intervals([(s, e) for s, e in removals if e > s])
    out = []
    for start, end in ranges:
        cursor = start
        for rem_start, rem_end in removals:
            if rem_end <= cursor or rem_start >= end:
                continue
            if rem_start > cursor:
                out.append((cursor, min(rem_start, end)))
            cursor = max(cursor, rem_end)
            if cursor >= end:
                break
        if cursor < end:
            out.append((cursor, end))
    return [(s, e) for s, e in out if e - s >= min_keep_seconds]


def complement_ranges(ranges, timeline_start, timeline_end):
    """Everything in [timeline_start, timeline_end] not covered by `ranges`."""
    out = []
    cursor = timeline_start
    for start, end in _merge_intervals(ranges):
        if start > cursor:
            out.append((cursor, min(start, timeline_end)))
        cursor = max(cursor, end)
        if cursor >= timeline_end:
            break
    if cursor < timeline_end:
        out.append((cursor, timeline_end))
    return out


def apply_range_edits(base, edits, add_kind, remove_kind, min_length=0.0):
    """
    Replays ordered (kind, start, end) edits over `base`, so the most recent
    action wins wherever edits overlap. `add_kind` unions a range in,
    `remove_kind` takes it back out.
    """
    out = list(base)
    for kind, start, end in edits:
        if end <= start:
            continue
        if kind == add_kind:
            out = _merge_intervals(out + [(start, end)])
        elif kind == remove_kind:
            out = subtract_ranges(out, [(start, end)], min_keep_seconds=0.0)
    return [(s, e) for s, e in out if e - s >= min_length]


def apply_edits(keep_ranges, edits, min_keep_seconds=MIN_KEEP_SECONDS):
    """
    Hand edits over the automatic keep ranges:
      ("cut", start, end)     - force this stretch out of the timeline
      ("restore", start, end) - force it back in, even if auto-detected as silence
    """
    return apply_range_edits(keep_ranges, edits, add_kind="restore",
                             remove_kind="cut", min_length=min_keep_seconds)


# Auto-mute: silence a speaker's track wherever they aren't the one talking,
# which kills mic bleed, breathing and keyboard noise from the idle mic.
MUTE_PADDING_SECONDS = 0.25   # keep either side of speech so onsets aren't clipped
MIN_AUTO_MUTE_SECONDS = 0.6   # don't litter the track with micro-mutes between words


# --------------------------------------------------- who is actually talking
#
# A lane muted purely on its own energy cannot tell a real voice from the other
# person bleeding into the microphone. Two consequences, both heard in practice:
# when someone laughs into your mic your gate opens and their laugh leaks
# through your channel, and when two people laugh together the quieter one can
# be gated off mid-laugh.
#
# Comparing lanes fixes both. Whoever is loudest in a moment is definitely
# talking; anyone within LEAD_MARGIN_DB of them is talking too - which is what
# lets both speakers stay open when they overlap. Bleed sits well below the
# person actually producing it, so it falls outside the margin and stays muted.

# Bleed is typically 10-20 dB down on the source, so 6 dB separates "we are
# both talking" from "that is you, in my microphone".
LEAD_MARGIN_DB = 6.0

# Below this nothing counts as talking however it compares to the others -
# without it, a silent passage would crown whichever lane happened to have the
# loudest hiss.
ACTIVE_FLOOR_DB = -50.0


def active_intervals_by_lane(levels_by_lane, hop_seconds,
                             lead_margin_db=LEAD_MARGIN_DB,
                             floor_db=ACTIVE_FLOOR_DB,
                             hangover_seconds=0.15,
                             min_active_seconds=0.20):
    """
    Per-frame comparison across lanes -> (start, end) "this speaker is really
    talking" intervals for each lane.

    `levels_by_lane` is one dB array per lane, all on the same frame grid.
    Lengths may differ slightly (recordings are rarely identical lengths); the
    shortest wins and the rest are truncated.

    Returns a list of interval lists, one per lane, in the same order.
    """
    import numpy as np

    if not levels_by_lane:
        return []
    length = min(len(l) for l in levels_by_lane)
    if length == 0:
        return [[] for _ in levels_by_lane]

    stacked = np.vstack([np.asarray(l[:length], dtype=np.float32)
                         for l in levels_by_lane])
    loudest = stacked.max(axis=0)
    # Active where within the margin of whoever leads AND above the floor.
    active = (stacked >= (loudest - lead_margin_db)) & (stacked > floor_db)

    out = []
    for lane in range(stacked.shape[0]):
        out.append(_runs_to_intervals(active[lane], hop_seconds,
                                      hangover_seconds, min_active_seconds))
    return out


def _runs_to_intervals(flags, hop_seconds, hangover_seconds,
                       min_active_seconds):
    """Boolean per-frame array -> merged, de-fluffed (start, end) seconds."""
    import numpy as np

    flags = np.asarray(flags)
    if not flags.any():
        return []
    # Edges of each True run, without looping in Python over every frame.
    padded = np.concatenate(([False], flags, [False]))
    changes = np.flatnonzero(padded[1:] != padded[:-1])
    starts, ends = changes[0::2], changes[1::2]

    intervals = [(float(a) * hop_seconds, float(b) * hop_seconds)
                 for a, b in zip(starts, ends)]
    intervals = _merge_intervals(
        [(s, e + hangover_seconds) for s, e in intervals])
    return [(s, e - hangover_seconds) for s, e in intervals
            if (e - hangover_seconds) - s >= min_active_seconds]


def compute_auto_mutes_from_intervals(speaking, timeline_start, timeline_end,
                                      padding=MUTE_PADDING_SECONDS,
                                      min_mute_seconds=MIN_AUTO_MUTE_SECONDS):
    """
    Stretches where THIS speaker is inactive, as (start, end) ranges. Their own
    speech is padded outward first so breaths and word onsets survive.
    """
    speaking = _merge_intervals(list(speaking))
    if not speaking:
        return [(timeline_start, timeline_end)]

    padded = _merge_intervals([
        (max(start - padding, timeline_start), min(end + padding, timeline_end))
        for start, end in speaking
    ])
    inactive = complement_ranges(padded, timeline_start, timeline_end)
    return [(s, e) for s, e in inactive if e - s >= min_mute_seconds]


def apply_mute_edits(auto_mutes, edits, min_length=0.0):
    """
    Hand edits over a lane's automatic mutes:
      ("mute", start, end)   - silence this stretch
      ("unmute", start, end) - bring it back, undoing an auto-mute if needed
    """
    return apply_range_edits(auto_mutes, edits, add_kind="mute",
                             remove_kind="unmute", min_length=min_length)


def compute_keep_ranges_from_intervals(per_speaker_intervals, timeline_start,
                                       timeline_end, aggressiveness, edits=None):
    """
    End-to-end: per-speaker speech intervals -> keep ranges, given a 0-100
    aggressiveness value. `edits` are ordered hand edits (cut/restore) layered
    on top. Returns (keep_ranges, gaps); gaps is exactly the complement of keep,
    so what the UI shades always matches what actually gets removed.
    """
    min_gap = aggressiveness_to_min_gap(aggressiveness)
    merged = []
    for intervals in per_speaker_intervals:
        merged.extend(intervals)
    speaking = _merge_intervals(merged)
    gaps = find_silence_gaps(speaking, timeline_start, timeline_end, min_gap)
    keep = gaps_to_keep_ranges(gaps, timeline_start, timeline_end)

    if edits:
        keep = apply_edits(keep, edits)

    return keep, complement_ranges(keep, timeline_start, timeline_end)


def summarize(gaps, keep_ranges):
    cut_seconds = sum(end - start for start, end in gaps)
    return {
        "num_cuts": len(gaps),
        "seconds_removed": round(cut_seconds, 2),
        "num_keep_segments": len(keep_ranges),
    }
