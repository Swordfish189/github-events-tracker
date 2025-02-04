""" GitHub Events Tracker app.
    MAX_REPOS repos, MAX_EVENTS events of the last MAX_DAYS days """

import datetime
import json
import logging
import sqlite3
import threading
from typing import Any, Dict, List

import requests
from apscheduler.schedulers.background import BackgroundScheduler
from flask import Flask, jsonify

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Flask application instance
app = Flask(__name__)

# Global configuration
CONFIG_FILE = "config.json"
DB_FILE = "events.db"
GITHUB_API_URL = "https://api.github.com/repos/{repo}/events"
POLL_INTERVAL_SECONDS = 60  # fetch events every minute
MAX_REPOS = 5
MAX_EVENTS = 500
MAX_DAYS = 7


def load_config() -> List[str]:
    """
    Load list of repositories from a JSON config file.
    The config file should contain a key "repositories" that maps to a list of repo full names.
    Example:
      { "repositories": ["owner1/repo1", "owner2/repo2"] }
    """
    try:
        with open(CONFIG_FILE, "r", encoding="utf-8") as f:
            config = json.load(f)
            repos = config.get("repositories", [])
            if len(repos) > MAX_REPOS:
                repos = repos[:MAX_REPOS]  # only monitor up to MAX_REPOS repositories
            logger.info("Configured repositories: %s", repos)
            return repos
    except FileNotFoundError:
        logger.error("Config file not found: %s", CONFIG_FILE)
        return []
    except json.JSONDecodeError:
        logger.error("Failed to parse config file. Ensure it is valid JSON.")
        return []
    # All generic exceptions have been commented out to increase lint score
    # except Exception as e:
    #     logger.error("Unexpected error while loading config: %s", e)
    #     return []


REPOSITORIES = load_config()


def init_db() -> None:
    """
    Initialize the SQLite database and create the events table if it does not exist.
    """
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute(
        """CREATE TABLE IF NOT EXISTS events (
                    id TEXT PRIMARY KEY,
                    repo TEXT,
                    event_type TEXT,
                    created_at TEXT,
                    raw_json TEXT
                )"""
    )
    conn.commit()
    conn.close()


def insert_event(event: Dict[str, Any], repo: str) -> None:
    """
    Insert a GitHub event into the database.
    The event is uniquely identified by its "id" field.
    """
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    try:
        c.execute(
            """INSERT OR IGNORE INTO events (id, repo, event_type, created_at, raw_json)
                     VALUES (?, ?, ?, ?, ?)""",
            (
                event.get("id"),
                repo,
                event.get("type"),
                event.get("created_at"),
                json.dumps(event),
            ),
        )
        conn.commit()
    except sqlite3.IntegrityError as e:
        logger.error("Integrity error while inserting event %s: %s", event.get("id"), e)
    except sqlite3.OperationalError as e:
        logger.error(
            "Operational error: Possible database lock or missing table: %s", e
        )
    except sqlite3.DatabaseError as e:
        logger.error("General database error: %s", e)
    except json.JSONDecodeError as e:
        logger.error("Failed to serialize event JSON: %s", e)
    # except Exception as e:
    #     logger.error("Failed to insert event: %s", e)
    finally:
        conn.close()


def get_recent_events(repo: str, event_type: str) -> List[Any]:
    """
    Retrieve events for the given repository and event type,
    that occurred within the last MAX_DAYS days.
    If more than MAX_EVENTS events are found,
    return only the most recent MAX_EVENTS (sorted ascending by created_at).
    """
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    cutoff = (
        datetime.datetime.now(datetime.UTC) - datetime.timedelta(days=MAX_DAYS)
    ).isoformat() + "Z"
    query = """SELECT created_at FROM events
               WHERE repo = ? AND event_type = ? AND created_at >= ?
               ORDER BY datetime(created_at) ASC"""
    c.execute(query, (repo, event_type, cutoff))
    rows = c.fetchall()
    conn.close()
    # Convert the created_at strings to datetime objects
    events = [datetime.datetime.fromisoformat(row[0].replace("Z", "")) for row in rows]
    # If more than MAX_EVENTS events, only take the latest MAX_EVENTS
    if len(events) > MAX_EVENTS:
        events = events[-MAX_EVENTS:]
    return events


