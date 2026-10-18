"""Janela principal do yt2mp3 (GTK4 + libadwaita)."""

from __future__ import annotations

import os
from pathlib import Path

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")

from gi.repository import Adw, Gdk, Gio, GLib, Gtk, Pango  # noqa: E402

from . import APP_TITLE  # noqa: E402
from .backend import (  # noqa: E402
    ACTIVE_STATES,
    CONVERTING,
    DONE,
    DOWNLOADING,
    ERROR,
    PROBING,
    Engine,
    Job,
)
from .config import AUDIO_FORMATS, BITRATES, LOSSLESS_FORMATS, Settings  # noqa: E402
from .formatting import human_bytes, human_eta, human_speed  # noqa: E402
from .urls import is_supported, split_entries  # noqa: E402

FORMAT_KEYS = list(AUDIO_FORMATS.keys())
FORMAT_LABELS = [AUDIO_FORMATS[k] for k in FORMAT_KEYS]

STATE_LABELS = {
    "queued": "Na fila",
    PROBING: "Analisando…",
    DOWNLOADING: "Baixando",
    CONVERTING: "Convertendo",
    DONE: "Concluído",
    ERROR: "Erro",
    "cancelled": "Cancelado",
}


def _open_path(path: str) -> None:
    """Abre uma pasta/arquivo com o aplicativo padrão do sistema."""
    uri = Gio.File.new_for_path(path).get_uri()
    launcher = Gtk.UriLauncher.new(uri)
    launcher.launch(None, None, None)


class JobRow(Gtk.ListBoxRow):
    """Uma linha da fila representando um Job."""

    def __init__(self, job: Job, on_cancel, on_remove):
        super().__init__()
        self.job = job
        self._on_cancel = on_cancel
        self._on_remove = on_remove
        self._output_dir = ""
        self.add_css_class("job-row")

        outer = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        outer.set_margin_top(10)
        outer.set_margin_bottom(10)
        outer.set_margin_start(12)
        outer.set_margin_end(12)
        self.set_child(outer)

        header = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        outer.append(header)

        text_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=1)
        text_box.set_hexpand(True)
        header.append(text_box)

        self.title_label = Gtk.Label(
            xalign=0.0, ellipsize=Pango.EllipsizeMode.END, max_width_chars=10
        )
        self.title_label.add_css_class("body")
        self.title_label.set_hexpand(True)
        text_box.append(self.title_label)

        self.subtitle_label = Gtk.Label(
            xalign=0.0, ellipsize=Pango.EllipsizeMode.END, max_width_chars=10
        )
        self.subtitle_label.add_css_class("caption")
        self.subtitle_label.add_css_class("dim-label")
        text_box.append(self.subtitle_label)

        self.cancel_button = Gtk.Button(icon_name="process-stop-symbolic")
        self.cancel_button.add_css_class("flat")
        self.cancel_button.set_valign(Gtk.Align.CENTER)
        self.cancel_button.set_tooltip_text("Cancelar")
        self.cancel_button.connect("clicked", lambda *_: self._on_cancel(self))
        header.append(self.cancel_button)

        self.open_button = Gtk.Button(icon_name="folder-open-symbolic")
        self.open_button.add_css_class("flat")
        self.open_button.set_valign(Gtk.Align.CENTER)
        self.open_button.set_tooltip_text("Abrir pasta")
        self.open_button.connect("clicked", lambda *_: self._open_folder())
        header.append(self.open_button)

        self.remove_button = Gtk.Button(icon_name="user-trash-symbolic")
        self.remove_button.add_css_class("flat")
        self.remove_button.set_valign(Gtk.Align.CENTER)
        self.remove_button.set_tooltip_text("Remover da lista")
        self.remove_button.connect("clicked", lambda *_: self._on_remove(self))
        header.append(self.remove_button)

        self.progress = Gtk.ProgressBar()
        self.progress.set_show_text(False)
        outer.append(self.progress)

        self.update(job)

    def _open_folder(self) -> None:
        target = self.job.filepath or self._output_dir
        if not target:
            return
        path = target if os.path.isdir(target) else os.path.dirname(target)
        if path:
            _open_path(path)

    def update(self, job: Job) -> None:
        self.job = job
        self.title_label.set_label(job.display_title)

        subtitle_parts = [STATE_LABELS.get(job.state, job.state)]
        if job.state == DOWNLOADING:
            if job.percent:
                subtitle_parts.append(f"{job.percent:.0f}%")
            if job.total:
                subtitle_parts.append(
                    f"{human_bytes(job.downloaded)} de {human_bytes(job.total)}"
                )
            if job.speed:
                subtitle_parts.append(human_speed(job.speed))
            if job.eta:
                subtitle_parts.append(f"faltam {human_eta(job.eta)}")
        elif job.state == CONVERTING:
            subtitle_parts.append("extraindo áudio e gravando tags")
        elif job.state == DONE and job.filepath:
            subtitle_parts.append(os.path.basename(job.filepath))
        elif job.state == ERROR and job.error:
            subtitle_parts.append(job.error)

        if job.playlist_title and job.playlist_index:
            subtitle_parts.insert(0, f"{job.playlist_title} · faixa {job.playlist_index}")

        self.subtitle_label.set_label(" · ".join(str(p) for p in subtitle_parts if p))

        active = job.state in ACTIVE_STATES
        self.cancel_button.set_visible(job.state in ACTIVE_STATES or job.state == "queued")
        self.remove_button.set_visible(job.is_finished)
        self.open_button.set_visible(job.state == DONE and bool(job.filepath))
        self.progress.set_visible(active or job.state == DONE)

        if job.state == CONVERTING or job.state == PROBING:
            self.progress.pulse()
        elif job.state == DONE:
            self.progress.set_fraction(1.0)
        else:
            self.progress.set_fraction(max(0.0, min(1.0, job.percent / 100.0)))

        self.remove_css_class("error")
        if job.state == ERROR:
            self.add_css_class("error")


