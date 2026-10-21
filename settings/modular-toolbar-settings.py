#!/usr/bin/python3
"""Native GTK/libadwaita profile manager for Modular Ubuntu Toolbar."""

import os
import re
import sqlite3
import sys
from contextlib import contextmanager
from pathlib import Path

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")

from gi.repository import Adw, Gio, GLib, Gtk


APP_ID = "com.example.ModularToolbar"
APP_NAME = "Modular Toolbar Settings"
SERVICE_NAME = "modular-toolbar.service"
MODULE_ID = "avalai_credit_info"
MODULE_LABEL = "Avalai credit information"
PROFILE_ID_RE = re.compile(r"^[a-z0-9][a-z0-9_-]*$")


class ProfileStore:
    """Small SQLite adapter that never returns API keys to the view layer."""

    def __init__(self):
        config_home = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config"))
        self.database_path = config_home / "modular-toolbar" / "toolbar.db"
        self.database_path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        try:
            os.chmod(self.database_path.parent, 0o700)
        except OSError:
            pass
        self._ensure_schema()
        try:
            os.chmod(self.database_path, 0o600)
        except OSError:
            pass

    def _connect(self):
        connection = sqlite3.connect(self.database_path, timeout=3)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA busy_timeout=3000")
        return connection

    @contextmanager
    def _connection(self):
        connection = self._connect()
        try:
            yield connection
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    def _ensure_schema(self):
        with self._connection() as connection:
            connection.executescript(
                """
                PRAGMA foreign_keys=ON;
                CREATE TABLE IF NOT EXISTS settings (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS profiles (
                    id TEXT PRIMARY KEY,
                    module_id TEXT NOT NULL,
                    name TEXT NOT NULL,
                    api_key TEXT NOT NULL,
                    enabled INTEGER NOT NULL DEFAULT 1,
                    latest_json BLOB,
                    last_success TEXT,
                    last_error TEXT NOT NULL DEFAULT ''
                );
                """
            )

    def profiles(self):
        with self._connection() as connection:
            rows = connection.execute(
                """
                SELECT id, module_id, name, enabled, last_success, last_error,
                       CASE WHEN trim(api_key) <> '' THEN 1 ELSE 0 END AS has_key
                FROM profiles
                ORDER BY name COLLATE NOCASE, id
                """
            ).fetchall()
        return [dict(row) for row in rows]

    def save_profile(self, profile_id, name, api_key, enabled):
        with self._connection() as connection:
            current = connection.execute(
                "SELECT api_key FROM profiles WHERE id = ?", (profile_id,)
            ).fetchone()

            if current is None:
                if not api_key:
                    raise ValueError("An API key is required for a new profile.")
                connection.execute(
                    """
                    INSERT INTO profiles
                        (id, module_id, name, api_key, enabled, last_error)
                    VALUES (?, ?, ?, ?, ?, '')
                    """,
                    (profile_id, MODULE_ID, name, api_key, int(enabled)),
                )
            elif api_key:
                connection.execute(
                    """
                    UPDATE profiles
                    SET name = ?, api_key = ?, enabled = ?, module_id = ?
                    WHERE id = ?
                    """,
                    (name, api_key, int(enabled), MODULE_ID, profile_id),
                )
            else:
                connection.execute(
                    """
                    UPDATE profiles
                    SET name = ?, enabled = ?, module_id = ?
                    WHERE id = ?
                    """,
                    (name, int(enabled), MODULE_ID, profile_id),
                )

    def set_enabled(self, profile_id, enabled):
        with self._connection() as connection:
            connection.execute(
                "UPDATE profiles SET enabled = ? WHERE id = ?",
                (int(enabled), profile_id),
            )

    def delete_profile(self, profile_id):
        with self._connection() as connection:
            connection.execute("DELETE FROM profiles WHERE id = ?", (profile_id,))


