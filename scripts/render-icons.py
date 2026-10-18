#!/usr/bin/python3
"""Gera PNGs do ícone a partir do SVG usando o carregador SVG do GdkPixbuf.

Uso: scripts/render-icons.py <arquivo.svg> <diretório-de-saída>
Saída: <dir>/<tamanho>/apps/<nome>.png e <dir>/scalable/apps/<nome>.svg
"""

from __future__ import annotations

import sys
from pathlib import Path

import gi

gi.require_version("GdkPixbuf", "2.0")
from gi.repository import GdkPixbuf  # noqa: E402

SIZES = (16, 24, 32, 48, 64, 128, 256, 512)


def render(svg: Path, out_dir: Path) -> list[Path]:
    fmt, _w, _h = GdkPixbuf.Pixbuf.get_file_info(str(svg))
    if fmt is None:
        raise SystemExit(f"Nenhum carregador conseguiu abrir {svg}")

    stem = svg.stem
    written: list[Path] = []
    for size in SIZES:
        target = out_dir / f"{size}x{size}" / "apps"
        target.mkdir(parents=True, exist_ok=True)
        pixbuf = GdkPixbuf.Pixbuf.new_from_file_at_scale(str(svg), size, size, True)
        png = target / f"{stem}.png"
        pixbuf.savev(str(png), "png", [], [])
        written.append(png)

    scalable = out_dir / "scalable" / "apps"
    scalable.mkdir(parents=True, exist_ok=True)
    (scalable / svg.name).write_bytes(svg.read_bytes())
    written.append(scalable / svg.name)
    return written


def main(argv: list[str]) -> int:
    if len(argv) != 3:
        print(__doc__)
        return 2
    svg = Path(argv[1])
    out_dir = Path(argv[2])
    if not svg.is_file():
        print(f"SVG não encontrado: {svg}", file=sys.stderr)
        return 1
    for path in render(svg, out_dir):
        print(path)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
