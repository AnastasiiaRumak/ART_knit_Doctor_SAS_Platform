# ============================================================
# ArtKnit v1.0 — Makefile
# Система автоматической маршрутизации пациентов
# ============================================================
# Python 3.11+ / venv / pandas / jinja2 / python-docx
# ============================================================
# Использование:
#   make setup          — создать venv + установить ВСЕ зависимости
#   make all            — полный цикл: setup + parse + test-real + demo + manager
# ============================================================
# Основные:
#   make setup          — установка
#   make parse          — пересобрать YAML из таблиц
#   make test-real      — прогнать 89 реальных протоколов
#   make test           — unit-тесты (pytest)
#   make demo           — сгенерировать 9 HTML (врач + пациент)
#   make manager        — построить дашборд руководителя
# ============================================================
# Открыть экраны:
#   make open-doctor    — экран врача (Кардио, urgent)
#   make open-patient   — экран пациента (ЩЖ)
#   make open-manager   — дашборд руководителя
#   make open-all       — все HTML в браузере
# ============================================================
# Качество кода (Python-аналоги clang/cppcheck):
#   make format         — форматировать код (black + ruff)
#   make lint           — проверить код (ruff)
#   make valgrind       — проверить память (tracemalloc)
#   make coverage       — отчёт покрытия (pytest-cov)
#   make profile        — профилировать узкие места
# ============================================================
# Утилиты:
#   make audit          — журнал аудита
#   make metrics        — метрики
#   make dvi            — открыть README
#   make dist           — собрать дистрибутив
#   make clean          — очистить output/ и кэш
#   make clean-all      — очистить + venv
# ============================================================

# ------------------------------------------------------------
# Настройки
# ------------------------------------------------------------
VENV       := venv
PYTHON     := python3
PIP        := $(VENV)/bin/pip
VENV_PY    := $(VENV)/bin/python

INPUT_DIR  := ./data
OUTPUT_DIR := ./config
HTML_DIR   := ./output
EXAMPLES   := ./examples

DIST_NAME  := artknit-1.0.tar.gz

