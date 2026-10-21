import pytest
from fastapi.testclient import TestClient
from app.main import create_app


@pytest.fixture
def client(tmp_path):
    # Every test gets its own file, including its own foreign key pragma.
    with TestClient(create_app(f"sqlite:///{tmp_path / 'test.db'}")) as client:
        yield client


@pytest.fixture
def student(client):
    response = client.post('/students', json={
        'name': 'Али', 'phone': '+998901234567', 'group_name': 'Python', 'monthly_fee': '100.00'})
    assert response.status_code == 201
    return response.json()
