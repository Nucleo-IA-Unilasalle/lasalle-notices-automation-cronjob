"""Unit tests for ``scripts/discover_fundacao_grupo_boticario_candidates.py``.

Ports the Fundação Grupo Boticário source from
``lasalle-notices-automation/app/services/scraper/playwright/fundacao_grupo_boticario.py``
into the cronjob, locking the discovery contract before Phase 4 ships.
Tests exercise the two-stage discovery (listing → detail URLs → PDFs)
on both the BS4 primary path and the Playwright fallback, plus the
``process_candidate`` / ``submit_candidates`` handoff.

The chamadas live as posts on the news index
``https://fundacaogrupoboticario.org.br/noticias/`` (the homepage links to
none); detail pages are on ``fundacaogrupoboticario.org.br`` and
``goias.gov.br`` (FAPEG). Discovery is lifecycle-gated by card date, result
title and the deadline written in the post.
"""

from __future__ import annotations

import asyncio
import importlib
import sys
from datetime import date
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import requests

from conftest import make_response, patch_request_with_safe_redirects

FIXTURES_DIR = (
    Path(__file__).resolve().parent
    / "fixtures"
    / "sources"
    / "fundacao_grupo_boticario"
)


LISTING_FIXTURE = FIXTURES_DIR / "listing.html"
DETAIL_CHAMADA_FIXTURE = FIXTURES_DIR / "detail_chamada.html"
DETAIL_SPRINT_FIXTURE = FIXTURES_DIR / "detail_sprint.html"


LISTING_URL = "https://fundacaogrupoboticario.org.br/"


CHAMADA_DETAIL_URL = (
    "https://goias.gov.br/fapeg/chamada-publica-fapeg-fgb-no-07-2026-chamada-cerrado-solucoes-para-protecao-da-biodiversidade-no-cerrado-de-goias-frente-aos-incendios-florestais"
)
SPRINT_DETAIL_URL = (
    "https://fundacaogrupoboticario.org.br/sprint-prevencao-ao-fogo-no-cerrado"
)


@pytest.fixture(autouse=True)
def _no_detail_delay(monkeypatch: pytest.MonkeyPatch) -> None:
    """The real pause between detail fetches would only slow the tests down."""
    import discover_fundacao_grupo_boticario_candidates as dfb

    monkeypatch.setattr(dfb, "FUNDACAO_GRUPO_BOTICARIO_DETAIL_DELAY_SECONDS", 0.0)


def _read_fixture(path: Path) -> str:
    return path.read_text(encoding="utf-8")


HOME_URL = LISTING_URL
NEWS_URL = "https://fundacaogrupoboticario.org.br/noticias/"

BASE = "https://fundacaogrupoboticario.org.br"
SPRINT_POST = f"{BASE}/sprint-prevencao-ao-fogo-no-cerrado"
BOLSAS_POST = (
    f"{BASE}/edital-oferece-bolsas-de-r-10-mil-para-reportagens-sobre-"
    "adaptacao-climatica-em-cidades-costeiras"
)
PRORROGA_POST = f"{BASE}/edital-conexao-oceano-prorroga-inscricoes-ate-29-de-abril"
OCEANO_RESULT_POST = (
    f"{BASE}/edital-conexao-oceano-define-os-cinco-projetos-contemplados-"
    "com-bolsas-de-jornalismo"
)
URGENT_POST = (
    f"{BASE}/chamada-para-acoes-urgentes-destina-ate-r-600-mil-para-resgate-e-"
    "reabilitacao-de-fauna-e-reestruturacao-pos-incendios-no-cerrado-e-pantanal"
)
RESULT_POST = f"{BASE}/resultado-chamada-recuperacao-pos-incendios-cerrado-e-pantanal"
ELNINO_POST = (
    f"{BASE}/nove-acoes-sao-indicadas-para-receber-ate-r-42-milhoes-para-"
    "minimizar-impactos-das-chuvas-provocadas-pelo-el-nino"
)
SPRINT_PDF = (
    f"{BASE}/wp-content/uploads/2026/03/Regulamento-SPRINT-PREVENCAO-AO-FOGO-2026.1-1.pdf"
)

# Structure copied from the live homepage nav (2026-11-01): no edital / chamada
# / sprint / bolsa anchor anywhere; /noticias is the only road to the posts.
HOME_HTML = """
<html><body>
<header><nav>
  <a href="https://fundacaogrupoboticario.org.br/quem-somos/">Quem somos</a>
  <a href="https://fundacaogrupoboticario.org.br/nossa-atuacao/">Nossa atuação</a>
  <a href="https://fundacaogrupoboticario.org.br/para-voce/">Para você</a>
  <a href="https://fundacaogrupoboticario.org.br/noticias">Notícias</a>
  <a href="https://fundacaogrupoboticario.org.br/transparencia/">Transparência</a>
  <a href="https://fundacaogrupoboticario.org.br/defensores-do-cerrado/">Defensores do Cerrado</a>
  <a href="https://sisger.fbpn.org.br/">Sisger</a>
  <a href="https://conduta.grupoboticario.com.br/">Canal de conduta</a>
</nav></header>
</body></html>
"""


