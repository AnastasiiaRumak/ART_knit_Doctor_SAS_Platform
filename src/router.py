"""
router.py — Построение маршрута на основе найденных триггеров.
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

    status: str = "pending"  # pending / no_action / assigned / pending_doctor
    specialist: list[str] = field(default_factory=list)
    urgency: str = "planned"
    deadline_days: int = 14
    scenario: str = "стандартный"

    basis: str = ""
    recommendation: str = ""
    finding_summary: str = ""

    primary_finding: Finding | None = None
    all_findings: list[Finding] = field(default_factory=list)

    reason: str = ""
    quote: str = ""

    multidisciplinary: bool = False
    dispute_applied: str | None = None
    status_label: str = "ожидает решения врача"

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


# Быстрый фильтр отрицаний — чтобы "не выявлено" не считалось находкой
_NEGATIVE_QUICK = (
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


class Router:
    """Строит маршрут пациента из списка findings."""

    def __init__(self, config: Config):
        self.config = config
        log.debug("Router инициализирован")

    # ------------------------------------------------------------------
    #  Приоритизация
    # ------------------------------------------------------------------

    def _priority_of(self, finding: Finding) -> int:
        urgency = finding.urgency or "planned"
        return self.config.priorities.get(urgency, 40)

    def _sort_findings(self, findings: list[Finding]) -> list[Finding]:
        return sorted(
            findings,
            key=lambda f: (
                -self._priority_of(f),
                -f.confidence,
                -len(f.specialist),
            ),
        )

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
        """
        markers = getattr(self.config, "unknown_markers", None) or []
        if not markers:
            return []

        # Все предложения, где уже есть распознанная позитивная находка
        recognized_sentences: set[str] = set()
        for f in extraction.findings:
            if f.negated:
                continue
            recognized_sentences.add((f.sentence or "")[:120].lower())

        unknown: list[str] = []

        for sentence in extraction.sentences:
            s_low = sentence.lower()

            # 1. Есть ли маркер?
            if not any(m in s_low for m in markers):
                continue

            # 2. Уже распознано?
            if sentence[:120].lower() in recognized_sentences:
                continue

            # 3. Есть ли отрицание в этом же предложении?
            if any(neg in s_low for neg in _NEGATIVE_QUICK):
                continue

            unknown.append(sentence)

        return unknown

    # ------------------------------------------------------------------
    #  Спорные ситуации
    # ------------------------------------------------------------------

    def _find_dispute(self, finding: Finding) -> DisputeEntry | None:
        if not self.config.disputes:
            return None
        matched_syn = (finding.matched_synonym or "").lower().strip()
        if not matched_syn or len(matched_syn) < 5:
            return None

        best: DisputeEntry | None = None
        best_len = 0
        for dispute in self.config.disputes:
            for syn in dispute.synonyms:
                syn_low = syn.lower().strip()
                if not syn_low:
                    continue
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
        if dispute.route_variants:
            route.specialist = list(dispute.route_variants)
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
                    dispute_urgency, route.deadline_days,
                )
        if len(route.specialist) > 1:
            route.multidisciplinary = True
        route.dispute_applied = dispute.situation
        if dispute.logic:
            route.reason = f"{route.reason} | {dispute.logic}"

    # ------------------------------------------------------------------
    #  Построение маршрута
    # ------------------------------------------------------------------

    def build(
        self,
        extraction: ExtractionResult,
        study_type: str = "УЗИ",
        study_date: str = "",
    ) -> Route:
        log.info("=" * 60)
        log.info("Построение маршрута")
        log.info("=" * 60)

        # 1. Позитивные находки
        positives = extraction.positive()
        log.info(
            f"Позитивных находок: {len(positives)} "
            f"(отрицательных: {len(extraction.negative())})"
        )

        # 1б. Неопознанные находки
        unknown_sentences = self._detect_unknown_findings(extraction)
        if unknown_sentences:
            log.info(
                f"Неопознанных находок: {len(unknown_sentences)} — "
                f"требуется подтверждение врача"
            )

        # 2. Если вообще ничего нет
        if not positives:
            # НО: если есть неопознанные — отдаём врачу, а не в no_action
            if unknown_sentences:
                log.info("Нет распознанных, но есть неопознанные — врач")
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
            log.info("Находок нет — маршрут не требуется")
            return Route(
                status="no_action",
                reason="Значимых находок не выявлено",
                basis=f"{study_type} от {study_date}".strip(),
                all_findings=extraction.findings,
            )

        # 2б. Отсеиваем находки без специалиста
        actionable = [f for f in positives if f.specialist]

        # Если распознанных нет, но есть неопознанные — врач
        if not actionable and unknown_sentences:
            log.info("Распознанные без специалиста + неопознанные — врач")
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

        # 3. Сортировка
        sorted_findings = self._sort_findings(positives)
        primary = sorted_findings[0]

        log.info(
            f"Приоритетная находка: {primary.id} "
            f"(специалист: {primary.specialist}, urgency: {primary.urgency})"
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

        # 5. Мультидисциплинарность
        if len(route.specialist) > 1:
            route.multidisciplinary = True

        # 6. Спорные ситуации
        dispute = self._find_dispute(primary)
        if dispute:
            log.info(f"Применена спорная ситуация: {dispute.situation}")
            self._apply_dispute(route, dispute, primary.urgency)

        # 7. Объединяем специалистов того же органа
        all_specialists = set(route.specialist)
        primary_organ = getattr(primary, "organ_code", "") or ""
        for f in sorted_findings[1:]:
            f_organ = getattr(f, "organ_code", "") or ""
            if primary_organ and f_organ != primary_organ:
                continue
            f_prio = self._priority_of(f)
            route_prio = self.config.priorities.get(route.urgency, 40)
            if f_prio >= route_prio - 20:
                all_specialists.update(f.specialist)
        route.specialist = sorted(all_specialists)
        if len(route.specialist) > 1:
            route.multidisciplinary = True

        # 8. Уточняем urgency
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

        # 8б. Неопознанные находки — помечаем
        if unknown_sentences:
            route.unknown_sentences = unknown_sentences
            if route.dispute_applied:
                route.dispute_applied += " + неопознанная находка"
            else:
                route.dispute_applied = "неопознанная находка"
            route.reason = (
                f"{route.reason} | В протоколе есть находка без чёткого правила — "
                f"требуется подтверждение врача"
            )
            # Минимум urgent для неопознанных
            if route.urgency == "planned":
                route.urgency = "urgent"
                route.deadline_days = min(route.deadline_days, 3)

        # 9. Финальный status_label
        if route.unknown_sentences:
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

    @staticmethod
    def _make_recommendation(finding: Finding) -> str:
        if not finding.specialist:
            return "требуется уточнение"
        specs = ", ".join(s.lower() for s in finding.specialist)
        return f"консультация {specs}"

    @staticmethod
    def _make_summary(finding: Finding) -> str:
        parts = [finding.matched_synonym]
        if finding.size_check:
            sc = finding.size_check
            parts.append(f"{sc.value} {sc.unit}")
        return " ".join(parts)
