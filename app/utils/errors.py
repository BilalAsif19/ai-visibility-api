class APIError(Exception):
    """Base class for errors that should be surfaced to the client with a
    consistent {"error": {"code", "message", "details"}} JSON shape."""

    status_code = 500
    code = "internal_error"

    def __init__(self, message: str, status_code: int | None = None, details=None):
        super().__init__(message)
        self.message = message
        if status_code is not None:
            self.status_code = status_code
        self.details = details

    def to_dict(self) -> dict:
        return {
            "error": {
                "code": self.code,
                "message": self.message,
                "details": self.details,
            }
        }


class NotFoundError(APIError):
    status_code = 404
    code = "not_found"


class ValidationError(APIError):
    status_code = 400
    code = "validation_error"


class PipelineError(APIError):
    status_code = 502
    code = "pipeline_error"