def _card(url: str, title: str, when: str) -> str:
    # Mirrors the live ``div.noticias-card`` markup of /noticias/.
    return (
        '<div class="noticias-card" data-aos="fade-down">'
        '<img alt="" class="wp-post-image" src="/wp-content/uploads/x-380x235.png"/> '
        '<p class="noticias-card__cat"><a href="https://fundacaogrupoboticario.org.br/'
        'category/clima-e-adaptacao/" rel="category tag">Clima e adaptação</a> '
        f"| {when}</p>"
        f'<h4><a href="{url}/">{title}</a></h4>'
        "<p>Resumo da notícia.</p></div>"
    )


# Newest first, like the live index. Titles and dates are the live ones.
NEWS_CARDS = [
    (f"{BASE}/fundacao-grupo-boticario-marca-presenca-nas-conferencias-da-onu-sobre-biodiversidade-e-clima",
     "Fundação Grupo Boticário marca presença nas Conferências da ONU", "23/10/2026"),
    (ELNINO_POST,
     "Nove ações são indicadas para receber até R$ 4,2 milhões para minimizar impactos das chuvas provocadas pelo El Niño.",
     "31/08/2026"),
    (OCEANO_RESULT_POST,
     "Edital Conexão Oceano define os cinco projetos contemplados com bolsas de jornalismo",
     "30/06/2026"),
    (PRORROGA_POST, "Edital Conexão Oceano prorroga inscrições até 29 de abril", "22/04/2026"),
    (BOLSAS_POST,
     "Edital oferece bolsas de R$ 10 mil para reportagens sobre adaptação climática em cidades costeiras",
     "16/03/2026"),
    (SPRINT_POST,
     "Fundação Grupo Boticário abre inscrições para o Sprint Prevenção ao Fogo no Cerrado goiano",
     "03/03/2026"),
    (RESULT_POST, "RESULTADO – CHAMADA RECUPERAÇÃO PÓS INCÊNDIOS – CERRADO E PANTANAL", "13/11/2025"),
    (URGENT_POST,
     "Chamada para ações urgentes destina até R$ 600 mil para resgate e reabilitação de fauna",
     "28/10/2025"),
]

NEWS_HTML = (
    "<html><body>"
    '<nav><a href="https://fundacaogrupoboticario.org.br/noticias">Notícias</a></nav>'
    '<div class="noticias-content"><div class="noticias-recentes__grid">'
    + "".join(_card(*card) for card in NEWS_CARDS)
    + "</div></div></body></html>"
)


def _post_html(title: str, published: str, body: str, *, pdf: str | None = None) -> str:
    """Mirror of the live ``div.noticia-content`` single-post structure."""
    anchor = f'<p><a href="{pdf}" target="_blank">Regulamento</a></p>' if pdf else ""
    return (
        "<html><body class='single single-post'>"
        '<div class="content noticia-content"><div class="wrapper__small">'
        '<div class="block-full cabecalho"><div class="cabecalho__wrapper">'
        f'<div class="cabecalho__txt"><p class="cabecalho__ttl">Notícias</p><h1>{title}</h1>'
        "</div></div></div>"
        f'<div class="wp-block-post-date"><time datetime="{published}T10:00:00">x</time></div>'
        f'<p class="wp-block-paragraph">{body}</p>{anchor}'
        "</div></div>"
        # Outside the article body: must never feed the deadline gate.
        '<aside><p>Relacionadas: inscrições até 30 de dezembro de 2030</p></aside>'
        "</body></html>"
    )


SPRINT_HTML = _post_html(
    "Fundação Grupo Boticário abre inscrições para o Sprint Prevenção ao Fogo",
    "2026-03-03",
    "Nova edição da Teia de Soluções; inscrições ficam abertas de 3 a 9 de março.",
    pdf=SPRINT_PDF,
)
# The other fetchable posts of the replay window, with no PDF. The Oct 2025
# chamada is only 128 days old on 2026-03-05, so it is fetched and found closed.
URGENT_HTML = _post_html(
    "Chamada para ações urgentes", "2025-10-28",
    "Inscrição: Aberto até 04 de novembro de 2025, às 23h59min.",
)
BOLSAS_HTML = _post_html("Edital", "2026-03-16", "Inscrições até 22 de abril.")
PRORROGA_HTML = _post_html("Edital", "2026-04-22", "Inscrições até 29 de abril.")


def _responses(**extra: Any) -> dict[str, Any]:
    responses: dict[str, Any] = {
        HOME_URL: make_response(HOME_HTML),
        NEWS_URL: make_response(NEWS_HTML),
        SPRINT_POST: make_response(SPRINT_HTML),
        BOLSAS_POST: make_response(BOLSAS_HTML),
        PRORROGA_POST: make_response(PRORROGA_HTML),
        URGENT_POST: make_response(URGENT_HTML),
    }
    responses.update(extra)
    return responses


AS_OF_OPEN = date(2026, 3, 5)  # inside the Sprint window (3-9 Mar 2026)


