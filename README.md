# yt2mp3 — YouTube to MP3 para Ubuntu 26.04

Alternativa **livre e independente** ao MediaHuman YouTube to MP3 Converter,
construída para funcionar nativamente no **Ubuntu 26.04 (Resolute Raccoon)**.

Este projeto nasceu de uma investigação do pacote original
`YouTubeToMP3.amd64.deb` (versão 3.9.9.96). O que foi descoberto e por que o
original não instala está documentado abaixo; o aplicativo em si é uma
implementação nova, sobre `yt-dlp` e `ffmpeg`, sem qualquer código proprietário.

---

## 1. Por que o pacote original não instala

O `.deb` da MediaHuman depende de nove pacotes. A simulação do `apt` mostra que
**todos resolvem no 26.04, exceto um**:

```
youtube-to-mp3 : Depende: libtag1v5-vanilla (>= 1.11.1+dfsg.1-0.3)
                 but none of the choices are installable: [no choices]
```

O Ubuntu 26.04 **removeu o TagLib 1.x**. Hoje só existe `libtag2` (TagLib 2.x),
cujo SONAME é `libtag.so.2`. O binário da MediaHuman, porém, foi compilado
contra a ABI antiga:

```
$ readelf -d YouTubeToMP3 | grep NEEDED
  (NEEDED)  libtag.so.1                    ← não existe mais no 26.04
  (NEEDED)  libQt5WebEngineCore.so.5
  (NEEDED)  libQt5Quick.so.5
  ...
```

As mensagens "não será instalado" para os pacotes Qt5 eram apenas **cascata**
do erro acima — instalando só os Qt5 + ffmpeg, o `apt` resolve normalmente.

### Como o original funciona por dentro

Extraído do ELF (símbolos, strings e seções):

| Camada | Evidência no binário |
|---|---|
| GUI Qt5 (Widgets + QML/Quick) | `libQt5Widgets.so.5`, `libQt5Qml.so.5`, `libQt5Quick.so.5` |
| Navegador embutido (login e assinatura) | `libQt5WebEngineCore.so.5`, `libQt5WebEngineWidgets.so.5` |
| Extrator próprio do YouTube | `plugins/youtubesignature.cpp`, `YouTubeSignatureTask`, `itag=`, `googlevideo.com/.../expire/` |
| Downloader HTTP próprio | `network/maxConnections`, `network/safeDownloading`, `speedLimit/globalBps` |
| Conversão via **ffmpeg externo** | `FFMpegDetector`, `FFMpegWrapper`, `mediahuman_ffmpeg_fileserver_` |
| Tags ID3 via TagLib | `libtag.so.1` |
| Enriquecimento de metadados | MusicBrainz, Discogs, Genius, Last.fm, iTunes |
| Licenciamento trial/pago (RSA) | `rsalib/rsaside.cpp`, `mediahuman.com/keycheck` |

O ponto frágil é o extrator próprio: ele reimplementa a lógica do YouTube e
quebra a cada mudança do site. Este projeto delega isso ao `yt-dlp`, que é
mantido ativamente.

---

## 2. Como o clone funciona

Mapeamento direto com o original:

| MediaHuman | yt2mp3 |
|---|---|
| extrator próprio do YouTube | **yt-dlp** (vendorizado, atualizado) |
| downloader HTTP multi-conexão | `yt-dlp --concurrent-fragments` |
| `FFMpegWrapper` / `cnvrt.cpp` | **ffmpeg** chamado pelo próprio app |
| TagLib (`libtag.so.1`) | ffmpeg (ID3v2.3 / átomos M4A) |
| Qt5 + QtWebEngine | **GTK4 + libadwaita** |
| trial com limite de músicas | livre (GPL-3.0) |

Fluxo de cada item da fila:

```
sondagem (--flat-playlist)
   ├─ vídeo único  ──────────────┐
   └─ playlist → 1 job por faixa ┘
                                 ▼
        download do áudio bruto (yt-dlp, sem pós-processamento)
                                 ▼
        conversão + tags + capa (ffmpeg, bitrate exato)
                                 ▼
        arquivo final em <pasta>/[<playlist>/][NN - ]<título>.<formato>
```

