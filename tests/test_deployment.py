"""Static deployment contract checks that do not require Docker daemon access."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_docker_image_contains_migrations_and_frontend():
    dockerfile = (ROOT / "docker" / "Dockerfile").read_text(encoding="utf-8")
    assert "COPY alembic.ini" in dockerfile
    assert "COPY alembic " in dockerfile
    assert "COPY frontend " in dockerfile


def test_dockerignore_excludes_large_local_state():
    ignored = (ROOT / ".dockerignore").read_text(encoding="utf-8")
    for entry in (".git", ".venv", "data"):
        assert entry in ignored


def test_readme_uses_served_frontend_url_instead_of_file_opening():
    zh = (ROOT / "README.md").read_text(encoding="utf-8")
    en = (ROOT / "README_EN.md").read_text(encoding="utf-8")
    assert "http://localhost:8000/app/" in zh
    assert "http://localhost:8000/app/" in en
    assert "frontend/index.html 用浏览器打开" not in zh
    assert "open frontend/index.html in a browser" not in en


def test_compose_runs_migrations_before_api_start():
    compose = (ROOT / "docker-compose.yml").read_text(encoding="utf-8")
    assert "alembic upgrade head && uvicorn" in compose


def test_compatibility_sensitive_dependencies_have_upper_bounds():
    import tomllib

    project = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    dependencies = project["project"]["dependencies"]
    by_name = {item.split(">=", 1)[0]: item for item in dependencies}
    for name in (
        "fastapi",
        "pydantic",
        "sqlalchemy",
        "langchain-core",
        "langchain-openai",
        "langchain-chroma",
        "langgraph",
        "chromadb",
    ):
        assert "<" in by_name[name], by_name[name]
