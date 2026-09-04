"""
Writes an FCPXML timeline containing only the "keep" ranges, for importing
into DaVinci Resolve (File > Import > Timeline > ...).

The first speaker goes in the primary storyline and lands on V1/A1. Every
other speaker is a connected clip on lane N, landing on V(N+1)/A(N+1). Two
speakers therefore import as exactly two video and two audio tracks.

An earlier version hung all speakers off a base <gap> instead, because putting
a speaker in the primary storyline had made Resolve splinter that speaker's
audio across extra tracks. That gap then occupied the primary storyline and
showed up as an empty V1. The scattering turned out to have two causes, both
since fixed: the assets declared audioChannels="2" for what are mono
recordings, and every speaker shared one generic "dialogue" role, so Resolve
could not tell whose audio was whose once the timeline fragmented into many
cut segments. With honest mono and a unique role per speaker, the storyline
structure imports cleanly and there is no empty track.

Host and guest are split on the UNION of both their mute boundaries, so their
pieces line up one to one and each guest piece can hang off the host piece it
sits over. A connected clip's offset is measured in its parent clip's local
time, which is why those offsets equal the source start rather than the
position on the timeline.

FCPXML expresses time as exact rationals (e.g. "1001/30000s"), so everything
here is computed in whole frames to avoid drift.
"""

import os
from fractions import Fraction
from xml.sax.saxutils import escape

FCPXML_VERSION = "1.8"

NL = chr(10)


def _time_str(frames, fps):
    """
    Rational time string for a whole number of frames at the given fps.
    fps is a Fraction, e.g. Fraction(30000, 1001) -> N frames is
    N * 1001/30000 seconds.
    """
    if frames == 0:
        return "0s"
    numerator = frames * fps.denominator
    denominator = fps.numerator
    common = Fraction(numerator, denominator)
    if common.denominator == 1:
        return f"{common.numerator}s"
    return f"{common.numerator}/{common.denominator}s"


def _frame_duration_str(fps):
    return _time_str(1, fps)


def _file_url(path):
    abs_path = os.path.abspath(path).replace("\\", "/")
    if not abs_path.startswith("/"):
        abs_path = "/" + abs_path
    from urllib.parse import quote
    # Keep the Windows drive colon literal (file:///C:/...) - Resolve fails to
    # relink media if it's percent-encoded as C%3A.
    return "file://" + quote(abs_path, safe="/:")


def _format_name(width, height, fps):
    fps_label = round(float(fps), 2)
    if float(fps).is_integer():
        fps_label = int(float(fps))
    return f"FFVideoFormat{height}p{fps_label}"


def _speaker_roles(speaker_media):
    """
    Assigns each speaker a distinct FCPXML audio subrole (e.g. "dialogue.host",
    "dialogue.guest2") derived from their filename. Resolve groups clips onto
    audio tracks by role - giving every speaker's clips the same generic
    "dialogue" role (as v1 did) left Resolve unable to tell whose audio was
    whose once the timeline fragmented into many cut segments, so it scattered
    them across tracks unpredictably. A unique role per speaker keeps each
    speaker on their own dedicated, contiguous audio track.
    """
    used = set()
    roles = []
    for media in speaker_media:
        base = os.path.splitext(os.path.basename(media.path))[0].lower()
        token = "".join(c for c in base if c.isalnum()) or "speaker"
        role = token
        n = 2
        while role in used:
            role = f"{token}{n}"
            n += 1
        used.add(role)
        roles.append(f"dialogue.{role}")
    return roles


def _aligned_pieces(seg_start_f, seg_end_f, mutes_by_speaker, speaker_count):
    """
    Splits a source frame range on EVERY speaker's mute boundaries at once,
    returning [(from_frame, to_frame, [muted_per_speaker]), ...].

    Splitting each speaker independently would give them different boundaries,
    and a connected clip has to hang off the storyline clip it overlaps - so
    the pieces have to line up.
    """
    cuts = set()
    for index in range(speaker_count):
        for m_start, m_end in mutes_by_speaker.get(index, []):
            if m_end > seg_start_f and m_start < seg_end_f:
                cuts.add(max(m_start, seg_start_f))
                cuts.add(min(m_end, seg_end_f))
    bounds = sorted({seg_start_f, seg_end_f} | cuts)

    pieces = []
    for a, b in zip(bounds, bounds[1:]):
        if b <= a:
            continue
        mid = (a + b) / 2
        muted = [any(m_start <= mid < m_end
                     for m_start, m_end in mutes_by_speaker.get(i, []))
                 for i in range(speaker_count)]
        pieces.append((a, b, muted))
    return pieces


def _split_on_mutes(seg_start_f, seg_end_f, mute_frames):
    """
    Splits a clip's source frame range on any muted spans, returning
    [(from_frame, to_frame, is_muted), ...] covering the whole range in order.
    """
    cuts = set()
    for m_start, m_end in mute_frames:
        if m_end > seg_start_f and m_start < seg_end_f:
            cuts.add(max(m_start, seg_start_f))
            cuts.add(min(m_end, seg_end_f))
    bounds = sorted({seg_start_f, seg_end_f} | cuts)

    pieces = []
    for a, b in zip(bounds, bounds[1:]):
        if b <= a:
            continue
        mid = (a + b) / 2
        muted = any(m_start <= mid < m_end for m_start, m_end in mute_frames)
        pieces.append((a, b, muted))
    return pieces


