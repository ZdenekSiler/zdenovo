# Testing Rules

## Stack

- **pytest** — test runner (`uv run pytest`)
- **httpx + TestClient** — FastAPI route tests
- **pytest-cov** — coverage (`uv run pytest --cov`)
- Tests live in `backend/tests/`, named `test_<module>.py`

## Test Layout

```
backend/tests/
├── conftest.py          # test_db and client fixtures
├── test_db.py           # db.py unit tests
├── test_data.py         # data/posts.py and data/projects.py
├── test_api.py          # /api/posts CRUD endpoints
└── test_routes.py       # HTML page routes + HTMX structure
```

Each test file mirrors the module it covers. Add a new `test_<module>.py` here when
adding a new `routers/` or `data/` module (see @.claude/rules/architecture.md).

## Fixtures

Define shared setup in `conftest.py`. Always isolate the database:

```python
@pytest.fixture()
def test_db(tmp_path, monkeypatch):
    import db
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "test.db")
    db.init_db()
    yield tmp_path / "test.db"

@pytest.fixture()
def client(test_db):
    from main import app
    return TestClient(app, raise_server_exceptions=True)
```

Never let tests share state. Each test gets a fresh DB.

## Test Naming

Function-based, plain English:

```python
def test_create_post_returns_201(client): ...
def test_create_post_duplicate_returns_409(client): ...
def test_get_post_missing_returns_404(client): ...
```

Pattern: `test_<function>_<condition>_<expected outcome>`

## Test Structure (AAA)

1. **Arrange** — set up data (use fixtures, insert rows)
2. **Act** — call the function or HTTP endpoint
3. **Assert** — check status code, response body, or side effect

One behaviour per test. No `assert` in helpers called from multiple tests.

## Coverage

- Minimum 80% line coverage for new backend code
- 100% for pure utility functions (`row_to_dict`, `_slugify`, etc.)
- Test behaviour, not implementation — avoid asserting on private internals

## What to Test

| Layer | What | How |
|-------|------|-----|
| `db.py` | `init_db`, `get_conn`, `row_to_dict` | Direct function calls with `test_db` fixture |
| `data/*.py` | Query helpers | Direct function calls with `test_db` fixture |
| `routers/posts_api.py` | CRUD endpoints | `client` fixture (status codes + response bodies) |
| HTML routes | Page rendering, HTMX attrs, tag filter | `client` fixture (status code + `b"substring" in r.content`) |

## Running Tests

```bash
cd backend

# Run all tests
uv run pytest

# With coverage report
uv run pytest --cov --cov-report=term-missing

# Single file
uv run pytest tests/test_api.py

# Single test
uv run pytest tests/test_api.py::test_create_post_returns_201
```

## Gate

**Do not commit code with failing tests.** Tests must pass before `/simplify` and before any commit.
