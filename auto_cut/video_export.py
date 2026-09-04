"""
Renders a finished video file, for people who do not use DaVinci Resolve.

The FCPXML export hands Resolve a timeline and lets it do the work. This does
the work itself: keeps only the ranges that survived the edit, and muxes them
against the audio Wavefield already rendered - cuts, mutes, effects and levels
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


def _filter_graph(segments, width, height, fps,
                  intro_kind=None, outro_kind=None, source_count=1):
    """
    trim/setpts per segment, concatenated - the standard way to cut a video at
    arbitrary points.

    `segments` is [(source_index, start, end)]. With one camera every segment
    names source 0 and this is a plain cut-and-join; for a vodcast the source
    index changes as the camera switches, and the only difference is which
    input each piece trims from.

    Every piece is conformed to the same size, rate and pixel format before
    concatenation - concat refuses inputs that disagree, and a V3 recorded at a
    different resolution is entirely normal.

    Only the picture is cut here. The audio comes from the WAV Wavefield
    rendered, which is already cut, muted and processed, so re-deriving it
    would both duplicate the work and risk the two drifting apart.

    `intro_kind` / `outro_kind` are None, "black" or "video". Intro and outro
    audio needs picture to sit against or everything after it drifts; a video
    bookend supplies its own, and anything else gets black.
    """
    parts = []

    def conform(source, label, trim=None):
        # Letterbox rather than stretch: a camera framed differently should
        # keep its shape rather than be squashed to fit.
        chain = f"[{source}:v]"
        if trim is not None:
            chain += f"trim=start={trim[0]:.6f}:end={trim[1]:.6f},"
        chain += (f"scale={width}:{height}:force_original_aspect_ratio=decrease,"
                  f"pad={width}:{height}:-1:-1:color=black,fps={fps},setsar=1,"
                  f"format=yuv420p,setpts=PTS-STARTPTS[{label}]")
        return chain

    # Bookends come in after the video sources and the audio.
    bookend_input = source_count + 1

    labels = []
    if intro_kind:
        parts.append(conform(bookend_input, "intro"))
        labels.append("[intro]")
        bookend_input += 1

    for i, (source, start, end) in enumerate(segments):
        parts.append(conform(source, f"v{i}", trim=(start, end)))
        labels.append(f"[v{i}]")

    if outro_kind:
        parts.append(conform(bookend_input, "outro"))
        labels.append("[outro]")

    parts.append(f"{''.join(labels)}concat=n={len(labels)}:v=1:a=0[outv]")
    return ";".join(parts)


def _bookend_input(path, seconds, width, height, fps):
    """
    ffmpeg input arguments for one bookend, and what kind it turned out to be.

    A video bookend contributes its own picture; audio-only gets black of the
    same length.
    """
    if seconds <= 0:
        return [], None
    if path:
        try:
            info = probe(path)
            if info.has_video:
                # Trimmed to the audio length so picture and sound agree even
                # if the file is slightly longer.
                return (["-t", f"{seconds:.6f}", "-i", path], "video")
        except Exception:
            pass                         # unreadable: fall through to black
    return (["-f", "lavfi", "-t", f"{seconds:.6f}",
             "-i", f"color=black:s={width}x{height}:r={fps}"], "black")


def render(video_path, audio_path, out_path, keep_ranges, crf=DEFAULT_CRF,
           use_gpu=None, progress=None, should_cancel=None,
           intro_seconds=0.0, outro_seconds=0.0,
           intro_path=None, outro_path=None,
           segments=None, sources=None):
    """
    Writes `out_path` from `video_path`'s picture and `audio_path`'s sound.

    For a vodcast, pass `sources` (the camera files, V1/V2/V3) and `segments`
    ([(camera_index, start, end)] from scenes.apply_to_keep_ranges); the cut
    then moves between cameras. Without them every segment comes from
    `video_path` and this is an ordinary single-camera export.

    V3 is only ever a picture source - its audio is the same two voices again
    and is never opened.

    `audio_path` is expected to already include any intro and outro; pass their
    durations so matching black can be put in front of and after the picture.

    progress(fraction, message) is called as ffmpeg reports its position.
    should_cancel() is polled; returning True stops the render and removes the
    partial file.
    """
    if segments is None:
        segments = [(0, start, end) for start, end in keep_ranges]
    if not segments:
        raise ValueError("Nothing to export - no segments survived the edit.")
    if not sources:
        sources = [video_path]

    # The first camera sets the format everything else is conformed to.
    info = probe(sources[0])
    total = (sum(end - start for _source, start, end in segments)
             + intro_seconds + outro_seconds)
    if use_gpu is None:
        use_gpu = has_nvenc()

    # NVENC needs a rate-control mode named explicitly; -cq on its own is
    # rejected with "Invalid argument" and no useful explanation.
    gpu_codec = ["-c:v", "h264_nvenc", "-preset", "p4",
                 "-rc", "vbr", "-cq", str(crf), "-b:v", "0"]
    cpu_codec = ["-c:v", "libx264", "-preset", "medium", "-crf", str(crf)]
    video_codec = gpu_codec if use_gpu else cpu_codec

    rate = f"{float(info.fps):.6f}"
    intro_args, intro_kind = _bookend_input(intro_path, intro_seconds,
                                            info.width, info.height, rate)
    outro_args, outro_kind = _bookend_input(outro_path, outro_seconds,
                                            info.width, info.height, rate)
    if progress and (intro_kind == "video" or outro_kind == "video"):
        progress(0.0, "using the picture from your intro/outro")

    source_args = []
    for source in sources:
        source_args += ["-i", source]

    cmd = [
        FFMPEG, "-y", "-hide_banner",
        *source_args,
        "-i", audio_path,
        *intro_args, *outro_args,
        "-filter_complex", _filter_graph(segments, info.width, info.height,
                                         rate, intro_kind, outro_kind,
                                         source_count=len(sources)),
        "-map", "[outv]", "-map", f"{len(sources)}:a:0",
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
                          should_cancel=should_cancel,
                          intro_seconds=intro_seconds,
                          outro_seconds=outro_seconds,
                          intro_path=intro_path, outro_path=outro_path,
                          segments=segments, sources=sources)
        raise RuntimeError("ffmpeg could not write the video:" + NL + NL
                           + "".join(tail[-12:]))
    return out_path
