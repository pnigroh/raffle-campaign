"""Copy in-repo source themes into THEMES_ROOT.

Called from the data migration that creates the default Theme row, from the
`setup_default_theme` management command (operator recovery tool), and from
the per-campaign `provision_*` commands, which ship their own theme in-repo.
"""
import shutil
from pathlib import Path

from django.conf import settings


REPO_THEMES_DIR = Path(__file__).resolve().parent / "themes"
DEFAULT_THEME_SLUG = "futboleros"
REPO_DEFAULT_THEME_DIR = REPO_THEMES_DIR / DEFAULT_THEME_SLUG


def copy_repo_theme_to_themes_root(slug, force=False):
    """Copy ``campaigns/themes/<slug>/`` into ``<THEMES_ROOT>/<slug>/``.

    Idempotent by default. With ``force=True``, removes the destination first.
    Returns the destination Path. Raises if the source directory is missing.
    """
    src = REPO_THEMES_DIR / slug
    if not src.is_dir():
        raise RuntimeError(f"Source theme directory missing: {src}")
    dest = Path(settings.THEMES_ROOT) / slug
    if dest.exists():
        if not force:
            return dest
        shutil.rmtree(dest)
    dest.parent.mkdir(parents=True, exist_ok=True)
    shutil.copytree(src, dest)
    return dest


def copy_default_theme_to_themes_root(force=False):
    """Copy the default theme into THEMES_ROOT. See the generic helper above."""
    return copy_repo_theme_to_themes_root(DEFAULT_THEME_SLUG, force=force)
