class ConfigurationError(Exception):
    """Raised when settings are missing or invalid.

    The message names the setting and the error type. It does not include
    setting values.
    """
