import os
from pathlib import Path
from contextlib import contextmanager
from typing import Generator

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from .models import Base


def get_db_path() -> Path:
    db_path = os.environ.get("PHABRICATOR_DB_PATH")
    if db_path:
        return Path(db_path)

    default_dir = Path.home() / ".phabricator"
    default_dir.mkdir(parents=True, exist_ok=True)
    return default_dir / "data.db"


def get_engine(db_path: Path | None = None):
    if db_path is None:
        db_path = get_db_path()

    db_path.parent.mkdir(parents=True, exist_ok=True)
    return create_engine(f"sqlite:///{db_path}", echo=False)


_session_factory = None


def get_session_factory(engine=None):
    global _session_factory
    if _session_factory is None:
        if engine is None:
            engine = get_engine()
        _session_factory = sessionmaker(bind=engine)
    return _session_factory


def get_session(engine=None) -> Session:
    factory = get_session_factory(engine)
    return factory()


@contextmanager
def session_scope(engine=None) -> Generator[Session, None, None]:
    session = get_session(engine)
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def init_db(engine=None):
    if engine is None:
        engine = get_engine()
    Base.metadata.create_all(engine)
    return engine
