# PNCP Backfill And Local AI Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a GitHub Actions PNCP backfill path that drains confirmed-active pending PNCP candidates through the existing Actions OCR/submission worker, then provide a local operator path for draining the resulting AI backlog.

**Architecture:** The backend exposes a small authenticated claim endpoint for active pending PNCP candidates. The cronjob repo adds a manual GitHub Actions workflow and script that claim candidates, reuse `pipeline_core.process_candidate`, and submit worker results back to `/api/pipeline/candidates`. The AI drain stays local in the backend repo and reuses `AIProcessingService`.

**Tech Stack:** FastAPI, SQLAlchemy, Pydantic, pytest, GitHub Actions, Python requests, existing OCR worker modules, Render MCP for post-deploy validation.

---

## Scope And Repositories

This plan intentionally spans two local repositories:

- Backend/API repo: `C:\Users\Vitor\Desktop\Vinicius\Projetos\lasalle-notices\lasalle-notices-automation`
- Cronjob/Actions repo: `C:\Users\Vitor\Desktop\Vinicius\Projetos\lasalle-notices\lasalle-notices-automation-cronjob`

Use separate commits per repository. Do not mix backend and cronjob changes into one repository commit.

## File Structure

Backend/API repo:

- Modify `app/services/scrape_candidate_service.py`: add a focused `claim_backfill_candidates(...)` query method that returns active pending PNCP candidates in priority order.
- Modify `app/api/pipeline_routes.py`: add response models and a protected `POST /api/pipeline/candidates/backfill/claim` route.
- Modify `tests/services/test_scrape_candidate_service.py`: cover active-only filtering, ordering, and limit behavior for the claim method.
- Modify `tests/api/test_pipeline_routes.py`: cover auth, route parameters, and response shape for the claim endpoint.
- Create `scripts/run_ai_backlog.py`: local operator script for bounded AI backlog processing.
- Create `tests/scripts/test_run_ai_backlog.py`: tests for script argument handling and service invocation.

Cronjob/Actions repo:

- Create `scripts/backfill_pncp_pending_candidates.py`: claim active pending PNCP candidates from Render, OCR them, and submit worker results.
- Create `tests/test_pncp_backfill.py`: tests for claim parsing, processing caps, submit behavior, and non-zero failure cases.
- Create `.github/workflows/pipeline-pncp-backfill.yml`: manual-only workflow with conservative defaults.
- Modify `README.md`: document the backfill workflow and post-deploy gate.

## Render MCP Context For The Execution Session

If the implementation session has Render MCP tools, select:

- Workspace id: `tea-d523k9dactks73ackil0`
- Workspace name: `My Workspace`
- Account email: `nucleoia@unilasalle.edu.br`

Relevant Render resources:

- API service: `lasalle-notices-api`, id `srv-d524fvlactks73ad3110`, URL `https://lasalle-notices-api.onrender.com`
- Static dashboard: `lasalle-notices`, id `srv-d52k6nili9vc73fa1f5g`, URL `https://lasalle-notices.onrender.com`
- Postgres: `DB Editais`, id `dpg-d8fhe658nd3s73fqq3hg-a`

Use Render MCP after pushing backend changes to confirm deploy health before triggering GitHub Actions.

---

### Task 1: Backend Claim Service

**Files:**
- Modify: `C:\Users\Vitor\Desktop\Vinicius\Projetos\lasalle-notices\lasalle-notices-automation\app\services\scrape_candidate_service.py`
- Test: `C:\Users\Vitor\Desktop\Vinicius\Projetos\lasalle-notices\lasalle-notices-automation\tests\services\test_scrape_candidate_service.py`

- [ ] **Step 1: Write failing service tests**

Append these tests to `tests/services/test_scrape_candidate_service.py`.

