from __future__ import annotations


def index_to_column_letter(idx: int) -> str:
    result = ""
    idx += 1
    while idx > 0:
        idx -= 1
        result = chr(65 + (idx % 26)) + result
        idx //= 26
    return result


def parse_int(val: str) -> int:
    try:
        return int(val.strip()) if val.strip() else 0
    except ValueError:
        return 0
