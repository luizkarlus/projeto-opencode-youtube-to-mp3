"""Diálogo de preferências do yt2mp3."""

from __future__ import annotations

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")

from gi.repository import Adw, Gio, GLib, Gtk  # noqa: E402

from .backend import Engine  # noqa: E402
from .config import Settings  # noqa: E402


class PreferencesDialog(Adw.PreferencesDialog):
    def __init__(self, parent: Gtk.Window, engine: Engine, settings: Settings):
        super().__init__()
        self.set_title("Preferências")
        self._parent = parent
        self._engine = engine
        self._settings = settings

        self.add(self._build_output_page())
        self.add(self._build_performance_page())
        self.add(self._build_tools_page())

    # ----------------------------------------------------------------- saída
    def _build_output_page(self) -> Adw.PreferencesPage:
        page = Adw.PreferencesPage()
        page.set_title("Saída")
        page.set_icon_name("folder-symbolic")

        folder_group = Adw.PreferencesGroup()
        folder_group.set_title("Pasta de saída")
        self._folder_row = Adw.ActionRow()
        self._folder_row.set_title("Salvar arquivos em")
        self._folder_row.set_subtitle(str(self._settings.resolved_output_dir()))
        choose = Gtk.Button(label="Alterar…")
        choose.add_css_class("flat")
        choose.set_valign(Gtk.Align.CENTER)
        choose.connect("clicked", self._on_choose_folder)
        self._folder_row.add_suffix(choose)
        folder_group.add(self._folder_row)
        page.add(folder_group)

        org_group = Adw.PreferencesGroup()
        org_group.set_title("Organização")
        self._playlist_folder = Adw.SwitchRow()
        self._playlist_folder.set_title("Criar subpasta por playlist")
        self._playlist_folder.set_subtitle(
            "Os arquivos de uma playlist vão para uma pasta com o nome dela."
        )
        self._playlist_folder.set_active(self._settings.playlist_subfolder)
        self._playlist_folder.connect("notify::active", self._on_playlist_folder)
        org_group.add(self._playlist_folder)

        self._index_row = Adw.SwitchRow()
        self._index_row.set_title("Numerar faixas no nome do arquivo")
        self._index_row.set_subtitle("Ex.: 01 - Nome da música.mp3")
        self._index_row.set_active(self._settings.index_in_filename)
        self._index_row.connect("notify::active", self._on_index_in_filename)
        org_group.add(self._index_row)
        page.add(org_group)

        meta_group = Adw.PreferencesGroup()
        meta_group.set_title("Metadados")
        self._cover_row = Adw.SwitchRow()
        self._cover_row.set_title("Embutir capa do vídeo")
        self._cover_row.set_active(self._settings.embed_thumbnail)
        self._cover_row.connect("notify::active", self._on_cover)
        meta_group.add(self._cover_row)

        self._tags_row = Adw.SwitchRow()
        self._tags_row.set_title("Gravar tags (título, artista, álbum, data)")
        self._tags_row.set_active(self._settings.add_metadata)
        self._tags_row.connect("notify::active", self._on_tags)
        meta_group.add(self._tags_row)
        page.add(meta_group)

        return page

    # ------------------------------------------------------------ desempenho
    def _build_performance_page(self) -> Adw.PreferencesPage:
        page = Adw.PreferencesPage()
        page.set_title("Desempenho")
        page.set_icon_name("power-profile-performance-symbolic")

        group = Adw.PreferencesGroup()
        group.set_title("Rede")

        parallel = Adw.SpinRow.new_with_range(1, 8, 1)
        parallel.set_title("Downloads simultâneos")
        parallel.set_subtitle("Quantos itens da fila são baixados ao mesmo tempo.")
        parallel.set_value(int(self._settings.max_parallel))
        parallel.connect("notify::value", self._on_parallel)
        group.add(parallel)

        limit = Adw.SpinRow.new_with_range(0, 100000, 100)
        limit.set_title("Limite de velocidade (KiB/s)")
        limit.set_subtitle("0 significa sem limite.")
        limit.set_value(int(self._settings.speed_limit_kib))
        limit.connect("notify::value", self._on_speed_limit)
        group.add(limit)

        page.add(group)
        return page

    # ---------------------------------------------------------------- motores
    def _build_tools_page(self) -> Adw.PreferencesPage:
        page = Adw.PreferencesPage()
        page.set_title("Motores")
        page.set_icon_name("application-x-executable-symbolic")

        group = Adw.PreferencesGroup()
        group.set_title("Binários utilizados")
        group.set_description(
            "O yt-dlp faz a extração e o ffmpeg converte e grava as tags."
        )

        self._ytdlp_row = Adw.ActionRow()
        self._ytdlp_row.set_title("yt-dlp")
        self._ytdlp_icon = Gtk.Image()
        self._ytdlp_row.add_prefix(self._ytdlp_icon)
        group.add(self._ytdlp_row)

        self._ffmpeg_row = Adw.ActionRow()
        self._ffmpeg_row.set_title("ffmpeg")
        self._ffmpeg_icon = Gtk.Image()
        self._ffmpeg_row.add_prefix(self._ffmpeg_icon)
        group.add(self._ffmpeg_row)

        verify = Gtk.Button(label="Verificar novamente")
        verify.add_css_class("flat")
        verify.set_halign(Gtk.Align.START)
        verify.connect("clicked", self._on_verify_tools)
        group.add(verify)

        page.add(group)
        self._refresh_tool_rows()
        return page

    def _refresh_tool_rows(self) -> None:
        ytdlp = self._engine.ytdlp
        ffmpeg = self._engine.ffmpeg
        self._ytdlp_row.set_subtitle(ytdlp.label)
        self._ffmpeg_row.set_subtitle(ffmpeg.label)
        for icon, status in (
            (self._ytdlp_icon, ytdlp),
            (self._ffmpeg_icon, ffmpeg),
        ):
            icon.set_from_icon_name(
                "emblem-ok-symbolic" if status.available else "dialog-warning-symbolic"
            )

    def _on_verify_tools(self, _button) -> None:
        self._engine.refresh_tools()
        self._refresh_tool_rows()

    # --------------------------------------------------------------- handlers
    def _on_playlist_folder(self, row, _param) -> None:
        self._settings.playlist_subfolder = row.get_active()
        self._settings.save()

    def _on_index_in_filename(self, row, _param) -> None:
        self._settings.index_in_filename = row.get_active()
        self._settings.save()

    def _on_cover(self, row, _param) -> None:
        self._settings.embed_thumbnail = row.get_active()
        self._settings.save()

    def _on_tags(self, row, _param) -> None:
        self._settings.add_metadata = row.get_active()
        self._settings.save()

    def _on_parallel(self, row, _param) -> None:
        self._settings.max_parallel = int(row.get_value())
        self._settings.save()

    def _on_speed_limit(self, row, _param) -> None:
        self._settings.speed_limit_kib = int(row.get_value())
        self._settings.save()

    def _on_choose_folder(self, _button) -> None:
        dialog = Gtk.FileDialog()
        dialog.set_title("Escolher pasta de saída")
        dialog.set_initial_folder(
            Gio.File.new_for_path(str(self._settings.resolved_output_dir()))
        )
        dialog.select_folder(self._parent, None, self._on_folder_chosen)

    def _on_folder_chosen(self, dialog, result) -> None:
        try:
            gfile = dialog.select_folder_finish(result)
        except GLib.Error:
            return
        if gfile is None or gfile.get_path() is None:
            return
        self._settings.output_folder = gfile.get_path()
        self._settings.save()
        self._folder_row.set_subtitle(str(self._settings.resolved_output_dir()))
