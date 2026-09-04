"""Single source of the version number - the app, the About box and the
installer all read it from here so they cannot drift apart."""

__version__ = "1.0.0"

APP_NAME = "Auto-Cut"
PROJECT_URL = "https://github.com/pcmflores19-ph/autocut-simple"

# Auto-Cut bundles pedalboard, rnnoise and ZamPlugins, all GPL, so the built
# application is GPL-3. That obliges us to make the source available to anyone
# who receives the program - satisfied simply by PROJECT_URL being public.
