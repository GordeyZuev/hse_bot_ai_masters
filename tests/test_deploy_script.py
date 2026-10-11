import os
import shutil
import subprocess
from pathlib import Path


SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "deploy.sh"


def _fake_deploy(
    tmp_path: Path,
    *,
    args: tuple[str, ...] = (),
    fail_build: bool = False,
    app_running: bool = False,
    app_status: str | None = None,
    dirty_tree: bool = False,
    has_creds: bool = True,
    app_exists: bool = True,
):
    project = tmp_path / "project"
    scripts = project / "scripts"
    config = project / "src" / "config"
    binaries = tmp_path / "bin"
    scripts.mkdir(parents=True)
    config.mkdir(parents=True)
    binaries.mkdir()
    (project / ".git").mkdir()
    (config / ".env").write_text("ENVIRONMENT=production\n")
    if has_creds:
        (config / "creds.json").write_text("{}")
    shutil.copy2(SCRIPT, scripts / "deploy.sh")
    (scripts / "backup-db.sh").write_text(
        '#!/usr/bin/env bash\necho "backup" >> "$CALLS"\n'
    )
    (scripts / "backup-db.sh").chmod(0o755)
    (binaries / "docker").write_text(
        '#!/usr/bin/env bash\necho "docker $*" >> "$CALLS"\n'
        'if [[ "$*" == *" ps --status ${APP_STATUS:-running} -q app"* && '
        '"${APP_RUNNING:-}" == "1" ]]; then echo app-id; fi\n'
        'if [[ "$*" == *" ps -a -q app"* && '
        '"${APP_EXISTS:-}" == "1" ]]; then echo app-id; fi\n'
        'if [[ "$*" == *" build "* && "${FAIL_BUILD:-}" == "1" ]]; '
        "then exit 1; fi\n"
    )
    (binaries / "docker").chmod(0o755)
    (binaries / "git").write_text(
        '#!/usr/bin/env bash\necho "git $*" >> "$CALLS"\n'
        'if [[ "$*" == "status --porcelain" && "${DIRTY_TREE:-}" == "1" ]]; '
        'then echo " M local-file"; fi\n'
    )
    (binaries / "git").chmod(0o755)
    calls = tmp_path / "calls"
    env = {
        **os.environ,
        "PATH": f"{binaries}:{os.environ['PATH']}",
        "CALLS": str(calls),
        "FAIL_BUILD": "1" if fail_build else "0",
        "APP_RUNNING": "1" if app_running else "0",
        "APP_STATUS": app_status or "running",
        "APP_EXISTS": "1" if app_exists else "0",
        "DIRTY_TREE": "1" if dirty_tree else "0",
    }
    result = subprocess.run(
        ["bash", str(scripts / "deploy.sh"), *args],
        cwd=project,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    return result, calls.read_text().splitlines()


def test_deploy_builds_and_backs_up_before_migrating_and_restarting(tmp_path) -> None:
    result, calls = _fake_deploy(tmp_path)
    assert result.returncode == 0, result.stderr
    assert calls[0] == "docker compose version"
    assert calls[1] == "docker compose --env-file src/config/.env config -q"
    assert not any(call.startswith("git ") for call in calls)
    assert "docker compose --env-file src/config/.env build migrate" in calls
    assert "backup" in calls
    assert "docker compose --env-file src/config/.env stop app" in calls
    assert "docker compose --env-file src/config/.env run --rm migrate" in calls
    assert "docker compose --env-file src/config/.env up -d --no-deps app" in calls
    assert not any(" down" in call for call in calls)
    assert calls.index("backup") < calls.index(
        "docker compose --env-file src/config/.env stop app"
    )
    assert calls.index(
        "docker compose --env-file src/config/.env stop app"
    ) < calls.index("docker compose --env-file src/config/.env run --rm migrate")


def test_deploy_does_not_touch_running_services_if_build_fails(tmp_path) -> None:
    result, calls = _fake_deploy(tmp_path, fail_build=True)
    assert result.returncode != 0
    assert calls[-1] == "docker compose --env-file src/config/.env build migrate"
    assert "backup" not in calls


def test_first_deploy_does_not_stop_nonexistent_app(tmp_path) -> None:
    result, calls = _fake_deploy(tmp_path, app_exists=False)
    assert result.returncode == 0, result.stderr
    assert "docker compose --env-file src/config/.env ps -a -q app" in calls
    assert "docker compose --env-file src/config/.env stop app" not in calls
    assert "docker compose --env-file src/config/.env up -d --no-deps app" in calls


def test_update_pulls_before_build(tmp_path) -> None:
    result, calls = _fake_deploy(tmp_path, args=("--pull",))
    assert result.returncode == 0, result.stderr
    assert calls[1] == "git status --porcelain"
    assert calls[2] == "git pull --ff-only"
    assert calls[3] == "docker compose --env-file src/config/.env config -q"
    assert calls.index("git pull --ff-only") < calls.index(
        "docker compose --env-file src/config/.env build migrate"
    )


def test_update_refuses_dirty_checkout_before_pull(tmp_path) -> None:
    result, calls = _fake_deploy(tmp_path, args=("--pull",), dirty_tree=True)
    assert result.returncode != 0
    assert calls[-1] == "git status --porcelain"
    assert "git pull --ff-only" not in calls


def test_migrate_only_does_not_start_app(tmp_path) -> None:
    result, calls = _fake_deploy(tmp_path, args=("--migrate-only",), has_creds=False)
    assert result.returncode == 0, result.stderr
    assert (
        "docker compose --env-file src/config/.env ps --status running -q app" in calls
    )
    assert "docker compose --env-file src/config/.env run --rm migrate" in calls
    assert not any(
        " stop app" in call or " up -d --no-deps app" in call for call in calls
    )
    assert not any(call.startswith("git ") for call in calls)


def test_migrate_only_refuses_running_app(tmp_path) -> None:
    result, calls = _fake_deploy(tmp_path, args=("--migrate-only",), app_running=True)
    assert result.returncode != 0
    assert "make deploy" in result.stderr
    assert (
        calls[-1]
        == "docker compose --env-file src/config/.env ps --status running -q app"
    )


def test_migrate_only_refuses_restarting_app(tmp_path) -> None:
    result, calls = _fake_deploy(
        tmp_path, args=("--migrate-only",), app_running=True, app_status="restarting"
    )
    assert result.returncode != 0
    assert "restarting" in result.stderr
    assert (
        calls[-1]
        == "docker compose --env-file src/config/.env ps --status restarting -q app"
    )
