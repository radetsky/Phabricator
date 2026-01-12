from datetime import datetime, timedelta
from typing import Optional
from collections import defaultdict

from sqlalchemy import select, func, and_
from sqlalchemy.orm import Session

from ..database.models import Task, User, Project, task_projects


class StatsReporter:
    def __init__(self, session: Session):
        self.session = session

    def _get_project_phids(self, project_names: list[str]) -> set[str]:
        """Get project PHIDs by names."""
        return set(
            self.session.execute(
                select(Project.phid).where(Project.name.in_(project_names))
            )
            .scalars()
            .all()
        )

    def _filter_by_projects(self, stmt, project_phids: set[str]):
        """Add project filter to a query using subquery."""
        task_ids_in_projects = (
            select(task_projects.c.task_id)
            .where(task_projects.c.project_phid.in_(project_phids))
            .distinct()
        )
        return stmt.where(Task.id.in_(task_ids_in_projects))

    def get_team_member_stats(
        self,
        start_date: datetime,
        end_date: datetime,
        member_usernames: list[str],
        project_names: Optional[list[str]] = None,
    ) -> list[dict]:
        """Statistics per team member: tasks created, owned, resolved."""
        member_phids = dict(
            self.session.execute(
                select(User.username, User.phid).where(
                    User.username.in_(member_usernames)
                )
            ).all()
        )

        project_phids = None
        if project_names:
            project_phids = self._get_project_phids(project_names)

        stats = []
        for username, phid in member_phids.items():
            # Base filter for project membership
            def apply_project_filter(stmt):
                if project_phids:
                    return self._filter_by_projects(stmt, project_phids)
                return stmt

            # Tasks owned (assigned to member)
            stmt = select(func.count(Task.id)).where(Task.owner_phid == phid)
            owned_total = self.session.scalar(apply_project_filter(stmt))

            # Tasks owned in period (by modified date)
            stmt = select(func.count(Task.id)).where(
                and_(
                    Task.owner_phid == phid,
                    Task.date_modified >= start_date,
                    Task.date_modified <= end_date,
                )
            )
            owned_in_period = self.session.scalar(apply_project_filter(stmt))

            # Tasks authored (created by member)
            stmt = select(func.count(Task.id)).where(Task.author_phid == phid)
            authored_total = self.session.scalar(apply_project_filter(stmt))

            # Tasks authored in period
            stmt = select(func.count(Task.id)).where(
                and_(
                    Task.author_phid == phid,
                    Task.date_created >= start_date,
                    Task.date_created <= end_date,
                )
            )
            authored_in_period = self.session.scalar(apply_project_filter(stmt))

            # Resolved tasks (owned by member)
            stmt = select(func.count(Task.id)).where(
                and_(
                    Task.owner_phid == phid,
                    Task.status_value == "resolved",
                )
            )
            resolved_total = self.session.scalar(apply_project_filter(stmt))

            # Resolved in period
            stmt = select(func.count(Task.id)).where(
                and_(
                    Task.owner_phid == phid,
                    Task.status_value == "resolved",
                    Task.date_closed >= start_date,
                    Task.date_closed <= end_date,
                )
            )
            resolved_in_period = self.session.scalar(apply_project_filter(stmt))

            # Open tasks owned
            stmt = select(func.count(Task.id)).where(
                and_(
                    Task.owner_phid == phid,
                    Task.status_value == "open",
                )
            )
            open_tasks = self.session.scalar(apply_project_filter(stmt))

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
        project_names: Optional[list[str]] = None,
    ) -> list[dict]:
        """Average task duration by team member for resolved tasks."""
        member_phids = dict(
            self.session.execute(
                select(User.username, User.phid).where(
                    User.username.in_(member_usernames)
                )
            ).all()
        )

        project_phids = None
        if project_names:
            project_phids = self._get_project_phids(project_names)

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

            if project_phids:
                stmt = self._filter_by_projects(stmt, project_phids)

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

    def get_utilization_rate(
        self,
        start_date: datetime,
        end_date: datetime,
        member_usernames: list[str],
        project_names: Optional[list[str]] = None,
    ) -> list[dict]:
        """
        Calculate utilization rate (workload distribution) per team member.
        Shows both task count % and hours %.
        """
        member_phids = dict(
            self.session.execute(
                select(User.username, User.phid).where(
                    User.username.in_(member_usernames)
                )
            ).all()
        )

        project_phids = None
        if project_names:
            project_phids = self._get_project_phids(project_names)

        member_stats = []
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

            if project_phids:
                stmt = self._filter_by_projects(stmt, project_phids)

            tasks = self.session.execute(stmt).scalars().all()

            total_hours = 0.0
            for task in tasks:
                if task.date_closed and task.date_created:
                    duration = task.date_closed - task.date_created
                    total_hours += duration.total_seconds() / 3600

            member_stats.append({
                "username": username,
                "tasks_count": len(tasks),
                "total_hours": round(total_hours, 1),
            })

        # Calculate totals
        total_tasks = sum(s["tasks_count"] for s in member_stats)
        total_hours = sum(s["total_hours"] for s in member_stats)

        # Calculate percentages
        for s in member_stats:
            s["task_percent"] = round(
                (s["tasks_count"] / total_tasks * 100) if total_tasks > 0 else 0, 1
            )
            s["hours_percent"] = round(
                (s["total_hours"] / total_hours * 100) if total_hours > 0 else 0, 1
            )

        member_stats.sort(key=lambda x: x["tasks_count"], reverse=True)
        return member_stats

    def print_utilization_rate(
        self,
        stats: list[dict],
        start_date: datetime,
        end_date: datetime,
        project_names: Optional[list[str]] = None,
    ):
        print(f"\n{'='*70}")
        print(f"UTILIZATION RATE (WORKLOAD DISTRIBUTION)")
        print(f"Period: {start_date.strftime('%Y-%m-%d')} - {end_date.strftime('%Y-%m-%d')}")
        if project_names:
            print(f"Projects: {', '.join(project_names)}")
        print(f"{'='*70}\n")

        header = f"{'Member':<15} {'Tasks':<8} {'Hours':<12} {'Task %':<10} {'Hours %':<10}"
        print(header)
        print("-" * 60)

        for s in stats:
            print(
                f"{s['username']:<15} "
                f"{s['tasks_count']:<8} "
                f"{s['total_hours']:<12} "
                f"{s['task_percent']:<10} "
                f"{s['hours_percent']:<10}"
            )

        print("-" * 60)
        total_tasks = sum(s["tasks_count"] for s in stats)
        total_hours = sum(s["total_hours"] for s in stats)
        print(
            f"{'TOTAL':<15} "
            f"{total_tasks:<8} "
            f"{round(total_hours, 1):<12} "
            f"{'100%':<10} "
            f"{'100%':<10}"
        )

    def print_team_stats(
        self,
        stats: list[dict],
        start_date: datetime,
        end_date: datetime,
        project_names: Optional[list[str]] = None,
    ):
        print(f"\n{'='*70}")
        print(f"TEAM MEMBER STATISTICS")
        print(f"Period: {start_date.strftime('%Y-%m-%d')} - {end_date.strftime('%Y-%m-%d')}")
        if project_names:
            print(f"Projects: {', '.join(project_names)}")
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

    def print_duration_by_member(
        self,
        stats: list[dict],
        start_date: datetime,
        end_date: datetime,
        project_names: Optional[list[str]] = None,
    ):
        print(f"\n{'='*70}")
        print(f"AVERAGE TASK DURATION BY TEAM MEMBER")
        print(f"Period: {start_date.strftime('%Y-%m-%d')} - {end_date.strftime('%Y-%m-%d')}")
        if project_names:
            print(f"Projects: {', '.join(project_names)}")
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
