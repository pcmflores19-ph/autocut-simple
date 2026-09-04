"""Single source of the version number - the app, the About box and the
installer all read it from here so they cannot drift apart."""

__version__ = "1.0.0"

APP_NAME = "Wavefield"
PROJECT_URL = "https://github.com/pcmflores19-ph/wavefield"

# Wavefield bundles pedalboard and rnnoise, both GPL, so the built application
# is GPL-3. That obliges us to make the source available to anyone who receives
# the program. While the repository is private that is done with a written
# offer (GPL-3 section 6(b)) naming this contact - the public podcast page, not
# a personal address, because the notices file lands on every user's computer.
SOURCE_CONTACT_URL = "https://www.facebook.com/btspodcastph"
