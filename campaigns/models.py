import shutil
import uuid

from django.db import models
from django.contrib.auth.models import User
from django.db.models.signals import post_delete
from django.dispatch import receiver
from django.utils.text import slugify

from .managers import CampaignQuerySet, DomainQuerySet


class Domain(models.Model):
    hostname = models.CharField(max_length=253, unique=True)
    display_name = models.CharField(max_length=200, blank=True)
    managers = models.ManyToManyField(
        "auth.User",
        blank=True,
        related_name="managed_domains",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    objects = DomainQuerySet.as_manager()

    class Meta:
        ordering = ["hostname"]

    def __str__(self):
        return self.hostname


class Campaign(models.Model):
    name = models.CharField(max_length=200)
    domain = models.ForeignKey(
        Domain,
        on_delete=models.PROTECT,
        related_name="campaigns",
    )
    slug = models.SlugField(blank=True)
    description = models.TextField(blank=True)
    start_date = models.DateTimeField()
    end_date = models.DateTimeField()
    is_active = models.BooleanField(default=True)
    validate_submission_code = models.BooleanField(
        default=True,
        help_text="If enabled, submission codes will be validated before saving a submission."
    )
    allow_multiple_submissions = models.BooleanField(
        default=False,
        help_text="Allow the same email to submit multiple times."
    )

    # --- Per-campaign dashboard branding ---
    display_title = models.CharField(
        max_length=200, blank=True,
        help_text="Title shown in the dashboard sidebar/topbar when viewing this campaign. Falls back to the campaign name if blank."
    )
    logo = models.ImageField(
        upload_to='campaign_logos/', blank=True, null=True,
        help_text="Logo shown in the dashboard sidebar when viewing this campaign."
    )
    primary_color = models.CharField(
        max_length=7, blank=True,
        help_text="Brand accent color (hex, e.g. #e30613). Drives buttons, badges and highlights on this campaign's dashboard."
    )
    sidebar_color = models.CharField(
        max_length=7, blank=True,
        help_text="Sidebar background color (hex, e.g. #1a2035). Optional. Falls back to a dark default if blank."
    )
    theme = models.ForeignKey(
        "Theme",
        on_delete=models.PROTECT,
        related_name="campaigns",
        null=True,
        blank=True,
    )

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    @property
    def brand_title(self):
        return self.display_title or self.name

    @property
    def brand_primary(self):
        # Default to Promo-Domo coral when the admin hasn't picked a custom color.
        return self.primary_color or '#FB7185'

    @property
    def brand_sidebar(self):
        # Default to Promo-Domo cream-soft when the admin hasn't picked a custom color.
        return self.sidebar_color or '#FFFBEB'

    @property
    def needs_dark_text(self):
        """True when the effective sidebar color is light enough that dark
        (ink) text reads better than white. Falls back to True for unset or
        malformed colors so the cream Promo-Domo default gets ink text.
        Threshold of 0.55 perceived luminance (rec. 601 weights).
        """
        color = (self.sidebar_color or '').strip()
        if len(color) != 7 or not color.startswith('#'):
            return True
        try:
            r = int(color[1:3], 16)
            g = int(color[3:5], 16)
            b = int(color[5:7], 16)
        except ValueError:
            return True
        luminance = (0.299 * r + 0.587 * g + 0.114 * b) / 255
        return luminance > 0.55

    form_schema = models.JSONField(
        default=dict,
        blank=True,
        help_text="Field schema for this campaign's submission form. "
                  "Leave empty (or '{}') to use the default 9-field schema. "
                  "See docs/superpowers/specs/2026-05-22-flexible-form-fields-design.md.",
    )

    managers = models.ManyToManyField(
        User, blank=True, related_name='managed_campaigns',
        help_text="Users assigned here can view and manage this campaign and its submissions in the dashboard."
    )

    objects = CampaignQuerySet.as_manager()

    class Meta:
        ordering = ['-created_at']
        constraints = [
            models.UniqueConstraint(
                fields=["domain", "slug"],
                name="unique_slug_per_domain",
            ),
        ]

    @property
    def public_url(self):
        return f"https://{self.domain.hostname}/submit/{self.slug}/"

    def __str__(self):
        return self.name

    def save(self, *args, **kwargs):
        if not self.slug:
            self.slug = slugify(self.name)
        super().save(*args, **kwargs)

    @property
    def submission_count(self):
        return self.submissions.count()

    @property
    def unused_codes_count(self):
        return self.submission_codes.filter(is_used=False).count()


class Prize(models.Model):
    campaign = models.ForeignKey(Campaign, on_delete=models.CASCADE, related_name='prizes')
    name = models.CharField(max_length=200)
    description = models.TextField(blank=True)
    quantity = models.PositiveIntegerField(default=1)
    order = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ['order', 'name']

    def __str__(self):
        return f"{self.name} ({self.campaign.name})"


class Store(models.Model):
    name = models.CharField(max_length=200, unique=True)
    is_active = models.BooleanField(
        default=True,
        help_text="Inactive stores are hidden from the public submission form."
    )
    order = models.PositiveIntegerField(default=0, help_text="Lower values appear first.")
    created_at = models.DateTimeField(auto_now_add=True)
    campaigns = models.ManyToManyField(
        Campaign, related_name="stores", blank=True,
        help_text="Campaigns this store appears in. "
                  "Stores with no campaigns are hidden from all public forms.",
    )

    class Meta:
        ordering = ['order', 'name']

    def __str__(self):
        return self.name


class SubmissionCode(models.Model):
    campaign = models.ForeignKey(Campaign, on_delete=models.CASCADE, related_name='submission_codes')
    code = models.CharField(max_length=100)
    is_used = models.BooleanField(default=False)
    used_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        unique_together = ['campaign', 'code']
        ordering = ['code']

    def __str__(self):
        return f"{self.code} ({'used' if self.is_used else 'available'})"


class Submission(models.Model):
    campaign = models.ForeignKey(Campaign, on_delete=models.CASCADE, related_name='submissions')
    submission_code = models.OneToOneField(
        SubmissionCode, null=True, blank=True,
        on_delete=models.SET_NULL, related_name='submission'
    )
    first_name = models.CharField(max_length=100)
    last_name = models.CharField(max_length=100)
    state = models.CharField(max_length=100, blank=True)
    county = models.CharField(max_length=100, blank=True)
    phone = models.CharField(max_length=20, blank=True)
    email = models.EmailField()
    store = models.ForeignKey(
        Store, null=True, blank=True,
        on_delete=models.SET_NULL, related_name='submissions',
        help_text="Store where the customer made their qualifying purchase."
    )
    image_1 = models.ImageField(upload_to='submissions/%Y/%m/', blank=True, null=True)
    image_2 = models.ImageField(upload_to='submissions/%Y/%m/', blank=True, null=True)
    submitted_at = models.DateTimeField(auto_now_add=True)
    ip_address = models.GenericIPAddressField(null=True, blank=True)
    extra_data = models.JSONField(
        default=dict, blank=True,
        help_text="Custom field values keyed by schema 'key'. Excludes file uploads.",
    )

    is_valid = models.BooleanField(
        default=True,
        help_text="Invalid submissions are excluded from raffles. Toggle from the dashboard or admin."
    )
    validated_at = models.DateTimeField(null=True, blank=True)
    validated_by = models.ForeignKey(
        User, null=True, blank=True,
        on_delete=models.SET_NULL, related_name='validated_submissions',
    )
    invalidation_reason = models.CharField(max_length=200, blank=True)

    # --- Already-participated lifecycle ---
    participated_at = models.DateTimeField(
        null=True, blank=True,
        help_text="Set when this submission was last included in any raffle pool. "
                  "Null = eligible for future draws."
    )
    eligibility_restored_at = models.DateTimeField(
        null=True, blank=True,
        help_text="Timestamp when participated_at was cleared to re-admit this submission to the pool."
    )
    eligibility_restored_by = models.ForeignKey(
        User, null=True, blank=True, on_delete=models.SET_NULL,
        related_name='eligibility_restorations',
    )
    eligibility_restoration_reason = models.CharField(
        max_length=200, blank=True,
        help_text="Staff-provided reason for restoring eligibility."
    )

    class Meta:
        ordering = ['-submitted_at']

    def __str__(self):
        return f"{self.first_name} {self.last_name} - {self.campaign.name}"

    @property
    def full_name(self):
        return f"{self.first_name} {self.last_name}"


class Raffle(models.Model):
    campaign = models.ForeignKey(Campaign, on_delete=models.CASCADE, related_name='raffles')
    conducted_at = models.DateTimeField(auto_now_add=True)
    conducted_by = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True, related_name='raffles'
    )
    notes = models.TextField(blank=True)
    segment_state = models.CharField(max_length=100, blank=True)
    segment_county = models.CharField(max_length=100, blank=True)
    segment_date_from = models.DateField(null=True, blank=True)
    segment_date_to = models.DateField(null=True, blank=True)
    total_participants = models.PositiveIntegerField(default=0)

    # --- Audit + reproducibility ---
    seed = models.CharField(
        max_length=64, blank=True,
        help_text="Hex string passed to random.Random(seed). 32 chars from os.urandom(16) by default."
    )
    algorithm = models.CharField(
        max_length=64, default='python.random.shuffle',
        help_text="Identifier for the RNG algorithm. Bump algorithm_version if behavior changes."
    )
    algorithm_version = models.CharField(max_length=16, default='1.0')
    participant_pool_snapshot = models.JSONField(
        default=list, blank=True,
        help_text="Ordered list of submission IDs as they were passed to the shuffler."
    )
    prize_quantities = models.JSONField(
        default=list, blank=True,
        help_text="List of {prize_id, prize_name, quantity} so the audit page is "
                  "readable even after a Prize is renamed or deleted."
    )
    consumed_pool = models.BooleanField(
        default=True,
        help_text="True if participated_at was set on every pool member after the draw."
    )
    excluded_already_participated = models.BooleanField(
        default=True,
        help_text="True if the pool was restricted to submissions where participated_at is null."
    )
    filter_search = models.CharField(
        max_length=200, blank=True,
        help_text="Free-text search string applied to the pool query at draw time. Blank = no filter."
    )
    filter_store_id = models.IntegerField(
        null=True, blank=True,
        help_text="Store PK used to filter the pool at draw time. Stored as int (not FK) to survive Store deletion."
    )

    class Meta:
        ordering = ['-conducted_at']

    def __str__(self):
        return f"Raffle for {self.campaign.name} on {self.conducted_at.strftime('%Y-%m-%d %H:%M')}"


