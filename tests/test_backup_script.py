import os
import shutil
import subprocess
from pathlib import Path


SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "backup-db.sh"


def test_backup_accepts_small_valid_dump_on_new_database(tmp_path: Path) -> None:
    project = tmp_path / "project"
    scripts = project / "scripts"
    binaries = tmp_path / "bin"
    scripts.mkdir(parents=True)
    binaries.mkdir()
    shutil.copy2(SCRIPT, scripts / "backup-db.sh")
    docker = binaries / "docker"
    docker.write_text(
        "#!/usr/bin/env bash\n"
        'if [[ "$1" == "ps" ]]; then echo fixture-container; exit 0; fi\n'
        'if [[ "$1" == "exec" ]]; then printf -- "-- empty database\\n"; exit 0; fi\n'
        "exit 1\n"
    )
    docker.chmod(0o755)

    result = subprocess.run(
        ["bash", str(scripts / "backup-db.sh")],
        cwd=project,
        env={**os.environ, "PATH": f"{binaries}:{os.environ['PATH']}"},
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    backups = list((project / "backups").glob("*.sql.gz"))
    assert len(backups) == 1
    assert 0 < backups[0].stat().st_size < 1024
