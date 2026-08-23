"""Safe user-facing controller errors."""


class ControllerError(RuntimeError):
    """An expected failure whose message is safe to display."""


class ConfigError(ControllerError):
    """Local controller configuration is invalid."""


class PreflightError(ControllerError):
    """A read-only DNS, TCP, or SSH preflight check failed."""


class ToolingError(ControllerError):
    """Controller tooling is missing or inconsistent."""
