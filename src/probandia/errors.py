"""Errors of the engine, each tied to an exit code of the command-line interface."""

# Exit codes.
EXIT_OK = 0          # OK or WARN
EXIT_FAIL = 1        # a verification failed, a rule refused, a proposal was rejected
EXIT_USAGE = 2       # usage or configuration error
EXIT_ASK = 3         # the user must answer
EXIT_STOP = 4        # free quota, budget or cap reached
EXIT_LOCKED = 5      # lock held by another owner
EXIT_NO_PROJECT = 6  # not inside a project
EXIT_NETWORK = 7     # network or provider error after all retries
EXIT_INTERNAL = 10   # internal error; details in the log


class ProbandiaError(Exception):
    """An expected failure: the CLI prints it with the output contract, never a traceback."""

    exit_code = EXIT_FAIL
    status = "FAIL"
    reason = "failed"

    def __init__(self, message, *, values=None, lines=None):
        super().__init__(message)
        self.message = message
        self.values = dict(values or {})
        self.lines = list(lines or [])


class UsageError(ProbandiaError):
    exit_code = EXIT_USAGE
    reason = "usage"


class AmbiguousResearch(UsageError):
    """A prefix that names several researches; ``candidates`` holds them all."""

    def __init__(self, message, ref, candidates, **kw):
        super().__init__(message, **kw)
        self.ref = ref
        self.candidates = list(candidates)


class NotInProject(ProbandiaError):
    exit_code = EXIT_NO_PROJECT
    reason = "no-project"


class LockHeld(ProbandiaError):
    exit_code = EXIT_LOCKED
    reason = "lock-held"


class NetworkError(ProbandiaError):
    exit_code = EXIT_NETWORK
    reason = "network"


class YamlSyntaxError(ProbandiaError):
    """A YAML file written by an agent or a person cannot be read: where, and a hint."""

    reason = "yaml"


class SchemaError(ProbandiaError):
    """A document does not match its schema."""

    reason = "schema"

    def __init__(self, message, errors=(), **kw):
        super().__init__(message, **kw)
        self.errors = list(errors)


class SchemaVersionError(SchemaError):
    """A document carries a schema version newer than this engine knows."""

    exit_code = EXIT_USAGE
    reason = "schema-version"
