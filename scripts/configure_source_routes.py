"""Resolve safe FUNBIO/TNC workflow routes from one repository variable."""

from __future__ import annotations

import json
import os
import sys
from dataclasses import asdict, dataclass
from pathlib import Path


CUTOVER_SOURCES = ("funbio", "tnc")
SCHEDULED_LEGACY_SOURCES = (
    "bndes",
    "brde",
    "fapergs",
    "iis_rio",
    "sema_rs",
    "wwf",
)
MANUAL_DEFAULT_SOURCES = (
    "bndes",
    "brde",
    "fapergs",
    "funbio",
    "iis_rio",
    "sema_rs",
    "tnc",
    "wwf",
)


class UnsafeRouteError(ValueError):
    """Raised when a manual submission would overlap a legacy source route."""


@dataclass(frozen=True)
class RouteConfig:
    sources: str
    opportunity_sources: str
    audit_only: str
    funbio_route: str
    tnc_route: str


def parse_source_list(raw: str | None) -> list[str]:
    """Return normalized, ordered, unique source keys."""
    seen: set[str] = set()
    result: list[str] = []
    for item in (raw or "").split(","):
        source = item.strip().lower()
        if not source or source in seen:
            continue
        seen.add(source)
        result.append(source)
    return result


def parse_flag(raw: str | None) -> bool:
    return (raw or "").strip().lower() in {"1", "true", "yes", "on"}


def resolve_routes(
    *,
    event_name: str,
    requested_sources: str | None,
    approved_opportunity_sources: str | None,
    audit_only: bool,
) -> RouteConfig:
    approved = parse_source_list(approved_opportunity_sources)
    approved_set = set(approved)
    routes = {
        source: "structured" if source in approved_set else "legacy"
        for source in CUTOVER_SOURCES
    }

    if event_name == "schedule":
        # Cut-over sources run first so the shared PDF cap cannot starve the
        # only active production route after its dedicated workflow is gated.
        selected = [
            source for source in CUTOVER_SOURCES if source in approved_set
        ]
        selected.extend(SCHEDULED_LEGACY_SOURCES)
        effective_audit_only = False
    else:
        selected = parse_source_list(requested_sources)
        if not selected:
            selected = list(MANUAL_DEFAULT_SOURCES)
        effective_audit_only = audit_only
        if not effective_audit_only:
            overlapping = sorted(
                set(selected).intersection(CUTOVER_SOURCES) - approved_set
            )
            if overlapping:
                raise UnsafeRouteError(
                    "manual submission would overlap active legacy workflow(s): "
                    + ",".join(overlapping)
                    + "; use audit_only=true or approve the structured route "
                    "through OPPORTUNITY_SOURCES first"
                )

    return RouteConfig(
        sources=",".join(selected),
        opportunity_sources="" if effective_audit_only else ",".join(approved),
        audit_only=str(effective_audit_only).lower(),
        funbio_route=routes["funbio"],
        tnc_route=routes["tnc"],
    )


def write_github_outputs(config: RouteConfig, output_path: Path) -> None:
    with output_path.open("a", encoding="utf-8") as output:
        for key, value in asdict(config).items():
            output.write(f"{key}={value}\n")


def main() -> int:
    try:
        config = resolve_routes(
            event_name=os.environ.get("EVENT_NAME", "workflow_dispatch"),
            requested_sources=os.environ.get("REQUESTED_SOURCES"),
            approved_opportunity_sources=os.environ.get(
                "APPROVED_OPPORTUNITY_SOURCES"
            ),
            audit_only=parse_flag(os.environ.get("AUDIT_ONLY")),
        )
    except UnsafeRouteError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    output_path = os.environ.get("GITHUB_OUTPUT")
    if output_path:
        write_github_outputs(config, Path(output_path))
    print(json.dumps(asdict(config), sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