```python
def test_claim_backfill_candidates_returns_active_pncp_editais_first():
    from datetime import datetime, timedelta, timezone
    from app.schemas.scrape_candidate import ScrapeCandidate, ScrapeCandidateStatus
    from app.services.scrape_candidate_service import ScrapeCandidateService

    now = datetime.now(timezone.utc)
    active_edital = ScrapeCandidate(
        id=1,
        source="pncp",
        url="https://pncp.gov.br/active-edital.pdf",
        status=ScrapeCandidateStatus.pending,
        candidate_metadata={
            "dataEncerramentoProposta": (now + timedelta(days=3)).isoformat(),
            "tipoDocumentoNome": "Edital",
            "numeroControlePNCP": "active-edital",
            "sequencialDocumento": 1,
        },
        pncp_control_number="active-edital",
        pncp_document_sequence=1,
        discovered_at=now - timedelta(days=10),
    )
    active_reference = ScrapeCandidate(
        id=2,
        source="pncp",
        url="https://pncp.gov.br/active-reference.pdf",
        status=ScrapeCandidateStatus.pending,
        candidate_metadata={
            "dataEncerramentoProposta": (now + timedelta(days=1)).isoformat(),
            "tipoDocumentoNome": "Termo de Referência",
            "numeroControlePNCP": "active-reference",
            "sequencialDocumento": 2,
        },
        pncp_control_number="active-reference",
        pncp_document_sequence=2,
        discovered_at=now - timedelta(days=11),
    )
    expired_edital = ScrapeCandidate(
        id=3,
        source="pncp",
        url="https://pncp.gov.br/expired.pdf",
        status=ScrapeCandidateStatus.pending,
        candidate_metadata={
            "dataEncerramentoProposta": (now - timedelta(days=1)).isoformat(),
            "tipoDocumentoNome": "Edital",
            "numeroControlePNCP": "expired",
            "sequencialDocumento": 3,
        },
        pncp_control_number="expired",
        pncp_document_sequence=3,
        discovered_at=now - timedelta(days=12),
    )

    class Query:
        def __init__(self, rows):
            self.rows = rows
            self.limit_value = None

        def filter(self, *_criteria):
            return self

        def order_by(self, *_criteria):
            return self

        def limit(self, value):
            self.limit_value = value
            return self

        def all(self):
            assert self.limit_value == 10
            return [active_edital, active_reference, expired_edital]

    class Db:
        def query(self, *_args):
            return Query([active_edital, active_reference, expired_edital])

    rows = ScrapeCandidateService(Db()).claim_backfill_candidates(
        source="pncp",
        limit=10,
        active_only=True,
    )

    assert [row.url for row in rows] == [
        "https://pncp.gov.br/active-edital.pdf",
        "https://pncp.gov.br/active-reference.pdf",
    ]


def test_claim_backfill_candidates_rejects_non_pncp_source():
    import pytest
    from app.services.scrape_candidate_service import ScrapeCandidateService

    class Db:
        pass

    with pytest.raises(ValueError, match="Only PNCP backfill is supported"):
        ScrapeCandidateService(Db()).claim_backfill_candidates(
            source="worldbank",
            limit=10,
        )
```

- [ ] **Step 2: Run service tests and verify failure**

Run in the backend repo:

```powershell
python -m pytest tests/services/test_scrape_candidate_service.py::test_claim_backfill_candidates_returns_active_pncp_editais_first tests/services/test_scrape_candidate_service.py::test_claim_backfill_candidates_rejects_non_pncp_source -q
```

Expected: FAIL because `ScrapeCandidateService.claim_backfill_candidates` does not exist.

- [ ] **Step 3: Implement the service method**

Add imports near the top of `app/services/scrape_candidate_service.py`:

```python
from sqlalchemy import case, cast, DateTime
```

Add this method inside `ScrapeCandidateService` after `ingest_pending(...)`:

```python
    def claim_backfill_candidates(
        self,
        *,
        source: str = "pncp",
        limit: int = 20,
        active_only: bool = True,
    ) -> list[ScrapeCandidate]:
        if source.strip().lower() != "pncp":
            raise ValueError("Only PNCP backfill is supported")
        if limit < 1 or limit > 100:
            raise ValueError("limit must be between 1 and 100")

        deadline_text = ScrapeCandidate.candidate_metadata["dataEncerramentoProposta"].astext
        type_text = ScrapeCandidate.candidate_metadata["tipoDocumentoNome"].astext
        deadline_at = cast(case((deadline_text != "", deadline_text), else_=None), DateTime(timezone=True))
        now = datetime.now(timezone.utc)

        rows = (
            self.db.query(ScrapeCandidate)
            .filter(
                ScrapeCandidate.source == "pncp",
                ScrapeCandidate.status == ScrapeCandidateStatus.pending,
            )
            .order_by(
                case((deadline_at > now, 0), else_=1),
                case((type_text == "Edital", 0), else_=1),
                deadline_at.asc().nulls_last(),
                ScrapeCandidate.discovered_at.asc(),
                ScrapeCandidate.id.asc(),
            )
            .limit(limit)
            .all()
        )

        if not active_only:
            return rows

        return [
            row
            for row in rows
            if _first_brazil_datetime(
                row.candidate_metadata or {},
                "dataEncerramentoProposta",
            )
            and _first_brazil_datetime(
                row.candidate_metadata or {},
                "dataEncerramentoProposta",
            )
            > now
        ]
```

- [ ] **Step 4: Run service tests**

```powershell
python -m pytest tests/services/test_scrape_candidate_service.py::test_claim_backfill_candidates_returns_active_pncp_editais_first tests/services/test_scrape_candidate_service.py::test_claim_backfill_candidates_rejects_non_pncp_source -q
```

