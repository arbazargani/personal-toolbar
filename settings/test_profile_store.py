"""Regression tests for the native settings application's SQLite adapter."""

import importlib.util
import os
import pathlib
import sqlite3
import sys
import tempfile
import unittest
from unittest.mock import patch


APP_PATH = pathlib.Path(__file__).with_name("modular-toolbar-settings.py")
SPEC = importlib.util.spec_from_file_location("modular_toolbar_settings", APP_PATH)
APP = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = APP
SPEC.loader.exec_module(APP)


class ProfileStoreTests(unittest.TestCase):
    def setUp(self):
        self.config_home = tempfile.TemporaryDirectory(prefix="toolbar-settings-test-")
        self.env = patch.dict(os.environ, {"XDG_CONFIG_HOME": self.config_home.name})
        self.env.start()
        self.addCleanup(self.env.stop)
        self.addCleanup(self.config_home.cleanup)
        self.store = APP.ProfileStore()

    def test_new_profile_requires_key_and_does_not_expose_it(self):
        with self.assertRaisesRegex(ValueError, "API key is required"):
            self.store.save_profile("personal", "Personal", None, True)

        self.store.save_profile("personal", "Personal", "secret-one", True)
        profile = self.store.profiles()[0]
        self.assertEqual(profile["has_key"], 1)
        self.assertNotIn("api_key", profile)
        self.assertNotIn("secret-one", repr(profile))

    def test_edit_without_key_preserves_key_and_polling_state(self):
        self.store.save_profile("work", "Work", "secret-one", True)
        with sqlite3.connect(self.store.database_path) as connection:
            connection.execute(
                """UPDATE profiles
                   SET latest_json=?, last_success=?, last_error=? WHERE id=?""",
                (b'{"credits":7}', "2026-10-21T10:00:00Z", "old error", "work"),
            )

        self.store.save_profile("work", "Work account", None, False)
        with sqlite3.connect(self.store.database_path) as connection:
            row = connection.execute(
                """SELECT name, api_key, enabled, latest_json, last_success, last_error
                   FROM profiles WHERE id=?""",
                ("work",),
            ).fetchone()

        self.assertEqual(
            row,
            (
                "Work account",
                "secret-one",
                0,
                b'{"credits":7}',
                "2026-10-21T10:00:00Z",
                "old error",
            ),
        )

    def test_key_can_be_replaced_and_profile_can_be_toggled_or_deleted(self):
        self.store.save_profile("work", "Work", "secret-one", True)
        self.store.save_profile("work", "Work", "secret-two", True)
        with sqlite3.connect(self.store.database_path) as connection:
            key = connection.execute(
                "SELECT api_key FROM profiles WHERE id=?", ("work",)
            ).fetchone()[0]
        self.assertEqual(key, "secret-two")

        self.store.set_enabled("work", False)
        self.assertEqual(self.store.profiles()[0]["enabled"], 0)
        self.store.delete_profile("work")
        self.assertEqual(self.store.profiles(), [])


if __name__ == "__main__":
    unittest.main()
