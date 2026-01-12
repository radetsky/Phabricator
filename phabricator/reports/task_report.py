import csv
from datetime import datetime
from typing import Optional

from sqlalchemy import select, and_, or_
from sqlalchemy.orm import Session

from ..database.models import Task, User, Project


class TaskReporter:
    def __init__(self, session: Session):
        self.session = session

    def get_tasks(
        self,
        start_date: datetime,
        end_date: datetime,
        project_names: Optional[list[str]] = None,
        statuses: Optional[list[str]] = None,
        owner_usernames: Optional[list[str]] = None,
        author_usernames: Optional[list[str]] = None,
        use_modified_date: bool = True,
    ) -> list[Task]:
        stmt = select(Task)

        if use_modified_date:
            stmt = stmt.where(
                and_(
                    Task.date_modified >= start_date,
                    Task.date_modified <= end_date,
                )
            )
        else:
            stmt = stmt.where(
                and_(
                    Task.date_created >= start_date,
                    Task.date_created <= end_date,
                )
            )

        if statuses:
            stmt = stmt.where(Task.status_value.in_(statuses))

        if project_names:
            stmt = stmt.join(Task.projects).where(Project.name.in_(project_names))

        if owner_usernames or author_usernames:
            user_conditions = []
            if owner_usernames:
                owner_subq = select(User.phid).where(User.username.in_(owner_usernames))
                user_conditions.append(Task.owner_phid.in_(owner_subq))
            if author_usernames:
                author_subq = select(User.phid).where(User.username.in_(author_usernames))
                user_conditions.append(Task.author_phid.in_(author_subq))

            if user_conditions:
                stmt = stmt.where(or_(*user_conditions))

        stmt = stmt.order_by(Task.date_modified.desc())

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

        return [
            task
            for task in tasks
            if task.owner_phid in member_phids or task.author_phid in member_phids
        ]

    def format_task(self, task: Task) -> dict:
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

        project_names = [p.name for p in task.projects]

        return {
            "id": task.id,
            "phid": task.phid,
            "title": task.title,
            "projects": project_names,
            "status": task.status_name,
            "priority": task.priority_name,
            "created": task.date_created,
            "modified": task.date_modified,
            "url": task.phabricator_url,
            "author": author_username,
            "owner": owner_username,
        }

    def print_tasks(self, tasks: list[Task]):
        print(f"\nFound {len(tasks)} tasks.\n")
        print("-" * 60)

        for task in tasks:
            info = self.format_task(task)
            print(f"\nT{info['id']}: {info['title']}")
            print(f"  Status: {info['status']}")
            if info["projects"]:
                print(f"  Projects: {', '.join(info['projects'])}")
            print(f"  Priority: {info['priority']}")
            print(f"  Created: {info['created']}")
            print(f"  Modified: {info['modified']}")
            print(f"  URL: {info['url']}")
            print(f"  Author: {info['author']}")
            print(f"  Owner: {info['owner']}")

    def export_csv(self, tasks: list[Task], filepath: str):
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

        with open(filepath, mode="w", newline="", encoding="utf-8") as csv_file:
            writer = csv.DictWriter(csv_file, fieldnames=fieldnames)
            writer.writeheader()

            for task in tasks:
                info = self.format_task(task)
                writer.writerow(
                    {
                        "id": info["id"],
                        "title": info["title"],
                        "projects": ", ".join(info["projects"]),
                        "status": info["status"],
                        "priority": info["priority"],
                        "created": info["created"],
                        "modified": info["modified"],
                        "url": info["url"],
                        "author": info["author"],
                        "owner": info["owner"],
                    }
                )

        print(f"Exported {len(tasks)} tasks to {filepath}")
