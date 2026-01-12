from datetime import datetime
from typing import Optional, List

from sqlalchemy import (
    Integer,
    String,
    Text,
    Boolean,
    DateTime,
    ForeignKey,
    Table,
    Column,
    Index,
)
from sqlalchemy.orm import DeclarativeBase, relationship, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


task_projects = Table(
    "task_projects",
    Base.metadata,
    Column("task_id", Integer, ForeignKey("tasks.id"), primary_key=True),
    Column("project_phid", String, ForeignKey("projects.phid"), primary_key=True),
)


class User(Base):
    __tablename__ = "users"

    phid: Mapped[str] = mapped_column(String(64), primary_key=True)
    username: Mapped[str] = mapped_column(String(255), unique=True, nullable=False)
    real_name: Mapped[Optional[str]] = mapped_column(String(255))
    roles: Mapped[Optional[str]] = mapped_column(Text)
    date_created: Mapped[Optional[datetime]] = mapped_column(DateTime)
    is_disabled: Mapped[bool] = mapped_column(Boolean, default=False)
    is_bot: Mapped[bool] = mapped_column(Boolean, default=False)
    is_mailing_list: Mapped[bool] = mapped_column(Boolean, default=False)
    is_system_agent: Mapped[bool] = mapped_column(Boolean, default=False)
    synced_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    owned_tasks: Mapped[List["Task"]] = relationship(
        back_populates="owner", foreign_keys="Task.owner_phid"
    )
    authored_tasks: Mapped[List["Task"]] = relationship(
        back_populates="author", foreign_keys="Task.author_phid"
    )

    def __repr__(self) -> str:
        return f"<User {self.username}>"


class Project(Base):
    __tablename__ = "projects"

    phid: Mapped[str] = mapped_column(String(64), primary_key=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    slug: Mapped[Optional[str]] = mapped_column(String(255))
    color: Mapped[Optional[str]] = mapped_column(String(32))
    icon: Mapped[Optional[str]] = mapped_column(String(64))
    date_created: Mapped[Optional[datetime]] = mapped_column(DateTime)
    date_modified: Mapped[Optional[datetime]] = mapped_column(DateTime)
    synced_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    tasks: Mapped[List["Task"]] = relationship(
        secondary=task_projects, back_populates="projects"
    )

    def __repr__(self) -> str:
        return f"<Project {self.name}>"


class Task(Base):
    __tablename__ = "tasks"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=False)
    phid: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    title: Mapped[str] = mapped_column(Text, nullable=False)
    description: Mapped[Optional[str]] = mapped_column(Text)
    status_name: Mapped[Optional[str]] = mapped_column(String(64))
    status_value: Mapped[Optional[str]] = mapped_column(String(64))
    priority_name: Mapped[Optional[str]] = mapped_column(String(64))
    priority_value: Mapped[Optional[int]] = mapped_column(Integer)
    date_created: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    date_modified: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    date_closed: Mapped[Optional[datetime]] = mapped_column(DateTime)
    owner_phid: Mapped[Optional[str]] = mapped_column(
        String(64), ForeignKey("users.phid")
    )
    author_phid: Mapped[Optional[str]] = mapped_column(
        String(64), ForeignKey("users.phid")
    )
    phabricator_url: Mapped[Optional[str]] = mapped_column(String(512))
    synced_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    owner: Mapped[Optional["User"]] = relationship(
        back_populates="owned_tasks", foreign_keys=[owner_phid]
    )
    author: Mapped[Optional["User"]] = relationship(
        back_populates="authored_tasks", foreign_keys=[author_phid]
    )
    projects: Mapped[List["Project"]] = relationship(
        secondary=task_projects, back_populates="tasks"
    )
    transactions: Mapped[List["TaskTransaction"]] = relationship(
        back_populates="task", cascade="all, delete-orphan"
    )

    __table_args__ = (
        Index("idx_tasks_date_created", "date_created"),
        Index("idx_tasks_date_modified", "date_modified"),
        Index("idx_tasks_date_closed", "date_closed"),
        Index("idx_tasks_status", "status_value"),
        Index("idx_tasks_owner", "owner_phid"),
        Index("idx_tasks_author", "author_phid"),
    )

    def __repr__(self) -> str:
        return f"<Task T{self.id}: {self.title[:30]}>"


class TaskTransaction(Base):
    __tablename__ = "task_transactions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    task_phid: Mapped[str] = mapped_column(
        String(64), ForeignKey("tasks.phid"), nullable=False
    )
    transaction_phid: Mapped[Optional[str]] = mapped_column(String(64), unique=True)
    transaction_type: Mapped[str] = mapped_column(String(64), nullable=False)
    old_value: Mapped[Optional[str]] = mapped_column(Text)
    new_value: Mapped[Optional[str]] = mapped_column(Text)
    date_created: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    author_phid: Mapped[Optional[str]] = mapped_column(String(64))
    synced_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    task: Mapped["Task"] = relationship(back_populates="transactions")

    __table_args__ = (
        Index("idx_transactions_task", "task_phid"),
        Index("idx_transactions_type", "transaction_type"),
    )

    def __repr__(self) -> str:
        return f"<Transaction {self.transaction_type} on {self.task_phid}>"


class SyncMetadata(Base):
    __tablename__ = "sync_metadata"

    entity_type: Mapped[str] = mapped_column(String(64), primary_key=True)
    last_sync_timestamp: Mapped[Optional[datetime]] = mapped_column(DateTime)
    last_sync_cursor: Mapped[Optional[str]] = mapped_column(String(255))
    records_synced: Mapped[int] = mapped_column(Integer, default=0)

    def __repr__(self) -> str:
        return f"<SyncMetadata {self.entity_type}: {self.last_sync_timestamp}>"
