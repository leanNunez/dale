"""Composition root of the verifier process (design §9): the request on stdin, the verdict as
JSON on stdout. It connects only through DALE_VERIFIER_DATABASE_URL, the read-only
dale_verifier role, and it reads no other setting."""

import os
import sys
import traceback
from collections.abc import Mapping
from typing import TextIO

import sqlalchemy as sa

from dale.verifier.application.verify import parse_request, report_to_json, verify
from dale.verifier.domain.verdict import Report
from dale.verifier.infrastructure.evidence import SqlEvidence

URL_VARIABLE = "DALE_VERIFIER_DATABASE_URL"


def run(stdin: TextIO, stdout: TextIO, environ: Mapping[str, str], stderr: TextIO) -> int:
    """Always one verdict line and exit 0; a crash exits non-zero, which the runner reads as
    unverifiable. Why a run is unverifiable goes to stderr first."""

    def trace(error: Exception) -> None:  # the class and the stack, never the message: it
        stack = "".join(traceback.format_tb(error.__traceback__))  # may quote the request
        stderr.write(f"Traceback:\n{stack}{type(error).__module__}.{type(error).__qualname__}\n")

    try:
        request = parse_request(stdin.read())
    except ValueError as error:  # bad JSON, a wrong shape, or bytes that are not UTF-8
        trace(error)
        report = Report.unverifiable("bad_request")
    else:
        if url := environ.get(URL_VARIABLE):
            engine = sa.create_engine(url, poolclass=sa.NullPool)
            try:
                report = verify(request, SqlEvidence(engine), trace)
            finally:
                engine.dispose()
        else:
            stderr.write(f"{URL_VARIABLE} is not set\n")
            report = Report.unverifiable("no_database_url")
    stdout.write(report_to_json(report) + "\n")
    return 0


def main() -> int:
    return run(sys.stdin, sys.stdout, os.environ, sys.stderr)
