"""
Тесты для модуля negations.
"""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

import yaml
from negations import NegationDetector


def _load():
    with open(ROOT / "config" / "negations.yaml", encoding="utf-8") as f:
        data = yaml.safe_load(f)
    return NegationDetector(
        negations=data.get("negations", []),
        negation_triggers=data.get("negation_triggers", []),
    )


def test_negation_detected():
    """Полип эндометрия не выявлен → отрицание."""
    d = _load()
    result = d.check("Полип эндометрия не выявлен.", "полип эндометрия")
    assert result.is_negated is True


def test_negation_not_detected():
    """Выявлен полип эндометрия → триггер (не отрицание)."""
    d = _load()
    result = d.check("Выявлен полип эндометрия 12 мм.", "полип эндометрия")
    assert result.is_negated is False


def test_soft_trigger_not_negation():
    """Нельзя исключить полип → мягкий триггер (не отрицание)."""
    d = _load()
    result = d.check("Нельзя исключить полип эндометрия.", "полип эндометрия")
    assert result.is_negated is False
    assert "мягкий" in result.reason.lower()


def test_absence_detected():
    """Свободная жидкость не лоцируется → отрицание."""
    d = _load()
    result = d.check(
        "Свободная жидкость в малом тазу не лоцируется.",
        "свободная жидкость",
    )
    assert result.is_negated is True
