"""Application failures, independent of any transport protocol."""


class ApplicationError(Exception):
    """An expected failure whose message is safe to expose to a client."""


class InvalidInput(ApplicationError):
    pass


class NotFound(ApplicationError):
    pass


class Conflict(ApplicationError):
    pass


class Unavailable(ApplicationError):
    pass
