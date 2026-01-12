#!/usr/bin/env python3
import argparse
import sys
from datetime import datetime

from phabricator.client import PhabricatorClient, PhabricatorConfiguration
from phabricator.database import init_db, get_session, get_db_path
from phabricator.sync import PhabricatorSyncer
from phabricator.reports import TaskReporter, LifecycleReporter, StatsReporter


def parse_date(date_str: str) -> datetime:
    try:
        return datetime.strptime(date_str, "%Y-%m-%d")
    except ValueError:
        raise argparse.ArgumentTypeError(
            f"Invalid date format: {date_str}. Use YYYY-MM-DD."
        )


def handle_sync(args):
    config = PhabricatorConfiguration()
    config.read_from_env()
    client = PhabricatorClient(config)

    engine = init_db()
    session = get_session(engine)

    syncer = PhabricatorSyncer(client, session)

    try:
        if args.users:
            syncer.sync_users()
        elif args.projects:
            syncer.sync_projects()
        elif args.tasks:
            since = parse_date(args.since) if args.since else None
            syncer.sync_tasks(full=args.full, since=since)
        else:
            syncer.sync_all(full=args.full)
    finally:
        session.close()


def handle_report(args):
    engine = init_db()
    session = get_session(engine)

    try:
        start_date = parse_date(args.start_date)
        end_date = parse_date(args.end_date)

        if start_date > end_date:
            print("Error: Start date cannot be later than end date.")
            sys.exit(1)

        project_names = None
        if args.projects:
            project_names = [p.strip() for p in args.projects.split(",") if p.strip()]

        statuses = None
        if args.statuses:
            statuses = [s.strip() for s in args.statuses.split(",") if s.strip()]

        reporter = TaskReporter(session)
        tasks = reporter.get_tasks(
            start_date=start_date,
            end_date=end_date,
            project_names=project_names,
            statuses=statuses,
        )

        if args.team:
            config = PhabricatorConfiguration()
            config.read_from_env()
            if config.devteam_members:
                tasks = reporter.filter_by_team_members(tasks, config.devteam_members)

        reporter.print_tasks(tasks)

        if args.csv:
            reporter.export_csv(tasks, args.csv)

    finally:
        session.close()


def handle_lifecycle(args):
    engine = init_db()
    session = get_session(engine)

    try:
        reporter = LifecycleReporter(session)

        if args.task:
            task = reporter.get_task_by_id(args.task)
            if not task:
                print(f"Error: Task {args.task} not found in local database.")
                print("Run 'python cli.py sync' first to populate the database.")
                sys.exit(1)

            details = reporter.calculate_duration(task)
            reporter.print_task_details(details)
            return

        start_date = parse_date(args.start_date)
        end_date = parse_date(args.end_date)

        if start_date > end_date:
            print("Error: Start date cannot be later than end date.")
            sys.exit(1)

        tasks = reporter.get_resolved_tasks(start_date, end_date)

        if args.team:
            config = PhabricatorConfiguration()
            config.read_from_env()
            if config.devteam_members:
                tasks = reporter.filter_by_team_members(tasks, config.devteam_members)

        reporter.print_tasks(tasks)

        if args.csv:
            reporter.export_csv(tasks, args.csv)

    finally:
        session.close()


def handle_stats(args):
    engine = init_db()
    session = get_session(engine)

    try:
        config = PhabricatorConfiguration()
        config.read_from_env()

        if not config.devteam_members:
            print("Error: DEVTEAM_MEMBERS environment variable is not set.")
            sys.exit(1)

        start_date = parse_date(args.start_date)
        end_date = parse_date(args.end_date)

        if start_date > end_date:
            print("Error: Start date cannot be later than end date.")
            sys.exit(1)

        reporter = StatsReporter(session)

        if args.type == "team" or args.type == "all":
            stats = reporter.get_team_member_stats(
                start_date, end_date, config.devteam_members
            )
            reporter.print_team_stats(stats, start_date, end_date)

        if args.type == "projects" or args.type == "all":
            stats = reporter.get_avg_duration_by_project(
                start_date, end_date, config.devteam_members if args.team else None
            )
            reporter.print_duration_by_project(stats, start_date, end_date)

        if args.type == "duration" or args.type == "all":
            stats = reporter.get_avg_duration_by_member(
                start_date, end_date, config.devteam_members
            )
            reporter.print_duration_by_member(stats, start_date, end_date)

    finally:
        session.close()