Expected: PASS.

- [ ] **Step 5: Commit backend service**

```powershell
git add app/services/scrape_candidate_service.py tests/services/test_scrape_candidate_service.py
git commit -m "feat: add pncp backfill candidate claim service"
```

---

### Task 2: Backend Claim API

**Files:**
- Modify: `C:\Users\Vitor\Desktop\Vinicius\Projetos\lasalle-notices\lasalle-notices-automation\app\api\pipeline_routes.py`
- Test: `C:\Users\Vitor\Desktop\Vinicius\Projetos\lasalle-notices\lasalle-notices-automation\tests\api\test_pipeline_routes.py`

- [ ] **Step 1: Write failing API tests**

Append this test to `tests/api/test_pipeline_routes.py`.

```python
def test_claim_pncp_backfill_candidates_returns_candidate_shape(monkeypatch, api_client):
    import app.api.pipeline_routes as pipeline_routes_module
    from datetime import datetime, timezone
    from types import SimpleNamespace

    candidate = SimpleNamespace(
        id=123,
        source="pncp",
        url="https://pncp.gov.br/doc.pdf",
        kind="pdf",
        candidate_metadata={
            "numeroControlePNCP": "control-1",
            "sequencialDocumento": 7,
            "tipoDocumentoNome": "Edital",
            "dataEncerramentoProposta": "2026-07-01T10:00:00",
        },
        pncp_control_number="control-1",
        pncp_document_sequence=7,
        discovered_at=datetime(2026, 6, 6, 11, 2, tzinfo=timezone.utc),
    )

    class FakeService:
        def __init__(self, _db):
            pass

        def claim_backfill_candidates(self, *, source, limit, active_only):
            assert source == "pncp"
            assert limit == 1
            assert active_only is True
            return [candidate]

    monkeypatch.setattr(pipeline_routes_module, "ScrapeCandidateService", FakeService)

    response = api_client.post(
        "/api/pipeline/candidates/backfill/claim?source=pncp&limit=1",
        headers=_auth_header(),
    )

    assert response.status_code == 200
    assert response.json() == {
        "source": "pncp",
        "limit": 1,
        "active_only": True,
        "candidates": [
            {
                "id": 123,
                "url": "https://pncp.gov.br/doc.pdf",
                "kind": "pdf",
                "metadata": {
                    "numeroControlePNCP": "control-1",
                    "sequencialDocumento": 7,
                    "tipoDocumentoNome": "Edital",
                    "dataEncerramentoProposta": "2026-07-01T10:00:00",
                },
                "pncp_control_number": "control-1",
                "pncp_document_sequence": 7,
                "discovered_at": "2026-06-06T11:02:00Z",
            }
        ],
    }


def test_claim_pncp_backfill_candidates_requires_auth(api_client):
    response = api_client.post("/api/pipeline/candidates/backfill/claim?source=pncp")
    assert response.status_code == 401
```

- [ ] **Step 2: Run API tests and verify failure**

```powershell
python -m pytest tests/api/test_pipeline_routes.py::test_claim_pncp_backfill_candidates_returns_candidate_shape tests/api/test_pipeline_routes.py::test_claim_pncp_backfill_candidates_requires_auth -q
```

Expected: FAIL with 404 for the new endpoint.

- [ ] **Step 3: Add API models and route**

In `app/api/pipeline_routes.py`, add these models near the existing candidate models:

```python
class BackfillCandidate(BaseModel):
    id: int
    url: str
    kind: str = "pdf"
    metadata: dict[str, Any] = Field(default_factory=dict)
    pncp_control_number: str | None = None
    pncp_document_sequence: int | None = None
    discovered_at: str | None = None


class ClaimBackfillCandidatesResponse(BaseModel):
    source: str
    limit: int
    active_only: bool
    candidates: list[BackfillCandidate] = Field(default_factory=list)
```

Add this route before `trigger_ingest(...)`:

