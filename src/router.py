"""
router.py — Построение маршрута на основе найденных триггеров.

Пайплайн:
  1. Отфильтровать позитивные находки (не отрицательные)
  2. Приоритизировать по priorities.yaml
  3. Разрешить спорные ситуации через disputes.yaml
  4. Объединить специалистов (мультидисциплинарные случаи)
  5. Определить urgency, deadline, scenario
  6. Вернуть Route

Пример:
    rt = Router(config)
    route = rt.build(extraction_result)
    print(route.specialist, route.urgency, route.deadline_days)
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from extractor import ExtractionResult, Finding

if TYPE_CHECKING:
    from config_loader import Config, DisputeEntry

log = logging.getLogger("router")


# ============================================================================
#                        DATACLASS
# ============================================================================


@dataclass
class Route:
    """Финальный маршрут пациента."""

    status: str = "pending"  # pending / no_action / assigned
    specialist: list[str] = field(default_factory=list)
    urgency: str = "planned"  # emergency / oncological / urgent / planned / observation
    deadline_days: int = 14
    scenario: str = "стандартный"  # стандартный / мягкий_сценарий / срочный_контакт

    basis: str = ""  # "УЗИ ОМТ от 26.08.2026"
    recommendation: str = ""  # "консультация гинеколога"
    finding_summary: str = ""  # "полип эндометрия 12 мм"

    primary_finding: Finding | None = None
    all_findings: list[Finding] = field(default_factory=list)

    reason: str = ""  # объяснение выбора
    quote: str = ""  # цитата из протокола

    multidisciplinary: bool = False  # True если >1 специалиста
    dispute_applied: str | None = None
    status_label: str = "ожидает решения врача"  # если применили спорную ситуацию
    unknown_sentences: list[str] = field(default_factory=list)   # ← НОВОЕ

    def is_empty(self) -> bool:
        return self.status == "no_action"

    def __repr__(self) -> str:
        spec = ", ".join(self.specialist) if self.specialist else "—"
        md = " [мультидисциплинарный]" if self.multidisciplinary else ""
        return f"Route({spec} | {self.urgency} | {self.deadline_days} дн.{md})"


# ============================================================================
#                        ROUTER
# ============================================================================


class Router:
    """
    Строит маршрут пациента из списка findings.

    Использование:
        rt = Router(config)
        route = rt.build(extraction_result)
    """

    def __init__(self, config: Config):
        self.config = config
        log.debug("Router инициализирован")

    # ------------------------------------------------------------------
    #  Приоритизация
    # ------------------------------------------------------------------

    def _priority_of(self, finding: Finding) -> int:
        """Возвращает числовой приоритет для finding."""
        # Если urgency явно указан — используем его
        urgency = finding.urgency or "planned"
        return self.config.priorities.get(urgency, 40)

    def _sort_findings(self, findings: list[Finding]) -> list[Finding]:
        """
        Сортирует findings по:
          1. Приоритету (убывание)
          2. Уверенности (убывание)
          3. Длине специализации (убывание — мультидисциплинарные важнее)
        """
        return sorted(
            findings,
            key=lambda f: (
                -self._priority_of(f),
                -f.confidence,
                -len(f.specialist),
            ),
        )

    # ------------------------------------------------------------------
    #  Спорные ситуации
    # ------------------------------------------------------------------

    def _find_dispute(self, finding: Finding) -> DisputeEntry | None:
        """
        Ищет спорную ситуацию по finding.
        Требует точного совпадения (по границам слов) или минимальной длины.
        """
        if not self.config.disputes:
            return None

        matched_syn = (finding.matched_synonym or "").lower().strip()

        # Слишком короткий синоним ("узел", "киста") — пропускаем,
        # чтобы не ловить ложные срабатывания
        if not matched_syn or len(matched_syn) < 5:
            return None

        best: DisputeEntry | None = None
        best_len = 0

        for dispute in self.config.disputes:
            for syn in dispute.synonyms:
                syn_low = syn.lower().strip()
                if not syn_low:
                    continue

                # 1. Совпадение по границам слов (не подстроку!)
                # 2. ИЛИ matched_syn целиком входит в syn_low
                pattern = r"(?<![а-яёa-z])" + re.escape(syn_low) + r"(?![а-яёa-z])"
                is_match = re.search(pattern, matched_syn) or (
                    syn_low in matched_syn and len(matched_syn) >= 5
                )
                if is_match and len(syn_low) > best_len:
                    best = dispute
                    best_len = len(syn_low)

        return best

    def _apply_dispute(
        self,
        route: Route,
        dispute: DisputeEntry,
        base_urgency: str,
    ) -> None:
        """Применяет спорную ситуацию к маршруту."""
        # Маршрут из dispute — приоритетнее
        if dispute.route_variants:
            route.specialist = list(dispute.route_variants)

        # Сценарий из dispute
        if dispute.scenario:
            scenario_map = {
                "мультидисциплинарный": "мультидисциплинарный",
                "мягкий сценарий": "мягкий_сценарий",
                "срочный контакт": "срочный_контакт",
                "плановая": "стандартный",
            }
            route.scenario = scenario_map.get(
                dispute.scenario.lower(),
                route.scenario,
            )

        # Срочность из dispute (если выше текущей)
        urgency_map = {
            "срочная": "emergency",
            "плановая": "planned",
        }
        dispute_urgency = urgency_map.get(dispute.urgency.lower(), "")
        if dispute_urgency:
            cur_prio = self.config.priorities.get(base_urgency, 40)
            new_prio = self.config.priorities.get(dispute_urgency, 40)
            if new_prio > cur_prio:
                route.urgency = dispute_urgency
                route.deadline_days = self.config.urgency_deadlines.get(
                    dispute_urgency,
                    route.deadline_days,
                )

        # Мультидисциплинарный?
        if len(route.specialist) > 1:
            route.multidisciplinary = True

        route.dispute_applied = dispute.situation

        # Объяснение
        if dispute.logic:
            route.reason = f"{route.reason} | {dispute.logic}"


    # ------------------------------------------------------------------
    #  Неопознанные находки
    # ------------------------------------------------------------------

    def _detect_unknown_findings(
        self,
        extraction: ExtractionResult,
    ) -> list[str]:
        """
        Ищет предложения, где есть маркер находки ('выявлено', 'обнаружено'),
        но известный триггер не сработал.

        Возвращает список таких предложений.
        """
        markers = getattr(self.config, "unknown_markers", None) or []
        if not markers:
            return []

        # 1. Все предложения, где уже есть распознанная позитивная находка
        recognized_sentences: set[str] = set()
        for f in extraction.findings:
            if f.negated:
                continue
            # нормализуем ключ — только начало предложения, чтобы совпадало надёжно
            recognized_sentences.add((f.sentence or "")[:120].lower())

        unknown: list[str] = []

        for sentence in extraction.sentences:
            s_low = sentence.lower()

            # 2. Есть ли маркер?
            if not any(m in s_low for m in markers):
                continue

            # 3. Уже распознано?
            if sentence[:120].lower() in recognized_sentences:
                continue

            # 4. Есть ли отрицание в этом же предложении?
            #    (проверяем через negation_detector — самые частые фразы)
            #    Если есть — пропускаем: это «не выявлено», а не находка.
            #    Простой быстрый фильтр:
            NEGATIVE_QUICK = (
                "не выявлено", "не выявлен", "не выявлена", "не выявлены",
                "не обнаружен", "не обнаружено", "не обнаружена", "не обнаружены",
                "не определяется", "не определяются",
                "не лоцируется", "не лоцируются",
                "не визуализируется", "не визуализируются",
                "не прослеживается", "не прослеживаются",
                "отсутствует", "отсутствуют",
                "без особенностей", "без изменений",
                "не изменен", "не изменена", "не изменено", "не изменены",
            )
            if any(neg in s_low for neg in NEGATIVE_QUICK):
                continue

            unknown.append(sentence)

        return unknown

    # ------------------------------------------------------------------
    #  Построение маршрута
    # ------------------------------------------------------------------

    def build(
        self,
        extraction: ExtractionResult,
        study_type: str = "УЗИ",
        study_date: str = "",
    ) -> Route:
        """
        Строит маршрут из результатов экстрактора.

        Args:
            extraction: ExtractionResult
            study_type: "УЗИ ОМТ", "УЗИ ПЖ" и т.п. (для баннера)
            study_date: "26.08.2026" (для баннера)
        """
        log.info("=" * 60)
        log.info("Построение маршрута")
        log.info("=" * 60)

        # 1. Только позитивные находки
        positives = extraction.positive()
        log.info(
            f"Позитивных находок: {len(positives)} "
            f"(отрицательных: {len(extraction.negative())})"
        )
        unknown_sentences = self._detect_unknown_findings(extraction)
        if unknown_sentences:
            log.info(
                f"Неопознанных находок: {len(unknown_sentences)} — "
                f"требуется подтверждение врача"
            )
        # 2. Если ничего нет — no_action
        # 2. Если ничего нет — no action
        if not positives:
            log.info("Находок нет — маршрут не требуется")
            return Route(
                status="no_action",
                reason="Значимых находок не выявлено",
                basis=f"{study_type} от {study_date}".strip(),
                all_findings=extraction.findings,
            )

        # 2б. Отсеиваем находки без специалиста (это нормы/наблюдения)
        actionable = [f for f in positives if f.specialist]

        # Если распознанных находок нет, но есть неопознанные —
        # НЕ отправляем в no_action, а отдаём врачу.
        if not actionable and unknown_sentences:
            log.info("Найдены неопознанные находки — требуется врач")
            return Route(
                status="pending_doctor",
                specialist=[],
                urgency="urgent",
                deadline_days=3,
                scenario="требуется_подтверждение_врача",
                basis=f"{study_type} от {study_date}".strip(),
                reason=(
                    "В протоколе есть находка, но она не распознана "
                    "автоматически. Требуется подтверждение врача."
                ),
                finding_summary="неопознанная находка",
                all_findings=extraction.findings,
                unknown_sentences=unknown_sentences,
                status_label="⚠️ Требует подтверждения врача",
            )

        if not actionable:
            log.info("Все находки — без специалиста — маршрут не требуется")
            return Route(
                status="no_action",
                reason="Значимых находок не выявлено",
                basis=f"{study_type} от {study_date}".strip(),
                all_findings=extraction.findings,
            )

        positives = actionable

        # 3. Сортировка по приоритету
        sorted_findings = self._sort_findings(positives)
        primary = sorted_findings[0]

        log.info(
            f"Приоритетная находка: {primary.id} "
            f"(специалист: {primary.specialist}, "
            f"urgency: {primary.urgency})"
        )

        # 4. Базовый маршрут
        route = Route(
            status="assigned",
            specialist=list(primary.specialist),
            urgency=primary.urgency,
            deadline_days=self.config.urgency_deadlines.get(primary.urgency, 14),
            scenario=self.config.urgency_scenarios.get(primary.urgency, "стандартный"),
            basis=f"{study_type} от {study_date}".strip(),
            recommendation=self._make_recommendation(primary),
            finding_summary=self._make_summary(primary),
            primary_finding=primary,
            all_findings=sorted_findings,
            reason=f"{primary.matched_synonym} — {self._make_recommendation(primary)}",
            quote=primary.quote,
        )

        # 5. Мультидисциплинарность (если у primary >1 специалиста)
        if len(route.specialist) > 1:
            route.multidisciplinary = True

        # 6. Применяем спорные ситуации
        #    — для primary ищем dispute
        dispute = self._find_dispute(primary)
        if dispute:
            log.info(f"Применена спорная ситуация: {dispute.situation}")
            self._apply_dispute(route, dispute, primary.urgency)

            # 7. Объединяем специалистов ТОЛЬКО из finding'ов того же органа,
        #    что и primary (чтобы не подмешивать случайные совпадения)
        all_specialists = set(route.specialist)
        primary_organ = getattr(primary, "organ_code", "") or ""

        for f in sorted_findings[1:]:
            # Только тот же орган
            f_organ = getattr(f, "organ_code", "") or ""
            if primary_organ and f_organ != primary_organ:
                continue

            f_prio = self._priority_of(f)
            route_prio = self.config.priorities.get(route.urgency, 40)
            if f_prio >= route_prio - 20:
                all_specialists.update(f.specialist)

        # Пересобираем список специалистов
        route.specialist = sorted(all_specialists)
        if len(route.specialist) > 1:
            route.multidisciplinary = True

        # 8. Уточняем urgency, если среди находок есть более срочная
        for f in sorted_findings:
            f_urgency = f.urgency or "planned"
            if self.config.priorities.get(f_urgency, 0) > self.config.priorities.get(
                route.urgency, 0
            ):
                route.urgency = f_urgency
                route.deadline_days = self.config.urgency_deadlines.get(
                    f_urgency, route.deadline_days
                )
                route.scenario = self.config.urgency_scenarios.get(
                    f_urgency, route.scenario
                )
        # 8б. Неопознанные находки — если есть, помечаем и требуем врача
        if unknown_sentences:
            route.unknown_sentences = unknown_sentences
            # Помечаем как спорную ситуацию
            if route.dispute_applied:
                route.dispute_applied += " + неопознанная находка"
            else:
                route.dispute_applied = "неопознанная находка"
            route.reason = (
                f"{route.reason} | В протоколе есть находка без чёткого правила — "
                f"требуется подтверждение врача"
            )

        # 9. Финальная проверка мультидисциплинарности
        if route.unknown_sentences and route.urgency == "planned":
            # Неопознанная находка — как минимум urgent
            route.urgency = "urgent"
            route.deadline_days = min(route.deadline_days, 3)
            route.status_label = "⚠️ Требует подтверждения врача"
        elif route.urgency == "emergency":
            route.status_label = "🚨 Требуется срочный контакт"
        elif route.urgency == "oncological":
            route.status_label = "⚠️ Онконастороженность"
        elif route.urgency == "urgent":
            route.status_label = "⏰ Требуется ускоренное решение"
        elif route.multidisciplinary:
            route.status_label = "👥 Мультидисциплинарный консилиум"
        else:
            route.status_label = "📅 Ожидает решения врача"

        log.info(f"Маршрут: {route} | {route.status_label}")
        return route

    # ------------------------------------------------------------------
    #  Вспомогательные
    # ------------------------------------------------------------------

    @staticmethod
    def _make_recommendation(finding: Finding) -> str:
        """'консультация гинеколога' / 'консультация гинеколога, хирурга'."""
        if not finding.specialist:
            return "требуется уточнение"
        specs = ", ".join(s.lower() for s in finding.specialist)
        return f"консультация {specs}"

    @staticmethod
    def _make_summary(finding: Finding) -> str:
        """Краткое описание находки для баннера."""
        parts = [finding.matched_synonym]
        if finding.size_check:
            sc = finding.size_check
            parts.append(f"{sc.value} {sc.unit}")
        return " ".join(parts)


# ============================================================================
#                        ТЕСТ
# ============================================================================

if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    )

    import sys
    from pathlib import Path

    sys.path.insert(0, str(Path(__file__).parent))

    from config_loader import ConfigLoader
    from extractor import Extractor

    project_root = Path(__file__).resolve().parent.parent
    loader = ConfigLoader(str(project_root / "config"))
    cfg = loader.load()

    ext = Extractor(cfg)
    rt = Router(cfg)

    # --- Тестовые протоколы ---
    tests = [
        (
            "ОМТ (полип)",
            "УЗИ органов малого таза от 26.08.2026",
            """
            УЗИ органов малого таза.
            В полости матки лоцируется гиперэхогенное образование 12 мм —
            полип эндометрия.
            ЗАКЛЮЧЕНИЕ: УЗ признаки полипа эндометрия.
            Рекомендовано: консультация гинеколога.
            """,
        ),
        (
            "ОМТ (без патологии)",
            "УЗИ ОМТ от 26.08.2026",
            """
            УЗИ органов малого таза.
            Полип эндометрия не выявлен.
            Свободная жидкость в малом тазу не лоцируется.
            ЗАКЛЮЧЕНИЕ: Без патологии.
            """,
        ),
        (
            "ОМТ (реальный)",
            "УЗИ ОМТ от 08.09.2026",
            """
            УЛЬТРАЗВУКОВОЕ ИССЛЕДОВАНИЕ ОРГАНОВ МАЛОГО ТАЗА
            МАТКА: размеры - 50 х 38 х 52 мм.
            М-ЭХО - 14.0 мм, неоднородной эхоструктуры.
            ЗАКЛЮЧЕНИЕ: УЗ признаки несоответствия толщины эндометрия дню цикла,
            неоднородной эхоструктуры эндометрия, диффузных изменений миометрия.
            """,
        ),
        (
            "ЖП (полип + холестаз)",
            "УЗИ ЖП от 08.09.2026",
            """
            ЖЕЛЧНЫЙ ПУЗЫРЬ: пристеночные образования размерами 3,3 х 2,8 мм.
            В просвете определяется хлопьевидный осадок.
            ЗАКЛЮЧЕНИЕ: Полипоз и холестаз желчного пузыря.
            """,
        ),
        (
            "ПЖ (ДГПЖ + остаточная моча)",
            "УЗИ ПЖ от 08.09.2026",
            """
            УЗИ предстательной железы.
            В переходной зоне определяются аденоматозные узлы до 15 мм.
            Объем остаточной мочи 87 мл.
            ЗАКЛЮЧЕНИЕ: ДГПЖ 2 степени.
            """,
        ),
        (
            "МЖ (BI-RADS 3 + фиброаденома)",
            "УЗИ МЖ от 08.09.2026",
            """
            В правой молочной железе лоцируется фиброаденома 12 мм.
            BI-RADS 3.
            ЗАКЛЮЧЕНИЕ: Фиброаденома правой молочной железы.
            """,
        ),
        (
            "НК (стеноз)",
            "УЗИ артерий НК от 08.09.2026",
            """
            УЗИ артерий нижних конечностей.
            В ОБА определяется стеноз 55%.
            ЗАКЛЮЧЕНИЕ: Стенозирующий атеросклероз.
            """,
        ),
        (
            "Кардио (ГЛЖ + ФВ 45%)",
            "ЭхоКГ от 26.08.2026",
            """
            Эхокардиография.
            Левый желудочек: гипертрофия стенок, МЖП 14 мм.
            Фракция выброса 45%, снижена.
            Диастолическая дисфункция 1 типа.
            Легочная гипертензия, СДЛА 42 мм рт.ст.
            ЗАКЛЮЧЕНИЕ: ГЛЖ, снижение ФВ, диастолическая дисфункция.
            """,
        ),
    ]

    for label, study_type, protocol in tests:
        print("\n" + "=" * 70)
        print(f"ПРОТОКОЛ: {label}")
        print("=" * 70)

        extraction = ext.extract(protocol)
        route = rt.build(extraction, study_type=study_type, study_date="")

        print("\n→ РЕЗУЛЬТАТ:")
        print(f"   status:           {route.status}")
        print(f"   specialist:       {route.specialist}")
        print(f"   urgency:          {route.urgency}")
        print(f"   deadline_days:    {route.deadline_days}")
        print(f"   scenario:         {route.scenario}")
        print(f"   multidisciplinary: {route.multidisciplinary}")
        print(f"   dispute_applied:  {route.dispute_applied}")
        print(f"   reason:           {route.reason}")
        print(f"   finding_summary:  {route.finding_summary}")
        print(f"   quote:            {route.quote[:80]}")
        print(f"   all_findings:     {len(route.all_findings)}")
