"""
auth.py — Аутентификация и авторизация.

Использование:
    from auth import AuthService, PermissionDenied

    auth = AuthService(ROOT / "config" / "roles.yaml")
    user = auth.authenticate(api_key="doctor_key_abc123")
    auth.require(user, "demo")           # бросит PermissionDenied, если нельзя
    visible = auth.filter_record(user, record)  # скроет ПДн, если нужно
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path

import yaml

log = logging.getLogger("auth")


class AuthError(Exception):
    """Базовая ошибка авторизации."""


class PermissionDenied(AuthError):
    """Недостаточно прав."""


@dataclass
class User:
    """Аутентифицированный пользователь."""

    role: str
    name: str = ""
    doctor_name: str = ""
    doctor_initials: str = ""
    permissions: dict = field(default_factory=dict)

    def can(self, action: str) -> bool:
        allowed = self.permissions.get("can_run", [])
        return "*" in allowed or action in allowed

    @property
    def can_see_pii(self) -> bool:
        return bool(self.permissions.get("can_see_pii", False))

    @property
    def can_see_others(self) -> bool:
        return bool(self.permissions.get("can_see_others", False))

    @property
    def can_see_aggregates(self) -> bool:
        return bool(self.permissions.get("can_see_aggregates", False))

    @property
    def can_edit_config(self) -> bool:
        return bool(self.permissions.get("can_edit_config", False))


class AuthService:
    """Загружает роли и проверяет права."""

    def __init__(self, roles_path: Path):
        if not roles_path.exists():
            raise FileNotFoundError(f"Не найден {roles_path}")
        with open(roles_path, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}
        self.roles: dict[str, dict] = data.get("roles", {})
        self.api_keys: dict[str, dict] = data.get("api_keys", {})
        log.info(f"Загружено ролей: {len(self.roles)}, ключей: {len(self.api_keys)}")

    # ------------------------------------------------------------------
    #  Аутентификация
    # ------------------------------------------------------------------

    def authenticate(self, api_key: str | None) -> User:
        """Проверяет API-ключ, возвращает User."""
        if not api_key:
            raise AuthError("API-ключ не передан")

        entry = self.api_keys.get(api_key)
        if not entry:
            raise AuthError(f"Неизвестный API-ключ: {api_key[:8]}…")

        role = entry.get("role", "patient")
        if role not in self.roles:
            raise AuthError(f"Роль '{role}' не определена в roles.yaml")

        return User(
            role=role,
            name=entry.get("name", ""),
            doctor_name=entry.get("doctor_name", ""),
            doctor_initials=entry.get("doctor_initials", ""),
            permissions=self.roles[role],
        )

    # ------------------------------------------------------------------
    #  Авторизация
    # ------------------------------------------------------------------

    def require(self, user: User, action: str) -> None:
        """Бросает PermissionDenied, если действие запрещено."""
        if not user.can(action):
            raise PermissionDenied(
                f"Роль '{user.role}' не может выполнять '{action}'. "
                f"Доступно: {user.permissions.get('can_run', [])}"
            )

    # ------------------------------------------------------------------
    #  Изоляция данных (ПДн)
    # ------------------------------------------------------------------

    PII_FIELDS = ("patient_name", "patient_id", "patient_age", "doctor")

    def filter_record(self, user: User, record: dict) -> dict:
        """Убирает ПДн, если роль не имеет права их видеть."""
        if user.can_see_pii:
            return record

        filtered = dict(record)
        for field in self.PII_FIELDS:
            if field in filtered:
                filtered[field] = "—"  # или хэш: f"пациент_{hash}"
        return filtered

    def filter_records(self, user: User, records: list[dict]) -> list[dict]:
        """Фильтрует список записей."""
        return [self.filter_record(user, r) for r in records]

    # ------------------------------------------------------------------
    #  Фильтрация по «своим» пациентам (для врача)
    # ------------------------------------------------------------------

    def filter_by_doctor(self, user: User, records: list[dict]) -> list[dict]:
        """Врач видит только своих пациентов."""
        if user.can_see_others:
            return records
        if not user.doctor_name:
            return []  # у пациента/менеджера нет doctor_name
        return [
            r for r in records
            if r.get("doctor") == user.doctor_name
        ]
