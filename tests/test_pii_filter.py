"""Tests for the PII filter module.

Unit tests for ``_drop_address_persons`` work directly on RecognizerResult
objects, so no spaCy models are loaded — they run in milliseconds.

The integration smoke tests for ``PiiFilter.clean`` use a module-scoped
fixture so the heavy engine initialisation happens only once per test session.
"""

from typing import Any
from unittest.mock import MagicMock

import pytest
from presidio_analyzer import RecognizerResult
from scrapy.exceptions import NotConfigured

from property_scraper.pii_filter import PiiFilter, _drop_address_persons
from property_scraper.pipelines import PiiFilterPipeline

_DEFAULT_ENTITIES = ["PHONE_NUMBER", "EMAIL_ADDRESS", "URL", "PL_PESEL"]


def _make_crawler(**overrides: Any) -> MagicMock:
    """Build a minimal fake Scrapy crawler with configurable settings."""
    settings: dict[str, Any] = {
        "PII_ENABLED": True,
        "PII_ENTITIES": list(_DEFAULT_ENTITIES),
        "PII_LANGUAGE": "en",
        "PII_NLP_MODEL": "en_core_web_sm",
        "PII_SCORE_THRESHOLD": 0.0,
        **overrides,
    }
    crawler = MagicMock()
    crawler.settings.getbool.side_effect = lambda key, default=True: settings.get(key, default)
    crawler.settings.getlist.side_effect = lambda key, default=None: settings.get(key, default)
    crawler.settings.get.side_effect = lambda key, default=None: settings.get(key, default)
    crawler.settings.getfloat.side_effect = lambda key, default=0.0: settings.get(key, default)
    crawler.settings.getdict.side_effect = lambda key, default=None: settings.get(key, default)
    return crawler


# ── Helpers ────────────────────────────────────────────────────────────────

def _person(start: int, end: int) -> RecognizerResult:
    return RecognizerResult(entity_type="PERSON", start=start, end=end, score=0.85)


def _phone(start: int, end: int) -> RecognizerResult:
    return RecognizerResult(entity_type="PHONE_NUMBER", start=start, end=end, score=0.75)


def _email(start: int, end: int) -> RecognizerResult:
    return RecognizerResult(entity_type="EMAIL_ADDRESS", start=start, end=end, score=0.90)


# ── _drop_address_persons unit tests ────────────────────────────────────────

