import logging
import os
import shutil
import subprocess
import tarfile
import tempfile
from pathlib import Path

from matterkeep.exceptions import MatterkeeperError

logger = logging.getLogger(__name__)


def encrypt_archive(
    archive_dir: Path,
    recipient: str | None = None,
    output_path: Path | None = None,
    shred: bool = False,
) -> Path:
    if not shutil.which("age"):
        raise MatterkeeperError(
            "'age' is not installed or not on PATH. "
            "See https://github.com/FiloSottile/age for installation instructions."
        )

    if not archive_dir.exists():
        raise MatterkeeperError(f"Archive directory not found: {archive_dir}")

    if output_path is None:
        output_path = archive_dir.parent / f"{archive_dir.name}.tar.age"

    with tempfile.NamedTemporaryFile(suffix=".tar", delete=False) as tmp_tar:
        tmp_tar_path = Path(tmp_tar.name)

    try:
        logger.info("Creating tarball of %s", archive_dir)
        with tarfile.open(tmp_tar_path, "w") as tar:
            tar.add(archive_dir, arcname=archive_dir.name)

        age_cmd = ["age", "--output", str(output_path)]
        if recipient:
            age_cmd += ["--recipient", recipient]
        else:
            age_cmd += ["--passphrase"]
        age_cmd.append(str(tmp_tar_path))

        logger.info("Encrypting with age")
        result = subprocess.run(age_cmd, capture_output=True, text=True)
        if result.returncode != 0:
            raise MatterkeeperError(f"age encryption failed: {result.stderr.strip()}")

    finally:
        tmp_tar_path.unlink(missing_ok=True)

    if shred:
        _shred_directory(archive_dir)

    return output_path


def _shred_directory(path: Path) -> None:
    for f in path.rglob("*"):
        if f.is_file():
            size = f.stat().st_size
            with f.open("r+b") as fh:
                fh.write(os.urandom(size))
            f.unlink()
    shutil.rmtree(path, ignore_errors=True)
    logger.info("Shredded and removed %s", path)
