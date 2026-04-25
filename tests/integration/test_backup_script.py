import subprocess
from pathlib import Path

SCRIPTS_DIR = Path(__file__).parent.parent.parent / "scripts"


def test_backup_script_syntax() -> None:
    out = subprocess.run(
        ["bash", "-n", str(SCRIPTS_DIR / "backup_sqlite.sh")],
        capture_output=True,
    )
    assert out.returncode == 0, out.stderr.decode()


def test_restore_script_syntax() -> None:
    out = subprocess.run(
        ["bash", "-n", str(SCRIPTS_DIR / "restore_sqlite.sh")],
        capture_output=True,
    )
    assert out.returncode == 0, out.stderr.decode()
