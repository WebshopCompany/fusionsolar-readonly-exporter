class ExporterError(RuntimeError):
    """Base exporter error."""


class ReadOnlyPolicyViolation(ExporterError):
    """Raised before network I/O when a request is outside the read-only policy."""


class AuthenticationError(ExporterError):
    """Authentication failed without exposing credentials."""


class HostDiscoveryRequired(AuthenticationError):
    """Automatic safe host discovery could not establish the data host."""