# Цвета
GREEN  := \033[0;32m
YELLOW := \033[0;33m
BLUE   := \033[0;34m
RED    := \033[0;31m
NC     := \033[0m

# ------------------------------------------------------------
# Help (по умолчанию)
# ------------------------------------------------------------
.PHONY: help
help:
	@echo ""
	@echo "$(BLUE)╔══════════════════════════════════════════════════════════╗$(NC)"
	@echo "$(BLUE)║  ArtKnit v1.0 — Система маршрутизации пациентов          ║$(NC)"
	@echo "$(BLUE)╚══════════════════════════════════════════════════════════╝$(NC)"
	@echo ""
	@echo "  $(GREEN)Основные:$(NC)"
	@echo "    make setup          — создать venv + установить зависимости"
	@echo "    make parse          — пересобрать YAML из таблиц"
	@echo "    make test-real      — прогнать 89 реальных протоколов"
	@echo "    make test           — unit-тесты (pytest)"
	@echo "    make demo           — сгенерировать 9 HTML"
	@echo "    make manager        — построить дашборд"
	@echo "    make all            — полный цикл с нуля"
	@echo ""
	@echo "  $(GREEN)Открыть экраны:$(NC)"
	@echo "    make open-doctor    — экран врача (Кардио, urgent)"
	@echo "    make open-patient   — экран пациента (ЩЖ)"
	@echo "    make open-manager   — дашборд руководителя"
	@echo "    make open-all       — все HTML"
	@echo ""
	@echo "  $(GREEN)Качество кода:$(NC)"
	@echo "    make format         — форматировать код"
	@echo "    make lint           — проверить код"
	@echo "    make valgrind       — проверить память"
	@echo "    make coverage       — покрытие тестами"
	@echo "    make profile        — профилирование"
	@echo ""
	@echo "  $(GREEN)Утилиты:$(NC)"
	@echo "    make audit          — журнал аудита"
	@echo "    make metrics        — метрики"
	@echo "    make dvi            — открыть README"
	@echo "    make dist           — собрать дистрибутив"
	@echo "    make clean          — очистить output/"
	@echo "    make clean-all      — очистить + venv"
	@echo ""

# ------------------------------------------------------------
# 1. Установка
# ------------------------------------------------------------
.PHONY: setup
setup:
	@echo "$(BLUE)🔧 Создаю venv...$(NC)"
	@$(PYTHON) -m venv $(VENV)
	@echo "$(BLUE)📦 Устанавливаю зависимости...$(NC)"
	@$(PIP) install --upgrade pip --quiet
	@$(PIP) install --quiet \
		pandas openpyxl PyYAML jinja2 pytest \
		python-docx black ruff pytest-cov
	@echo "$(GREEN)✅ Готово! Активируйте: source $(VENV)/bin/activate$(NC)"

.PHONY: install
install: setup

# ------------------------------------------------------------
# 2. Парсинг таблиц
# ------------------------------------------------------------
.PHONY: parse
parse:
	@echo "$(BLUE)📊 Пересобираю YAML из таблиц...$(NC)"
	@$(VENV_PY) parse_tables.py --input-dir $(INPUT_DIR) --output-dir $(OUTPUT_DIR)
	@echo "$(GREEN)✅ Конфиги обновлены$(NC)"

# ------------------------------------------------------------
# 3. Тесты на реальных протоколах
# ------------------------------------------------------------
.PHONY: test-real
test-real:
	@echo "$(BLUE)🧪 Прогоняю 89 реальных протоколов...$(NC)"
	@$(VENV_PY) scripts/test_on_real.py
	@echo "$(GREEN)✅ Метрики: output/metrics_report.json$(NC)"

# ------------------------------------------------------------
# 4. Unit-тесты
# ------------------------------------------------------------
.PHONY: test
test:
	@echo "$(BLUE)🧪 Прогоняю unit-тесты...$(NC)"
	@$(VENV_PY) -m pytest tests/ -v || true
	@echo "$(GREEN)✅ Тесты завершены$(NC)"

# ------------------------------------------------------------
# 5. Дашборд руководителя
# ------------------------------------------------------------
.PHONY: manager
manager:
	@echo "$(BLUE)📊 Строю дашборд руководителя...$(NC)"
	@$(VENV_PY) scripts/build_manager.py
	@echo "$(GREEN)✅ Дашборд: output/manager.html$(NC)"

# ------------------------------------------------------------
# 6. Демо — 9 HTML
# ------------------------------------------------------------
.PHONY: demo
demo:
	@echo "$(BLUE)🎬 Генерирую HTML (9 протоколов)...$(NC)"
	@$(VENV_PY) main.py --demo
	@echo "$(GREEN)✅ 9 файлов в $(HTML_DIR)/$(NC)"

.PHONY: demo-open
demo-open:
	@echo "$(BLUE)🎬 Генерирую + открываю...$(NC)"
	@$(VENV_PY) main.py --demo --open

# ------------------------------------------------------------
# 7. Открыть экраны
# ------------------------------------------------------------
.PHONY: open-doctor
open-doctor:
	@echo "$(BLUE)👨‍⚕️  Экран врача (Кардио, urgent)$(NC)"
	@xdg-open $(HTML_DIR)/doctor_1030.html 2>/dev/null || \
		firefox $(HTML_DIR)/doctor_1030.html 2>/dev/null || \
		open $(HTML_DIR)/doctor_1030.html 2>/dev/null || \
		echo "$(RED)❌ Откройте вручную: $(HTML_DIR)/doctor_1030.html$(NC)"

.PHONY: open-patient
open-patient:
	@echo "$(BLUE)🤒 Экран пациента (ЩЖ)$(NC)"
	@xdg-open $(HTML_DIR)/patient_1032.html 2>/dev/null || \
		firefox $(HTML_DIR)/patient_1032.html 2>/dev/null || \
		open $(HTML_DIR)/patient_1032.html 2>/dev/null || \
		echo "$(RED)❌ Откройте вручную: $(HTML_DIR)/patient_1032.html$(NC)"

.PHONY: open-manager
open-manager:
	@echo "$(BLUE)📊 Дашборд руководителя$(NC)"
	@xdg-open $(HTML_DIR)/manager.html 2>/dev/null || \
		firefox $(HTML_DIR)/manager.html 2>/dev/null || \
		open $(HTML_DIR)/manager.html 2>/dev/null || \
		echo "$(RED)❌ Откройте вручную: $(HTML_DIR)/manager.html$(NC)"

.PHONY: open-all
open-all:
	@echo "$(BLUE)🌐 Открываю 3 ключевых экрана...$(NC)"
	@$(MAKE) --no-print-directory open-doctor
	@sleep 1
	@$(MAKE) --no-print-directory open-patient
	@sleep 1
	@$(MAKE) --no-print-directory open-manager
	@echo "$(GREEN)✅ Открыто$(NC)"

# ------------------------------------------------------------
# 8. Полный цикл
# ------------------------------------------------------------
.PHONY: all
all: setup parse test-real demo manager
	@echo ""
	@echo "$(GREEN)╔══════════════════════════════════════════════════════════╗$(NC)"
	@echo "$(GREEN)║  ✅ ВСЁ ГОТОВО!                                          ║$(NC)"
	@echo "$(GREEN)╚══════════════════════════════════════════════════════════╝$(NC)"
	@echo ""
	@echo "  Конфиги:  $(OUTPUT_DIR)/"
	@echo "  HTML:     $(HTML_DIR)/"
	@echo "  Метрики:  $(HTML_DIR)/metrics_report.json"
	@echo "  Аудит:    $(HTML_DIR)/routes_audit.jsonl"
	@echo ""
	@echo "  $(GREEN)Открыть экраны:$(NC)  make open-all"
	@echo ""

# ------------------------------------------------------------
# 9. КАЧЕСТВО КОДА (Python-аналоги clang/cppcheck/valgrind)
# ------------------------------------------------------------

# Форматирование (аналог clang-format)
.PHONY: format
format:
	@echo "$(BLUE)🎨 Форматирую код (black + ruff)...$(NC)"
	@$(VENV_PY) -m black src/ scripts/ main.py parse_tables.py 2>/dev/null || true
	@$(VENV_PY) -m ruff check --fix src/ scripts/ main.py parse_tables.py 2>/dev/null || true
	@echo "$(GREEN)✅ Код отформатирован$(NC)"

# Линтер (аналог cppcheck)
.PHONY: lint
lint:
	@echo "$(BLUE)🔍 Проверяю код (ruff)...$(NC)"
	@$(VENV_PY) -m ruff check src/ scripts/ main.py parse_tables.py 2>/dev/null || true
	@echo "$(GREEN)✅ Проверка завершена$(NC)"

# Проверка памяти (аналог valgrind — через tracemalloc)
.PHONY: valgrind
valgrind:
	@echo "$(BLUE)🧠 Проверяю память (tracemalloc)...$(NC)"
	@$(VENV_PY) scripts/check_memory.py 2>/dev/null || \
		echo "$(YELLOW)⚠️  scripts/check_memory.py не найден$(NC)"

# Покрытие тестами (аналог gcov_report)
.PHONY: coverage
coverage:
	@echo "$(BLUE)📊 Считаю покрытие (pytest-cov)...$(NC)"
	@$(VENV_PY) -m pytest tests/ \
		--cov=src \
		--cov-report=html:coverage_html \
		--cov-report=term \
		|| true
	@echo "$(GREEN)✅ Отчёт: coverage_html/index.html$(NC)"
	@xdg-open coverage_html/index.html 2>/dev/null || true

# Профилирование
.PHONY: profile
profile:
	@echo "$(BLUE)⏱️  Профилирую узкие места...$(NC)"
	@$(VENV_PY) scripts/profiler.py

# ------------------------------------------------------------
# 10. Утилиты
# ------------------------------------------------------------
.PHONY: audit
audit:
	@echo "$(BLUE)📋 Последние 5 записей журнала:$(NC)"
	@echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
	@tail -5 $(HTML_DIR)/routes_audit.jsonl 2>/dev/null || \
		echo "$(RED)❌ Журнал пуст — запустите make demo$(NC)"

.PHONY: metrics
metrics:
	@echo "$(BLUE)📊 Метрики:$(NC)"
	@cat $(HTML_DIR)/metrics_report.json 2>/dev/null | \
		$(VENV_PY) -m json.tool 2>/dev/null | head -30 || \
		echo "$(RED)❌ Метрики не найдены — запустите make test-real$(NC)"

.PHONY: dvi
dvi:
	@echo "$(BLUE)📖 Открываю README...$(NC)"
	@xdg-open README.md 2>/dev/null || \
		firefox README.md 2>/dev/null || \
		open README.md 2>/dev/null || \
		cat README.md

.PHONY: dist
dist: clean
	@echo "$(BLUE)📦 Собираю дистрибутив...$(NC)"
	@mkdir -p dist
	@tar -czf dist/$(DIST_NAME) \
		--exclude='venv' \
		--exclude='__pycache__' \
		--exclude='output' \
		--exclude='dist' \
		--exclude='.cache' \
		src/ templates/ config/ scripts/ examples/protocols_real \
		main.py parse_tables.py Makefile README.md requirements.txt
	@echo "$(GREEN)✅ Дистрибутив: dist/$(DIST_NAME)$(NC)"

# ------------------------------------------------------------
# 11. Очистка
# ------------------------------------------------------------
.PHONY: clean
clean:
	@echo "$(YELLOW)🧹 Удаляю output/, кэш и __pycache__...$(NC)"
	@rm -rf $(HTML_DIR)
	@rm -rf $(EXAMPLES)/.cache
	@rm -rf coverage_html .pytest_cache .ruff_cache
	@find . -type d -name "__pycache__" -exec rm -rf {} + 2>/dev/null || true
	@find . -type f -name "*.pyc" -delete 2>/dev/null || true
	@echo "$(GREEN)✅ Готово$(NC)"

.PHONY: clean-all
clean-all: clean
	@echo "$(YELLOW)🧹 Удаляю venv и dist...$(NC)"
	@rm -rf $(VENV)
	@rm -rf dist
	@echo "$(GREEN)✅ Готово$(NC)"
