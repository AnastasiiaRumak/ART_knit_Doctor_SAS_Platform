"""
extractor.py — Извлечение триггеров из текста протокола.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, ClassVar

from measures import (
    ThresholdCheck,
    compare_with_threshold,
    find_measure_for_param,
)
from negations import NegationDetector
from preprocessor import Preprocessor

if TYPE_CHECKING:
    from config_loader import Config
    from config_loader import Finding as ConfigFinding

log = logging.getLogger("extractor")


# ============================================================================
#                        DATACLASSES
# ============================================================================


@dataclass
class Finding:
    """Найденный триггер."""

    id: str
    organ_code: str
    matched_synonym: str
    specialist: list[str]
    urgency: str
    sentence: str
    quote: str
    negated: bool = False
    negated_reason: str = ""
    size_check: ThresholdCheck | None = None
    confidence: float = 1.0

    def __repr__(self) -> str:
        spec = ", ".join(self.specialist) if self.specialist else "—"
        neg = " [ОТРИЦАНИЕ]" if self.negated else ""
        return f"Finding({self.id} → {spec}, {self.urgency}{neg})"


@dataclass
class ExtractionResult:
    """Результат извлечения."""

    findings: list[Finding] = field(default_factory=list)
    sentences_total: int = 0
    sentences: list[str] = field(default_factory=list)   # ← НОВОЕ
    organ_codes: list[str] = field(default_factory=list)
    primary_organ: str = ""

    def positive(self) -> list[Finding]:
        return [f for f in self.findings if not f.negated]

    def negative(self) -> list[Finding]:
        return [f for f in self.findings if f.negated]


# ============================================================================
#                        EXTRACTOR
# ============================================================================


class Extractor:
    """Извлекает триггеры из текста протокола УЗИ."""

    SKIP_SYNONYM_MARKERS: ClassVar[list[str]] = [
        "(морфология)",
        "морфология",
        "гистология",
    ]

    def __init__(self, config: Config):
        self.config = config
        self.preprocessor = Preprocessor(config)
        self.negation_detector = NegationDetector(
            negations=config.negations,
            negation_triggers=config.negation_triggers,
        )
        log.debug("Extractor инициализирован")

    @staticmethod
    def _stem_word(word: str) -> str:
        if len(word) <= 4:
            return word
        vowels = "аеёиоуыэюя"
        result = word
        while len(result) > 4 and result[-1] in vowels:
            result = result[:-1]
        return result

    @classmethod
    def _synonym_to_pattern(cls, synonym: str) -> str | None:
        if not synonym or len(synonym) < 3:
            return None
        syn = synonym.lower().strip()
        syn = re.sub(r"\([^)]*\)", "", syn).strip()
        if not syn:
            return None
        words = syn.split()
        parts = []
        for w in words:
            if len(w) <= 3:
                parts.append(re.escape(w))
            else:
                stem = cls._stem_word(w)
                parts.append(rf"{re.escape(stem)}[а-яё]{{0,4}}")
        body = r"\s+".join(parts)
        return rf"(?<![а-яёa-z]){body}(?![а-яёa-z])"

    @classmethod
    def _compile_synonyms(cls, synonyms: list[str]) -> list:
        result = []
        for syn in synonyms:
            pattern_str = cls._synonym_to_pattern(syn)
            if not pattern_str:
                continue
            try:
                compiled = re.compile(pattern_str, re.IGNORECASE)
                result.append((syn, compiled))
            except re.error:
                continue
        return result

    def _find_synonym_matches(
        self,
        sentence: str,
        finding: ConfigFinding,
    ) -> list[tuple[str, str]]:
        if not sentence:
            return []
        sentence_lower = sentence.lower()
        matches: list[tuple[str, str]] = []
        seen_spans: list[tuple[int, int]] = []

        compiled = getattr(finding, "compiled_synonyms", None)
        if compiled:
            for syn, pattern in compiled:
                if any(marker in syn.lower() for marker in self.SKIP_SYNONYM_MARKERS):
                    continue
                m = pattern.search(sentence_lower)
                if m:
                    matches.append((syn, m.group(0)))
                    seen_spans.append((m.start(), m.end()))
        else:
            for syn in finding.synonyms:
                if any(marker in syn.lower() for marker in self.SKIP_SYNONYM_MARKERS):
                    continue
                pattern = self._synonym_to_pattern(syn)
                if not pattern:
                    continue
                try:
                    for m in re.finditer(pattern, sentence_lower):
                        matches.append((syn, m.group(0)))
                        seen_spans.append((m.start(), m.end()))
                        break
                except re.error as e:
                    log.warning(f"Ошибка regex для '{syn}': {e}")

        if finding.regex:
            try:
                for m in re.finditer(finding.regex, sentence, re.IGNORECASE):
                    overlap = any(
                        not (m.end() <= s or m.start() >= e) for s, e in seen_spans
                    )
                    if not overlap:
                        matches.append((finding.source, m.group(0)))
                    break
            except re.error as e:
                log.warning(f"Ошибка regex {finding.regex!r}: {e}")

        return matches

    @staticmethod
    def _extract_quote(sentence: str, matched: str, context: int = 60) -> str:
        if not matched:
            return sentence[:120]
        pos = sentence.lower().find(matched.lower())
        if pos < 0:
            return sentence[:120]
        start = max(0, pos - 15)
        end = min(len(sentence), pos + len(matched) + context)
        quote = sentence[start:end].strip()
        if start > 0:
            quote = "…" + quote
        if end < len(sentence):
            quote = quote + "…"
        return quote

    def _process_finding(
        self,
        finding: ConfigFinding,
        sentence: str,
        matched_synonym: str,
        matched_text: str,
    ) -> Finding | None:
        neg_result = self.negation_detector.check(sentence, matched_synonym)
        quote = self._extract_quote(sentence, matched_text)

        if neg_result.is_negated:
            return Finding(
                id=finding.id,
                organ_code=finding.organ_code,
                matched_synonym=matched_synonym,
                specialist=[],
                urgency="negative",
                sentence=sentence,
                quote=quote,
                negated=True,
                negated_reason=neg_result.reason,
                confidence=0.0,
            )

        size_check: ThresholdCheck | None = None
        if self.config.sizes:
            size_check = self._check_size_rules(sentence, finding)

        confidence = 0.9
        if size_check and not size_check.triggered:
            confidence = 0.6
        if len(matched_text.split()) > 1:
            confidence = min(1.0, confidence + 0.05)

        return Finding(
            id=finding.id,
            organ_code=finding.organ_code,
            matched_synonym=matched_synonym,
            specialist=list(finding.specialist),
            urgency=finding.urgency,
            sentence=sentence,
            quote=quote,
            negated=False,
            negated_reason="",
            size_check=size_check,
            confidence=confidence,
        )

    def _check_size_rules(
        self,
        sentence: str,
        finding: ConfigFinding,
    ) -> ThresholdCheck | None:
        sentence_lower = sentence.lower()
        for params in self.config.sizes.values():
            for param in params:
                param_kw = param.param.lower()
                tokens = [
                    t
                    for t in re.split(r"\s+", param_kw)
                    if len(t) > 3 and t not in ("размер", "общий", "объем")
                ]
                if not tokens:
                    continue
                hit = any(tok in sentence_lower for tok in tokens)
                if not hit:
                    continue
                measure = find_measure_for_param(sentence, tokens)
                if not measure:
                    continue
                if param.threshold is not None:
                    return compare_with_threshold(
                        measure,
                        threshold=param.threshold,
                        operator=param.operator,
                        threshold_unit=param.unit,
                    )
        return None

    def extract(self, text: str) -> ExtractionResult:
        if not text:
            return ExtractionResult()

        log.info("=" * 60)
        log.info("Извлечение триггеров")
        log.info("=" * 60)

        pre = self.preprocessor.process(text)
        log.info(f"Предложений: {len(pre.sentences)}, органы: {pre.organ_codes}")

        result = ExtractionResult(
            sentences_total=len(pre.sentences),
            sentences=list(pre.sentences),        # ← НОВОЕ
            organ_codes=[],
            primary_organ=pre.primary_organ,
        )

        if pre.organ_codes:
            organ_codes_to_check = [pre.organ_codes[0]]
        else:
            organ_codes_to_check = list(self.config.organs.keys())

        for sentence in pre.sentences:
            log.debug(f"Предложение: {sentence[:80]}...")
            for organ_code in organ_codes_to_check:
                organ = self.config.organs.get(organ_code)
                if not organ:
                    continue
                for finding in organ.findings:
                    matches = self._find_synonym_matches(sentence, finding)
                    for syn, matched in matches:
                        f = self._process_finding(finding, sentence, syn, matched)
                        if f:
                            result.findings.append(f)

        result.findings = self._deduplicate(result.findings)

        real_organs = sorted(
            {f.organ_code for f in result.findings if f.organ_code and not f.negated}
        )
        if not real_organs:
            real_organs = list(pre.organ_codes)
        result.organ_codes = real_organs

        log.info(
            f"Найдено находок: {len(result.findings)} "
            f"(из них негативных: {len(result.negative())}), "
            f"органы: {result.organ_codes}"
        )

        return result

    @staticmethod
    def _deduplicate(findings: list[Finding]) -> list[Finding]:
        seen = set()
        unique = []
        sorted_findings = sorted(findings, key=lambda f: (f.negated, f.id))
        for f in sorted_findings:
            key = (f.matched_synonym.lower(), f.sentence[:60])
            if key in seen:
                continue
            seen.add(key)
            unique.append(f)
        return unique
