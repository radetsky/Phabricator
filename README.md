# Phabricator Tasks Reporter

A CLI tool for syncing Phabricator tasks to a local SQLite database and generating reports. Sync once, query locally — fast reports without API calls.

## Features

- **Local SQLite database** — sync tasks, users, and projects from Phabricator
- **Incremental sync** — only fetch modified data after initial sync
- **Task reports** — filter by project, status, date range, and team members
- **Lifecycle analysis** — track task duration from creation to resolution
- **Team statistics** — tasks resolved/opened per member, average completion time

## Requirements

- Python 3.10+
- Access to a Phabricator instance with API token

## Installation

```bash
pip install -r requirements.txt
```

## Configuration

Create a `.env` file (or export environment variables):

```bash
export API_TOKEN="api-xxxxxxxxxxxxxxxxxxxx"
export PHABRICATOR_URL="https://your.phabricator.url"
export DEVTEAM_MEMBERS="user1, user2, user3"
```

Source it before running commands:

```bash
source .env
```

Optional: customize database location (default: `~/.phabricator/data.db`):

```bash
export PHABRICATOR_DB_PATH="/path/to/custom/database.db"
```

## Quick Start

```bash
# 1. Sync all data from Phabricator
python cli.py sync --full

# 2. Check sync status
python cli.py status

# 3. Generate a report
python cli.py report --start-date 2024-01-01 --end-date 2024-12-31 --team
```

## Commands

### `sync` — Sync data from Phabricator

```bash
# Full sync (all users, projects, tasks)
python cli.py sync --full

# Incremental sync (only changes since last sync)
python cli.py sync

# Sync specific entities
python cli.py sync --users
python cli.py sync --projects
python cli.py sync --tasks

# Sync tasks modified since a specific date
python cli.py sync --tasks --since 2024-06-01
```

### `report` — Generate task reports

```bash
# All tasks in date range
python cli.py report --start-date 2024-01-01 --end-date 2024-12-31

# Filter by team members (from DEVTEAM_MEMBERS)
python cli.py report --start-date 2024-01-01 --end-date 2024-12-31 --team

# Filter by project
python cli.py report --start-date 2024-01-01 --end-date 2024-12-31 --projects "ProjectA,ProjectB"

# Filter by status
python cli.py report --start-date 2024-01-01 --end-date 2024-12-31 --statuses "open"

# Export to CSV
python cli.py report --start-date 2024-01-01 --end-date 2024-12-31 --team --csv tasks.csv
```

**Output fields:** id, title, projects, status, priority, created, modified, url, author, owner

### `lifecycle` — Task duration analysis

```bash
# Resolved tasks with duration info
python cli.py lifecycle --start-date 2024-01-01 --end-date 2024-12-31 --team

# Single task details
python cli.py lifecycle --task T123

# Export to CSV
python cli.py lifecycle --start-date 2024-01-01 --end-date 2024-12-31 --csv lifecycle.csv
```

**Output fields:** id, title, status, priority, created, modified, closed, url, author, owner, duration_days, duration_hours, duration_formatted

### `stats` — Team and project statistics

```bash
# All statistics (team + projects + duration)
python cli.py stats --start-date 2024-01-01 --end-date 2024-12-31

# Team member statistics only
python cli.py stats --start-date 2024-01-01 --end-date 2024-12-31 --type team

# Average duration by project
python cli.py stats --start-date 2024-01-01 --end-date 2024-12-31 --type projects

# Average duration by team member
python cli.py stats --start-date 2024-01-01 --end-date 2024-12-31 --type duration

# Project stats filtered by team members only
python cli.py stats --start-date 2024-01-01 --end-date 2024-12-31 --type projects --team
```

**Statistics types:**

| Type | Description |
|------|-------------|
| `team` | Tasks resolved, open, authored, and owned per team member |
| `projects` | Average task duration by project (days, min/max hours) |
| `duration` | Average task duration by team member |
| `all` | All three reports (default) |

### `status` — Show sync status

```bash
python cli.py status
```

Shows: Phabricator URL, team members, database path, last sync time per entity type.

## Example Output

### Team Statistics

```
======================================================================
TEAM MEMBER STATISTICS
Period: 2024-01-01 - 2024-12-31
======================================================================

Member          Resolved   Open     Authored   Owned
------------------------------------------------------------
alice           83         49       92         89
bob             25         19       25         27
charlie         15         23       121        24
------------------------------------------------------------
TOTAL           123        91       238        140
```

### Average Duration by Project

```
======================================================================
AVERAGE TASK DURATION BY PROJECT
Period: 2024-01-01 - 2024-12-31
======================================================================

Project                        Tasks    Avg Days   Min Hrs    Max Hrs
----------------------------------------------------------------------
backend                        190      20.6       0.2        500.3
frontend                       150      41.8       0.0        320.5
infrastructure                 137      34.6       0.2        890.8
```

## Architecture

```
phabricator/
├── client.py           # Phabricator Conduit API client
├── database/
│   ├── models.py       # SQLAlchemy models
│   └── connection.py   # DB session management
├── sync/
│   └── syncer.py       # Sync from API to local DB
└── reports/
    ├── task_report.py  # Task reports
    ├── lifecycle.py    # Duration analysis
    └── stats.py        # Team/project statistics

cli.py                  # Main CLI entry point
```

## License

MIT License
