"""
Test suite for the GitHub Events Tracker application.

This module contains both unit tests and integration tests for the main application.
"""

import datetime
import json
import os
import tempfile
import unittest

import app  # our main application module


class TestLoadConfig(unittest.TestCase):
    """Tests for the load_config function in the application module."""

    def setUp(self):
        """Create a temporary directory and config file for testing."""
        # Using TemporaryDirectory without 'with' since we need it in tearDown.
        self.temp_dir = (
            tempfile.TemporaryDirectory()  # pylint: disable=consider-using-with
        )
        self.config_path = os.path.join(self.temp_dir.name, "config.json")

    def tearDown(self):
        """Cleanup the temporary directory."""
        self.temp_dir.cleanup()

    def test_valid_config_limits(self):
        """Test that only MAX_REPOS repositories are loaded from the configuration."""
        data = {
            "repositories": [f"owner/repo{num}" for num in range(1, app.MAX_REPOS + 9)]
        }
        with open(self.config_path, "w", encoding="utf-8") as f:
            json.dump(data, f)

        original_config_file = app.CONFIG_FILE
        try:
            app.CONFIG_FILE = self.config_path
            repos = app.load_config()
            self.assertEqual(len(repos), app.MAX_REPOS)
            expected_repos = [f"owner/repo{num}" for num in range(1, app.MAX_REPOS + 1)]
            self.assertEqual(repos, expected_repos)
        finally:
            app.CONFIG_FILE = original_config_file


class TestDatabaseFunctions(unittest.TestCase):
    """Tests for database functions (insert_event and get_recent_events),
    in the application module."""

    def setUp(self):
        """Create a temporary SQLite database file and initialize it."""
        self.temp_db = (
            tempfile.NamedTemporaryFile(  # pylint: disable=consider-using-with
                delete=False
            )
        )
        self.temp_db.close()
        self.original_db_file = app.DB_FILE
        app.DB_FILE = self.temp_db.name
        app.init_db()

    def tearDown(self):
        """Restore the original DB_FILE value and remove the temporary database file."""
        app.DB_FILE = self.original_db_file
        os.unlink(self.temp_db.name)

    def test_insert_and_get_recent_events(self):
        """Test that inserted events are retrieved in the correct order."""
        now = datetime.datetime.now(datetime.timezone.utc)
        event1 = {
            "id": "1",
            "type": "TestEvent",
            "created_at": (now - datetime.timedelta(hours=2))
            .isoformat()
            .replace("+00:00", "Z"),
        }
        event2 = {
            "id": "2",
            "type": "TestEvent",
            "created_at": now.isoformat().replace("+00:00", "Z"),
        }
        app.insert_event(event1, "owner/repo")
        app.insert_event(event2, "owner/repo")
        events = app.get_recent_events("owner/repo", "TestEvent")
        self.assertEqual(len(events), 2)
        self.assertLess(events[0], events[1])


class TestAPIIntegration(unittest.TestCase):
    """Integration tests for the Flask API endpoint in the application module."""

    def setUp(self):
        """Set up a temporary database and a Flask test client, and insert sample events."""
        self.temp_db = (
            tempfile.NamedTemporaryFile(  # pylint: disable=consider-using-with
                delete=False
            )
        )
        self.temp_db.close()
        self.original_db_file = app.DB_FILE
        app.DB_FILE = self.temp_db.name
        app.init_db()
        self.client = app.app.test_client()
        self.client.testing = True

        # Insert sample events for repository "owner/repo" with event type "PushEvent"
        now = datetime.datetime.now(datetime.timezone.utc)
        event_times = [now - datetime.timedelta(minutes=i * 5) for i in range(5)]
        # Insert events so that they are in ascending order by created_at.
        for i, event_time in enumerate(reversed(event_times)):
            event = {
                "id": str(i),
                "type": "PushEvent",
                "created_at": event_time.isoformat().replace("+00:00", "Z"),
            }
            app.insert_event(event, "owner/repo")

    def tearDown(self):
        """Restore the original DB_FILE value and remove the temporary database file."""
        app.DB_FILE = self.original_db_file
        os.unlink(self.temp_db.name)

    def test_stats_endpoint(self):
        """Test that the /stats endpoint returns the expected data structure and values."""
        response = self.client.get("/stats")
        self.assertEqual(response.status_code, 200)
        data = json.loads(response.data.decode("utf-8"))
        self.assertIn("owner/repo", data)
        self.assertIn("PushEvent", data["owner/repo"])
        avg_interval = data["owner/repo"]["PushEvent"]
        self.assertIsInstance(avg_interval, float)
        self.assertGreater(avg_interval, 0)


if __name__ == "__main__":
    unittest.main()
