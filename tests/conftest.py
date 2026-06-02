import os
import pytest
from sqlmodel import SQLModel, create_engine, Session

# Set testing environment variable
os.environ["TESTING"] = "True"

TEST_DB_FILE = "./test_gp_connect.db"
TEST_DATABASE_URL = f"sqlite:///{TEST_DB_FILE}"

# 1. Clean up any previous test db file
if os.path.exists(TEST_DB_FILE):
    try:
        os.remove(TEST_DB_FILE)
    except OSError:
        pass

# 2. Create the test engine
test_engine = create_engine(TEST_DATABASE_URL, connect_args={"check_same_thread": False})

# 3. Patch the engine in the database module before main or routes are imported
import database
database.engine = test_engine

# 4. Now import app and get_session
from main import app
from database import get_session
from fastapi.testclient import TestClient

@pytest.fixture(name="engine", scope="session")
def engine_fixture():
    # Make sure tables are created
    SQLModel.metadata.create_all(test_engine)
    yield test_engine
    # Drop tables and clean up the file
    SQLModel.metadata.drop_all(test_engine)
    if os.path.exists(TEST_DB_FILE):
        try:
            os.remove(TEST_DB_FILE)
        except OSError:
            pass

@pytest.fixture(name="session")
def session_fixture(engine):
    with Session(engine) as session:
        yield session

@pytest.fixture(name="client")
def client_fixture(session):
    # Override the dependency to use the session fixture
    def get_session_override():
        yield session
        
    fastapi_app = app.other_asgi_app
    fastapi_app.dependency_overrides[get_session] = get_session_override
    with TestClient(app) as client:
        yield client
    fastapi_app.dependency_overrides.clear()
