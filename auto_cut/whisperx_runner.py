"""
Runs WhisperX against a speaker's recording and returns word-level timestamps
plus the segment text, caching results on disk so re-runs (moving the
aggressiveness slider, reopening a project) don't re-transcribe.

Defaults are the settings proven on a 6GB card:
    --model large-v2 --batch_size 4 --compute_type int8
Lower `batch_size` first if the GPU runs out of memory, or use a smaller
model. Without a CUDA GPU everything falls back to the CPU automatically.
"""

import contextlib
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile

NL = chr(10)

def whisperx_executable():
    """
    Finds WhisperX: $AUTOCUT_WHISPERX first, otherwise whatever is on PATH.

    This used to be one hardcoded path into the author's virtualenv, which
    meant transcription could not work on anybody else's machine.
    """
    override = os.environ.get("AUTOCUT_WHISPERX")
    if override:
        return override
    found = shutil.which("whisperx")
    if found:
        return found
    raise RuntimeError(
        "WhisperX was not found." + NL + NL +
        "Install it so that `whisperx` is on your PATH (pip install whisperx), "
        "or set the AUTOCUT_WHISPERX environment variable to the full path of "
        "the whisperx executable." + NL + NL +
        "Transcription is optional - the cuts do not depend on it."
    )

CACHE_DIR = os.path.join(os.path.dirname(__file__), ".cache")

DEFAULT_MODEL = "large-v2"
DEFAULT_BATCH_SIZE = 4
DEFAULT_COMPUTE_TYPE = "int8"

_device_cache = None


def device():
    """
    "cuda" when an NVIDIA GPU is usable, otherwise "cpu".

    WhisperX defaults to CUDA and simply fails on a machine without it, which
    is most machines - so the device is now chosen explicitly.

    Do NOT decide this by importing torch. WhisperX usually lives in its own
    virtualenv, so the torch that matters is not the one this process can
    import: on the development machine (an RTX 3050) `import torch` fails here
    and would wrongly force everything onto the CPU. Asking the driver via
    nvidia-smi answers the question that actually matters - is there a usable
    NVIDIA GPU on this machine - regardless of which environment WhisperX runs
    in. Set AUTOCUT_DEVICE to override either way.

    Worked out once and remembered; nvidia-smi takes a moment.
    """
    global _device_cache
    if _device_cache is not None:
        return _device_cache

    forced = os.environ.get("AUTOCUT_DEVICE")
    if forced:
        _device_cache = forced
        return _device_cache

    _device_cache = "cuda" if _has_nvidia_gpu() else "cpu"
    return _device_cache


def _has_nvidia_gpu():
    if not shutil.which("nvidia-smi"):
        return False
    try:
        result = subprocess.run(
            ["nvidia-smi", "--query-gpu=name", "--format=csv,noheader"],
            capture_output=True, text=True, timeout=15,
        )
    except Exception:
        return False
    return result.returncode == 0 and bool(result.stdout.strip())


# Never use auto-detect: it was tried, guessed an unrelated language and
# produced garbage. Always pass a language explicitly.
DEFAULT_LANGUAGE = "tl"