class TestDropAddressPersons:
    """Pure-function tests — no Presidio engines are instantiated."""

    # ── Should DROP: street prefix immediately before entity ──

    @pytest.mark.parametrize("text, start, end", [
        # ul. / ulica variants
        ("mieszkanie przy ul. Jana Kowalskiego", 20, 35),
        ("mieszkanie przy ul Jana Kowalskiego", 19, 34),
        ("mieszkanie przy ulica Jana Kowalskiego", 21, 36),
        # al. / aleja / aleje
        ("przy al. Niepodległości 12", 9, 24),
        ("przy aleja Niepodległości 12", 11, 26),
        ("przy aleje Niepodległości 12", 11, 26),
        # os. / osiedle
        ("os. Mickiewicza, blok 3", 4, 14),
        ("osiedle Mickiewicza, blok 3", 8, 18),
        # pl. / plac
        ("pl. Wolności 1", 4, 12),
        ("plac Wolności 1", 5, 13),
        # rondo
        ("rondo Mogilskie 2", 6, 14),
        # skwer
        ("skwer Niepodległości", 6, 19),
        # park
        ("park Kościuszki", 5, 14),
        # bulwar
        ("bulwar Czerwieński", 7, 17),
        # brama
        ("brama Floriańska", 6, 15),
        # droga / szosa / boczna
        ("droga Królewska", 6, 14),
        ("szosa Krakowska", 6, 14),
        ("boczna Jana Pawła", 7, 16),
        # Case-insensitive
        ("przy UL. Jana Kowalskiego", 9, 24),
        ("przy Ul. Jana Kowalskiego", 9, 24),
        # Extra whitespace between prefix and name
        ("ul.  Jana Kowalskiego", 5, 20),
    ])
    def test_drops_person_after_street_prefix(self, text: str, start: int, end: int) -> None:
        results = [_person(start, end)]
        assert _drop_address_persons(text, results) == []

    # ── Should KEEP: real person (no street prefix) ──

    @pytest.mark.parametrize("text, start, end", [
        # Name appears in isolation
        ("skontaktuj się z Janem Kowalskim", 17, 31),
        # Name at the very start of the string
        ("Jana Kowalska proponuje", 0, 13),
        # Street prefix is too far back (> 30 chars before entity start)
        ("ul. " + "x" * 30 + "Jana Kowalskiego", 34, 50),
        # Prefix is a substring of a longer word (not a word boundary)
        ("ul. to skrót; tutaj Kowalski", 20, 28),  # prefix > 30 chars before entity
    ])
    def test_keeps_person_without_street_prefix(self, text: str, start: int, end: int) -> None:
        results = [_person(start, end)]
        assert _drop_address_persons(text, results) == results

    # ── Non-PERSON entities pass through unconditionally ──

    def test_phone_always_kept(self) -> None:
        text = "ul. 500-123-456"  # contrived but prefix present
        results = [_phone(4, 15)]
        assert _drop_address_persons(text, results) == results

    def test_email_always_kept(self) -> None:
        text = "ul. test@example.com"
        results = [_email(4, 20)]
        assert _drop_address_persons(text, results) == results

    # ── Mixed lists ──

    def test_mixed_drops_only_street_persons(self) -> None:
        text = "ul. Jana Pawła II, zadzwoń 500-123-456"
        # PERSON at 4..16, PHONE at 27..38
        results = [_person(4, 16), _phone(27, 38)]
        out = _drop_address_persons(text, results)
        assert len(out) == 1
        assert out[0].entity_type == "PHONE_NUMBER"

    def test_keeps_standalone_person_alongside_phone(self) -> None:
        text = "Jan Kowalski, tel. 500-123-456"
        results = [_person(0, 12), _phone(19, 30)]
        out = _drop_address_persons(text, results)
        assert len(out) == 2

    # ── Edge cases ──

    def test_empty_results_list(self) -> None:
        assert _drop_address_persons("jakiś tekst", []) == []

    def test_empty_text_with_no_results(self) -> None:
        assert _drop_address_persons("", []) == []

    def test_person_at_start_of_string_is_kept(self) -> None:
        # look_behind is empty string — regex cannot match
        results = [_person(0, 8)]
        assert _drop_address_persons("Kowalski mieszka tu", results) == results

    def test_prefix_without_dot(self) -> None:
        # "ul " (no dot) should still trigger
        text = "ul Jana Kowalskiego 5"
        results = [_person(3, 18)]
        assert _drop_address_persons(text, results) == []

    def test_multiple_persons_selective_drop(self) -> None:
        # Two PERSON spans: one after street prefix, one standalone
        text = "Jan Nowak mieszka przy ul. Jana Kowalskiego"
        # "Jan Nowak" at 0..8, "Jana Kowalskiego" at 27..43
        results = [_person(0, 8), _person(27, 43)]
        out = _drop_address_persons(text, results)
        assert len(out) == 1
        assert out[0].start == 0


# ── PiiFilter.clean integration smoke tests ─────────────────────────────────

@pytest.fixture(scope="module")
def pii_filter() -> PiiFilter:
    """Module-scoped fixture: engine loaded once for the whole test session."""
    return PiiFilter()


