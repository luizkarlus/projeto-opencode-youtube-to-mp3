#!/usr/bin/env bash
#
# Monta o pacote .deb do yt2mp3.
#
#   ./build-deb.sh            # gera build/yt2mp3_<versao>_all.deb
#   ./build-deb.sh --clean    # limpa antes de montar
#
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$ROOT"

APP_ID="io.github.yt2mp3.Yt2Mp3"
PKG="yt2mp3"
ARCH="all"
VERSION="$(python3 -c 'import re,sys; print(re.search(r"VERSION = \"([^\"]+)\"", open("yt2mp3/__init__.py").read()).group(1))')"

BUILD="$ROOT/build"
STAGE="$BUILD/stage"
DEB="$BUILD/${PKG}_${VERSION}_${ARCH}.deb"
VENDOR_YTDLP="$ROOT/vendor/yt-dlp"

if [[ "${1:-}" == "--clean" ]]; then
    rm -rf "$BUILD"
fi

echo ">> yt2mp3 $VERSION — montando pacote .deb"

# ---------------------------------------------------------------- dependências
if [[ ! -x "$VENDOR_YTDLP" ]]; then
    echo ">> vendor/yt-dlp ausente; baixando a versão mais recente do yt-dlp"
    mkdir -p "$ROOT/vendor"
    curl -sSL --fail --max-time 180 \
        -o "$VENDOR_YTDLP" \
        "https://github.com/yt-dlp/yt-dlp/releases/latest/download/yt-dlp"
    chmod +x "$VENDOR_YTDLP"
fi

# ------------------------------------------------------------------- limpeza
rm -rf "$STAGE"
mkdir -p "$STAGE"

# --------------------------------------------------------------- instalação
install -d "$STAGE/usr/bin"
install -d "$STAGE/usr/lib/$PKG/$PKG"
install -d "$STAGE/usr/lib/$PKG/vendor"
install -d "$STAGE/usr/share/applications"
install -d "$STAGE/usr/share/metainfo"
install -d "$STAGE/usr/share/doc/$PKG"

install -Dm755 bin/yt2mp3 "$STAGE/usr/bin/$PKG"

for file in yt2mp3/*.py; do
    install -Dm644 "$file" "$STAGE/usr/lib/$PKG/$PKG/$(basename "$file")"
done

install -Dm755 "$VENDOR_YTDLP" "$STAGE/usr/lib/$PKG/vendor/yt-dlp"

install -Dm644 "data/$APP_ID.desktop" "$STAGE/usr/share/applications/$APP_ID.desktop"
install -Dm644 "data/$APP_ID.metainfo.xml" "$STAGE/usr/share/metainfo/$APP_ID.metainfo.xml"

echo ">> gerando ícones"
python3 scripts/render-icons.py "data/$APP_ID.svg" "$STAGE/usr/share/icons/hicolor" >/dev/null

# ------------------------------------------------------------------ copyright
cat > "$STAGE/usr/share/doc/$PKG/copyright" <<EOF
Format: https://www.debian.org/doc/packaging-manuals/copyright-format/1.0/
Upstream-Name: $PKG
Source: https://github.com/yt2mp3

Files: *
Copyright: 2026 Projeto yt2mp3
License: GPL-3.0-or-later
 This program is free software: you can redistribute it and/or modify it
 under the terms of the GNU General Public License as published by the Free
 Software Foundation, either version 3 of the License, or (at your option)
 any later version.
 .
 On Debian systems the full text of the GNU General Public License version 3
 can be found in /usr/share/common-licenses/GPL-3.

Files: usr/lib/$PKG/vendor/yt-dlp
Copyright: yt-dlp contributors
License: Unlicense
 The yt-dlp executable bundled here is distributed under the Unlicense.
 See https://github.com/yt-dlp/yt-dlp/blob/master/LICENSE for details.
EOF

# ---------------------------------------------------------------------- DEBIAN
mkdir -p "$STAGE/DEBIAN"

INSTALLED_SIZE="$(du -sk "$STAGE" | cut -f1)"
cat > "$STAGE/DEBIAN/control" <<EOF
Package: $PKG
Version: $VERSION
Architecture: $ARCH
Maintainer: Projeto yt2mp3 <yt2mp3@localhost>
Installed-Size: $INSTALLED_SIZE
Depends: python3 (>= 3.10), python3-gi, gir1.2-gtk-4.0 (>= 4.10), gir1.2-adw-1 (>= 1.4), ffmpeg, curl
Recommends: xdg-utils
Section: web
Priority: optional
Homepage: https://github.com/yt2mp3
Description: YouTube to MP3 - conversor de áudio para Ubuntu 26.04
 Converte links de vídeo em arquivos de áudio (MP3, M4A, Opus, FLAC, WAV).
 Suporta YouTube, Vimeo, SoundCloud e centenas de outros sites via yt-dlp.
 Baixa, converte com ffmpeg e grava tags e capa automaticamente.
 .
 Alternativa livre ao MediaHuman YouTube to MP3, sem Qt5 e sem TagLib 1.x,
 funcionando nativamente no Ubuntu 26.04.
EOF

cat > "$STAGE/DEBIAN/postinst" <<'EOF'
#!/bin/sh
set -e

if [ "$1" = "configure" ]; then
    if command -v gtk-update-icon-cache >/dev/null 2>&1; then
        gtk-update-icon-cache -q -t -f /usr/share/icons/hicolor || true
    fi
    if command -v update-desktop-database >/dev/null 2>&1; then
        update-desktop-database -q /usr/share/applications || true
    fi
fi

exit 0
EOF

cat > "$STAGE/DEBIAN/postrm" <<'EOF'
#!/bin/sh
set -e

if [ "$1" = "remove" ] || [ "$1" = "purge" ]; then
    if command -v gtk-update-icon-cache >/dev/null 2>&1; then
        gtk-update-icon-cache -q -t -f /usr/share/icons/hicolor || true
    fi
    if command -v update-desktop-database >/dev/null 2>&1; then
        update-desktop-database -q /usr/share/applications || true
    fi
fi

exit 0
EOF

chmod 755 "$STAGE/DEBIAN/postinst" "$STAGE/DEBIAN/postrm"

# ---------------------------------------------------------------------- build
mkdir -p "$BUILD"
dpkg-deb --root-owner-group --build "$STAGE" "$DEB" >/dev/null
rm -rf "$STAGE"

echo ">> pronto: $DEB"
ls -lh "$DEB" | awk '{print "   tamanho:", $5}'
