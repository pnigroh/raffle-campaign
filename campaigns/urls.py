from django.urls import path
from django.contrib.auth import views as auth_views
from . import views

urlpatterns = [
    # Public
    path('submit/<slug:campaign_slug>/', views.submission_form, name='submission_form'),
    path('submit/<slug:campaign_slug>/success/', views.submission_success, name='submission_success'),

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
    path('dashboard/campaign/<int:campaign_id>/import-codes/', views.import_codes_view, name='import_codes'),
    path('dashboard/campaign/<int:campaign_id>/filter-count/', views.ajax_filter_count, name='ajax_filter_count'),
    path('dashboard/raffle/<int:raffle_id>/results/', views.raffle_results, name='raffle_results'),
    path('dashboard/raffle/<int:raffle_id>/export/', views.export_raffle_winners, name='export_winners'),
]
