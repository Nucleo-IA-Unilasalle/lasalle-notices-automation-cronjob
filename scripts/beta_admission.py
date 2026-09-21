"""Fail-closed source admission for scheduled Actions workers.

``SOURCE_ADMISSION_MODE=closed_beta`` retains the one-source canary fence.
``SOURCE_ADMISSION_MODE=legacy`` is the reviewed post-beta mode: every registry
entry explicitly marked ``ingest`` may run, while audit/paused entries remain
blocked. Repo A remains the authoritative server-side admission fence.
"""

from __future__ import annotations

import argparse
import os
import sys

from build_source_matrix import load_registry, validate_registry


ALLOWLIST_ENV = "CLOSED_BETA_SOURCE_ALLOWLIST"
MODE_ENV = "SOURCE_ADMISSION_MODE"
VALID_MODES = frozenset({"closed_beta", "legacy"})


class BetaAdmissionDenied(RuntimeError):
    """The worker is not authorized to claim or ingest this source."""


def admission_mode(*, environ: dict[str, str] | None = None) -> str:
    """Return the explicit admission mode, defaulting safely to closed beta."""
    environment = os.environ if environ is None else environ
    mode = environment.get(MODE_ENV, "closed_beta")
    if mode not in VALID_MODES:
        raise BetaAdmissionDenied(
            f"{MODE_ENV} must be one of {','.join(sorted(VALID_MODES))}"
        )
    return mode


def admitted_source(source: str, *, environ: dict[str, str] | None = None) -> str:
    """Return the admitted source or fail closed on every invalid configuration.

    A one-source list is intentional for this release.  Rejecting whitespace,
    commas, duplicates, and unknown keys prevents a partially valid value from
    accidentally broadening the canary.
    """
    environment = os.environ if environ is None else environ
    entries = {entry["source_key"]: entry for entry in validate_registry(load_registry())}
    known_sources = set(entries)
    if source not in known_sources:
        raise BetaAdmissionDenied("requested source is not in the execution registry")
    if entries[source]["rollout_mode"] != "ingest":
        raise BetaAdmissionDenied("the selected source is held outside ingestion")

    if admission_mode(environ=environment) == "legacy":
        return source

    raw = environment.get(ALLOWLIST_ENV)
    if raw is None or not raw:
        raise BetaAdmissionDenied(f"{ALLOWLIST_ENV} must name exactly one source")
    if raw != raw.strip() or "," in raw or any(char.isspace() for char in raw):
        raise BetaAdmissionDenied(f"{ALLOWLIST_ENV} must be one canonical source key")
    if raw not in known_sources:
        raise BetaAdmissionDenied(f"{ALLOWLIST_ENV} contains an unknown source key")
    if source != raw:
        raise BetaAdmissionDenied("requested source is not selected for the closed beta")
    if entries[source]["submission_contract"] != "candidate":
        raise BetaAdmissionDenied("the first closed-beta source must use the candidate contract")
    return source


def require_admitted_source(source: str, *, environ: dict[str, str] | None = None) -> str:
    """Enforce beta admission before a worker can claim or ingest."""
    return admitted_source(source, environ=environ)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", required=True)
    parser.add_argument(
        "--legacy-route",
        action="store_true",
        help="block an unfenced legacy API route even when its source is selected",
    )
    args = parser.parse_args(argv)
    try:
        require_admitted_source(args.source)
        if args.legacy_route and admission_mode() != "legacy":
            raise BetaAdmissionDenied(
                "legacy API routes are disabled in closed beta until Repo A exposes fenced admission"
            )
    except (BetaAdmissionDenied, SystemExit) as exc:
        print(f"Source admission denied: {exc}", file=sys.stderr)
        return 2
    print(f"Source admission granted for {args.source} in {admission_mode()} mode")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
