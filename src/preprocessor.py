"""
preprocessor.py — Подготовка текста протокола к анализу.

Задачи:
  1. Нормализация: регистр, ё→е, унификация символов
  2. Разбивка на предложения (с учётом сокращений "см.", "мм.", "т.е")
  3. Определение органа по ключевым словам (со стеммингом)
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from config_loader import Config

log = logging.getLogger("preprocessor")


# Сокращения — НЕ разрываем предложение после них, если следующее слово строчное
ABBREVIATIONS = [
    "см",
    "мм",
    "мл",
    "кг",
    "г",
    "мг",
    "ед",
    "тыс",
    "млн",
    "т.е",
    "т.к",
    "т.д",
    "т.п",
    "др",
    "рис",
    "табл",
    "стр",
    "им",
    "г-н",
    "г-жа",
    "ул",
    "кв",
    "корп",
    "оф",
    "н/д",
    "б/н",
    "ч/з",
    "и.о",
    "в.и",
    "г.в",
]

# Унификация символов. ВНИМАНИЕ: НЕ заменяем русскую "х" на латинскую "x"!
CHAR_REPLACEMENTS = {
    "ё": "е",
    "Ё": "Е",
    "\u00a0": " ",  # неразрывный пробел
    "\u2013": "-",  # en dash
    "\u2014": "-",  # em dash
    "\u2018": "'",
    "\u2019": "'",
    "\u201c": '"',
    "\u201d": '"',
    "×": "x",  # знак умножения U+00D7
}


@dataclass
class PreprocessedText:
    """Результат предобработки."""

    original: str
    normalized: str
    sentences: list[str] = field(default_factory=list)
    organ_codes: list[str] = field(default_factory=list)
    organ_scores: dict[str, int] = field(default_factory=dict)
    primary_organ: str = ""


class Preprocessor:
    """
    Подготавливает текст протокола УЗИ к анализу.

    Пример:
        pre = Preprocessor(config)
        result = pre.process("УЗИ ОМТ: М-эхо 14 мм...")
        for s in result.sentences:
            print(s)
    """

    def __init__(self, config: Config | None = None):
        self.config = config
        # Предкомпилированные regex для keywords органов
        self._compiled_keywords: dict[str, list] = {}
        self._compile_organ_keywords()

    def _compile_organ_keywords(self) -> None:
        """Компилирует regex для keywords всех органов один раз."""
        if not self.config or not self.config.organs:
            return

        for code, organ in self.config.organs.items():
            keywords = getattr(organ, "keywords", []) or []
            compiled = []
            for kw in keywords:
                pattern_str = self._keyword_to_pattern(kw)
                if not pattern_str:
                    continue
                try:
                    compiled.append(re.compile(pattern_str, re.IGNORECASE))
                except re.error:
                    continue
            self._compiled_keywords[code] = compiled

    # ------------------------------------------------------------------
    #  Нормализация
    # ------------------------------------------------------------------

    @staticmethod
    def normalize(text: str) -> str:
        """Нормализует текст: унификация символов, схлопывание пробелов."""
        if not text:
            return ""
        for src, dst in CHAR_REPLACEMENTS.items():
            text = text.replace(src, dst)
        text = re.sub(r"[ \t]+", " ", text)
        text = "\n".join(line.strip() for line in text.split("\n"))
        text = re.sub(r"\n{3,}", "\n\n", text)
        return text.strip()

    # ------------------------------------------------------------------
    #  Разбивка на предложения
    # ------------------------------------------------------------------

    def split_sentences(self, text: str) -> list[str]:
        """
        Разбивает текст на предложения.

        Учитывает:
          • Точки в сокращениях (см., мм., т.е.) — только если следующее слово строчное
          • Точки в числах (14.0)
          • Точки в датах (08.09.2026)
          • Переносы строк
        """
        if not text:
            return []

        protected = text

        # Защищаем числа с точкой: 14.0
        protected = re.sub(
            r"\b(\d+)\.(\d+)",
            r"\1<<DOT>>\2",
            protected,
        )
        # Защищаем даты: 08.09.2026
        protected = re.sub(
            r"\b(\d{1,2})\.(\d{1,2})\.(\d{2,4})",
            r"\1<<DOT>>\2<<DOT>>\3",
            protected,
        )
        # Защищаем сокращения ТОЛЬКО если следующее слово со строчной буквы
        for abbr in ABBREVIATIONS:
            # Защищаем сокращение, только если следующее слово со строчной буквы
            # (не используем IGNORECASE — иначе [а-я] матчит и заглавные)
            protected = re.sub(
                rf"\b{re.escape(abbr)}\.(?!\s*[А-ЯЁA-Z])",
                f"{abbr}<<DOT>>",
                protected,
            )

        # Разделители предложений
        protected = re.sub(r"([.!?;])\s+", r"\1<<SPLIT>>", protected)
        protected = re.sub(r"\n{2,}", "<<SPLIT>>", protected)

        parts = re.split(r"<<SPLIT>>", protected)

        sentences = []
        for part in parts:
            part = part.replace("<<DOT>>", ".").strip()
            part = re.sub(r"\s+", " ", part)
            if len(part) > 3:
                sentences.append(part)

        return sentences

    # ------------------------------------------------------------------
    #  Стемминг ключевых слов
    # ------------------------------------------------------------------

    @staticmethod
    def _stem_word(word: str) -> str:
        """
        Отрезает от слова падежные окончания.
        'предстательная' → 'предстательн'
        'железа'          → 'желез'
        'яичник'          → 'яичник'  (не режем — согласная на конце)
        'тела'            → 'тел'
        'тело'            → 'тел'
        """
        if len(word) <= 4:
            return word

        # Убираем все гласные с конца, но оставляем минимум 4 символа
        vowels = "аеёиоуыэюя"
        result = word
        while len(result) > 4 and result[-1] in vowels:
            result = result[:-1]
        return result

    @classmethod
    def _keyword_to_pattern(cls, keyword: str) -> str | None:
        """
        Превращает ключевое слово в regex с учётом падежных окончаний.

        'предстательная железа' → 'предстательн[а-яё]{0,4}\\s+желез[а-яё]{0,4}'
        'пж'                    → 'пж'
        """
        if not keyword:
            return None

        kw = keyword.lower().strip()
        words = kw.split()

        # Короткие аббревиатуры (≤3 буквы) — матчим точно
        if len(kw) <= 3 and len(words) == 1:
            return re.escape(kw)

        parts = []
        for w in words:
            if len(w) <= 3:
                # Короткие слова — как есть
                parts.append(re.escape(w))
            else:
                stem = cls._stem_word(w)
                # Экранируем основу, разрешаем окончание до 4 букв
                parts.append(rf"{re.escape(stem)}[а-яё]{{0,4}}")

        body = r"\s+".join(parts)
        return rf"(?<![а-яёa-z]){body}(?![а-яёa-z])"

    # ------------------------------------------------------------------
    #  Определение органа
    # ------------------------------------------------------------------

    def detect_organs(self, text: str) -> tuple[list[str], dict[str, int]]:
        """
        Определяет органы по ключевым словам (со стеммингом).
        """
        if not self.config or not self.config.organs:
            return [], {}

        text_lower = text.lower()
        scores: dict[str, int] = {}

        for code in self.config.organs:
            # Используем предкомпилированные regex
            compiled = self._compiled_keywords.get(code, [])
            score = 0
            for pattern in compiled:
                score += len(pattern.findall(text_lower))
            if score > 0:
                scores[code] = score

        sorted_codes = sorted(scores, key=lambda c: -scores[c])
        return sorted_codes, scores

    # ------------------------------------------------------------------
    #  Главный метод
    # ------------------------------------------------------------------

    def process(self, text: str) -> PreprocessedText:
        """Полный цикл предобработки."""
        if not text:
            return PreprocessedText(original="", normalized="")

        normalized = self.normalize(text)
        sentences = self.split_sentences(normalized)
        # Орган обычно упоминается в начале — ищем в первых 5000 символов
        organ_codes, scores = self.detect_organs(normalized)

        # Первичный орган — с максимальным счётом
        primary = organ_codes[0] if organ_codes else ""

        return PreprocessedText(
            original=text,
            normalized=normalized,
            sentences=sentences,
            organ_codes=organ_codes,
            organ_scores=scores,
            primary_organ=primary,
        )


# ============================================================================
#                        ТЕСТ
# ============================================================================

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)

    import sys
    from pathlib import Path

    sys.path.insert(0, str(Path(__file__).parent))
    from config_loader import ConfigLoader

    project_root = Path(__file__).resolve().parent.parent
    loader = ConfigLoader(str(project_root / "config"))
    cfg = loader.load()

    pre = Preprocessor(cfg)

    print()
    print("=" * 70)
    print("ТЕСТ 1: Нормализация")
    print("=" * 70)

    raw = "УЗИ ОМТ: М-ЭХО — 14.0 мм, неоднородной эхоструктуры."
    normalized = pre.normalize(raw)
    print(f"Исходный:        {raw}")
    print(f"Нормализованный: {normalized}")

    print()
    print("=" * 70)
    print("ТЕСТ 2: Разбивка на предложения")
    print("=" * 70)

    text = """
    УЗИ органов малого таза.
    М-ЭХО - 14.0 мм, неоднородной эхоструктуры.
    Размеры матки 50 х 38 х 52 мм. Свободная жидкость в малом тазу не лоцируется.
    ЗАКЛЮЧЕНИЕ: УЗ признаки несоответствия толщины эндометрия дню цикла.
    Рекомендовано: консультация гинеколога.
    """
    sentences = pre.split_sentences(pre.normalize(text))
    for i, s in enumerate(sentences, 1):
        print(f"  {i}. {s}")

    print()
    print("=" * 70)
    print("ТЕСТ 3: Определение органа (со стеммингом)")
    print("=" * 70)

    protocols = {
        "ОМТ": "УЗИ органов малого таза. М-ЭХО 14 мм. Размеры матки 50х38х52 мм.",
        "ПЖ": "УЗИ предстательной железы. Объем 64 см3. Остаточная моча 87 мл.",
        "ПЖ-2": "УЗИ предстательной железы, размеры 45x38x42 мм, объем 47 см3.",
        "МЖ": "УЗИ молочных желез. BI-RADS 3. Фиброаденома 12 мм.",
        "НК": "УЗИ артерий нижних конечностей. Стеноз ОБА 55%.",
        "ЖП": "УЗИ желчного пузыря. Полип 8 мм. Конкременты.",
        "Кардио": "Эхокардиография. Гипертрофия ЛЖ. ФВ 45%.",
    }

    for label, txt in protocols.items():
        result = pre.process(txt)
        print(f"\n{label}: {txt[:60]}...")
        print(f"  Органы: {result.organ_codes}")
        print(f"  Scores: {result.organ_scores}")

    print()
    print("=" * 70)
    print("ТЕСТ 4: Полный протокол (реальный)")
    print("=" * 70)

    protocol = """
    УЛЬТРАЗВУКОВОЕ ИССЛЕДОВАНИЕ ОРГАНОВ МАЛОГО ТАЗА
    МАТКА:
    положение - срединное, отклонена - кпереди, форма - седловидная
    Размеры - 50 х 38 х 52 мм.
    Структура миометрия - диффузно-неоднородная, эхогенность средняя.
    М-ЭХО - 14.0 мм, неоднородной эхоструктуры, с анэхогенными мелкими включениями.
    ПРАВЫЙ ЯИЧНИК: Размеры - 35 х 22 х 29 мм, V - 12.0 мл, структура не изменена.
    ЛЕВЫЙ ЯИЧНИК: Размеры - 28 х 14 х 25 мм, V - 5.0 мл.
    Свободная жидкость в малом тазу: не лоцируется.
    ЗАКЛЮЧЕНИЕ: УЗ признаки несоответствия толщины эндометрия дню цикла,
    неоднородной эхоструктуры эндометрия, диффузных изменений миометрия.
    Рекомендовано: консультация и наблюдение гинеколога.
    """

    result = pre.process(protocol)
    print(f"Всего предложений: {len(result.sentences)}")
    print(f"Органы: {result.organ_codes}")
    print(f"Scores: {result.organ_scores}")
    print()
    print("Предложения:")
    for i, s in enumerate(result.sentences, 1):
        print(f"  {i}. {s}")