class TestDetailUrlExtraction:
    """The detail-URL extraction is a verbatim port of the FastAPI helper."""

    def test_synthetic_listing_yields_signal_detail_urls(self) -> None:
        from bs4 import BeautifulSoup

        from discover_fundacao_grupo_boticario_candidates import (
            extract_fundacao_grupo_boticario_detail_urls_from_soup,
        )

        soup = BeautifulSoup(_read_fixture(LISTING_FIXTURE), "html.parser")
        discovered = extract_fundacao_grupo_boticario_detail_urls_from_soup(
            soup, LISTING_URL,
        )

        # goias.gov.br /fapeg/ chamada and the sprint post are kept; the
        # third-party host and the blacklisted /noticias path are dropped.
        assert discovered == [CHAMADA_DETAIL_URL, SPRINT_DETAIL_URL]

    def test_homepage_yields_no_chamada_but_news_index_does(self) -> None:
        """Regression for the 2026-10-30 diagnosis: the homepage has no edital
        anchors; the news index exposes them."""
        from discover_fundacao_grupo_boticario_candidates import (
            extract_fundacao_grupo_boticario_detail_urls,
        )

        assert extract_fundacao_grupo_boticario_detail_urls(HOME_HTML, HOME_URL) == []

        discovered = extract_fundacao_grupo_boticario_detail_urls(NEWS_HTML, NEWS_URL)
        assert discovered == [
            OCEANO_RESULT_POST,
            PRORROGA_POST,
            BOLSAS_POST,
            SPRINT_POST,
            RESULT_POST,
            URGENT_POST,
        ]
        assert ELNINO_POST not in discovered  # no signal token

    def test_is_fundacao_grupo_boticario_host(self) -> None:
        from discover_fundacao_grupo_boticario_candidates import (
            is_fundacao_grupo_boticario_host,
        )

        assert is_fundacao_grupo_boticario_host(
            "https://fundacaogrupoboticario.org.br/sprint-prevencao/",
        )
        assert is_fundacao_grupo_boticario_host(
            "https://www.fundacaogrupoboticario.org.br/sprint-prevencao/",
        )
        assert not is_fundacao_grupo_boticario_host("https://goias.gov.br/fapeg/chamada/")


class TestListingUrls:
    def test_default_listing_urls(self) -> None:
        from discover_fundacao_grupo_boticario_candidates import (
            FUNDACAO_GRUPO_BOTICARIO_LISTING_URL,
            FUNDACAO_GRUPO_BOTICARIO_LISTING_URLS,
            FUNDACAO_GRUPO_BOTICARIO_NEWS_URL,
        )

        assert FUNDACAO_GRUPO_BOTICARIO_LISTING_URL == HOME_URL
        assert FUNDACAO_GRUPO_BOTICARIO_NEWS_URL == NEWS_URL
        assert FUNDACAO_GRUPO_BOTICARIO_LISTING_URLS == (HOME_URL, NEWS_URL)

    def test_listing_posts_carry_title_and_card_date(self) -> None:
        from discover_fundacao_grupo_boticario_candidates import (
            extract_fundacao_grupo_boticario_listing_posts,
        )

        posts = extract_fundacao_grupo_boticario_listing_posts(NEWS_HTML, NEWS_URL)
        assert len(posts) == len(NEWS_CARDS)
        assert posts[SPRINT_POST].published == date(2026, 3, 3)
        assert "Sprint" in posts[SPRINT_POST].title
        assert posts[URGENT_POST].published == date(2025, 10, 28)
        assert extract_fundacao_grupo_boticario_listing_posts(HOME_HTML, HOME_URL) == {}


class TestLifecycleHelpers:
    @pytest.mark.parametrize(
        "text, reference, expected",
        [
            ("inscrições ficam abertas de 3 a 9 de março.", date(2026, 3, 3), date(2026, 3, 9)),
            ("Inscrição: Aberto até 04 de novembro de 2025, às 23h59min", None, date(2025, 11, 4)),
            ("Inscrições: de 28 de março a 15 de maio", date(2022, 3, 28), date(2022, 5, 15)),
            ("inscrições até o dia 02 de junho de 2022", None, date(2022, 6, 2)),
            ("inscrições prorrogadas até 1º de dezembro", date(2026, 11, 20), date(2026, 12, 1)),
            # Year-less deadline preceding the post date rolls into next year.
            ("inscrições abertas até 5 de janeiro", date(2026, 12, 20), date(2027, 1, 5)),
            # Latest wins, so an extension supersedes the original deadline.
            (
                "Inscrições até 20 de abril. Inscrições prorrogadas até 27 de abril.",
                date(2026, 4, 1),
                date(2026, 4, 27),
            ),
        ],
    )
    def test_extract_application_deadline(
        self, text: str, reference: date | None, expected: date,
    ) -> None:
        from discover_fundacao_grupo_boticario_candidates import (
            extract_application_deadline,
        )

        assert extract_application_deadline(text, reference=reference) == expected

    @pytest.mark.parametrize(
        "text",
        [
            # No inscription context -> not a deadline.
            "as reportagens deverão ser publicadas até 30 de novembro de 2026",
            # Year-less deadline with no reference date cannot be resolved.
            "inscrições até 9 de março",
            "sem datas",
        ],
    )
    def test_extract_application_deadline_returns_none(self, text: str) -> None:
        from discover_fundacao_grupo_boticario_candidates import (
            extract_application_deadline,
        )

        assert extract_application_deadline(text, reference=None) is None

    @pytest.mark.parametrize(
        "title, expected",
        [
            ("Edital Conexão Oceano define os cinco projetos contemplados com bolsas", True),
            ("RESULTADO – CHAMADA RECUPERAÇÃO PÓS INCÊNDIOS", True),
            ("Edital divulga fotografias e projetos de reportagem vencedores", True),
            ("Evento revela selecionados de chamada de soluções baseadas na natureza", True),
            ("Fundação Grupo Boticário abre inscrições para o Sprint Prevenção ao Fogo", False),
            ("Edital oferece bolsas de R$ 10 mil para reportagens", False),
            ("Chamada seleciona soluções para fortalecer áreas naturais protegidas", False),
        ],
    )
    def test_is_result_post(self, title: str, expected: bool) -> None:
        from discover_fundacao_grupo_boticario_candidates import is_result_post

        assert is_result_post(title) is expected