class SettingsWindow(Adw.ApplicationWindow):
    def __init__(self, application):
        super().__init__(application=application)
        self.set_title(APP_NAME)
        self.set_default_size(760, 620)

        self.store = ProfileStore()
        self._editor_window = None
        self._restart_process = None
        self._restart_queued = False
        self._refresh_source = GLib.timeout_add_seconds(
            5, self._refresh_periodically
        )

        self._build_ui()
        self.refresh_profiles()

    def _build_ui(self):
        self.toast_overlay = Adw.ToastOverlay()
        self.set_content(self.toast_overlay)

        toolbar_view = Adw.ToolbarView()
        self.toast_overlay.set_child(toolbar_view)

        header = Adw.HeaderBar()
        header.set_title_widget(
            Adw.WindowTitle(title="Modular Toolbar", subtitle="Profile settings")
        )

        add_button = Gtk.Button(label="Add profile")
        add_button.add_css_class("suggested-action")
        add_button.set_tooltip_text("Add a new Avalai profile")
        add_button.connect("clicked", lambda *_args: self.open_editor())
        header.pack_end(add_button)

        refresh_button = Gtk.Button.new_from_icon_name("view-refresh-symbolic")
        refresh_button.set_tooltip_text("Refresh profile status")
        refresh_button.connect("clicked", lambda *_args: self.refresh_profiles())
        header.pack_start(refresh_button)
        toolbar_view.add_top_bar(header)

        content = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=18)
        content.set_margin_top(24)
        content.set_margin_bottom(24)
        content.set_margin_start(24)
        content.set_margin_end(24)
        toolbar_view.set_content(content)

        intro = Gtk.Label(
            label=(
                "Manage the accounts shown by the top-panel monitor. "
                "API keys are stored locally and are never displayed in the profile list."
            )
        )
        intro.set_wrap(True)
        intro.set_xalign(0)
        intro.add_css_class("dim-label")
        content.append(intro)

        self.profiles_container = Gtk.Box(
            orientation=Gtk.Orientation.VERTICAL, spacing=8
        )
        profile_scroller = Gtk.ScrolledWindow()
        profile_scroller.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        profile_scroller.set_vexpand(True)
        profile_scroller.set_child(self.profiles_container)
        content.append(profile_scroller)

        self.service_status = Gtk.Label()
        self.service_status.set_xalign(0)
        self.service_status.add_css_class("dim-label")
        content.append(self.service_status)

    def refresh_profiles(self):
        while (child := self.profiles_container.get_first_child()) is not None:
            child.unparent()

        try:
            profiles = self.store.profiles()
        except (OSError, sqlite3.Error) as error:
            self._show_error_page("Could not read profiles", str(error))
            return

        if not profiles:
            empty = Adw.StatusPage(
                title="No profiles yet",
                description="Add an Avalai profile to start showing credit data.",
                icon_name="contact-new-symbolic",
            )
            empty.set_vexpand(True)
            self.profiles_container.append(empty)
            self.service_status.set_text("The backend will remain inactive until a profile is enabled.")
            return

        group = Adw.PreferencesGroup(
            title="Profiles",
            description="Enable, edit, or remove saved monitor profiles.",
        )
        for profile in profiles:
            group.add(self._profile_row(profile))
        self.profiles_container.append(group)

        enabled_count = sum(1 for profile in profiles if profile["enabled"])
        self.service_status.set_text(
            f"{len(profiles)} profile(s), {enabled_count} enabled. Changes restart the background service."
        )

    def _refresh_periodically(self):
        self.refresh_profiles()
        return GLib.SOURCE_CONTINUE

    def _profile_row(self, profile):
        row = Adw.ActionRow()
        row.set_title(profile["name"])
        row.set_subtitle(self._profile_subtitle(profile))
        row.set_subtitle_lines(3)

        enabled_switch = Gtk.Switch(valign=Gtk.Align.CENTER)
        enabled_switch.set_active(bool(profile["enabled"]))
        enabled_switch.set_tooltip_text("Enable or disable this profile")
        enabled_switch.connect(
            "state-set", self._on_profile_toggled, profile["id"]
        )
        row.add_suffix(enabled_switch)

        edit_button = Gtk.Button.new_from_icon_name("document-edit-symbolic")
        edit_button.set_valign(Gtk.Align.CENTER)
        edit_button.set_tooltip_text("Edit profile")
        edit_button.connect("clicked", lambda *_args: self.open_editor(profile["id"]))
        row.add_suffix(edit_button)

        delete_button = Gtk.Button.new_from_icon_name("user-trash-symbolic")
        delete_button.set_valign(Gtk.Align.CENTER)
        delete_button.add_css_class("destructive-action")
        delete_button.set_tooltip_text("Delete profile")
        delete_button.connect(
            "clicked", lambda *_args: self.confirm_delete(profile)
        )
        row.add_suffix(delete_button)
        return row

    @staticmethod
    def _profile_subtitle(profile):
        state = "Enabled" if profile["enabled"] else "Disabled"
        key_state = "API key saved" if profile["has_key"] else "API key missing"
        lines = [f"{state} · {key_state} · ID: {profile['id']}"]

        if profile["last_error"]:
            lines.append(f"Last error: {profile['last_error']}")
        elif profile["last_success"]:
            timestamp = profile["last_success"].replace("T", " ").replace("Z", " UTC")
            lines.append(f"Last successful update: {timestamp}")
        else:
            lines.append("Waiting for the first successful update")
        return "\n".join(lines)

    def _on_profile_toggled(self, _switch, state, profile_id):
        try:
            self.store.set_enabled(profile_id, state)
        except (OSError, sqlite3.Error) as error:
            self._show_toast(f"Could not update profile: {error}")
            _switch.set_active(not state)
            return True

        self._restart_backend()
        return False

    def open_editor(self, profile_id=None):
        if self._editor_window is not None:
            self._editor_window.present()
            return

        editing = profile_id is not None
        existing = None
        if profile_id is not None:
            try:
                existing = next(
                    (p for p in self.store.profiles() if p["id"] == profile_id), None
                )
            except (OSError, sqlite3.Error) as error:
                self._show_toast(f"Could not open profile: {error}")
                return

        if profile_id is not None and existing is None:
            self._show_toast("That profile no longer exists.")
            self.refresh_profiles()
            return
        dialog = Adw.Window(
            transient_for=self,
            modal=True,
            title="Edit profile" if editing else "Add profile",
        )
        dialog.set_default_size(520, 0)
        dialog.set_resizable(False)
        self._editor_window = dialog

        header = Adw.HeaderBar()
        save_button = Gtk.Button(label="Save")
        save_button.add_css_class("suggested-action")
        header.pack_end(save_button)

        body = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=18)
        body.set_margin_top(24)
        body.set_margin_bottom(24)
        body.set_margin_start(24)
        body.set_margin_end(24)

        dialog_view = Adw.ToolbarView()
        dialog_view.add_top_bar(header)
        dialog_view.set_content(body)
        dialog.set_content(dialog_view)

        group = Adw.PreferencesGroup(
            title="Profile details",
            description="Only the display name and profile ID are shown outside this window.",
        )
        body.append(group)

        name_row = Adw.EntryRow(title="Display name")
        name_row.set_text(existing["name"] if existing else "")
        name_row.set_show_apply_button(False)
        group.add(name_row)

        id_row = Adw.EntryRow(title="Profile ID")
        id_row.set_text(existing["id"] if existing else "")
        id_row.set_show_apply_button(False)
        id_row.set_editable(not editing)
        if editing:
            id_row.set_tooltip_text("The profile ID cannot be changed while editing.")
        group.add(id_row)

        generated_id = id_row.get_text()

        def suggest_id(*_args):
            nonlocal generated_id
            current_id = id_row.get_text()
            if current_id and current_id != generated_id:
                return
            slug = re.sub(r"[^a-z0-9]+", "-", name_row.get_text().strip().lower())
            slug = slug.strip("-")
            if slug:
                generated_id = slug
                id_row.set_text(slug)

        if not editing:
            name_row.connect("changed", suggest_id)

        key_row = Adw.ActionRow(title="Avalai API key")
        key_entry = Gtk.PasswordEntry(show_peek_icon=True, hexpand=True)
        key_entry.set_property("placeholder-text", "Enter API key")
        key_row.add_suffix(key_entry)
        key_row.set_activatable_widget(key_entry)
        if editing:
            key_entry.set_property("placeholder-text", "Leave blank to keep saved key")
        key_row.set_tooltip_text("API key input is hidden while you type.")
        group.add(key_row)

        module_row = Adw.ActionRow(
            title="Module", subtitle=MODULE_LABEL
        )
        module_row.add_suffix(Gtk.Image.new_from_icon_name("emblem-ok-symbolic"))
        group.add(module_row)

        enabled_row = Adw.SwitchRow(title="Enabled")
        enabled_row.set_subtitle("Enabled profiles are refreshed by the background service.")
        enabled_row.set_active(bool(existing["enabled"]) if existing else True)
        group.add(enabled_row)

        help_label = Gtk.Label(
            label=(
                "For an existing profile, leave the API key blank to keep it. "
                "The key is stored only in the local SQLite database."
            )
        )
        help_label.set_wrap(True)
        help_label.set_xalign(0)
        help_label.add_css_class("dim-label")
        body.append(help_label)

        error_label = Gtk.Label()
        error_label.set_wrap(True)
        error_label.set_xalign(0)
        error_label.add_css_class("error")
        body.append(error_label)

        def save():
            name = name_row.get_text().strip()
            profile_id = id_row.get_text().strip().lower()
            api_key = key_entry.get_text()

            if not name:
                error_label.set_text("Display name cannot be empty.")
                return
            if not PROFILE_ID_RE.fullmatch(profile_id):
                error_label.set_text(
                    "Profile ID must use lowercase letters, numbers, underscores, or hyphens."
                )
                return
            if not editing and not api_key.strip():
                error_label.set_text("An API key is required for a new profile.")
                return

            try:
                self.store.save_profile(
                    profile_id,
                    name,
                    api_key or None,
                    enabled_row.get_active(),
                )
            except ValueError as error:
                error_label.set_text(str(error))
                return
            except sqlite3.IntegrityError:
                error_label.set_text("A profile with that ID already exists.")
                return
            except (OSError, sqlite3.Error) as error:
                error_label.set_text(f"Could not save profile: {error}")
                return

            dialog.close()
            self.refresh_profiles()
            self._restart_backend()

        save_button.connect("clicked", lambda *_args: save())
        dialog.connect("close-request", lambda *_args: self._clear_editor(dialog))
        dialog.present()

        def focus_name_once():
            name_row.grab_focus()
            return GLib.SOURCE_REMOVE

        GLib.idle_add(focus_name_once)

    def _clear_editor(self, dialog):
        if self._editor_window is dialog:
            self._editor_window = None
        return False

    def confirm_delete(self, profile):
        dialog = Adw.AlertDialog.new(
            "Delete profile?",
            f"Remove {profile['name']} from the local profile list? This cannot be undone.",
        )
        dialog.add_response("cancel", "Cancel")
        dialog.add_response("delete", "Delete")
        dialog.set_response_appearance("delete", Adw.ResponseAppearance.DESTRUCTIVE)
        dialog.set_default_response("cancel")
        dialog.set_close_response("cancel")

        def respond(_dialog, response):
            if response != "delete":
                return
            try:
                self.store.delete_profile(profile["id"])
            except (OSError, sqlite3.Error) as error:
                self._show_toast(f"Could not delete profile: {error}")
                return
            self.refresh_profiles()
            self._restart_backend()
            self._show_toast(f"Deleted {profile['name']}")

        dialog.connect("response", respond)
        dialog.present(self)

    def _restart_backend(self):
        if self._restart_process is not None:
            self._restart_queued = True
            return
        try:
            self._restart_process = Gio.Subprocess.new(
                ["systemctl", "--user", "restart", SERVICE_NAME],
                Gio.SubprocessFlags.STDOUT_SILENCE
                | Gio.SubprocessFlags.STDERR_SILENCE,
            )
            self._restart_process.wait_check_async(None, self._restart_finished)
        except (GLib.Error, OSError):
            self._restart_process = None
            self._show_toast("Saved, but the backend could not be restarted automatically.")

    def _restart_finished(self, process, result):
        try:
            process.wait_check_finish(result)
        except GLib.Error:
            self._show_toast(
                "Saved, but the backend could not be restarted. Restart it manually."
            )
        else:
            self._show_toast("Saved. Backend restarted.")
        finally:
            self._restart_process = None
            self.refresh_profiles()
            if self._restart_queued:
                self._restart_queued = False
                self._restart_backend()

    def _show_error_page(self, title, description):
        page = Adw.StatusPage(title=title, description=description, icon_name="dialog-error-symbolic")
        page.set_vexpand(True)
        self.profiles_container.append(page)
        self.service_status.set_text("Check that the database is readable by your user.")

    def _show_toast(self, message):
        self.toast_overlay.add_toast(Adw.Toast.new(message))

    def do_close_request(self):
        if self._refresh_source:
            GLib.source_remove(self._refresh_source)
            self._refresh_source = 0
        return False


class SettingsApplication(Adw.Application):
    def __init__(self):
        # Keep one settings process per user session. Launching the app again
        # from the panel is forwarded to do_activate() on the existing process.
        super().__init__(application_id=APP_ID)
        self.window = None

    def do_activate(self):
        if self.window is None:
            self.window = SettingsWindow(self)
        self.window.present()


def main():
    application = SettingsApplication()
    return application.run(sys.argv)


if __name__ == "__main__":
    raise SystemExit(main())
