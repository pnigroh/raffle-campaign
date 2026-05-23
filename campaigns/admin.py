import json
from django import forms
from django.contrib import admin, messages
from django.core.exceptions import PermissionDenied
from django.core.exceptions import ValidationError as DjangoValidationError
from django.db import models as db_models
from django.utils import timezone
from django.utils.html import format_html
from django.urls import reverse
from unfold.admin import ModelAdmin, TabularInline
from .models import Campaign, Domain, Prize, SubmissionCode, Submission, Raffle, RaffleWinner, Store, Theme
from .schema_validator import validate_form_schema


def _user_managed_campaign_ids(request):
    """Return the IDs of campaigns the current user is allowed to manage.

    Superusers see everything (returns None sentinel). Otherwise, routes
    through Campaign.objects.visible_to so domain-only managers (assigned via
    Domain.managers but not Campaign.managers directly) are also included.
    """
    if request.user.is_superuser:
        return None  # sentinel: no filter
    from .models import Campaign  # avoid potential circular import
    return set(Campaign.objects.visible_to(request.user).values_list('id', flat=True))


class CampaignScopedAdminMixin:
    """Filters a model admin to only show rows that belong to a campaign the
    current user is assigned to manage. Each ModelAdmin sets `_campaign_field`
    to the FK lookup that connects the model to a Campaign."""

    _campaign_field = 'campaign'

    def get_queryset(self, request):
        qs = super().get_queryset(request)
        ids = _user_managed_campaign_ids(request)
        if ids is None:
            return qs
        return qs.filter(**{f'{self._campaign_field}__in': ids})

    def has_change_permission(self, request, obj=None):
        if obj is None or request.user.is_superuser:
            return super().has_change_permission(request, obj)
        ids = _user_managed_campaign_ids(request)
        campaign = getattr(obj, self._campaign_field, None)
        # Walk one extra hop for RaffleWinner -> raffle -> campaign
        if hasattr(campaign, 'campaign_id'):
            campaign_id = campaign.campaign_id
        else:
            campaign_id = getattr(campaign, 'id', None)
        return super().has_change_permission(request, obj) and (campaign_id in (ids or []))

    def has_delete_permission(self, request, obj=None):
        return self.has_change_permission(request, obj) and super().has_delete_permission(request, obj)


class HexColorInput(forms.TextInput):
    """Renders an HTML <input type="color"> alongside a small text label."""
    input_type = 'color'


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


@admin.register(Domain)
class DomainAdmin(ModelAdmin):
    list_display = ("hostname", "display_name", "manager_count", "campaign_count")
    search_fields = ("hostname", "display_name")
    filter_horizontal = ("managers",)
    ordering = ("hostname",)

    def get_queryset(self, request):
        return Domain.objects.visible_to(request.user)

    @admin.display(description="Managers")
    def manager_count(self, obj):
        return obj.managers.count()

    @admin.display(description="Campaigns")
    def campaign_count(self, obj):
        return obj.campaigns.count()

    def has_add_permission(self, request):
        return request.user.is_superuser

    def has_delete_permission(self, request, obj=None):
        return request.user.is_superuser