class RaffleWinner(models.Model):
    raffle = models.ForeignKey(Raffle, on_delete=models.CASCADE, related_name='winners')
    submission = models.ForeignKey(Submission, on_delete=models.CASCADE, related_name='wins')
    prize = models.ForeignKey(Prize, on_delete=models.CASCADE, related_name='winners')
    position = models.PositiveIntegerField(default=1)

    class Meta:
        ordering = ['prize__order', 'position']
        unique_together = ['raffle', 'submission']

    def __str__(self):
        return f"{self.submission.full_name} won {self.prize.name}"


class Theme(models.Model):
    name = models.CharField(max_length=200)
    slug = models.SlugField(unique=True)
    description = models.CharField(max_length=500, blank=True)
    is_default = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)
    created_by = models.ForeignKey(
        "auth.User",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="themes_created",
    )

    class Meta:
        ordering = ["name"]
        constraints = [
            models.UniqueConstraint(
                fields=["is_default"],
                condition=models.Q(is_default=True),
                name="only_one_default_theme",
            ),
        ]

    def __str__(self):
        return self.name

    @property
    def directory(self):
        from pathlib import Path
        from django.conf import settings as dj_settings
        return Path(dj_settings.THEMES_ROOT) / self.slug

    def save(self, *args, **kwargs):
        if self.is_default:
            Theme.objects.filter(is_default=True).exclude(pk=self.pk).update(
                is_default=False
            )
        super().save(*args, **kwargs)

    @classmethod
    def get_default(cls):
        return cls.objects.get(is_default=True)


@receiver(post_delete, sender=Theme)
def _remove_theme_directory(sender, instance, **kwargs):
    """When a Theme row is deleted, remove its on-disk directory.

    Protected by Campaign.theme's on_delete=PROTECT: deletion only fires
    when no Campaign references the theme.
    """
    if instance.directory.exists():
        shutil.rmtree(instance.directory)


class SubmissionAttachment(models.Model):
    submission = models.ForeignKey(
        Submission, on_delete=models.CASCADE, related_name="attachments",
    )
    schema_key = models.CharField(max_length=64)
    file = models.FileField(upload_to="submissions/extras/%Y/%m/")
    uploaded_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = [("submission", "schema_key")]
        ordering = ["uploaded_at"]

    def __str__(self):
        return f"{self.submission_id}:{self.schema_key}"
