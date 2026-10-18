"""Motor de download e conversão do yt2mp3.

Arquitetura equivalente ao app original da MediaHuman:

  MediaHuman                          yt2mp3
  ----------------------------------  -----------------------------------------
  extrator próprio do YouTube    ->   yt-dlp (mantido, cobre 1000+ sites)
  downloader HTTP multi-conexão  ->   yt-dlp (--concurrent-fragments)
  cnvrt.cpp / FFMpegWrapper      ->   ffmpeg (chamado por nós, igual ao original)
  TagLib (libtag.so.1)           ->   ffmpeg (escreve ID3 / átomos M4A)

Cada Job passa por: sondagem -> download do áudio bruto -> conversão -> tags.
Playlists são expandidas em uma faixa por linha da fila, como no original.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import tempfile
import threading
import unicodedata
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from pathlib import Path

from .config import LOSSLESS_FORMATS, Settings
from .tools import ToolStatus, find_ffmpeg, find_ytdlp, ytdlp_ffmpeg_location

# Estados possíveis de um Job.
QUEUED = "queued"
PROBING = "probing"
DOWNLOADING = "downloading"
CONVERTING = "converting"
DONE = "done"
ERROR = "error"
CANCELLED = "cancelled"

ACTIVE_STATES = {PROBING, DOWNLOADING, CONVERTING}
FINISHED_STATES = {DONE, ERROR, CANCELLED}

# Limite de faixas ao expandir uma playlist (evita expandir listas gigantes).
MAX_PLAYLIST_ENTRIES = 500

_PROGRESS_PREFIX = "PROG|"
_PROGRESS_TEMPLATE = _PROGRESS_PREFIX + "|".join(
    [
        "%(progress.status)s",
        "%(progress.downloaded_bytes)s",
        "%(progress.total_bytes)s",
        "%(progress.total_bytes_estimate)s",
        "%(progress.speed)s",
        "%(progress.eta)s",
    ]
)

_META_FIELDS = (
    "id,title,artist,album,track,uploader,channel,upload_date,"
    "thumbnail,playlist_title,playlist_index,ext,filepath,webpage_url,"
    "duration,duration_string"
)
_META_TEMPLATE = "after_move:%(.{" + _META_FIELDS + "})j"
_PROBE_TEMPLATE = "%(.{id,title,url,playlist_title,playlist_index})j"

# Formatos que aceitam capa embutida com segurança.
_FORMATS_WITH_COVER = {"mp3", "m4a", "flac"}

# Caracteres proibidos em nomes de arquivo.
_UNSAFE_RE = re.compile(r'[<>:"/\\|?*\x00-\x1f]')
_SPACES_RE = re.compile(r"\s+")


def sanitize_filename(name: str, max_length: int = 180) -> str:
    """Limpa um nome vindo do título do vídeo para uso como nome de arquivo."""
    name = unicodedata.normalize("NFC", name or "")
    name = _UNSAFE_RE.sub("_", name)
    name = _SPACES_RE.sub(" ", name).strip().strip(".")
    if len(name) > max_length:
        name = name[:max_length].rstrip()
    return name or "audio"


def _unique_path(path: Path) -> Path:
    """Evita sobrescrever: titulo.mp3, titulo (2).mp3, ..."""
    if not path.exists():
        return path
    stem, suffix, parent = path.stem, path.suffix, path.parent
    for index in range(2, 1000):
        candidate = parent / f"{stem} ({index}){suffix}"
        if not candidate.exists():
            return candidate
    return path


def _to_int(value) -> int:
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return 0


def _to_float(value) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


@dataclass
class Job:
    job_id: int
    url: str
    title: str = ""
    state: str = QUEUED
    percent: float = 0.0
    downloaded: int = 0
    total: int = 0
    speed: float = 0.0
    eta: int = 0
    filepath: str = ""
    error: str = ""
    playlist_title: str = ""
    playlist_index: int = 0
    duration: int = 0
    # Campos internos (não exibidos).
    meta: dict = field(default_factory=dict)
    temp_dir: str = ""
    _proc: subprocess.Popen | None = field(default=None, repr=False)
    _cancel: threading.Event = field(default_factory=threading.Event, repr=False)

    @property
    def is_active(self) -> bool:
        return self.state in ACTIVE_STATES

    @property
    def is_finished(self) -> bool:
        return self.state in FINISHED_STATES

    @property
    def display_title(self) -> str:
        if self.title:
            return self.title
        if self.state == PROBING:
            return "Analisando link…"
        return self.url


class Engine:
    """Gerencia a fila de Jobs e o pool de workers.

    Não depende de GTK: as notificações são callbacks simples, e a camada de
    interface se encarrega de agendá-las na thread principal.
    """

    def __init__(
        self,
        settings: Settings,
        on_job_changed=None,
        on_tools_changed=None,
        on_queue_changed=None,
    ) -> None:
        self.settings = settings
        self.on_job_changed = on_job_changed or (lambda job: None)
        self.on_tools_changed = on_tools_changed or (lambda: None)
        self.on_queue_changed = on_queue_changed or (lambda: None)

        self.jobs: list[Job] = []
        self.ytdlp: ToolStatus = ToolStatus(None, None)
        self.ffmpeg: ToolStatus = ToolStatus(None, None)

        self._lock = threading.RLock()
        self._counter = 0
        self._executor: ThreadPoolExecutor | None = None
        self._executor_workers = 0
        self._futures: dict[int, object] = {}

    # ------------------------------------------------------------------ tools
    def refresh_tools(self) -> None:
        self.ytdlp = find_ytdlp(self.settings.ytdlp_path)
        self.ffmpeg = find_ffmpeg(self.settings.ffmpeg_path)
        self.on_tools_changed()

    @property
    def tools_ready(self) -> bool:
        return self.ytdlp.available and self.ffmpeg.available

    def tool_problems(self) -> list[str]:
        problems = []
        if not self.ytdlp.available:
            problems.append(
                "O extrator (yt-dlp) não foi encontrado. Instale o pacote 'yt-dlp'."
            )
        if not self.ffmpeg.available:
            problems.append(
                "O ffmpeg (com ffprobe) não foi encontrado. Instale o pacote 'ffmpeg'."
            )
        return problems

    # ------------------------------------------------------------------ queue
    def add(self, urls: list[str]) -> list[Job]:
        created = []
        with self._lock:
            for url in urls:
                url = url.strip()
                if not url:
                    continue
                if any(j.url == url and not j.is_finished for j in self.jobs):
                    continue  # já está na fila
                self._counter += 1
                job = Job(job_id=self._counter, url=url)
                self.jobs.append(job)
                created.append(job)
                self._submit(job)
        if created:
            self.on_queue_changed()
        return created

    def _submit(self, job: Job) -> None:
        executor = self._ensure_executor()
        self._futures[job.job_id] = executor.submit(self._run_job, job)

    def _ensure_executor(self) -> ThreadPoolExecutor:
        workers = max(1, int(self.settings.max_parallel or 1))
        if self._executor is None or workers != self._executor_workers:
            old = self._executor
            self._executor = ThreadPoolExecutor(
                max_workers=workers, thread_name_prefix="yt2mp3"
            )
            self._executor_workers = workers
            if old is not None:
                old.shutdown(wait=False, cancel_futures=False)
        return self._executor

    def cancel(self, job_id: int) -> None:
        with self._lock:
            job = self._find(job_id)
            if job is None or job.is_finished:
                return
            job._cancel.set()
            proc = job._proc
        if proc is not None and proc.poll() is None:
            try:
                proc.terminate()
            except OSError:
                pass
        if job.state == QUEUED:
            self._set_state(job, CANCELLED)

    def cancel_all(self) -> None:
        for job in list(self.jobs):
            if not job.is_finished:
                self.cancel(job.job_id)

    def remove(self, job_id: int) -> None:
        with self._lock:
            job = self._find(job_id)
            if job is None:
                return
            if job.is_active:
                return  # não remove em execução
            self.jobs = [j for j in self.jobs if j.job_id != job_id]
            self._cleanup_temp(job)
        self.on_queue_changed()

    def clear_finished(self) -> None:
        with self._lock:
            keep = [j for j in self.jobs if not j.is_finished]
            removed = [j for j in self.jobs if j.is_finished]
            self.jobs = keep
        for job in removed:
            self._cleanup_temp(job)
        if removed:
            self.on_queue_changed()

    def _find(self, job_id: int) -> Job | None:
        for job in self.jobs:
            if job.job_id == job_id:
                return job
        return None

    def _set_state(self, job: Job, state: str, error: str = "") -> None:
        job.state = state
        if error:
            job.error = error
        self.on_job_changed(job)

    def _notify(self, job: Job) -> None:
        self.on_job_changed(job)

    # ------------------------------------------------------------- job worker
    def _run_job(self, job: Job) -> None:
        try:
            if job._cancel.is_set():
                self._set_state(job, CANCELLED)
                return
            if not self.tools_ready:
                self._set_state(job, ERROR, "; ".join(self.tool_problems()))
                return

            self._set_state(job, PROBING)
            entries = self._probe(job)

            if job._cancel.is_set():
                self._set_state(job, CANCELLED)
                return

            if len(entries) > 1:
                self._expand_playlist(job, entries)
                return

            if entries and not job.title:
                job.title = entries[0].get("title") or ""
                self._notify(job)

            self._download_and_convert(job)
        except RuntimeError as exc:
            self._set_state(job, ERROR, str(exc))
        except Exception as exc:  # nunca deixar o worker morrer em silêncio
            self._set_state(job, ERROR, f"Falha inesperada: {exc}")
        finally:
            self._cleanup_temp(job)

    # ------------------------------------------------------- playlist expand
    def _probe(self, job: Job) -> list[dict]:
        """Sonda o link. Retorna [] para vídeo único e a lista de faixas para playlist."""
        cmd = [
            str(self.ytdlp.path),
            "--ignore-config",
            "--flat-playlist",
            "--no-warnings",
            "--socket-timeout", "30",
            "--playlist-end", str(MAX_PLAYLIST_ENTRIES),
            "--print", _PROBE_TEMPLATE,
            "--", job.url,
        ]
        try:
            proc = subprocess.run(cmd, capture_output=True, text=True, timeout=180)
        except subprocess.TimeoutExpired:
            raise RuntimeError(
                "O site demorou demais para responder ao analisar o link."
            ) from None
        except OSError as exc:
            raise RuntimeError(f"Não foi possível executar o yt-dlp: {exc}") from None
        if proc.returncode != 0:
            detail = self._last_error(proc.stderr) if proc.stderr else ""
            if not detail:
                lines = (proc.stderr or "").strip().splitlines()
                detail = lines[-1] if lines else "Falha ao analisar o link"
            raise RuntimeError(detail)

        entries: list[dict] = []
        for line in proc.stdout.splitlines():
            line = line.strip()
            if not line.startswith("{"):
                continue
            try:
                entries.append(json.loads(line))
            except ValueError:
                continue
        return entries

    def _expand_playlist(self, job: Job, entries: list[dict]) -> None:
        playlist_title = next(
            (e.get("playlist_title") for e in entries if e.get("playlist_title")), ""
        )
        children: list[Job] = []
        with self._lock:
            for entry in entries:
                url = entry.get("url") or entry.get("webpage_url")
                if not url:
                    continue
                self._counter += 1
                child = Job(
                    job_id=self._counter,
                    url=url,
                    title=entry.get("title") or "",
                    playlist_title=playlist_title,
                    playlist_index=_to_int(entry.get("playlist_index")),
                )
                self.jobs.append(child)
                children.append(child)
            # O job "pai" era só o invólucro da playlist.
            self.jobs = [j for j in self.jobs if j.job_id != job.job_id]
            job.state = DONE
            job.percent = 100.0
            job.error = ""
        self.on_queue_changed()
        for child in children:
            self._submit(child)

    # --------------------------------------------------- download + convert
    def _download_and_convert(self, job: Job) -> None:
        temp_dir = Path(tempfile.mkdtemp(prefix="yt2mp3-"))
        job.temp_dir = str(temp_dir)
        meta_file = temp_dir / "meta.json"
        raw_template = str(temp_dir / "raw.%(ext)s")

        self._set_state(job, DOWNLOADING)
        cmd = [
            str(self.ytdlp.path),
            "--ignore-config",
            "--no-warnings",
            "--newline",
            "--no-color",
            "--no-simulate",
            "--no-part",
            "--concurrent-fragments", "4",
            "--retries", "5",
            "--socket-timeout", "30",
            "--progress",
            f"--progress-template={_PROGRESS_TEMPLATE}",
            "--print-to-file", _META_TEMPLATE, str(meta_file),
            "-f", "bestaudio/best",
            "-o", raw_template,
        ]
        limit = int(self.settings.speed_limit_kib or 0)
        if limit > 0:
            cmd += ["--limit-rate", f"{limit}K"]
        ffmpeg_location = ytdlp_ffmpeg_location(self.ffmpeg)
        if ffmpeg_location:
            cmd += ["--ffmpeg-location", ffmpeg_location]
        cmd += ["--", job.url]

        code, output = self._spawn(
            job, cmd, on_line=lambda line: self._parse_progress(job, line)
        )
        if job._cancel.is_set():
            self._set_state(job, CANCELLED)
            return

        records = self._read_meta(meta_file)
        if not records:
            detail = self._last_error(output)
            if code != 0 or detail:
                self._set_state(job, ERROR, detail or "Falha no download do áudio.")
            else:
                self._set_state(
                    job, ERROR, "O download não produziu metadados do áudio."
                )
            return

        first = records[0]
        if first.get("title"):
            job.title = first["title"]
        job.playlist_title = first.get("playlist_title") or job.playlist_title
        job.playlist_index = _to_int(first.get("playlist_index")) or job.playlist_index
        job.duration = _to_int(first.get("duration"))
        self._notify(job)

        self._set_state(job, CONVERTING)
        outputs: list[str] = []
        for record in records:
            if job._cancel.is_set():
                self._set_state(job, CANCELLED)
                return
            output = self._convert(job, record)
            if output is None:
                return  # erro já registrado
            outputs.append(str(output))

        job.filepath = outputs[0] if outputs else ""
        job.percent = 100.0
        if len(outputs) > 1:
            job.title = f"{job.title or job.url} ({len(outputs)} faixas)"
        job.error = ""
        self._set_state(job, DONE)

    # ------------------------------------------------------------------ ffmpeg
    def _convert(self, job: Job, record: dict) -> Path | None:
        raw = Path(record.get("filepath") or "")
        if not raw.is_file():
            self._set_state(job, ERROR, "Arquivo de áudio bruto não encontrado.")
            return None

        target_dir = self._target_dir(job, record)
        target_dir.mkdir(parents=True, exist_ok=True)
        fmt = self.settings.audio_format
        name = self._target_name(job, record)
        out_path = _unique_path(target_dir / f"{name}.{fmt}")

        cover: Path | None = None
        if self.settings.embed_thumbnail and fmt in _FORMATS_WITH_COVER:
            cover = self._fetch_cover(record.get("thumbnail"), job.temp_dir)

        attempts = [True, False] if cover is not None else [False]
        last_error = ""
        for use_cover in attempts:
            if job._cancel.is_set():
                self._set_state(job, CANCELLED)
                return None
            cmd = self._ffmpeg_cmd(raw, out_path, record, cover if use_cover else None)
            code, output = self._spawn(job, cmd)
            if job._cancel.is_set():
                try:
                    out_path.unlink(missing_ok=True)
                except OSError:
                    pass
                self._set_state(job, CANCELLED)
                return None
            if code == 0 and out_path.is_file():
                # Remove o arquivo bruto para liberar espaço.
                try:
                    raw.unlink()
                except OSError:
                    pass
                job.filepath = str(out_path)
                return out_path
            last_error = output.strip().splitlines()[-1] if output.strip() else ""
            try:
                out_path.unlink(missing_ok=True)
            except OSError:
                pass

        self._set_state(job, ERROR, f"ffmpeg falhou ao converter: {last_error}")
        return None

    def _ffmpeg_cmd(
        self, raw: Path, out_path: Path, record: dict, cover: Path | None
    ) -> list[str]:
        fmt = self.settings.audio_format
        bitrate = str(self.settings.bitrate)
        cmd = [
            str(self.ffmpeg.path),
            "-y",
            "-loglevel", "error",
            "-i", str(raw),
        ]
        if cover is not None:
            cmd += ["-i", str(cover)]

        cmd += ["-map", "0:a:0"]
        if cover is not None:
            cmd += ["-map", "1:v:0", "-c:v", "mjpeg", "-disposition:v", "attached_pic"]

        if fmt == "mp3":
            cmd += ["-c:a", "libmp3lame", "-b:a", f"{bitrate}k"]
        elif fmt == "m4a":
            cmd += ["-c:a", "aac", "-b:a", f"{bitrate}k", "-movflags", "+faststart"]
        elif fmt == "opus":
            cmd += ["-c:a", "libopus", "-b:a", f"{bitrate}k"]
        elif fmt == "flac":
            cmd += ["-c:a", "flac"]
        elif fmt == "wav":
            cmd += ["-c:a", "pcm_s16le"]
        else:
            cmd += ["-c:a", "libmp3lame", "-b:a", f"{bitrate}k"]

        # Descarta metadados do container de origem antes de gravar os nossos.
        cmd += ["-map_metadata", "-1"]

        if self.settings.add_metadata:
            title = record.get("title") or out_path.stem
            artist = (
                record.get("artist")
                or record.get("uploader")
                or record.get("channel")
                or ""
            )
            album = record.get("album") or record.get("playlist_title") or ""
            cmd += ["-metadata", f"title={title}"]
            if artist:
                cmd += ["-metadata", f"artist={artist}"]
            if album:
                cmd += ["-metadata", f"album={album}"]
            date = str(record.get("upload_date") or "")
            if len(date) >= 4:
                cmd += ["-metadata", f"date={date[:4]}"]
            if record.get("playlist_index"):
                cmd += ["-metadata", f"track={record['playlist_index']}"]
            if record.get("webpage_url"):
                cmd += ["-metadata", f"comment={record['webpage_url']}"]

        if cover is not None:
            cmd += [
                "-metadata:s:v", "title=Album cover",
                "-metadata:s:v", "comment=Cover (front)",
            ]
        if fmt == "mp3":
            cmd += ["-id3v2_version", "3"]
        cmd += [str(out_path)]
        return cmd

    def _fetch_cover(self, url: str | None, temp_dir: str) -> Path | None:
        if not url:
            return None
        cover = Path(temp_dir) / "cover"
        cmd = [
            "curl", "-sSL", "--max-time", "60", "--fail", "-o", str(cover), url,
        ]
        try:
            proc = subprocess.run(cmd, capture_output=True, text=True, timeout=90)
        except (OSError, subprocess.SubprocessError):
            return None
        return cover if proc.returncode == 0 and cover.is_file() else None

    # -------------------------------------------------------------- helpers
    def _target_dir(self, job: Job, record: dict) -> Path:
        base = self.settings.resolved_output_dir()
        playlist = job.playlist_title or record.get("playlist_title") or ""
        if self.settings.playlist_subfolder and playlist:
            base = base / sanitize_filename(playlist, 120)
        return base

    def _target_name(self, job: Job, record: dict) -> str:
        title = record.get("title") or job.title or record.get("id") or "audio"
        name = sanitize_filename(title)
        index = job.playlist_index or _to_int(record.get("playlist_index"))
        if self.settings.index_in_filename and index:
            name = f"{int(index):02d} - {name}"
        return name

    @staticmethod
    def _last_error(output: str) -> str:
        """Extrai a mensagem de erro mais relevante da saída do yt-dlp/ffmpeg."""
        lines = [ln.strip() for ln in (output or "").splitlines() if ln.strip()]
        for line in reversed(lines):
            if line.startswith("ERROR:"):
                return line[len("ERROR:"):].strip()
        return ""

    def _read_meta(self, meta_file: Path) -> list[dict]:
        if not meta_file.is_file():
            return []
        records = []
        for line in meta_file.read_text(encoding="utf-8", errors="replace").splitlines():
            line = line.strip()
            if not line.startswith("{"):
                continue
            try:
                records.append(json.loads(line))
            except ValueError:
                continue
        return records

    def _parse_progress(self, job: Job, line: str) -> None:
        if not line.startswith(_PROGRESS_PREFIX):
            return
        parts = line[len(_PROGRESS_PREFIX):].split("|")
        if len(parts) < 6:
            return
        status, downloaded, total, total_est, speed, eta = parts[:6]
        job.downloaded = _to_int(downloaded)
        job.total = _to_int(total) or _to_int(total_est)
        job.speed = _to_float(speed)
        job.eta = _to_int(eta)
        if job.total > 0:
            job.percent = min(100.0, job.downloaded * 100.0 / job.total)
        elif status == "finished":
            job.percent = 100.0
        if status == "finished":
            job.percent = 100.0
        self._notify(job)

    def _spawn(self, job: Job, cmd: list[str], on_line=None) -> tuple[int, str]:
        """Executa um subprocesso acompanhando stdout linha a linha."""
        proc = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
        )
        job._proc = proc
        captured: list[str] = []
        try:
            assert proc.stdout is not None
            for line in proc.stdout:
                line = line.rstrip("\n")
                captured.append(line)
                if on_line is not None:
                    on_line(line)
                if job._cancel.is_set() and proc.poll() is None:
                    proc.terminate()
            proc.wait(timeout=60)
        except subprocess.TimeoutExpired:
            proc.kill()
        finally:
            job._proc = None
        output = "\n".join(captured)
        if proc.returncode == 0 and "ERROR:" in output:
            return 1, output
        return proc.returncode or 0, output

    def _cleanup_temp(self, job: Job) -> None:
        if job.temp_dir:
            shutil.rmtree(job.temp_dir, ignore_errors=True)
            job.temp_dir = ""