@admin.register(Campaign)
class CampaignAdmin(ModelAdmin):
    list_display = ['name', 'is_active', 'validate_submission_code', 'start_date', 'end_date', 'submission_count', 'logo_thumb', 'dashboard_link']
    list_filter = ['is_active', 'validate_submission_code']
    search_fields = ['name', 'slug']
    prepopulated_fields = {'slug': ('name',)}
    filter_horizontal = ['managers']
    inlines = [PrizeInline]
    fieldsets = (
        ('Basics', {
            'fields': ('name', 'domain', 'slug', 'theme', 'description', 'is_active'),
        }),
        ('Schedule', {
            'fields': ('start_date', 'end_date'),
        }),
        ('Submission rules', {
            'fields': ('validate_submission_code', 'allow_multiple_submissions'),
        }),
        ('Access', {
            'description': "Users listed here can manage this campaign and its submissions in the dashboard. Add them to the \"Campaign Managers\" group too so the right permissions apply.",
            'fields': ('managers',),
        }),
        ('Dashboard branding', {
            'description': "Customize how this campaign looks in the dashboard. Leave blank to use defaults.",
            'fields': ('display_title', 'logo', 'logo_preview', 'primary_color', 'sidebar_color', 'palette_preview'),
        }),
        ('Form configuration', {
            'description': "Paste valid JSON to customise the submission form fields. Leave empty to use the default 9-field layout.",
            'fields': ('form_schema',),
        }),
    )
    readonly_fields = ['logo_preview', 'palette_preview']

    actions = ("reset_form_schema",)

    @admin.action(description="Reset form schema to default (9-field form)")
    def reset_form_schema(self, request, queryset):
        n = queryset.update(form_schema={})
        self.message_user(request, f"Reset {n} campaign(s) to the default form schema.")

    view_on_site = True

    def get_view_on_site_url(self, obj=None):
        if obj is None:
            return None
        return obj.public_url

    def get_queryset(self, request):
        return Campaign.objects.visible_to(request.user)

    def formfield_for_foreignkey(self, db_field, request, **kwargs):
        if db_field.name == "domain" and request is not None:
            kwargs["queryset"] = Domain.objects.visible_to(request.user)
        return super().formfield_for_foreignkey(db_field, request, **kwargs)

    def save_model(self, request, obj, form, change):
        # Defense-in-depth: even if the form's queryset filter was bypassed,
        # reject cross-tenant domain assignments here.
        if not request.user.is_superuser:
            if obj.domain_id not in Domain.objects.visible_to(
                request.user
            ).values_list("id", flat=True):
                raise PermissionDenied("You don't manage that domain.")

        if change:
            old = Campaign.objects.get(pk=obj.pk)
            if old.slug != obj.slug or old.domain_id != obj.domain_id:
                messages.warning(
                    request,
                    "Public URL changed; previously distributed links no "
                    "longer work.",
                )
        super().save_model(request, obj, form, change)

    def has_change_permission(self, request, obj=None):
        if request.user.is_superuser:
            return True
        if obj is None:
            return super().has_change_permission(request, obj)
        return Campaign.objects.visible_to(request.user).filter(pk=obj.pk).exists()

    def has_delete_permission(self, request, obj=None):
        if request.user.is_superuser:
            return super().has_delete_permission(request, obj)
        # Managers can't delete the campaign itself, only manage its data
        return False

    formfield_overrides = {
        db_models.JSONField: {
            "widget": forms.Textarea(attrs={
                "rows": 12,
                "style": "font-family: monospace; width: 100%;",
            }),
        },
    }

    def get_form(self, request, obj=None, **kwargs):
        FormCls = super().get_form(request, obj, **kwargs)
        for field_name in ('primary_color', 'sidebar_color'):
            if field_name in FormCls.base_fields:
                f = FormCls.base_fields[field_name]
                f.widget = HexColorInput(attrs={
                    'style': 'width:60px; height:38px; padding:2px; border-radius:8px;',
                })
                # Browsers' <input type="color"> requires a 7-char hex; if blank,
                # the widget renders as black. Keep CharField blank=True semantics
                # — strip empty submissions so the model stays unset.
                if not f.required:
                    f.required = False

        class FormWithSchemaValidation(FormCls):
            def clean_form_schema(self):
                value = self.cleaned_data.get("form_schema")
                # Django coerces JSONField input to Python. If a string sneaks
                # in (e.g. via a textarea widget), parse defensively.
                if isinstance(value, str):
                    try:
                        value = json.loads(value) if value.strip() else {}
                    except json.JSONDecodeError as exc:
                        raise DjangoValidationError(f"Invalid JSON: {exc}")
                errors = validate_form_schema(value or {})
                if errors:
                    msgs = [f"{e['path']}: {e['message']}" for e in errors]
                    raise DjangoValidationError(msgs)
                return value

        return FormWithSchemaValidation

    def submission_count(self, obj):
        return obj.submissions.count()
    submission_count.short_description = 'Submissions'

    def dashboard_link(self, obj):
        url = reverse('campaign_detail', args=[obj.id])
        return format_html('<a href="{}">View Dashboard →</a>', url)
    dashboard_link.short_description = 'Dashboard'

    def logo_thumb(self, obj):
        if obj.logo:
            return format_html('<img src="{}" style="height:28px; border-radius:4px;" />', obj.logo.url)
        return '—'
    logo_thumb.short_description = 'Logo'

    def logo_preview(self, obj):
        if obj.logo:
            return format_html(
                '<img src="{}" style="max-height:120px; border-radius:8px; border:1px solid #e5e7eb;" />',
                obj.logo.url,
            )
        return format_html('<span style="color:#94a3b8;">No logo uploaded yet.</span>')
    logo_preview.short_description = 'Logo preview'

    def palette_preview(self, obj):
        primary = obj.brand_primary
        sidebar = obj.brand_sidebar
        return format_html(
            '<div style="display:flex; gap:10px; align-items:center;">'
            '<div style="display:flex; flex-direction:column; gap:4px; align-items:center;">'
            '<div style="width:48px; height:48px; border-radius:8px; background:{}; border:1px solid #e5e7eb;"></div>'
            '<small style="color:#64748b;">{}</small><small style="color:#64748b;">primary</small>'
            '</div>'
            '<div style="display:flex; flex-direction:column; gap:4px; align-items:center;">'
            '<div style="width:48px; height:48px; border-radius:8px; background:{}; border:1px solid #e5e7eb;"></div>'
            '<small style="color:#64748b;">{}</small><small style="color:#64748b;">sidebar</small>'
            '</div>'
            '</div>',
            primary, primary, sidebar, sidebar,
        )
    palette_preview.short_description = 'Color preview'