class TestDiscoverCandidates:
    def test_news_index_is_fetched_and_open_sprint_becomes_candidate(self) -> None:
        import discover_fundacao_grupo_boticario_candidates as dfb

        # The response map raises AssertionError for any unmapped URL, so a
        # result or stale post being fetched would fail this test.
        with patch_request_with_safe_redirects(_responses()):
            with patch.object(dfb, "_run_playwright_fallback") as listing_pw:
                with patch.object(dfb, "_run_playwright_detail_fallback") as detail_pw:
                    stats, candidates = dfb.discover_candidates(as_of_date=AS_OF_OPEN)

        listing_pw.assert_not_called()
        detail_pw.assert_not_called()
        assert stats["listings_fetched"] == 2
        assert stats["playwright_fallback_used"] == 0
        assert stats["detail_urls_found"] == 6
        assert stats["skipped_result_posts"] == 2  # oceano result + RESULTADO
        assert stats["skipped_stale_posts"] == 0
        assert stats["closed_details"] == 1  # Oct 2025 chamada: deadline 4 Nov 2025
        assert stats["open_details"] == 3  # Sprint + the two April posts
        assert stats["errors"] == 0
        assert [c["url"] for c in candidates] == [SPRINT_PDF]
        metadata = candidates[0]["metadata"]
        assert metadata["source"] == "fundacao_grupo_boticario"
        assert metadata["listing_url"] == NEWS_URL
        assert metadata["detail_url"] == SPRINT_POST
        assert metadata["application_deadline"] == "2026-03-09"
        assert metadata["published_at"] == "2026-03-03"
        assert metadata["status"] == "open"

    def test_deadline_day_is_open_and_the_day_after_is_closed(self) -> None:
        import discover_fundacao_grupo_boticario_candidates as dfb

        with patch_request_with_safe_redirects(_responses()):
            _stats, on_deadline = dfb.discover_candidates(as_of_date=date(2026, 3, 9))
            stats, after = dfb.discover_candidates(as_of_date=date(2026, 3, 10))

        assert [c["url"] for c in on_deadline] == [SPRINT_PDF]
        assert after == []
        assert stats["closed_details"] == 2  # Oct 2025 chamada + Sprint

    def test_live_state_stale_posts_are_fetched_and_found_closed(self) -> None:
        """2026-11-01: the newest signal post is a result and the rest is older
        than the window. The stale posts are still fetched (their detail could
        announce a future deadline) and every one of them is found closed."""
        import discover_fundacao_grupo_boticario_candidates as dfb

        with patch_request_with_safe_redirects(_responses()):
            with patch.object(dfb, "_run_playwright_fallback") as listing_pw:
                stats, candidates = dfb.discover_candidates(as_of_date=date(2026, 11, 1))

        listing_pw.assert_not_called()
        assert candidates == []
        assert stats["listings_fetched"] == 2
        assert stats["detail_urls_found"] == 6
        assert stats["details_fetched"] == 4
        assert stats["closed_details"] == 4
        assert stats["open_details"] == 0
        assert stats["skipped_result_posts"] == 2
        assert stats["skipped_stale_posts"] == 0
        assert stats["errors"] == 0
        assert "partial_inventory" not in stats

    def test_default_as_of_is_today(self) -> None:
        import discover_fundacao_grupo_boticario_candidates as dfb

        with patch_request_with_safe_redirects(_responses()):
            stats, candidates = dfb.discover_candidates()

        assert candidates == []
        assert stats["details_fetched"] == 4

    def test_homepage_and_news_detail_urls_are_unioned_without_duplicates(self) -> None:
        import discover_fundacao_grupo_boticario_candidates as dfb

        home_only_post = f"{BASE}/chamada-extra-no-home"
        extra_pdf = f"{BASE}/wp-content/uploads/2026/03/extra.pdf"
        home = HOME_HTML.replace(
            "</nav>",
            f'<a href="{SPRINT_POST}/">Sprint</a>'
            f'<a href="{home_only_post}/">Chamada extra</a></nav>',
        )
        responses = _responses(
            **{
                HOME_URL: make_response(home),
                home_only_post: make_response(
                    _post_html(
                        "Chamada extra", "2026-03-04",
                        "Inscrições até 20 de março.", pdf=extra_pdf,
                    ),
                ),
            },
        )
        with patch_request_with_safe_redirects(responses):
            stats, candidates = dfb.discover_candidates(as_of_date=AS_OF_OPEN)

        assert sorted(c["url"] for c in candidates) == sorted([SPRINT_PDF, extra_pdf])
        listing_of = {c["metadata"]["detail_url"]: c["metadata"]["listing_url"] for c in candidates}
        # Seen on the homepage first; the union keeps a single entry each.
        assert listing_of == {SPRINT_POST: HOME_URL, home_only_post: HOME_URL}
        assert stats["detail_urls_found"] == 7

    def test_recent_post_without_deadline_is_open_but_undated_post_is_not(self) -> None:
        import discover_fundacao_grupo_boticario_candidates as dfb

        undated = f"{BASE}/chamada-sem-data"
        undated_html = (
            '<html><body><div class="noticia-content"><p>Chamada sem data.</p>'
            f'<a href="{BASE}/x.pdf">pdf</a></div></body></html>'
        )
        responses = _responses(
            **{
                HOME_URL: make_response(
                    HOME_HTML.replace("</nav>", f'<a href="{undated}/">Chamada</a></nav>'),
                ),
                undated: make_response(undated_html),
                SPRINT_POST: make_response(
                    _post_html("Sprint", "2026-03-03", "Regulamento sem prazo.", pdf=SPRINT_PDF),
                ),
            },
        )
        with patch_request_with_safe_redirects(responses):
            stats, candidates = dfb.discover_candidates(as_of_date=AS_OF_OPEN)

        assert [c["url"] for c in candidates] == [SPRINT_PDF]
        assert "application_deadline" not in candidates[0]["metadata"]
        assert stats["missing_lifecycle"] == 1

    def test_foundation_post_without_pdf_does_not_launch_the_browser(self) -> None:
        import discover_fundacao_grupo_boticario_candidates as dfb

        responses = _responses(
            **{SPRINT_POST: make_response(_post_html("Sprint", "2026-03-03", "Inscrições até 9 de março."))},
        )
        with patch_request_with_safe_redirects(responses):
            with patch.object(dfb, "_run_playwright_detail_fallback") as detail_pw:
                stats, candidates = dfb.discover_candidates(as_of_date=AS_OF_OPEN)

        detail_pw.assert_not_called()
        assert candidates == []
        assert stats["detail_browser_fallback_used"] == 0
        assert stats["errors"] == 0

    def test_browser_fallback_runs_when_foundation_article_is_not_server_rendered(
        self,
    ) -> None:
        import discover_fundacao_grupo_boticario_candidates as dfb

        dynamic_pdf = f"{BASE}/wp-content/uploads/2026/03/dynamic.pdf"
        # No .noticia-content: lifecycle falls back to the listing card date.
        responses = _responses(
            **{SPRINT_POST: make_response('<html><body><div id="app"></div></body></html>')},
        )
        with patch_request_with_safe_redirects(responses):
            with patch.object(
                dfb, "_run_playwright_detail_fallback", return_value=[dynamic_pdf],
            ) as detail_pw:
                stats, candidates = dfb.discover_candidates(as_of_date=AS_OF_OPEN)

        detail_pw.assert_called_once_with(SPRINT_POST, stats=stats)
        assert stats["detail_browser_fallback_used"] == 1
        assert [c["url"] for c in candidates] == [dynamic_pdf]

    def test_non_foundation_host_uses_static_pdfs_then_browser_fallback(self) -> None:
        import discover_fundacao_grupo_boticario_candidates as dfb

        goias_detail = "https://goias.gov.br/fapeg/chamada-publica-fapeg-fgb-no-08-2026"
        goias_pdf = "https://goias.gov.br/fapeg/wp-content/uploads/chamada-publica-08.pdf"
        home = HOME_HTML.replace(
            "</nav>", f'<a href="{goias_detail}/">Chamada FAPEG/FGB</a></nav>',
        )
        with_pdf = (
            "<html><body><p>Inscrições até 20 de março de 2026.</p>"
            f'<a href="{goias_pdf}">Edital</a></body></html>'
        )
        without_pdf = "<html><body><p>Inscrições até 20 de março de 2026.</p></body></html>"

        responses = _responses(
            **{HOME_URL: make_response(home), goias_detail: make_response(with_pdf)},
        )
        with patch_request_with_safe_redirects(responses):
            with patch.object(dfb, "_run_playwright_detail_fallback") as detail_pw:
                _stats, candidates = dfb.discover_candidates(as_of_date=AS_OF_OPEN)
        detail_pw.assert_not_called()
        assert goias_pdf in [c["url"] for c in candidates]

        responses[goias_detail] = make_response(without_pdf)
        with patch_request_with_safe_redirects(responses):
            with patch.object(
                dfb, "_run_playwright_detail_fallback", return_value=[goias_pdf],
            ) as detail_pw:
                stats, candidates = dfb.discover_candidates(as_of_date=AS_OF_OPEN)
        detail_pw.assert_called_once_with(goias_detail, stats=stats)
        assert goias_pdf in [c["url"] for c in candidates]

    def test_news_fetch_failure_keeps_homepage_and_tries_listing_fallback(self) -> None:
        import discover_fundacao_grupo_boticario_candidates as dfb

        with patch_request_with_safe_redirects(
            {HOME_URL: make_response(HOME_HTML), NEWS_URL: requests.ConnectionError("down")},
        ):
            with patch.object(dfb, "_run_playwright_fallback", return_value=[]) as listing_pw:
                stats, candidates = dfb.discover_candidates(as_of_date=date(2026, 11, 1))

        assert stats["errors"] == 1
        assert stats["listings_fetched"] == 1
        assert stats["playwright_fallback_used"] == 1
        assert [call.args[0] for call in listing_pw.call_args_list] == [HOME_URL, NEWS_URL]
        assert candidates == []

    def test_playwright_listing_fallback_urls_still_pass_the_lifecycle_gate(self) -> None:
        import discover_fundacao_grupo_boticario_candidates as dfb

        empty_news = "<html><body><a>nothing</a></body></html>"
        responses = {
            HOME_URL: make_response(HOME_HTML),
            NEWS_URL: make_response(empty_news),
            SPRINT_POST: make_response(SPRINT_HTML),
        }
        with patch_request_with_safe_redirects(responses):
            with patch.object(dfb, "_run_playwright_fallback", return_value=[SPRINT_POST]):
                stats, candidates = dfb.discover_candidates(as_of_date=AS_OF_OPEN)
                _stats, later = dfb.discover_candidates(as_of_date=date(2026, 6, 1))

        assert stats["playwright_fallback_used"] == 1
        # No card date from the fallback: lifecycle comes from the post itself.
        assert [c["url"] for c in candidates] == [SPRINT_PDF]
        assert candidates[0]["metadata"]["application_deadline"] == "2026-03-09"
        assert later == []

    def test_detail_fetch_failure_is_counted_and_does_not_stop_other_details(self) -> None:
        import discover_fundacao_grupo_boticario_candidates as dfb

        responses = _responses(**{BOLSAS_POST: requests.ConnectionError("detail down")})
        with patch_request_with_safe_redirects(responses):
            stats, candidates = dfb.discover_candidates(as_of_date=AS_OF_OPEN)

        assert stats["errors"] == 1
        assert [c["url"] for c in candidates] == [SPRINT_PDF]

    def test_detail_budget_is_spent_after_gating_and_flags_partial_inventory(self) -> None:
        import discover_fundacao_grupo_boticario_candidates as dfb

        with patch_request_with_safe_redirects(_responses()):
            with patch.object(dfb, "FUNDACAO_GRUPO_BOTICARIO_MAX_DETAILS_PER_RUN", 1):
                stats, _candidates = dfb.discover_candidates(as_of_date=AS_OF_OPEN)

        assert stats["details_fetched"] == 1
        assert stats["detail_cap_reached"] == 1
        assert stats["partial_inventory"] == 1

    # -- stale posts: fetched after the in-window ones, with leftover budget --

    @staticmethod
    def _cards_responses(
        cards: list[tuple[str, str, str]], pages: dict[str, str],
    ) -> dict[str, Any]:
        news = (
            "<html><body>"
            '<div class="noticias-content"><div class="noticias-recentes__grid">'
            + "".join(_card(*card) for card in cards)
            + "</div></div></body></html>"
        )
        responses: dict[str, Any] = {
            HOME_URL: make_response(HOME_HTML),
            NEWS_URL: make_response(news),
        }
        responses.update({url: make_response(html) for url, html in pages.items()})
        return responses

    def test_old_post_with_future_deadline_becomes_candidate(self) -> None:
        import discover_fundacao_grupo_boticario_candidates as dfb

        old_post = f"{BASE}/chamada-antiga-prorrogada"
        old_pdf = f"{BASE}/wp-content/uploads/2026/01/chamada-antiga.pdf"
        responses = self._cards_responses(
            [(old_post, "Chamada antiga", "10/01/2026")],
            {
                old_post: _post_html(
                    "Chamada antiga", "2026-01-10",
                    "Inscrições prorrogadas até 20 de novembro de 2026.",
                    pdf=old_pdf,
                ),
            },
        )
        with patch_request_with_safe_redirects(responses):
            stats, candidates = dfb.discover_candidates(as_of_date=date(2026, 11, 1))

        assert [c["url"] for c in candidates] == [old_pdf]
        assert candidates[0]["metadata"]["application_deadline"] == "2026-11-20"
        assert candidates[0]["metadata"]["published_at"] == "2026-01-10"
        assert candidates[0]["metadata"]["status"] == "open"
        assert stats["details_fetched"] == 1
        assert stats["open_details"] == 1
        assert stats["skipped_stale_posts"] == 0

    def test_old_post_without_deadline_is_closed(self) -> None:
        import discover_fundacao_grupo_boticario_candidates as dfb

        old_post = f"{BASE}/chamada-antiga-sem-prazo"
        responses = self._cards_responses(
            [(old_post, "Chamada antiga", "10/01/2026")],
            {
                old_post: _post_html(
                    "Chamada antiga", "2026-01-10", "Regulamento sem prazo.",
                    pdf=f"{BASE}/wp-content/uploads/2026/01/antiga.pdf",
                ),
            },
        )
        with patch_request_with_safe_redirects(responses):
            stats, candidates = dfb.discover_candidates(as_of_date=date(2026, 11, 1))

        assert candidates == []
        assert stats["details_fetched"] == 1
        assert stats["closed_details"] == 1
        assert stats["open_details"] == 0

    def test_stale_overflow_past_the_budget_reports_incomplete_coverage(self) -> None:
        import discover_fundacao_grupo_boticario_candidates as dfb

        fresh = f"{BASE}/chamada-recente"
        stale = [f"{BASE}/chamada-antiga-{n}" for n in range(3)]
        cards = [(fresh, "Chamada recente", "20/10/2026")] + [
            (url, "Chamada antiga", "10/01/2026") for url in stale
        ]
        # Only the fresh post and the first stale post are mapped: the response
        # map raises for any other URL, so fetching more would register errors.
        responses = self._cards_responses(
            cards,
            {
                fresh: _post_html("Recente", "2026-10-20", "Inscrições até 30 de novembro de 2026."),
                stale[0]: _post_html("Antiga", "2026-01-10", "Sem prazo."),
            },
        )
        with patch_request_with_safe_redirects(responses):
            with patch.object(dfb, "FUNDACAO_GRUPO_BOTICARIO_MAX_DETAILS_PER_RUN", 2):
                stats, _candidates = dfb.discover_candidates(as_of_date=date(2026, 11, 1))

        assert stats["details_fetched"] == 2
        assert stats["errors"] == 0
        assert stats["skipped_stale_posts"] == 2
        assert stats["detail_cap_reached"] == 1
        assert stats["partial_inventory"] == 1

    def test_default_budget_fits_the_news_index(self) -> None:
        import discover_fundacao_grupo_boticario_candidates as dfb

        # The live /noticias/ index yields 25 signal URLs (2026-11-01).
        assert dfb.FUNDACAO_GRUPO_BOTICARIO_MAX_DETAILS_PER_RUN >= 25

    def test_in_window_overflow_flags_partial_and_starves_stale_posts(self) -> None:
        import discover_fundacao_grupo_boticario_candidates as dfb

        fresh = [f"{BASE}/chamada-recente-{n}" for n in range(2)]
        stale = f"{BASE}/chamada-antiga"
        cards = [(url, "Chamada recente", "20/10/2026") for url in fresh] + [
            (stale, "Chamada antiga", "10/01/2026"),
        ]
        responses = self._cards_responses(
            cards,
            {fresh[0]: _post_html("Recente", "2026-10-20", "Inscrições até 30 de novembro de 2026.")},
        )
        with patch_request_with_safe_redirects(responses):
            with patch.object(dfb, "FUNDACAO_GRUPO_BOTICARIO_MAX_DETAILS_PER_RUN", 1):
                stats, _candidates = dfb.discover_candidates(as_of_date=date(2026, 11, 1))

        assert stats["details_fetched"] == 1
        assert stats["errors"] == 0
        assert stats["open_details"] == 1
        assert stats["detail_cap_reached"] == 1
        assert stats["partial_inventory"] == 1
        assert stats["skipped_stale_posts"] == 1

    def test_pause_between_detail_fetches_but_not_before_the_first(self) -> None:
        import discover_fundacao_grupo_boticario_candidates as dfb

        with patch_request_with_safe_redirects(_responses()):
            with patch.object(dfb, "FUNDACAO_GRUPO_BOTICARIO_DETAIL_DELAY_SECONDS", 0.5):
                with patch.object(dfb.time, "sleep") as sleep:
                    stats, _candidates = dfb.discover_candidates(as_of_date=date(2026, 11, 1))

        assert stats["details_fetched"] == 4
        assert [call.args[0] for call in sleep.call_args_list] == [0.5] * 3

    def test_candidate_cap_stops_discovery(self) -> None:
        import discover_fundacao_grupo_boticario_candidates as dfb

        two_pdfs = SPRINT_HTML.replace(
            "</div></div><aside>", f'<a href="{BASE}/b.pdf">b</a></div></div><aside>',
        )
        assert two_pdfs != SPRINT_HTML
        with patch_request_with_safe_redirects(
            _responses(**{SPRINT_POST: make_response(two_pdfs)}),
        ):
            with patch.object(dfb, "FUNDACAO_GRUPO_BOTICARIO_MAX_CANDIDATES_PER_RUN", 1):
                stats, candidates = dfb.discover_candidates(as_of_date=AS_OF_OPEN)

        assert len(candidates) == 1
        assert stats["candidate_cap_reached"] == 1


