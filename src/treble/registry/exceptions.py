"""Registry exceptions."""


class RegistryError(Exception):
    """Base class for registry errors."""


class ProcedureNotFound(RegistryError):
    """Requested procedure does not exist."""


class DuplicateProcedure(RegistryError):
    """A procedure with this name already exists in the target scope."""


class InvalidProcedure(RegistryError):
    """Procedure file failed validation."""
