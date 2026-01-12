from datetime import datetime, timedelta
from typing import Optional
from collections import defaultdict

from sqlalchemy import select, func, and_
from sqlalchemy.orm import Session

from ..database.models import Task, User, Project, task_projects


class StatsReporter:
    def __init__(self, session: Session):
        self.session = session

    def get_team_member_stats(
        self,
        start_date: datetime,
        end_date: datetime,
        member_usernames: list[str],
    ) -> list[dict]:
        """Statistics per team member: tasks created, owned, resolved."""
        member_phids = dict(
            self.session.execute(
                select(User.username, User.phid).where(
                    User.username.in_(member_usernames)
                )
            ).all()
        )

        stats = []
        for username, phid in member_phids.items():
            # Tasks owned (assigned to member)
            owned_total = self.session.scalar(
                select(func.count(Task.id)).where(Task.owner_phid == phid)
            )

            # Tasks owned in period (by modified date)
            owned_in_period = self.session.scalar(
                select(func.count(Task.id)).where(
                    and_(
                        Task.owner_phid == phid,
                        Task.date_modified >= start_date,
                        Task.date_modified <= end_date,
                    )
                )
            )

            # Tasks authored (created by member)
            authored_total = self.session.scalar(
                select(func.count(Task.id)).where(Task.author_phid == phid)
            )

            # Tasks authored in period
            authored_in_period = self.session.scalar(
                select(func.count(Task.id)).where(
                    and_(
                        Task.author_phid == phid,
                        Task.date_created >= start_date,
                        Task.date_created <= end_date,
                    )
                )
            )

            # Resolved tasks (owned by member)
            resolved_total = self.session.scalar(
                select(func.count(Task.id)).where(
                    and_(
                        Task.owner_phid == phid,
                        Task.status_value == "resolved",
                    )
                )
            )

            # Resolved in period
            resolved_in_period = self.session.scalar(
                select(func.count(Task.id)).where(
                    and_(
                        Task.owner_phid == phid,
                        Task.status_value == "resolved",
                        Task.date_closed >= start_date,
                        Task.date_closed <= end_date,
                    )
                )
            )

            # Open tasks owned
            open_tasks = self.session.scalar(
                select(func.count(Task.id)).where(
                    and_(
                        Task.owner_phid == phid,
                        Task.status_value == "open",
                    )
                )
            )

            stats.append(
                {
                    "username": username,
                    "owned_total": owned_total or 0,
                    "owned_in_period": owned_in_period or 0,
                    "authored_total": authored_total or 0,
                    "authored_in_period": authored_in_period or 0,
                    "resolved_total": resolved_total or 0,
                    "resolved_in_period": resolved_in_period or 0,
                    "open_tasks": open_tasks or 0,
                }
            )

        stats.sort(key=lambda x: x["resolved_in_period"], reverse=True)
        return stats

    def get_avg_duration_by_project(
        self,
        start_date: datetime,
        end_date: datetime,
        member_usernames: Optional[list[str]] = None,
    ) -> list[dict]:
        """Average task duration by project for resolved tasks."""
        stmt = (
            select(Task)
            .where(
                and_(
                    Task.status_value == "resolved",
                    Task.date_closed >= start_date,
                    Task.date_closed <= end_date,
                    Task.date_closed.isnot(None),
                )
            )
        )

        if member_usernames:
            member_phids = set(
                self.session.execute(
                    select(User.phid).where(User.username.in_(member_usernames))
                )
                .scalars()
                .all()
            )
            stmt = stmt.where(Task.owner_phid.in_(member_phids))

        tasks = self.session.execute(stmt).scalars().all()

        project_durations = defaultdict(list)

        for task in tasks:
            if task.date_closed and task.date_created:
                duration = task.date_closed - task.date_created
                duration_hours = duration.total_seconds() / 3600

                if task.projects:
                    for project in task.projects:
                        project_durations[project.name].append(duration_hours)
                else:
                    project_durations["(No Project)"].append(duration_hours)

        stats = []
        for project_name, durations in project_durations.items():
            avg_hours = sum(durations) / len(durations)
            avg_days = avg_hours / 24

            stats.append(
                {
                    "project": project_name,
                    "tasks_count": len(durations),
                    "avg_duration_hours": round(avg_hours, 1),
                    "avg_duration_days": round(avg_days, 1),
                    "min_duration_hours": round(min(durations), 1),
                    "max_duration_hours": round(max(durations), 1),
                }
            )

        stats.sort(key=lambda x: x["tasks_count"], reverse=True)
        return stats

    def get_avg_duration_by_member(
        self,
        start_date: datetime,
        end_date: datetime,
        member_usernames: list[str],
    ) -> list[dict]:
        """Average task duration by team member for resolved tasks."""
        member_phids = dict(
            self.session.execute(
                select(User.username, User.phid).where(
                    User.username.in_(member_usernames)
                )
            ).all()
        )

        stats = []
        for username, phid in member_phids.items():
            stmt = select(Task).where(
                and_(
                    Task.owner_phid == phid,
                    Task.status_value == "resolved",
                    Task.date_closed >= start_date,
                    Task.date_closed <= end_date,
                    Task.date_closed.isnot(None),
                )
            )

            tasks = self.session.execute(stmt).scalars().all()

            if not tasks:
                stats.append(
                    {
                        "username": username,
                        "tasks_count": 0,
                        "avg_duration_hours": 0,
                        "avg_duration_days": 0,
                        "min_duration_hours": 0,
                        "max_duration_hours": 0,
                    }
                )
                continue

            durations = []
            for task in tasks:
                if task.date_closed and task.date_created:
                    duration = task.date_closed - task.date_created
                    durations.append(duration.total_seconds() / 3600)

            if durations:
                avg_hours = sum(durations) / len(durations)
                stats.append(
                    {
                        "username": username,
                        "tasks_count": len(durations),
                        "avg_duration_hours": round(avg_hours, 1),
                        "avg_duration_days": round(avg_hours / 24, 1),
                        "min_duration_hours": round(min(durations), 1),
                        "max_duration_hours": round(max(durations), 1),
                    }
                )
            else:
                stats.append(
                    {
                        "username": username,
                        "tasks_count": len(tasks),
                        "avg_duration_hours": 0,
                        "avg_duration_days": 0,
                        "min_duration_hours": 0,
                        "max_duration_hours": 0,
                    }
                )

        stats.sort(key=lambda x: x["tasks_count"], reverse=True)
        return stats

    def print_team_stats(self, stats: list[dict], start_date: datetime, end_date: datetime):
        print(f"\n{'='*70}")
        print(f"TEAM MEMBER STATISTICS")
        print(f"Period: {start_date.strftime('%Y-%m-%d')} - {end_date.strftime('%Y-%m-%d')}")
        print(f"{'='*70}\n")

        header = f"{'Member':<15} {'Resolved':<10} {'Open':<8} {'Authored':<10} {'Owned':<8}"
        print(header)
        print("-" * 60)

        for s in stats:
            print(
                f"{s['username']:<15} "
                f"{s['resolved_in_period']:<10} "
                f"{s['open_tasks']:<8} "
                f"{s['authored_in_period']:<10} "
                f"{s['owned_in_period']:<8}"
            )

        print("-" * 60)
        totals = {
            "resolved": sum(s["resolved_in_period"] for s in stats),
            "open": sum(s["open_tasks"] for s in stats),
            "authored": sum(s["authored_in_period"] for s in stats),
            "owned": sum(s["owned_in_period"] for s in stats),
        }
        print(
            f"{'TOTAL':<15} "
            f"{totals['resolved']:<10} "
            f"{totals['open']:<8} "
            f"{totals['authored']:<10} "
            f"{totals['owned']:<8}"
        )

    def print_duration_by_project(self, stats: list[dict], start_date: datetime, end_date: datetime):
        print(f"\n{'='*70}")
        print(f"AVERAGE TASK DURATION BY PROJECT")
        print(f"Period: {start_date.strftime('%Y-%m-%d')} - {end_date.strftime('%Y-%m-%d')}")
        print(f"{'='*70}\n")

        header = f"{'Project':<30} {'Tasks':<8} {'Avg Days':<10} {'Min Hrs':<10} {'Max Hrs':<10}"
        print(header)
        print("-" * 70)

        for s in stats:
            print(
                f"{s['project'][:29]:<30} "
                f"{s['tasks_count']:<8} "
                f"{s['avg_duration_days']:<10} "
                f"{s['min_duration_hours']:<10} "
                f"{s['max_duration_hours']:<10}"
            )

    def print_duration_by_member(self, stats: list[dict], start_date: datetime, end_date: datetime):
        print(f"\n{'='*70}")
        print(f"AVERAGE TASK DURATION BY TEAM MEMBER")
        print(f"Period: {start_date.strftime('%Y-%m-%d')} - {end_date.strftime('%Y-%m-%d')}")
        print(f"{'='*70}\n")

        header = f"{'Member':<15} {'Tasks':<8} {'Avg Days':<10} {'Min Hrs':<10} {'Max Hrs':<10}"
        print(header)
        print("-" * 60)

        for s in stats:
            print(
                f"{s['username']:<15} "
                f"{s['tasks_count']:<8} "
                f"{s['avg_duration_days']:<10} "
                f"{s['min_duration_hours']:<10} "
                f"{s['max_duration_hours']:<10}"
            )