```python
@router.post("/api/pipeline/candidates/backfill/claim", response_model=ClaimBackfillCandidatesResponse)
@limiter.exempt
async def claim_backfill_candidates(
    request: Request,
    source: str = Query(default="pncp", min_length=1, max_length=100),
    limit: int = Query(default=20, ge=1, le=100),
    active_only: bool = Query(default=True),
    _auth: None = Depends(verify_pipeline_token),
    db: Session = Depends(get_db),
) -> ClaimBackfillCandidatesResponse:
    normalized_source = source.strip().lower()
    if normalized_source != "pncp":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Only PNCP backfill is supported",
        )
    service = ScrapeCandidateService(db)
    rows = service.claim_backfill_candidates(
        source=normalized_source,
        limit=limit,
        active_only=active_only,
    )
    return ClaimBackfillCandidatesResponse(
        source=normalized_source,
        limit=limit,
        active_only=active_only,
        candidates=[
            BackfillCandidate(
                id=row.id,
                url=row.url,
                kind=row.kind,
                metadata=row.candidate_metadata or {},
                pncp_control_number=row.pncp_control_number,
                pncp_document_sequence=row.pncp_document_sequence,
                discovered_at=row.discovered_at.isoformat().replace("+00:00", "Z")
                if row.discovered_at
                else None,
            )
            for row in rows
        ],
    )
```

- [ ] **Step 4: Run API tests**

```powershell
python -m pytest tests/api/test_pipeline_routes.py::test_claim_pncp_backfill_candidates_returns_candidate_shape tests/api/test_pipeline_routes.py::test_claim_pncp_backfill_candidates_requires_auth -q
```

Expected: PASS.

- [ ] **Step 5: Run backend regression slice**

```powershell
python -m pytest tests/services/test_scrape_candidate_service.py tests/api/test_pipeline_routes.py -q
```

Expected: PASS.

- [ ] **Step 6: Commit backend API**

```powershell
git add app/api/pipeline_routes.py tests/api/test_pipeline_routes.py
git commit -m "feat: expose pncp backfill claim endpoint"
```

---

### Task 3: Cronjob Backfill Script

**Files:**
- Create: `C:\Users\Vitor\Desktop\Vinicius\Projetos\lasalle-notices\lasalle-notices-automation-cronjob\scripts\backfill_pncp_pending_candidates.py`
- Test: `C:\Users\Vitor\Desktop\Vinicius\Projetos\lasalle-notices\lasalle-notices-automation-cronjob\tests\test_pncp_backfill.py`

- [ ] **Step 1: Write failing cronjob tests**

Create `tests/test_pncp_backfill.py`.

```python
from __future__ import annotations

import pytest


def test_fetch_claimed_candidates_calls_render(monkeypatch):
    import scripts.backfill_pncp_pending_candidates as backfill

    captured = {}

    class Response:
        def raise_for_status(self):
            pass

        def json(self):
            return {
                "source": "pncp",
                "limit": 2,
                "active_only": True,
                "candidates": [
                    {
                        "id": 1,
                        "url": "https://pncp.gov.br/doc.pdf",
                        "kind": "pdf",
                        "metadata": {"numeroControlePNCP": "control", "sequencialDocumento": 1},
                    }
                ],
            }

    def fake_post(url, headers, params, timeout):
        captured.update({"url": url, "headers": headers, "params": params, "timeout": timeout})
        return Response()

    monkeypatch.setattr(backfill.requests, "post", fake_post)

    candidates = backfill.fetch_claimed_candidates(
        render_url="https://render.example",
        token="secret",
        limit=2,
    )

    assert captured["url"] == "https://render.example/api/pipeline/candidates/backfill/claim"
    assert captured["headers"] == {"Authorization": "Bearer secret"}
    assert captured["params"] == {"source": "pncp", "limit": 2, "active_only": "true"}
    assert candidates == [
        {
            "url": "https://pncp.gov.br/doc.pdf",
            "kind": "pdf",
            "metadata": {"numeroControlePNCP": "control", "sequencialDocumento": 1},
        }
    ]


def test_run_backfill_processes_and_submits_successes(monkeypatch):
    import scripts.backfill_pncp_pending_candidates as backfill

    monkeypatch.setattr(
        backfill,
        "fetch_claimed_candidates",
        lambda **_kwargs: [{"url": "https://pncp.gov.br/doc.pdf", "kind": "pdf", "metadata": {}}],
    )
    monkeypatch.setattr(backfill.pipeline_core, "SCRAPE_MAX_PDF_BYTES", 123)
    monkeypatch.setattr(backfill.pipeline_core, "pdf_download_limit_reached", lambda stats: False)
    monkeypatch.setattr(backfill.pipeline_core, "record_pdf_download", lambda stats: stats.__setitem__("pdfs_downloaded", 1))
    monkeypatch.setattr(
        backfill.pipeline_core,
        "process_candidate",
        lambda candidate, extractor, max_bytes: {**candidate, "worker_result": {"ocr_markdown": "# ok"}},
    )
    monkeypatch.setattr(backfill.pipeline_core, "make_default_ocr_extractor", lambda: (object(), object()))
    monkeypatch.setattr(
        backfill.pipeline_core,
        "submit_candidates",
        lambda processed, source: {"submitted": len(processed), "failed_batches": 0},
    )

    exit_code = backfill.run_backfill(
        render_url="https://render.example",
        token="secret",
        claim_limit=1,
        process_limit=1,
    )

    assert exit_code == 0


def test_run_backfill_fails_when_claimed_but_submitted_none(monkeypatch):
    import scripts.backfill_pncp_pending_candidates as backfill

    monkeypatch.setattr(
        backfill,
        "fetch_claimed_candidates",
        lambda **_kwargs: [{"url": "https://pncp.gov.br/doc.pdf", "kind": "pdf", "metadata": {}}],
    )
    monkeypatch.setattr(backfill.pipeline_core, "SCRAPE_MAX_PDF_BYTES", 123)
    monkeypatch.setattr(backfill.pipeline_core, "pdf_download_limit_reached", lambda stats: False)
    monkeypatch.setattr(
        backfill.pipeline_core,
        "process_candidate",
        lambda candidate, extractor, max_bytes: {**candidate, "error": "ocr: boom"},
    )
    monkeypatch.setattr(backfill.pipeline_core, "make_default_ocr_extractor", lambda: (object(), object()))
    monkeypatch.setattr(
        backfill.pipeline_core,
        "submit_candidates",
        lambda processed, source: {"submitted": 0, "failed_batches": 0},
    )

    assert backfill.run_backfill(
        render_url="https://render.example",
        token="secret",
        claim_limit=1,
        process_limit=1,
    ) == 1
```

