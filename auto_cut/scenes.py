"""
Which camera is on screen, and when.

A vodcast here is three recordings of the same conversation: V1 the host alone,
V2 the guest alone, and V3 the merged shot with both already in frame. V3 is
picture only - its audio is the same two voices again and would double every
word - so it never becomes a speaker track.

The decision needs no new analysis. `silence_detector.active_intervals_by_lane`
already works out who is genuinely talking at each moment, including two people
at once, for auto-mute. A camera cut asks the same question:

    host alone   -> V1
    guest alone  -> V2
    both, or neither -> V3

An earlier attempt at switching described it in FCPXML and asked DaVinci
Resolve to honour it; Resolve rearranged the clips instead, and the free
edition blocks the scripting API that would have made it work. This time the
cut is rendered by us in the video export, where nothing can second-guess it.
"""

HOST, GUEST, BOTH = 0, 1, 2

# Below this a shot is not a shot. Without it, a "mm-hm" in the middle of the
# other person's sentence cuts away and back inside a few frames, which reads
# as a glitch rather than an edit.
DEFAULT_MIN_SHOT_SECONDS = 2.0


def scene_timeline(active_by_lane, duration, min_shot_seconds=None,
                   hop_seconds=0.01):
    """
    [(camera, start, end)] covering 0..duration with no gaps.

    `active_by_lane` is [host_intervals, guest_intervals] from
    active_intervals_by_lane - who is really talking, bleed already excluded.
    """
    if min_shot_seconds is None:
        min_shot_seconds = DEFAULT_MIN_SHOT_SECONDS
    if duration <= 0:
        return []

    host = list(active_by_lane[0]) if len(active_by_lane) > 0 else []
    guest = list(active_by_lane[1]) if len(active_by_lane) > 1 else []

    # Every instant where either state changes becomes a candidate boundary.
    edges = {0.0, float(duration)}
    for intervals in (host, guest):
        for start, end in intervals:
            edges.add(max(0.0, min(float(duration), start)))
            edges.add(max(0.0, min(float(duration), end)))
    bounds = sorted(edges)

    raw = []
    for a, b in zip(bounds, bounds[1:]):
        if b - a <= 0:
            continue
        middle = (a + b) / 2.0
        host_on = _covers(host, middle)
        guest_on = _covers(guest, middle)
        if host_on and not guest_on:
            camera = HOST
        elif guest_on and not host_on:
            camera = GUEST
        else:
            camera = BOTH          # talking together, or nobody talking
        raw.append((camera, a, b))

    return _enforce_minimum(_merge_runs(raw), min_shot_seconds)


def _covers(intervals, moment):
    for start, end in intervals:
        if start <= moment < end:
            return True
    return False


def _merge_runs(scenes):
    """Joins neighbouring blocks that are on the same camera."""
    merged = []
    for camera, start, end in scenes:
        if merged and merged[-1][0] == camera and abs(merged[-1][2] - start) < 1e-6:
            merged[-1] = (camera, merged[-1][1], end)
        else:
            merged.append((camera, start, end))
    return merged


def _enforce_minimum(scenes, min_shot_seconds):
    """
    Absorbs anything too short into the shot before it.

    Repeated until nothing changes: removing one short shot can leave its
    neighbours adjacent and on the same camera, which then merge into one and
    may reveal another short shot beside them.
    """
    if min_shot_seconds <= 0 or not scenes:
        return scenes

    while True:
        for index, (camera, start, end) in enumerate(scenes):
            if end - start >= min_shot_seconds or len(scenes) == 1:
                continue
            if index > 0:
                previous = scenes[index - 1]
                scenes[index - 1] = (previous[0], previous[1], end)
            else:
                following = scenes[1]
                scenes[1] = (following[0], start, following[2])
            del scenes[index]
            scenes = _merge_runs(scenes)
            break
        else:
            return scenes


# ------------------------------------------------------------- hand editing

def apply_scene_edits(scenes, edits):
    """
    Replays ordered hand edits over the automatic timeline; the latest wins.

    Assignment rather than add/remove, so this cannot reuse
    silence_detector.apply_range_edits. Edits are
    ("scene", camera, start, end), where camera None means "back to automatic"
    - recorded as an edit of its own rather than deleting history, so undo
    still steps back through it.
    """
    result = list(scenes)
    for edit in edits or []:
        try:
            _kind, camera, start, end = edit
        except (TypeError, ValueError):
            continue
        if end <= start:
            continue
        if camera is None:
            continue           # automatic already sits underneath
        result = _assign(result, int(camera), float(start), float(end))
    return _merge_runs(result)


def _assign(scenes, camera, start, end):
    """Forces `camera` over [start, end), splitting whatever was there."""
    out = []
    for existing, a, b in scenes:
        if b <= start or a >= end:
            out.append((existing, a, b))
            continue
        if a < start:
            out.append((existing, a, start))
        if b > end:
            out.append((existing, end, b))
    out.append((camera, start, end))
    out.sort(key=lambda s: s[1])
    return out


# --------------------------------------------------- what the renderer needs

def apply_to_keep_ranges(scenes, keep_ranges):
    """
    Clips the scene timeline to the surviving edit.

    A keep range routinely spans several shots, so this intersection - not the
    scenes and not the keep ranges alone - is what the video export consumes.
    Returns [(camera, start, end)] in timeline order.
    """
    pieces = []
    for keep_start, keep_end in keep_ranges:
        for camera, start, end in scenes:
            a = max(start, keep_start)
            b = min(end, keep_end)
            if b > a:
                pieces.append((camera, a, b))
    pieces.sort(key=lambda p: p[1])
    return pieces


def summarize(scenes):
    """Seconds on each camera, for the UI."""
    totals = {HOST: 0.0, GUEST: 0.0, BOTH: 0.0}
    for camera, start, end in scenes:
        totals[camera] = totals.get(camera, 0.0) + (end - start)
    return {"cuts": max(0, len(scenes) - 1),
            "host": totals[HOST], "guest": totals[GUEST], "both": totals[BOTH]}
