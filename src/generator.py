"""
generator.py — Рендер HTML-страниц через Jinja2.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import TYPE_CHECKING, Any

from jinja2 import Environment, FileSystemLoader, select_autoescape

if TYPE_CHECKING:
    from router import Route

log = logging.getLogger("generator")


BANNER_STYLES = {
    "emergency": {
        "bg": "#FDECEA",
        "border": "#F5A6A0",
        "left": "#E53935",
        "head": "#991B1B",
        "body": "#7F1D1D",
        "bold": "#5B1414",
        "hover": "#FEE2E2",
    },
    "oncological": {
        "bg": "#FFF4E6",
        "border": "#F5D97A",
        "left": "#D97706",
        "head": "#7A5A00",
        "body": "#5C4A00",
        "bold": "#3F3300",
        "hover": "#FFEAC2",
    },
    "urgent": {
        "bg": "#FEF3C7",
        "border": "#FCD34D",
        "left": "#F59E0B",
        "head": "#78350F",
        "body": "#78350F",
        "bold": "#451A03",
        "hover": "#FDE68A",
    },
    "planned": {
        "bg": "#FFF8E6",
        "border": "#F5D97A",
        "left": "#F5B400",
        "head": "#7A5A00",
        "body": "#5C4A00",
        "bold": "#3F3300",
        "hover": "#FFF4D6",
    },
    "observation": {
        "bg": "#F3F4F6",
        "border": "#D1D5DB",
        "left": "#9CA3AF",
        "head": "#374151",
        "body": "#4B5563",
        "bold": "#1F2937",
        "hover": "#E5E7EB",
    },
}

URGENCY_LABELS = {
    "emergency": "🚨 Срочно",
    "oncological": "⚠️ Онконастороженность",
    "urgent": "⏰ Ускоренно",
    "planned": "📅 Планово",
    "observation": "👁 Наблюдение",
    "negative": "❌ Отрицание",
}


class Generator:
    def __init__(self, templates_dir="./templates", output_dir="./output"):
        self.templates_dir = Path(templates_dir)
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.env = Environment(
            loader=FileSystemLoader(str(self.templates_dir)),
            autoescape=select_autoescape(["html", "xml"]),
            trim_blocks=True,
            lstrip_blocks=True,
        )

    def prepare_context(self, route, patient, visit, meta, doctor=None):
        banner = BANNER_STYLES.get(route.urgency, BANNER_STYLES["planned"])
        doctor = doctor or {"name": "Врач", "initials": "ВР"}
        return {
            "route": route,
            "primary": route.primary_finding,
            "patient": patient,
            "visit": visit,
            "doctor_name": doctor.get("name", "Врач"),
            "doctor_initials": doctor.get("initials", "ВР"),
            "banner_bg": banner["bg"],
            "banner_border": banner["border"],
            "banner_left": banner["left"],
            "banner_head_color": banner["head"],
            "banner_body_color": banner["body"],
            "banner_bold_color": banner["bold"],
            "banner_hover": banner["hover"],
            "urgency_labels": URGENCY_LABELS,
            "meta": meta,
        }

    def render_doctor(self, route, patient, visit, meta, doctor=None, output_name=None):
        context = self.prepare_context(route, patient, visit, meta, doctor)
        template = self.env.get_template("doctor.html.j2")
        html = template.render(**context)
        if output_name is None:
            patient_id = patient.get("card_id", "unknown")
            output_name = f"doctor_{patient_id}.html"
        output_path = self.output_dir / output_name
        output_path.write_text(html, encoding="utf-8")
        log.info(f"Записан {output_path}")
        return output_path

    def render_patient(
        self,
        route: Route,
        patient: dict[str, Any],
        visit: dict[str, Any],
        meta: dict[str, Any],
        output_name: str | None = None,
    ) -> Path:
        """
        Рендерит templates/patient.html.j2 → output/patient_<id>.html.

        Использует тот же prepare_context, что и render_doctor, но
        не передаёт doctor (пациенту он не нужен).
        """
        context = self.prepare_context(
            route=route,
            patient=patient,
            visit=visit,
            meta=meta,
            doctor=None,
        )

        template = self.env.get_template("patient.html.j2")
        html = template.render(**context)

        if output_name is None:
            patient_id = patient.get("card_id", "unknown")
            output_name = f"patient_{patient_id}.html"

        output_path = self.output_dir / output_name
        output_path.write_text(html, encoding="utf-8")
        log.info(f"Записан {output_path}")
        return output_path