# Every language Whisper transcribes. Filipino and English are pinned to the
# top as this project's daily case; the rest follow alphabetically.
#
# Whisper transcribes all of these, but WhisperX only ships wav2vec2 ALIGNMENT
# for a subset (`tl` among them). Without alignment the word timings are
# coarse. That used to matter enormously, because the cuts were derived from
# word timings - it no longer does, since cuts come from the waveform. Coarse
# timings now only make the karaoke highlight less precise, so nothing here is
# blocked.
LANGUAGES = [("Filipino", "tl"), ("English", "en")] + sorted([
    ("Afrikaans", "af"), ("Albanian", "sq"), ("Amharic", "am"),
    ("Arabic", "ar"), ("Armenian", "hy"), ("Assamese", "as"),
    ("Azerbaijani", "az"), ("Bashkir", "ba"), ("Basque", "eu"),
    ("Belarusian", "be"), ("Bengali", "bn"), ("Bosnian", "bs"),
    ("Breton", "br"), ("Bulgarian", "bg"), ("Burmese", "my"),
    ("Cantonese", "yue"), ("Catalan", "ca"), ("Chinese", "zh"),
    ("Croatian", "hr"), ("Czech", "cs"), ("Danish", "da"),
    ("Dutch", "nl"), ("Estonian", "et"), ("Faroese", "fo"),
    ("Finnish", "fi"), ("French", "fr"), ("Galician", "gl"),
    ("Georgian", "ka"), ("German", "de"), ("Greek", "el"),
    ("Gujarati", "gu"), ("Haitian Creole", "ht"), ("Hausa", "ha"),
    ("Hawaiian", "haw"), ("Hebrew", "he"), ("Hindi", "hi"),
    ("Hungarian", "hu"), ("Icelandic", "is"), ("Indonesian", "id"),
    ("Italian", "it"), ("Japanese", "ja"), ("Javanese", "jw"),
    ("Kannada", "kn"), ("Kazakh", "kk"), ("Khmer", "km"),
    ("Korean", "ko"), ("Lao", "lo"), ("Latin", "la"),
    ("Latvian", "lv"), ("Lingala", "ln"), ("Lithuanian", "lt"),
    ("Luxembourgish", "lb"), ("Macedonian", "mk"), ("Malagasy", "mg"),
    ("Malay", "ms"), ("Malayalam", "ml"), ("Maltese", "mt"),
    ("Maori", "mi"), ("Marathi", "mr"), ("Mongolian", "mn"),
    ("Nepali", "ne"), ("Norwegian", "no"), ("Norwegian Nynorsk", "nn"),
    ("Occitan", "oc"), ("Pashto", "ps"), ("Persian", "fa"),
    ("Polish", "pl"), ("Portuguese", "pt"), ("Punjabi", "pa"),
    ("Romanian", "ro"), ("Russian", "ru"), ("Sanskrit", "sa"),
    ("Serbian", "sr"), ("Shona", "sn"), ("Sindhi", "sd"),
    ("Sinhala", "si"), ("Slovak", "sk"), ("Slovenian", "sl"),
    ("Somali", "so"), ("Spanish", "es"), ("Sundanese", "su"),
    ("Swahili", "sw"), ("Swedish", "sv"), ("Tajik", "tg"),
    ("Tamil", "ta"), ("Tatar", "tt"), ("Telugu", "te"), ("Thai", "th"),
    ("Tibetan", "bo"), ("Turkish", "tr"), ("Turkmen", "tk"),
    ("Ukrainian", "uk"), ("Urdu", "ur"), ("Uzbek", "uz"),
    ("Vietnamese", "vi"), ("Welsh", "cy"), ("Yiddish", "yi"),
    ("Yoruba", "yo"),
])


def language_label(code):
    for label, value in LANGUAGES:
        if value == code:
            return label
    return code


def _cache_key(file_path, model, language, compute_type):
    stat = os.stat(file_path)
    # Model and language MUST be part of the key: without them, switching from
    # English to Filipino would silently hand back the previous transcript.
    raw = (f"{file_path}|{stat.st_size}|{stat.st_mtime}"
           f"|{model}|{language}|{compute_type}")
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()


def _cache_path(file_path, model, language, compute_type):
    os.makedirs(CACHE_DIR, exist_ok=True)
    key = _cache_key(file_path, model, language, compute_type)
    return os.path.join(CACHE_DIR, key + ".transcript.json")


def _extract(whisperx_json):
    """
    Flattens WhisperX output into {"words": [...], "segments": [...]}.
    Words drive the cutting; segments carry the readable text used by the
    transcript editor, correction pass and subtitle export.
    """
    words, segments = [], []
    for segment in whisperx_json.get("segments", []):
        seg_words = []
        for word in segment.get("words", []):
            start, end = word.get("start"), word.get("end")
            if start is None or end is None:
                # WhisperX drops timestamps on some punctuation-only tokens.
                continue
            entry = {"start": float(start), "end": float(end),
                     "text": word.get("word", "")}
            words.append(entry)
            seg_words.append(entry)

        text = (segment.get("text") or "").strip()
        if not text and seg_words:
            text = " ".join(w["text"] for w in seg_words).strip()
        if not text:
            continue

        start = segment.get("start")
        end = segment.get("end")
        if start is None and seg_words:
            start = seg_words[0]["start"]
        if end is None and seg_words:
            end = seg_words[-1]["end"]
        if start is None or end is None:
            continue

        segments.append({"start": float(start), "end": float(end), "text": text})

    return {"words": words, "segments": segments}