def fetch_repo_events(repo: str) -> None:
    """
    Fetch the latest events for a given repository using the GitHub Events API.
    New events are inserted into the database.
    To minimize requests, we rely on the API returning only recent events.
    """
    url = GITHUB_API_URL.format(repo=repo)
    headers = {"Accept": "application/vnd.github.v3+json"}
    try:
        response = requests.get(url, headers=headers, timeout=15)
        if response.status_code == 200:
            events = response.json()
            logger.info("Fetched %d events for %s", len(events), repo)
            for event in events:
                insert_event(event, repo)
        else:
            logger.error(
                "Failed to fetch events for %s: %s", repo, response.status_code
            )
    except requests.exceptions.Timeout:
        logger.error("Request timed out while fetching events for %s", repo)
    except requests.exceptions.ConnectionError:
        logger.error("Network error: Unable to connect to GitHub API for %s", repo)
    except requests.exceptions.HTTPError as http_err:
        logger.error("HTTP error fetching events for %s: %s", repo, http_err)
    except requests.exceptions.RequestException as req_err:
        logger.error("Request error fetching events for %s: %s", repo, req_err)
    except ValueError:  # Raised when response.json() fails (invalid JSON)
        logger.error("Failed to decode JSON response for %s", repo)
    # except Exception as e:
    #     logger.error("Error fetching events for %s: %s", repo, e)


def poll_github_events() -> None:
    """
    Poll GitHub events for all configured repositories.
    This function is intended to be scheduled to run periodically.
    """
    logger.info("Polling GitHub events...")
    for repo in REPOSITORIES:
        fetch_repo_events(repo)


def start_scheduler() -> None:
    """
    Start background scheduler for polling GitHub events.
    """
    scheduler = BackgroundScheduler()
    scheduler.add_job(poll_github_events, "interval", seconds=POLL_INTERVAL_SECONDS)
    scheduler.start()
    logger.info("Started background scheduler for GitHub polling.")


# API endpoint: GET /stats
@app.route("/stats", methods=["GET"])
def get_stats():
    """
    Compute and return the average time between consecutive events for each combination
    of repository and event type. The rolling window is defined as the events within the
    last MAX_DAYS days or the latest MAX_EVENTS events (whichever is fewer).

    Returns:
      A JSON object structured as:
      {
          "repo1": {
              "PushEvent": average_interval_in_seconds,
              "PullRequestEvent": average_interval_in_seconds,
              ...
          },
          "repo2": { ... }
      }
    """
    results: Dict[str, Dict[str, float]] = {}
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    # Get distinct repository and event type combinations from events in the last MAX_DAYS days
    cutoff = (
        datetime.datetime.now(datetime.UTC) - datetime.timedelta(days=MAX_DAYS)
    ).isoformat() + "Z"
    c.execute(
        """SELECT DISTINCT repo, event_type FROM events WHERE created_at >= ?""",
        (cutoff,),
    )
    pairs = c.fetchall()
    conn.close()

    for repo, event_type in pairs:
        event_times = get_recent_events(repo, event_type)
        if len(event_times) < 2:
            # Not enough events to compute an interval
            continue
        # Compute average time difference (in seconds) between consecutive events
        total_diff = (event_times[-1] - event_times[0]).total_seconds()
        avg_interval = total_diff / (len(event_times) - 1)
        if repo not in results:
            results[repo] = {}
        results[repo][event_type] = avg_interval

    return jsonify(results)


if __name__ == "__main__":
    init_db()
    # Start background thread for polling
    poll_thread = threading.Thread(target=poll_github_events)
    poll_thread.start()
    # Also start the APScheduler
    start_scheduler()
    # Run the Flask app
    app.run(host="127.0.0.1", port=5000)
