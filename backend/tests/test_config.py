from config import read_secret


def test_read_secret_from_file(tmp_path, monkeypatch):
    secret_dir = tmp_path / "run" / "secrets"
    secret_dir.mkdir(parents=True)
    (secret_dir / "my_key").write_text("file-value\n")
    monkeypatch.setattr("config.Path", lambda p: secret_dir / p.split("/")[-1] if p.startswith("/run/secrets/") else __import__("pathlib").Path(p))
    # Simpler: just write to the actual path the function checks
    import config
    original = config.Path
    def patched_path(p):
        if p.startswith("/run/secrets/"):
            return secret_dir / p.split("/")[-1]
        return original(p)
    monkeypatch.setattr(config, "Path", patched_path)
    assert read_secret("my_key") == "file-value"


def test_read_secret_falls_back_to_env(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "env-value")
    result = read_secret("anthropic_api_key", "ANTHROPIC_API_KEY")
    assert result == "env-value"


def test_read_secret_returns_empty_when_missing(monkeypatch):
    monkeypatch.delenv("NONEXISTENT_KEY", raising=False)
    result = read_secret("nonexistent", "NONEXISTENT_KEY")
    assert result == ""