def transcribe(audio_path, model=DEFAULT_MODEL, language=DEFAULT_LANGUAGE,
               batch_size=DEFAULT_BATCH_SIZE, compute_type=None,
               force=False, progress=None):
    """
    Returns {"words": [{"start","end","text"}...], "segments": [...]} for the
    whole file, in seconds from the start of the recording.
    """
    dev = device()
    if compute_type is None:
        compute_type = DEFAULT_COMPUTE_TYPE
    cache_file = _cache_path(audio_path, model, language, compute_type)
    if not force and os.path.exists(cache_file):
        with open(cache_file, "r", encoding="utf-8") as f:
            cached = json.load(f)
        if isinstance(cached, dict) and "words" in cached:
            return cached

    if progress:
        progress(f"transcribing {os.path.basename(audio_path)} "
                 f"(WhisperX {model}, {language_label(language)}, {dev}, "
                 f"batch {batch_size}, {compute_type})")
        if dev == "cpu":
            progress("  no CUDA GPU found - running on the CPU, which is slow "
                     "for an hour-long track. A smaller model helps a lot.")

    with tempfile_dir() as out_dir:
        cmd = [
            whisperx_executable(), audio_path,
            "--model", model,
            "--device", dev,
            "--batch_size", str(batch_size),
            "--compute_type", compute_type,
            "--output_format", "json",
            "--output_dir", out_dir,
        ]
        if language:
            cmd += ["--language", language]

        # WhisperX prints transcript text to stdout as it goes. On Windows the
        # default cp1252 console encoding blows up (UnicodeEncodeError) the
        # moment a non-cp1252 character appears - which Filipino output will
        # contain - killing the run mid-file. Force UTF-8 on both ends.
        env = dict(os.environ, PYTHONIOENCODING="utf-8", PYTHONUTF8="1")
        result = subprocess.run(
            cmd, capture_output=True, text=True,
            encoding="utf-8", errors="replace", env=env,
        )
        if result.returncode != 0:
            tail = (result.stderr or result.stdout or "")[-1500:]
            hint = ""
            if "out of memory" in tail.lower():
                hint = ("\n\nThe GPU ran out of memory - lower the batch size, "
                        "or keep compute_type at int8.")
            raise RuntimeError(f"whisperx failed on {audio_path}:\n{tail}{hint}")

        base = os.path.splitext(os.path.basename(audio_path))[0]
        json_path = os.path.join(out_dir, base + ".json")
        if not os.path.exists(json_path):
            raise RuntimeError(f"whisperx did not produce expected output at {json_path}")

        with open(json_path, "r", encoding="utf-8") as f:
            whisperx_json = json.load(f)

    data = _extract(whisperx_json)
    with open(cache_file, "w", encoding="utf-8") as f:
        json.dump(data, f)
    return data


def transcribe_words(audio_path, **kwargs):
    """Just the word timings - what the cut logic consumes."""
    return transcribe(audio_path, **kwargs)["words"]


@contextlib.contextmanager
def tempfile_dir():
    d = tempfile.mkdtemp(prefix="autocut_whisperx_")
    try:
        yield d
    finally:
        # Left in place deliberately: if a run fails the JSON is worth
        # inspecting, and Windows cleans its own temp directory.
        pass


if __name__ == "__main__":
    # Manual smoke test: python whisperx_runner.py <media file> [language]
    path = sys.argv[1]
    lang = sys.argv[2] if len(sys.argv) > 2 else DEFAULT_LANGUAGE
    data = transcribe(path, language=lang, progress=print)
    print(f"{len(data['words'])} words, {len(data['segments'])} segments")
    for seg in data["segments"][:5]:
        print(f"  {seg['start']:7.2f} - {seg['end']:7.2f}  {seg['text'][:70]}")
