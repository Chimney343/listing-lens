"""PII detection and redaction for scraped listing text.

Only free-text fields (title, description) are scrubbed.
Structured address fields (street, city, district) are intentionally
preserved — they are identity fields used in the dedup hash.

Stage B (future): add PERSON detection by configuring a Polish spaCy model:
    poetry run python -m spacy download pl_core_news_md
Then add "PERSON" to ENTITIES and pass the Polish NlpEngine to AnalyzerEngine.
"""

from __future__ import annotations

import re

from presidio_analyzer import AnalyzerEngine, Pattern, PatternRecognizer, RecognizerRegistry, RecognizerResult
from presidio_analyzer.nlp_engine import NlpEngineProvider
from presidio_analyzer.predefined_recognizers import (
    EmailRecognizer,
    PhoneRecognizer,
    PlPeselRecognizer,
    UrlRecognizer,
)
from presidio_anonymizer import AnonymizerEngine
from presidio_anonymizer.entities import OperatorConfig

# Regex-based recognizers are language-agnostic; no Polish NLP model required.
# LOCATION is excluded — Polish descriptions legitimately reference district
# and neighbourhood names that would generate excessive false positives.
DEFAULT_ENTITIES = ["PHONE_NUMBER", "EMAIL_ADDRESS", "URL", "PL_PESEL"]

# Polish street type prefixes — a PERSON entity immediately following any of
# these is a street name, not an individual (e.g. "ul. Jana Pawła II").
# The regex matches the prefix at the END of a look-behind window so spacing
# and optional dot variants are all handled.
_STREET_PREFIX_RE = re.compile(
    r"\b(ul|ulica|al|aleja|aleje|os|osiedle|pl|plac|rondo|skwer|park|bulwar|"
    r"boczna|droga|szosa|brama)\s*\.?\s*$",
    re.IGNORECASE,
)


def _drop_address_persons(
    text: str, results: list[RecognizerResult]
) -> list[RecognizerResult]:
    """Remove PERSON results immediately preceded by a Polish street type prefix.

    Polish addresses like "ul. Jana Pawła II", "os. Mickiewicza", or
    "al. Niepodległości" trigger PERSON detection on the name tokens.
    The street-type prefix is a reliable sentinel that the capitalised span
    that follows is a toponym, not a real person.

    Looks back at most 30 characters before the entity start to find a prefix.
    All other entity types pass through unchanged.
    """
    out = []
    for result in results:
        if result.entity_type == "PERSON":
            look_behind = text[max(0, result.start - 30) : result.start]
            if _STREET_PREFIX_RE.search(look_behind):
                continue
        out.append(result)
    return out


# Polish mobile numbers without country-code prefix, e.g. "500 123 456".
# Score 0.5 (medium confidence) — boosted to 0.85 when context words are present.
_BARE_PL_MOBILE_PATTERN = Pattern(
    name="PL_bare_mobile",
    regex=r"\b[4-9]\d{2}[\s\-]?\d{3}[\s\-]?\d{3}\b",
    score=0.5,
)
_BARE_PL_MOBILE_CONTEXT = [
    "telefon", "tel", "tel.", "kom", "komórka",
    "zadzwoń", "dzwoń", "kontakt", "napisz",
]


class PiiFilter:
    """Wraps Presidio engines for PII detection and redaction.

    Initialisation is expensive (~0.5 s) due to spaCy model loading.
    Instantiate once per spider run via open_spider(), not per item.
    The analyze/anonymize calls themselves are thread-safe reads.
    """

    def __init__(
        self,
        *,
        entities: list[str] | None = None,
        language: str = "en",
        nlp_model: str = "en_core_web_sm",
        score_threshold: float = 0.0,
        operators: dict[str, dict] | None = None,
    ) -> None:
        self._entities = list(entities) if entities is not None else list(DEFAULT_ENTITIES)
        self._language = language
        self._score_threshold = score_threshold
        # Build OperatorConfig map once; each entry is {"type": ..., **params}.
        self._operators: dict[str, OperatorConfig] = {
            entity: OperatorConfig(cfg["type"], {k: v for k, v in cfg.items() if k != "type"})
            for entity, cfg in (operators or {}).items()
        }

        # Explicitly specify the spaCy model to prevent presidio auto-downloading
        # en_core_web_lg (400 MB). Tokenisation is all we need — regex recognizers
        # are language-agnostic.
        _nlp_provider = NlpEngineProvider(
            nlp_configuration={
                "nlp_engine_name": "spacy",
                "models": [{"lang_code": language, "model_name": nlp_model}],
            }
        )
        nlp_engine = _nlp_provider.create_engine()

        registry = RecognizerRegistry()
        # Load only the recognizers we need; avoids noise from US-only patterns.
        registry.add_recognizer(PhoneRecognizer(supported_language=language))
        registry.add_recognizer(EmailRecognizer(supported_language=language))
        registry.add_recognizer(UrlRecognizer(supported_language=language))
        # PESEL: Polish national ID number (regex + checksum, language-agnostic).
        registry.add_recognizer(PlPeselRecognizer(supported_language=language))
        # Bare Polish mobile numbers without country-code prefix.
        registry.add_recognizer(
            PatternRecognizer(
                supported_entity="PHONE_NUMBER",
                supported_language=language,
                patterns=[_BARE_PL_MOBILE_PATTERN],
                context=_BARE_PL_MOBILE_CONTEXT,
            )
        )

        self._analyzer = AnalyzerEngine(
            registry=registry,
            nlp_engine=nlp_engine,
            supported_languages=[language],
        )
        self._anonymizer = AnonymizerEngine()

    def clean(self, text: str | None) -> str | None:
        """Return text with detected PII replaced by entity-type placeholders.

        Returns the original value unchanged when no PII is detected,
        and returns None/empty unchanged without analysis overhead.
        """
        if not text:
            return text

        results = self._analyzer.analyze(
            text=text,
            entities=self._entities,
            language=self._language,
            score_threshold=self._score_threshold,
        )
        results = _drop_address_persons(text, results)
        if not results:
            return text

        return self._anonymizer.anonymize(
            text=text,
            analyzer_results=results,
            operators=self._operators or None,
        ).text
