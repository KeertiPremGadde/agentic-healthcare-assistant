"""Account persistence (sync SQLAlchemy; the routes call these through `asyncio.to_thread`)."""

from collections.abc import Callable
from contextlib import AbstractContextManager
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from medagent.db.models import Patient, User

SessionFactory = Callable[[], AbstractContextManager[Session]]


class UsernameTakenError(Exception):
    pass


@dataclass(frozen=True)
class Account:
    id: int
    username: str
    patient_id: int
    password_hash: str


def _account(user: User) -> Account:
    return Account(user.id, user.username, user.patient_id, user.password_hash)


def create_account(session_factory: SessionFactory, username: str, password_hash: str) -> Account:
    """Create the user and its own synthetic patient record in one transaction."""
    with session_factory() as session:
        if session.scalar(select(User.id).where(User.username == username)) is not None:
            raise UsernameTakenError
        patient = Patient(name=username)  # no email, phone or other personal data
        session.add(patient)
        session.flush()
        user = User(username=username, password_hash=password_hash, patient_id=patient.id)
        session.add(user)
        try:
            session.commit()
        except IntegrityError as exc:  # lost a race on the unique username
            session.rollback()
            raise UsernameTakenError from exc
        return _account(user)


def find_by_username(session_factory: SessionFactory, username: str) -> Account | None:
    with session_factory() as session:
        user = session.scalars(select(User).where(User.username == username)).one_or_none()
        return _account(user) if user else None


def find_by_id(session_factory: SessionFactory, user_id: int) -> Account | None:
    with session_factory() as session:
        user = session.get(User, user_id)
        return _account(user) if user else None
