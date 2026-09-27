class ExporterError(RuntimeError):
    """Base exporter error."""


class ReadOnlyPolicyViolation(ExporterError):
    """Raised before network I/O when a request is outside the read-only policy."""


class AuthenticationError(ExporterError):
    """Authentication failed without exposing credentials."""


class HostDiscoveryRequired(AuthenticationError):
    """A safe FusionSolar browser/data host is required before authentication."""


class UnsupportedRegion(HostDiscoveryRequired):
    """The supplied FusionSolar host maps to an explicitly unsupported login flow."""


class ApiResponseError(ExporterError):
    """A permitted endpoint returned a response that could not be parsed safely."""