- [ ] **Step 2: Run cronjob tests and verify failure**

```powershell
python -m pytest tests/test_pncp_backfill.py -q
```

Expected: FAIL because `scripts/backfill_pncp_pending_candidates.py` does not exist.

- [ ] **Step 3: Implement the cronjob script**

Create `scripts/backfill_pncp_pending_candidates.py`.

```python
from __future__ import annotations

import os
import sys
from typing import Any

import requests

import pipeline_core


PNCP_BACKFILL_CLAIM_LIMIT = int(os.getenv("PNCP_BACKFILL_CLAIM_LIMIT", "20"))
PNCP_MAX_PROCESSED_CANDIDATES_PER_RUN = int(os.getenv("PNCP_MAX_PROCESSED_CANDIDATES_PER_RUN", "20"))
RENDER_CLAIM_TIMEOUT = int(os.getenv("RENDER_CLAIM_TIMEOUT", "60"))


def fetch_claimed_candidates(
    *,
    render_url: str,
    token: str,
    limit: int,
) -> list[dict[str, Any]]:
    response = requests.post(
        f"{render_url.rstrip('/')}/api/pipeline/candidates/backfill/claim",
        headers={"Authorization": f"Bearer {token}"},
        params={"source": "pncp", "limit": limit, "active_only": "true"},
        timeout=RENDER_CLAIM_TIMEOUT,
    )
    response.raise_for_status()
    payload = response.json()
    candidates = payload.get("candidates", [])
    if not isinstance(candidates, list):
        raise ValueError("Render claim response field 'candidates' must be a list")
    return [
        {
            "url": str(item["url"]),
            "kind": str(item.get("kind") or "pdf"),
            "metadata": item.get("metadata") or {},
        }
        for item in candidates
        if isinstance(item, dict) and item.get("url")
    ]


def run_backfill(
    *,
    render_url: str,
    token: str,
    claim_limit: int,
    process_limit: int,
) -> int:
    candidates = fetch_claimed_candidates(
        render_url=render_url,
        token=token,
        limit=claim_limit,
    )
    stats: dict[str, int] = {
        "claimed": len(candidates),
        "processed": 0,
        "ocr_successes": 0,
        "ocr_failures": 0,
        "pdfs_downloaded": 0,
    }
    print(f"PNCP backfill claim stats: {stats}")
    if not candidates:
        print("No active PNCP pending candidates claimed")
        return 0

    _ocr_config, extractor = pipeline_core.make_default_ocr_extractor()
    processed: list[dict[str, Any]] = []

    for candidate in candidates:
        if len(processed) >= process_limit:
            stats["processing_cap_reached"] = 1
            break
        if pipeline_core.pdf_download_limit_reached(stats):
            stats["pdf_download_cap_reached"] = 1
            break
        result = pipeline_core.process_candidate(
            candidate,
            extractor=extractor,
            max_bytes=pipeline_core.SCRAPE_MAX_PDF_BYTES,
        )
        processed.append(result)
        stats["processed"] = len(processed)
        if result.get("worker_result"):
            pipeline_core.record_pdf_download(stats)
            stats["ocr_successes"] += 1
        else:
            stats["ocr_failures"] += 1

    print(f"PNCP backfill processing stats: {stats}")
    submit_result = pipeline_core.submit_candidates(processed, source="pncp")
    print(f"Render candidate submission: {submit_result}")

    if stats["claimed"] > 0 and submit_result.get("submitted", 0) == 0:
        print("error: claimed PNCP candidates but submitted none", file=sys.stderr)
        return 1
    if submit_result.get("failed_batches", 0) > 0:
        return 1
    return 0


def main() -> int:
    render_url = os.environ.get("RENDER_APP_URL")
    token = os.environ.get("PIPELINE_SECRET")
    if not render_url:
        print("error: RENDER_APP_URL is required", file=sys.stderr)
        return 2
    if not token:
        print("error: PIPELINE_SECRET is required", file=sys.stderr)
        return 2
    return run_backfill(
        render_url=render_url,
        token=token,
        claim_limit=PNCP_BACKFILL_CLAIM_LIMIT,
        process_limit=PNCP_MAX_PROCESSED_CANDIDATES_PER_RUN,
    )


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 4: Run cronjob tests**

```powershell
python -m pytest tests/test_pncp_backfill.py -q
```

Expected: PASS.

- [ ] **Step 5: Commit cronjob script**

```powershell
git add scripts/backfill_pncp_pending_candidates.py tests/test_pncp_backfill.py
git commit -m "feat: add pncp pending candidate backfill worker"
```

---

### Task 4: GitHub Actions Workflow And Docs

**Files:**
- Create: `C:\Users\Vitor\Desktop\Vinicius\Projetos\lasalle-notices\lasalle-notices-automation-cronjob\.github\workflows\pipeline-pncp-backfill.yml`
- Modify: `C:\Users\Vitor\Desktop\Vinicius\Projetos\lasalle-notices\lasalle-notices-automation-cronjob\README.md`

- [ ] **Step 1: Create manual workflow**

Create `.github/workflows/pipeline-pncp-backfill.yml`.

```yaml
name: PNCP pending candidate backfill

