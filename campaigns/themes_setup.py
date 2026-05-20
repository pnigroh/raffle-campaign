"""Copy the in-repo source theme into THEMES_ROOT.

Called from the data migration that creates the default Theme row, AND from
the `setup_default_theme` management command (operator recovery tool).
"""
import shutil
from pathlib import Path

from django.conf import settings


REPO_DEFAULT_THEME_DIR = Path(__file__).resolve().parent / "themes" / "futboleros"


def copy_default_theme_to_themes_root(force=False):
    """Copy ``campaigns/themes/futboleros/`` into ``<THEMES_ROOT>/futboleros/``.

    Idempotent by default. With ``force=True``, removes the destination first.
    Returns the destination Path. Raises if the source directory is missing.
    """
    src = REPO_DEFAULT_THEME_DIR
    if not src.is_dir():
        raise RuntimeError(
            f"Source default theme directory missing: {src}. "
            "Did Task 4 (repo restructure) run yet?"
        )
    dest = Path(settings.THEMES_ROOT) / "futboleros"
    if dest.exists():
        if not force:
            return dest
        shutil.rmtree(dest)
    dest.parent.mkdir(parents=True, exist_ok=True)
    shutil.copytree(src, dest)
    return dest
