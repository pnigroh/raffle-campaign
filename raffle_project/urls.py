from pathlib import Path

from django.contrib import admin
from django.conf import settings
from django.conf.urls.static import static
from django.http import Http404
from django.urls import path, include
from django.views.static import serve as static_serve


def _theme_asset_view(request, slug, path):
    """Dev-only theme asset serving. In prod, nginx serves these directly."""
    asset_root = Path(settings.THEMES_ROOT) / slug / "assets"
    if not asset_root.is_dir():
        raise Http404
    return static_serve(request, path, document_root=str(asset_root))


urlpatterns = [
    path('i18n/', include('django.conf.urls.i18n')),
    path('admin/', admin.site.urls),
    path('theme-assets/<slug:slug>/<path:path>', _theme_asset_view, name='theme_asset'),
    path('', include('campaigns.urls')),
] + static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
