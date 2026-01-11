import argparse
import csv

from datetime import datetime
from pprint import pprint

from phabricator.client import PhabricatorClient, PhabricatorConfiguration

def main():
    parser = argparse.ArgumentParser(description="Phabricator tasks report")
    parser.add_argument(
        "--start-date", type=str, required=True, help="Start date in YYYY-MM-DD format"
    )
    parser.add_argument(
        "--end-date", type=str, required=True, help="End date in YYYY-MM-DD format"
    )
    parser.add_argument("--task", type=str, help="Task ID to fetch details")
    parser.add_argument("--csv", type=str, help="Export tasks to CSV file")

    args = parser.parse_args()

    phconf = PhabricatorConfiguration()
    phconf.read_from_env()
    client = PhabricatorClient(phconf)
    client.get_members_phids()

    if args.task:
        # Fetch details for a specific task
        task_id = args.task
        task_details = client.calculate_task_duration(task_id)
        pprint(task_details)
        return

    try:
        start_date = datetime.strptime(args.start_date, "%Y-%m-%d")
        end_date = datetime.strptime(args.end_date, "%Y-%m-%d")
    except ValueError:
        raise Exception("Invalid date format. Please use YYYY-MM-DD.")

    # Validate date range
    if start_date > end_date:
        raise Exception("Start date cannot be later than end date.")

    # Fetch tasks within the date range and status='resolved'
    tasks = client.get_tasks_by_date_range(start_date, end_date, status='resolved')
    tasks = client.filter_tasks_by_members(tasks, "owner")
    all_users = client.get_all_users()
    # Print information about tasks and collect task_details for each task
    task_details_map = {}
    for task in tasks:
        task_info = client.format_task_info(task)
        details = client.calculate_task_duration(task_info["id"])
        task_details_map[task_info["id"]] = details
        print(f"\nT{task_info['id']}: {task_info['title']}")
        print(f"  Status: {task_info['status']}")
        print(f"  Created: {task_info['created']}")
        print(f"  Modified: {task_info['modified']}")
        print(f"  URL: {task_info['url']}")
        print(f"  Author: {all_users.get(task_info['author'], task_info['author'])}")
        print(f"  Owner: {all_users.get(task_info['owner'], task_info['owner'])}")
        print(f"  Duration: {details['duration_days']}")
        print(f"  Duration formatted: {details['duration_formatted']}")
        print(f"  Duration hours: {details['duration_hours']}")

    # Export to CSV if requested
    if args.csv:
        with open(args.csv, mode="w", newline="") as csv_file:
            fieldnames = [
                "id",
                "title",
                "status",
                "priority",
                "created",
                "modified",
                "url",
                "author",
                "owner",
                "duration_days",
                "duration_formatted",
                "duration_hours",
            ]
            writer = csv.DictWriter(csv_file, fieldnames=fieldnames)

            writer.writeheader()
            for task in tasks:
                task_info = client.format_task_info(task)
                details = task_details_map[task_info["id"]]
                writer.writerow(
                    {
                        "id": task_info["id"],
                        "title": task_info["title"],
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
                        "duration_days": details["duration_days"],
                        "duration_formatted": details["duration_formatted"],
                        "duration_hours": details["duration_hours"],
                    }
                )


if __name__ == "__main__":
    main()
