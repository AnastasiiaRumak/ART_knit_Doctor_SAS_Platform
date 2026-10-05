"""
main.py — CLI для системы автоматической маршрутизации пациентов.

Режимы:
  --demo              Прогоняет 8 встроенных протоколов, создаёт HTML
  --protocol <file>   Прогоняет один протокол из файла
  --open              Открывает результат в браузере

Авторизация:
  --api-key <key>     API-ключ (см. config/roles.yaml)
  --role <role>       Явная роль (только для демо/отладки, без ключа)
  SM_CLINIC_API_KEY   Переменная окружения (приоритетнее --api-key)

Контуры доступа:
  patient  — только свой маршрут
  doctor   — только свои пациенты
  manager  — агрегаты без ПДн
  admin    — полный доступ

Примеры:
  python3 main.py --demo --open
  python3 main.py --demo --api-key admin_key_root
  python3 main.py --demo --api-key doctor_key_abc123
  python3 main.py --demo --api-key manager_key_xyz789
  python3 main.py --protocol my_protocol.txt \
      --patient-name "Иванова А.С." --patient-age 30 \
      --study-type "УЗИ ОМТ" --study-date "26.08.2026" \
      --api-key doctor_key_abc123
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
import webbrowser
from pathlib import Path

# Добавляем src/ в путь
ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / "src"))

from config_loader import ConfigLoader
from extractor import Extractor
from generator import Generator
from router import Router

# --- Авторизация (мягкий импорт — чтобы демо не падало без auth.py) ---
try:
    from auth import AuthError, AuthService, PermissionDenied, User
    AUTH_AVAILABLE = True
except ImportError:
    AUTH_AVAILABLE = False
    AuthService = None  # type: ignore
    AuthError = PermissionDenied = Exception  # type: ignore
    User = None  # type: ignore


# ============================================================================
#                        ВСТРОЕННЫЕ ПРОТОКОЛЫ
# ============================================================================

DEMO_PROTOCOLS = [
    # ------------------------------------------------------------------
    # 1. ОМТ — полип эндометрия (мягкий сценарий)
    # ------------------------------------------------------------------
    {
        "label": "ОМТ (полип эндометрия)",
        "study_type": "УЗИ ОМТ",
        "study_date": "26.08.2026",
        "patient": {
            "name": "Иванова Анна Сергеевна",
            "initials": "ИА",
            "age": 30,
            "sex_label": "женский",
            "card_id": "1024",
        },
        "doctor": {"name": "Туаева А.С.", "initials": "АТ"},
        "visit": {"date": "26.08.2026", "time": "10:30", "doctor": "Туаева А.С."},
        "protocol": """
            УЛЬТРАЗВУКОВОЕ ИССЛЕДОВАНИЕ ОРГАНОВ МАЛОГО ТАЗА
            МАТКА: положение - срединное, отклонена - кпереди, форма - седловидная
            Размеры - 50 х 38 х 52 мм.
            Структура миометрия - диффузно-неоднородная, эхогенность средняя.
            М-ЭХО - 14.0 мм, неоднородной эхоструктуры, с анэхогенными мелкими включениями.
            В полости матки лоцируется гиперэхогенное образование 12 мм - полип эндометрия.
            ПРАВЫЙ ЯИЧНИК: Размеры - 35 х 22 х 29 мм, V - 12.0 мл.
            ЛЕВЫЙ ЯИЧНИК: Размеры - 28 х 14 х 25 мм, V - 5.0 мл.
            Свободная жидкость в малом тазу: не лоцируется.
            ЗАКЛЮЧЕНИЕ: УЗ признаки полипа эндометрия, несоответствия толщины эндометрия дню цикла,
            неоднородной эхоструктуры эндометрия, диффузных изменений миометрия.
        """,
    },
    # ------------------------------------------------------------------
    # 2. ОМТ — без патологии (no_action)
    # ------------------------------------------------------------------
    {
        "label": "ОМТ (без патологии)",
        "study_type": "УЗИ ОМТ",
        "study_date": "26.08.2026",
        "patient": {
            "name": "Смирнова Ольга Ивановна",
            "initials": "ОС",
            "age": 42,
            "sex_label": "женский",
            "card_id": "1025",
        },
        "doctor": {"name": "Туаева А.С.", "initials": "АТ"},
        "visit": {"date": "26.08.2026", "time": "11:15", "doctor": "Туаева А.С."},
        "protocol": """
            УЗИ органов малого таза.
            М-ЭХО - 6.0 мм, однородной эхоструктуры.
            Полип эндометрия не выявлен.
            Свободная жидкость в малом тазу не лоцируется.
            ЗАКЛЮЧЕНИЕ: Без патологии.
        """,
    },
    # ------------------------------------------------------------------
    # 3. ЖП — полип + холестаз (мультидисциплинарный)
    # ------------------------------------------------------------------
    {
        "label": "ЖП (полип + холестаз)",
        "study_type": "УЗИ органов брюшной полости",
        "study_date": "26.08.2026",
        "patient": {
            "name": "Петров Сергей Андреевич",
            "initials": "СП",
            "age": 45,
            "sex_label": "мужской",
            "card_id": "1026",
        },
        "doctor": {"name": "Евгения М.В.", "initials": "ЕМ"},
        "visit": {"date": "26.08.2026", "time": "09:45", "doctor": "Евгения М.В."},
        "protocol": """
            УЗИ органов брюшной полости (комплексное).
            ПЕЧЕНЬ: правая доля КВР 143 мм. Контуры четкие, ровные.
            ЖЕЛЧНЫЙ ПУЗЫРЬ: Размерами 63 х 17 мм, грушевидной формы с загибом в области шейки.
            По боковым стенкам определяются аваскулярные гиперэхогенные пристеночные образования
            размерами 3,3 х 2,8 мм; 2,8 х 1,9 мм; 3,1 х 1,8 мм.
            В просвете определяется большое количество хлопьевидного осадка.
            ЗАКЛЮЧЕНИЕ: Полипоз и холестаз желчного пузыря.
            Рекомендовано: консультация гастроэнтеролога.
        """,
    },
    # ------------------------------------------------------------------
    # 4. ПЖ — ДГПЖ + остаточная моча
    # ------------------------------------------------------------------
    {
        "label": "ПЖ (ДГПЖ + остаточная моча)",
        "study_type": "УЗИ предстательной железы",
        "study_date": "26.08.2026",
        "patient": {
            "name": "Сидоров Иван Иванович",
            "initials": "ИС",
            "age": 62,
            "sex_label": "мужской",
            "card_id": "1027",
        },
        "doctor": {"name": "Кузнецова А.В.", "initials": "АК"},
        "visit": {"date": "26.08.2026", "time": "10:00", "doctor": "Кузнецова А.В."},
        "protocol": """
            УЗИ предстательной железы.
            Размеры 45 х 38 х 42 мм, объем 47 см3.
            В переходной зоне определяются аденоматозные узлы до 15 мм.
            Объем остаточной мочи 87 мл.
            ЗАКЛЮЧЕНИЕ: ДГПЖ 2 степени.
        """,
    },
    # ------------------------------------------------------------------
    # 5. МЖ — фиброаденома (BI-RADS 3)
    # ------------------------------------------------------------------
    {
        "label": "МЖ (фиброаденома, BI-RADS 3)",
        "study_type": "УЗИ молочных желез",
        "study_date": "26.08.2026",
        "patient": {
            "name": "Морозова Людмила Викторовна",
            "initials": "ЛМ",
            "age": 48,
            "sex_label": "женский",
            "card_id": "1028",
        },
        "doctor": {"name": "Кузнецова А.В.", "initials": "АК"},
        "visit": {"date": "26.08.2026", "time": "11:00", "doctor": "Кузнецова А.В."},
        "protocol": """
            УЗИ молочных желез.
            В правой молочной железе лоцируется фиброаденома 12 мм.
            BI-RADS 3.
            ЗАКЛЮЧЕНИЕ: Фиброаденома правой молочной железы.
        """,
    },
    # ------------------------------------------------------------------
    # 6. НК — стеноз ОБА 55%
    # ------------------------------------------------------------------
    {
        "label": "НК (стеноз ОБА 55%)",
        "study_type": "УЗИ артерий нижних конечностей",
        "study_date": "26.08.2026",
        "patient": {
            "name": "Кузнецов Дмитрий Михайлович",
            "initials": "ДК",
            "age": 55,
            "sex_label": "мужской",
            "card_id": "1029",
        },
        "doctor": {"name": "Кузнецова А.В.", "initials": "АК"},
        "visit": {"date": "26.08.2026", "time": "12:00", "doctor": "Кузнецова А.В."},
        "protocol": """
            УЗИ артерий нижних конечностей.
            В ОБА определяется стеноз 55%.
            ЗАКЛЮЧЕНИЕ: Стенозирующий атеросклероз.
        """,
    },
    # ------------------------------------------------------------------
    # 7. Кардио — ГЛЖ + ФВ 45% (urgent, мультидисциплинарный)
    # ------------------------------------------------------------------
    {
        "label": "Кардио (ГЛЖ + ФВ 45%)",
        "study_type": "Эхокардиография",
        "study_date": "26.08.2026",
        "patient": {
            "name": "Орлова Елена Петровна",
            "initials": "ЕО",
            "age": 67,
            "sex_label": "женский",
            "card_id": "1030",
        },
        "doctor": {"name": "Кузнецова А.В.", "initials": "АК"},
        "visit": {"date": "26.08.2026", "time": "14:00", "doctor": "Кузнецова А.В."},
        "protocol": """
            Эхокардиография.
            Левый желудочек: гипертрофия стенок, МЖП 14 мм.
            Фракция выброса 45%, снижена.
            Диастолическая дисфункция 1 типа.
            Легочная гипертензия, СДЛА 42 мм рт.ст.
            ЗАКЛЮЧЕНИЕ: ГЛЖ, снижение ФВ, диастолическая дисфункция.
        """,
    },
    # ------------------------------------------------------------------
    # 8. Кардио — норма (no_action)
    # ------------------------------------------------------------------
    {
        "label": "Кардио (норма)",
        "study_type": "Эхокардиография",
        "study_date": "26.08.2026",
        "patient": {
            "name": "Александрова Мария Дмитриевна",
            "initials": "МА",
            "age": 35,
            "sex_label": "женский",
            "card_id": "1031",
        },
        "doctor": {"name": "Кузнецова А.В.", "initials": "АК"},
        "visit": {"date": "26.08.2026", "time": "15:00", "doctor": "Кузнецова А.В."},
        "protocol": """
            Эхокардиография.
            Фракция выброса в норме, 62%.
            Камеры сердца не расширены.
            ЗАКЛЮЧЕНИЕ: Показатели в пределах возрастной нормы.
        """,
    },
    # ------------------------------------------------------------------
    # 9. ЩЖ — узлы + TI-RADS 3 (эндокринолог)
    # ------------------------------------------------------------------
    {
        "label": "ЩЖ (узлы + TI-RADS 3)",
        "study_type": "УЗИ щитовидной железы",
        "study_date": "11.09.2026",
        "patient": {
            "name": "Николаева Ольга Владимировна",
            "initials": "ОН",
            "age": 50,
            "sex_label": "женский",
            "card_id": "1032",
        },
        "doctor": {"name": "Юлия Ю.", "initials": "ЮЮ"},
        "visit": {"date": "11.09.2026", "time": "14:21", "doctor": "Юлия Ю."},
        "protocol": """
            УЗИ ЩИТОВИДНОЙ ЖЕЛЕЗЫ.
            Расположена обычно. Контуры ровные.
            Общий объем железы: 25,6 см куб (увеличен).
            Правая доля: 28,0х35,0х40,0 мм, объем 20,4 см куб.
            Левая доля: 15,0х16,0х40,0 мм, объем 5,2 см куб.
            Перешеек: 5,1 мм (увеличен).
            Эхоструктура: неоднородная.
            В правой доле визуализируются гиперэхогенные узлы 26х25мм, 20х17мм,
            15х14мм, 25х21мм с перинодулярным кровотоком.
            В левой доле в нижнем полюсе изоэхогенный узел 24х13мм
            с активным перинодулярным кровотоком.
            Региональные лимфоузлы: не увеличены.
            ЗАКЛЮЧЕНИЕ: Узлы в обеих долях щитовидной железы,
            увеличение кровотока. EU-TIRADS справа 3, слева 3.
        """,
    },
]


# ============================================================================
#                        АУДИТ
# ============================================================================


def _append_audit(
    audit_file: Path,
    record: dict,
    user: "User | None" = None,
    auth: "AuthService | None" = None,
) -> None:
    """
    Пишет запись в JSONL-журнал.
    Если переданы user/auth — фильтрует ПДн по правам роли.
    """
    if user is not None and auth is not None:
        record = auth.filter_record(user, record)
        # Помечаем, кто смотрел
        record["_viewer_role"] = user.role
        record["_viewer_name"] = user.name or user.doctor_name or user.role

    audit_file.parent.mkdir(parents=True, exist_ok=True)
    with open(audit_file, "a", encoding="utf-8") as f:
        f.write(json.dumps(record, ensure_ascii=False) + "\n")


# ============================================================================
#                        ОСНОВНАЯ ЛОГИКА
# ============================================================================


def process_protocol(
    protocol: str,
    study_type: str,
    study_date: str,
    patient: dict,
    visit: dict,
    doctor: dict,
    cfg,
    ext: Extractor,
    rt: Router,
    gen: Generator,
    user: "User | None" = None,
    auth: "AuthService | None" = None,
) -> tuple[Path | None, object]:
    """
    Прогоняет один протокол через пайплайн и сохраняет HTML.
    Возвращает (путь_к_HTML, route).
    Если роль не имеет прав на пациента — возвращает (None, route).
    """
    # 1. Извлечение
    extraction = ext.extract(protocol)

    # 2. Маршрут
    route = rt.build(extraction, study_type=study_type, study_date=study_date)

    # 3. Метаданные для generator
    meta = {
        "sentences_total": extraction.sentences_total,
        "positive_count": len(extraction.positive()),
        "negative_count": len(extraction.negative()),
        "organ_codes": extraction.organ_codes or ["—"],
    }

    # 4. Генерация HTML
    output_path = gen.render_doctor(
        route=route,
        patient=patient,
        visit=visit,
        meta=meta,
        doctor=doctor,
    )
    gen.render_patient(
        route=route,
        patient=patient,
        visit=visit,
        meta=meta,
    )

    # 5. Журнал аудита
    audit_file = Path("output") / "routes_audit.jsonl"
    audit_record = {
        "patient_id": patient.get("card_id", "unknown"),
        "patient_name": patient.get("name", ""),
        "patient_age": patient.get("age", 0),
        "doctor": doctor.get("name", ""),
        "visit_date": visit.get("date", ""),
        "visit_time": visit.get("time", ""),
        "finding": route.finding_summary,
        "finding_id": route.primary_finding.id if route.primary_finding else None,
        "specialist": route.specialist,
        "urgency": route.urgency,
        "deadline_days": route.deadline_days,
        "scenario": route.scenario,
        "multidisciplinary": route.multidisciplinary,
        "dispute_applied": route.dispute_applied or None,
        "timestamp": "2026-08-26T14:00:00",
        "basis": route.basis,
        "reason": route.reason,
        "quote": route.quote,
        "status": route.status,
        "status_label": route.status_label,
        "organ_codes": meta.get("organ_codes", []),
        "sentences_total": meta.get("sentences_total", 0),
        "positive_count": meta.get("positive_count", 0),
        "negative_count": meta.get("negative_count", 0),
    }

    _append_audit(audit_file, audit_record, user=user, auth=auth)

    return output_path, route


def print_short_report(label: str, route, output_path: Path | None) -> None:
    """Короткий отчёт в консоль."""
    status_icon = {
        "no_action": "✅",
        "assigned": "📋",
    }.get(route.status, "•")

    specialists = ", ".join(route.specialist) if route.specialist else "—"
    urgency_icon = {
        "emergency": "🚨",
        "oncological": "⚠️",
        "urgent": "⏰",
        "planned": "📅",
        "observation": "👁",
    }.get(route.urgency, "•")

    print(f"  {status_icon} {label}")
    print(
        f"      → {specialists} | {urgency_icon} {route.urgency} | "
        f"{route.deadline_days} дн. | {route.status_label}"
    )
    if output_path:
        print(f"      → {output_path.name}")
    else:
        print("      → ⛔ пропущено (нет прав на просмотр)")


def run_demo(
    cfg,
    ext,
    rt,
    gen,
    output_dir: Path,
    open_browser: bool,
    user: "User | None" = None,
    auth: "AuthService | None" = None,
) -> None:
    """Прогоняет все встроенные протоколы."""
    print()
    print("=" * 70)
    print(f"ДЕМО: {len(DEMO_PROTOCOLS)} протоколов")
    print(f"Выход: {output_dir.resolve()}")
    if user:
        print(f"Роль:  {user.role}")
    print("=" * 70)

    last_output = None
    processed = 0
    skipped = 0

    for i, item in enumerate(DEMO_PROTOCOLS, 1):
        print(f"\n[{i}/{len(DEMO_PROTOCOLS)}] {item['label']}")

        # Изоляция врача: пропускаем чужих пациентов
        if (
            user is not None
            and auth is not None
            and user.role == "doctor"
            and not user.can_see_others
            and item["doctor"]["name"] != user.doctor_name
        ):
            print(
                f"  ⛔ Пропуск: врач {user.doctor_name} не видит "
                f"пациента врача {item['doctor']['name']}"
            )
            skipped += 1
            continue

        # Пациент видит только свой протокол (в демо — card_id == user.name)
        if user is not None and user.role == "patient":
            patient_card = item["patient"]["card_id"]
            if str(patient_card) != str(user.name):
                print(f"  ⛔ Пропуск: не ваш протокол (card_id={patient_card})")
                skipped += 1
                continue

        try:
            output_path, route = process_protocol(
                protocol=item["protocol"],
                study_type=item["study_type"],
                study_date=item["study_date"],
                patient=item["patient"],
                visit=item["visit"],
                doctor=item["doctor"],
                cfg=cfg,
                ext=ext,
                rt=rt,
                gen=gen,
                user=user,
                auth=auth,
            )
            print_short_report(item["label"], route, output_path)
            if output_path:
                last_output = output_path
                processed += 1
        except (KeyError, ValueError, AttributeError, TypeError) as e:
            print(f"  ❌ Ошибка: {type(e).__name__}: {e}")
            import traceback

            traceback.print_exc()

    print()
    print("=" * 70)
    print(f"ГОТОВО: обработано {processed}, пропущено {skipped}")
    print(f"Открыть: file://{output_dir.resolve()}/")
    print("=" * 70)

    if open_browser:
        # Открываем страницу входа, а не конкретный экран
        login_path = output_dir / "login.html"
        if not login_path.exists():
            import shutil
            src = ROOT / "templates" / "login_static.html"
            if src.exists():
                shutil.copy(src, login_path)

        if login_path.exists():
            print(f"\n🌐 Открываю страницу входа: {login_path.name}")
            uri = f"file://{login_path.resolve()}"
            try:
                import webbrowser
                ok = webbrowser.open(uri)
            except Exception:
                ok = False

            if not ok:
                print("⚠️  Браузер не открылся автоматически. Откройте вручную:")
                print(f"    {uri}")
                print(f"    Или в Windows: explorer.exe output/")
        else:
            print(f"⚠️  Не найден {login_path}. Проверьте templates/login_static.html")


def run_single(
    protocol_path: Path,
    patient_name: str,
    patient_age: int,
    study_type: str,
    study_date: str,
    cfg,
    ext,
    rt,
    gen,
    output_dir: Path,
    open_browser: bool,
    user: "User | None" = None,
    auth: "AuthService | None" = None,
) -> None:
    """Прогоняет один протокол из файла."""
    if not protocol_path.exists():
        print(f"❌ Файл не найден: {protocol_path}")
        sys.exit(1)

    protocol = protocol_path.read_text(encoding="utf-8")
    initials = "".join(p[0] for p in patient_name.split()[:2]).upper()

    patient = {
        "name": patient_name,
        "initials": initials,
        "age": patient_age,
        "sex_label": "—",
        "card_id": "auto",
    }
    visit = {
        "date": study_date or "—",
        "time": "—",
        "doctor": "—",
    }

    # Врач для записи в аудит: если это doctor-роль — его имя, иначе "—"
    if user is not None and user.doctor_name:
        doctor = {"name": user.doctor_name, "initials": user.doctor_initials}
    else:
        doctor = {"name": "Врач", "initials": "ВР"}

    print(f"\n📄 Обрабатываю {protocol_path.name}...")
    output_path, route = process_protocol(
        protocol=protocol,
        study_type=study_type,
        study_date=study_date,
        patient=patient,
        visit=visit,
        doctor=doctor,
        cfg=cfg,
        ext=ext,
        rt=rt,
        gen=gen,
        user=user,
        auth=auth,
    )

    print()
    print("=" * 70)
    print("РЕЗУЛЬТАТ:")
    print("=" * 70)
    print(f"  status:            {route.status}")
    print(f"  specialist:        {route.specialist}")
    print(f"  urgency:           {route.urgency}")
    print(f"  deadline_days:     {route.deadline_days}")
    print(f"  scenario:          {route.scenario}")
    print(f"  multidisciplinary: {route.multidisciplinary}")
    print(f"  status_label:      {route.status_label}")
    print(f"  reason:            {route.reason}")
    print(f"  finding_summary:   {route.finding_summary}")
    print(f"  all_findings:      {len(route.all_findings)}")
    if output_path:
        print(f"\n  HTML: file://{output_path.resolve()}")

    if open_browser and output_path:
        webbrowser.open(f"file://{output_path.resolve()}")


# ============================================================================
#                        АУТЕНТИФИКАЦИЯ
# ============================================================================


def resolve_user(args, loader_dir: Path) -> tuple["User | None", "AuthService | None"]:
    """
    Определяет пользователя по API-ключу или роли.

    Приоритет:
      1. SM_CLINIC_API_KEY (env)
      2. --api-key
      3. --role (только для демо/отладки)
      4. fallback: admin (если roles.yaml отсутствует)
    """
    if not AUTH_AVAILABLE:
        print("⚠️  auth.py не найден — работаю без авторизации")
        return None, None

    roles_path = loader_dir / "roles.yaml"

    # Если roles.yaml нет — работаем без авторизации (fallback для демо)
    if not roles_path.exists():
        print(f"⚠️  {roles_path} не найден — работаю без авторизации")
        return None, None

    auth = AuthService(roles_path)

    # 1. Env
    api_key = os.environ.get("SM_CLINIC_API_KEY")
    source = "env SM_CLINIC_API_KEY"

    # 2. --api-key
    if not api_key and args.api_key:
        api_key = args.api_key
        source = "--api-key"

    # 3. Аутентификация по ключу
    if api_key:
        try:
            user = auth.authenticate(api_key)
            print(f"🔑 Аутентифицирован ({source}): "
                  f"{user.name or user.doctor_name or user.role} "
                  f"[{user.role}]")
            return user, auth
        except AuthError as e:
            print(f"❌ Ошибка авторизации: {e}")
            sys.exit(403)

    # 4. Явная роль (только для демо)
    if args.role:
        role = args.role
        if role not in auth.roles:
            print(f"❌ Неизвестная роль: {role}")
            print(f"   Доступные: {list(auth.roles.keys())}")
            sys.exit(403)
        print(f"⚠️  Демо-режим: роль '{role}' без API-ключа")
        return (
            User(role=role, name=role, permissions=auth.roles[role]),
            auth,
        )

    # 5. Ничего не передано — отказ
    print("❌ Не указан API-ключ или роль.")
    print("   Используйте: --api-key <key>  или  --role <role>")
    print(f"   Пример: python main.py --demo --role admin")
    sys.exit(401)


# ============================================================================
#                        CLI
# ============================================================================


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Система автоматической маршрутизации пациентов (MVP)",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Примеры:
  python3 main.py --demo --role admin
  python3 main.py --demo --api-key admin_key_root
  python3 main.py --demo --api-key doctor_key_abc123
  python3 main.py --demo --api-key manager_key_xyz789
  python3 main.py --protocol protocol.txt \\
      --patient-name "Иванова А.С." --patient-age 30 \\
      --api-key doctor_key_abc123
        """,
    )

    # --- Режимы ---
    parser.add_argument("--demo", action="store_true",
                        help="Прогнать встроенные протоколы")
    parser.add_argument("--protocol", type=Path,
                        help="Путь к файлу с протоколом")

    # --- Данные пациента ---
    parser.add_argument("--patient-name", type=str, default="Пациент П.П.",
                        help="ФИО пациента")
    parser.add_argument("--patient-age", type=int, default=0,
                        help="Возраст пациента")
    parser.add_argument("--study-type", type=str, default="УЗИ",
                        help="Тип исследования")
    parser.add_argument("--study-date", type=str, default="",
                        help="Дата исследования (DD.MM.YYYY)")

    # --- Вывод ---
    parser.add_argument("--output-dir", type=Path, default=Path("output"),
                        help="Папка для HTML (по умолчанию ./output)")
    parser.add_argument("--open", action="store_true",
                        help="Открыть результат в браузере")

    # --- Авторизация ---
    parser.add_argument("--api-key", type=str, default=None,
                        help="API-ключ (см. config/roles.yaml)")
    parser.add_argument(
        "--role",
        type=str,
        default=None,
        choices=["patient", "doctor", "manager", "admin"],
        help="Роль для демо-режима (без ключа)",
    )

    args = parser.parse_args()

    # Логирование
    logging.basicConfig(
        level=logging.WARNING,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    )

    # Загрузка конфигов
    print("🔧 Загрузка конфигов...")
    loader = ConfigLoader(ROOT / "config")
    cfg = loader.load()

    # Аутентификация
    user, auth = resolve_user(args, ROOT / "config")

    # Проверка прав на действие
    action = "demo" if args.demo else ("protocol" if args.protocol else None)
    if action and user is not None and auth is not None:
        try:
            auth.require(user, action)
        except PermissionDenied as e:
            print(f"❌ Доступ запрещён: {e}")
            sys.exit(403)

    # Инициализация модулей
    ext = Extractor(cfg)
    rt = Router(cfg)
    gen = Generator(
        templates_dir=ROOT / "templates",
        output_dir=args.output_dir,
    )

    print(
        f"✅ Загружено: {len(cfg.organs)} органов, "
        f"{len(cfg.disputes)} спорных ситуаций"
    )

    # Режим
    if args.demo:
        run_demo(cfg, ext, rt, gen, args.output_dir, args.open,
                 user=user, auth=auth)
    elif args.protocol:
        run_single(
            protocol_path=args.protocol,
            patient_name=args.patient_name,
            patient_age=args.patient_age,
            study_type=args.study_type,
            study_date=args.study_date,
            cfg=cfg,
            ext=ext,
            rt=rt,
            gen=gen,
            output_dir=args.output_dir,
            open_browser=args.open,
            user=user,
            auth=auth,
        )
    else:
        parser.print_help()
        print("\n⚠️  Укажите --demo или --protocol <file>")
        sys.exit(1)


if __name__ == "__main__":
    main()
