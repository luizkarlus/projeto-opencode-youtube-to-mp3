"""Formatação de valores para a interface."""

from __future__ import annotations


def human_bytes(value: float) -> str:
    value = float(value or 0)
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if value < 1024 or unit == "TB":
            if unit == "B":
                return f"{int(value)} {unit}"
            return f"{value:.1f} {unit}"
        value /= 1024
    return f"{value:.1f} TB"


def human_speed(value: float) -> str:
    if not value:
        return ""
    return f"{human_bytes(value)}/s"


def human_eta(seconds: float) -> str:
    seconds = int(seconds or 0)
    if seconds <= 0:
        return ""
    if seconds >= 3600:
        return f"{seconds // 3600}h{(seconds % 3600) // 60:02d}m"
    return f"{seconds // 60}m{seconds % 60:02d}s"
