"""Ponto de entrada: python3 -m yt2mp3 [URL ...]"""

from __future__ import annotations

import sys

from .application import main

if __name__ == "__main__":
    sys.exit(main())
