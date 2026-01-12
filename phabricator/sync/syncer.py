import json
from datetime import datetime
from typing import Optional

from sqlalchemy.orm import Session
from sqlalchemy.dialects.sqlite import insert

from ..client import PhabricatorClient
from ..database.models import (
    User,
    Project,
    Task,
    TaskTransaction,
    SyncMetadata,
    task_projects,
)


class PhabricatorSyncer:
    def __init__(self, client: PhabricatorClient, session: Session):
        self.client = client
        self.session = session

    def sync_all(self, full: bool = False):
        print("Starting sync...")
        self.sync_users()
        self.sync_projects()
        self.sync_tasks(full=full)
        print("Sync completed.")

    def sync_users(self):
        print("Syncing users...")
        users_data = self.client.get_all_users_detailed()
        count = 0

        for user_data in users_data:
            self._upsert_user(user_data)
            count += 1

        self.session.commit()
        self._update_sync_metadata("users", count)
        print(f"  Synced {count} users.")

    def _upsert_user(self, user_data: dict):
        roles = user_data.get("roles", [])
        roles_json = json.dumps(roles) if roles else None

        stmt = insert(User).values(
            phid=user_data["phid"],
            username=user_data["username"],
            real_name=user_data.get("realName"),
            roles=roles_json,
            date_created=user_data.get("dateCreated"),
            is_disabled=user_data.get("isDisabled", False),
            is_bot=user_data.get("isBot", False),
            is_mailing_list=user_data.get("isMailingList", False),
            is_system_agent=user_data.get("isSystemAgent", False),
            synced_at=datetime.utcnow(),
        )

        stmt = stmt.on_conflict_do_update(
            index_elements=["phid"],
            set_={
                "username": stmt.excluded.username,
                "real_name": stmt.excluded.real_name,
                "roles": stmt.excluded.roles,
                "is_disabled": stmt.excluded.is_disabled,
                "is_bot": stmt.excluded.is_bot,
                "is_mailing_list": stmt.excluded.is_mailing_list,
                "is_system_agent": stmt.excluded.is_system_agent,
                "synced_at": stmt.excluded.synced_at,
            },
        )

        self.session.execute(stmt)

    def sync_projects(self):
        print("Syncing projects...")
        projects_data = self.client.get_all_projects()
        count = 0

        for phid, fields in projects_data.items():
            self._upsert_project(phid, fields)
            count += 1

        self.session.commit()
        self._update_sync_metadata("projects", count)
        print(f"  Synced {count} projects.")

    def _upsert_project(self, phid: str, fields: dict):
        date_created = None
        if fields.get("dateCreated"):
            date_created = datetime.fromtimestamp(fields["dateCreated"])

        date_modified = None
        if fields.get("dateModified"):
            date_modified = datetime.fromtimestamp(fields["dateModified"])

        stmt = insert(Project).values(
            phid=phid,
            name=fields.get("name", ""),
            slug=fields.get("slug"),
            color=fields.get("color", {}).get("key") if isinstance(fields.get("color"), dict) else fields.get("color"),
            icon=fields.get("icon", {}).get("key") if isinstance(fields.get("icon"), dict) else fields.get("icon"),
            date_created=date_created,
            date_modified=date_modified,
            synced_at=datetime.utcnow(),
        )

        stmt = stmt.on_conflict_do_update(
            index_elements=["phid"],
            set_={
                "name": stmt.excluded.name,
                "slug": stmt.excluded.slug,
                "color": stmt.excluded.color,
                "icon": stmt.excluded.icon,
                "date_modified": stmt.excluded.date_modified,
                "synced_at": stmt.excluded.synced_at,
            },
        )

        self.session.execute(stmt)

    def sync_tasks(
        self,
        full: bool = False,
        since: Optional[datetime] = None,
        project_names: Optional[list[str]] = None,
    ):
        print("Syncing tasks...")

        if not full and since is None:
            since = self._get_last_sync_time("tasks")

        self.client.all_projects = self.client.get_all_projects()
        project_phids = self.client.get_project_phids(project_names) if project_names else list(self.client.all_projects.keys())

        if since:
            print(f"  Incremental sync since {since}")
            end_date = datetime.now()
            tasks_data = self.client.get_tasks_by_projects_and_period(
                project_phids=project_phids,
                start_date=since,
                end_date=end_date,
                use_modified_date=True,
                statuses=["open", "resolved", "wontfix", "invalid", "duplicate"],
            )
        else:
            print("  Full sync...")
            start_date = datetime(2020, 1, 1)
            end_date = datetime.now()
            tasks_data = self.client.get_tasks_by_projects_and_period(
                project_phids=project_phids,
                start_date=start_date,
                end_date=end_date,
                use_modified_date=True,
                statuses=["open", "resolved", "wontfix", "invalid", "duplicate"],
            )

        count = 0
        for task_data in tasks_data:
            self._upsert_task(task_data)
            count += 1

        self.session.commit()
        self._update_sync_metadata("tasks", count)
        print(f"  Synced {count} tasks.")

    def _upsert_task(self, task_data: dict):
        fields = task_data.get("fields", {})
        task_id = task_data["id"]
        task_phid = task_data["phid"]

        date_created = datetime.fromtimestamp(fields.get("dateCreated", 0))
        date_modified = datetime.fromtimestamp(fields.get("dateModified", 0))

        date_closed = None
        if fields.get("dateClosed"):
            date_closed = datetime.fromtimestamp(fields["dateClosed"])

        status = fields.get("status", {})
        priority = fields.get("priority", {})

        stmt = insert(Task).values(
            id=task_id,
            phid=task_phid,
            title=fields.get("name", ""),
            description=fields.get("description", {}).get("raw") if isinstance(fields.get("description"), dict) else None,
            status_name=status.get("name") if isinstance(status, dict) else None,
            status_value=status.get("value") if isinstance(status, dict) else None,
            priority_name=priority.get("name") if isinstance(priority, dict) else None,
            priority_value=priority.get("value") if isinstance(priority, dict) else None,
            date_created=date_created,
            date_modified=date_modified,
            date_closed=date_closed,
            owner_phid=fields.get("ownerPHID"),
            author_phid=fields.get("authorPHID"),
            phabricator_url=f"{self.client.base_url}/T{task_id}",
            synced_at=datetime.utcnow(),
        )

        stmt = stmt.on_conflict_do_update(
            index_elements=["id"],
            set_={
                "title": stmt.excluded.title,
                "description": stmt.excluded.description,
                "status_name": stmt.excluded.status_name,
                "status_value": stmt.excluded.status_value,
                "priority_name": stmt.excluded.priority_name,
                "priority_value": stmt.excluded.priority_value,
                "date_modified": stmt.excluded.date_modified,
                "date_closed": stmt.excluded.date_closed,
                "owner_phid": stmt.excluded.owner_phid,
                "author_phid": stmt.excluded.author_phid,
                "synced_at": stmt.excluded.synced_at,
            },
        )

        self.session.execute(stmt)

        project_names = task_data.get("projects", [])
        if project_names:
            self._sync_task_projects(task_id, project_names)

    def _sync_task_projects(self, task_id: int, project_names: list[str]):
        self.session.execute(
            task_projects.delete().where(task_projects.c.task_id == task_id)
        )

        for project_name in project_names:
            project = (
                self.session.query(Project).filter(Project.name == project_name).first()
            )
            if project:
                self.session.execute(
                    insert(task_projects).values(
                        task_id=task_id, project_phid=project.phid
                    ).on_conflict_do_nothing()
                )

    def sync_task_transactions(self, task_phid: str):
        transactions = self.client.get_task_transactions(task_phid)

        for tx_data in transactions:
            self._upsert_transaction(task_phid, tx_data)

        self.session.commit()

    def _upsert_transaction(self, task_phid: str, tx_data: dict):
        tx_phid = tx_data.get("phid")
        tx_type = tx_data.get("type", "")
        date_created = datetime.fromtimestamp(tx_data.get("dateCreated", 0))

        fields = tx_data.get("fields", {})
        old_value = json.dumps(fields.get("old")) if fields.get("old") is not None else None
        new_value = json.dumps(fields.get("new")) if fields.get("new") is not None else None

        stmt = insert(TaskTransaction).values(
            task_phid=task_phid,
            transaction_phid=tx_phid,
            transaction_type=tx_type,
            old_value=old_value,
            new_value=new_value,
            date_created=date_created,
            author_phid=tx_data.get("authorPHID"),
            synced_at=datetime.utcnow(),
        )

        if tx_phid:
            stmt = stmt.on_conflict_do_update(
                index_elements=["transaction_phid"],
                set_={
                    "old_value": stmt.excluded.old_value,
                    "new_value": stmt.excluded.new_value,
                    "synced_at": stmt.excluded.synced_at,
                },
            )

        self.session.execute(stmt)

    def _get_last_sync_time(self, entity_type: str) -> Optional[datetime]:
        metadata = (
            self.session.query(SyncMetadata)
            .filter(SyncMetadata.entity_type == entity_type)
            .first()
        )
        return metadata.last_sync_timestamp if metadata else None

    def _update_sync_metadata(self, entity_type: str, records_synced: int):
        stmt = insert(SyncMetadata).values(
            entity_type=entity_type,
            last_sync_timestamp=datetime.utcnow(),
            records_synced=records_synced,
        )

        stmt = stmt.on_conflict_do_update(
            index_elements=["entity_type"],
            set_={
                "last_sync_timestamp": stmt.excluded.last_sync_timestamp,
                "records_synced": stmt.excluded.records_synced,
            },
        )

        self.session.execute(stmt)
        self.session.commit()

    def get_sync_status(self) -> dict:
        metadata = self.session.query(SyncMetadata).all()
        return {
            m.entity_type: {
                "last_sync": m.last_sync_timestamp,
                "records_synced": m.records_synced,
            }
            for m in metadata
        }