### Recursos

- YouTube, Vimeo, SoundCloud e centenas de sites (via yt-dlp)
- Formatos: **MP3, M4A (AAC), Opus, FLAC, WAV**
- Bitrate: 96 / 128 / 192 / 256 / 320 kbps (**CBR exato**)
- Playlists: viram fila, com **subpasta** e **numeração** opcionais
- Tags: título, artista, álbum, data e comentário (URL de origem)
- Capa do vídeo embutida
- Downloads simultâneos e limite de velocidade
- Colar da área de transferência, arrastar arquivo `.txt` com links
- Suporte a `yt2mp3:` como esquema de URL (compatível com o pacote original)

---

## 3. Instalação

```bash
sudo apt install ./build/yt2mp3_1.0.0_all.deb
```

O `apt` resolve as dependências automaticamente. Ele puxa apenas:

```
python3, python3-gi, gir1.2-gtk-4.0, gir1.2-adw-1, ffmpeg, curl
```

O `yt-dlp` já vem embutido no pacote (~3 MB), então não há dependência de
versão do repositório. Depois de instalar, o app aparece no menu como
**YouTube to MP3** ou pode ser aberto pelo terminal:

```bash
yt2mp3
yt2mp3 "https://youtu.be/VIDEO"
```

---

## 4. Desenvolvimento

Requisitos: Python 3.10+, PyGObject, GTK 4.10+, libadwaita 1.4+, ffmpeg.

```bash
# rodar direto do checkout
./bin/yt2mp3

# ou
python3 -m yt2mp3

# baixar o yt-dlp vendorizado se ainda não existir
mkdir -p vendor
curl -sSL -o vendor/yt-dlp \
  https://github.com/yt-dlp/yt-dlp/releases/latest/download/yt-dlp
chmod +x vendor/yt-dlp
```

Para apontar motores alternativos (útil em testes):

```bash
YT2MP3_VENDOR_DIR=/caminho/com/ytdlp-e-ffmpeg ./bin/yt2mp3
```

### Estrutura

```
yt2mp3/
├── application.py    # Adw.Application, ações, despacho thread→UI
├── window.py         # janela principal, fila e linhas de job
├── preferences.py    # diálogo de preferências
├── backend.py        # motor: sondagem, download, ffmpeg, tags
├── tools.py          # localização de yt-dlp e ffmpeg
├── urls.py           # validação e extração de links
├── config.py         # Settings em ~/.config/yt2mp3/settings.json
└── formatting.py     # bytes, velocidade e ETA
bin/yt2mp3            # launcher (funciona no checkout e instalado)
data/                 # .desktop, metainfo AppStream e ícone SVG
scripts/render-icons.py
build-deb.sh
```

Configurações ficam em `~/.config/yt2mp3/settings.json` e espelham as chaves do
original (`output/format`, `output/bitrate`, `outputFolder`,
`network/maxConnections`, `speedLimit/globalBps`,
`addIndexInPlaylistToFilename`).

---

## 5. Empacotamento

```bash
./build-deb.sh          # gera build/yt2mp3_1.0.0_all.deb
./build-deb.sh --clean  # limpa antes
```

O script baixa o `yt-dlp` mais recente se `vendor/yt-dlp` não existir, gera os
ícones PNG a partir do SVG e monta o `.deb` com `dpkg-deb --root-owner-group`
(sem precisar de `fakeroot`).

---

## 6. Nota legal

Este projeto **não contém, não redistribui e não modifica** o binário da
MediaHuman, nem contorna sua checagem de licença. É uma implementação
independente com funcionalidade equivalente.

O `yt-dlp` embutido é distribuído sob a **Unlicense**. Respeite os termos de
serviço dos sites e as leis de direito autoral ao baixar conteúdo.

Licença deste projeto: **GPL-3.0-or-later**.
