"""
export_to_excel.py — Конвертация routes_audit.jsonl → Excel.

Запуск:
    python scripts/export_to_excel.py
    python scripts/export_to_excel.py --input output/routes_audit.jsonl \
                                       --output output/routes_report.xlsx
"""

from __future__ import annotations

import argparse
import json
import logging
from pathlib import Path

import pandas as pd

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("export_to_excel")

ROOT = Path(__file__).resolve().parent.parent


# ============================================================================
#                        ЧТЕНИЕ JSONL
# ============================================================================

def read_jsonl(path: Path) -> list[dict]:
    """Читает JSONL-файл, пропуская битые строки."""
    if not path.exists():
        raise FileNotFoundError(f"Файл не найден: {path}")

    records = []
    with open(path, "r", encoding="utf-8") as f:
        for i, line in enumerate(f, 1):
            line = line.strip()
            if not line:
                continue
            try:
                records.append(json.loads(line))
            except json.JSONDecodeError as e:
                log.warning(f"Строка {i}: битый JSON → {e}")
    return records


# ============================================================================
#                        ПОДГОТОВКА ДАННЫХ
# ============================================================================

def flatten_record(rec: dict) -> dict:
    """
    Превращает вложенные списки в строки для Excel.
    ['Кардиолог', 'Пульмонолог'] → 'Кардиолог, Пульмонолог'
    """
    flat = {}
    for key, value in rec.items():
        if isinstance(value, list):
            flat[key] = ", ".join(str(v) for v in value) if value else ""
        elif isinstance(value, dict):
            flat[key] = json.dumps(value, ensure_ascii=False)
        elif value is None:
            flat[key] = ""
        else:
            flat[key] = value
    return flat


# ============================================================================
#                        ЭКСПОРТ
# ============================================================================

def export_to_excel(
    records: list[dict],
    output_path: Path,
    with_summary: bool = True,
) -> None:
    """Пишет Excel с несколькими листами."""
    if not records:
        log.error("Нет данных для экспорта")
        return

    # 1. Основной лист — все записи
    df = pd.DataFrame([flatten_record(r) for r in records])

    # Сортируем колонки в удобном порядке
    preferred_order = [
        "timestamp",
        "patient_id",
        "patient_name",
        "patient_age",
        "doctor",
        "visit_date",
        "visit_time",
        "status",
        "status_label",
        "urgency",
        "deadline_days",
        "specialist",
        "finding",
        "finding_id",
        "scenario",
        "multidisciplinary",
        "dispute_applied",
        "organ_codes",
        "basis",
        "reason",
        "quote",
        "sentences_total",
        "positive_count",
        "negative_count",
    ]
    # Оставляем только те, что есть в df, остальные — в конец
    existing = [c for c in preferred_order if c in df.columns]
    rest = [c for c in df.columns if c not in existing]
    df = df[existing + rest]

    # 2. Лист со сводкой (если нужно)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    with pd.ExcelWriter(output_path, engine="openpyxl") as writer:
        df.to_excel(writer, sheet_name="Маршруты", index=False)

        if with_summary:
            # Сводка по срочности
            summary_urgency = (
                df.groupby("urgency")
                .size()
                .reset_index(name="Количество")
                .rename(columns={"urgency": "Срочность"})
            )
            summary_urgency.to_excel(
                writer, sheet_name="Сводка по срочности", index=False
            )

            # Сводка по специалистам
            spec_counts = {}
            for rec in records:
                for spec in rec.get("specialist", []) or []:
                    spec_counts[spec] = spec_counts.get(spec, 0) + 1
            summary_spec = pd.DataFrame(
                sorted(spec_counts.items(), key=lambda x: -x[1]),
                columns=["Специалист", "Количество"],
            )
            summary_spec.to_excel(
                writer, sheet_name="Сводка по специалистам", index=False
            )

            # Сводка по органам
            organ_counts = {}
            for rec in records:
                for organ in rec.get("organ_codes", []) or []:
                    organ_counts[organ] = organ_counts.get(organ, 0) + 1
            summary_organ = pd.DataFrame(
                sorted(organ_counts.items(), key=lambda x: -x[1]),
                columns=["Орган", "Количество"],
            )
            summary_organ.to_excel(
                writer, sheet_name="Сводка по органам", index=False
            )

    log.info(f"Записан {output_path}")
    log.info(f"  Записей: {len(df)}")
    log.info(f"  Колонок: {len(df.columns)}")
    if with_summary:
        log.info("  Листы: Маршруты, Сводка по срочности, "
                 "Сводка по специалистам, Сводка по органам")


# ============================================================================
#                        MAIN
# ============================================================================

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Конвертация routes_audit.jsonl → Excel"
    )
    parser.add_argument(
        "--input",
        type=Path,
        default=ROOT / "output" / "routes_audit.jsonl",
        help="Путь к JSONL-файлу",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=ROOT / "output" / "routes_report.xlsx",
        help="Путь к Excel-файлу",
    )
    parser.add_argument(
        "--no-summary",
        action="store_true",
        help="Не создавать листы со сводками",
    )
    args = parser.parse_args()

    log.info(f"Читаю {args.input}")
    records = read_jsonl(args.input)
    log.info(f"Записей: {len(records)}")

    export_to_excel(
        records,
        args.output,
        with_summary=not args.no_summary,
    )

    print()
    print("=" * 60)
    print(f"✅ Excel готов: {args.output}")
    print("=" * 60)


if __name__ == "__main__":
    main()

