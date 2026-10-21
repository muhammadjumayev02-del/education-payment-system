"""SQLite engine and sessions; no database is opened at import time."""
import os
from sqlalchemy import create_engine, event
from sqlalchemy.orm import DeclarativeBase
from dotenv import load_dotenv

load_dotenv()


class Base(DeclarativeBase):
    pass


def make_engine(url: str):
    engine = create_engine(url, connect_args={"check_same_thread": False})

    @event.listens_for(engine, "connect")
    def enable_foreign_keys(connection, _):
        cursor = connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

    return engine


def database_url():
    return os.getenv("DATABASE_URL", "sqlite:///./education.db")


if __name__ == "__main__":
    from app import models  # register tables
    engine = make_engine(database_url())
    Base.metadata.create_all(engine)
    engine.dispose()
    print("База данных подготовлена.")
