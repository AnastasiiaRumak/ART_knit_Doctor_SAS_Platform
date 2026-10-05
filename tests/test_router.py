"""
Тесты для модуля router.
"""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from config_loader import ConfigLoader
from extractor import Extractor
from router import Router


def _make_router():
    cfg = ConfigLoader(str(ROOT / "config")).load()
    ext = Extractor(cfg)
    rt = Router(cfg)
    return ext, rt


def test_router_polyp():
    """Полип эндометрия → Гинеколог, planned."""
    ext, rt = _make_router()
    route = rt.build(
        ext.extract("УЗИ ОМТ. Полип эндометрия 12 мм."),
        study_type="УЗИ ОМТ", study_date="",
    )
    assert route.status == "assigned"
    assert "Гинеколог" in route.specialist
    assert route.urgency == "planned"


def test_router_no_action():
    """Нет находок → no_action."""
    ext, rt = _make_router()
    route = rt.build(
        ext.extract("УЗИ ОМТ. Без патологии."),
        study_type="УЗИ ОМТ", study_date="",
    )
    assert route.status == "no_action"


def test_router_thyroid():
    """Узлы ЩЖ → Эндокринолог, planned."""
    ext, rt = _make_router()
    route = rt.build(
        ext.extract("УЗИ ЩЖ. Узлы 15х14 мм."),
        study_type="УЗИ ЩЖ", study_date="",
    )
    assert "Эндокринолог" in route.specialist
    assert route.urgency == "planned"


def test_router_emergency_trombosis():
    """Тромбоз → emergency (Сосудистый хирург)."""
    ext, rt = _make_router()
    route = rt.build(
        ext.extract("УЗИ вен нижних конечностей. Тромбоз глубоких вен."),
        study_type="УЗИ вен", study_date="",
    )
    assert route.urgency == "emergency"
    assert "Сосудистый хирург" in route.specialist


def test_router_no_false_dispute():
    """Фиброаденома → НЕ должна вызывать dispute."""
    ext, rt = _make_router()
    route = rt.build(
        ext.extract("УЗИ МЖ. Фиброаденома 12 мм. BI-RADS 3."),
        study_type="УЗИ МЖ", study_date="",
    )
    # dispute_applied может быть None или '' — оба варианта = "не применён"
    assert not route.dispute_applied
    assert route.urgency == "planned"
