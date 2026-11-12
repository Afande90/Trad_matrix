import pytest

from src.db import set_db
from tests.fakes import FakeDB


@pytest.fixture(autouse=True)
def fake_supabase():
    db = FakeDB()
    set_db(db)
    yield db
    set_db(None)
