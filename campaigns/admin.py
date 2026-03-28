from django.contrib import admin
from django.utils.html import format_html
from django.urls import reverse
from unfold.admin import ModelAdmin, TabularInline
from .models import Campaign, Prize, SubmissionCode, Submission, Raffle, RaffleWinner


class PrizeInline(TabularInline):
    model = Prize
    extra = 1
    fields = ['name', 'description', 'quantity', 'order']


class SubmissionCodeInline(TabularInline):
    model = SubmissionCode
    extra = 0
    fields = ['code', 'is_used', 'used_at']
    readonly_fields = ['used_at']
    max_num = 20
    show_change_link = True


@admin.register(Campaign)
class CampaignAdmin(ModelAdmin):
    list_display = ['name', 'is_active', 'validate_submission_code', 'start_date', 'end_date', 'submission_count', 'dashboard_link']
    list_filter = ['is_active', 'validate_submission_code']
    search_fields = ['name', 'slug']
    prepopulated_fields = {'slug': ('name',)}
    inlines = [PrizeInline]

    def submission_count(self, obj):
        return obj.submissions.count()
    submission_count.short_description = 'Submissions'

    def dashboard_link(self, obj):
        url = reverse('campaign_detail', args=[obj.id])
        return format_html('<a href="{}">View Dashboard →</a>', url)
    dashboard_link.short_description = 'Dashboard'


@admin.register(Prize)
class PrizeAdmin(ModelAdmin):
    list_display = ['name', 'campaign', 'quantity', 'order']
    list_filter = ['campaign']
    search_fields = ['name', 'campaign__name']


@admin.register(SubmissionCode)
class SubmissionCodeAdmin(ModelAdmin):
    list_display = ['code', 'campaign', 'is_used', 'used_at']
    list_filter = ['campaign', 'is_used']
    search_fields = ['code']
    readonly_fields = ['used_at']


@admin.register(Submission)
class SubmissionAdmin(ModelAdmin):
    list_display = ['full_name', 'email', 'campaign', 'state', 'county', 'submitted_at']
    list_filter = ['campaign', 'state']
    search_fields = ['first_name', 'last_name', 'email', 'phone']
    readonly_fields = ['submitted_at', 'ip_address']

    def full_name(self, obj):
        return obj.full_name
    full_name.short_description = 'Name'


@admin.register(Raffle)
class RaffleAdmin(ModelAdmin):
    list_display = ['campaign', 'conducted_at', 'conducted_by', 'total_participants', 'winner_count']
    list_filter = ['campaign']
    readonly_fields = ['conducted_at', 'total_participants']

    def winner_count(self, obj):
        return obj.winners.count()
    winner_count.short_description = 'Winners'


@admin.register(RaffleWinner)
class RaffleWinnerAdmin(ModelAdmin):
    list_display = ['submission', 'prize', 'raffle', 'position']
    list_filter = ['raffle__campaign', 'prize']
