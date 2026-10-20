"""Repo-level guarantees that must hold for a public repo."""

import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def _env_example_entries() -> list[tuple[str, str]]:
    entries = []
    for line in (ROOT / ".env.example").read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        key, sep, value = line.partition("=")
        assert sep, f"malformed line in .env.example: {line!r}"
        entries.append((key, value))
    return entries


def test_env_example_has_names_only():
    entries = _env_example_entries()
    assert entries, ".env.example should list at least one variable"
    filled = [key for key, value in entries if value.strip()]
    assert not filled, f".env.example must not contain values: {filled}"


def test_no_env_file_is_tracked():
    tracked = subprocess.run(
        ["git", "ls-files"], cwd=ROOT, capture_output=True, text=True, check=True
    ).stdout.splitlines()
    env_files = [p for p in tracked if Path(p).name.startswith(".env") and p != ".env.example"]
    assert not env_files, f"env files must not be committed: {env_files}"
