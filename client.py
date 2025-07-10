import requests
from datetime import datetime
from typing import List, Dict, Any
import os
import argparse
import csv


class PhabricatorClient:
    def __init__(self, base_url: str, api_token: str):
        """
        Initialize Phabricator API client

        Args:
            base_url: URL of the Phabricator instance (e.g., 'https://phabricator.example.com')
            api_token: API token for authentication
        """
        self.base_url = base_url.rstrip("/")
        self.api_token = api_token
        self.session = requests.Session()

    def _make_request(self, method: str, params: Dict[str, Any]) -> Dict[str, Any]:
        """
        Make a request to the API

        Args:
            method: API method name (e.g., 'maniphest.search')
            params: Request parameters

        Returns:
            API response in JSON format
        """
        url = f"{self.base_url}/api/{method}"

        # Add API token
        params["api.token"] = self.api_token

        try:
            response = self.session.post(url, data=params)
            response.raise_for_status()

            result = response.json()

            if result.get("error_code"):
                raise Exception(
                    f"API Error: {result.get('error_info', 'Unknown error')}"
                )

            return result

        except requests.exceptions.RequestException as e:
            raise Exception(f"Request failed: {str(e)}")

    def get_projects(
        self, project_names: List[str] | None = None
    ) -> List[Dict[str, Any]]:
        """
        Get a list of projects

        Args:
            project_names: List of project names for filtering

        Returns:
            List of projects with their PHID
        """
        params = {}

        if project_names:
            for i, name in enumerate(project_names):
                params["constraints[name]"] = name

        response = self._make_request("project.search", params)
        return response.get("result", {}).get("data", [])

    def get_project_phids(self, project_names: List[str]) -> List[str]:
        """
        Get project PHIDs by their names

        Args:
            project_names: List of project names

        Returns:
            List of project PHIDs
        """
        phids = []

        for project_name in project_names:
            params = {"constraints[name]": project_name}
            response = self._make_request("project.search", params)

            projects = response.get("result", {}).get("data", [])
            for project in projects:
                if project.get("fields", {}).get("name") == project_name:
                    phids.append(project["phid"])
                    break

        return phids

    def get_tasks_by_projects_and_period(
        self,
        project_phids: List[str],
        start_date: datetime,
        end_date: datetime,
        use_modified_date: bool = False,
        statuses: List[str] | None = None,
        limit: int = 100,
    ) -> List[Dict[str, Any]]:
        """
        Get tasks by projects for a specific period

        Args:
            project_phids: List of project PHIDs
            start_date: Start of the period
            end_date: End of the period
            use_modified_date: Whether to use modified date instead of created date
            statuses: List of statuses (open, resolved, wontfix, invalid, duplicate)
            limit: Maximum number of results

        Returns:
            List of tasks
        """
        params = {"order": "created", "limit": str(limit)}

        # Add projects
        for i, phid in enumerate(project_phids):
            params[f"constraints[projects][{i}]"] = phid

        # Add time period
        start_timestamp = int(start_date.timestamp())
        end_timestamp = int(end_date.timestamp())

        if use_modified_date:
            params["constraints[modifiedStart]"] = str(start_timestamp)
            params["constraints[modifiedEnd]"] = str(end_timestamp)
        else:
            params["constraints[createdStart]"] = str(start_timestamp)
            params["constraints[createdEnd]"] = str(end_timestamp)

        # Add statuses
        if statuses:
            for i, status in enumerate(statuses):
                params[f"constraints[statuses][{i}]"] = status

        all_tasks = []
        cursor = None

        while True:
            if cursor:
                params["after"] = cursor

            response = self._make_request("maniphest.search", params)
            result = response.get("result", {})

            tasks = result.get("data", [])
            all_tasks.extend(tasks)

            # Check if there are more pages
            cursor_info = result.get("cursor", {})
            if not cursor_info.get("after"):
                break

            cursor = cursor_info["after"]

            # If limit reached, exit
            if len(all_tasks) >= limit:
                break

        return all_tasks[:limit]

    def format_task_info(self, task: Dict[str, Any]) -> Dict[str, Any]:
        """
        Format task information

        Args:
            task: Raw task data from API

        Returns:
            Formatted task data
        """
        fields = task.get("fields", {})

        return {
            "id": task.get("id"),
            "phid": task.get("phid"),
            "title": fields.get("name", ""),
            "status": fields.get("status", {}).get("name", ""),
            "priority": fields.get("priority", {}).get("name", ""),
            "created": datetime.fromtimestamp(fields.get("dateCreated", 0)),
            "modified": datetime.fromtimestamp(fields.get("dateModified", 0)),
            "author": fields.get("authorPHID", ""),
            "owner": fields.get("ownerPHID", ""),
            "url": f"{self.base_url}/T{task.get('id')}",
        }

    def get_user_phids(self, usernames: List[str]) -> Dict[str, str]:
        """
        Get user PHIDs by their usernames

        Args:
            usernames: List of user usernames

        Returns:
            Dictionary {username: PHID}
        """
        user_phids = {}

        for username in usernames:
            try:
                # Try different search options

                # Option 1: Search by usernames
                params = {"constraints[usernames][0]": username}
                response = self._make_request("user.search", params)
                users = response.get("result", {}).get("data", [])

                if users:
                    user_phids[username] = users[0]["phid"]
                    continue

                # Option 2: Search via phid.lookup (if username is actually a PHID)
                if username.startswith("PHID-"):
                    user_phids[username] = username
                    continue

                # Option 3: Search via phid.lookup with username
                try:
                    params = {"names[0]": username}
                    response = self._make_request("phid.lookup", params)
                    lookup_result = response.get("result", {})
                    if username in lookup_result:
                        user_phids[username] = lookup_result[username]["phid"]
                        continue
                except Exception:
                    pass

                # Option 4: Search by realName (if it's a full name)
                params = {}
                response = self._make_request("user.search", params)
                all_users = response.get("result", {}).get("data", [])

                for user in all_users:
                    fields = user.get("fields", {})
                    if (
                        fields.get("username") == username
                        or fields.get("realName") == username
                    ):
                        user_phids[username] = user["phid"]
                        break

                if username not in user_phids:
                    print(f"Warning: User {username} not found.")

            except Exception as e:
                print(f"Error searching for user {username}: {e}")

        return user_phids

    def get_all_users(self) -> Dict[str, str]:
        """
        Отримання всіх доступних користувачів

        Returns:
            Словник {phid: username}
        """
        all_users_dict = {}
        cursor = None

        while True:
            params = {"limit": "100", "order": "newest"}

            if cursor:
                params["after"] = cursor

            try:
                response = self._make_request("user.search", params)
                result = response.get("result", {})

                users = result.get("data", [])

                for user in users:
                    phid = user.get("phid")
                    fields = user.get("fields", {})
                    username = fields.get("username")

                    if phid and username:
                        all_users_dict[phid] = username

                # Перевіряємо, чи є ще сторінки
                cursor_info = result.get("cursor", {})
                if not cursor_info.get("after"):
                    break

                cursor = cursor_info["after"]

            except Exception as e:
                print(f"Помилка при отриманні користувачів: {e}")
                break

        return all_users_dict

    def get_all_users_detailed(self) -> List[Dict[str, Any]]:
        """
        Отримання детальної інформації про всіх доступних користувачів

        Returns:
            Список словників з детальною інформацією про користувачів
        """
        all_users = []
        cursor = None

        while True:
            params = {"limit": "100", "order": "username"}

            if cursor:
                params["after"] = cursor

            try:
                response = self._make_request("user.search", params)
                result = response.get("result", {})

                users = result.get("data", [])

                for user in users:
                    phid = user.get("phid")
                    fields = user.get("fields", {})

                    user_info = {
                        "phid": phid,
                        "username": fields.get("username"),
                        "realName": fields.get("realName"),
                        "roles": fields.get("roles", []),
                        "dateCreated": datetime.fromtimestamp(
                            fields.get("dateCreated", 0)
                        )
                        if fields.get("dateCreated")
                        else None,
                        "isDisabled": fields.get("isDisabled", False),
                        "isBot": fields.get("isBot", False),
                        "isMailingList": fields.get("isMailingList", False),
                        "isSystemAgent": fields.get("isSystemAgent", False),
                    }

                    all_users.append(user_info)

                # Перевіряємо, чи є ще сторінки
                cursor_info = result.get("cursor", {})
                if not cursor_info.get("after"):
                    break

                cursor = cursor_info["after"]

            except Exception as e:
                print(f"Помилка при отриманні користувачів: {e}")
                break

        return all_users


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
        required=True,
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
    PROJECT_NAMES = [name.strip() for name in args.projects.split(",") if name.strip()]

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
    DEVTEAM_MEMBERS_PHIDS = {}
    DEVTEAM_MEMBERS_PHIDS_NAMES = {}

    # Create client
    client = PhabricatorClient(PHABRICATOR_URL, API_TOKEN)

    try:
        # Get all users
        all_users = client.get_all_users()

        # Fill in PHIDs of team members
        print("Getting PHIDs of team members...")
        DEVTEAM_MEMBERS_PHIDS = client.get_user_phids(DEVTEAM_MEMBERS)

        # Fill in dictionary with member names
        for username, phid in DEVTEAM_MEMBERS_PHIDS.items():
            DEVTEAM_MEMBERS_PHIDS_NAMES[phid] = username

        # Get project PHIDs
        print(f"Getting project PHIDs...{PROJECT_NAMES}")
        project_phids = client.get_project_phids(PROJECT_NAMES)
        print(f"Found projects: {project_phids}")

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
            limit=50,
        )

        print(f"\nFound tasks: {len(tasks)}")

        # Filter tasks by team members
        tasks = [
            task
            for task in tasks
            if task.get("fields", {}).get("ownerPHID") in DEVTEAM_MEMBERS_PHIDS.values()
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
        for username, phid in DEVTEAM_MEMBERS_PHIDS.items():
            print(f"  {username}: {phid}")

        print("\nTeam tasks:")
        print("---------------")

        # Print information about tasks
        for task in tasks:
            task_info = client.format_task_info(task)
            print(f"\nT{task_info['id']}: {task_info['title']}")
            print(f"  Status: {task_info['status']}")
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