class MainWindow(Adw.ApplicationWindow):
    def __init__(self, application: Adw.Application, engine: Engine, settings: Settings):
        super().__init__(application=application)
        self.engine = engine
        self.settings = settings
        self.rows: dict[int, JobRow] = {}
        self._output_dir = str(settings.resolved_output_dir())
        self._banner_mode = ""

        self.set_title(APP_TITLE)
        self.set_default_size(820, 640)

        self.toolbar = Adw.ToolbarView()
        self.set_content(self.toolbar)

        header = Adw.HeaderBar()
        title_widget = Adw.WindowTitle(title=APP_TITLE, subtitle="yt2mp3")
        header.set_title_widget(title_widget)
        header.pack_end(self._build_menu_button())
        self.toolbar.add_top_bar(header)

        self.banner = Adw.Banner(title="", revealed=False)
        self.banner.set_button_label("Verificar novamente")
        self.banner.connect("button-clicked", self._on_banner_action)
        self.toolbar.add_top_bar(self.banner)

        self.toolbar.set_content(self._build_content())

        self._drop_target = Gtk.DropTarget.new(Gdk.FileList, Gdk.DragAction.COPY)
        self._drop_target.connect("drop", self._on_drop)
        self.add_controller(self._drop_target)

        self.refresh_tools_ui()
        self.update_footer()

    # ------------------------------------------------------------------ UI
    def _build_menu_button(self) -> Gtk.MenuButton:
        menu = Gio.Menu()
        menu.append("Preferências", "app.preferences")
        menu.append("Sobre", "app.about")
        menu.append("Sair", "app.quit")
        button = Gtk.MenuButton(icon_name="open-menu-symbolic")
        button.set_menu_model(menu)
        button.set_tooltip_text("Menu principal")
        return button

    def _build_content(self) -> Gtk.Widget:
        clamp = Adw.Clamp()
        clamp.set_maximum_size(760)
        clamp.set_tightening_threshold(560)

        root = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        root.set_margin_top(16)
        root.set_margin_bottom(16)
        root.set_margin_start(16)
        root.set_margin_end(16)

        root.append(self._build_input_card())
        root.append(self._build_options_card())

        self.stack = Gtk.Stack()
        self.stack.set_transition_type(Gtk.StackTransitionType.CROSSFADE)
        self.stack.set_vexpand(True)
        self.stack.add_named(self._build_empty_state(), "empty")
        self.stack.add_named(self._build_queue_view(), "queue")
        self.stack.set_visible_child_name("empty")
        root.append(self.stack)

        root.append(self._build_footer())
        clamp.set_child(root)
        return clamp

    def _build_input_card(self) -> Gtk.Widget:
        card = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        card.add_css_class("card")
        card.set_margin_top(2)

        inner = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        inner.set_margin_top(12)
        inner.set_margin_bottom(12)
        inner.set_margin_start(12)
        inner.set_margin_end(12)

        self.url_entry = Gtk.Entry()
        self.url_entry.set_placeholder_text("Cole o link do YouTube, Vimeo, SoundCloud…")
        self.url_entry.set_hexpand(True)
        self.url_entry.set_input_purpose(Gtk.InputPurpose.URL)
        self.url_entry.connect("activate", lambda *_: self._on_add_clicked())
        inner.append(self.url_entry)

        paste_button = Gtk.Button(icon_name="edit-paste-symbolic")
        paste_button.set_tooltip_text("Colar da área de transferência")
        paste_button.connect("clicked", self._on_paste_clicked)
        inner.append(paste_button)

        add_button = Gtk.Button(label="Adicionar")
        add_button.add_css_class("suggested-action")
        add_button.connect("clicked", lambda *_: self._on_add_clicked())
        inner.append(add_button)

        card.append(inner)
        return card

    def _build_options_card(self) -> Gtk.Widget:
        card = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)
        card.add_css_class("card")
        card.set_margin_top(2)

        inner = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)
        inner.set_margin_top(10)
        inner.set_margin_bottom(10)
        inner.set_margin_start(12)
        inner.set_margin_end(12)
        inner.set_hexpand(True)

        inner.append(self._label("Formato"))
        self.format_dropdown = Gtk.DropDown.new_from_strings(FORMAT_LABELS)
        self.format_dropdown.set_selected(
            FORMAT_KEYS.index(self.settings.audio_format)
            if self.settings.audio_format in FORMAT_KEYS
            else 0
        )
        self.format_dropdown.connect("notify::selected", self._on_format_changed)
        inner.append(self.format_dropdown)

        inner.append(self._label("Bitrate"))
        self.bitrate_dropdown = Gtk.DropDown.new_from_strings(
            [f"{b} kbps" for b in BITRATES]
        )
        self.bitrate_dropdown.set_selected(
            BITRATES.index(self.settings.bitrate)
            if self.settings.bitrate in BITRATES
            else 0
        )
        self.bitrate_dropdown.connect("notify::selected", self._on_bitrate_changed)
        inner.append(self.bitrate_dropdown)

        spacer = Gtk.Box()
        spacer.set_hexpand(True)
        inner.append(spacer)

        self.folder_button = Gtk.Button()
        self.folder_button.add_css_class("flat")
        self.folder_button.set_tooltip_text("Escolher pasta de saída")
        self.folder_button.connect("clicked", self._on_choose_folder)
        inner.append(self.folder_button)
        self._refresh_folder_button()

        card.append(inner)
        self._update_bitrate_sensitivity()
        return card

    def _label(self, text: str) -> Gtk.Label:
        label = Gtk.Label(label=text)
        label.add_css_class("dim-label")
        return label

    def _build_empty_state(self) -> Gtk.Widget:
        status = Adw.StatusPage()
        status.set_icon_name("folder-music-symbolic")
        status.set_title("Nenhum download na fila")
        status.set_description(
            "Cole um link acima ou arraste um arquivo de texto com links para começar."
        )
        return status

    def _build_queue_view(self) -> Gtk.Widget:
        scroller = Gtk.ScrolledWindow()
        scroller.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        scroller.set_vexpand(True)

        self.listbox = Gtk.ListBox()
        self.listbox.set_selection_mode(Gtk.SelectionMode.NONE)
        self.listbox.add_css_class("boxed-list")
        self.listbox.set_valign(Gtk.Align.START)
        scroller.set_child(self.listbox)
        return scroller

    def _build_footer(self) -> Gtk.Widget:
        footer = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        footer.set_margin_top(4)

        self.summary_label = Gtk.Label(xalign=0.0)
        self.summary_label.add_css_class("caption")
        self.summary_label.add_css_class("dim-label")
        self.summary_label.set_hexpand(True)
        footer.append(self.summary_label)

        self.cancel_all_button = Gtk.Button(label="Cancelar tudo")
        self.cancel_all_button.add_css_class("flat")
        self.cancel_all_button.connect("clicked", lambda *_: self.engine.cancel_all())
        footer.append(self.cancel_all_button)

        self.clear_button = Gtk.Button(label="Limpar concluídos")
        self.clear_button.add_css_class("flat")
        self.clear_button.connect("clicked", lambda *_: self.engine.clear_finished())
        footer.append(self.clear_button)

        return footer

    # --------------------------------------------------------------- actions
    def _on_add_clicked(self) -> None:
        text = self.url_entry.get_text().strip()
        if not text:
            return
        urls = split_entries(text)
        valid = [u for u in urls if is_supported(u)]
        if not valid:
            self.banner.set_title("Nenhum link suportado encontrado no texto colado.")
            self.banner.set_revealed(True)
            self._banner_mode = "dismiss"
            self.banner.set_button_label("OK")
            return
        self.url_entry.set_text("")
        self.engine.add(valid)

    def _on_paste_clicked(self, _button) -> None:
        clipboard = self.get_clipboard()
        clipboard.read_text_async(None, self._on_clipboard_text)

    def _on_clipboard_text(self, clipboard, result) -> None:
        try:
            text = clipboard.read_text_finish(result) or ""
        except GLib.Error:
            return
        urls = [u for u in split_entries(text) if is_supported(u)]
        if urls:
            self.url_entry.set_text(urls[0])
            self.url_entry.set_position(-1)

    def _on_drop(self, _target, value, _x, _y) -> bool:
        texts: list[str] = []
        for gfile in value.get_files():
            path = gfile.get_path()
            if not path:
                continue
            try:
                texts.append(Path(path).read_text(encoding="utf-8", errors="replace"))
            except OSError:
                continue
        urls = []
        for text in texts:
            urls.extend(u for u in split_entries(text) if is_supported(u))
        if urls:
            self.engine.add(urls)
            return True
        return False

    def _on_format_changed(self, dropdown, _param) -> None:
        key = FORMAT_KEYS[dropdown.get_selected()]
        self.settings.audio_format = key
        self.settings.save()
        self._update_bitrate_sensitivity()

    def _on_bitrate_changed(self, dropdown, _param) -> None:
        self.settings.bitrate = BITRATES[dropdown.get_selected()]
        self.settings.save()

    def _update_bitrate_sensitivity(self) -> None:
        lossless = self.settings.audio_format in LOSSLESS_FORMATS
        self.bitrate_dropdown.set_sensitive(not lossless)
        self.bitrate_dropdown.set_tooltip_text(
            "Formatos sem perda não usam bitrate." if lossless else None
        )

    def _on_choose_folder(self, _button) -> None:
        dialog = Gtk.FileDialog()
        dialog.set_title("Escolher pasta de saída")
        dialog.set_initial_folder(
            Gio.File.new_for_path(str(self.settings.resolved_output_dir()))
        )
        dialog.select_folder(self, None, self._on_folder_chosen)

    def _on_folder_chosen(self, dialog, result) -> None:
        try:
            gfile = dialog.select_folder_finish(result)
        except GLib.Error:
            return
        if gfile is None:
            return
        path = gfile.get_path()
        if not path:
            return
        self.settings.output_folder = path
        self.settings.save()
        self._refresh_folder_button()

    def _refresh_folder_button(self) -> None:
        path = self.settings.resolved_output_dir()
        display = str(path).replace(str(Path.home()), "~")
        box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        box.append(Gtk.Image.new_from_icon_name("folder-open-symbolic"))
        box.append(Gtk.Label(label=display))
        self.folder_button.set_child(box)

    def _on_cancel_row(self, row: JobRow) -> None:
        self.engine.cancel(row.job.job_id)

    def _on_remove_row(self, row: JobRow) -> None:
        self.engine.remove(row.job.job_id)

    # ------------------------------------------------------------- callbacks
    def on_tools_changed(self) -> None:
        self.refresh_tools_ui()

    def refresh_tools_ui(self) -> None:
        problems = self.engine.tool_problems()
        if problems:
            self._banner_mode = "tools"
            self.banner.set_title(problems[0])
            self.banner.set_button_label("Verificar novamente")
            self.banner.set_revealed(True)
        elif getattr(self, "_banner_mode", "") != "dismiss":
            self.banner.set_revealed(False)

    def _on_banner_action(self) -> None:
        if getattr(self, "_banner_mode", "") == "dismiss":
            self.banner.set_revealed(False)
        else:
            self.engine.refresh_tools()

    def on_queue_changed(self) -> None:
        self._rebuild_rows()
        self.update_footer()

    def on_job_changed(self, job: Job) -> None:
        if job.job_id < 0:
            return
        row = self.rows.get(job.job_id)
        if row is None:
            self._rebuild_rows()
            self.update_footer()
            return
        row.update(job)
        self.update_footer()

    def _rebuild_rows(self) -> None:
        if not hasattr(self, "listbox") or not hasattr(self, "stack"):
            return
        existing = {job.job_id for job in self.engine.jobs}
        for job_id in list(self.rows):
            if job_id not in existing:
                self.listbox.remove(self.rows.pop(job_id))

        for job in self.engine.jobs:
            if job.job_id in self.rows:
                continue
            row = JobRow(job, self._on_cancel_row, self._on_remove_row)
            row._output_dir = self._output_dir
            self.rows[job.job_id] = row
            self.listbox.append(row)

        # Mantém a ordem da fila.
        for index, job in enumerate(self.engine.jobs):
            row = self.rows.get(job.job_id)
            if row is not None:
                self.listbox.remove(row)
                self.listbox.insert(row, index)

        self.stack.set_visible_child_name("queue" if self.engine.jobs else "empty")

    def update_footer(self) -> None:
        jobs = self.engine.jobs
        total = len(jobs)
        done = sum(1 for j in jobs if j.state == DONE)
        errors = sum(1 for j in jobs if j.state == ERROR)
        active = sum(1 for j in jobs if j.state in ACTIVE_STATES)

        if total == 0:
            self.summary_label.set_label("Pronto.")
        else:
            parts = [f"{done} de {total} concluídos"]
            if active:
                parts.append(f"{active} em andamento")
            if errors:
                parts.append(f"{errors} com erro")
            self.summary_label.set_label(" · ".join(parts))

        self.clear_button.set_sensitive(any(j.is_finished for j in jobs))
        self.cancel_all_button.set_sensitive(active > 0)
