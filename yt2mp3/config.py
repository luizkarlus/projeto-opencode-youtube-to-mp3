"""Configurações persistentes do yt2mp3.

Espelha as chaves que o app original da MediaHuman guardava
(output/format, output/bitrate, outputFolder, network/maxConnections,
speedLimit/globalBps, addIndexInPlaylistToFilename ...), mas em JSON
simples dentro de ~/.config/yt2mp3/settings.json.
"""

from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass, field
from pathlib import Path

from . import APP_NAME

# Formatos de saída suportados (mesmos do original: mp3 e m4a, mais livres).
AUDIO_FORMATS = {
    "mp3": "MP3",
    "m4a": "M4A (AAC)",
    "opus": "Opus",
    "flac": "FLAC",
    "wav": "WAV",
}

# Formatos sem perda não usam bitrate.
LOSSLESS_FORMATS = {"flac", "wav"}

BITRATES = ["320", "256", "192", "128", "96"]


def config_dir() -> Path:
    base = os.environ.get("XDG_CONFIG_HOME") or os.path.join(Path.home(), ".config")
    return Path(base) / APP_NAME


def default_output_dir() -> Path:
    music = os.environ.get("XDG_MUSIC_DIR")
    if music:
        return Path(music) / APP_NAME
    for candidate in ("Música", "Music"):
        path = Path.home() / candidate
        if path.is_dir():
            return path / APP_NAME
    return Path.home() / APP_NAME


@dataclass
class Settings:
    output_folder: str = field(default_factory=lambda: str(default_output_dir()))
    audio_format: str = "mp3"
    bitrate: str = "320"
    max_parallel: int = 2
    # Limite global de velocidade em KiB/s; 0 = ilimitado.
    speed_limit_kib: int = 0
    # Cria subpasta com o nome da playlist dentro da pasta de saída.
    playlist_subfolder: bool = False
    # Prefixa o nome do arquivo com a posição na playlist.
    index_in_filename: bool = True
    embed_thumbnail: bool = True
    add_metadata: bool = True
    # "auto" deixa o app localizar os binários sozinho.
    ytdlp_path: str = "auto"
    ffmpeg_path: str = "auto"

    @classmethod
    def load(cls) -> "Settings":
        path = config_dir() / "settings.json"
        if not path.is_file():
            return cls()
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return cls()
        known = {f for f in cls.__dataclass_fields__}  # type: ignore[attr-defined]
        return cls(**{k: v for k, v in raw.items() if k in known})

    def save(self) -> None:
        path = config_dir() / "settings.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(asdict(self), indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )

    def resolved_output_dir(self) -> Path:
        return Path(os.path.expanduser(self.output_folder))
