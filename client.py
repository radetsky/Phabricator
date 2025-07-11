from datetime import datetime
import os
import argparse
import csv

from phabricator.client import PhabricatorClient

def main():

    parser = argparse.ArgumentParser(description="Phabricator tasks report")
    parser.add_argument("--csv", type=str, help="Export tasks to CSV file")
    parser.add_argument(
        "--start-date", type=str, required=True, help="Start date in YYYY-MM-DD format"
    )
    parser.add_argument(
        "--end-date", type=str, required=True, help="End date in YYYY-MM-DD format"
    )
    parser.add_argument(
        "--projects",
        type=str,
        help="Comma-separated list of project names",
    )
    parser.add_argument(
        "--statuses",
        type=str,
        default="open,resolved",
        help="Comma-separated list of task statuses (default: 'open,resolved')",
    )

    args = parser.parse_args()

    TASK_STATUSES = [
        status.strip() for status in args.statuses.split(",") if status.strip()
    ]

    # Parse project names from argument
    if args.projects:
        PROJECT_NAMES = [name.strip() for name in args.projects.split(",") if name.strip()]
    else:
        PROJECT_NAMES = []

    # Parse dates from arguments
    try:
        start_date = datetime.strptime(args.start_date, "%Y-%m-%d")
        end_date = datetime.strptime(args.end_date, "%Y-%m-%d")
    except ValueError:
        raise Exception("Invalid date format. Please use YYYY-MM-DD.")

    # Configuration
    PHABRICATOR_URL = os.environ.get("PHABRICATOR_URL")
    if not PHABRICATOR_URL:
        raise Exception("PHABRICATOR_URL environment variable is not set.")
    API_TOKEN = os.environ.get("API_TOKEN")
    if not API_TOKEN:
        raise Exception("API_TOKEN environment variable is not set.")
    DEVTEAM_MEMBERS = os.environ.get("DEVTEAM_MEMBERS", "").split(",")
    DEVTEAM_MEMBERS = [name.strip() for name in DEVTEAM_MEMBERS if name.strip()]

    members_phids = {}
    members_phids_names = {}

    # Create client
    client = PhabricatorClient(PHABRICATOR_URL, API_TOKEN)
    client.all_projects = client.get_all_projects()
    print(f"Found {len(client.all_projects)} projects in Phabricator.")

    try:
        all_users = client.get_all_users()
        print("Getting PHIDs of team members...")
        members_phids = client.get_user_phids(DEVTEAM_MEMBERS)

        # Fill in dictionary with member names
        for username, phid in members_phids.items():
            members_phids_names[phid] = username

        # Get project PHIDs
        project_phids = client.get_project_phids(PROJECT_NAMES)
        print("\nSelected projects:")
        if not project_phids:
            print("  (No projects selected)")
        else:
            for phid in project_phids:
                project_name = client.all_projects.get(phid, {}).get("name", phid)
                print(f"  {project_name}: {phid}")

        print(
            f"\nSearching tasks for period: {start_date.strftime('%Y-%m-%d')} - {end_date.strftime('%Y-%m-%d')}"
        )

        # Get tasks
        tasks = client.get_tasks_by_projects_and_period(
            project_phids=project_phids,
            start_date=start_date,
            end_date=end_date,
            use_modified_date=True,  # Search by modification date (activation)
            statuses=TASK_STATUSES,
        )

        print(f"\nFound tasks: {len(tasks)}")

        # Filter tasks by team members
        tasks = [
            task
            for task in tasks
            if (
            task.get("fields", {}).get("ownerPHID") in members_phids.values()
            or task.get("fields", {}).get("authorPHID") in members_phids.values()
            )
        ]

        print(f"Found tasks for the team: {len(tasks)}")

        if not tasks:
            print("No tasks to display.")
            return

        # Sort tasks by modification date
        tasks.sort(
            key=lambda x: x.get("fields", {}).get("dateModified", 0), reverse=True
        )

        print("\nTeam tasks:")
        print("---------------")

        # Print general information
        print(
            f"Found {len(tasks)} tasks for the team for the period from {start_date.strftime('%Y-%m-%d')} to {end_date.strftime('%Y-%m-%d')}."
        )

        # Print information about team members
        print("\nTeam members:")
        for username, phid in members_phids.items():
            print(f"  {username}: {phid}")

        print("\nTeam tasks:")
        print("---------------")

        # Print information about tasks
        for task in tasks:
            task_info = client.format_task_info(task)
            print(f"\nT{task_info['id']}: {task_info['title']}")
            print(f"  Status: {task_info['status']}")
            print(f"  Projects: {', '.join(task_info['projects'])}")
            print(f"  Priority: {task_info['priority']}")
            print(f"  Created: {task_info['created']}")
            print(f"  Modified: {task_info['modified']}")
            print(f"  URL: {task_info['url']}")
            print(
                f"  Author: {all_users.get(task_info['author'], task_info['author'])}"
            )
            print(f"  Owner: {all_users.get(task_info['owner'], task_info['owner'])}")

        # Export to CSV if requested
        if args.csv:
            with open(args.csv, mode="w", newline="") as csv_file:
                fieldnames = [
                    "id",
                    "title",
                    "projects",
                    "status",
                    "priority",
                    "created",
                    "modified",
                    "url",
                    "author",
                    "owner",
                ]
                writer = csv.DictWriter(csv_file, fieldnames=fieldnames)

                writer.writeheader()
                for task in tasks:
                    task_info = client.format_task_info(task)
                    writer.writerow(
                        {
                            "id": task_info["id"],
                            "title": task_info["title"],
                            "projects": ", ".join(task_info["projects"]),
                            "status": task_info["status"],
                            "priority": task_info["priority"],
                            "created": task_info["created"],
                            "modified": task_info["modified"],
                            "url": task_info["url"],
                            "author": all_users.get(
                                task_info["author"], task_info["author"]
                            ),
                            "owner": all_users.get(
                                task_info["owner"], task_info["owner"]
                            ),
                        }
                    )

    except Exception as e:
        print(f"Error: {e}")


if __name__ == "__main__":
    main()
