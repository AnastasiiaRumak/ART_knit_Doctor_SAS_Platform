"""
config_loader.py — Загрузка всех YAML-конфигов в единую структуру.

Читает:
  config/triggers/*.yaml     — триггеры (ОМТ, ПЖ, МЖ, НК, ЖП, Кардио)
  config/sizes.yaml          — числовые пороги
  config/disputes.yaml       — спорные ситуации
  config/negations.yaml      — отрицания
  config/priorities.yaml     — приоритеты

Возвращает:
  Config — dataclass со всеми данными
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

log = logging.getLogger("config_loader")


# ============================================================================
#                          DATACLASSES
# ============================================================================


@dataclass
class Finding:
    """Одна находка из таблицы триггеров."""

    id: str
    synonyms: list[str]
    specialist: list[str]
    is_negative: bool
    urgency: str
    source: str
    organ_code: str = ""  # заполняется при загрузке
    regex: str | None = None  # только для cardio_regex
    # Предкомпилированные regex для синонимов (для ускорения)
    compiled_synonyms: list[tuple[str, re.Pattern]] = field(default_factory=list)


@dataclass
class OrganTriggers:
    """Триггеры для одного органа/направления."""

    organ_code: str
    organ_name: str
    keywords: list[str]
    findings: list[Finding] = field(default_factory=list)
    patterns: list[Finding] = field(default_factory=list)  # для RegEx


@dataclass
class SizeParam:
    """Один числовой параметр из sizes.yaml."""

    param: str
    normal: str
    normal_range: tuple[float | None, float | None]
    trigger_text: str
    threshold: float | None
    unit: str
    operator: str
    specialist: list[str]
    is_negative: bool


@dataclass
class DisputeEntry:
    """Одна спорная ситуация."""

    situation: str
    synonyms: list[str]
    route_variants: list[str]
    logic: str
    urgency: str
    scenario: str
    category: str


@dataclass
class Config:
    """Полный конфиг системы."""

    organs: dict[str, OrganTriggers] = field(default_factory=dict)
    sizes: dict[str, list[SizeParam]] = field(default_factory=dict)
    disputes: list[DisputeEntry] = field(default_factory=list)
    negations: list[str] = field(default_factory=list)
    negation_triggers: list[str] = field(default_factory=list)
    priorities: dict[str, int] = field(default_factory=dict)
    urgency_deadlines: dict[str, int] = field(default_factory=dict)
    urgency_scenarios: dict[str, str] = field(default_factory=dict)
    oncological_specialists: list[str] = field(default_factory=list)
    emergency_specialists: list[str] = field(default_factory=list)
    unknown_markers: list[str] = field(default_factory=list)   # ← НОВОЕ

# ============================================================================
#                          LOADER
# ============================================================================


class ConfigLoader:
    """Загружает все YAML-конфиги из директории."""

    def __init__(self, config_dir: Path | str = "./config"):
        self.config_dir = Path(config_dir)
        if not self.config_dir.exists():
            raise FileNotFoundError(f"Папка конфигов не найдена: {self.config_dir}")

    # ------------------------------------------------------------------
    #  Приватные методы
    # ------------------------------------------------------------------

    # ------------------------------------------------------------------
    #  Предкомпиляция regex для синонимов
    # ------------------------------------------------------------------

    @staticmethod
    def _stem_word(word: str) -> str:
        """Убирает падежные окончания: 'полипа' -> 'полип'."""
        if len(word) <= 4:
            return word
        vowels = "аеёиоуыэюя"
        result = word
        while len(result) > 4 and result[-1] in vowels:
            result = result[:-1]
        return result

    @classmethod
    def _synonym_to_pattern(cls, synonym: str) -> str | None:
        """Превращает синоним в regex с учётом окончаний."""
        if not synonym or len(synonym) < 3:
            return None

        syn = synonym.lower().strip()
        import re as _re

        syn = _re.sub(r"\([^)]*\)", "", syn).strip()
        if not syn:
            return None

        words = syn.split()
        parts = []
        for w in words:
            if len(w) <= 3:
                parts.append(_re.escape(w))
            else:
                stem = cls._stem_word(w)
                parts.append(rf"{_re.escape(stem)}[а-яё]{{0,4}}")

        body = r"\s+".join(parts)
        return rf"(?<![а-яёa-z]){body}(?![а-яёa-z])"

    @classmethod
    def _compile_synonyms(cls, synonyms: list) -> list:
        """Компилирует regex для всех синонимов."""
        import re as _re

        result = []
        for syn in synonyms:
            pattern_str = cls._synonym_to_pattern(syn)
            if not pattern_str:
                continue
            try:
                compiled = _re.compile(pattern_str, _re.IGNORECASE)
                result.append((syn, compiled))
            except _re.error:
                continue
        return result

    @staticmethod
    def _load_yaml(path: Path) -> dict[str, Any]:
        """Читает YAML, возвращает {} если файл пустой."""
        if not path.exists():
            log.warning(f"Файл не найден: {path}")
            return {}
        with open(path, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f)
            return data or {}

    def _load_triggers(self) -> dict[str, OrganTriggers]:
        """Загружает все triggers/*.yaml."""
        triggers_dir = self.config_dir / "triggers"
        if not triggers_dir.exists():
            log.warning(f"Папка триггеров не найдена: {triggers_dir}")
            return {}

        organs: dict[str, OrganTriggers] = {}

        for yaml_path in sorted(triggers_dir.glob("*.yaml")):
            data = self._load_yaml(yaml_path)
            if not data:
                continue

            organ_code = data.get("organ_code") or yaml_path.stem
            organ_name = data.get("organ_name", organ_code)
            keywords = data.get("keywords", [])

            organ = OrganTriggers(
                organ_code=organ_code,
                organ_name=organ_name,
                keywords=keywords,
            )

            # findings (синонимы + врач + regex)
            for f in data.get("findings", []):
                finding = Finding(
                    id=f.get("id", ""),
                    synonyms=f.get("synonyms", []),
                    specialist=f.get("specialist", []),
                    is_negative=f.get("is_negative", False),
                    urgency=f.get("urgency", "planned"),
                    source=f.get("source", ""),
                    organ_code=organ_code,
                    regex=f.get("regex"),
                )

                # Предкомпилируем regex для синонимов
                finding.compiled_synonyms = self._compile_synonyms(finding.synonyms)

                organ.findings.append(finding)
            # patterns (RegEx)
            for p in data.get("patterns", []):
                organ.patterns.append(
                    Finding(
                        id=p.get("id", ""),
                        synonyms=[],  # у RegEx нет синонимов
                        specialist=p.get("specialist", []),
                        is_negative=p.get("is_negative", False),
                        urgency=p.get("urgency", "planned"),
                        source=p.get("source", ""),
                        organ_code=organ_code,
                        regex=p.get("regex"),
                    )
                )

            organs[organ_code] = organ
            log.debug(
                f"  {organ_code}: {len(organ.findings)} находок, "
                f"{len(organ.patterns)} RegEx"
            )

        log.info(f"Загружено триггеров: {len(organs)} органов")
        return organs

    def _load_sizes(self) -> dict[str, list[SizeParam]]:
        """Загружает sizes.yaml."""
        data = self._load_yaml(self.config_dir / "sizes.yaml")
        sizes: dict[str, list[SizeParam]] = {}

        for organ_name, params in data.get("organs", {}).items():
            sizes[organ_name] = []
            for p in params:
                nr = p.get("normal_range", [None, None])
                if not isinstance(nr, (list, tuple)):
                    nr = [None, None]
                nr = (nr[0] if len(nr) > 0 else None, nr[1] if len(nr) > 1 else None)

                sizes[organ_name].append(
                    SizeParam(
                        param=p.get("param", ""),
                        normal=p.get("normal", ""),
                        normal_range=nr,
                        trigger_text=p.get("trigger_text", ""),
                        threshold=p.get("threshold"),
                        unit=p.get("unit", ""),
                        operator=p.get("operator", ">"),
                        specialist=p.get("specialist", []),
                        is_negative=p.get("is_negative", False),
                    )
                )

        total = sum(len(v) for v in sizes.values())
        log.info(
            f"Загружено числовых порогов: {len(sizes)} органов, {total} параметров"
        )
        return sizes

    def _load_disputes(self) -> list[DisputeEntry]:
        """Загружает disputes.yaml."""
        data = self._load_yaml(self.config_dir / "disputes.yaml")
        entries: list[DisputeEntry] = []

        for category, items in data.get("by_category", {}).items():
            for item in items:
                entries.append(
                    DisputeEntry(
                        situation=item.get("situation", ""),
                        synonyms=item.get("synonyms", []),
                        route_variants=item.get("route_variants", []),
                        logic=item.get("logic", ""),
                        urgency=item.get("urgency", ""),
                        scenario=item.get("scenario", ""),
                        category=category,
                    )
                )

        log.info(f"Загружено спорных ситуаций: {len(entries)}")
        return entries

    def _load_negations(self) -> tuple[list[str], list[str]]:
        """Загружает negations.yaml."""
        data = self._load_yaml(self.config_dir / "negations.yaml")
        negations = data.get("negations", [])
        triggers = data.get("negation_triggers", [])
        log.info(f"Загружено отрицаний: {len(negations)}, триггеров: {len(triggers)}")
        return negations, triggers

    def _load_priorities(self) -> dict[str, Any]:
        """Загружает priorities.yaml."""
        data = self._load_yaml(self.config_dir / "priorities.yaml")
        log.info(f"Загружены приоритеты: {len(data.get('priorities', {}))} уровней")
        return data
    def _load_unknown_markers(self) -> list[str]:
        """Загружает config/unknown_markers.yaml."""
        data = self._load_yaml(self.config_dir / "unknown_markers.yaml")
        markers = data.get("markers", [])
        log.info(f"Загружено маркеров находки: {len(markers)}")
        return markers

    # ------------------------------------------------------------------
    #  Публичный метод
    # ------------------------------------------------------------------

    def load(self) -> Config:
        """Загружает всё и возвращает Config."""
        log.info("=" * 50)
        log.info(f"Загрузка конфигов из {self.config_dir}")
        log.info("=" * 50)

        priorities_data = self._load_priorities()
        negations, neg_triggers = self._load_negations()

        config = Config(
            organs=self._load_triggers(),
            sizes=self._load_sizes(),
            disputes=self._load_disputes(),
            negations=negations,
            negation_triggers=neg_triggers,
            priorities=priorities_data.get("priorities", {}),
            urgency_deadlines=priorities_data.get("urgency_deadlines", {}),
            urgency_scenarios=priorities_data.get("urgency_scenarios", {}),
            oncological_specialists=priorities_data.get("oncological_specialists", []),
            emergency_specialists=priorities_data.get("emergency_specialists", []),
            unknown_markers=self._load_unknown_markers(),
        )

        log.info("=" * 50)
        return config


# ============================================================================
#                          БЫСТРЫЙ ТЕСТ
# ============================================================================

if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
        datefmt="%H:%M:%S",
    )
    loader = ConfigLoader(str(Path(__file__).parent.parent / "config"))
    cfg = loader.load()

    print()
    print("=== ПРОВЕРКА ===")
    print(f"Органов: {len(cfg.organs)}")
    for code, organ in cfg.organs.items():
        print(
            f"  {code:10s} {organ.organ_name:40s} "
            f"findings={len(organ.findings):3d} patterns={len(organ.patterns):3d}"
        )
    print(
        f"Размеров: {len(cfg.sizes)} органов, "
        f"{sum(len(v) for v in cfg.sizes.values())} параметров"
    )
    print(f"Споров: {len(cfg.disputes)}")
    print(f"Отрицаний: {len(cfg.negations)}")
    print(f"Приоритетов: {list(cfg.priorities.keys())}")
