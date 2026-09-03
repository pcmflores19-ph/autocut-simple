#!/usr/bin/env python
"""
Headless run: find the cuts from the waveforms and write the FCPXML.
Handy when you'd rather not click through the GUI, or for batching episodes.

  python run_episode.py <host_file> <guest_file> [...] --out timeline.fcpxml [--aggressiveness 50]

No transcription happens here. The cuts are measured from the audio itself, so
this needs neither WhisperX nor a GPU - only ffmpeg.
"""

import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import voice_activity
from fcpxml_writer import write_fcpxml
from media_probe import probe
from silence_detector import compute_keep_ranges_from_intervals, summarize


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("files", nargs="+", help="speaker recordings, host first")
    parser.add_argument("--out", required=True, help="output .fcpxml path")
    parser.add_argument("--aggressiveness", type=int, default=50,
                        help="0 (cuts pauses over 3.0s) - 100 (over 0.25s)")
    args = parser.parse_args()

    media = []
    for path in args.files:
        info = probe(path)
        print(f"[probe] {os.path.basename(path)}: {info.width}x{info.height} "
              f"@{float(info.fps):.3f}fps {info.duration_seconds / 60:.1f}min", flush=True)
        media.append(info)

    duration = max(m.duration_seconds for m in media)

    denoiser = voice_activity.find_denoiser()
    if not denoiser:
        print("[speech] rnnoise not found - detecting on the raw waveform, "
              "which is less exact on a noisy room", flush=True)

    speech = []
    for path in args.files:
        speech.append(voice_activity.speaking_intervals(
            path, denoiser, duration=duration,
            log=lambda m: print(f"[speech]{m}", flush=True)))

    keep_ranges, gaps = compute_keep_ranges_from_intervals(
        speech, 0.0, duration, args.aggressiveness)
    stats = summarize(gaps, keep_ranges)
    print(f"[cuts] {stats}", flush=True)
    print(f"[cuts] {duration / 60:.1f}min -> "
          f"{(duration - stats['seconds_removed']) / 60:.1f}min", flush=True)

    write_fcpxml(args.out, media, keep_ranges)
    print(f"[done] wrote {args.out}", flush=True)


if __name__ == "__main__":
    main()
