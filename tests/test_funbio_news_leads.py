from datetime import datetime, timezone
from pathlib import Path

from discover_funbio_news_leads import parse_news_inventory, resolve_news_leads
import discover_funbio_candidates as funbio


FIXTURE = Path(__file__).parent / "fixtures" / "sources" / "funbio" / "news.html"


def test_explicit_url_resolves_and_unlinked_mention_is_not_submitted():
    inventory = parse_news_inventory(
        FIXTURE.read_text(encoding="utf-8"),
        now=datetime(2026, 7, 23, tzinfo=timezone.utc),
    )
    resolutions = resolve_news_leads(
        inventory,
        [
            {
                "source_record_id": "floresta-viva-piaui",
                "canonical_url": "https://chamadas.funbio.org.br/floresta-viva-piaui",
            }
        ],
    )
    assert [item["resolution"] for item in resolutions] == [
        "resolved",
        "unresolved_lead",
    ]
    assert resolutions[0]["source_record_id"] == "floresta-viva-piaui"
    assert resolutions[1]["reason_code"] == "unresolved_news_lead"


def test_lookback_and_detail_caps_are_bounded():
    inventory = parse_news_inventory(
        FIXTURE.read_text(encoding="utf-8"),
        now=datetime(2026, 7, 23, tzinfo=timezone.utc),
        lookback_days=1,
        max_items=1,
    )
    assert [item["news_id"] for item in inventory] == ["44"]


def test_canonical_call_fields_take_precedence_over_news():
    fixtures = FIXTURE.parent
    listing = (fixtures / "listing.html").read_text(encoding="utf-8")
    detail = (fixtures / "detail.html").read_text(encoding="utf-8")
    pages = {
        funbio.FUNBIO_LISTING_URL: listing,
        "https://chamadas.funbio.org.br/floresta-viva-piaui": detail,
        "https://chamadas.funbio.org.br/noticias": FIXTURE.read_text(encoding="utf-8"),
    }
    stats, opportunities = funbio.discover_opportunities(
        fetch_html=pages.__getitem__,
        snapshot_at=datetime(2026, 7, 23, tzinfo=timezone.utc),
        include_news=True,
    )
    assert stats["news_resolved"] == 1
    assert len(opportunities) == 1
    assert opportunities[0]["title"] == "Floresta Viva - Piaui"
    assert opportunities[0]["source_record_id"] == "floresta-viva-piaui"
    assert opportunities[0]["_related_news"]


def test_current_nextjs_detail_shell_is_parsed():
    html = """
    <html><body><div id="__next"><nav>Portal</nav><div class="call-shell">
      <h1>Chamada Floresta Viva</h1>
      <p>Inscricoes ate 31/08/2026.</p>
      <a href="/download/regulamento?id=42">Regulamento</a>
    </div><footer>Politica de Privacidade</footer></div></body></html>
    """
    opportunity = funbio.parse_funbio_opportunity(
        "https://chamadas.funbio.org.br/floresta-viva",
        html,
        snapshot_at=datetime(2026, 7, 23, tzinfo=timezone.utc),
    )
    assert opportunity is not None
    assert opportunity["source_record_id"] == "floresta-viva"
    assert opportunity["application_deadline"].startswith("2026-08-31")
    assert "Politica de Privacidade" not in opportunity["source_markdown"]
