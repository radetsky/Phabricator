import requests
from datetime import datetime
from typing import List, Dict, Any


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
        self.all_projects = {}

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

    def paginated_request(self, method: str, params: dict):
        """
        Make a paginated request to the API

        Args:
            method: API method name
            params: Request parameters

        Yields:
            Individual items from the paginated response
        """
        cursor = None
        while True:
            if cursor:
                params["after"] = cursor
            response = self._make_request(method, params)
            result = response.get("result", {})
            yield from result.get("data", [])
            cursor_info = result.get("cursor", {})
            if not cursor_info.get("after"):
                break
            cursor = cursor_info["after"]

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

    def get_all_projects(self) -> dict:
        """
        Retrieves all projects from Phabricator.

        Returns:
            dict: A dictionary where each key is a project's PHID and the value is a dictionary of the project's fields.
        """
        params = {}
        print("Getting all projects...")

        response = self._make_request("project.search", params)
        projects = response.get("result", {}).get("data", [])
        result = {}
        for project in projects:
            fields = project.get("fields", {})
            result[project.get("phid")] = fields

        return result

    def get_project_phids(self, project_names: List[str] = []) -> List[str]:
        """
        Get project PHIDs by their names

        Args:
            project_names: List of project names

        Returns:
            List of project PHIDs
        """
        phids = []

        if not project_names:
            return list(self.all_projects.keys())

        for project_name in project_names:
            for phid, project in self.all_projects.items():
                if project.get("name", "") == project_name:
                    phids.append(phid)
                    break

        return phids

    def get_tasks_by_projects_and_period(
        self,
        project_phids: List[str],
        start_date: datetime,
        end_date: datetime,
        use_modified_date: bool = False,
        statuses: List[str] = ["open", "resolved", "wontfix", "invalid", "duplicate"],
        limit: int = 100,
        search_mode: str = "any",  # 'any' або 'all'
    ) -> List[Dict[str, Any]]:
        """
        Get tasks by projects for a specific period

        Args:
            project_phids: List of project PHIDs
            start_date: Start of the period
            end_date: End of the period
            use_modified_date: Whether to use modification date instead of creation date
            statuses: List of statuses (open, resolved, wontfix, invalid, duplicate)
            limit: Maximum number of results
            search_mode: 'any' - tasks from any project, 'all' - tasks from all projects at once

        Returns:
            List of tasks
        """
        all_tasks = []
        if search_mode == "any":
            any_tasks = {}

            for project_phid in project_phids:
                tasks = self._get_tasks_single_project(
                    project_phid,
                    start_date,
                    end_date,
                    use_modified_date,
                    statuses,
                    limit,
                )
                for task in tasks:
                    task_id = task.get("id")
                    task = any_tasks.get(task_id, task)
                    current_project_name = self.all_projects.get(project_phid, {}).get(
                        "name", project_phid
                    )
                    project_names = task.get("projects", [])
                    if current_project_name not in project_names:
                        project_names.append(current_project_name)
                        task["projects"] = project_names
                    any_tasks[task_id] = task

            all_tasks.extend(any_tasks.values())

        else:
            all_tasks = self._get_tasks_multiple_projects(
                project_phids, start_date, end_date, use_modified_date, statuses, limit
            )

        all_tasks.sort(
            key=lambda x: x.get("fields", {}).get("dateCreated", 0), reverse=True
        )

        return all_tasks

    def _get_tasks_single_project(
        self,
        project_phid: str,
        start_date: datetime,
        end_date: datetime,
        use_modified_date: bool = False,
        statuses: List[str] = ["open", "resolved", "wontfix", "invalid", "duplicate"],
        limit: int = 100,
    ) -> List[Dict[str, Any]]:
        """
        Get tasks for a single project
        """
        params = {
            "order": "created",
            "limit": str(limit),
            "constraints[projects][0]": project_phid,
        }

        start_timestamp = int(start_date.timestamp())
        end_timestamp = int(end_date.timestamp())

        if use_modified_date:
            params["constraints[modifiedStart]"] = str(start_timestamp)
            params["constraints[modifiedEnd]"] = str(end_timestamp)
        else:
            params["constraints[createdStart]"] = str(start_timestamp)
            params["constraints[createdEnd]"] = str(end_timestamp)

        if statuses:
            for i, status in enumerate(statuses):
                params[f"constraints[statuses][{i}]"] = status

        tasks = []
        for task in self.paginated_request("maniphest.search", params):
            task["project_phid"] = project_phid
            tasks.append(task)

        return tasks

    def _get_tasks_multiple_projects(
        self,
        project_phids: List[str],
        start_date: datetime,
        end_date: datetime,
        use_modified_date: bool = False,
        statuses: List[str] = ["open", "resolved", "wontfix", "invalid", "duplicate"],
        limit: int = 100,
    ) -> List[Dict[str, Any]]:
        """
        Get tasks for multiple projects (AND logic)
        """
        params = {"order": "created", "limit": str(limit)}

        for i, phid in enumerate(project_phids):
            params[f"constraints[projects][{i}]"] = phid

        start_timestamp = int(start_date.timestamp())
        end_timestamp = int(end_date.timestamp())

        if use_modified_date:
            params["constraints[modifiedStart]"] = str(start_timestamp)
            params["constraints[modifiedEnd]"] = str(end_timestamp)
        else:
            params["constraints[createdStart]"] = str(start_timestamp)
            params["constraints[createdEnd]"] = str(end_timestamp)

        if statuses:
            for i, status in enumerate(statuses):
                params[f"constraints[statuses][{i}]"] = status

        all_tasks = []
        for task in self.paginated_request("maniphest.search", params):
            task["project_phids"] = project_phids
            all_tasks.append(task)

        return all_tasks

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
            "projects": task.get("projects", []),
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
        Get all available users

        Returns:
            Dictionary {phid: username}
        """
        all_users_dict = {}
        params = {"limit": "100", "order": "newest"}
        try:
            for user in self.paginated_request("user.search", params):
                phid = user.get("phid")
                fields = user.get("fields", {})
                username = fields.get("username")
                if phid and username:
                    all_users_dict[phid] = username
        except Exception as e:
            print(f"Error while retrieving users: {e}")
        return all_users_dict

    def get_all_users_detailed(self) -> List[Dict[str, Any]]:
        """
        Retrieve detailed information about all available users

        Returns:
            List of dictionaries with detailed information about users
        """
        all_users = []
        params = {"limit": "100", "order": "username"}

        try:
            for user in self.paginated_request("user.search", params):
                phid = user.get("phid")
                fields = user.get("fields", {})

                user_info = {
                    "phid": phid,
                    "username": fields.get("username"),
                    "realName": fields.get("realName"),
                    "roles": fields.get("roles", []),
                    "dateCreated": datetime.fromtimestamp(fields.get("dateCreated", 0))
                    if fields.get("dateCreated")
                    else None,
                    "isDisabled": fields.get("isDisabled", False),
                    "isBot": fields.get("isBot", False),
                    "isMailingList": fields.get("isMailingList", False),
                    "isSystemAgent": fields.get("isSystemAgent", False),
                }

                all_users.append(user_info)
        except Exception as e:
            print(f"Error while retrieving users: {e}")

        return all_users
