"""Deployment artifact contracts: scripts, PM2 config, runbook, gitignore.

These tests are static: they read files and never execute PM2, migrations or the app.
"""

from __future__ import annotations

import os
import re
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPTS = REPO_ROOT / "scripts"
ECOSYSTEM = REPO_ROOT / "ecosystem.config.cjs"
MAKEFILE = REPO_ROOT / "Makefile"
GITIGNORE = REPO_ROOT / ".gitignore"
RUNBOOK = REPO_ROOT / "docs" / "deployment-runbook.md"


@pytest.mark.parametrize("name", ["start.sh", "backup_db.sh", "restore_db.sh"])
def test_deployment_script_exists_and_is_executable(name: str) -> None:
    script = SCRIPTS / name
    assert script.is_file(), f"missing {name}"
    assert os.access(script, os.X_OK), f"{name} is not executable"


@pytest.mark.parametrize("name", ["start.sh", "backup_db.sh", "restore_db.sh"])
def test_deployment_scripts_pass_bash_syntax_check(name: str) -> None:
    result = subprocess.run(
        ["bash", "-n", str(SCRIPTS / name)],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr


def test_start_script_migrates_before_starting() -> None:
    content = (SCRIPTS / "start.sh").read_text(encoding="utf-8")
    migrate_at = content.index("alembic upgrade head")
    run_at = content.index("python main.py")
    assert migrate_at < run_at, "migrations must run before the app starts"
    assert content.startswith("#!/usr/bin/env bash")


def test_backup_script_uses_online_backup_not_copy() -> None:
    content = (SCRIPTS / "backup_db.sh").read_text(encoding="utf-8")
    assert ".backup" in content
    assert 'cp "' not in content


def test_restore_script_removes_stale_wal_siblings_and_verifies_revision() -> None:
    content = (SCRIPTS / "restore_db.sh").read_text(encoding="utf-8")
    assert "-wal" in content and "-shm" in content
    assert "alembic_version" in content
    assert "get_current_head" in content


def test_ecosystem_config_matches_docs_contract() -> None:
    content = ECOSYSTEM.read_text(encoding="utf-8")
    for fragment in (
        'name: "vk-topic-bridge"',
        "cwd: __dirname",
        'script: "./scripts/start.sh"',
        'interpreter: "none"',
        "autorestart: true",
        "watch: false",
        "restart_delay: 5000",
        "max_restarts: 10",
        "kill_timeout: 15000",
        'log_file: "./logs/pm2.log"',
        "PYTHONUNBUFFERED",
    ):
        assert fragment in content, f"ecosystem.config.cjs is missing: {fragment}"


def test_pid_directory_is_preserved_in_git() -> None:
    assert (REPO_ROOT / "pid" / ".gitkeep").is_file()


def test_makefile_exposes_backup_and_restore_targets() -> None:
    content = MAKEFILE.read_text(encoding="utf-8")
    assert re.search(r"^backup-db:", content, flags=re.MULTILINE)
    assert re.search(r"^restore-db:", content, flags=re.MULTILINE)
    assert "scripts/backup_db.sh" in content
    assert "scripts/restore_db.sh" in content


@pytest.mark.parametrize(
    "path",
    [".vkbottle/x", "runtime/vk_cursor/x", "runtime/media/x", "runtime/telethon/x"],
)
def test_runtime_paths_are_gitignored(path: str) -> None:
    result = subprocess.run(
        ["git", "check-ignore", path],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, f"{path} is not gitignored"


def test_runbook_covers_required_procedures() -> None:
    content = RUNBOOK.read_text(encoding="utf-8")
    for topic in (
        "Fresh install",
        "Reboot / autostart",
        "Backup",
        "Restore",
        "Secrets hygiene",
        "Graceful shutdown",
        "Known limitations",
        "pm2-logrotate",
    ):
        assert topic in content, f"runbook is missing section: {topic}"