def handle_status(args):
    engine = init_db()
    session = get_session(engine)

    try:
        config = PhabricatorConfiguration()
        try:
            config.read_from_env()
            print(f"Phabricator URL: {config.base_url}")
            print(f"Team members: {', '.join(config.devteam_members)}")
        except Exception:
            print("Warning: Environment variables not configured.")

        print(f"\nDatabase: {get_db_path()}")

        syncer = PhabricatorSyncer(None, session)
        status = syncer.get_sync_status()

        if not status:
            print("\nNo sync data yet. Run 'python cli.py sync --full' to sync data.")
        else:
            print("\nSync status:")
            for entity_type, info in status.items():
                last_sync = info["last_sync"]
                if last_sync:
                    last_sync_str = last_sync.strftime("%Y-%m-%d %H:%M:%S")
                else:
                    last_sync_str = "Never"
                print(
                    f"  {entity_type}: {info['records_synced']} records, last sync: {last_sync_str}"
                )

    finally:
        session.close()


def main():
    parser = argparse.ArgumentParser(
        description="Phabricator CLI Tool - Sync and report on tasks"
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    # Sync command
    sync_parser = subparsers.add_parser("sync", help="Sync data from Phabricator")
    sync_parser.add_argument(
        "--full", action="store_true", help="Full sync (all data)"
    )
    sync_parser.add_argument(
        "--users", action="store_true", help="Sync only users"
    )
    sync_parser.add_argument(
        "--projects", action="store_true", help="Sync only projects"
    )
    sync_parser.add_argument(
        "--tasks", action="store_true", help="Sync only tasks"
    )
    sync_parser.add_argument(
        "--since", type=str, help="Sync tasks modified since date (YYYY-MM-DD)"
    )

    # Report command
    report_parser = subparsers.add_parser("report", help="Generate task reports")
    report_parser.add_argument(
        "--start-date", required=True, help="Start date (YYYY-MM-DD)"
    )
    report_parser.add_argument(
        "--end-date", required=True, help="End date (YYYY-MM-DD)"
    )
    report_parser.add_argument(
        "--projects", type=str, help="Comma-separated list of project names"
    )
    report_parser.add_argument(
        "--statuses",
        type=str,
        default="open,resolved",
        help="Comma-separated list of statuses (default: open,resolved)",
    )
    report_parser.add_argument(
        "--team",
        action="store_true",
        help="Filter by team members from DEVTEAM_MEMBERS env var",
    )
    report_parser.add_argument("--csv", type=str, help="Export to CSV file")

    # Lifecycle command
    lifecycle_parser = subparsers.add_parser(
        "lifecycle", help="Task lifecycle analysis"
    )
    lifecycle_parser.add_argument(
        "--start-date", type=str, help="Start date (YYYY-MM-DD)"
    )
    lifecycle_parser.add_argument(
        "--end-date", type=str, help="End date (YYYY-MM-DD)"
    )
    lifecycle_parser.add_argument(
        "--task", type=str, help="Single task ID (e.g., T123 or 123)"
    )
    lifecycle_parser.add_argument(
        "--team",
        action="store_true",
        help="Filter by team members from DEVTEAM_MEMBERS env var",
    )
    lifecycle_parser.add_argument("--csv", type=str, help="Export to CSV file")

    # Stats command
    stats_parser = subparsers.add_parser("stats", help="Team and project statistics")
    stats_parser.add_argument(
        "--start-date", required=True, help="Start date (YYYY-MM-DD)"
    )
    stats_parser.add_argument(
        "--end-date", required=True, help="End date (YYYY-MM-DD)"
    )
    stats_parser.add_argument(
        "--type",
        choices=["all", "team", "projects", "duration"],
        default="all",
        help="Type of stats: all, team (member stats), projects (avg duration by project), duration (avg duration by member)",
    )
    stats_parser.add_argument(
        "--team",
        action="store_true",
        help="Filter project stats by team members only",
    )

    # Status command
    subparsers.add_parser("status", help="Show sync status and configuration")

    args = parser.parse_args()

    if args.command == "sync":
        handle_sync(args)
    elif args.command == "report":
        handle_report(args)
    elif args.command == "lifecycle":
        if not args.task and (not args.start_date or not args.end_date):
            print("Error: --start-date and --end-date are required unless --task is specified.")
            sys.exit(1)
        handle_lifecycle(args)
    elif args.command == "stats":
        handle_stats(args)
    elif args.command == "status":
        handle_status(args)


if __name__ == "__main__":
    main()
