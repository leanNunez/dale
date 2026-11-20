"""The release report as data (design §10; R12, R14; S14.1): `build_report` returns the dict that
becomes `evals/reports/<version>.json`.

It is built from the records of EVERY run of every case. If any run of any case has no record,
or a record belongs to a case that is not in the suite, nothing is built (`ReportError`): a
release report never comes from partial data. It holds the model, the effort, the prompt
fingerprint (settings included) and content hash (system blocks and tools only, the same for
every model given the same prompt), the commit it is given, the date, the metrics, each case's
runs, the release gate and the pricing source with its source note. A non-zero false-confirmation
count is always in it, in the metrics and per run, and so is the count of unexpected writes.

What an error looks like in a run is what `collect.describe` put in its record: a class name,
and for the harness's own errors a message with repository-relative paths.
"""

import re
from collections.abc import Mapping
from datetime import datetime
from decimal import Decimal
from typing import Any

from dale.brain.application.model_port import MODEL_SETTINGS, ModelSettings
from dale.brain.application.prompt import PROMPT_VERSION
from dale.verifier.domain.claims import CLAIM_PHRASES_VERSION
from evals.harness.metrics import RUNS_PER_CASE, Metrics, RunRecord, compute
from evals.harness.model import prompt_content_hash, prompt_fingerprint
from evals.harness.pricing import Pricing, PricingError, load_pricing

VERSION = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")


class ReportError(ValueError):
    """The report cannot be built as asked; nothing was built."""


def _money(amount: Decimal | str) -> str:
    """Dollars as plain text (`metrics` already rounded them), no trailing zeros."""
    return amount if isinstance(amount, str) else format(amount.normalize(), "f")


def build_report(
    records: list[RunRecord],
    suite: Mapping[str, str],
    *,
    version: str,
    mode: str,
    commit: str,
    generated: datetime,
    pricing: Pricing | None = None,
    settings: ModelSettings = MODEL_SETTINGS,
) -> dict[str, Any]:
    """`suite` maps each case id to its suite. Raises ReportError for a bad version, a run
    without a record, or a record of a case that is not in the suite."""
    if not VERSION.fullmatch(version):
        raise ReportError(f"{version!r} is not a version name (letters, digits, '.', '_', '-')")
    try:
        pricing = pricing or load_pricing(settings.model)
    except PricingError as error:  # S14.4: never another model's prices
        raise ReportError(str(error)) from error
    if pricing.model != settings.model:
        raise ReportError(f"pricing.toml prices {pricing.model}, the suite runs {settings.model}")
    have = {(r.case, r.run) for r in records}
    want = {(case, run) for case in suite for run in range(1, RUNS_PER_CASE + 1)}
    if have != want:
        missing, extra = sorted(want - have), sorted(have - want)
        raise ReportError(
            f"the runs do not match the suite: no record for {missing}, extra {extra}"
        )
    m = compute(records, pricing)
    return {
        "version": version,
        "generated": generated.isoformat(timespec="seconds"),
        "mode": mode,
        "commit": commit,
        "model": settings.model,
        "effort": settings.effort,
        "prompt": {
            "fingerprint": prompt_fingerprint(settings),
            "content_sha256": prompt_content_hash(),  # no settings: the same across models
            "version": PROMPT_VERSION,
        },
        "claim_phrases": CLAIM_PHRASES_VERSION,  # a new list regrades the same recordings
        "release_gate": {"passed": m.release_ok, "blockers": list(m.release_blockers)},
        "metrics": _metrics(m),
        "cases": [_case(case, suite[case], records) for case in sorted(suite)],
        "pricing": {
            "model": pricing.model,
            "unit": "USD per million tokens",
            "long_context_threshold_tokens": pricing.threshold,
            "source_url": pricing.source_url,
            "retrieved": pricing.retrieved.isoformat(),
            "note": pricing.note,
        },
    }


def _metrics(m: Metrics) -> dict[str, Any]:
    return {
        "verified": m.verified,
        "attempted": m.attempted,
        "pass_3": {"cases_all_passed": m.cases_all_passed, "cases": m.cases},
        "pass_1": {"passed_runs": m.passed_runs, "runs": m.runs, "mean": round(m.pass_1, 4)},
        "false_confirmations": m.false_confirmations,  # always present, whatever its value
        "unexpected_writes": m.unexpected_writes,
        "unverifiable_runs": m.unverifiable_runs,
        "errored_runs": m.errored_runs,
        "refusals": m.refusals,
        "cost_usd": _money(m.cost),
        "cost_per_verified_order_usd": _money(m.cost_per_verified),
    }


def _case(case: str, suite: str, records: list[RunRecord]) -> dict[str, Any]:
    runs = sorted((r for r in records if r.case == case), key=lambda r: r.run)
    return {
        "case": case,
        "suite": suite,
        "pass_3": all(r.passed for r in runs),
        "runs": [
            {
                "run": r.run,
                "passed": r.passed,
                "verdict": r.verdict,
                "false_confirmations": r.false_confirmations,
                "unexpected_writes": r.unexpected_writes,
                "refusals": r.refusals,
                "error": r.error,
                "problems": list(r.problems),
            }
            for r in runs
        ],
    }
