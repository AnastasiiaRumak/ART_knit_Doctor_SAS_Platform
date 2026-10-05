"""
numbers.py — Парсинг чисел, единиц и сравнение с порогами.

Задачи:
  1. Извлечь числа из текста: "М-эхо 14.0 мм" → 14.0
  2. Определить единицу измерения: "мм", "см", "см³", "%", "мл"
  3. Извлечь пары чисел: "узел 24×13 мм" → (24.0, 13.0)
  4. Извлечь тройки: "50 х 38 х 52 мм" → (50.0, 38.0, 52.0)
  5. Сравнить с порогом из sizes.yaml
  6. Привести единицы: 0.6 см ↔ 6.0 мм
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass

log = logging.getLogger("numbers")


# ============================================================================
#                        ЕДИНИЦЫ ИЗМЕРЕНИЯ
# ============================================================================

UNIT_ALIASES: dict[str, str] = {
    "мм": "мм",
    "мм.": "мм",
    "миллиметр": "мм",
    "миллиметров": "мм",
    "см": "см",
    "см.": "см",
    "сантиметр": "см",
    "сантиметров": "см",
    "см³": "см³",
    "см3": "см³",
    "cm3": "см³",
    "куб.см": "см³",
    "мл": "мл",
    "мл.": "мл",
    "миллилитр": "мл",
    "миллилитров": "мл",
    "см/с": "см/с",
    "см/сек": "см/с",
    "cm/s": "см/с",
    "%": "%",
    "мм рт.ст.": "мм рт.ст.",
    "мм рт ст": "мм рт.ст.",
    "": "",
}

UNIT_CONVERSION = {
    "мм": ("мм", 1.0),
    "см": ("мм", 10.0),
    "см³": ("мл", 1.0),
    "мл": ("мл", 1.0),
    "см/с": ("см/с", 1.0),
    "%": ("%", 1.0),
    "мм рт.ст.": ("мм рт.ст.", 1.0),
    "": ("", 1.0),
}


def normalize_unit(raw_unit: str) -> str:
    return UNIT_ALIASES.get(raw_unit.strip().lower(), raw_unit.strip().lower())


def convert_to_base(value: float, unit: str) -> tuple[float, str]:
    base_unit, factor = UNIT_CONVERSION.get(unit, (unit, 1.0))
    return value * factor, base_unit


# ============================================================================
#                        РЕГУЛЯРКИ
# ============================================================================

NUM = r"\d+(?:[.,]\d+)?"

# Единицы, отсортированные по длине убывания (важно!)
UNIT_RE = r"(мм рт\.?ст\.?|см/с|см/сек|см³|см3|мм|см|мл|%)"

# Пара чисел: 24×13, 24 x 13, 24х13 (разделитель — только ×/x/х, не дефис!)
PAIR_MEASURE_RE = re.compile(
    rf"({NUM})\s*[×xх]\s*({NUM})\s*({UNIT_RE})?",
    re.IGNORECASE,
)

# Тройка чисел: 50 х 38 х 52, 40×30×25
TRIPLE_MEASURE_RE = re.compile(
    rf"({NUM})\s*[×xх]\s*({NUM})\s*[×xх]\s*({NUM})\s*({UNIT_RE})?",
    re.IGNORECASE,
)

# Одиночное число с единицей
SINGLE_MEASURE_RE = re.compile(
    rf"(?<![\d.,])({NUM})\s*({UNIT_RE})?",
    re.IGNORECASE,
)

# Паттерн даты: 08.09.2026, 08.09.26, 2026-09-08
DATE_RE = re.compile(r"\d{1,2}\.\d{1,2}\.\d{2,4}|\d{4}-\d{2}-\d{2}")

# Паттерн времени: 18:30, 10:41
TIME_RE = re.compile(r"\b\d{1,2}:\d{2}\b")

# Паттерн года: 4 цифры подряд (2026)
YEAR_RE = re.compile(r"(?<!\d)\d{4}(?!\d)")


# ============================================================================
#                        DATACLASS
# ============================================================================


@dataclass
class Measure:
    value: float
    unit: str
    raw: str
    pos: int
    pair: tuple[float, float] | None = None
    triple: tuple[float, float, float] | None = None

    @property
    def base_value(self) -> float:
        val, _ = convert_to_base(self.value, self.unit)
        return val

    def __repr__(self) -> str:
        return f"Measure({self.value} {self.unit} @ {self.pos})"


# ============================================================================
#                        ПАРСЕР
# ============================================================================


def _find_date_spans(text: str) -> list[tuple[int, int]]:
    """Находит все спаны дат и времени — их нужно исключить из парсинга."""
    spans = []
    for pattern in (DATE_RE, TIME_RE):
        for m in pattern.finditer(text):
            spans.append((m.start(), m.end()))
    return spans


def _in_spans(pos: int, end: int, spans: list[tuple[int, int]]) -> bool:
    """Проверяет, попадает ли отрезок в один из исключённых спанов."""
    return any(not (end <= s or pos >= e) for s, e in spans)


def parse_measures(text: str) -> list[Measure]:
    """
    Извлекает все измерения из текста.

    Порядок (важен!):
      1. Тройки чисел (50×38×52 мм) — самый специфичный
      2. Пары чисел (24×13 мм)
      3. Одиночные числа с единицей (14.0 мм, 55%)
    """
    if not text:
        return []

    results: list[Measure] = []
    used_spans: list[tuple[int, int]] = []
    date_spans = _find_date_spans(text)

    def _overlaps(start: int, end: int) -> bool:
        return any(not (end <= s or start >= e) for s, e in used_spans)

    # 1. Тройки чисел (самый специфичный случай)
    for m in TRIPLE_MEASURE_RE.finditer(text):
        if _overlaps(m.start(), m.end()) or _in_spans(m.start(), m.end(), date_spans):
            continue
        v1 = float(m.group(1).replace(",", "."))
        v2 = float(m.group(2).replace(",", "."))
        v3 = float(m.group(3).replace(",", "."))
        unit = normalize_unit(m.group(4) or "")
        results.append(
            Measure(
                value=v1,
                unit=unit,
                raw=m.group(0).strip(),
                pos=m.start(),
                triple=(v1, v2, v3),
            )
        )
        used_spans.append((m.start(), m.end()))

    # 2. Пары чисел
    for m in PAIR_MEASURE_RE.finditer(text):
        if _overlaps(m.start(), m.end()) or _in_spans(m.start(), m.end(), date_spans):
            continue
        v1 = float(m.group(1).replace(",", "."))
        v2 = float(m.group(2).replace(",", "."))
        unit = normalize_unit(m.group(3) or "")
        results.append(
            Measure(
                value=v1,
                unit=unit,
                raw=m.group(0).strip(),
                pos=m.start(),
                pair=(v1, v2),
            )
        )
        used_spans.append((m.start(), m.end()))

    # 3. Одиночные числа
    for m in SINGLE_MEASURE_RE.finditer(text):
        if _overlaps(m.start(), m.end()):
            continue
        if _in_spans(m.start(), m.end(), date_spans):
            continue

        raw_value = m.group(1)
        raw_unit = m.group(2) or ""

        # Отсекаем годы без единиц
        if not raw_unit and len(raw_value) == 4 and raw_value.isdigit():
            continue
        # Отсекаем длинные числа без единиц (ID карт)
        if not raw_unit and len(raw_value) >= 5:
            continue
        # Отсекаем числа без единиц, если они стоят в начале предложения
        # и после них нет явного контекста измерения (простая эвристика)
        if not raw_unit:
            after = text[m.end() : m.end() + 3]
            # Если после числа идёт ":" — это, скорее всего, часть чего-то (например, "2:1")
            if ":" in after:
                continue

        value = float(raw_value.replace(",", "."))
        unit = normalize_unit(raw_unit)
        results.append(
            Measure(
                value=value,
                unit=unit,
                raw=m.group(0).strip(),
                pos=m.start(),
            )
        )
        used_spans.append((m.start(), m.end()))

    results.sort(key=lambda x: x.pos)
    return results


def parse_single_value(text: str) -> float | None:
    if not text:
        return None
    m = re.search(NUM, text)
    return float(m.group(0).replace(",", ".")) if m else None


def parse_dimensions(text: str) -> tuple[float, float, float] | None:
    if not text:
        return None
    m = TRIPLE_MEASURE_RE.search(text)
    if m:
        return (
            float(m.group(1).replace(",", ".")),
            float(m.group(2).replace(",", ".")),
            float(m.group(3).replace(",", ".")),
        )
    return None


# ============================================================================
#                        СРАВНЕНИЕ С ПОРОГОМ
# ============================================================================


@dataclass
class ThresholdCheck:
    triggered: bool
    value: float
    threshold: float
    operator: str
    unit: str
    reason: str
    converted_value: float | None = None
    converted_unit: str = ""


def compare_with_threshold(
    measure: Measure,
    threshold: float,
    operator: str,
    threshold_unit: str,
) -> ThresholdCheck:
    measure_val, measure_unit_base = convert_to_base(measure.value, measure.unit)
    threshold_val, threshold_unit_base = convert_to_base(threshold, threshold_unit)

    if (
        measure_unit_base
        and threshold_unit_base
        and measure_unit_base != threshold_unit_base
    ):
        return ThresholdCheck(
            triggered=False,
            value=measure.value,
            threshold=threshold,
            operator=operator,
            unit=measure.unit,
            reason=f"Несовместимые единицы: {measure.unit} vs {threshold_unit}",
        )

    if operator == ">":
        triggered = measure_val > threshold_val
        cmp_text = ">"
    elif operator == ">=":
        triggered = measure_val >= threshold_val
        cmp_text = "≥"
    elif operator == "<":
        triggered = measure_val < threshold_val
        cmp_text = "<"
    elif operator == "<=":
        triggered = measure_val <= threshold_val
        cmp_text = "≤"
    else:
        triggered = measure_val > threshold_val
        cmp_text = ">"

    reason = (
        f"{measure.value} {measure.unit} {cmp_text} "
        f"{threshold} {threshold_unit} → {triggered}"
    )
    if measure_unit_base != measure.unit:
        reason += f" (в базовых: {measure_val} {measure_unit_base} vs {threshold_val} {threshold_unit_base})"

    return ThresholdCheck(
        triggered=triggered,
        value=measure.value,
        threshold=threshold,
        operator=operator,
        unit=measure.unit,
        reason=reason,
        converted_value=measure_val,
        converted_unit=measure_unit_base,
    )


def find_measure_for_param(
    text: str,
    param_keywords: list[str],
) -> Measure | None:
    if not text:
        return None
    text_lower = text.lower()
    for kw in param_keywords:
        pos = text_lower.find(kw.lower())
        if pos < 0:
            continue
        window_start = pos
        window_end = min(len(text), pos + 100)
        window = text[window_start:window_end]
        measures = parse_measures(window)
        if measures:
            return measures[0]
    return None


# ============================================================================
#                        ТЕСТ
# ============================================================================

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)

    print()
    print("=" * 70)
    print("ТЕСТ 1: parse_measures (исправленный)")
    print("=" * 70)

    tests_parse = [
        "М-ЭХО - 14.0 мм, неоднородной эхоструктуры",
        "узел 24×13 мм с активным периферическим кровотоком",
        "размеры 50 х 38 х 52 мм",
        "объём предстательной железы 64 см3",
        "стеноз 55%",
        "объём остаточной мочи 87 мл",
        "размеры - 35 х 22 х 29 мм",
        "По боковым стенкам определяются аваскулярные гиперэхогенные пристеночные образования размерами 3,3 х 2,8 мм",
        "Дата приема: 08.09.2026",
        "скорость кровотока Vps 85 см/с",
        "М-эхо 14.0 мм, неоднородной эхоструктуры, с анэхогенными мелкими включениями",
    ]

    for text in tests_parse:
        measures = parse_measures(text)
        print(f"\nТекст: {text}")
        if not measures:
            print("  → (пусто)")
        for m in measures:
            extra = ""
            if m.pair:
                extra = f" [пара: {m.pair}]"
            if m.triple:
                extra = f" [тройка: {m.triple}]"
            print(f"  → {m.value} {m.unit} (raw='{m.raw}'){extra}")
