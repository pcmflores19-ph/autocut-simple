"""
Opens one VST3 plugin's native editor, in its own process.

pedalboard refuses to show a plugin UI from anything but the main thread, and
the call blocks until the window closes. Calling it directly from the app would
freeze the whole interface - meters, playhead and all - for as long as the
editor is open. So the editor runs here instead, as a subprocess:

    parent  --(plugin path + current raw_state)-->  this script
    this script  shows the editor on ITS main thread, user tweaks, closes
    parent  <--(new raw_state on stdout)--  this script
    parent  applies that state to its own live plugin instance

Run directly:  python plugin_editor.py <plugin path> [<state file>]
Prints the resulting state as base64 on stdout, prefixed with STATE:.
"""

import base64
import os
import sys
import threading
import time

# How often the plugin's state is checked while its editor is open. Fast enough
# that a knob move is audible almost immediately, slow enough not to thrash.
STATE_POLL_SECONDS = 0.15


def _center_editor_window(title, timeout=15.0):
    """
    JUCE opens the plugin editor at roughly (-8, -31) - its title bar sits above
    the top of the screen, so the window can't be dragged and its close button
    is unreachable. Wait for the window to appear, then move it on-screen and
    give it a useful title.

    Runs on a worker thread because show_editor() owns the main thread.
    """
    if os.name != "nt":
        return
    import ctypes
    from ctypes import wintypes

    user32 = ctypes.windll.user32
    enum_proc = ctypes.WINFUNCTYPE(ctypes.c_bool, wintypes.HWND, wintypes.LPARAM)
    pid = os.getpid()
    deadline = time.time() + timeout

    while time.time() < deadline:
        matches = []

        def callback(hwnd, _lparam):
            window_pid = wintypes.DWORD()
            user32.GetWindowThreadProcessId(hwnd, ctypes.byref(window_pid))
            if window_pid.value == pid and user32.IsWindowVisible(hwnd):
                cls = ctypes.create_unicode_buffer(256)
                user32.GetClassNameW(hwnd, cls, 256)
                if cls.value.startswith("JUCE"):
                    matches.append(hwnd)
            return True

        user32.EnumWindows(enum_proc(callback), 0)

        if matches:
            hwnd = matches[0]
            rect = wintypes.RECT()
            user32.GetWindowRect(hwnd, ctypes.byref(rect))
            width = rect.right - rect.left
            height = rect.bottom - rect.top

            screen_w = user32.GetSystemMetrics(0)
            screen_h = user32.GetSystemMetrics(1)
            x = max(0, (screen_w - width) // 2)
            y = max(0, (screen_h - height) // 3)

            SWP_NOSIZE, SWP_NOZORDER, SWP_SHOWWINDOW = 0x0001, 0x0004, 0x0040
            user32.SetWindowPos(hwnd, 0, x, y, 0, 0,
                                SWP_NOSIZE | SWP_NOZORDER | SWP_SHOWWINDOW)
            user32.SetWindowTextW(hwnd, title)
            user32.SetForegroundWindow(hwnd)
            return
        time.sleep(0.25)


def main():
    if len(sys.argv) < 2:
        print("usage: plugin_editor.py <plugin path> [<state file>]", file=sys.stderr)
        return 2

    plugin_path = sys.argv[1]
    state_path = sys.argv[2] if len(sys.argv) > 2 else None

    import pedalboard

    plugin = pedalboard.load_plugin(plugin_path)

    if state_path:
        try:
            with open(state_path, "rb") as f:
                data = f.read()
            if data:
                plugin.raw_state = data
        except Exception as exc:
            print(f"could not restore plugin state: {exc}", file=sys.stderr)

    # Nudge the window on-screen once JUCE has created it. Must happen on a
    # worker thread - show_editor() takes over the main thread below.
    title = os.path.splitext(os.path.basename(plugin_path.rstrip("\\/")))[0]
    threading.Thread(target=_center_editor_window, args=(title,), daemon=True).start()

    # Stream state out while the editor is open, so the parent can apply each
    # tweak to its live plugin and you hear the change as you make it, rather
    # than only once the window closes.
    stop_watching = threading.Event()

    def emit_state():
        try:
            return base64.b64encode(plugin.raw_state).decode("ascii")
        except Exception:
            return None

    def watch_state():
        last = emit_state()
        while not stop_watching.is_set():
            time.sleep(STATE_POLL_SECONDS)
            current = emit_state()
            if current and current != last:
                last = current
                print("STATE:" + current, flush=True)

    threading.Thread(target=watch_state, daemon=True).start()

    plugin.show_editor()      # blocks here until the user closes the window
    stop_watching.set()

    final = emit_state()
    if final is None:
        print("could not read back plugin state", file=sys.stderr)
        return 1
    print("STATE:" + final, flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
