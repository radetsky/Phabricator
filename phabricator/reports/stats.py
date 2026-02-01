import csv
from datetime import datetime, timedelta
from typing import Optional
from collections import defaultdict

from sqlalchemy import select, func, and_
from sqlalchemy.orm import Session

from ..database.models import Task, User, Project, task_projects
from .periods import generate_periods, PeriodType


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

    # =====================================================================
    # Periodic Methods - Break down stats by calendar periods
    # =====================================================================

    def get_team_member_stats_periodic(
        self,
        start_date: datetime,
        end_date: datetime,
        member_usernames: list[str],
        project_names: Optional[list[str]],
        period_type: PeriodType,
    ) -> dict:
        """
        Get team member stats broken down by period.
        Returns pivot structure with periods as columns, members as rows.
        """
        periods = generate_periods(start_date, end_date, period_type)
        period_labels = [p.label for p in periods]

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

        def apply_project_filter(stmt):
            if project_phids:
                return self._filter_by_projects(stmt, project_phids)
            return stmt

        rows = []
        for username, phid in sorted(member_phids.items()):
            resolved_values = []
            authored_values = []
            owned_values = []
            open_values = []

            for period in periods:
                # Resolved in period
                stmt = select(func.count(Task.id)).where(
                    and_(
                        Task.owner_phid == phid,
                        Task.status_value == "resolved",
                        Task.date_closed >= period.start,
                        Task.date_closed <= period.end,
                    )
                )
                resolved = self.session.scalar(apply_project_filter(stmt)) or 0
                resolved_values.append(resolved)

                # Authored in period
                stmt = select(func.count(Task.id)).where(
                    and_(
                        Task.author_phid == phid,
                        Task.date_created >= period.start,
                        Task.date_created <= period.end,
                    )
                )
                authored = self.session.scalar(apply_project_filter(stmt)) or 0
                authored_values.append(authored)

                # Owned in period (by modified date)
                stmt = select(func.count(Task.id)).where(
                    and_(
                        Task.owner_phid == phid,
                        Task.date_modified >= period.start,
                        Task.date_modified <= period.end,
                    )
                )
                owned = self.session.scalar(apply_project_filter(stmt)) or 0
                owned_values.append(owned)

                # Open tasks at end of period (simplified: current open)
                stmt = select(func.count(Task.id)).where(
                    and_(
                        Task.owner_phid == phid,
                        Task.status_value == "open",
                    )
                )
                open_count = self.session.scalar(apply_project_filter(stmt)) or 0
                open_values.append(open_count)

            rows.append({
                "member": username,
                "resolved": resolved_values,
                "authored": authored_values,
                "owned": owned_values,
                "open": open_values,
            })

        # Calculate column totals
        totals = {
            "resolved": [sum(r["resolved"][i] for r in rows) for i in range(len(periods))],
            "authored": [sum(r["authored"][i] for r in rows) for i in range(len(periods))],
            "owned": [sum(r["owned"][i] for r in rows) for i in range(len(periods))],
            "open": [sum(r["open"][i] for r in rows) for i in range(len(periods))],
        }

        return {
            "periods": period_labels,
            "rows": rows,
            "totals": totals,
        }

    def get_avg_duration_by_member_periodic(
        self,
        start_date: datetime,
        end_date: datetime,
        member_usernames: list[str],
        project_names: Optional[list[str]],
        period_type: PeriodType,
    ) -> dict:
        """
        Get average task duration by member, broken down by period.
        Members as rows, periods as columns, avg_duration_days as values.
        """
        periods = generate_periods(start_date, end_date, period_type)
        period_labels = [p.label for p in periods]

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

        rows = []
        for username, phid in sorted(member_phids.items()):
            values = []
            for period in periods:
                stmt = select(Task).where(
                    and_(
                        Task.owner_phid == phid,
                        Task.status_value == "resolved",
                        Task.date_closed >= period.start,
                        Task.date_closed <= period.end,
                        Task.date_closed.isnot(None),
                    )
                )
                if project_phids:
                    stmt = self._filter_by_projects(stmt, project_phids)

                tasks = self.session.execute(stmt).scalars().all()

                durations = []
                for task in tasks:
                    if task.date_closed and task.date_created:
                        duration = task.date_closed - task.date_created
                        durations.append(duration.total_seconds() / 3600)

                if durations:
                    avg_days = round((sum(durations) / len(durations)) / 24, 1)
                else:
                    avg_days = 0.0

                values.append(avg_days)

            # Calculate row average (excluding zeros)
            non_zero = [v for v in values if v > 0]
            avg = round(sum(non_zero) / len(non_zero), 1) if non_zero else 0.0

            rows.append({
                "member": username,
                "values": values,
                "avg": avg,
            })

        return {
            "periods": period_labels,
            "rows": rows,
        }

    def get_avg_duration_by_project_periodic(
        self,
        start_date: datetime,
        end_date: datetime,
        member_usernames: Optional[list[str]],
        period_type: PeriodType,
    ) -> dict:
        """
        Get average task duration by project, broken down by period.
        Projects as rows, periods as columns.
        """
        periods = generate_periods(start_date, end_date, period_type)
        period_labels = [p.label for p in periods]

        member_phids = None
        if member_usernames:
            member_phids = set(
                self.session.execute(
                    select(User.phid).where(User.username.in_(member_usernames))
                )
                .scalars()
                .all()
            )

        # Collect project->period->durations data
        project_period_durations = defaultdict(lambda: defaultdict(list))

        for idx, period in enumerate(periods):
            stmt = select(Task).where(
                and_(
                    Task.status_value == "resolved",
                    Task.date_closed >= period.start,
                    Task.date_closed <= period.end,
                    Task.date_closed.isnot(None),
                )
            )
            if member_phids:
                stmt = stmt.where(Task.owner_phid.in_(member_phids))

            tasks = self.session.execute(stmt).scalars().all()

            for task in tasks:
                if task.date_closed and task.date_created:
                    duration_hours = (task.date_closed - task.date_created).total_seconds() / 3600
                    if task.projects:
                        for project in task.projects:
                            project_period_durations[project.name][idx].append(duration_hours)
                    else:
                        project_period_durations["(No Project)"][idx].append(duration_hours)

        rows = []
        for project_name in sorted(project_period_durations.keys()):
            values = []
            for idx in range(len(periods)):
                durations = project_period_durations[project_name][idx]
                if durations:
                    avg_days = round((sum(durations) / len(durations)) / 24, 1)
                else:
                    avg_days = 0.0
                values.append(avg_days)

            non_zero = [v for v in values if v > 0]
            avg = round(sum(non_zero) / len(non_zero), 1) if non_zero else 0.0

            rows.append({
                "project": project_name,
                "values": values,
                "avg": avg,
            })

        return {
            "periods": period_labels,
            "rows": rows,
        }

    def get_utilization_rate_periodic(
        self,
        start_date: datetime,
        end_date: datetime,
        member_usernames: list[str],
        project_names: Optional[list[str]],
        period_type: PeriodType,
    ) -> dict:
        """
        Get utilization rate (task %) by member, broken down by period.
        Members as rows, periods as columns, task_percent as values.
        """
        periods = generate_periods(start_date, end_date, period_type)
        period_labels = [p.label for p in periods]

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

        # First pass: collect task counts per member per period
        member_counts = {username: [] for username in member_phids.keys()}
        period_totals = []

        for period in periods:
            period_total = 0
            for username, phid in sorted(member_phids.items()):
                stmt = select(func.count(Task.id)).where(
                    and_(
                        Task.owner_phid == phid,
                        Task.status_value == "resolved",
                        Task.date_closed >= period.start,
                        Task.date_closed <= period.end,
                    )
                )
                if project_phids:
                    stmt = self._filter_by_projects(stmt, project_phids)

                count = self.session.scalar(stmt) or 0
                member_counts[username].append(count)
                period_total += count

            period_totals.append(period_total)

        # Second pass: calculate percentages
        rows = []
        for username in sorted(member_phids.keys()):
            counts = member_counts[username]
            values = []
            for i, count in enumerate(counts):
                if period_totals[i] > 0:
                    pct = round(count / period_totals[i] * 100, 1)
                else:
                    pct = 0.0
                values.append(pct)

            # Average of percentages (excluding zeros)
            non_zero = [v for v in values if v > 0]
            avg = round(sum(non_zero) / len(non_zero), 1) if non_zero else 0.0

            rows.append({
                "member": username,
                "values": values,
                "avg": avg,
            })

        return {
            "periods": period_labels,
            "rows": rows,
            "period_totals": period_totals,
        }

    # =====================================================================
    # Periodic Print Methods - Pivot table output
    # =====================================================================

    def _print_pivot_header(
        self,
        title: str,
        start_date: datetime,
        end_date: datetime,
        period_type: PeriodType,
        project_names: Optional[list[str]] = None,
    ):
        period_label = "MONTHLY" if period_type == "monthly" else "WEEKLY"
        print(f"\n{'='*80}")
        print(f"{title} ({period_label})")
        print(f"Period: {start_date.strftime('%Y-%m-%d')} - {end_date.strftime('%Y-%m-%d')}")
        if project_names:
            print(f"Projects: {', '.join(project_names)}")
        print(f"{'='*80}\n")

    def _calculate_col_width(self, periods: list[str]) -> int:
        """Calculate column width based on period labels."""
        max_label_len = max(len(p) for p in periods) if periods else 7
        return max(max_label_len + 2, 10)

    def print_team_stats_periodic(
        self,
        data: dict,
        metric: str,
        start_date: datetime,
        end_date: datetime,
        project_names: Optional[list[str]],
        period_type: PeriodType,
    ):
        """Print team stats pivot table for a specific metric."""
        metric_titles = {
            "resolved": "TEAM MEMBER STATISTICS - RESOLVED TASKS",
            "authored": "TEAM MEMBER STATISTICS - AUTHORED TASKS",
            "owned": "TEAM MEMBER STATISTICS - OWNED TASKS",
            "open": "TEAM MEMBER STATISTICS - OPEN TASKS",
        }
        self._print_pivot_header(
            metric_titles.get(metric, f"TEAM STATS - {metric.upper()}"),
            start_date, end_date, period_type, project_names
        )

        periods = data["periods"]
        rows = data["rows"]
        totals = data["totals"][metric]

        col_width = self._calculate_col_width(periods)
        member_width = 15

        # Header row
        header = f"{'Member':<{member_width}}"
        for p in periods:
            header += f"{p:>{col_width}}"
        header += f"{'TOTAL':>{col_width}}"
        print(header)
        print("-" * len(header))

        # Data rows
        for row in rows:
            values = row[metric]
            total = sum(values)
            line = f"{row['member']:<{member_width}}"
            for v in values:
                line += f"{v:>{col_width}}"
            line += f"{total:>{col_width}}"
            print(line)

        # Total row
        print("-" * len(header))
        total_line = f"{'TOTAL':<{member_width}}"
        for t in totals:
            total_line += f"{t:>{col_width}}"
        total_line += f"{sum(totals):>{col_width}}"
        print(total_line)

    def print_duration_by_member_periodic(
        self,
        data: dict,
        start_date: datetime,
        end_date: datetime,
        project_names: Optional[list[str]],
        period_type: PeriodType,
    ):
        """Print average duration by member pivot table."""
        self._print_pivot_header(
            "AVG TASK DURATION IN DAYS",
            start_date, end_date, period_type, project_names
        )

        periods = data["periods"]
        rows = data["rows"]

        col_width = self._calculate_col_width(periods)
        member_width = 15

        # Header row
        header = f"{'Member':<{member_width}}"
        for p in periods:
            header += f"{p:>{col_width}}"
        header += f"{'AVG':>{col_width}}"
        print(header)
        print("-" * len(header))

        # Data rows
        for row in rows:
            line = f"{row['member']:<{member_width}}"
            for v in row["values"]:
                line += f"{v:>{col_width}.1f}" if v > 0 else f"{'-':>{col_width}}"
            line += f"{row['avg']:>{col_width}.1f}" if row["avg"] > 0 else f"{'-':>{col_width}}"
            print(line)

    def print_duration_by_project_periodic(
        self,
        data: dict,
        start_date: datetime,
        end_date: datetime,
        period_type: PeriodType,
    ):
        """Print average duration by project pivot table."""
        self._print_pivot_header(
            "AVG TASK DURATION BY PROJECT IN DAYS",
            start_date, end_date, period_type
        )

        periods = data["periods"]
        rows = data["rows"]

        col_width = self._calculate_col_width(periods)
        project_width = 25

        # Header row
        header = f"{'Project':<{project_width}}"
        for p in periods:
            header += f"{p:>{col_width}}"
        header += f"{'AVG':>{col_width}}"
        print(header)
        print("-" * len(header))

        # Data rows
        for row in rows:
            project_name = row["project"][:project_width-1]
            line = f"{project_name:<{project_width}}"
            for v in row["values"]:
                line += f"{v:>{col_width}.1f}" if v > 0 else f"{'-':>{col_width}}"
            line += f"{row['avg']:>{col_width}.1f}" if row["avg"] > 0 else f"{'-':>{col_width}}"
            print(line)

    def print_utilization_rate_periodic(
        self,
        data: dict,
        start_date: datetime,
        end_date: datetime,
        project_names: Optional[list[str]],
        period_type: PeriodType,
    ):
        """Print utilization rate pivot table."""
        self._print_pivot_header(
            "UTILIZATION RATE %",
            start_date, end_date, period_type, project_names
        )

        periods = data["periods"]
        rows = data["rows"]

        col_width = self._calculate_col_width(periods)
        member_width = 15

        # Header row
        header = f"{'Member':<{member_width}}"
        for p in periods:
            header += f"{p:>{col_width}}"
        header += f"{'AVG':>{col_width}}"
        print(header)
        print("-" * len(header))

        # Data rows
        for row in rows:
            line = f"{row['member']:<{member_width}}"
            for v in row["values"]:
                line += f"{v:>{col_width}.1f}" if v > 0 else f"{'-':>{col_width}}"
            line += f"{row['avg']:>{col_width}.1f}" if row["avg"] > 0 else f"{'-':>{col_width}}"
            print(line)

    # =====================================================================
    # CSV Export for Periodic Data
    # =====================================================================

    def export_pivot_csv(
        self,
        data: dict,
        filepath: str,
        row_label: str = "member",
        value_key: str = "values",
        total_key: str = "total",
    ):
        """
        Export pivot data to CSV with periods as columns.
        Headers: row_label,period1,period2,...,total/avg
        """
        periods = data["periods"]
        rows = data["rows"]

        with open(filepath, "w", newline="") as f:
            writer = csv.writer(f)

            # Header
            header = [row_label] + periods + [total_key]
            writer.writerow(header)

            # Data rows
            for row in rows:
                label = row.get(row_label, row.get("project", ""))
                values = row.get(value_key, [])

                # Calculate total or use avg
                if "avg" in row:
                    total = row["avg"]
                else:
                    total = sum(values)

                csv_row = [label] + values + [total]
                writer.writerow(csv_row)

        print(f"\nExported to: {filepath}")

    def export_team_stats_periodic_csv(
        self,
        data: dict,
        filepath: str,
        metric: str,
    ):
        """Export team stats pivot data for a specific metric."""
        periods = data["periods"]
        rows = data["rows"]

        with open(filepath, "w", newline="") as f:
            writer = csv.writer(f)

            # Header
            header = ["member"] + periods + ["total"]
            writer.writerow(header)

            # Data rows
            for row in rows:
                values = row[metric]
                total = sum(values)
                csv_row = [row["member"]] + values + [total]
                writer.writerow(csv_row)

            # Total row
            totals = data["totals"][metric]
            total_row = ["TOTAL"] + totals + [sum(totals)]
            writer.writerow(total_row)

        print(f"\nExported to: {filepath}")
