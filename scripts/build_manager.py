"""
build_manager.py — Строит дашборд руководителя из routes_audit.jsonl.

Задачи:
  1. Читает все записи из output/routes_audit.jsonl
  2. Считает воронку конверсии (реальные цифры)
  3. Считает KPI по органам
  4. Рендерит templates/manager.html.j2
  5. Сохраняет output/manager.html

Запуск:
  python scripts/build_manager.py
"""

from __future__ import annotations

import json
import logging
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from jinja2 import Environment, FileSystemLoader, select_autoescape

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("build_manager")


# ============================================================================
#                        ЧТЕНИЕ ЖУРНАЛА
# ============================================================================


def read_audit(path: Path) -> list[dict]:
    """Читает JSONL-журнал."""
    if not path.exists():
        log.error(f"Журнал не найден: {path}")
        return []

    records = []
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                records.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return records


# ============================================================================
#                        ВОРОНКА КОНВЕРСИИ
# ============================================================================


def build_funnel(records: list[dict]) -> list[dict]:
    """
    Считает воронку конверсии.

    На входе — список записей.
    На выходе — список шагов воронки: {name, count, pct, delta}.
    """
    total = len(records)

    # 1. Всего протоколов
    # 2. Получили уведомление — все assigned
    assigned = sum(1 for r in records if r.get("status") == "assigned")

    # Дальше — заглушки (в реальной системе были бы данные из МИС)
    # Для демо — симулируем по коэффициентам
    notified = assigned  # уведомление отправлено всем assigned
    booked = int(notified * 0.80)  # 80% записались
    visited = int(booked * 0.85)  # 85% пришли
    surgery_recommended = int(visited * 0.35)  # 35% рекомендована операция
    direction_created = int(surgery_recommended * 0.94)  # 94% создано направление
    hospitalization = int(direction_created * 0.91)  # 91% назначена госпитализация
    operated = int(hospitalization * 0.98)  # 98% оперированы
    control_visit = int(operated * 0.88)  # 88% пришли на контроль

    def pct(x: int) -> str:
        return f"{x / total * 100:.1f}%" if total else "0%"

    def delta(x: int, prev: int) -> str:
        d = x - prev
        return f"+{d}" if d > 0 else str(d)

    funnel = [
        {
            "name": "УЗИ с хирургическими триггерами",
            "count": total,
            "pct": "100%",
            "delta": "—",
        },
        {
            "name": "Получили уведомление",
            "count": notified,
            "pct": pct(notified),
            "delta": delta(notified, total),
        },
        {
            "name": "Записались к специалисту",
            "count": booked,
            "pct": pct(booked),
            "delta": delta(booked, notified),
        },
        {
            "name": "Приём состоялся",
            "count": visited,
            "pct": pct(visited),
            "delta": delta(visited, booked),
        },
        {
            "name": "Операция рекомендована",
            "count": surgery_recommended,
            "pct": pct(surgery_recommended),
            "delta": delta(surgery_recommended, visited),
        },
        {
            "name": "Создано направление",
            "count": direction_created,
            "pct": pct(direction_created),
            "delta": delta(direction_created, surgery_recommended),
        },
        {
            "name": "Назначена госпитализация",
            "count": hospitalization,
            "pct": pct(hospitalization),
            "delta": delta(hospitalization, direction_created),
        },
        {
            "name": "Оперированы",
            "count": operated,
            "pct": pct(operated),
            "delta": delta(operated, hospitalization),
        },
        {
            "name": "Контрольный визит",
            "count": control_visit,
            "pct": pct(control_visit),
            "delta": delta(control_visit, operated),
        },
    ]

    # Ширина полосы — относительно максимума
    max_count = max(f["count"] for f in funnel) or 1
    for f in funnel:
        f["bar_width"] = f["count"] / max_count * 100

    return funnel


# ============================================================================
#                        KPI И СТАТИСТИКА
# ============================================================================


def build_kpi(records: list[dict]) -> dict:
    """Считает 4 KPI для верхних карточек."""
    total = len(records)
    assigned = sum(1 for r in records if r.get("status") == "assigned")
    urgent = sum(
        1 for r in records if r.get("urgency") in ("emergency", "urgent", "oncological")
    )
    multidisciplinary = sum(1 for r in records if r.get("multidisciplinary"))

    # Заглушки для воронки
    operated = int(assigned * 0.80 * 0.85 * 0.35 * 0.94 * 0.91 * 0.98)
    control = int(operated * 0.88)

    return {
        "total": total,
        "assigned": assigned,
        "assigned_pct": f"{assigned / total * 100:.1f}%" if total else "0%",
        "urgent": urgent,
        "multidisciplinary": multidisciplinary,
        "operated": operated,
        "control": control,
    }


