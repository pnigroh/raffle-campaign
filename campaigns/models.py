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
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

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
    submitted_at = models.DateTimeField(auto_now_add=True)
    ip_address = models.GenericIPAddressField(null=True, blank=True)

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