on:
  workflow_dispatch:
    inputs:
      claim_limit:
        description: "Maximum active pending PNCP candidates to claim"
        required: false
        default: "5"
      process_limit:
        description: "Maximum claimed candidates to download/OCR"
        required: false
        default: "5"

concurrency:
  group: pncp-backfill
  cancel-in-progress: false

jobs:
  backfill-pncp:
    runs-on: ubuntu-latest
    timeout-minutes: 20
    steps:
      - name: Checkout scheduler repository
        uses: actions/checkout@v4

      - name: Set up Python
        uses: actions/setup-python@v5
        with:
          python-version: "3.13"
          cache: pip
          cache-dependency-path: requirements-ocr-worker.txt

      - name: Install OCR worker dependencies
        run: pip install -r requirements-ocr-worker.txt

      - name: Run PNCP active pending candidate backfill
        run: python scripts/backfill_pncp_pending_candidates.py
        env:
          RENDER_APP_URL: ${{ secrets.RENDER_APP_URL }}
          PIPELINE_SECRET: ${{ secrets.PIPELINE_SECRET }}
          PNCP_BACKFILL_CLAIM_LIMIT: ${{ inputs.claim_limit }}
          PNCP_MAX_PROCESSED_CANDIDATES_PER_RUN: ${{ inputs.process_limit }}
          SCRAPE_MAX_PDF_BYTES: "15000000"
          SCRAPE_MAX_PDFS_PER_RUN: "5"
          RENDER_CLAIM_TIMEOUT: "60"
          RENDER_SUBMIT_BATCH_SIZE: "5"
          RENDER_SUBMIT_TIMEOUT: "90"
          RENDER_SUBMIT_MAX_ATTEMPTS: "4"
          RENDER_SUBMIT_BACKOFF_BASE: "5"
          KREUZBERG_PADDLE_LANGUAGE: "latin"
          KREUZBERG_PADDLE_MODEL_TIER: "tiny"
          KREUZBERG_USE_GPU: "false"
          KREUZBERG_FORCE_OCR_DEFAULT: "false"
          KREUZBERG_EXTRACTION_TIMEOUT_SECONDS: "120"
          FLAGS_use_mkldnn: "0"
          PADDLE_PDX_ENABLE_MKLDNN_BYDEFAULT: "0"
```

- [ ] **Step 2: Document the workflow**

In `README.md`, add a row to the workflow table:

```markdown
| `pipeline-pncp-backfill.yml` | Manual only | Claims active pending PNCP candidates from Render, downloads/OCRs them in Actions, and submits worker results back to Render |
```

Add this section after the PNCP runtime settings:

```markdown
### PNCP pending candidate backfill

