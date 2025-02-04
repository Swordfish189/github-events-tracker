# GitHub Events Tracker

## Overview

This application tracks events from up to a given number of GitHub repositories using the GitHub Events API. It collects events and stores them locally in a SQLite database to minimize API requests and to retain data across restarts. The REST API provides statistics based on a rolling window defined by either a given number of days or a given number of events (whichever is less). Specifically, for each repository and event type combination, the API returns the average time (in seconds) between consecutive events.

## Features

- **Configurable Repositories:** Monitor up to a given number repositories by listing them in `config.json`.
- **Rolling Window Statistics:** For each repository and event type, statistics are computed from events in the last given number of days (or the latest given number of events, if fewer).
- **REST API Endpoint:** A GET endpoint at `/stats` returns the average time interval between events.
- **Data Persistence:** All fetched events are stored in a local SQLite database (`events.db`), ensuring data is retained between restarts.
- **Efficient GitHub API Usage:** The application minimizes requests by periodically polling and ignoring duplicate events.

## Assumptions

- The GitHub Events API endpoint `https://api.github.com/repos/{repo}/events` is used without authentication (which has lower rate limits). In a production setting, you might consider using authenticated requests.
- The rolling window is defined as events that occurred in the last {7} days. If more than {500} events occur within that period, only the most recent {500} are used for the statistics.
- Event timestamps are assumed to be in ISO 8601 format (as provided by GitHub) and are stored as UTC.
- For simplicity, error handling is basic. In production, you might add retries, exponential backoff, and more robust error logging.
- The application uses APScheduler to poll GitHub every {60} seconds.

## Setup and Running

### Prerequisites

- Python 3.8 or higher
- `pip` (Python package installer)

### Installation

1. **Clone the repository or download the project files.**

2. **Install dependencies:**

   ```bash
   pip install -r requirements.txt
   
3. **Configure Repositories:**

   Edit the config.json file to list the GitHub repositories you wish to monitor. For example:
   ```json
   {
     "repositories": [
       "torvalds/linux",
       "psf/requests",
       "..."
     ]
   }
   ```
   
4. **Run the app:**

   ```bash
   python .\app.py

5. **Check results:**

   ```browser
   http://127.0.0.1:5000/stats