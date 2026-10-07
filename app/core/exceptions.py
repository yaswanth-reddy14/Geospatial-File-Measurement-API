class ApplicationError(Exception):
    status_code = 400


class UnsupportedFileTypeError(ApplicationError):
    pass


class InvalidGeospatialFileError(ApplicationError):
    pass


class UploadTooLargeError(ApplicationError):
    status_code = 413


class CRSProcessingError(ApplicationError):
    status_code = 422


class StoredFileNotFoundError(ApplicationError):
    status_code = 404
