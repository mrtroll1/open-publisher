"""Contractor field validation rules."""

from __future__ import annotations

import re

from common.models import ContractorType


def _digits_only(val: str) -> str:
    return re.sub(r"\D", "", val)


def _check_email(email: str, warnings: list[str]) -> None:
    if email and not re.match(r"^[^@\s]+@[^@\s]+\.[^@\s]+$", email.strip()):
        warnings.append(f"Формат email выглядит некорректно (сейчас: {email})")


def validate_fields(collected: dict, ctype: ContractorType) -> list[str]:
    """Validate collected fields with regex checks. Returns list of warning strings."""
    warnings: list[str] = []

    if ctype in (ContractorType.SAMOZANYATY, ContractorType.IP):
        _validate_person_fields(collected, warnings)

    if ctype == ContractorType.IP:
        _validate_ip_fields(collected, warnings)

    if ctype == ContractorType.GLOBAL:
        _validate_global_fields(collected, warnings)

    return warnings


def _validate_person_fields(collected: dict, warnings: list[str]) -> None:
    ps = collected.get("passport_series", "")
    if ps and len(_digits_only(ps)) != 4:
        warnings.append(f"Серия паспорта должна содержать 4 цифры (сейчас: {ps})")

    pn = collected.get("passport_number", "")
    if pn and len(_digits_only(pn)) != 6:
        warnings.append(f"Номер паспорта должен содержать 6 цифр (сейчас: {pn})")

    inn = collected.get("inn", "")
    if inn and len(_digits_only(inn)) not in (10, 12):
        warnings.append(f"ИНН должен содержать 10 или 12 цифр (сейчас: {len(_digits_only(inn))})")

    ba = collected.get("bank_account", "")
    if ba and len(_digits_only(ba)) != 20:
        warnings.append(f"Номер счёта должен содержать 20 цифр (сейчас: {len(_digits_only(ba))})")

    bik = collected.get("bik", "")
    if bik and len(_digits_only(bik)) != 9:
        warnings.append(f"БИК должен содержать 9 цифр (сейчас: {len(_digits_only(bik))})")

    ca = collected.get("corr_account", "")
    if ca and len(_digits_only(ca)) != 20:
        warnings.append(f"Корр. счёт должен содержать 20 цифр (сейчас: {len(_digits_only(ca))})")

    pc = collected.get("passport_code", "")
    if pc and not re.match(r"^\d{3}-?\d{3}$", pc.strip()):
        warnings.append(f"Код подразделения: формат NNN-NNN (сейчас: {pc})")

    _validate_address_ru(collected.get("address", ""), warnings)
    _check_email(collected.get("email", ""), warnings)


def _validate_address_ru(address: str, warnings: list[str]) -> None:
    if not address:
        return
    issues = []
    if not re.search(r"\d{6}", address):
        issues.append("почтовый индекс (6 цифр)")
    if not re.search(r"(кв|квартира|офис|оф|пом|комн)\W*\d", address, re.IGNORECASE):
        issues.append("номер квартиры/офиса")
    if not re.search(r"(г\.|город|москва|санкт-петербург|спб|мск)", address, re.IGNORECASE):
        issues.append("город")
    if issues:
        warnings.append(f"В адресе, возможно, не хватает: {', '.join(issues)}")


def _validate_ip_fields(collected: dict, warnings: list[str]) -> None:
    ogrnip = collected.get("ogrnip", "")
    if ogrnip and len(_digits_only(ogrnip)) != 15:
        warnings.append(f"ОГРНИП должен содержать 15 цифр (сейчас: {len(_digits_only(ogrnip))})")


def _validate_global_fields(collected: dict, warnings: list[str]) -> None:
    swift = collected.get("swift", "")
    account = collected.get("bank_account", "")

    if swift and not re.match(r"^[A-Z0-9]{8}([A-Z0-9]{3})?$", swift.strip().upper()):
        warnings.append(f"SWIFT/BIC должен содержать 8 или 11 буквенно-цифровых символов (сейчас: {swift})")

    # IBAN validation only if it looks like IBAN (starts with 2 letters)
    if account and re.match(r"^[A-Z]{2}", account.strip().upper()):
        if not re.match(r"^[A-Z]{2}\d{2}[A-Z0-9]{4,30}$", account.strip().upper().replace(" ", "")):
            warnings.append(f"Формат IBAN выглядит некорректно (сейчас: {account})")

    _check_email(collected.get("email", ""), warnings)

    address = collected.get("address", "")
    if address and re.search(r"[а-яёА-ЯЁ]", address):
        warnings.append("Адрес должен быть латиницей (English)")
