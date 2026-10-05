"""
Тесты для модуля extractor.
"""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from config_loader import ConfigLoader
from extractor import Extractor


def _make_extractor():
    cfg = ConfigLoader(str(ROOT / "config")).load()
    return Extractor(cfg)


def test_extract_polyp():
    """Полип эндометрия → триггер omt_polip_endometriya."""
    ext = _make_extractor()
    result = ext.extract(
        "УЗИ ОМТ. В полости матки лоцируется образование 12 мм — полип эндометрия."
    )
    ids = [f.id for f in result.findings]
    assert any("polip" in i for i in ids)


def test_negation_in_extract():
    """Полип не выявлен → отрицательная находка."""
    ext = _make_extractor()
    result = ext.extract("УЗИ ОМТ. Полип эндометрия не выявлен.")
    assert any(f.negated for f in result.findings)


def test_extract_thyroid():
    """Узлы ЩЖ → триггер thyroid_uzel."""
    ext = _make_extractor()
    result = ext.extract(
        "УЗИ щитовидной железы. В правой доле узлы 15х14 мм."
    )
    ids = [f.id for f in result.findings]
    assert any("thyroid_uzel" in i for i in ids)


def test_organ_detection():
    """Определение органа ЩЖ."""
    ext = _make_extractor()
    result = ext.extract("УЗИ щитовидной железы. Узлы.")
    assert "thyroid" in result.organ_codes
