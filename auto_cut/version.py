"""Single source of the version number - the app, the About box and the
installer all read it from here so they cannot drift apart."""

__version__ = "1.0.0"

APP_NAME = "Auto-Cut"
PROJECT_URL = "https://github.com/pcmflores19-ph/autocut-simple"

# How to request the source code. Auto-Cut bundles pedalboard, rnnoise and
# ZamPlugins, all of which are GPL, so the built application is GPL-3 even
# though this code is not published. GPL-3 section 6(b) allows distributing a
# binary WITHOUT publishing the source, provided a written offer to supply it
# accompanies the binary - that offer is in THIRD-PARTY-NOTICES.txt and the
# About box, and this is the channel it names.
#
# Deliberately the public podcast page rather than a personal address: the
# offer has to name a way to get in touch, and this file ends up on the
# computer of everyone who installs the program.
SOURCE_CONTACT = "the Behind The Science Podcast page on Facebook"
SOURCE_CONTACT_URL = "https://www.facebook.com/btspodcastph"
