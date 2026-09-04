"""
Renders a finished video file, for people who do not use DaVinci Resolve.

The FCPXML export hands Resolve a timeline and lets it do the work. This does
the work itself: keeps only the ranges that survived the edit, and muxes them
against the audio Auto-Cut already rendered - cuts, mutes, effects and levels
included.

The video HAS to be re-encoded. Cuts land wherever the speech stops, which is
almost never on a keyframe, and a stream copy can only cut on keyframes - it
would drift by up to several seconds per cut.
"""

import os
import re
import subprocess

import bundled
from media_probe import probe

FFMPEG = bundled.tool("ffmpeg")
NL = chr(10)

# Constant Rate Factor. 20 is visually near-identical to a typical screen or
# webcam recording while roughly halving the size; lower is bigger and better.
DEFAULT_CRF = 20


_nvenc_cache = None


def has_nvenc():
    """
    Whether NVIDIA hardware encoding actually WORKS here.

    Listing the encoders is not enough - it only says NVENC was compiled in.
    On this development machine ffmpeg lists h264_nvenc and then fails with
    "Driver does not support the required nvenc API version. Required: 13.1
    Found: 13.0", because the bundled ffmpeg is newer than the installed
    driver. The only reliable test is to encode something.

    So: two frames of black, to nowhere. Costs a fraction of a second, once.
    """
    global _nvenc_cache
    if _nvenc_cache is not None:
        return _nvenc_cache
    try:
        result = subprocess.run(
            [FFMPEG, "-hide_banner", "-f", "lavfi",
             "-i", "color=black:s=256x256:d=0.1",
             "-c:v", "h264_nvenc", "-f", "null", "-"],
            capture_output=True, text=True, timeout=60)
        _nvenc_cache = result.returncode == 0
    except Exception:
        _nvenc_cache = False
    return _nvenc_cache


def _filter_graph(keep_ranges, fps):
    """
    trim/setpts per keep range, concatenated - the standard way to cut a video
    at arbitrary points.

    Only the video is cut here. The audio comes from the WAV Auto-Cut rendered,
    which is already cut, muted and processed, so re-deriving it here would
    both duplicate the work and risk the two drifting apart.
    """
    parts = []
    for i, (start, end) in enumerate(keep_ranges):
        parts.append(
            f"[0:v]trim=start={start:.6f}:end={end:.6f},"
            f"setpts=PTS-STARTPTS[v{i}]")
    joined = "".join(f"[v{i}]" for i in range(len(keep_ranges)))
    parts.append(f"{joined}concat=n={len(keep_ranges)}:v=1:a=0[outv]")
    return ";".join(parts)


def render(video_path, audio_path, out_path, keep_ranges, crf=DEFAULT_CRF,
           use_gpu=None, progress=None, should_cancel=None):
    """
    Writes `out_path` from `video_path`'s picture and `audio_path`'s sound.

    progress(fraction, message) is called as ffmpeg reports its position.
    should_cancel() is polled; returning True stops the render and removes the
    partial file.
    """
    if not keep_ranges:
        raise ValueError("Nothing to export - no segments survived the edit.")

    info = probe(video_path)
    total = sum(end - start for start, end in keep_ranges)
    if use_gpu is None:
        use_gpu = has_nvenc()

    # NVENC needs a rate-control mode named explicitly; -cq on its own is
    # rejected with "Invalid argument" and no useful explanation.
    gpu_codec = ["-c:v", "h264_nvenc", "-preset", "p4",
                 "-rc", "vbr", "-cq", str(crf), "-b:v", "0"]
    cpu_codec = ["-c:v", "libx264", "-preset", "medium", "-crf", str(crf)]
    video_codec = gpu_codec if use_gpu else cpu_codec

    cmd = [
        FFMPEG, "-y", "-hide_banner",
        "-i", video_path,
        "-i", audio_path,
        "-filter_complex", _filter_graph(keep_ranges, info.fps),
        "-map", "[outv]", "-map", "1:a:0",
        *video_codec,
        "-pix_fmt", "yuv420p",          # anything else will not play everywhere
        "-c:a", "aac", "-b:a", "192k",
        "-movflags", "+faststart",      # so it starts playing before it loads
        out_path,
    ]

    if progress:
        progress(0.0, f"encoding with {'GPU' if use_gpu else 'CPU'} "
                      f"({total / 60:.1f} min of video)")

    process = subprocess.Popen(cmd, stdout=subprocess.DEVNULL,
                               stderr=subprocess.PIPE, text=True,
                               encoding="utf-8", errors="replace", bufsize=1)
    tail = []
    time_pattern = re.compile(r"time=(\d+):(\d+):(\d+\.?\d*)")
    try:
        for line in process.stderr:
            tail.append(line)
            del tail[:-40]              # keep only enough to explain a failure
            if should_cancel and should_cancel():
                process.terminate()
                process.wait(timeout=10)
                if os.path.exists(out_path):
                    try:
                        os.remove(out_path)
                    except OSError:
                        pass
                return None
            match = time_pattern.search(line)
            if match and progress and total > 0:
                hours, minutes, seconds = match.groups()
                done = int(hours) * 3600 + int(minutes) * 60 + float(seconds)
                progress(min(1.0, done / total),
                         f"{done / 60:.1f} of {total / 60:.1f} min")
        process.wait()
    finally:
        if process.poll() is None:
            process.kill()

    if process.returncode != 0:
        message = "".join(tail)
        # A GPU encode can still fail after passing the probe - a driver
        # update mid-session, another program holding the encoder. The CPU
        # path is slower but always works, and is far better than handing
        # someone an ffmpeg backtrace.
        if use_gpu and "nvenc" in message.lower():
            if progress:
                progress(0.0, "GPU encoder unavailable - encoding on the "
                              "processor instead (slower)")
            return render(video_path, audio_path, out_path, keep_ranges,
                          crf=crf, use_gpu=False, progress=progress,
                          should_cancel=should_cancel)
        raise RuntimeError("ffmpeg could not write the video:" + NL + NL
                           + "".join(tail[-12:]))
    return out_path
