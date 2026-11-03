import pytest
from fastapi.testclient import TestClient

from app import db
from app.main import app


@pytest.fixture()
def client(tmp_path):
    db.init_engine(f"sqlite:///{tmp_path / 'test.db'}")
    with TestClient(app) as c:
        yield c