class TestPlaywrightFallback:
    """The Playwright fallback imports ``async_playwright`` lazily and
    returns detail URLs after a single page navigation. Detail-page
    PDFs are then resolved by feeding each detail URL back through
    ``extract_fundacao_grupo_boticario_detail_urls_from_soup`` (or its
    detail-page equivalent); the cronjob keeps it simple by
    reproducing the FastAPI pattern of rebuilding an HTML fragment.
    """

    def _fake_async_pw(self, links: list[dict[str, str]]) -> MagicMock:
        fake_links: list[MagicMock] = []
        for link in links:
            anchor = MagicMock()
            anchor.get_attribute = AsyncMock(return_value=link.get("href", ""))
            fake_links.append(anchor)

        fake_page = MagicMock()
        fake_page.goto = AsyncMock()
        fake_page.query_selector_all = AsyncMock(return_value=fake_links)

        fake_context = MagicMock()
        fake_context.new_page = AsyncMock(return_value=fake_page)

        fake_browser = MagicMock()
        fake_browser.new_context = AsyncMock(return_value=fake_context)
        fake_browser.close = AsyncMock()

        fake_pw = MagicMock()
        fake_pw.chromium.launch = AsyncMock(return_value=fake_browser)

        class _ACMGate:
            def __init__(self, value: object) -> None:
                self.value = value

            async def __aenter__(self) -> object:
                return self.value

            async def __aexit__(self, *_: object) -> bool:
                return False

        fake_async_pw = MagicMock(return_value=_ACMGate(fake_pw))
        return fake_async_pw

    def _patched_asyncio_run(self, coro: Any) -> Any:
        loop = asyncio.new_event_loop()
        try:
            return loop.run_until_complete(coro)
        finally:
            loop.close()

    def test_run_playwright_fallback_returns_detail_urls(self) -> None:
        import types

        import discover_fundacao_grupo_boticario_candidates as dfb

        fake_pw = self._fake_async_pw(
            [
                {"href": CHAMADA_DETAIL_URL + "/"},
                {"href": "https://fundacaogrupoboticario.org.br/noticias/"},
                {"href": SPRINT_DETAIL_URL + "/"},
            ],
        )

        fake_async_api = types.ModuleType("playwright.async_api")
        fake_async_api.async_playwright = fake_pw  # type: ignore[attr-defined]
        fake_playwright = types.ModuleType("playwright")
        fake_playwright.async_api = fake_async_api  # type: ignore[attr-defined]

        stats: dict[str, int] = {}
        with patch.dict(
            sys.modules,
            {
                "playwright": fake_playwright,
                "playwright.async_api": fake_async_api,
            },
        ):
            with patch.object(dfb.asyncio, "run", side_effect=self._patched_asyncio_run):
                detail_urls = dfb._run_playwright_fallback(LISTING_URL, stats=stats)

        assert detail_urls == [CHAMADA_DETAIL_URL, SPRINT_DETAIL_URL]

    def test_run_playwright_detail_fallback_returns_pdf_urls(self) -> None:
        import types

        import discover_fundacao_grupo_boticario_candidates as dfb

        pdf_url = "https://fundacaogrupoboticario.org.br/docs/edital.pdf"
        fake_pw = self._fake_async_pw(
            [{"href": "/docs/edital.pdf"}, {"href": "/docs/notices.html"}],
        )
        fake_async_api = types.ModuleType("playwright.async_api")
        fake_async_api.async_playwright = fake_pw  # type: ignore[attr-defined]
        fake_playwright = types.ModuleType("playwright")
        fake_playwright.async_api = fake_async_api  # type: ignore[attr-defined]

        stats: dict[str, int] = {}
        with patch.dict(
            sys.modules,
            {
                "playwright": fake_playwright,
                "playwright.async_api": fake_async_api,
            },
        ):
            with patch.object(dfb, "ensure_safe_url"):
                with patch.object(dfb.asyncio, "run", side_effect=self._patched_asyncio_run):
                    pdf_urls = dfb._run_playwright_detail_fallback(
                        SPRINT_DETAIL_URL, stats=stats,
                    )

        assert pdf_urls == [pdf_url]
        assert stats == {}

    def test_run_playwright_fallback_returns_empty_when_playwright_missing(
        self,
    ) -> None:
        import discover_fundacao_grupo_boticario_candidates as dfb

        stats: dict[str, int] = {}

        def _raise_import_error(coro: Any) -> object:
            coro.close()
            raise ImportError("playwright")

        with patch.object(dfb.asyncio, "run", side_effect=_raise_import_error):
            detail_urls = dfb._run_playwright_fallback(LISTING_URL, stats=stats)

        assert detail_urls == []
        assert stats["errors"] == 1