class TestPiiFilterClean:
    """Integration tests — verify clean() delegates correctly to the filter."""

    def test_returns_none_for_none(self, pii_filter: PiiFilter) -> None:
        assert pii_filter.clean(None) is None

    def test_returns_empty_string_unchanged(self, pii_filter: PiiFilter) -> None:
        assert pii_filter.clean("") == ""

    def test_redacts_phone(self, pii_filter: PiiFilter) -> None:
        result = pii_filter.clean("Zadzwoń 500-123-456")
        assert "500" not in result
        assert "<PHONE_NUMBER>" in result

    def test_redacts_email(self, pii_filter: PiiFilter) -> None:
        result = pii_filter.clean("Kontakt: jan@example.com")
        assert "jan@example.com" not in result
        assert "<EMAIL_ADDRESS>" in result

    def test_redacts_url(self, pii_filter: PiiFilter) -> None:
        result = pii_filter.clean("Więcej na https://example.com/listing")
        assert "example.com" not in result

    def test_clean_text_returned_unchanged(self, pii_filter: PiiFilter) -> None:
        text = "Piękne mieszkanie, 3 pokoje, 65 m², balkon, winda."
        assert pii_filter.clean(text) == text


# ── PiiFilterPipeline.from_crawler settings tests ───────────────────────────

class TestPiiFilterPipelineFromCrawler:
    """Tests that from_crawler reads Scrapy settings and stores them."""

    def test_raises_not_configured_when_disabled(self) -> None:
        crawler = _make_crawler(PII_ENABLED=False)
        with pytest.raises(NotConfigured):
            PiiFilterPipeline.from_crawler(crawler)

    def test_enabled_by_default_does_not_raise(self) -> None:
        pipeline = PiiFilterPipeline.from_crawler(_make_crawler())
        assert pipeline is not None

    def test_stores_default_entities(self) -> None:
        pipeline = PiiFilterPipeline.from_crawler(_make_crawler())
        assert pipeline._entities == _DEFAULT_ENTITIES

    def test_stores_custom_entities(self) -> None:
        pipeline = PiiFilterPipeline.from_crawler(_make_crawler(PII_ENTITIES=["EMAIL_ADDRESS"]))
        assert pipeline._entities == ["EMAIL_ADDRESS"]

    def test_stores_default_score_threshold(self) -> None:
        pipeline = PiiFilterPipeline.from_crawler(_make_crawler())
        assert pipeline._score_threshold == 0.0

    def test_stores_custom_score_threshold(self) -> None:
        pipeline = PiiFilterPipeline.from_crawler(_make_crawler(PII_SCORE_THRESHOLD=0.75))
        assert pipeline._score_threshold == 0.75

    def test_stores_default_language(self) -> None:
        pipeline = PiiFilterPipeline.from_crawler(_make_crawler())
        assert pipeline._language == "en"

    def test_stores_custom_language(self) -> None:
        pipeline = PiiFilterPipeline.from_crawler(_make_crawler(PII_LANGUAGE="pl"))
        assert pipeline._language == "pl"

    def test_stores_default_nlp_model(self) -> None:
        pipeline = PiiFilterPipeline.from_crawler(_make_crawler())
        assert pipeline._nlp_model == "en_core_web_sm"

    def test_stores_custom_nlp_model(self) -> None:
        pipeline = PiiFilterPipeline.from_crawler(_make_crawler(PII_NLP_MODEL="pl_core_news_md"))
        assert pipeline._nlp_model == "pl_core_news_md"


# ── PiiFilter constructor param integration tests ────────────────────────────

@pytest.fixture(scope="module")
def pii_filter_email_only() -> PiiFilter:
    """PiiFilter configured to detect only email addresses."""
    return PiiFilter(entities=["EMAIL_ADDRESS"])


@pytest.fixture(scope="module")
def pii_filter_high_threshold() -> PiiFilter:
    """PiiFilter with score_threshold=0.9 — never reaches bare mobile score (0.5)."""
    return PiiFilter(score_threshold=0.9)


class TestPiiFilterCustomEntities:
    """Integration tests that entity-list config is actually respected."""

    def test_does_not_redact_phone_when_email_only(self, pii_filter_email_only: PiiFilter) -> None:
        result = pii_filter_email_only.clean("Zadzwoń 500-123-456")
        assert "500-123-456" in result

    def test_redacts_email_when_email_only(self, pii_filter_email_only: PiiFilter) -> None:
        result = pii_filter_email_only.clean("Kontakt: jan@example.com")
        assert "jan@example.com" not in result
        assert "<EMAIL_ADDRESS>" in result


