"""
negations.py — Проверка отрицаний.

Логика:
  1. Если синоним встречается в предложении — проверяем контекст.
  2. Ищем отрицание в окне ±N символов вокруг синонима.
  3. Если отрицание найдено и оно "привязано" к синониму — триггер не срабатывает.
  4. Отдельно проверяем отрицание ПОСЛЕ синонима ("полип эндометрия не выявлен").

Особые случаи:
  • "не выявлено" может стоять ДО синонима ("не выявлено полип эндометрия")
  • "не выявлен" может стоять ПОСЛЕ ("полип эндометрия не выявлен")
  • "отсутствует" может стоять ПОСЛЕ ("внутрипузырный компонент отсутствует")
  • Двойное отрицание ("нельзя исключить") — это НЕ отрицание, а подозрение
  • Проверка границ слова — чтобы "однородной" не находилось внутри "неоднородной"
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass

log = logging.getLogger("negations")


# Слова-маркеры "мягкого" подозрения — НЕ считаются отрицанием
SOFT_TRIGGERS = [
    "нельзя исключить",
    "не исключено",
    "не исключается",
    "подозрение на",
    "подозрительн",
    "требует уточнения",
    "неоднозначн",
    "вероятно",
    "возможно",
    "может соответствовать",
]


@dataclass
class NegationResult:
    """Результат проверки отрицания."""

    is_negated: bool
    reason: str
    matched_phrase: str | None = None
    window: str = ""


class NegationDetector:
    """
    Определяет, отрицается ли находка в предложении.

    Пример:
        detector = NegationDetector(negations, negation_triggers)
        result = detector.check(
            sentence="Полип эндометрия не выявлен.",
            synonym="полип эндометрия",
        )
        # result.is_negated == True, reason="..."
    """

    def __init__(
        self,
        negations: list[str],
        negation_triggers: list[str] | None = None,
        window_size: int = 50,
    ):
        self.negations = sorted(negations, key=len, reverse=True)
        self.negation_triggers = negation_triggers or []
        self.window_size = window_size

        # Регекс с проверкой границ слова: чтобы "однородной" не находилось в "неоднородной"
        # (?<![а-яёa-z]) — перед фразой не должно быть буквы
        # (?![а-яёa-z])  — после фразы не должно быть буквы
        self._negation_patterns = [
            (
                n,
                re.compile(
                    r"(?<![а-яёa-z])" + re.escape(n) + r"(?![а-яёa-z])",
                    re.IGNORECASE,
                ),
            )
            for n in self.negations
        ]
        self._soft_patterns = [
            (s, re.compile(re.escape(s), re.IGNORECASE)) for s in SOFT_TRIGGERS
        ]
        self._trigger_re = (
            re.compile(
                r"\b("
                + "|".join(re.escape(t) for t in self.negation_triggers)
                + r")\b",
                re.IGNORECASE,
            )
            if self.negation_triggers
            else None
        )

    # ------------------------------------------------------------------
    #  Публичный метод
    # ------------------------------------------------------------------

    def check(self, sentence: str, synonym: str) -> NegationResult:
        """Проверяет, отрицается ли `synonym` в `sentence`."""
        if not sentence or not synonym:
            return NegationResult(False, "Пустой ввод")

        sentence_lower = sentence.lower()
        synonym_lower = synonym.lower()

        pos = sentence_lower.find(synonym_lower)
        if pos < 0:
            return NegationResult(False, "Синоним не найден в предложении")

        # 1. Мягкие триггеры — это НЕ отрицание, а подозрение
        for soft, pattern in self._soft_patterns:
            if pattern.search(sentence_lower):
                return NegationResult(
                    is_negated=False,
                    reason=f"Найден мягкий триггер '{soft}' — не отрицание, а подозрение",
                    matched_phrase=None,
                )

        # 2. Окно вокруг синонима
        window_start = max(0, pos - self.window_size)
        window_end = min(len(sentence), pos + len(synonym) + self.window_size)
        window = sentence_lower[window_start:window_end]

        # 3. Точные фразы ДО или ВОКРУГ синонима
        for phrase, pattern in self._negation_patterns:
            m = pattern.search(window)
            if not m:
                continue
            if self._is_related(window, m.start(), pos - window_start):
                return NegationResult(
                    is_negated=True,
                    reason=f"Найдено отрицание: '{phrase}'",
                    matched_phrase=phrase,
                    window=window,
                )

        # 4. Триггер-слово ("не", "нет", "без") ПРЯМО ПЕРЕД синонимом
        if self._trigger_re:
            prefix_start = max(0, pos - 30)
            prefix = sentence_lower[prefix_start:pos]
            m = self._trigger_re.search(prefix)
            if m:
                between = prefix[m.end() :]
                if not re.search(r"[.,;:!?]", between):
                    return NegationResult(
                        is_negated=True,
                        reason=f"Найден триггер '{m.group(1)}' непосредственно перед находкой",
                        matched_phrase=m.group(1),
                        window=prefix + synonym_lower,
                    )

        # 5. Отрицание ПОСЛЕ синонима ("полип эндометрия не выявлен")
        suffix_end = min(len(sentence_lower), pos + len(synonym_lower) + 40)
        suffix = sentence_lower[pos + len(synonym_lower) : suffix_end]

        for phrase, pattern in self._negation_patterns:
            m = pattern.search(suffix)
            if m and m.start() < 30:
                between = suffix[: m.start()]
                if "." not in between:
                    return NegationResult(
                        is_negated=True,
                        reason=f"Найдено отрицание после находки: '{phrase}'",
                        matched_phrase=phrase,
                        window=synonym_lower + suffix,
                    )

        return NegationResult(False, "Отрицаний не найдено")

    # ------------------------------------------------------------------
    #  Вспомогательные
    # ------------------------------------------------------------------

    @staticmethod
    def _is_related(window: str, negation_pos: int, synonym_pos: int) -> bool:
        """Проверяет, что отрицание и синоним относятся к одной части предложения."""
        if negation_pos < synonym_pos:
            between = window[negation_pos:synonym_pos]
        else:
            between = window[synonym_pos:negation_pos]

        if "." in between:
            return False
        return len(between) <= 60

    def check_batch(
        self, sentence: str, synonyms: list[str]
    ) -> dict[str, NegationResult]:
        """Проверяет сразу список синонимов."""
        return {s: self.check(sentence, s) for s in synonyms}


# ============================================================================
#                          БЫСТРЫЙ ТЕСТ
# ============================================================================

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)

    import yaml

    with open("config/negations.yaml", encoding="utf-8") as f:
        data = yaml.safe_load(f)

    detector = NegationDetector(
        negations=data.get("negations", []),
        negation_triggers=data.get("negation_triggers", []),
    )

    tests = [
        ("Полип эндометрия не выявлен.", "полип эндометрия"),
        ("Внутрипузырный компонент отсутствует.", "внутрипузырный компонент"),
        ("Образования не выявлены.", "образования"),
        ("Выявлен полип эндометрия размером 12 мм.", "полип эндометрия"),
        ("Нельзя исключить полип эндометрия.", "полип эндометрия"),
        ("Подозрение на полип эндометрия.", "полип эндометрия"),
        ("Почки без особенностей. В матке полип эндометрия.", "полип эндометрия"),
        ("М-эхо 14 мм, неоднородной эхоструктуры.", "неоднородной эхоструктуры"),
        ("Свободная жидкость в малом тазу не лоцируется.", "свободная жидкость"),
        ("Структура не изменена.", "структура не изменена"),
    ]

    print()
    print("=" * 70)
    for sentence, synonym in tests:
        result = detector.check(sentence, synonym)
        flag = "❌ ОТРИЦАНИЕ" if result.is_negated else "✅ ТРИГГЕР"
        print(f"{flag:15s} | {sentence[:50]:50s}")
        print(f"                  синоним: {synonym}")
        print(f"                  причина: {result.reason}")
        print("-" * 70)