`pipeline-pncp-backfill.yml` is a manual integration workflow for draining the active PNCP backlog in `scrape_candidates`. It calls the Render claim endpoint for active pending PNCP candidates, reuses the same download/OCR worker path as PNCP discovery, and submits successful worker results to `/api/pipeline/candidates`.

Use conservative inputs until the post-deploy testing gate passes:

- `claim_limit=1`
- `process_limit=1`

After Render is confirmed healthy and the first manual run moves an active candidate into `editais`, the limits can be increased gradually. Do not schedule this workflow until the active backlog behavior is verified in production.
```

- [ ] **Step 3: Run cronjob tests**

```powershell
python -m pytest tests/test_pncp_backfill.py -q
```

Expected: PASS.

- [ ] **Step 4: Commit workflow and docs**

```powershell
git add .github/workflows/pipeline-pncp-backfill.yml README.md
git commit -m "ci: add manual pncp backfill workflow"
```

---

### Task 5: Local AI Backlog Runner

**Files:**
- Create: `C:\Users\Vitor\Desktop\Vinicius\Projetos\lasalle-notices\lasalle-notices-automation\scripts\run_ai_backlog.py`
- Create: `C:\Users\Vitor\Desktop\Vinicius\Projetos\lasalle-notices\lasalle-notices-automation\tests\scripts\test_run_ai_backlog.py`

- [ ] **Step 1: Write failing script tests**

Create `tests/scripts/test_run_ai_backlog.py`.

```python
from __future__ import annotations


def test_run_ai_backlog_invokes_ai_service_with_limit(monkeypatch):
    import asyncio
    import scripts.run_ai_backlog as runner

    captured = {}

    class Db:
        def close(self):
            captured["closed"] = True

    class FakeService:
        def __init__(self, db):
            captured["db"] = db

        async def process_all_pending(self, limit=None, only_with_markdown=True):
            captured["limit"] = limit
            captured["only_with_markdown"] = only_with_markdown
            return {"processed": 2}

    monkeypatch.setattr(runner, "SessionLocal", lambda: Db())
    monkeypatch.setattr(runner, "AIProcessingService", FakeService)

    result = asyncio.run(runner.run_ai_backlog(limit=25, only_with_markdown=True))

    assert result == {"processed": 2}
    assert captured["limit"] == 25
    assert captured["only_with_markdown"] is True
    assert captured["closed"] is True
```

- [ ] **Step 2: Run test and verify failure**

```powershell
python -m pytest tests/scripts/test_run_ai_backlog.py -q
```

Expected: FAIL because `scripts/run_ai_backlog.py` does not exist or `AIProcessingService.process_all_pending` lacks the planned parameters.

- [ ] **Step 3: Inspect `AIProcessingService.process_all_pending` signature**

Open `app/services/ai_processing_service.py` and find:

```powershell
Select-String -Path app/services/ai_processing_service.py -Pattern "def process_all_pending" -Context 0,20
```

If the method already supports a limit, use its existing parameter. If it does not, add optional parameters `limit: int | None = None` and `only_with_markdown: bool = True` and thread them into the query that selects pending editais.

- [ ] **Step 4: Implement local runner**

Create `scripts/run_ai_backlog.py`.

```python
from __future__ import annotations

import argparse
import asyncio
import json

from app.config.db import SessionLocal
from app.services.ai_processing_service import AIProcessingService


