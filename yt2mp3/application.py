"""Aplicação GTK4 do yt2mp3."""

from __future__ import annotations

import sys
from pathlib import Path

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")

from gi.repository import Adw, Gdk, Gio, GLib, Gtk  # noqa: E402

from . import APP_ID, APP_TITLE, VERSION  # noqa: E402
from .backend import Engine, Job  # noqa: E402
from .config import Settings  # noqa: E402
from .preferences import PreferencesDialog  # noqa: E402
from .urls import is_supported, split_entries  # noqa: E402
from .window import MainWindow  # noqa: E402

_CSS = b"""
.job-row.error label.body { color: @error_color; }
.job-row { transition: background-color 150ms ease-in-out; }
"""


class Application(Adw.Application):
    def __init__(self) -> None:
        super().__init__(
            application_id=APP_ID,
            flags=Gio.ApplicationFlags.HANDLES_OPEN,
        )
        self.settings = Settings.load()
        self.engine = Engine(
            self.settings,
            on_job_changed=self._dispatch_job,
            on_tools_changed=self._dispatch_tools,
            on_queue_changed=self._dispatch_queue,
        )
        self.window: MainWindow | None = None
        self._pending_urls: list[str] = []

    # ------------------------------------------------------------ ciclo de vida
    def do_startup(self) -> None:
        Adw.Application.do_startup(self)
        Gtk.Window.set_default_icon_name(APP_ID)
        self._install_actions()
        self._install_css()
        self.engine.refresh_tools()

    def do_activate(self) -> None:
        if self.window is None:
            self.window = MainWindow(self, self.engine, self.settings)
        self.window.present()
        if self._pending_urls:
            urls, self._pending_urls = self._pending_urls, []
            self.engine.add(urls)

    def do_open(self, files, n_files: int, hint: str) -> None:
        urls: list[str] = []
        for gfile in files:
            uri = gfile.get_uri() or ""
            if uri.startswith("yt2mp3:"):
                inner = uri[len("yt2mp3:"):]
                if is_supported(inner):
                    urls.append(inner)
                continue
            if uri.startswith(("http://", "https://")):
                if is_supported(uri):
                    urls.append(uri)
                continue
            path = gfile.get_path()
            if path and Path(path).is_file():
                try:
                    text = Path(path).read_text(encoding="utf-8", errors="replace")
                except OSError:
                    continue
                urls.extend(u for u in split_entries(text) if is_supported(u))
        if urls:
            if self.window is None:
                self._pending_urls.extend(urls)
            else:
                self.engine.add(urls)
            self.activate()

    # ----------------------------------------------------------- thread -> UI
    def _dispatch_job(self, job: Job) -> None:
        GLib.idle_add(self._apply_job, job)

    def _dispatch_tools(self) -> None:
        GLib.idle_add(self._apply_tools)

    def _dispatch_queue(self) -> None:
        GLib.idle_add(self._apply_queue)

    def _apply_job(self, job: Job) -> bool:
        if self.window is not None:
            self.window.on_job_changed(job)
        return False

    def _apply_tools(self) -> bool:
        if self.window is not None:
            self.window.on_tools_changed()
        return False

    def _apply_queue(self) -> bool:
        if self.window is not None:
            self.window.on_queue_changed()
        return False

    # ---------------------------------------------------------------- ações
    def _install_actions(self) -> None:
        preferences = Gio.SimpleAction.new("preferences", None)
        preferences.connect("activate", self._on_preferences)
        self.add_action(preferences)

        about = Gio.SimpleAction.new("about", None)
        about.connect("activate", self._on_about)
        self.add_action(about)

        quit_action = Gio.SimpleAction.new("quit", None)
        quit_action.connect("activate", lambda *_: self.quit())
        self.add_action(quit_action)

        self.set_accels_for_action("app.preferences", ["<Primary>comma"])
        self.set_accels_for_action("app.quit", ["<Primary>q"])

    def _on_preferences(self, *_args) -> None:
        if self.window is None:
            return
        dialog = PreferencesDialog(self.window, self.engine, self.settings)
        dialog.present(self.window)

    def _on_about(self, *_args) -> None:
        about = Adw.AboutDialog()
        about.set_application_name(APP_TITLE)
        about.set_application_icon(APP_ID)
        about.set_developer_name("Projeto yt2mp3")
        about.set_version(VERSION)
        about.set_license_type(Gtk.License.GPL_3_0)
        about.set_comments(
            "Converte links de vídeo em arquivos de áudio. "
            "Alternativa livre ao MediaHuman YouTube to MP3, construída sobre "
            "yt-dlp e ffmpeg."
        )
        about.set_website("https://github.com/")
        about.present(self.window)

    def _install_css(self) -> None:
        provider = Gtk.CssProvider()
        provider.load_from_data(_CSS)
        display = Gdk.Display.get_default()
        if display is not None:
            Gtk.StyleContext.add_provider_for_display(
                display,
                provider,
                Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION,
            )


def main(argv: list[str] | None = None) -> int:
    app = Application()
    return app.run(argv if argv is not None else sys.argv)
