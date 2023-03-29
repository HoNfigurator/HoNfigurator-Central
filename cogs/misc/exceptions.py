# exceptions.py

class ServerConnectionError(Exception):
    """Raised when there's an error connecting to the server."""


class AuthenticationError(Exception):
    """Raised when there's an error during authentication."""

class ConfigError(Exception):
    """Raised when there's an error with the user's configuration file."""
