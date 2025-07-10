
# Phabricator Tasks Reporter

This script allows you to fetch tasks from Phabricator by project, filter them by date, status, and team members, and export the results to CSV.

## Features
- Search for tasks in Phabricator by project and period
- Filter tasks by status and owner
- Display team and task information in the console
- Export results to a CSV file

## Requirements
- Python 3.8+
- requests

## Installing dependencies

```sh
pip install requests
```

## Configuration

1. Create a `.env.fish` file (or export environment variables in another way) with the following variables:

```fish
set -gx API_TOKEN "<your_phabricator_api_token>"
set -gx PHABRICATOR_URL "https://your.phabricator.url"
set -gx DEVTEAM_MEMBERS "user1, user2, user3"
```

2. Make sure the environment variables are available in your shell session.

## Usage

```sh
python client.py \
  --start-date 2024-06-01 \
  --end-date 2024-06-30 \
  --projects "Project1,Project2" \
  --statuses "open,resolved" \
  --csv report.csv
```

- `--start-date` — start date (format YYYY-MM-DD)
- `--end-date` — end date (format YYYY-MM-DD)
- `--projects` — comma-separated list of project names
- `--statuses` — comma-separated list of task statuses (default: open,resolved)
- `--csv` — (optional) path to CSV export file

## Example output

```
Getting PHIDs of team members...
Getting project PHIDs...['Project1', 'Project2']
Found projects: ['PHID-PROJ-xxxx', ...]

Searching tasks for period: 2024-06-01 - 2024-06-30

Found tasks: 10
Found tasks for the team: 5

Team members:
  user1: PHID-USER-xxxx
  ...

Team tasks:
---------------
T123: Fix bug in module
  Status: resolved
  Priority: High
  Created: 2024-06-10 12:00:00
  Modified: 2024-06-15 09:00:00
  URL: https://your.phabricator.url/T123
  Author: user1
  Owner: user2
...
```

## License

MIT License
