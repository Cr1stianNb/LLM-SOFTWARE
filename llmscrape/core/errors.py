"""Controlled errors and process exit codes.

Every foreseeable failure (unreachable URL, missing field, LLM endpoint down,
bad config) is represented as a ``ScrapeError`` subclass carrying its own exit
code, so the CLI can report a clean message instead of leaking a stack trace.
"""

from __future__ import annotations

# Exit codes. 0 = success, 1 = at least one test case failed (a *result*, not a
# crash), and everything >=2 is an infrastructure/usage problem.
EXIT_OK = 0
EXIT_TESTS_FAILED = 1
EXIT_USAGE = 2  # also what argparse emits on bad arguments
EXIT_FETCH_ERROR = 3
EXIT_CONFIG_ERROR = 4
EXIT_LLM_ERROR = 5
EXIT_SCHEMA_ERROR = 6
EXIT_DATA_ERROR = 7


class ScrapeError(Exception):
    """Base class for all controlled errors. Carries a process exit code."""

    exit_code = EXIT_USAGE

    def __init__(self, message: str):
        super().__init__(message)
        self.message = message


class ConfigError(ScrapeError):
    exit_code = EXIT_CONFIG_ERROR


class FetchError(ScrapeError):
    exit_code = EXIT_FETCH_ERROR


class LLMError(ScrapeError):
    exit_code = EXIT_LLM_ERROR


class SchemaError(ScrapeError):
    exit_code = EXIT_SCHEMA_ERROR


class DataError(ScrapeError):
    """Malformed test cases, cassette, or extraction program."""

    exit_code = EXIT_DATA_ERROR
