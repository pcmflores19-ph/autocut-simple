"""
Reads frame rate, resolution and duration out of a media file via ffprobe,
so the generated FCPXML matches the real source media.
"""

import json
import subprocess
from fractions import Fraction

import bundled

FFPROBE = bundled.tool("ffprobe")


class MediaInfo:
    def __init__(self, path, fps, width, height, duration_seconds, has_audio,
                 audio_channels=1):
        self.path = path
        self.fps = fps  # Fraction, e.g. Fraction(30000, 1001)
        self.width = width
        self.height = height
        self.duration_seconds = duration_seconds
        self.has_audio = has_audio
        self.audio_channels = audio_channels

    @property
    def fps_float(self):
        return float(self.fps)

    def __repr__(self):
        return (f"MediaInfo({self.path!r}, {self.fps} fps, {self.width}x{self.height}, "
                f"{self.duration_seconds:.2f}s, audio={self.has_audio})")


def probe(path):
    cmd = [
        FFPROBE, "-v", "error",
        "-print_format", "json",
        "-show_streams", "-show_format",
        path,
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(f"ffprobe failed on {path}:\n{result.stderr}")

    data = json.loads(result.stdout)
    streams = data.get("streams", [])

    video = next((s for s in streams if s.get("codec_type") == "video"), None)
    if video is None:
        raise RuntimeError(f"No video stream found in {path}")
    audio = next((s for s in streams if s.get("codec_type") == "audio"), None)
    has_audio = audio is not None
    # Declared in the FCPXML: telling Resolve a mono source is stereo made it
    # allocate extra audio tracks on import.
    audio_channels = int(audio.get("channels", 1)) if audio else 1

    # r_frame_rate is the real (not average) rate, e.g. "30000/1001"
    fps = Fraction(video.get("r_frame_rate", "30/1"))
    if fps <= 0:
        raise RuntimeError(f"Could not determine frame rate for {path}")

    width = int(video.get("width", 1920))
    height = int(video.get("height", 1080))

    duration = video.get("duration") or data.get("format", {}).get("duration")
    if duration is None:
        raise RuntimeError(f"Could not determine duration for {path}")

    return MediaInfo(path, fps, width, height, float(duration), has_audio,
                     audio_channels=audio_channels)
