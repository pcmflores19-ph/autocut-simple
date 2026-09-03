"""
Where the Support menu points.

===========================================================================
 THESE ARE PLACEHOLDERS. Replace them with the real URLs before publishing.
 Anything still containing "example.com" is treated as unset: the menu item
 says so rather than opening a dead link.
===========================================================================

Kept in their own file so changing a link never means touching UI code.
"""

BUY_ME_A_COFFEE = "https://example.com/REPLACE-buymeacoffee"
YOUTUBE = "https://example.com/REPLACE-youtube"
SPOTIFY = "https://example.com/REPLACE-spotify"
FACEBOOK = "https://example.com/REPLACE-facebook"
INSTAGRAM = "https://example.com/REPLACE-instagram"

PODCAST_NAME = "Behind The Science Podcast"

# Menu order. Buy Me a Coffee sits on its own above the rest because it is the
# one that is actually being asked for.
SUPPORT_MENU = [
    ("Buy me a coffee", BUY_ME_A_COFFEE),
    (None, None),                        # separator
    ("Watch on YouTube", YOUTUBE),
    ("Listen on Spotify", SPOTIFY),
    ("Facebook", FACEBOOK),
    ("Instagram", INSTAGRAM),
]


def is_placeholder(url):
    return not url or "example.com" in url