async def run_ai_backlog(*, limit: int | None, only_with_markdown: bool) -> dict:
    db = SessionLocal()
    try:
        service = AIProcessingService(db)
        return await service.process_all_pending(
            limit=limit,
            only_with_markdown=only_with_markdown,
        )
    finally:
        db.close()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run bounded local AI processing for pending editais.")
    parser.add_argument("--limit", type=int, default=25, help="Maximum pending editais to process in this invocation.")
    parser.add_argument(
        "--only-with-markdown",
        action="store_true",
        default=True,
        help="Only process rows that already have markdown/text content.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    result = asyncio.run(
        run_ai_backlog(
            limit=args.limit,
            only_with_markdown=args.only_with_markdown,
        )
    )
    print(json.dumps(result, ensure_ascii=False, indent=2, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 5: Run local AI tests**

```powershell
python -m pytest tests/scripts/test_run_ai_backlog.py tests/services/test_ai_processing_service.py -q
```

Expected: PASS. If `test_ai_processing_service.py` failures show signature mismatch, update existing tests to pass the new optional defaults without changing behavior.

- [ ] **Step 6: Commit local AI runner**

```powershell
git add scripts/run_ai_backlog.py tests/scripts/test_run_ai_backlog.py app/services/ai_processing_service.py tests/services/test_ai_processing_service.py
git commit -m "feat: add bounded local ai backlog runner"
```

---

### Task 6: OpenAPI And Full Verification

**Files:**
- Modify if generated: `C:\Users\Vitor\Desktop\Vinicius\Projetos\lasalle-notices\lasalle-notices-automation\openapi.json`
- Modify if generated: `C:\Users\Vitor\Desktop\Vinicius\Projetos\lasalle-notices\lasalle-notices-automation\frontend\openapi.json`

- [ ] **Step 1: Regenerate OpenAPI artifacts if route changes require it**

In the backend repo, inspect existing generation command in tests/docs. If no helper exists, run the same command used by the project. A common pattern is:

```powershell
python -c "import json; from app.main import app; schema = app.openapi(); open('openapi.json','w',encoding='utf-8').write(json.dumps(schema, ensure_ascii=False, indent=2)); open('frontend/openapi.json','w',encoding='utf-8').write(json.dumps(schema, ensure_ascii=False, indent=2))"
```

Expected: `openapi.json` and `frontend/openapi.json` include `/api/pipeline/candidates/backfill/claim`.

- [ ] **Step 2: Run backend verification**

```powershell
python -m pytest tests/services/test_scrape_candidate_service.py tests/api/test_pipeline_routes.py tests/scripts/test_run_ai_backlog.py tests/api/test_openapi_contract_sync.py -q
```

Expected: PASS.

- [ ] **Step 3: Run cronjob verification**

In the cronjob repo:

```powershell
python -m pytest tests/test_pncp_backfill.py -q
```

Expected: PASS.

- [ ] **Step 4: Commit generated backend artifacts if changed**

```powershell
git add openapi.json frontend/openapi.json
git commit -m "chore: update openapi for pncp backfill claim"
```

If no OpenAPI files changed, do not create an empty commit.

---

### Task 7: Push And Post-Deploy Testing Gate

**Files:**
- No code changes expected.

- [ ] **Step 1: Push both repositories**

Push backend first, then cronjob:

```powershell
git push
```

Expected: both repos push successfully.

- [ ] **Step 2: Confirm Render deploy**

Using Render MCP, select workspace `tea-d523k9dactks73ackil0` and inspect service `srv-d524fvlactks73ad3110`.

Expected:

- `lasalle-notices-api` deploy for the backend commit is live.
- Recent logs show no startup exception.
- Health/API requests succeed.

- [ ] **Step 3: Smoke-test claim endpoint with limit 1**

Call the deployed endpoint with `limit=1` and the pipeline bearer token.

Expected response shape:

```json
{
  "source": "pncp",
  "limit": 1,
  "active_only": true,
  "candidates": [
    {
      "id": 1,
      "url": "https://...",
      "kind": "pdf",
      "metadata": {},
      "pncp_control_number": "...",
      "pncp_document_sequence": 1,
      "discovered_at": "2026-06-..."
    }
  ]
}
```

If `candidates` is empty, query production to confirm there are no active pending PNCP candidates before treating it as success.

- [ ] **Step 4: Trigger GitHub Actions backfill manually**

Run `.github/workflows/pipeline-pncp-backfill.yml` with:

```text
claim_limit=1
process_limit=1
```

Expected: workflow completes successfully or fails with an explainable PDF/OCR issue. If the workflow claims a candidate and submits zero candidates, keep the gate failed.

- [ ] **Step 5: Validate production state**

Run the validation queries from the spec against production:

```sql
SELECT
  COUNT(*) AS pending_candidates,
  COUNT(e.id) AS matching_editais
FROM public.scrape_candidates sc
LEFT JOIN public.editais e ON e.source_url = sc.url
WHERE sc.source = 'pncp'
  AND sc.status = 'pending';
```

```sql
SELECT
  COUNT(*) FILTER (WHERE ai_processing_completed IS FALSE) AS ai_not_completed,
  COUNT(*) FILTER (WHERE ai_processing_completed IS TRUE) AS ai_completed
FROM public.editais;
```

Expected:

- A successful workflow run moves at least one active candidate into `editais`, or logs explain exactly why not.
- AI backlog may increase after promotion.

- [ ] **Step 6: Decide cadence**

If the gate passes, keep the workflow manual for the first few larger batches. Increase only to conservative limits such as:

```text
claim_limit=5
process_limit=5
```

Do not add a schedule until several manual runs are clean.

## Self-Review Notes

- Spec coverage: backend claim endpoint, Actions worker, manual workflow, local AI runner, and post-deploy Render/GitHub Actions gate are covered.
- Red-flag scan: no open-ended implementation gaps are intentionally left; Task 5 includes an explicit branch for the existing AI service signature because that code must be inspected during execution.
- Type consistency: backend route returns `metadata`, while database uses `candidate_metadata`; cronjob converts the API response into the existing `pipeline_core.process_candidate` input shape.
