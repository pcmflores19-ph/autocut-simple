"""
Writes the transcript alongside every export.

The important part is the remapping: transcript timings are in SOURCE time, but
the exported edit has had dead air removed, so subtitles written against source
time would drift further out of sync with every cut. Everything here is
projected through the keep ranges into edited-timeline time first.

Segments spanning a cut are split at the cut, so a subtitle never covers a
moment that no longer exists.
"""

import os


def build_time_map(keep_ranges):
    """
    [(src_start, src_end, edited_start)] - enough to convert any source time
    that survives the edit into its position on the exported timeline.
    """
    mapping = []
    cursor = 0.0
    for start, end in keep_ranges:
        mapping.append((start, end, cursor))
        cursor += end - start
    return mapping


def remap_segments(segments, keep_ranges):
    """
    Projects segments into edited time, splitting any that straddle a cut and
    dropping anything that falls entirely inside removed audio.
    """
    time_map = build_time_map(keep_ranges)
    out = []
    for segment in segments:
        seg_start = float(segment.get("start", 0.0))
        seg_end = float(segment.get("end", 0.0))
        if seg_end <= seg_start:
            continue
        for src_start, src_end, edited_start in time_map:
            overlap_start = max(seg_start, src_start)
            overlap_end = min(seg_end, src_end)
            if overlap_end <= overlap_start:
                continue
            out.append({
                "start": edited_start + (overlap_start - src_start),
                "end": edited_start + (overlap_end - src_start),
                "text": segment.get("text", "").strip(),
                "speaker": segment.get("speaker"),
            })
    out.sort(key=lambda s: s["start"])
    return out


def _timestamp(seconds, comma=True):
    if seconds < 0:
        seconds = 0.0
    hours, rest = divmod(seconds, 3600)
    minutes, secs = divmod(rest, 60)
    whole = int(secs)
    millis = int(round((secs - whole) * 1000))
    if millis == 1000:      # rounding can tip a whole second
        whole += 1
        millis = 0
    sep = "," if comma else "."
    return f"{int(hours):02d}:{int(minutes):02d}:{whole:02d}{sep}{millis:03d}"


def write_srt(path, segments):
    with open(path, "w", encoding="utf-8") as f:
        for index, segment in enumerate(segments, start=1):
            if not segment["text"]:
                continue
            f.write(f"{index}\n")
            f.write(f"{_timestamp(segment['start'])} --> {_timestamp(segment['end'])}\n")
            speaker = segment.get("speaker")
            prefix = f"[{speaker}] " if speaker else ""
            f.write(f"{prefix}{segment['text']}\n\n")
    return path


def write_vtt(path, segments):
    with open(path, "w", encoding="utf-8") as f:
        f.write("WEBVTT\n\n")
        for segment in segments:
            if not segment["text"]:
                continue
            f.write(f"{_timestamp(segment['start'], comma=False)} --> "
                    f"{_timestamp(segment['end'], comma=False)}\n")
            speaker = segment.get("speaker")
            prefix = f"<v {speaker}>" if speaker else ""
            f.write(f"{prefix}{segment['text']}\n\n")
    return path


def write_txt(path, segments):
    """Readable transcript - timestamped lines, for show notes and reference."""
    with open(path, "w", encoding="utf-8") as f:
        for segment in segments:
            if not segment["text"]:
                continue
            stamp = _timestamp(segment["start"]).split(",")[0]
            speaker = segment.get("speaker")
            who = f"{speaker}: " if speaker else ""
            f.write(f"[{stamp}] {who}{segment['text']}\n")
    return path


def export_alongside(export_path, segments, keep_ranges, formats=("srt", "vtt", "txt")):
    """
    Writes the transcript next to whatever was just exported, sharing its name.
    Returns the list of files written.
    """
    remapped = remap_segments(segments, keep_ranges)
    base = os.path.splitext(export_path)[0]
    writers = {"srt": write_srt, "vtt": write_vtt, "txt": write_txt}

    written = []
    for fmt in formats:
        writer = writers.get(fmt)
        if writer is None:
            continue
        written.append(writer(f"{base}.{fmt}", remapped))
    return written
