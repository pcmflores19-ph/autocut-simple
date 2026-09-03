"""
Asks GitHub whether there is a newer release.

Only ever runs when the user picks Help > Check for updates. Nothing happens on
startup: an app that phones home the moment it opens is a surprise, and this
one is aimed at people who value everything staying on their own machine.

Best-effort throughout, in the same spirit as ollama_client: no network, a
rate-limit, a repository with no releases yet - all of those are ordinary, and
none of them is an error worth a traceback.
"""

import json
import re
import urllib.request

from version import APP_NAME, PROJECT_URL, __version__

RELEASES_URL = PROJECT_URL.rstrip("/") + "/releases"


def _repo_slug():
    """"owner/repo" out of the project URL, or None if it is not a GitHub one."""
    match = re.search(r"github\.com/([^/]+/[^/]+?)(?:\.git)?/?$", PROJECT_URL)
    return match.group(1) if match else None


def _parse(version_string):
    """
    "v1.10.2" -> (1, 10, 2), for comparison as numbers.

    Comparing the strings instead would put 1.10.0 *below* 1.9.0, which is the
    classic way to tell everyone they are up to date forever.
    """
    numbers = re.findall(r"\d+", version_string or "")
    return tuple(int(n) for n in numbers[:3]) or (0,)


def latest_release(timeout=8.0):
    """
    Returns {"version", "url", "name"} for the newest release, or None.

    None covers every failure and also the perfectly normal case of a
    repository that has no releases yet.
    """
    slug = _repo_slug()
    if not slug:
        return None
    request = urllib.request.Request(
        f"https://api.github.com/repos/{slug}/releases/latest",
        headers={
            # GitHub rejects API requests that do not identify themselves.
            "User-Agent": f"{APP_NAME}/{__version__}",
            "Accept": "application/vnd.github+json",
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except Exception:
        return None

    tag = payload.get("tag_name") or payload.get("name")
    if not tag:
        return None
    return {
        "version": tag.lstrip("vV"),
        "url": payload.get("html_url") or RELEASES_URL,
        "name": payload.get("name") or tag,
    }


def check():
    """
    Returns (status, detail):

        "current"     already newest, detail is None
        "available"   detail is the release dict from latest_release()
        "unknown"     could not tell - offline, rate-limited, no releases yet
    """
    release = latest_release()
    if release is None:
        return "unknown", None
    if _parse(release["version"]) > _parse(__version__):
        return "available", release
    return "current", release
