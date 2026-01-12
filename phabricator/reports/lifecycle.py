import csv
import json
from datetime import datetime, timedelta
from typing import Optional

from sqlalchemy import select, and_
from sqlalchemy.orm import Session

from ..database.models import Task, User, TaskTransaction


class LifecycleReporter:
    def __init__(self, session: Session):
        self.session = session

    def get_resolved_tasks(
        self,
        start_date: datetime,
        end_date: datetime,
        owner_usernames: Optional[list[str]] = None,
    ) -> list[Task]:
        stmt = select(Task).where(
            and_(
                Task.status_value == "resolved",
                Task.date_closed >= start_date,
                Task.date_closed <= end_date,
            )
        )

        if owner_usernames:
            owner_subq = select(User.phid).where(User.username.in_(owner_usernames))
            stmt = stmt.where(Task.owner_phid.in_(owner_subq))

        stmt = stmt.order_by(Task.date_closed.desc())

        return list(self.session.execute(stmt).scalars().all())

    def filter_by_team_members(
        self, tasks: list[Task], member_usernames: list[str]
    ) -> list[Task]:
        member_phids = set(
            self.session.execute(
                select(User.phid).where(User.username.in_(member_usernames))
            )
            .scalars()
            .all()
        )

        return [task for task in tasks if task.owner_phid in member_phids]

    def get_task_by_id(self, task_id: int | str) -> Optional[Task]:
        if isinstance(task_id, str):
            if task_id.startswith("T"):
                task_id = int(task_id[1:])
            else:
                task_id = int(task_id)

        return self.session.get(Task, task_id)

    def calculate_duration(self, task: Task) -> dict:
        created = task.date_created
        is_resolved = task.status_value == "resolved"

        if task.date_closed:
            closed = task.date_closed
        elif is_resolved:
            closed = self._find_closure_date_from_transactions(task.phid)
            if not closed:
                closed = task.date_modified
        else:
            closed = None

        if closed:
            duration = closed - created
        else:
            duration = datetime.now() - created

        owner_username = None
        if task.owner:
            owner_username = task.owner.username
        elif task.owner_phid:
            owner = self.session.get(User, task.owner_phid)
            owner_username = owner.username if owner else task.owner_phid

        author_username = None
        if task.author:
            author_username = task.author.username
        elif task.author_phid:
            author = self.session.get(User, task.author_phid)
            author_username = author.username if author else task.author_phid

        result = {
            "task_id": task.id,
            "title": task.title,
            "status": task.status_name,
            "priority": task.priority_name,
            "url": task.phabricator_url,
            "author": author_username,
            "owner": owner_username,
            "created_date": created,
            "modified_date": task.date_modified,
            "is_resolved": is_resolved,
            "duration_days": duration.days,
            "duration_hours": round(duration.total_seconds() / 3600, 2),
            "duration_formatted": self._format_duration(duration),
        }

        if is_resolved and closed:
            result["closed_date"] = closed
        else:
            result["note"] = "Task is not closed yet. Showing time from creation to now."

        return result

    def _find_closure_date_from_transactions(self, task_phid: str) -> Optional[datetime]:
        stmt = (
            select(TaskTransaction)
            .where(
                and_(
                    TaskTransaction.task_phid == task_phid,
                    TaskTransaction.transaction_type == "status",
                )
            )
            .order_by(TaskTransaction.date_created.desc())
        )

        transactions = self.session.execute(stmt).scalars().all()

        for tx in transactions:
            if tx.new_value:
                try:
                    new_val = json.loads(tx.new_value)
                    if new_val == "resolved":
                        return tx.date_created
                except (json.JSONDecodeError, TypeError):
                    if tx.new_value == "resolved":
                        return tx.date_created

        return None

    def _format_duration(self, duration: timedelta) -> str:
        days = duration.days
        hours = duration.seconds // 3600
        minutes = (duration.seconds % 3600) // 60

        parts = []
        if days > 0:
            parts.append(f"{days} days")
        if hours > 0:
            parts.append(f"{hours} hours")
        if minutes > 0:
            parts.append(f"{minutes} minutes")

        return " ".join(parts) if parts else "less than a minute"

    def print_task_details(self, details: dict):
        print(f"\nT{details['task_id']}: {details['title']}")
        print(f"  Status: {details['status']}")
        print(f"  Priority: {details['priority']}")
        print(f"  Created: {details['created_date']}")
        print(f"  Modified: {details['modified_date']}")
        if details.get("closed_date"):
            print(f"  Closed: {details['closed_date']}")
        print(f"  URL: {details['url']}")
        print(f"  Author: {details['author']}")
        print(f"  Owner: {details['owner']}")
        print(f"  Duration: {details['duration_formatted']}")
        print(f"  Duration (days): {details['duration_days']}")
        print(f"  Duration (hours): {details['duration_hours']}")
        if details.get("note"):
            print(f"  Note: {details['note']}")

    def print_tasks(self, tasks: list[Task]):
        print(f"\nFound {len(tasks)} resolved tasks.\n")
        print("-" * 60)

        for task in tasks:
            details = self.calculate_duration(task)
            self.print_task_details(details)

    def export_csv(self, tasks: list[Task], filepath: str):
        fieldnames = [
            "id",
            "title",
            "status",
            "priority",
            "created",
            "modified",
            "closed",
            "url",
            "author",
            "owner",
            "duration_days",
            "duration_hours",
            "duration_formatted",
        ]

        with open(filepath, mode="w", newline="", encoding="utf-8") as csv_file:
            writer = csv.DictWriter(csv_file, fieldnames=fieldnames)
            writer.writeheader()

            for task in tasks:
                details = self.calculate_duration(task)
                writer.writerow(
                    {
                        "id": details["task_id"],
                        "title": details["title"],
                        "status": details["status"],
                        "priority": details["priority"],
                        "created": details["created_date"],
                        "modified": details["modified_date"],
                        "closed": details.get("closed_date", ""),
                        "url": details["url"],
                        "author": details["author"],
                        "owner": details["owner"],
                        "duration_days": details["duration_days"],
                        "duration_hours": details["duration_hours"],
                        "duration_formatted": details["duration_formatted"],
                    }
                )

        print(f"Exported {len(tasks)} tasks to {filepath}")
