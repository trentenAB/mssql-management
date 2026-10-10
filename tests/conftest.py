import pytest
from app import create_app


@pytest.fixture
def app(tmp_path):
    return create_app({'TESTING':True, 'SECRET_KEY':'test-only', 'DEMO_MODE':True,
                       'DATABASE':str(tmp_path/'test.sqlite3')})


@pytest.fixture
def client(app):
    return app.test_client()


def csrf(client):
    client.get('/')
    with client.session_transaction() as session:
        return session['csrf_token']
