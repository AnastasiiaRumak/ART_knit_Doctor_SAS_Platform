"""
parse_tables.py — Конвертер таблиц триггеров в YAML-конфиги.

Читает из ./data:
  • ОМТ.xlsx, ПЖ.xlsx, МЖ.xlsx, НК.xlsx          — синонимы → врач
  • Размеры_норма.xlsx                            — числовые пороги
  • ЖП.txt                                        — гастроэнтерология
  • klinicheskie_nahodki_serdca.csv               — кардио (синонимы)
  • ekhg_patterns_with_regex.csv                  — кардио (RegEx)
  • спорные ситуации.txt                          — спорные ситуации

Пишет в ./config:
  • triggers/omt.yaml
  • triggers/pzh.yaml
  • triggers/mzh.yaml
  • triggers/nk.yaml
  • triggers/zhp.yaml
  • triggers/cardio.yaml
  • triggers/cardio_regex.yaml
  • sizes.yaml
  • disputes.yaml

Запуск:
  python3 parse_tables.py --input-dir ./data --output-dir ./config
"""

from __future__ import annotations

import argparse
import csv
import logging
import re
import sys
from pathlib import Path
from typing import Any

import pandas as pd
import yaml

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("parse_tables")


# ============================================================================
#                        ОБЩИЕ УТИЛИТЫ
# ============================================================================


def slugify(text: str) -> str:
    """Преобразует строку в безопасный slug: 'Полип эндометрия' → 'polip_endometriya'."""
    text = text.lower().strip()
    trans = {
        "а": "a",
        "б": "b",
        "в": "v",
        "г": "g",
        "д": "d",
        "е": "e",
        "ё": "e",
        "ж": "zh",
        "з": "z",
        "и": "i",
        "й": "y",
        "к": "k",
        "л": "l",
        "м": "m",
        "н": "n",
        "о": "o",
        "п": "p",
        "р": "r",
        "с": "s",
        "т": "t",
        "у": "u",
        "ф": "f",
        "х": "h",
        "ц": "ts",
        "ч": "ch",
        "ш": "sh",
        "щ": "sch",
        "ъ": "",
        "ы": "y",
        "ь": "",
        "э": "e",
        "ю": "yu",
        "я": "ya",
        " ": "_",
        "-": "_",
        "/": "_",
        ",": "",
        ".": "",
        "(": "",
        ")": "",
        "?": "",
        "!": "",
        ":": "",
        ";": "",
        '"': "",
        "'": "",
    }
    result = []
    for ch in text:
        result.append(trans.get(ch, ch))
    slug = "".join(result)
    slug = re.sub(r"_+", "_", slug).strip("_")
    return slug


def split_synonyms(cell: str) -> list[str]:
    """'Полип эндометрия / полипоз / подозрение' → ['полип эндометрия', ...]."""
    if not cell or not isinstance(cell, str):
        return []
    parts = re.split(r"\s*[/,;]\s*|\s*→\s*", cell)
    result = []
    for p in parts:
        p = p.strip().strip('"').strip("'").lower()
        p = re.sub(r"\s*\.\.\.\s*", " ", p)
        p = re.sub(r"\s+", " ", p).strip()
        if p and len(p) > 1:
            result.append(p)
    seen = set()
    unique = []
    for p in result:
        if p not in seen:
            seen.add(p)
            unique.append(p)
    return unique


def parse_specialist(cell: str) -> list[str]:
    """'Гинеколог / хирург' → ['Гинеколог', 'Хирург']. '—' → []."""
    if not cell or not isinstance(cell, str):
        return []
    cell = cell.strip()
    if cell in ("—", "-", "— (клинически незначимо)", "— (вариант нормы)"):
        return []
    parts = re.split(r"\s*[/,;]\s*|\s*→\s*", cell)
    result = []
    for p in parts:
        p = p.strip()
        p = re.sub(r"\s*\([^)]*\)\s*", "", p).strip()
        if p and p not in ("—", "-"):
            result.append(p)
    seen = set()
    unique = []
    for p in result:
        if p not in seen:
            seen.add(p)
            unique.append(p)
    return unique


