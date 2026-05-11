from django.db import models
from django.contrib.auth.models import User
from django.utils.text import slugify
import uuid


class Campaign(models.Model):
    name = models.CharField(max_length=200)
    slug = models.SlugField(unique=True, blank=True)
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

    managers = models.ManyToManyField(
        User, blank=True, related_name='managed_campaigns',
        help_text="Users assigned here can view and manage this campaign and its submissions in the dashboard."
    )

    class Meta:
        ordering = ['-created_at']

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
    state = models.CharField(max_length=100)
    county = models.CharField(max_length=100)
    phone = models.CharField(max_length=20)
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
