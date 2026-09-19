"""Unit tests for the versioned commit gate (`.githooks/pre-commit`) and its activation.

The hook must block every commit behind the full `make check` quality gate. These
tests pin that contract without running the whole suite: `make` is stubbed on PATH.
"""

import os
import stat
import subprocess
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
HOOK_PATH = REPO_ROOT / ".githooks" / "pre-commit"
MAKEFILE_PATH = REPO_ROOT / "Makefile"
GITIGNORE_PATH = REPO_ROOT / ".gitignore"

STUBBED_MAKE_FAILURE_EXIT = 3


def _run_hook_with_stubbed_make(tmp_path: Path, *, make_exit: int) -> int:
    stub_bin = tmp_path / "bin"
    stub_bin.mkdir()
    stub_make = stub_bin / "make"
    stub_make.write_text(f"#!/usr/bin/env bash\nexit {make_exit}\n", encoding="utf-8")
    stub_make.chmod(stub_make.stat().st_mode | stat.S_IXUSR)

    env = dict(os.environ)
    env["PATH"] = f"{stub_bin}{os.pathsep}{env['PATH']}"
    completed = subprocess.run(
        [str(HOOK_PATH)], cwd=REPO_ROOT, env=env, check=False, capture_output=True, text=True
    )
    return completed.returncode


def _run_hook_capturing_make_env(
    tmp_path: Path, fake_home: Path, *, incoming_path: str
) -> dict[str, str]:
    stub_bin = tmp_path / "bin"
    stub_bin.mkdir()
    capture = tmp_path / "capture.txt"
    stub_make = stub_bin / "make"
    stub_make.write_text(
        "#!/usr/bin/env bash\n"
        f'printf "PATH=%s\\n" "$PATH" > "{capture}"\n'
        f'printf "UV=%s\\n" "$(command -v uv || true)" >> "{capture}"\n',
        encoding="utf-8",
    )
    stub_make.chmod(stub_make.stat().st_mode | stat.S_IXUSR)

    env = dict(os.environ)
    env["HOME"] = str(fake_home)
    env["PATH"] = f"{stub_bin}{os.pathsep}{incoming_path}"
    completed = subprocess.run(
        [str(HOOK_PATH)], cwd=REPO_ROOT, env=env, check=False, capture_output=True, text=True
    )
    assert completed.returncode == 0, completed.stderr

    return dict(
        line.split("=", 1)
        for line in capture.read_text(encoding="utf-8").splitlines()
        if "=" in line
    )


def test_hook_bootstraps_user_local_bin_so_make_can_find_uv(tmp_path: Path) -> None:
    fake_home = tmp_path / "home"
    local_bin = fake_home / ".local" / "bin"
    local_bin.mkdir(parents=True)
    stub_uv = local_bin / "uv"
    stub_uv.write_text("#!/usr/bin/env bash\nexit 0\n", encoding="utf-8")
    stub_uv.chmod(stub_uv.stat().st_mode | stat.S_IXUSR)

    captured = _run_hook_capturing_make_env(
        tmp_path,
        fake_home,
        incoming_path="/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin",
    )

    assert str(local_bin) in captured["PATH"].split(os.pathsep)
    assert captured["UV"] == str(stub_uv)


def test_pre_commit_hook_is_executable() -> None:
    assert HOOK_PATH.is_file()
    assert HOOK_PATH.stat().st_mode & stat.S_IXUSR


def test_pre_commit_hook_runs_full_check_gate() -> None:
    assert "make check" in HOOK_PATH.read_text(encoding="utf-8")


def test_hook_propagates_make_check_failure(tmp_path: Path) -> None:
    exit_code = _run_hook_with_stubbed_make(tmp_path, make_exit=STUBBED_MAKE_FAILURE_EXIT)

    assert exit_code == STUBBED_MAKE_FAILURE_EXIT


def test_hook_exits_zero_when_make_check_passes(tmp_path: Path) -> None:
    assert _run_hook_with_stubbed_make(tmp_path, make_exit=0) == 0


def test_makefile_exposes_hooks_target_activating_githooks_dir() -> None:
    makefile = MAKEFILE_PATH.read_text(encoding="utf-8")

    assert "hooks:" in makefile
    assert "git config --local core.hooksPath .githooks" in makefile


def test_githooks_directory_is_not_gitignored() -> None:
    ignored = {
        line.strip().rstrip("/")
        for line in GITIGNORE_PATH.read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.strip().startswith("#")
    }

    assert ".githooks" not in ignored