@admin.register(Prize)
class PrizeAdmin(CampaignScopedAdminMixin, ModelAdmin):
    list_display = ['name', 'campaign', 'quantity', 'order']
    list_filter = ['campaign']
    search_fields = ['name', 'campaign__name']


@admin.register(SubmissionCode)
class SubmissionCodeAdmin(CampaignScopedAdminMixin, ModelAdmin):
    list_display = ['code', 'campaign', 'is_used', 'used_at']
    list_filter = ['campaign', 'is_used']
    search_fields = ['code']
    readonly_fields = ['used_at']


@admin.register(Store)
class StoreAdmin(ModelAdmin):
    list_display = ['name', 'is_active', 'order', 'submission_count']
    list_editable = ['is_active', 'order']
    list_filter = ['is_active']
    search_fields = ['name']
    ordering = ['order', 'name']

    def submission_count(self, obj):
        return obj.submissions.count()
    submission_count.short_description = 'Submissions'


@admin.register(Submission)
class SubmissionAdmin(CampaignScopedAdminMixin, ModelAdmin):
    list_display = ['full_name', 'email', 'campaign', 'store', 'validity_badge', 'submitted_at']
    list_filter = ['is_valid', 'campaign', 'store', 'state']
    search_fields = ['first_name', 'last_name', 'email', 'phone']
    readonly_fields = ['submitted_at', 'ip_address', 'image_1_preview', 'image_2_preview', 'validated_at', 'validated_by',
                       'participated_at', 'eligibility_restored_at', 'eligibility_restored_by', 'eligibility_restoration_reason']
    autocomplete_fields = ['store']
    actions = ['mark_valid', 'mark_invalid']
    fieldsets = (
        ('Validity', {
            'fields': ('is_valid', 'invalidation_reason', 'validated_at', 'validated_by'),
        }),
        ('Entrant', {
            'fields': ('campaign', 'submission_code', 'first_name', 'last_name', 'email', 'phone'),
        }),
        ('Location', {
            'fields': ('state', 'county'),
        }),
        ('Purchase', {
            'fields': ('store', 'image_1', 'image_1_preview', 'image_2', 'image_2_preview'),
        }),
        ('Meta', {
            'fields': ('submitted_at', 'ip_address'),
        }),
        ('Participation lifecycle', {
            'fields': ('participated_at', 'eligibility_restored_at',
                       'eligibility_restored_by', 'eligibility_restoration_reason'),
            'description': "Use the dashboard's 'Restaurar elegibilidad' button to flip a participated submission back to eligible — it records the audit trail. These fields are read-only here.",
        }),
    )

    def full_name(self, obj):
        return obj.full_name
    full_name.short_description = 'Name'

    def validity_badge(self, obj):
        if obj.is_valid:
            return format_html(
                '<span style="display:inline-block; padding:2px 10px; border-radius:12px; background:#dcfce7; color:#166534; font-size:11px; font-weight:600;">Valid</span>'
            )
        return format_html(
            '<span style="display:inline-block; padding:2px 10px; border-radius:12px; background:#fee2e2; color:#991b1b; font-size:11px; font-weight:600;" title="{}">Invalid</span>',
            obj.invalidation_reason or '',
        )
    validity_badge.short_description = 'Validity'

    def save_model(self, request, obj, form, change):
        # Track validation events when is_valid is changed via the form
        if change and 'is_valid' in form.changed_data:
            obj.validated_at = timezone.now()
            obj.validated_by = request.user
            if obj.is_valid:
                obj.invalidation_reason = ''
        super().save_model(request, obj, form, change)

    def mark_valid(self, request, queryset):
        count = queryset.update(
            is_valid=True,
            invalidation_reason='',
            validated_at=timezone.now(),
            validated_by=request.user,
        )
        self.message_user(request, f'{count} submission(s) marked as valid.', messages.SUCCESS)
    mark_valid.short_description = "Mark selected submissions as valid"

    def mark_invalid(self, request, queryset):
        count = queryset.update(
            is_valid=False,
            validated_at=timezone.now(),
            validated_by=request.user,
        )
        self.message_user(request, f'{count} submission(s) marked as invalid.', messages.WARNING)
    mark_invalid.short_description = "Mark selected submissions as invalid"

    def _img(self, field):
        if field:
            return format_html('<img src="{}" style="max-height:160px; border-radius:6px;" />', field.url)
        return '—'

    def image_1_preview(self, obj):
        return self._img(obj.image_1)
    image_1_preview.short_description = 'Image 1 preview'

    def image_2_preview(self, obj):
        return self._img(obj.image_2)
    image_2_preview.short_description = 'Image 2 preview'


