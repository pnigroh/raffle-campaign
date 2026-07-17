from django.urls import path, reverse_lazy
from django.contrib.auth import views as auth_views
from django.views.generic.base import RedirectView
from . import views

_GT_SUBMIT = reverse_lazy('submission_form', kwargs={'campaign_slug': 'futboleros-bn-gt'})
_HN_SUBMIT = reverse_lazy('submission_form', kwargs={'campaign_slug': 'futboleros-bn-hn'})

urlpatterns = [
    # Public
    path('submit/<slug:campaign_slug>/', views.submission_form, name='submission_form'),
    path('submit/<slug:campaign_slug>/success/', views.submission_success, name='submission_success'),
    path('submit/<slug:campaign_slug>/preview/<str:variant>/', views.submission_form_preview, name='submission_form_preview'),

    # Short links (QR / sharing): /g[/] -> Guatemala, /h[/] -> Honduras.
    path('g', RedirectView.as_view(url=_GT_SUBMIT), name='shortlink_gt'),
    path('g/', RedirectView.as_view(url=_GT_SUBMIT)),
    path('h', RedirectView.as_view(url=_HN_SUBMIT), name='shortlink_hn'),
    path('h/', RedirectView.as_view(url=_HN_SUBMIT)),

    # Auth
    path('dashboard/login/', auth_views.LoginView.as_view(
        template_name='campaigns/login.html',
        next_page='/dashboard/'
    ), name='login'),
    path('dashboard/logout/', auth_views.LogoutView.as_view(next_page='/dashboard/login/'), name='logout'),

    # Dashboard
    path('dashboard/', views.dashboard, name='dashboard'),
    path('dashboard/campaign/<int:campaign_id>/', views.campaign_detail, name='campaign_detail'),
    path('dashboard/campaign/<int:campaign_id>/export/', views.export_campaign_submissions, name='export_submissions'),
    path('dashboard/campaign/<int:campaign_id>/raffle/', views.raffle_view, name='raffle'),
    path('dashboard/campaign/<int:campaign_id>/reveal/', views.raffle_reveal, name='raffle_reveal'),
    path('dashboard/campaign/<int:campaign_id>/import-codes/', views.import_codes_view, name='import_codes'),
    path('dashboard/campaign/<int:campaign_id>/filter-count/', views.ajax_filter_count, name='ajax_filter_count'),
    path('dashboard/campaign/<int:campaign_id>/submission/<int:submission_id>/validity/', views.submission_set_validity, name='submission_set_validity'),
    path('dashboard/campaign/<int:campaign_id>/submission/<int:submission_id>/restore-eligibility/',
         views.submission_restore_eligibility, name='submission_restore_eligibility'),
    path('dashboard/campaign/<int:campaign_id>/prize/add/', views.prize_add, name='prize_add'),
    path('dashboard/campaign/<int:campaign_id>/prize/<int:prize_id>/edit/', views.prize_edit, name='prize_edit'),
    path('dashboard/campaign/<int:campaign_id>/prize/<int:prize_id>/delete/', views.prize_delete, name='prize_delete'),
    path('dashboard/raffle/<int:raffle_id>/results/', views.raffle_results, name='raffle_results'),
    path('dashboard/raffle/<int:raffle_id>/export/', views.export_raffle_winners, name='export_winners'),
    path('dashboard/raffle/<int:raffle_id>/audit/', views.raffle_audit, name='raffle_audit'),
    path('dashboard/raffle/<int:raffle_id>/audit/json/', views.raffle_audit_json, name='raffle_audit_json'),
    path('dashboard/raffle/<int:raffle_id>/verify/json/', views.raffle_verify_json, name='raffle_verify_json'),
]