class TestPiiFilterScoreThreshold:
    """Integration tests that score_threshold is passed to the analyzer."""

    def test_bare_mobile_preserved_when_below_threshold(
        self, pii_filter_high_threshold: PiiFilter
    ) -> None:
        """Bare mobile without context words scores 0.5, well below threshold 0.9."""
        result = pii_filter_high_threshold.clean("numer: 500-123-456")
        assert "500-123-456" in result

    def test_bare_mobile_redacted_at_default_threshold(self, pii_filter: PiiFilter) -> None:
        """Default threshold (0.0) + context word 'Zadzwoń' boosts score → redacted."""
        result = pii_filter.clean("Zadzwoń 500-123-456")
        assert "500-123-456" not in result


# ── PiiFilterPipeline.from_crawler operator settings tests ───────────────────

_CUSTOM_OPERATORS = {
    "PHONE_NUMBER": {"type": "replace", "new_value": "<TELEFON>"},
    "EMAIL_ADDRESS": {"type": "redact"},
    "DEFAULT": {"type": "replace", "new_value": "<PII>"},
}


class TestPiiFilterPipelineOperators:
    """Tests that from_crawler reads PII_OPERATORS and stores it."""

    def test_stores_empty_operators_by_default(self) -> None:
        pipeline = PiiFilterPipeline.from_crawler(_make_crawler())
        assert pipeline._operators == {}

    def test_stores_custom_operators(self) -> None:
        pipeline = PiiFilterPipeline.from_crawler(
            _make_crawler(PII_OPERATORS=_CUSTOM_OPERATORS)
        )
        assert pipeline._operators == _CUSTOM_OPERATORS

    def test_stores_single_operator_entry(self) -> None:
        ops = {"PHONE_NUMBER": {"type": "redact"}}
        pipeline = PiiFilterPipeline.from_crawler(_make_crawler(PII_OPERATORS=ops))
        assert pipeline._operators == ops


# ── PiiFilter operator integration tests ────────────────────────────────────

@pytest.fixture(scope="module")
def pii_filter_with_operators() -> PiiFilter:
    """PiiFilter with per-entity operator overrides."""
    return PiiFilter(
        operators={
            "PHONE_NUMBER": {"type": "replace", "new_value": "<TELEFON>"},
            "EMAIL_ADDRESS": {"type": "redact"},
            "DEFAULT": {"type": "replace", "new_value": "<PII>"},
        }
    )


class TestPiiFilterOperators:
    """Integration tests that operators config is forwarded to the anonymizer."""

    def test_phone_uses_custom_replacement_label(
        self, pii_filter_with_operators: PiiFilter
    ) -> None:
        result = pii_filter_with_operators.clean("Zadzwoń 500-123-456")
        assert "<TELEFON>" in result
        assert "500-123-456" not in result

    def test_email_is_removed_by_redact_operator(
        self, pii_filter_with_operators: PiiFilter
    ) -> None:
        result = pii_filter_with_operators.clean("Kontakt: jan@example.com")
        assert "jan@example.com" not in result
        # redact removes the span entirely — no placeholder
        assert "<EMAIL_ADDRESS>" not in result
        assert "<PII>" not in result

    def test_url_uses_default_operator(
        self, pii_filter_with_operators: PiiFilter
    ) -> None:
        """URL has no explicit operator — DEFAULT applies."""
        result = pii_filter_with_operators.clean("Więcej na https://example.com/listing")
        assert "example.com" not in result
        assert "<PII>" in result

    def test_default_behavior_without_operators(
        self, pii_filter: PiiFilter
    ) -> None:
        """No operators → Presidio default: <ENTITY_TYPE> placeholder."""
        result = pii_filter.clean("Zadzwoń 500-123-456")
        assert "<PHONE_NUMBER>" in result
