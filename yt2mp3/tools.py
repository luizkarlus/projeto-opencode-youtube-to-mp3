"""Localização dos binários de motor: yt-dlp e ffmpeg.

O app original embutia o próprio extrator e dependia do ffmpeg do sistema
(FFMpegDetector / FFMpegWrapper). Aqui o extrator é o yt-dlp, que pode vir
vendorizado junto do pacote ou do sistema, e o ffmpeg é detectado da mesma
forma e reportado com mensagem clara quando ausente.
"""

from __future__ import annotations

import os
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path

# Pasta onde o .deb instala os binários vendorizados.
SYSTEM_VENDOR_DIR = Path("/usr/lib/yt2mp3/vendor")
# Pasta vendorizada no checkout de desenvolvimento (../vendor).
DEV_VENDOR_DIR = Path(__file__).resolve().parent.parent / "vendor"


def _vendor_dirs() -> list[Path]:
    dirs = []
    env = os.environ.get("YT2MP3_VENDOR_DIR")
    if env:
        dirs.append(Path(env))
    dirs.extend([SYSTEM_VENDOR_DIR, DEV_VENDOR_DIR])
    return dirs


def _is_executable(path: Path) -> bool:
    return path.is_file() and os.access(path, os.X_OK)


def _run_version(binary: Path, args: list[str]) -> str | None:
    try:
        out = subprocess.run(
            [str(binary), *args],
            capture_output=True,
            text=True,
            timeout=20,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    line = (out.stdout or out.stderr).strip().splitlines()
    return line[0].strip() if line else None


@dataclass
class ToolStatus:
    path: Path | None
    version: str | None

    @property
    def available(self) -> bool:
        return self.path is not None

    @property
    def label(self) -> str:
        if not self.available:
            return "não encontrado"
        return self.version or str(self.path)


def find_ytdlp(configured: str = "auto") -> ToolStatus:
    """Localiza o yt-dlp: caminho configurado, vendorizado ou no PATH."""
    candidates: list[Path] = []
    if configured and configured != "auto":
        candidates.append(Path(os.path.expanduser(configured)))
    for directory in _vendor_dirs():
        candidates.append(directory / "yt-dlp")
        candidates.append(directory / "yt-dlp_linux")
    which = shutil.which("yt-dlp")
    if which:
        candidates.append(Path(which))

    for candidate in candidates:
        if _is_executable(candidate):
            version = _run_version(candidate, ["--version"])
            if version:
                return ToolStatus(candidate, f"yt-dlp {version}")

    # Último recurso: módulo Python instalado via pip.
    try:
        import yt_dlp  # type: ignore

        return ToolStatus(None, f"módulo yt_dlp {yt_dlp.version.__version__}")
    except Exception:
        pass
    return ToolStatus(None, None)


def find_ffmpeg(configured: str = "auto") -> ToolStatus:
    """Localiza o ffmpeg e confirma que o ffprobe acompanha (yt-dlp exige os dois)."""
    roots: list[Path] = []
    if configured and configured != "auto":
        roots.append(Path(os.path.expanduser(configured)))
    for directory in _vendor_dirs():
        roots.append(directory)
        roots.append(directory / "ffmpeg")
    which = shutil.which("ffmpeg")
    if which:
        roots.append(Path(which))

    seen: set[Path] = set()
    for root in roots:
        directory = root if root.is_dir() else root.parent
        if directory in seen:
            continue
        seen.add(directory)
        ffmpeg = directory / "ffmpeg"
        ffprobe = directory / "ffprobe"
        if _is_executable(ffmpeg) and _is_executable(ffprobe):
            version = _run_version(ffmpeg, ["-version"])
            return ToolStatus(ffmpeg, version)
    return ToolStatus(None, None)


def ytdlp_ffmpeg_location(ffmpeg: ToolStatus) -> str | None:
    """Diretório que deve ser passado a --ffmpeg-location."""
    if not ffmpeg.available or ffmpeg.path is None:
        return None
    return str(ffmpeg.path.parent)
