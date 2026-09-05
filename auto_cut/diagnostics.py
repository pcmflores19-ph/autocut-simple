"""
Builds the file someone sends when Wavefield misbehaves.

The problems that actually reach us are environmental - a driver too old for
the bundled ffmpeg, a WhisperX whose torch has no CUDA, a plugin that kills the
interpreter outright - and every one of them is invisible in a description like
"it didn't work". This gathers the handful of facts that would otherwise take a
dozen messages to establish.

Two rules it follows:

  Never fail. A diagnostic report that raises while collecting diagnostics is
  worse than useless, so every probe is wrapped and missing information is
  recorded as a line saying so.

  Never include a full path from the user's disk. Recording names is enough to
  work out what went wrong, and this file is written to be emailed to a
  stranger - real paths carry the person's name, employer and folder layout.
  Only basenames go in, and the one place a full path is genuinely needed (the
  WhisperX location, which is the thing most likely to be wrong) is included
  deliberately because it cannot be diagnosed otherwise.
"""

import os
import platform
import subprocess
import sys
import time

import bundled
import settings
import version

NL = chr(10)


def _run(command, timeout=15):
    """First line of a command's output, or a note explaining its absence."""
    try:
        result = subprocess.run(command, capture_output=True, text=True,
                                timeout=timeout,
                                creationflags=getattr(subprocess,
                                                      "CREATE_NO_WINDOW", 0))
    except FileNotFoundError:
        return "not found"
    except subprocess.TimeoutExpired:
        return f"timed out after {timeout}s"
    except Exception as exc:
        return f"could not run ({exc})"
    text = (result.stdout or result.stderr or "").strip()
    return text.splitlines()[0] if text else f"no output (exit {result.returncode})"


def _section(title):
    return NL + title + NL + "-" * len(title)


def _app_lines():
    lines = [f"{version.APP_NAME} {version.__version__}",
             f"frozen build: {bundled.frozen()}"]
    return lines


def _system_lines():
    return [
        f"os        : {platform.platform()}",
        f"machine   : {platform.machine()}",
        f"python    : {sys.version.split()[0]}",
    ]


def _gpu_lines():
    out = _run(["nvidia-smi",
                "--query-gpu=name,driver_version,memory.total",
                "--format=csv,noheader"])
    return [f"nvidia-smi: {out}"]


def _tool_lines():
    lines = []
    for name in ("ffmpeg", "ffprobe"):
        path = bundled.tool(name)
        # Whether it is the bundled copy or one from PATH is exactly the
        # distinction that explains "works on my machine".
        which = "bundled" if os.path.isabs(path) else "from PATH"
        lines.append(f"{name:9}: {_run([path, '-version'])}  ({which})")
    return lines


def _whisperx_lines():
    lines = []
    configured = settings.get("whisperx_path") or "(not set - searched for)"
    lines.append(f"configured: {configured}")
    try:
        import whisperx_runner
        path, has_cuda = whisperx_runner.resolve()
        lines.append(f"found     : {path or 'nothing found'}")
        lines.append(f"can use GPU: {has_cuda}")
        lines.append(f"device    : {whisperx_runner.device()}")
    except Exception as exc:
        lines.append(f"lookup failed: {exc}")
    return lines


def _package_lines():
    lines = []
    for name in ("numpy", "sounddevice", "pedalboard"):
        try:
            module = __import__(name)
            lines.append(f"{name:12}: {getattr(module, '__version__', 'unknown')}")
        except Exception as exc:
            lines.append(f"{name:12}: not importable ({exc})")
    return lines


def _project_lines(app):
    """
    What the session was doing - names only, never full paths.
    """
    lines = []
    try:
        paths = getattr(app, "speaker_paths", []) or []
        lines.append(f"recordings loaded: {len(paths)}")
        for index, path in enumerate(paths):
            lines.append(f"  {index + 1}. {os.path.basename(path)}")
        media = getattr(app, "speaker_media", None) or []
        for index, info in enumerate(media):
            lines.append(f"  {index + 1}. {info.duration_seconds:.1f}s, "
                         f"video={info.has_video}")
        lines.append(f"timeline duration: {getattr(app, 'timeline_duration', 0):.1f}s")
        lines.append(f"transcript segments: "
                     f"{len((getattr(app, 'transcript', None) or {}).get('segments', []))}")
        lines.append(f"camera switching: {_var(app, 'scene_switching')}")
        lines.append(f"auto-cut: {_var(app, 'auto_cut_on')}  "
                     f"auto-mute: {_var(app, 'auto_mute_on')}")
    except Exception as exc:
        lines.append(f"could not read session state: {exc}")
    return lines


def _var(app, name):
    try:
        return getattr(app, name).get()
    except Exception:
        return "unknown"


def _log_lines(app, limit=400):
    try:
        text = app.log_text.get("1.0", "end").strip()
    except Exception as exc:
        return [f"could not read the log ({exc})"]
    if not text:
        return ["(empty)"]
    lines = text.splitlines()
    if len(lines) > limit:
        lines = [f"... {len(lines) - limit} earlier lines omitted ..."] + lines[-limit:]
    return lines


def _crash_lines(limit=120):
    """
    The tail of the native crash log, which is the whole reason it exists.
    """
    path = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                        "autocut_crash.log")
    if not os.path.exists(path):
        return ["(no crash log - the app has not died unexpectedly)"]
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as handle:
            lines = handle.read().splitlines()
    except Exception as exc:
        return [f"could not read the crash log ({exc})"]
    if not lines:
        return ["(crash log is empty)"]
    return lines[-limit:]


def summary(app=None):
    """The whole report as one string."""
    parts = []
    parts.append(f"{version.APP_NAME} problem report")
    parts.append(time.strftime("%Y-%m-%d %H:%M:%S"))

    for title, lines in (
            ("Application", _app_lines()),
            ("System", _system_lines()),
            ("Graphics", _gpu_lines()),
            ("Bundled tools", _tool_lines()),
            ("Speech recognition", _whisperx_lines()),
            ("Python packages", _package_lines()),
    ):
        parts.append(_section(title))
        parts.extend(lines)

    if app is not None:
        parts.append(_section("This session"))
        parts.extend(_project_lines(app))

    parts.append(_section("Log"))
    parts.extend(_log_lines(app) if app is not None else ["(not available)"])

    parts.append(_section("Crash log"))
    parts.extend(_crash_lines())

    return NL.join(parts) + NL


def write_report(app=None, directory=None):
    """
    Writes the report and returns its path.

    Lands in the settings folder rather than beside the program: on a normal
    install the program directory is not writable, and that is exactly the
    moment someone is trying to report a problem.
    """
    directory = directory or settings.config_dir()
    os.makedirs(directory, exist_ok=True)
    name = time.strftime("wavefield-report-%Y%m%d-%H%M%S.txt")
    path = os.path.join(directory, name)
    with open(path, "w", encoding="utf-8") as handle:
        handle.write(summary(app))
    return path


def reveal(path):
    """Opens the folder containing `path`, selecting it where possible."""
    folder = os.path.dirname(path)
    try:
        if os.name == "nt":
            # explorer returns a non-zero exit code even when it works, so its
            # result is deliberately not checked.
            subprocess.Popen(["explorer", "/select,", os.path.normpath(path)])
        elif sys.platform == "darwin":
            subprocess.Popen(["open", "-R", path])
        else:
            subprocess.Popen(["xdg-open", folder])
        return True
    except Exception:
        return False
