# exceptions.py

class HoNServerConnectionError(Exception):
    """Raised when there's an error connecting to the server."""


class HoNAuthenticationError(Exception):
    """Raised when there's an error during authentication."""

class HoNConfigError(Exception):
    """Raised when there's an error with the user's configuration file."""

class HoNUnexpectedVersionError(Exception):
    """Raised when there is an issue with the hon files"""

class HoNPatchError(Exception):
    """Raised when there is an issue with patching"""

class HoNInvalidServerBinaries(Exception):
    """There is an issue with the local server binaries. They are probably not from wasserver."""

class HoNCompatibilityError(Exception):
    """There is an issue with the local server binaries. They are probably not from wasserver."""