def build_fcpxml(speaker_media, keep_ranges, project_name="Podcast (Wavefield)",
                 mutes=None):
    """
    speaker_media: list of MediaInfo (from media_probe.probe), speaker 1 first.
                   Their timelines are assumed to start together at 0.
    keep_ranges:   list of (start_seconds, end_seconds) in timeline time.
    mutes:         optional [(speaker_index, start_seconds, end_seconds)] -
                   those stretches are emitted as silenced sub-clips.
    Returns the FCPXML document as a string.
    """
    if not speaker_media:
        raise ValueError("Need at least one speaker's media to build a timeline.")

    # The sequence format follows the first speaker.
    base = speaker_media[0]
    fps = base.fps
    frame_dur = _frame_duration_str(fps)

    resources = []
    resources.append(
        f'    <format id="r0" name="{_format_name(base.width, base.height, fps)}" '
        f'frameDuration="{frame_dur}" width="{base.width}" height="{base.height}" '
        f'colorSpace="1-1-1 (Rec. 709)"/>'
    )

    asset_ids = {}
    for i, media in enumerate(speaker_media, start=1):
        asset_id = f"r{i}"
        asset_ids[media.path] = asset_id
        total_frames = int(round(media.duration_seconds * float(media.fps)))
        name = escape(os.path.splitext(os.path.basename(media.path))[0])
        resources.append(
            f'    <asset id="{asset_id}" name="{name}" src="{_file_url(media.path)}" '
            f'start="0s" duration="{_time_str(total_frames, fps)}" '
            f'hasVideo="1" format="r0" '
            f'hasAudio="{1 if media.has_audio else 0}" '
            f'audioSources="{1 if media.has_audio else 0}" '
            f'audioChannels="{getattr(media, "audio_channels", 1) or 1}"/>'
        )

    roles = _speaker_roles(speaker_media)

    # Muted spans, per speaker, in source frames.
    mute_frames_by_speaker = {}
    for speaker_index, m_start, m_end in (mutes or []):
        mute_frames_by_speaker.setdefault(speaker_index, []).append(
            (int(round(m_start * float(fps))), int(round(m_end * float(fps))))
        )

    # Convert keep ranges to whole frames and lay them end to end on the
    # timeline; each keeps its own source in-point. Speaker 0 forms the primary
    # storyline, everyone else hangs off it on a lane (see module docstring).
    spine_entries = []
    timeline_cursor_frames = 0

    def clip_xml(indent, media, lane, offset_f, start_f, dur_f, muted,
                 role, children=""):
        name = escape(os.path.splitext(os.path.basename(media.path))[0])
        lane_attr = f'lane="{lane}" ' if lane else ""
        attrs = (
            f'ref="{asset_ids[media.path]}" {lane_attr}'
            f'offset="{_time_str(offset_f, fps)}" name="{name}" '
            f'start="{_time_str(start_f, fps)}" '
            f'duration="{_time_str(dur_f, fps)}" '
            f'format="r0" audioRole="{role}"'
        )
        inner = ""
        if muted:
            inner += NL + f'{indent}  <adjust-volume amount="-96dB"/>'
        inner += children
        if inner:
            return (f'{indent}<asset-clip {attrs}>{inner}' + NL +
                    f'{indent}</asset-clip>')
        return f'{indent}<asset-clip {attrs}/>'

    for start_s, end_s in keep_ranges:
        src_start_frames = int(round(start_s * float(fps)))
        src_end_frames = int(round(end_s * float(fps)))
        if src_end_frames - src_start_frames <= 0:
            continue

        pieces = _aligned_pieces(src_start_frames, src_end_frames,
                                 mute_frames_by_speaker, len(speaker_media))

        for piece_start, piece_end, muted in pieces:
            piece_dur = piece_end - piece_start
            piece_offset = timeline_cursor_frames + (piece_start - src_start_frames)

            # Connected clips are positioned in the parent clip's own local
            # time, whose origin is the parent's start attribute - so they take
            # the source start, not the timeline offset.
            connected = ""
            for lane, media in enumerate(speaker_media[1:], start=1):
                connected += NL + clip_xml(
                    "                ", media, lane, piece_start, piece_start,
                    piece_dur, muted[lane], roles[lane])

            spine_entries.append(clip_xml(
                "            ", speaker_media[0], 0, piece_offset, piece_start,
                piece_dur, muted[0], roles[0], children=connected))

        timeline_cursor_frames += src_end_frames - src_start_frames

    sequence_duration = _time_str(timeline_cursor_frames, fps)
    spine_body = NL.join(spine_entries)

    return f"""<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE fcpxml>
<fcpxml version="{FCPXML_VERSION}">
  <resources>
{chr(10).join(resources)}
  </resources>
  <library>
    <event name="Wavefield">
      <project name="{escape(project_name)}">
        <sequence format="r0" duration="{sequence_duration}" tcStart="0s" tcFormat="NDF" audioLayout="mono" audioRate="48kHz">
          <spine>
{spine_body}
          </spine>
        </sequence>
      </project>
    </event>
  </library>
</fcpxml>
"""


def write_fcpxml(path, speaker_media, keep_ranges, project_name="Podcast (Wavefield)",
                 mutes=None):
    xml = build_fcpxml(speaker_media, keep_ranges, project_name, mutes=mutes)
    with open(path, "w", encoding="utf-8") as f:
        f.write(xml)
    return path