def write_yaml(path: Path, data: dict[str, Any]) -> None:
    """Пишет YAML с заголовком."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write("# Автоматически сгенерировано parse_tables.py\n")
        f.write(f"# Источник: {path.stem}\n")
        f.write(
            "# НЕ РЕДАКТИРОВАТЬ ВРУЧНУЮ — правьте исходные таблицы и перезапускайте\n\n"
        )
        yaml.dump(
            data,
            f,
            allow_unicode=True,
            sort_keys=False,
            default_flow_style=False,
            width=120,
        )
    log.info(f"  → записан {path}")


# ============================================================================
#                   ПАРСЕРЫ XLSX
# ============================================================================


def parse_synonym_table(
    path: Path,
    organ_code: str,
    organ_name: str,
    keywords: list[str],
) -> dict[str, Any]:
    """Читает .xlsx с колонками: Находка, Врач."""
    log.info(f"Читаю {path.name}...")
    df = pd.read_excel(path, header=0)
    cols = list(df.columns)
    if len(cols) < 2:
        raise ValueError(f"{path.name}: ожидалось ≥2 колонок, найдено {len(cols)}")

    col_finding, col_doctor = cols[0], cols[1]
    findings = []
    seen_ids = set()

    for _, row in df.iterrows():
        finding_raw = row[col_finding]
        doctor_raw = row[col_doctor]
        if pd.isna(finding_raw) or str(finding_raw).strip() in ("", "nan"):
            continue

        finding_str = str(finding_raw).strip()
        doctor_str = str(doctor_raw).strip() if not pd.isna(doctor_raw) else ""
        synonyms = split_synonyms(finding_str)
        if not synonyms:
            continue

        specialists = parse_specialist(doctor_str)
        is_negative = len(specialists) == 0

        base_id = f"{organ_code}_{slugify(synonyms[0])[:40]}"
        if base_id in seen_ids:
            base_id = f"{base_id}_{len(findings)}"
        seen_ids.add(base_id)

        findings.append(
            {
                "id": base_id,
                "synonyms": synonyms,
                "specialist": specialists,
                "is_negative": is_negative,
                "urgency": "observation" if is_negative else "planned",
                "source": finding_str,
            }
        )

    log.info(
        f"  → {len(findings)} находок (негативных: {sum(1 for f in findings if f['is_negative'])})"
    )
    return {
        "organ_code": organ_code,
        "organ_name": organ_name,
        "keywords": keywords,
        "findings": findings,
    }


NUM_RE = re.compile(r"(-?\d+[.,]?\d*)")


def parse_numeric_value(text: str) -> float | None:
    if not text or pd.isna(text):
        return None
    m = NUM_RE.search(str(text).replace(",", "."))
    return float(m.group(1)) if m else None


def parse_range(text: str) -> tuple[float | None, float | None]:
    if not text or pd.isna(text):
        return None, None
    text = str(text).replace(",", ".")
    nums = [float(n) for n in NUM_RE.findall(text)]
    if len(nums) >= 2:
        return nums[0], nums[1]
    if len(nums) == 1:
        return nums[0], None
    return None, None


def parse_unit(text: str) -> str:
    if not text or pd.isna(text):
        return ""
    text = str(text)
    for unit in ["см³", "см3", "см/с", "мм", "см", "мл", "%", "мм рт.ст."]:
        if unit in text:
            return unit
    return ""


def parse_sizes_table(path: Path) -> dict[str, Any]:
    """Читает Размеры_норма.xlsx: Орган, Параметр, Норма, Когда триггер, Врач."""
    log.info(f"Читаю {path.name}...")
    df = pd.read_excel(path, header=0)
    cols = list(df.columns)
    col_organ, col_param, col_normal, col_trigger = cols[0], cols[1], cols[2], cols[3]
    col_doctor = cols[4] if len(cols) > 4 else None

    organs: dict[str, list[dict]] = {}

    for _, row in df.iterrows():
        organ = str(row[col_organ]).strip() if not pd.isna(row[col_organ]) else ""
        param = str(row[col_param]).strip() if not pd.isna(row[col_param]) else ""
        normal = str(row[col_normal]).strip() if not pd.isna(row[col_normal]) else ""
        trigger = str(row[col_trigger]).strip() if not pd.isna(row[col_trigger]) else ""
        doctor = (
            str(row[col_doctor]).strip()
            if col_doctor and not pd.isna(row[col_doctor])
            else ""
        )

        if not organ or not param:
            continue

        normal_lo, normal_hi = parse_range(normal)
        threshold = parse_numeric_value(trigger)
        unit = parse_unit(trigger) or parse_unit(normal)
        operator = "<" if "<" in trigger else ">"
        specialists = parse_specialist(doctor)

        organs.setdefault(organ, []).append(
            {
                "param": param,
                "normal": normal,
                "normal_range": [normal_lo, normal_hi],
                "trigger_text": trigger,
                "threshold": threshold,
                "unit": unit,
                "operator": operator,
                "specialist": specialists,
                "is_negative": len(specialists) == 0,
            }
        )

    log.info(
        f"  → {len(organs)} органов, {sum(len(v) for v in organs.values())} параметров"
    )
    return {"organs": organs}


# ============================================================================
#                   ПАРСЕРЫ TXT/CSV
# ============================================================================


def parse_zhp(path: Path) -> dict[str, Any]:
    """Читает ЖП.txt: 'Триггер и синонимы,Врач'."""
    log.info(f"Читаю {path.name}...")
    findings, seen_ids = [], set()

    with open(path, "r", encoding="utf-8-sig") as f:
        reader = csv.reader(f)
        next(reader, None)
        for row in reader:
            if not row or len(row) < 2:
                continue
            finding_raw, doctor_raw = row[0].strip(), row[1].strip()
            if not finding_raw:
                continue
            synonyms = split_synonyms(finding_raw)
            if not synonyms:
                continue
            specialists = parse_specialist(doctor_raw)
            is_negative = len(specialists) == 0
            base_id = f"zhp_{slugify(synonyms[0])[:40]}"
            if base_id in seen_ids:
                base_id = f"{base_id}_{len(findings)}"
            seen_ids.add(base_id)
            findings.append(
                {
                    "id": base_id,
                    "synonyms": synonyms,
                    "specialist": specialists,
                    "is_negative": is_negative,
                    "urgency": "observation" if is_negative else "planned",
                    "source": finding_raw,
                }
            )

    log.info(f"  → {len(findings)} находок")
    return {
        "organ_code": "zhp",
        "organ_name": "Желчный пузырь и гепатобилиарная зона",
        "keywords": [
            "желчный пузырь",
            "жп",
            "печень",
            "поджелудочная железа",
            "холедох",
            "портальная вена",
            "желчевыводящие",
            "гепатомегалия",
            "холецистит",
            "конкременты",
            "полип желчного пузыря",
        ],
        "findings": findings,
    }


def parse_cardio(path: Path) -> dict[str, Any]:
    """
    Читает Кардио.xlsx:
      A: Находка и синонимы
      B: Врач
      C: RegEx (опционально)
      D: Срочность (опционально)
    """
    log.info(f"Читаю {path.name}...")
    df = pd.read_excel(path, header=0)
    cols = list(df.columns)

    if len(cols) < 2:
        raise ValueError(f"{path.name}: ожидалось ≥2 колонок")

    col_finding = cols[0]
    col_doctor = cols[1]
    col_regex = cols[2] if len(cols) > 2 else None
    col_urgency = cols[3] if len(cols) > 3 else None

    findings, seen_ids = [], set()

    for _, row in df.iterrows():
        finding_raw = row[col_finding]
        doctor_raw = row[col_doctor]
        if pd.isna(finding_raw) or str(finding_raw).strip() in ("", "nan"):
            continue

        finding_str = str(finding_raw).strip()
        doctor_str = str(doctor_raw).strip() if not pd.isna(doctor_raw) else ""

        # RegEx
        regex_str: str | None = None
        if col_regex is not None and not pd.isna(row[col_regex]):
            regex_str = str(row[col_regex]).strip()
            if regex_str.lower() in ("", "nan", "none"):
                regex_str = None
            else:
                try:
                    re.compile(regex_str)
                except re.error as e:
                    log.warning(f"  Некорректный RegEx {regex_str!r} → {e}")
                    regex_str = None

        # Срочность
        urgency = "planned"
        if col_urgency is not None and not pd.isna(row[col_urgency]):
            u = str(row[col_urgency]).strip().lower()
            if u in ("planned", "urgent", "emergency", "oncological", "observation"):
                urgency = u

        synonyms = split_synonyms(finding_str)
        if not synonyms:
            continue

        specialists = parse_specialist(doctor_str)
        is_negative = len(specialists) == 0

        base_id = f"cardio_{slugify(synonyms[0])[:40]}"
        if base_id in seen_ids:
            base_id = f"{base_id}_{len(findings)}"
        seen_ids.add(base_id)

        findings.append(
            {
                "id": base_id,
                "synonyms": synonyms,
                "specialist": specialists,
                "is_negative": is_negative,
                "urgency": "observation" if is_negative else urgency,
                "source": finding_str,
                "regex": regex_str,
            }
        )

    log.info(
        f"  → {len(findings)} находок "
        f"(с regex: {sum(1 for f in findings if f['regex'])})"
    )

    return {
        "organ_code": "cardio",
        "organ_name": "Сердце и сосуды (ЭхоКГ)",
        "keywords": [
            "эхокардиография",
            "эхокг",
            "сердце",
            "лж",
            "пж",
            "лп",
            "пп",
            "глж",
            "мжп",
            "зслж",
            "фв",
            "фракция выброса",
            "митральный клапан",
            "аортальный клапан",
            "трикуспидальный",
            "перикард",
            "легочная артерия",
            "сдла",
            "аорта",
            "регургитация",
            "гипокинезия",
            "акинезия",
            "диастолическая дисфункция",
        ],
        "findings": findings,
    }


def parse_cardio_regex(path: Path) -> dict[str, Any]:
    """Читает ekhg_patterns_with_regex.csv: 'Находка,RegEx,Врач'."""
    log.info(f"Читаю {path.name}...")
    patterns, seen_ids = [], set()

    with open(path, "r", encoding="utf-8-sig") as f:
        reader = csv.reader(f)
        next(reader, None)
        for row in reader:
            if not row or len(row) < 3:
                continue
            finding_raw, regex_raw, doctor_raw = (
                row[0].strip(),
                row[1].strip().strip('"'),
                row[2].strip(),
            )
            if not regex_raw:
                continue
            try:
                re.compile(regex_raw)
            except re.error as e:
                log.warning(f"  Некорректный RegEx: {regex_raw!r} → {e}")
                continue
            specialists = parse_specialist(doctor_raw)
            is_negative = len(specialists) == 0
            base_id = f"cardio_re_{slugify(finding_raw)[:40]}"
            if base_id in seen_ids:
                base_id = f"{base_id}_{len(patterns)}"
            seen_ids.add(base_id)
            patterns.append(
                {
                    "id": base_id,
                    "source": finding_raw,
                    "regex": regex_raw,
                    "specialist": specialists,
                    "is_negative": is_negative,
                    "urgency": "observation" if is_negative else "planned",
                }
            )

    log.info(f"  → {len(patterns)} RegEx-паттернов")
    return {
        "organ_code": "cardio_regex",
        "organ_name": "Сердце (RegEx-паттерны)",
        "patterns": patterns,
    }


def parse_disputes(path: Path) -> dict[str, Any]:
    """Читает спорные ситуации.txt: 7 колонок."""
    log.info(f"Читаю {path.name}...")
    by_category: dict[str, list[dict]] = {}
    negations: list[dict] = []
    total = 0

    with open(path, "r", encoding="utf-8-sig") as f:
        reader = csv.reader(f)
        next(reader, None)
        for row in reader:
            if not row or len(row) < 3:
                continue
            category = row[0].strip() if len(row) > 0 else ""
            situation = row[1].strip() if len(row) > 1 else ""
            triggers_raw = row[2].strip() if len(row) > 2 else ""
            routes_raw = row[3].strip() if len(row) > 3 else ""
            logic = row[4].strip() if len(row) > 4 else ""
            urgency = row[5].strip() if len(row) > 5 else ""
            scenario = row[6].strip() if len(row) > 6 else ""

            if not category or not situation:
                continue
            synonyms = split_synonyms(triggers_raw)

            # Фильтр: убираем синонимы, которые слишком общие
            # для спорной ситуации (могут давать ложные срабатывания)
            FILTER_OUT = {
                "фиброаденома",
                "фиброаденома?",
                "узел",
                "узлы",
                "киста",
                "кисты",
                "образование",
                "образования",
            }
            synonyms = [s for s in synonyms if s.lower() not in FILTER_OUT]

            if not synonyms:
                continue
            specialists = parse_specialist(routes_raw)

            entry = {
                "situation": situation,
                "synonyms": synonyms,
                "route_variants": specialists,
                "logic": logic,
                "urgency": urgency.lower() if urgency else "",
                "scenario": scenario.lower() if scenario else "",
            }

            if "ложный" in category.lower():
                negations.append(entry)
            else:
                by_category.setdefault(category, []).append(entry)
            total += 1

    log.info(f"  → {total} ситуаций (ложных триггеров: {len(negations)})")
    return {
        "by_category": by_category,
        "negations_from_disputes": negations,
    }


# ============================================================================
#                   MAIN
# ============================================================================

ORGAN_KEYWORDS = {
    "omt": [
        "органы малого таза",
        "омт",
        "матка",
        "яичник",
        "эндометрий",
        "миометрий",
        "шейка матки",
        "м-эхо",
        "цервикальный канал",
    ],
    "pzh": [
        "предстательная железа",
        "пж",
        "простата",
        "семенные пузырьки",
        "переходная зона",
        "парапростатическая",
    ],
    "mzh": [
        "молочная железа",
        "молочные железы",
        "мж",
        "би-rads",
        "bi-rads",
        "млечные протоки",
        "фиброаденома",
    ],
    "nk": [
        "артерии нижних конечностей",
        "вены нижних конечностей",
        "бпв",
        "мпв",
        "збба",
        "пбба",
        "оба",
        "пба",
        "пка",
        "тас",
        "ким",
        "асб",
        "стеноз",
        "окклюзия",
        "рефлюкс",
        "тромбоз",
    ],
    "zhp": [
        "желчный пузырь",
        "жп",
        "печень",
        "поджелудочная железа",
        "холедох",
        "портальная вена",
        "желчевыводящие",
    ],
    "thyroid": [
        "щитовидная железа",
        "щитовидной железы",
        "щж",
        "тиреоидная",
        "перешеек",
        "правая доля",
        "левая доля",
        "ti-rads",
        "eu-tirads",
        "ти-радс",
        "узловой зоб",
        "аит",
    ],
}


def parse_all_xlsx(input_dir: Path, output_dir: Path) -> None:
    triggers_dir = output_dir / "triggers"
    triggers_dir.mkdir(parents=True, exist_ok=True)

    for code, name, kw_key in [
        ("omt", "Органы малого таза", "omt"),
        ("pzh", "Предстательная железа", "pzh"),
        ("mzh", "Молочная железа", "mzh"),
        ("nk", "Нижние конечности (сосуды)", "nk"),
    ]:
        # Ищем файл с любым регистром
        candidates = [
            input_dir / f"{code.upper()}.xlsx",
            input_dir / f"{code.capitalize()}.xlsx",
            input_dir
            / {"omt": "ОМТ.xlsx", "pzh": "ПЖ.xlsx", "mzh": "МЖ.xlsx", "nk": "НК.xlsx"}[
                code
            ],
        ]
        path = next((p for p in candidates if p.exists()), None)
        if not path:
            log.warning(f"Не найден файл для {code} (пробовали: {candidates})")
            continue
        data = parse_synonym_table(path, code, name, ORGAN_KEYWORDS[kw_key])
        write_yaml(triggers_dir / f"{code}.yaml", data)

    sizes_path = input_dir / "Размеры_норма.xlsx"
    if sizes_path.exists():
        data = parse_sizes_table(sizes_path)
        write_yaml(output_dir / "sizes.yaml", data)
    else:
        log.warning(f"Не найден {sizes_path}")


def parse_all_txt(input_dir: Path, output_dir: Path) -> None:
    triggers_dir = output_dir / "triggers"
    triggers_dir.mkdir(parents=True, exist_ok=True)

    # ЖП
    zhp_path = input_dir / "ЖП.txt"
    if zhp_path.exists():
        data = parse_zhp(zhp_path)
        write_yaml(triggers_dir / "zhp.yaml", data)
    else:
        log.warning(f"Не найден {zhp_path}")

    # Кардио (единый xlsx: находки + regex)
    cardio_path = input_dir / "Кардио.xlsx"
    if cardio_path.exists():
        data = parse_cardio(cardio_path)
        write_yaml(triggers_dir / "cardio.yaml", data)
    else:
        log.warning(f"Не найден {cardio_path} — пропускаю кардио")
    # Спорные ситуации
    disputes_path = input_dir / "спорные ситуации.txt"
    if disputes_path.exists():
        data = parse_disputes(disputes_path)
        write_yaml(output_dir / "disputes.yaml", data)
    else:
        log.warning(f"Не найден {disputes_path}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Парсер таблиц триггеров → YAML")
    parser.add_argument("--input-dir", type=Path, default=Path("./data"))
    parser.add_argument("--output-dir", type=Path, default=Path("./config"))
    parser.add_argument("--only", choices=["xlsx", "txt", "all"], default="all")
    args = parser.parse_args()

    if not args.input_dir.exists():
        log.error(f"Папка {args.input_dir} не существует!")
        sys.exit(1)

    log.info("=" * 60)
    log.info("ПАРСЕР ТАБЛИЦ ТРИГГЕРОВ")
    log.info(f"  input:  {args.input_dir.resolve()}")
    log.info(f"  output: {args.output_dir.resolve()}")
    log.info("=" * 60)

    if args.only in ("xlsx", "all"):
        log.info("\n--- ЭТАП 1: XLSX-таблицы ---")
        parse_all_xlsx(args.input_dir, args.output_dir)

    if args.only in ("txt", "all"):
        log.info("\n--- ЭТАП 2: TXT/CSV-таблицы ---")
        parse_all_txt(args.input_dir, args.output_dir)

    log.info("\n" + "=" * 60)
    log.info("ГОТОВО! Проверьте config/")
    log.info("=" * 60)


if __name__ == "__main__":
    main()