class TestSubmitHandoff:
    def test_main_calls_submit_candidates_with_fundacao_grupo_boticario_source(
        self,
    ) -> None:
        import discover_fundacao_grupo_boticario_candidates as dfb

        candidate = {
            "url": "https://fundacaogrupoboticario.org.br/example.pdf",
            "kind": "pdf",
            "metadata": {"source": "fundacao_grupo_boticario"},
            "worker_result": {
                "ocr_markdown": "# Edital",
                "content_hash": "h",
                "content_length": 100,
                "validated_at": "2026-06-22T12:00:00+00:00",
                "validation_outcome": "valid_pdf",
            },
        }

        ocr_mod = MagicMock()
        config_mod = MagicMock()
        module_stubs = {
            "ocr_worker.ocr_extraction_config": config_mod,
            "ocr_worker.pdf_markdown_extractor": ocr_mod,
        }
        with patch.dict(sys.modules, module_stubs):
            with patch.object(dfb, "discover_candidates") as mock_disc:
                mock_disc.return_value = ({"candidates": 1}, [candidate])
                with patch.object(
                    dfb.pipeline_core,
                    "process_candidate",
                    return_value=candidate,
                ):
                    with patch.object(
                        dfb.pipeline_core,
                        "submit_candidates",
                    ) as mock_submit:
                        mock_submit.return_value = {
                            "total": 1,
                            "submitted": 1,
                            "failed_batches": 0,
                            "errors": [],
                        }
                        with patch.dict(
                            "os.environ",
                            {
                                "RENDER_APP_URL": "https://r.example.com",
                                "PIPELINE_SECRET": "tok",
                            },
                        ):
                            dfb.main()

        mock_submit.assert_called_once()
        call_args = mock_submit.call_args
        assert call_args.args[0] == [candidate]
        assert call_args.kwargs["source"] == "fundacao_grupo_boticario"

    def test_main_returns_2_when_required_env_missing(self) -> None:
        import discover_fundacao_grupo_boticario_candidates as dfb

        with patch.dict("os.environ", {}, clear=True):
            assert dfb.main() == 2

    def test_main_returns_0_when_no_candidates(self) -> None:
        import discover_fundacao_grupo_boticario_candidates as dfb

        with patch.object(dfb, "discover_candidates") as mock_disc:
            mock_disc.return_value = ({"candidates": 0}, [])
            with patch.dict(
                "os.environ",
                {
                    "RENDER_APP_URL": "https://r.example.com",
                    "PIPELINE_SECRET": "tok",
                },
            ):
                assert dfb.main() == 0