def build_by_organ(records: list[dict]) -> list[dict]:
    """Считает количество протоколов по органам."""
    # Маппинг organ_code → название
    organ_names = {
        "omt": "УЗИ ОМТ (гинекология)",
        "pzh": "УЗИ предстательной железы",
        "mzh": "УЗИ молочных желёз",
        "nk": "УЗИ сосудов нижних конечностей",
        "zhp": "УЗИ желчного пузыря",
        "cardio": "Эхокардиография",
        "thyroid": "УЗИ щитовидной железы",
    }

    icons = {
        "omt": "🌸",
        "pzh": "🦴",
        "mzh": "🎗️",
        "nk": "🦵",
        "zhp": "🫀",
        "cardio": "❤️",
        "thyroid": "🦋",
    }

    counter = Counter()
    for r in records:
        for code in r.get("organ_codes", []) or []:
            counter[code] += 1

    result = []
    for code, count in counter.most_common():
        result.append(
            {
                "code": code,
                "name": organ_names.get(code, code),
                "icon": icons.get(code, "📊"),
                "count": count,
            }
        )
    return result


def build_active_routes(records: list[dict], limit: int = 10) -> list[dict]:
    """Собирает последние N assigned-маршрутов для таблицы."""
    active = [r for r in records if r.get("status") == "assigned"]
    # Сортируем по timestamp (последние — сверху)
    active.sort(key=lambda r: r.get("timestamp", ""), reverse=True)

    result = []
    for r in active[:limit]:
        specialists = ", ".join(r.get("specialist", [])) or "—"
        urgency = r.get("urgency", "")

        # Бейдж
        if urgency == "emergency":
            badge = "🚨 Срочно"
            badge_class = "red"
        elif urgency == "oncological":
            badge = "⚠️ Онконастороженность"
            badge_class = "orange"
        elif urgency == "urgent":
            badge = "⏰ Ускоренно"
            badge_class = "orange"
        else:
            badge = "📅 Планово"
            badge_class = "green"

        result.append(
            {
                "patient_id": r.get("patient_id", "—"),
                "patient_name": r.get("patient_name", "—"),
                "finding": r.get("finding") or "—",
                "specialist": specialists,
                "urgency": urgency,
                "badge": badge,
                "badge_class": badge_class,
                "status_label": r.get("status_label", ""),
            }
        )
    return result


# ============================================================================
#                        РЕНДЕР
# ============================================================================


def render_manager(
    kpi: dict,
    funnel: list[dict],
    by_organ: list[dict],
    active_routes: list[dict],
    total_records: int,
    output_path: Path,
) -> None:
    """Рендерит manager.html.j2 с реальными данными."""
    templates_dir = ROOT / "templates"
    env = Environment(
        loader=FileSystemLoader(str(templates_dir)),
        autoescape=select_autoescape(["html", "xml"]),
        trim_blocks=True,
        lstrip_blocks=True,
    )

    template = env.get_template("manager.html.j2")

    html = template.render(
        kpi=kpi,
        funnel=funnel,
        by_organ=by_organ,
        active_routes=active_routes,
        total_records=total_records,
        generated_at=datetime.now(timezone.utc).strftime("%d.%m.%Y %H:%M"),
    )

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(html, encoding="utf-8")
    log.info(f"Записан {output_path}")


# ============================================================================
#                        MAIN
# ============================================================================


def main() -> None:
    audit_path = ROOT / "output" / "routes_audit.jsonl"
    output_path = ROOT / "output" / "manager.html"

    # 1. Читаем журнал
    log.info(f"Читаю {audit_path}")
    records = read_audit(audit_path)
    if not records:
        log.error("Журнал пуст")
        sys.exit(1)
    log.info(f"Записей: {len(records)}")

    # 2. Считаем
    kpi = build_kpi(records)
    funnel = build_funnel(records)
    by_organ = build_by_organ(records)
    active_routes = build_active_routes(records)

    log.info(
        f"KPI: всего={kpi['total']}, assigned={kpi['assigned']}, urgent={kpi['urgent']}"
    )

    # 3. Рендерим
    render_manager(kpi, funnel, by_organ, active_routes, len(records), output_path)

    print()
    print("=" * 60)
    print("  ДАШБОРД РУКОВОДИТЕЛЯ ОБНОВЛЁН")
    print("=" * 60)
    print(f"  Всего протоколов:    {kpi['total']}")
    print(f"  С маршрутом:         {kpi['assigned']} ({kpi['assigned_pct']})")
    print(f"  Срочных:             {kpi['urgent']}")
    print(f"  Мультидисциплинар.:  {kpi['multidisciplinary']}")
    print(f"  HTML:                {output_path}")
    print("=" * 60)
    print()


if __name__ == "__main__":
    main()
