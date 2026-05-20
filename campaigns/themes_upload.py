"""Validation + extraction of theme bundle .zip uploads.

Public API:
- ``validate_bundle(uploaded_file)`` — raises ``ValidationError`` on any issue.
- ``extract_bundle(uploaded_file, theme)`` — validates, then atomically
  populates ``theme.directory``.
"""
import os
import shutil
import zipfile
from pathlib import Path

from django.conf import settings
from django.core.exceptions import ValidationError


REQUIRED_FILES = ("submission_form.html", "submission_success.html")
ALLOWED_ASSET_EXTENSIONS = {
    ".svg", ".png", ".jpg", ".jpeg", ".webp", ".gif",
    ".css", ".woff", ".woff2", ".ttf", ".otf", ".ico",
}
MAX_UNCOMPRESSED_SIZE = 10 * 1024 * 1024  # 10 MB


def _is_safe_path(name):
    """Reject path traversal, absolute paths, and zip-slip."""
    if name.startswith("/") or name.startswith("\\"):
        return False
    parts = Path(name).parts
    if ".." in parts:
        return False
    if any(p.startswith("..") for p in parts):
        return False
    return True


def validate_bundle(uploaded_file):
    """Validate a .zip upload. Raises ValidationError on any issue."""
    try:
        zf = zipfile.ZipFile(uploaded_file)
    except zipfile.BadZipFile as e:
        raise ValidationError(f"Not a valid .zip file: {e}")

    names = zf.namelist()

    # Required files at the root.
    for required in REQUIRED_FILES:
        if required not in names:
            raise ValidationError(
                f"Bundle is missing required file: {required}"
            )

    # Path safety + total uncompressed size.
    total = 0
    for info in zf.infolist():
        if not _is_safe_path(info.filename):
            raise ValidationError(
                f"Unsafe path in bundle: {info.filename!r}"
            )
        total += info.file_size
        if total > MAX_UNCOMPRESSED_SIZE:
            raise ValidationError(
                f"Bundle uncompressed size exceeds {MAX_UNCOMPRESSED_SIZE // 1024 // 1024} MB"
            )

    # Asset extension allowlist (anything under assets/).
    for name in names:
        if name in REQUIRED_FILES or name.endswith("/"):
            continue
        if name.startswith("assets/"):
            ext = Path(name).suffix.lower()
            if ext not in ALLOWED_ASSET_EXTENSIONS:
                raise ValidationError(
                    f"Disallowed asset extension in bundle: {name}"
                )
        else:
            raise ValidationError(
                f"Unexpected file outside assets/: {name}"
            )

    if hasattr(uploaded_file, "seek"):
        uploaded_file.seek(0)


def extract_bundle(uploaded_file, theme):
    """Validate + atomically extract a bundle into theme.directory."""
    validate_bundle(uploaded_file)
    if hasattr(uploaded_file, "seek"):
        uploaded_file.seek(0)
    zf = zipfile.ZipFile(uploaded_file)

    dest = theme.directory
    staging = dest.with_name(dest.name + ".new")
    if staging.exists():
        shutil.rmtree(staging)
    staging.mkdir(parents=True)

    for info in zf.infolist():
        if info.filename.endswith("/"):
            continue
        target = staging / info.filename
        target.parent.mkdir(parents=True, exist_ok=True)
        with zf.open(info) as src, open(target, "wb") as dst:
            shutil.copyfileobj(src, dst)

    if dest.exists():
        shutil.rmtree(dest)
    os.rename(staging, dest)