@admin.register(Raffle)
class RaffleAdmin(CampaignScopedAdminMixin, ModelAdmin):
    list_display = ['campaign', 'conducted_at', 'conducted_by', 'total_participants', 'winner_count']
    list_filter = ['campaign']
    readonly_fields = [
        'conducted_at', 'total_participants',
        'seed', 'algorithm', 'algorithm_version',
        'participant_pool_snapshot', 'prize_quantities',
        'consumed_pool', 'excluded_already_participated',
        'filter_search', 'filter_store_id',
    ]

    def winner_count(self, obj):
        return obj.winners.count()
    winner_count.short_description = 'Winners'


@admin.register(RaffleWinner)
class RaffleWinnerAdmin(ModelAdmin):
    list_display = ['submission', 'prize', 'raffle', 'position']
    list_filter = ['raffle__campaign', 'prize']

    def get_queryset(self, request):
        qs = super().get_queryset(request)
        ids = _user_managed_campaign_ids(request)
        if ids is None:
            return qs
        return qs.filter(raffle__campaign_id__in=ids)


from .themes_upload import extract_bundle


class ThemeUploadForm(forms.ModelForm):
    bundle = forms.FileField(
        required=False,
        help_text=(
            "Upload a .zip containing submission_form.html, "
            "submission_success.html, and an optional assets/ directory. "
            "Max 10 MB."
        ),
    )

    class Meta:
        model = Theme
        fields = ("name", "slug", "description", "is_default", "bundle")


@admin.register(Theme)
class ThemeAdmin(ModelAdmin):
    form = ThemeUploadForm
    list_display = ("name", "slug", "is_default", "created_by", "created_at")
    search_fields = ("name", "slug", "description")
    readonly_fields = ("created_at", "created_by")

    def has_module_permission(self, request):
        return request.user.is_superuser

    def has_add_permission(self, request):
        return request.user.is_superuser

    def has_change_permission(self, request, obj=None):
        return request.user.is_superuser

    def has_delete_permission(self, request, obj=None):
        return request.user.is_superuser

    def save_model(self, request, obj, form, change):
        if not change:
            obj.created_by = request.user
        super().save_model(request, obj, form, change)
        bundle = form.cleaned_data.get("bundle")
        if bundle:
            extract_bundle(bundle, obj)


# ============================================================
# Promo-Domo admin branding
# ============================================================
admin.site.site_header = "Promo-Domo Admin"
admin.site.site_title = "Promo-Domo"
admin.site.index_title = "Campaign Operations"
