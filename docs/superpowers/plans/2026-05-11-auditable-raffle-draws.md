# Auditable raffle draws + consumable participant pool — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make every raffle draw reproducible and internally auditable, expand the participant-pool filter, and add an "Already Participated" lifecycle on submissions with operator-restorable eligibility.

**Architecture:** One migration adds the audit fields to `Raffle` and the participation-state fields to `Submission`. `conduct_raffle()` is refactored to take an explicit seed (auto-generated when absent), use an isolated `random.Random(seed)`, persist the participant pool snapshot in canonical order, save filter and toggle context, and post-draw mark all pool members as participated when `consume_pool=True`. A `verify_raffle_audit()` helper re-runs the recorded inputs and reports whether the winners reproduce. New views render the audit page and JSON export, and the restore-eligibility flow.

**Tech Stack:** Django 4.2, JSONField (SQLite-native), `secrets.token_hex`, `random.Random`, Bootstrap 5 modals.

**Spec:** `docs/superpowers/specs/2026-05-11-auditable-raffle-draws.md`

---

## File Structure

**Create:**
- `campaigns/migrations/0006_raffle_audit_and_submission_participated_at.py` — single migration adding all new model fields.
- `campaigns/templates/campaigns/raffle_audit.html` — full-page audit view, extends `base.html`.
- `campaigns/templates/campaigns/_restore_eligibility_modal.html` — single modal partial included from `campaign_detail.html`.
- `campaigns/tests/test_raffle_audit.py` — ~24 tests covering reproducibility, lifecycle, filters, restore, audit page, JSON export, verification.

**Modify:**
- `campaigns/models.py` — `Submission` gains `participated_at` + 3 restoration fields; `Raffle` gains `seed`, `algorithm`, `algorithm_version`, `participant_pool_snapshot`, `prize_quantities`, `consumed_pool`, `excluded_already_participated`, `filter_search`, `filter_store_id`.
- `campaigns/utils.py` — refactor `conduct_raffle()`; add `verify_raffle_audit()` helper.
- `campaigns/forms.py` — `RaffleSegmentForm` gains `search`, `store`, `include_already_participated`, `consume_pool`.
- `campaigns/views.py` — update `raffle_view` and `ajax_filter_count` to honor new filters; add `raffle_audit`, `raffle_audit_json`, `submission_restore_eligibility`.
- `campaigns/urls.py` — three new URL patterns.
- `campaigns/templates/campaigns/raffle.html` — render new form fields.
- `campaigns/templates/campaigns/campaign_detail.html` — Estado column on submissions table; Audit button in raffle history; include restore-eligibility modal + JS.
- `campaigns/admin.py` — register the new audit fields as readonly on `RaffleAdmin` for superuser inspection.

**Out of scope per spec:** cryptographic verification, per-row include/exclude during draw, named pool segments, bulk eligibility restoration, audit logs for non-raffle entities.

---

## Task 1: Data model — migration adds audit + participation fields

**Files:**
- Modify: `campaigns/models.py`
- Create: `campaigns/migrations/0006_raffle_audit_and_submission_participated_at.py` (auto-generated)
- Modify: `campaigns/tests/test_raffle_audit.py` (new file in this task)

- [ ] **Step 1: Create the test file with two model-default tests**

Create `campaigns/tests/test_raffle_audit.py`:

```python
"""Tests for the auditable raffle draws + consumable participant pool feature.

Spec: docs/superpowers/specs/2026-05-11-auditable-raffle-draws.md
"""

from datetime import timedelta

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.utils import timezone

from campaigns.models import Campaign, Prize, Raffle, RaffleWinner, Store, Submission

User = get_user_model()


def _campaign(name="Test", slug="test", manager=None):
    now = timezone.now()
    c = Campaign.objects.create(
        name=name,
        slug=slug,
        description=f"{name} description",
        start_date=now - timedelta(days=1),
        end_date=now + timedelta(days=7),
        is_active=True,
        validate_submission_code=False,
        allow_multiple_submissions=False,
    )
    if manager:
        c.managers.add(manager)
    return c


def _submission(campaign, first_name="Test", last_name="User", **kwargs):
    return Submission.objects.create(
        campaign=campaign,
        first_name=first_name,
        last_name=last_name,
        phone=kwargs.pop("phone", "555-0000"),
        email=kwargs.pop("email", f"{first_name.lower()}{last_name.lower()}@example.com"),
        **kwargs,
    )


class ModelDefaultsTests(TestCase):
    """Pin down the new field defaults so a future migration can't silently change them."""

    def setUp(self):
        self.alice = User.objects.create_user("alice", password="pw", is_staff=True)
        self.campaign = _campaign(manager=self.alice)

    def test_submission_participated_at_defaults_to_null(self):
        sub = _submission(self.campaign)
        self.assertIsNone(sub.participated_at)
        self.assertIsNone(sub.eligibility_restored_at)
        self.assertIsNone(sub.eligibility_restored_by)
        self.assertEqual(sub.eligibility_restoration_reason, "")

    def test_raffle_audit_fields_default_safely(self):
        raffle = Raffle.objects.create(campaign=self.campaign, conducted_by=self.alice)
        self.assertEqual(raffle.seed, "")
        self.assertEqual(raffle.algorithm, "python.random.shuffle")
        self.assertEqual(raffle.algorithm_version, "1.0")
        self.assertEqual(raffle.participant_pool_snapshot, [])
        self.assertEqual(raffle.prize_quantities, [])
        self.assertTrue(raffle.consumed_pool)
        self.assertTrue(raffle.excluded_already_participated)
        self.assertEqual(raffle.filter_search, "")
        self.assertIsNone(raffle.filter_store_id)
```

- [ ] **Step 2: Run the tests to verify they fail**

```bash
docker exec raffle-web python manage.py test campaigns.tests.test_raffle_audit.ModelDefaultsTests -v 2
```

Expected: ERRORS — fields don't exist yet (`AttributeError` or migration mismatch).

- [ ] **Step 3: Add the new model fields**

In `campaigns/models.py`, find the `Submission` class. After the existing `invalidation_reason` field (around line 177), add:

```python
    # --- Already-participated lifecycle ---
    participated_at = models.DateTimeField(
        null=True, blank=True,
        help_text="Set when this submission was last included in any raffle pool. "
                  "Null = eligible for future draws."
    )
    eligibility_restored_at = models.DateTimeField(null=True, blank=True)
    eligibility_restored_by = models.ForeignKey(
        User, null=True, blank=True, on_delete=models.SET_NULL,
        related_name='eligibility_restorations',
    )
    eligibility_restoration_reason = models.CharField(max_length=200, blank=True)
```

In the same file, find the `Raffle` class. After the existing `total_participants` field (around line 201), add:

```python
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
    filter_search = models.CharField(max_length=200, blank=True)
    filter_store_id = models.IntegerField(null=True, blank=True)
```

- [ ] **Step 4: Generate the migration**

```bash
docker exec raffle-web python manage.py makemigrations campaigns -n raffle_audit_and_submission_participated_at
```

Expected output:

```
Migrations for 'campaigns':
  campaigns/migrations/0006_raffle_audit_and_submission_participated_at.py
    - Add field algorithm to raffle
    - Add field algorithm_version to raffle
    ... (etc, one line per added field)
```

Verify the file landed:

```bash
ls campaigns/migrations/0006_*.py
```

- [ ] **Step 5: Apply the migration**

```bash
docker exec raffle-web python manage.py migrate campaigns
```

Expected: `Applying campaigns.0006_raffle_audit_and_submission_participated_at... OK`

- [ ] **Step 6: Run the tests to verify they pass**

```bash
docker exec raffle-web python manage.py test campaigns.tests.test_raffle_audit.ModelDefaultsTests -v 2
```

Expected: 2/2 pass.

Also confirm the full suite still passes (the migration shouldn't break anything else):

```bash
docker exec raffle-web python manage.py test -v 1
```

Expected: 73/73 (71 prior + 2 new).

- [ ] **Step 7: Commit AND PUSH**

```bash
git add campaigns/models.py campaigns/migrations/0006_raffle_audit_and_submission_participated_at.py campaigns/tests/test_raffle_audit.py
git commit -m "feat(audit): add Submission.participated_at + Raffle audit fields (model + migration)"
git push origin main
```

---

## Task 2: `conduct_raffle()` refactor — seed, snapshot, JSON, consume_pool

**Files:**
- Modify: `campaigns/utils.py`
- Modify: `campaigns/tests/test_raffle_audit.py`

- [ ] **Step 1: Append the reproducibility tests**

Append to `campaigns/tests/test_raffle_audit.py`:

```python


class ConductRaffleReproducibilityTests(TestCase):
    """The shipped raffle algorithm must be reproducible: same seed + same pool
    must yield the same winner ordering. The seed and pool snapshot must
    persist on the Raffle row."""

    @classmethod
    def setUpTestData(cls):
        cls.alice = User.objects.create_user("alice", password="pw", is_staff=True)
        cls.campaign = _campaign(manager=cls.alice)
        # 12 submissions to make collision-by-chance unlikely in the
        # different-seed test below.
        cls.subs = [
            _submission(cls.campaign, first_name=f"S{i}", email=f"s{i}@example.com")
            for i in range(12)
        ]
        cls.prize = Prize.objects.create(campaign=cls.campaign, name="P", quantity=3)

    def _draw(self, seed):
        from campaigns.utils import conduct_raffle
        qs = self.campaign.submissions.all()
        return conduct_raffle(
            campaign=self.campaign,
            prizes_with_quantities=[(self.prize, 3)],
            submission_qs=qs,
            conducted_by=self.alice,
            seed=seed,
            consume_pool=False,  # don't mutate so we can re-draw
        )

    def test_same_seed_produces_same_winners(self):
        r1 = self._draw(seed="deadbeef" * 4)
        r2 = self._draw(seed="deadbeef" * 4)
        self.assertEqual(
            list(r1.winners.values_list("submission_id", "position")),
            list(r2.winners.values_list("submission_id", "position")),
        )

    def test_different_seeds_produce_different_winners(self):
        r1 = self._draw(seed="aaaaaaaa" * 4)
        r2 = self._draw(seed="bbbbbbbb" * 4)
        ids1 = set(r1.winners.values_list("submission_id", flat=True))
        ids2 = set(r2.winners.values_list("submission_id", flat=True))
        # With 12 submissions and 3 winners, probability of identical sets
        # by chance is C(3,3)/C(12,3) = 1/220 ≈ 0.45%.
        self.assertNotEqual(ids1, ids2)

    def test_seed_is_persisted_on_raffle(self):
        r = self._draw(seed=None)  # auto-generate
        self.assertRegex(r.seed, r"^[0-9a-f]{32}$")

    def test_participant_pool_snapshot_uses_canonical_order(self):
        r = self._draw(seed="cafef00d" * 4)
        # Snapshot must be sorted by id (canonical), regardless of QuerySet ordering.
        self.assertEqual(r.participant_pool_snapshot, sorted(s.id for s in self.subs))

    def test_prize_quantities_are_persisted_with_name(self):
        r = self._draw(seed="00000000" * 4)
        self.assertEqual(r.prize_quantities, [
            {"prize_id": self.prize.id, "prize_name": "P", "quantity": 3},
        ])

    def test_algorithm_metadata_is_persisted(self):
        r = self._draw(seed="11111111" * 4)
        self.assertEqual(r.algorithm, "python.random.shuffle")
        self.assertEqual(r.algorithm_version, "1.0")


class ConsumePoolTests(TestCase):
    """consume_pool toggle controls whether participants are marked as
    already-participated after the draw."""

    @classmethod
    def setUpTestData(cls):
        cls.alice = User.objects.create_user("alice", password="pw", is_staff=True)
        cls.campaign = _campaign(manager=cls.alice)
        cls.subs = [
            _submission(cls.campaign, first_name=f"S{i}", email=f"s{i}@example.com")
            for i in range(5)
        ]
        cls.prize = Prize.objects.create(campaign=cls.campaign, name="P", quantity=2)

    def test_consume_pool_true_sets_participated_at_on_all_pool_members(self):
        from campaigns.utils import conduct_raffle
        raffle = conduct_raffle(
            campaign=self.campaign,
            prizes_with_quantities=[(self.prize, 2)],
            submission_qs=self.campaign.submissions.all(),
            conducted_by=self.alice,
            consume_pool=True,
        )
        for sub in self.subs:
            sub.refresh_from_db()
            self.assertEqual(sub.participated_at, raffle.conducted_at,
                             f"{sub.first_name} should be marked participated")

    def test_consume_pool_false_leaves_participated_at_null(self):
        from campaigns.utils import conduct_raffle
        conduct_raffle(
            campaign=self.campaign,
            prizes_with_quantities=[(self.prize, 2)],
            submission_qs=self.campaign.submissions.all(),
            conducted_by=self.alice,
            consume_pool=False,
        )
        for sub in self.subs:
            sub.refresh_from_db()
            self.assertIsNone(sub.participated_at)

    def test_consumed_pool_flag_is_persisted_on_raffle(self):
        from campaigns.utils import conduct_raffle
        r1 = conduct_raffle(
            campaign=self.campaign,
            prizes_with_quantities=[(self.prize, 2)],
            submission_qs=self.campaign.submissions.all(),
            conducted_by=self.alice,
            consume_pool=True,
        )
        # Reset so a second draw can run on the same pool
        Submission.objects.filter(campaign=self.campaign).update(participated_at=None)
        r2 = conduct_raffle(
            campaign=self.campaign,
            prizes_with_quantities=[(self.prize, 2)],
            submission_qs=self.campaign.submissions.all(),
            conducted_by=self.alice,
            consume_pool=False,
        )
        self.assertTrue(r1.consumed_pool)
        self.assertFalse(r2.consumed_pool)
```

- [ ] **Step 2: Run the new tests to verify they fail**

```bash
docker exec raffle-web python manage.py test campaigns.tests.test_raffle_audit.ConductRaffleReproducibilityTests campaigns.tests.test_raffle_audit.ConsumePoolTests -v 2
```

Expected: failures — `conduct_raffle` doesn't accept `seed=` or `consume_pool=` yet, and doesn't persist the new fields.

- [ ] **Step 3: Refactor `conduct_raffle()`**

Replace the existing `conduct_raffle` function in `campaigns/utils.py` with this version. First, update the imports at the top of the file:

```python
import csv
import random
import secrets
```

(Add `import secrets` if not already present; keep all other existing imports.)

Then replace the `conduct_raffle` function body with:

```python
def conduct_raffle(campaign, prizes_with_quantities, submission_qs,
                   conducted_by=None, segment_data=None,
                   seed=None, consume_pool=True,
                   excluded_already_participated=True):
    """
    Conduct a raffle.

    prizes_with_quantities: list of (Prize, quantity) tuples
    submission_qs: QuerySet of eligible Submission objects
    seed: hex string for the RNG. If None, generates 32-char hex via secrets.token_hex(16).
    consume_pool: if True, marks every pool member as already-participated after the draw.
    excluded_already_participated: stored on the Raffle to record what filter was applied
        upstream (the filter itself is applied by the view, not here).

    Returns: Raffle object with winners attached.
    """
    from .models import Raffle, RaffleWinner, Submission

    segment_data = segment_data or {}

    if seed is None:
        seed = secrets.token_hex(16)
    rng = random.Random(seed)

    # Canonical order: order_by('id') so the snapshot is deterministic
    # regardless of the QuerySet's default ordering.
    pool = list(submission_qs.order_by('id'))
    snapshot = [s.id for s in pool]
    rng.shuffle(pool)

    raffle = Raffle.objects.create(
        campaign=campaign,
        conducted_by=conducted_by,
        notes=segment_data.get('notes', ''),
        segment_state=segment_data.get('state', ''),
        segment_county=segment_data.get('county', ''),
        segment_date_from=segment_data.get('date_from'),
        segment_date_to=segment_data.get('date_to'),
        total_participants=len(pool),
        seed=seed,
        algorithm='python.random.shuffle',
        algorithm_version='1.0',
        participant_pool_snapshot=snapshot,
        prize_quantities=[
            {'prize_id': p.id, 'prize_name': p.name, 'quantity': q}
            for p, q in prizes_with_quantities
        ],
        consumed_pool=consume_pool,
        excluded_already_participated=excluded_already_participated,
        filter_search=segment_data.get('search', ''),
        filter_store_id=segment_data.get('store_id'),
    )

    used_submissions = set()
    for prize, quantity in prizes_with_quantities:
        count = 0
        for submission in pool:
            if submission.id in used_submissions:
                continue
            if count >= quantity:
                break
            RaffleWinner.objects.create(
                raffle=raffle,
                submission=submission,
                prize=prize,
                position=count + 1,
            )
            used_submissions.add(submission.id)
            count += 1

    if consume_pool and snapshot:
        Submission.objects.filter(id__in=snapshot).update(
            participated_at=raffle.conducted_at,
        )

    return raffle
```

- [ ] **Step 4: Run the refactored tests to verify they pass**

```bash
docker exec raffle-web python manage.py test campaigns.tests.test_raffle_audit -v 2
```

Expected: all tests in `ModelDefaultsTests`, `ConductRaffleReproducibilityTests`, `ConsumePoolTests` pass.

Confirm full suite (no regressions):

```bash
docker exec raffle-web python manage.py test -v 1
```

Expected: all tests pass.

- [ ] **Step 5: Commit AND PUSH**

```bash
git add campaigns/utils.py campaigns/tests/test_raffle_audit.py
git commit -m "feat(audit): conduct_raffle uses isolated seeded RNG, persists snapshot + audit fields"
git push origin main
```

---

## Task 3: Pool filtering — new form fields + view + ajax_filter_count

**Files:**
- Modify: `campaigns/forms.py`
- Modify: `campaigns/views.py`
- Modify: `campaigns/tests/test_raffle_audit.py`

- [ ] **Step 1: Append the filter tests**

Append to `campaigns/tests/test_raffle_audit.py`:

```python


class PoolFilterTests(TestCase):
    """The expanded RaffleSegmentForm filters the pool by search, store, and
    the include_already_participated toggle."""

    @classmethod
    def setUpTestData(cls):
        cls.alice = User.objects.create_user("alice", password="pw", is_staff=True)
        cls.campaign = _campaign(manager=cls.alice)
        cls.store_a = Store.objects.create(name="Store A", is_active=True)
        cls.store_b = Store.objects.create(name="Store B", is_active=True)
        cls.prize = Prize.objects.create(campaign=cls.campaign, name="P", quantity=10)

        cls.alice_sub = _submission(
            cls.campaign, first_name="Alice", last_name="A", email="alice@x.com",
            phone="111", store=cls.store_a,
        )
        cls.bob_sub = _submission(
            cls.campaign, first_name="Bob", last_name="B", email="bob@x.com",
            phone="222", store=cls.store_a,
        )
        cls.cara_sub = _submission(
            cls.campaign, first_name="Cara", last_name="C", email="cara@x.com",
            phone="333", store=cls.store_b,
        )

    def _post_draw(self, **form_data):
        # Ensure all four prize-quantity inputs default sanely
        form_data.setdefault("prize_qty_" + str(self.prize.id), "10")
        self.client.force_login(self.alice)
        from django.urls import reverse
        return self.client.post(
            reverse("raffle", args=[self.campaign.id]),
            data=form_data,
            follow=False,
        )

    def test_search_filter_narrows_pool_by_first_name(self):
        self._post_draw(search="Alice")
        raffle = Raffle.objects.filter(campaign=self.campaign).latest("conducted_at")
        self.assertEqual(raffle.participant_pool_snapshot, [self.alice_sub.id])
        self.assertEqual(raffle.filter_search, "Alice")

    def test_store_filter_narrows_pool(self):
        self._post_draw(store=str(self.store_a.id))
        raffle = Raffle.objects.filter(campaign=self.campaign).latest("conducted_at")
        self.assertEqual(
            sorted(raffle.participant_pool_snapshot),
            sorted([self.alice_sub.id, self.bob_sub.id]),
        )
        self.assertEqual(raffle.filter_store_id, self.store_a.id)

    def test_already_participated_excluded_by_default(self):
        # Mark bob as already-participated
        Submission.objects.filter(id=self.bob_sub.id).update(
            participated_at=timezone.now()
        )
        self._post_draw()
        raffle = Raffle.objects.filter(campaign=self.campaign).latest("conducted_at")
        self.assertNotIn(self.bob_sub.id, raffle.participant_pool_snapshot)
        self.assertTrue(raffle.excluded_already_participated)

    def test_include_already_participated_overrides_default(self):
        Submission.objects.filter(id=self.bob_sub.id).update(
            participated_at=timezone.now()
        )
        self._post_draw(include_already_participated="on")
        raffle = Raffle.objects.filter(campaign=self.campaign).latest("conducted_at")
        self.assertIn(self.bob_sub.id, raffle.participant_pool_snapshot)
        self.assertFalse(raffle.excluded_already_participated)

    def test_invalid_submissions_always_excluded(self):
        Submission.objects.filter(id=self.cara_sub.id).update(is_valid=False)
        self._post_draw()
        raffle = Raffle.objects.filter(campaign=self.campaign).latest("conducted_at")
        self.assertNotIn(self.cara_sub.id, raffle.participant_pool_snapshot)
```

- [ ] **Step 2: Run the new tests to verify they fail**

```bash
docker exec raffle-web python manage.py test campaigns.tests.test_raffle_audit.PoolFilterTests -v 2
```

Expected: failures — `RaffleSegmentForm` doesn't accept `search`, `store`, or `include_already_participated` yet, and `raffle_view` doesn't apply them.

- [ ] **Step 3: Add the new form fields**

In `campaigns/forms.py`, replace the existing `RaffleSegmentForm` class with:

```python
class RaffleSegmentForm(forms.Form):
    state = forms.ChoiceField(
        choices=[('', 'All States')] + list(US_STATES)[1:],
        required=False,
        label='Filter by State'
    )
    county = forms.CharField(max_length=100, required=False, label='Filter by County')
    date_from = forms.DateField(
        required=False, label='Submitted From',
        widget=forms.DateInput(attrs={'type': 'date'})
    )
    date_to = forms.DateField(
        required=False, label='Submitted To',
        widget=forms.DateInput(attrs={'type': 'date'})
    )
    search = forms.CharField(
        max_length=200, required=False,
        label='Search',
        widget=forms.TextInput(attrs={
            'placeholder': 'Nombre, correo o teléfono...',
        }),
    )
    store = forms.ModelChoiceField(
        queryset=Store.objects.filter(is_active=True), required=False,
        empty_label="-- Cualquier tienda --",
        label='Filter by Store',
    )
    include_already_participated = forms.BooleanField(
        required=False,
        label='Incluir participantes que ya han participado',
        help_text='Por defecto, los participantes de sorteos anteriores se excluyen.',
    )
    consume_pool = forms.BooleanField(
        required=False, initial=True,
        label='Marcar participantes como "ya participaron" después del sorteo',
    )
    notes = forms.CharField(
        required=False, label='Raffle Notes',
        widget=forms.Textarea(attrs={'rows': 2, 'placeholder': 'Optional notes about this raffle draw...'})
    )
```

(`Store` is already imported at the top of `forms.py` — `from .models import Campaign, Prize, Submission, SubmissionCode, Store`.)

- [ ] **Step 4: Update `raffle_view` to apply the new filters**

In `campaigns/views.py`, find the `raffle_view` function (around line 206). Replace the inner block that builds `filtered_submissions` and calls `conduct_raffle`. The relevant existing code:

```python
        filtered_submissions = campaign.submissions.filter(is_valid=True)
        if state:
            filtered_submissions = filtered_submissions.filter(state=state)
        if county:
            filtered_submissions = filtered_submissions.filter(county__icontains=county)
        if date_from:
            filtered_submissions = filtered_submissions.filter(submitted_at__date__gte=date_from)
        if date_to:
            filtered_submissions = filtered_submissions.filter(submitted_at__date__lte=date_to)
```

Replace with:

```python
        filtered_submissions = campaign.submissions.filter(is_valid=True)
        if state:
            filtered_submissions = filtered_submissions.filter(state=state)
        if county:
            filtered_submissions = filtered_submissions.filter(county__icontains=county)
        if date_from:
            filtered_submissions = filtered_submissions.filter(submitted_at__date__gte=date_from)
        if date_to:
            filtered_submissions = filtered_submissions.filter(submitted_at__date__lte=date_to)
        search = segment_form.cleaned_data.get('search', '').strip()
        if search:
            filtered_submissions = filtered_submissions.filter(
                Q(first_name__icontains=search)
                | Q(last_name__icontains=search)
                | Q(email__icontains=search)
                | Q(phone__icontains=search)
            )
        store = segment_form.cleaned_data.get('store')
        if store:
            filtered_submissions = filtered_submissions.filter(store=store)
        include_already_participated = segment_form.cleaned_data.get(
            'include_already_participated', False
        )
        if not include_already_participated:
            filtered_submissions = filtered_submissions.filter(participated_at__isnull=True)
```

Now find the `conduct_raffle(...)` call inside the same view (a few lines later). Replace:

```python
            raffle = conduct_raffle(
                campaign=campaign,
                prizes_with_quantities=prizes_with_quantities,
                submission_qs=filtered_submissions,
                conducted_by=request.user,
                segment_data=segment_form.cleaned_data,
            )
```

With:

```python
            consume_pool = segment_form.cleaned_data.get('consume_pool', True)
            segment_data = dict(segment_form.cleaned_data)
            # Persist the store id (FK object isn't JSON-serializable downstream)
            segment_data['store_id'] = store.id if store else None
            raffle = conduct_raffle(
                campaign=campaign,
                prizes_with_quantities=prizes_with_quantities,
                submission_qs=filtered_submissions,
                conducted_by=request.user,
                segment_data=segment_data,
                consume_pool=consume_pool,
                excluded_already_participated=not include_already_participated,
            )
```

- [ ] **Step 5: Update `ajax_filter_count` to honor the same filters**

In `campaigns/views.py`, find `ajax_filter_count` and replace the function body with:

```python
@login_required
def ajax_filter_count(request, campaign_id):
    """AJAX endpoint to get submission count for given filters.

    Mirrors the filtering applied by raffle_view so the live count preview
    accurately predicts the pool size for the next draw.
    """
    campaign = _get_managed_campaign_or_403(request.user, campaign_id)

    state = request.GET.get('state', '')
    county = request.GET.get('county', '')
    date_from = request.GET.get('date_from', '')
    date_to = request.GET.get('date_to', '')
    search = request.GET.get('search', '').strip()
    store_id = request.GET.get('store', '')
    include_already_participated = request.GET.get('include_already_participated') == 'on'

    qs = campaign.submissions.filter(is_valid=True)
    if state:
        qs = qs.filter(state=state)
    if county:
        qs = qs.filter(county__icontains=county)
    if date_from:
        qs = qs.filter(submitted_at__date__gte=date_from)
    if date_to:
        qs = qs.filter(submitted_at__date__lte=date_to)
    if search:
        qs = qs.filter(
            Q(first_name__icontains=search)
            | Q(last_name__icontains=search)
            | Q(email__icontains=search)
            | Q(phone__icontains=search)
        )
    if store_id:
        qs = qs.filter(store_id=store_id)
    if not include_already_participated:
        qs = qs.filter(participated_at__isnull=True)

    return JsonResponse({'count': qs.count()})
```

- [ ] **Step 6: Run the filter tests to verify they pass**

```bash
docker exec raffle-web python manage.py test campaigns.tests.test_raffle_audit.PoolFilterTests -v 2
```

Expected: 5/5 pass.

Full suite:

```bash
docker exec raffle-web python manage.py test -v 1
```

- [ ] **Step 7: Commit AND PUSH**

```bash
git add campaigns/forms.py campaigns/views.py campaigns/tests/test_raffle_audit.py
git commit -m "feat(audit): expand RaffleSegmentForm filters (search, store, include_already_participated, consume_pool)"
git push origin main
```

---

## Task 4: Restore-eligibility view + URL

**Files:**
- Modify: `campaigns/views.py`
- Modify: `campaigns/urls.py`
- Modify: `campaigns/tests/test_raffle_audit.py`

- [ ] **Step 1: Append the restore-eligibility tests**

Append to `campaigns/tests/test_raffle_audit.py`:

```python


class RestoreEligibilityTests(TestCase):
    """Operators (campaign managers) can flip a submission back to eligible
    by POSTing a reason. The reversal is recorded on the submission row."""

    @classmethod
    def setUpTestData(cls):
        cls.alice = User.objects.create_user("alice", password="pw", is_staff=True)
        cls.bob = User.objects.create_user("bob", password="pw", is_staff=True)
        cls.camp_x = _campaign(name="X", slug="x", manager=cls.alice)
        cls.camp_y = _campaign(name="Y", slug="y", manager=cls.bob)
        cls.sub_x = _submission(cls.camp_x, first_name="X", email="x@x.com")
        cls.sub_y = _submission(cls.camp_y, first_name="Y", email="y@y.com")
        # Pre-mark both as already participated
        Submission.objects.filter(id__in=[cls.sub_x.id, cls.sub_y.id]).update(
            participated_at=timezone.now()
        )

    def test_restore_eligibility_clears_participated_at_and_records_audit(self):
        from django.urls import reverse
        self.client.force_login(self.alice)
        resp = self.client.post(
            reverse("submission_restore_eligibility",
                    args=[self.camp_x.id, self.sub_x.id]),
            data={"reason": "Drew the wrong campaign by mistake"},
        )
        self.assertEqual(resp.status_code, 302)
        self.sub_x.refresh_from_db()
        self.assertIsNone(self.sub_x.participated_at)
        self.assertIsNotNone(self.sub_x.eligibility_restored_at)
        self.assertEqual(self.sub_x.eligibility_restored_by, self.alice)
        self.assertEqual(
            self.sub_x.eligibility_restoration_reason,
            "Drew the wrong campaign by mistake",
        )

    def test_restore_eligibility_requires_reason(self):
        from django.urls import reverse
        self.client.force_login(self.alice)
        resp = self.client.post(
            reverse("submission_restore_eligibility",
                    args=[self.camp_x.id, self.sub_x.id]),
            data={"reason": ""},
        )
        self.assertEqual(resp.status_code, 400)
        self.sub_x.refresh_from_db()
        self.assertIsNotNone(self.sub_x.participated_at)  # unchanged

    def test_restore_eligibility_on_already_eligible_returns_400(self):
        from django.urls import reverse
        Submission.objects.filter(id=self.sub_x.id).update(participated_at=None)
        self.client.force_login(self.alice)
        resp = self.client.post(
            reverse("submission_restore_eligibility",
                    args=[self.camp_x.id, self.sub_x.id]),
            data={"reason": "should be a no-op"},
        )
        self.assertEqual(resp.status_code, 400)

    def test_restore_eligibility_non_manager_gets_403(self):
        from django.urls import reverse
        self.client.force_login(self.alice)
        resp = self.client.post(
            reverse("submission_restore_eligibility",
                    args=[self.camp_y.id, self.sub_y.id]),
            data={"reason": "tampering"},
        )
        self.assertEqual(resp.status_code, 403)
        self.sub_y.refresh_from_db()
        self.assertIsNotNone(self.sub_y.participated_at)  # unchanged

    def test_restore_eligibility_get_returns_405(self):
        from django.urls import reverse
        self.client.force_login(self.alice)
        resp = self.client.get(
            reverse("submission_restore_eligibility",
                    args=[self.camp_x.id, self.sub_x.id]),
        )
        self.assertEqual(resp.status_code, 405)
```

- [ ] **Step 2: Run the new tests to verify they fail**

```bash
docker exec raffle-web python manage.py test campaigns.tests.test_raffle_audit.RestoreEligibilityTests -v 2
```

Expected: all errors with `NoReverseMatch: Reverse for 'submission_restore_eligibility' not found`.

- [ ] **Step 3: Add the URL pattern**

In `campaigns/urls.py`, append after the existing `submission_set_validity` line:

```python
    path('dashboard/campaign/<int:campaign_id>/submission/<int:submission_id>/restore-eligibility/',
         views.submission_restore_eligibility, name='submission_restore_eligibility'),
```

- [ ] **Step 4: Add the view**

At the bottom of `campaigns/views.py`, add:

```python
@login_required
@require_POST
def submission_restore_eligibility(request, campaign_id, submission_id):
    """Operator restores a submission's eligibility (clears participated_at
    and records who/when/why)."""
    campaign = _get_managed_campaign_or_403(request.user, campaign_id)
    submission = get_object_or_404(Submission, id=submission_id, campaign=campaign)

    reason = request.POST.get('reason', '').strip()[:200]
    if not reason:
        return JsonResponse(
            {'error': 'A reason is required to restore eligibility.'},
            status=400,
        )
    if submission.participated_at is None:
        return JsonResponse(
            {'error': 'Submission is already eligible.'},
            status=400,
        )

    submission.participated_at = None
    submission.eligibility_restored_at = timezone.now()
    submission.eligibility_restored_by = request.user
    submission.eligibility_restoration_reason = reason
    submission.save(update_fields=[
        'participated_at',
        'eligibility_restored_at',
        'eligibility_restored_by',
        'eligibility_restoration_reason',
    ])
    messages.success(
        request,
        f'Elegibilidad restaurada para {submission.full_name}.',
    )
    return redirect('campaign_detail', campaign_id=campaign.id)
```

- [ ] **Step 5: Run the restore-eligibility tests to verify they pass**

```bash
docker exec raffle-web python manage.py test campaigns.tests.test_raffle_audit.RestoreEligibilityTests -v 2
```

Expected: 5/5 pass.

- [ ] **Step 6: Commit AND PUSH**

```bash
git add campaigns/urls.py campaigns/views.py campaigns/tests/test_raffle_audit.py
git commit -m "feat(audit): add submission_restore_eligibility POST endpoint with reason + audit trail"
git push origin main
```

---

## Task 5: `verify_raffle_audit()` helper

**Files:**
- Modify: `campaigns/utils.py`
- Modify: `campaigns/tests/test_raffle_audit.py`

- [ ] **Step 1: Append the verify tests**

Append to `campaigns/tests/test_raffle_audit.py`:

```python


class VerifyRaffleAuditTests(TestCase):
    """verify_raffle_audit re-runs the recorded inputs and checks the
    winners reproduce. It does NOT mutate state."""

    @classmethod
    def setUpTestData(cls):
        cls.alice = User.objects.create_user("alice", password="pw", is_staff=True)
        cls.campaign = _campaign(manager=cls.alice)
        cls.subs = [
            _submission(cls.campaign, first_name=f"S{i}", email=f"s{i}@example.com")
            for i in range(8)
        ]
        cls.prize = Prize.objects.create(campaign=cls.campaign, name="P", quantity=3)

    def test_verify_succeeds_for_unmodified_raffle(self):
        from campaigns.utils import conduct_raffle, verify_raffle_audit
        raffle = conduct_raffle(
            campaign=self.campaign,
            prizes_with_quantities=[(self.prize, 3)],
            submission_qs=self.campaign.submissions.all(),
            conducted_by=self.alice,
            consume_pool=False,
        )
        result = verify_raffle_audit(raffle)
        self.assertEqual(result['status'], 'ok')
        self.assertIsNone(result.get('diff'))

    def test_verify_fails_when_winners_have_been_tampered_with(self):
        from campaigns.utils import conduct_raffle, verify_raffle_audit
        raffle = conduct_raffle(
            campaign=self.campaign,
            prizes_with_quantities=[(self.prize, 3)],
            submission_qs=self.campaign.submissions.all(),
            conducted_by=self.alice,
            consume_pool=False,
        )
        # Swap the winning submission of position 1 with a non-winner
        winner_1 = raffle.winners.get(position=1)
        all_winner_ids = set(raffle.winners.values_list('submission_id', flat=True))
        non_winner = next(s for s in self.subs if s.id not in all_winner_ids)
        winner_1.submission = non_winner
        winner_1.save()
        result = verify_raffle_audit(raffle)
        self.assertEqual(result['status'], 'mismatch')
        self.assertIsNotNone(result['diff'])

    def test_verify_unverifiable_for_pre_audit_raffle(self):
        from campaigns.utils import verify_raffle_audit
        raffle = Raffle.objects.create(
            campaign=self.campaign, conducted_by=self.alice,
            seed='',  # explicitly empty (pre-feature raffle)
            participant_pool_snapshot=[],
        )
        result = verify_raffle_audit(raffle)
        self.assertEqual(result['status'], 'unverifiable')

    def test_verify_unverifiable_when_pool_submissions_have_been_deleted(self):
        from campaigns.utils import conduct_raffle, verify_raffle_audit
        raffle = conduct_raffle(
            campaign=self.campaign,
            prizes_with_quantities=[(self.prize, 3)],
            submission_qs=self.campaign.submissions.all(),
            conducted_by=self.alice,
            consume_pool=False,
        )
        # Delete one submission from the original pool (admin override scenario).
        # Pick a non-winner so the winners table integrity isn't affected.
        winner_ids = set(raffle.winners.values_list('submission_id', flat=True))
        victim = next(s for s in self.subs if s.id not in winner_ids)
        victim.delete()
        result = verify_raffle_audit(raffle)
        self.assertEqual(result['status'], 'unverifiable')
        self.assertIn('missing', result.get('diff', {}).get('reason', '').lower())
```

- [ ] **Step 2: Run the tests to verify they fail**

```bash
docker exec raffle-web python manage.py test campaigns.tests.test_raffle_audit.VerifyRaffleAuditTests -v 2
```

Expected: ImportError — `verify_raffle_audit` doesn't exist.

- [ ] **Step 3: Add `verify_raffle_audit()`**

Append to `campaigns/utils.py`:

```python
def verify_raffle_audit(raffle):
    """Re-run the recorded raffle inputs and assert the winners reproduce.

    Returns a dict:
      {'status': 'ok'} if winners reproduce exactly.
      {'status': 'mismatch', 'diff': {...}} if winners differ.
      {'status': 'unverifiable', 'diff': {'reason': '...'}} if the raffle predates
        audit logging or some pool members no longer exist in the database.

    Does NOT mutate any data.
    """
    from .models import Submission

    if not raffle.seed or not raffle.participant_pool_snapshot:
        return {'status': 'unverifiable',
                'diff': {'reason': 'Raffle was conducted before audit logging was added.'}}

    snapshot_ids = list(raffle.participant_pool_snapshot)
    pool = list(Submission.objects.filter(id__in=snapshot_ids).order_by('id'))
    if len(pool) != len(snapshot_ids):
        existing_ids = {s.id for s in pool}
        missing = [sid for sid in snapshot_ids if sid not in existing_ids]
        return {'status': 'unverifiable',
                'diff': {'reason': f'{len(missing)} pool submissions are missing from the database.',
                         'missing_ids': missing}}

    rng = random.Random(raffle.seed)
    rng.shuffle(pool)

    expected_winners = []
    used = set()
    for entry in raffle.prize_quantities:
        prize_id = entry['prize_id']
        quantity = entry['quantity']
        count = 0
        for submission in pool:
            if submission.id in used:
                continue
            if count >= quantity:
                break
            expected_winners.append({
                'prize_id': prize_id,
                'submission_id': submission.id,
                'position': count + 1,
            })
            used.add(submission.id)
            count += 1

    actual_winners = [
        {'prize_id': w.prize_id, 'submission_id': w.submission_id, 'position': w.position}
        for w in raffle.winners.order_by('prize__order', 'position')
    ]
    expected_sorted = sorted(expected_winners, key=lambda w: (w['prize_id'], w['position']))
    actual_sorted = sorted(actual_winners, key=lambda w: (w['prize_id'], w['position']))

    if expected_sorted == actual_sorted:
        return {'status': 'ok'}
    return {'status': 'mismatch',
            'diff': {'expected': expected_sorted, 'actual': actual_sorted}}
```

- [ ] **Step 4: Run the verify tests**

```bash
docker exec raffle-web python manage.py test campaigns.tests.test_raffle_audit.VerifyRaffleAuditTests -v 2
```

Expected: 4/4 pass.

- [ ] **Step 5: Commit AND PUSH**

```bash
git add campaigns/utils.py campaigns/tests/test_raffle_audit.py
git commit -m "feat(audit): add verify_raffle_audit() helper that re-runs and compares"
git push origin main
```

---

## Task 6: Audit page — view + URL + template

**Files:**
- Modify: `campaigns/views.py`
- Modify: `campaigns/urls.py`
- Create: `campaigns/templates/campaigns/raffle_audit.html`
- Modify: `campaigns/tests/test_raffle_audit.py`

- [ ] **Step 1: Append the audit-page tests**

Append to `campaigns/tests/test_raffle_audit.py`:

```python


class RaffleAuditPageTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.alice = User.objects.create_user("alice", password="pw", is_staff=True)
        cls.bob = User.objects.create_user("bob", password="pw", is_staff=True)
        cls.camp_x = _campaign(name="X", slug="x", manager=cls.alice)
        cls.camp_y = _campaign(name="Y", slug="y", manager=cls.bob)
        cls.subs = [
            _submission(cls.camp_x, first_name=f"S{i}", email=f"s{i}@example.com")
            for i in range(5)
        ]
        cls.prize = Prize.objects.create(campaign=cls.camp_x, name="P", quantity=2)

    def _draw(self):
        from campaigns.utils import conduct_raffle
        return conduct_raffle(
            campaign=self.camp_x,
            prizes_with_quantities=[(self.prize, 2)],
            submission_qs=self.camp_x.submissions.all(),
            conducted_by=self.alice,
            consume_pool=False,
        )

    def test_audit_page_renders_for_recorded_raffle(self):
        from django.urls import reverse
        raffle = self._draw()
        self.client.force_login(self.alice)
        resp = self.client.get(reverse("raffle_audit", args=[raffle.id]))
        self.assertEqual(resp.status_code, 200)
        body = resp.content.decode()
        self.assertIn(raffle.seed, body)
        self.assertIn("python.random.shuffle", body)
        # All 5 submission IDs from the snapshot appear on the page
        for sub in self.subs:
            self.assertIn(str(sub.id), body)

    def test_audit_page_403_for_non_manager(self):
        from django.urls import reverse
        raffle = self._draw()
        self.client.force_login(self.bob)
        resp = self.client.get(reverse("raffle_audit", args=[raffle.id]))
        self.assertEqual(resp.status_code, 403)

    def test_audit_page_includes_verify_status_in_context(self):
        from django.urls import reverse
        raffle = self._draw()
        self.client.force_login(self.alice)
        resp = self.client.get(reverse("raffle_audit", args=[raffle.id]))
        self.assertEqual(resp.context["verify_result"]["status"], "ok")
```

- [ ] **Step 2: Run the tests to verify they fail**

```bash
docker exec raffle-web python manage.py test campaigns.tests.test_raffle_audit.RaffleAuditPageTests -v 2
```

Expected: NoReverseMatch — `raffle_audit` URL doesn't exist.

- [ ] **Step 3: Add the URL**

In `campaigns/urls.py`, append after the existing `raffle_results` line:

```python
    path('dashboard/raffle/<int:raffle_id>/audit/', views.raffle_audit, name='raffle_audit'),
```

- [ ] **Step 4: Add the view**

At the bottom of `campaigns/views.py`, add:

```python
@login_required
def raffle_audit(request, raffle_id):
    """Render the audit page for a raffle, including verification status."""
    from .utils import verify_raffle_audit
    raffle = get_object_or_404(Raffle, id=raffle_id)
    if not request.user.is_superuser and not raffle.campaign.managers.filter(
        id=request.user.id
    ).exists():
        raise PermissionDenied("You don't have access to this raffle.")

    verify_result = verify_raffle_audit(raffle)
    pool_submissions = list(
        Submission.objects.filter(id__in=raffle.participant_pool_snapshot)
        .order_by('id')
    )
    pool_existing_ids = {s.id for s in pool_submissions}
    missing_pool_ids = [sid for sid in raffle.participant_pool_snapshot
                        if sid not in pool_existing_ids]
    winners = raffle.winners.select_related('submission', 'prize').order_by(
        'prize__order', 'position'
    )
    restored_count = Submission.objects.filter(
        id__in=raffle.participant_pool_snapshot,
        eligibility_restored_at__gte=raffle.conducted_at,
    ).count()

    return render(request, 'campaigns/raffle_audit.html', {
        'raffle': raffle,
        'campaign': raffle.campaign,
        'verify_result': verify_result,
        'pool_submissions': pool_submissions,
        'missing_pool_ids': missing_pool_ids,
        'winners': winners,
        'restored_count': restored_count,
    })
```

- [ ] **Step 5: Create the audit template**

Create `campaigns/templates/campaigns/raffle_audit.html`:

```django
{% extends "campaigns/base.html" %}
{% load i18n %}

{% block title %}{% trans "Auditoría del Sorteo" %} #{{ raffle.id }} · Promo-Domo{% endblock %}
{% block topbar_title %}{% trans "Auditoría del Sorteo" %}{% endblock %}

{% block content %}
<div class="page-header">
  <div class="d-flex align-items-start justify-content-between flex-wrap gap-2">
    <div>
      <h1 class="pd-display">
        <i class="bi bi-shield-check me-2" style="color: var(--pd-coral);"></i>
        {% blocktrans with id=raffle.id %}Auditoría del Sorteo #{{ id }}{% endblocktrans %}
      </h1>
      <nav aria-label="breadcrumb">
        <ol class="breadcrumb">
          <li class="breadcrumb-item"><a href="{% url 'dashboard' %}">{% trans "Tablero" %}</a></li>
          <li class="breadcrumb-item"><a href="{% url 'campaign_detail' campaign.id %}">{{ campaign.name }}</a></li>
          <li class="breadcrumb-item active">{% trans "Auditoría" %} #{{ raffle.id }}</li>
        </ol>
      </nav>
    </div>
    <div class="d-flex gap-2">
      <a href="{% url 'raffle_audit_json' raffle.id %}" class="btn btn-outline-secondary">
        <i class="bi bi-download me-1"></i>{% trans "Descargar JSON" %}
      </a>
      <a href="{% url 'raffle_audit' raffle.id %}" class="btn btn-outline-primary">
        <i class="bi bi-arrow-clockwise me-1"></i>{% trans "Verificar de nuevo" %}
      </a>
    </div>
  </div>
</div>

{# Verification banner #}
{% if verify_result.status == 'ok' %}
  <div class="alert alert-success d-flex align-items-center gap-2 mb-4">
    <i class="bi bi-check-circle-fill"></i>
    <span>{% trans "Auditoría verificada — los ganadores se reprodujeron exactamente." %}</span>
  </div>
{% elif verify_result.status == 'mismatch' %}
  <div class="alert alert-danger d-flex align-items-center gap-2 mb-4">
    <i class="bi bi-x-circle-fill"></i>
    <span>{% trans "AUDITORÍA FALLÓ — los ganadores re-calculados NO coinciden con los almacenados." %}</span>
  </div>
{% else %}
  <div class="alert alert-warning d-flex align-items-center gap-2 mb-4">
    <i class="bi bi-exclamation-triangle-fill"></i>
    <span>{% trans "No se puede verificar:" %} {{ verify_result.diff.reason }}</span>
  </div>
{% endif %}

<div class="row g-3">
  {# Who/When #}
  <div class="col-md-6">
    <div class="card">
      <div class="card-header"><i class="bi bi-person-badge me-2"></i>{% trans "Realización" %}</div>
      <div class="card-body">
        <p class="mb-1"><strong>{% trans "Realizado por:" %}</strong> {{ raffle.conducted_by.username|default:"—" }}</p>
        <p class="mb-1"><strong>{% trans "Fecha:" %}</strong> {{ raffle.conducted_at|date:"d/m/Y H:i:s" }}</p>
        {% if raffle.notes %}<p class="mb-0"><strong>{% trans "Notas:" %}</strong> {{ raffle.notes }}</p>{% endif %}
      </div>
    </div>
  </div>

  {# Algorithm #}
  <div class="col-md-6">
    <div class="card">
      <div class="card-header"><i class="bi bi-cpu me-2"></i>{% trans "Algoritmo" %}</div>
      <div class="card-body">
        <p class="mb-1"><strong>{% trans "Nombre:" %}</strong> <code>{{ raffle.algorithm }}</code></p>
        <p class="mb-1"><strong>{% trans "Versión:" %}</strong> <code>{{ raffle.algorithm_version }}</code></p>
        <p class="mb-0"><strong>{% trans "Semilla:" %}</strong> <code style="word-break:break-all;">{{ raffle.seed|default:"—" }}</code></p>
      </div>
    </div>
  </div>

  {# Filters #}
  <div class="col-12">
    <div class="card">
      <div class="card-header"><i class="bi bi-funnel me-2"></i>{% trans "Filtros aplicados" %}</div>
      <div class="card-body">
        <div class="d-flex flex-wrap gap-3" style="font-size:0.9rem;">
          <div><strong>{% trans "Estado:" %}</strong> {{ raffle.segment_state|default:"—" }}</div>
          <div><strong>{% trans "Municipio:" %}</strong> {{ raffle.segment_county|default:"—" }}</div>
          <div><strong>{% trans "Desde:" %}</strong> {{ raffle.segment_date_from|date:"d/m/Y"|default:"—" }}</div>
          <div><strong>{% trans "Hasta:" %}</strong> {{ raffle.segment_date_to|date:"d/m/Y"|default:"—" }}</div>
          <div><strong>{% trans "Búsqueda:" %}</strong> {{ raffle.filter_search|default:"—" }}</div>
          <div><strong>{% trans "Tienda ID:" %}</strong> {{ raffle.filter_store_id|default:"—" }}</div>
          <div><strong>{% trans "Excluyó ya-participantes:" %}</strong> {{ raffle.excluded_already_participated|yesno:"Sí,No" }}</div>
          <div><strong>{% trans "Consumió pool:" %}</strong> {{ raffle.consumed_pool|yesno:"Sí,No" }}</div>
        </div>
      </div>
    </div>
  </div>

  {# Pool #}
  <div class="col-md-6">
    <div class="card">
      <div class="card-header">
        <i class="bi bi-people me-2"></i>{% trans "Pool de participantes" %}
        <span class="badge bg-primary rounded-pill ms-2">{{ raffle.participant_pool_snapshot|length }}</span>
      </div>
      <div class="card-body" style="max-height:320px; overflow-y:auto;">
        {% if missing_pool_ids %}
          <div class="alert alert-warning py-2 mb-2" style="font-size:0.85rem;">
            {% blocktrans count n=missing_pool_ids|length %}{{ n }} participante del pool original ya no existe en la base de datos.{% plural %}{{ n }} participantes del pool original ya no existen en la base de datos.{% endblocktrans %}
          </div>
        {% endif %}
        <ul class="list-unstyled mb-0" style="font-family:monospace; font-size:0.85rem;">
          {% for sid in raffle.participant_pool_snapshot %}
            <li>#{{ sid }}{% for sub in pool_submissions %}{% if sub.id == sid %} — {{ sub.full_name }}{% endif %}{% endfor %}</li>
          {% endfor %}
        </ul>
      </div>
    </div>
  </div>

  {# Prizes #}
  <div class="col-md-6">
    <div class="card">
      <div class="card-header"><i class="bi bi-trophy me-2"></i>{% trans "Premios sorteados" %}</div>
      <div class="card-body">
        <ul class="list-unstyled mb-0">
          {% for entry in raffle.prize_quantities %}
            <li>{{ entry.prize_name }} — {% blocktrans with q=entry.quantity %}cantidad: {{ q }}{% endblocktrans %} <span class="text-muted">(prize_id: {{ entry.prize_id }})</span></li>
          {% endfor %}
        </ul>
      </div>
    </div>
  </div>

  {# Winners #}
  <div class="col-12">
    <div class="card">
      <div class="card-header"><i class="bi bi-stars me-2"></i>{% trans "Ganadores" %}</div>
      <div class="table-responsive">
        <table class="table table-sm mb-0">
          <thead>
            <tr><th>{% trans "Premio" %}</th><th>{% trans "Posición" %}</th><th>{% trans "Participante" %}</th><th>{% trans "ID" %}</th></tr>
          </thead>
          <tbody>
            {% for w in winners %}
              <tr>
                <td>{{ w.prize.name }}</td>
                <td>{{ w.position }}</td>
                <td>{{ w.submission.full_name }}</td>
                <td><code>{{ w.submission.id }}</code></td>
              </tr>
            {% endfor %}
          </tbody>
        </table>
      </div>
    </div>
  </div>

  {# Restorations #}
  {% if restored_count %}
  <div class="col-12">
    <div class="alert alert-info d-flex align-items-center gap-2">
      <i class="bi bi-arrow-counterclockwise"></i>
      <span>{% blocktrans count n=restored_count %}{{ n }} participante de este sorteo ha tenido su elegibilidad restaurada después del draw.{% plural %}{{ n }} participantes de este sorteo han tenido su elegibilidad restaurada después del draw.{% endblocktrans %}</span>
    </div>
  </div>
  {% endif %}
</div>
{% endblock %}
```

- [ ] **Step 6: Run the audit page tests**

```bash
docker exec raffle-web python manage.py test campaigns.tests.test_raffle_audit.RaffleAuditPageTests -v 2
```

Expected: 3/3 pass.

- [ ] **Step 7: Commit AND PUSH**

```bash
git add campaigns/urls.py campaigns/views.py campaigns/templates/campaigns/raffle_audit.html campaigns/tests/test_raffle_audit.py
git commit -m "feat(audit): raffle audit page (view + URL + template) with verify status"
git push origin main
```

---

## Task 7: Audit JSON export

**Files:**
- Modify: `campaigns/views.py`
- Modify: `campaigns/urls.py`
- Modify: `campaigns/tests/test_raffle_audit.py`

- [ ] **Step 1: Append the JSON export tests**

Append to `campaigns/tests/test_raffle_audit.py`:

```python


class RaffleAuditJsonTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.alice = User.objects.create_user("alice", password="pw", is_staff=True)
        cls.bob = User.objects.create_user("bob", password="pw", is_staff=True)
        cls.camp_x = _campaign(name="X", slug="x", manager=cls.alice)
        cls.camp_y = _campaign(name="Y", slug="y", manager=cls.bob)
        cls.subs = [
            _submission(cls.camp_x, first_name=f"S{i}", email=f"s{i}@example.com")
            for i in range(4)
        ]
        cls.prize = Prize.objects.create(campaign=cls.camp_x, name="P", quantity=2)

    def _draw(self):
        from campaigns.utils import conduct_raffle
        return conduct_raffle(
            campaign=self.camp_x,
            prizes_with_quantities=[(self.prize, 2)],
            submission_qs=self.camp_x.submissions.all(),
            conducted_by=self.alice,
            consume_pool=False,
        )

    def test_audit_json_returns_application_json_with_expected_keys(self):
        import json
        from django.urls import reverse
        raffle = self._draw()
        self.client.force_login(self.alice)
        resp = self.client.get(reverse("raffle_audit_json", args=[raffle.id]))
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp['Content-Type'], 'application/json')
        data = json.loads(resp.content)
        for key in [
            'raffle_id', 'campaign_id', 'campaign_name',
            'conducted_by', 'conducted_at',
            'algorithm', 'algorithm_version', 'seed',
            'participant_pool_snapshot', 'prize_quantities',
            'consumed_pool', 'excluded_already_participated',
            'winners', 'verify_result',
        ]:
            self.assertIn(key, data, f"missing key: {key}")
        self.assertEqual(data['verify_result']['status'], 'ok')
        self.assertEqual(len(data['winners']), 2)

    def test_audit_json_403_for_non_manager(self):
        from django.urls import reverse
        raffle = self._draw()
        self.client.force_login(self.bob)
        resp = self.client.get(reverse("raffle_audit_json", args=[raffle.id]))
        self.assertEqual(resp.status_code, 403)

    def test_audit_json_includes_content_disposition(self):
        from django.urls import reverse
        raffle = self._draw()
        self.client.force_login(self.alice)
        resp = self.client.get(reverse("raffle_audit_json", args=[raffle.id]))
        self.assertIn('attachment', resp.get('Content-Disposition', ''))
        self.assertIn(f'raffle-{raffle.id}-audit.json', resp.get('Content-Disposition', ''))
```

- [ ] **Step 2: Run the tests to verify they fail**

```bash
docker exec raffle-web python manage.py test campaigns.tests.test_raffle_audit.RaffleAuditJsonTests -v 2
```

Expected: NoReverseMatch — `raffle_audit_json` URL doesn't exist.

- [ ] **Step 3: Add the URL**

In `campaigns/urls.py`, append after the `raffle_audit` line:

```python
    path('dashboard/raffle/<int:raffle_id>/audit/json/', views.raffle_audit_json, name='raffle_audit_json'),
```

- [ ] **Step 4: Add the view**

At the bottom of `campaigns/views.py`, add:

```python
@login_required
def raffle_audit_json(request, raffle_id):
    """Return the full audit blob as a downloadable JSON file."""
    from .utils import verify_raffle_audit
    raffle = get_object_or_404(Raffle, id=raffle_id)
    if not request.user.is_superuser and not raffle.campaign.managers.filter(
        id=request.user.id
    ).exists():
        raise PermissionDenied("You don't have access to this raffle.")

    verify_result = verify_raffle_audit(raffle)
    winners = [
        {
            'prize_id': w.prize_id,
            'prize_name': w.prize.name,
            'submission_id': w.submission_id,
            'submission_name': w.submission.full_name,
            'position': w.position,
        }
        for w in raffle.winners.select_related('submission', 'prize').order_by(
            'prize__order', 'position'
        )
    ]
    payload = {
        'raffle_id': raffle.id,
        'campaign_id': raffle.campaign_id,
        'campaign_name': raffle.campaign.name,
        'conducted_by': raffle.conducted_by.username if raffle.conducted_by else None,
        'conducted_at': raffle.conducted_at.isoformat(),
        'notes': raffle.notes,
        'algorithm': raffle.algorithm,
        'algorithm_version': raffle.algorithm_version,
        'seed': raffle.seed,
        'participant_pool_snapshot': list(raffle.participant_pool_snapshot),
        'prize_quantities': list(raffle.prize_quantities),
        'segment_state': raffle.segment_state,
        'segment_county': raffle.segment_county,
        'segment_date_from': raffle.segment_date_from.isoformat() if raffle.segment_date_from else None,
        'segment_date_to': raffle.segment_date_to.isoformat() if raffle.segment_date_to else None,
        'filter_search': raffle.filter_search,
        'filter_store_id': raffle.filter_store_id,
        'consumed_pool': raffle.consumed_pool,
        'excluded_already_participated': raffle.excluded_already_participated,
        'winners': winners,
        'verify_result': verify_result,
    }
    response = JsonResponse(payload, json_dumps_params={'indent': 2})
    response['Content-Disposition'] = (
        f'attachment; filename="raffle-{raffle.id}-audit.json"'
    )
    return response
```

- [ ] **Step 5: Run the JSON tests**

```bash
docker exec raffle-web python manage.py test campaigns.tests.test_raffle_audit.RaffleAuditJsonTests -v 2
```

Expected: 3/3 pass.

- [ ] **Step 6: Commit AND PUSH**

```bash
git add campaigns/urls.py campaigns/views.py campaigns/tests/test_raffle_audit.py
git commit -m "feat(audit): raffle_audit_json downloadable export with verify result embedded"
git push origin main
```

---

## Task 8: campaign_detail Estado column + restore-eligibility modal

**Files:**
- Modify: `campaigns/templates/campaigns/campaign_detail.html`
- Create: `campaigns/templates/campaigns/_restore_eligibility_modal.html`
- Modify: `campaigns/tests/test_raffle_audit.py`

- [ ] **Step 1: Append the rendering smoke tests**

Append to `campaigns/tests/test_raffle_audit.py`:

```python


class CampaignDetailParticipationUITests(TestCase):
    """The submissions table in campaign_detail.html shows an Estado column
    and exposes the restore-eligibility modal for already-participated rows."""

    @classmethod
    def setUpTestData(cls):
        cls.alice = User.objects.create_user("alice", password="pw", is_staff=True)
        cls.campaign = _campaign(manager=cls.alice)
        cls.eligible = _submission(cls.campaign, first_name="Eligible", email="e@x.com")
        cls.participated = _submission(cls.campaign, first_name="Participated", email="p@x.com")
        Submission.objects.filter(id=cls.participated.id).update(
            participated_at=timezone.now()
        )

    def test_participated_submission_shows_status_badge(self):
        from django.urls import reverse
        self.client.force_login(self.alice)
        resp = self.client.get(reverse("campaign_detail", args=[self.campaign.id]))
        body = resp.content.decode()
        # Eligible row uses the eligible badge
        self.assertIn("Elegible", body)
        # Participated row uses the participated badge
        self.assertIn("Ya participó", body)

    def test_participated_row_has_restore_trigger(self):
        from django.urls import reverse
        self.client.force_login(self.alice)
        resp = self.client.get(reverse("campaign_detail", args=[self.campaign.id]))
        body = resp.content.decode()
        self.assertIn(f'data-submission-id="{self.participated.id}"', body)
        self.assertIn('data-bs-target="#restoreEligibilityModal"', body)

    def test_restore_modal_present_in_campaign_detail(self):
        from django.urls import reverse
        self.client.force_login(self.alice)
        resp = self.client.get(reverse("campaign_detail", args=[self.campaign.id]))
        body = resp.content.decode()
        self.assertIn('id="restoreEligibilityModal"', body)
```

- [ ] **Step 2: Run the tests to verify they fail**

```bash
docker exec raffle-web python manage.py test campaigns.tests.test_raffle_audit.CampaignDetailParticipationUITests -v 2
```

Expected: failures — markup not present.

- [ ] **Step 3: Create the restore-eligibility modal partial**

Create `campaigns/templates/campaigns/_restore_eligibility_modal.html`:

```django
{% load i18n %}

<div class="modal fade" id="restoreEligibilityModal" tabindex="-1" role="dialog"
     aria-labelledby="restoreEligibilityModalTitle" aria-hidden="true">
  <div class="modal-dialog">
    <div class="modal-content">
      <form id="restoreEligibilityForm" method="post" action="#">
        {% csrf_token %}
        <div class="modal-header">
          <h5 class="modal-title pd-display" id="restoreEligibilityModalTitle">
            {% trans "Restaurar elegibilidad" %}
          </h5>
          <button type="button" class="btn-close" data-bs-dismiss="modal"
                  aria-label="{% trans 'Cerrar' %}"></button>
        </div>
        <div class="modal-body">
          <p>
            {% blocktrans with name='<strong id="restoreEligibilitySubmissionName"></strong>' %}
            ¿Restaurar la elegibilidad de {{ name }}?
            {% endblocktrans %}
          </p>
          <p class="text-muted small">
            {% trans "Esto permite que vuelvan a participar en futuros sorteos. La acción se registra con quién, cuándo y por qué." %}
          </p>
          <div class="mb-3">
            <label for="restoreEligibilityReason" class="form-label">
              {% trans "Razón (obligatoria)" %}
            </label>
            <input type="text" name="reason" id="restoreEligibilityReason"
                   class="form-control" maxlength="200" required>
          </div>
        </div>
        <div class="modal-footer">
          <button type="button" class="btn btn-outline-secondary" data-bs-dismiss="modal">
            {% trans "Cancelar" %}
          </button>
          <button type="submit" class="btn btn-primary">{% trans "Restaurar" %}</button>
        </div>
      </form>
    </div>
  </div>
</div>
```

- [ ] **Step 4: Add the Estado column to the submissions table**

Open `campaigns/templates/campaigns/campaign_detail.html`. Find the `<thead>` of the submissions table (search for `<th>Validez</th>`):

**Before (the existing `<thead>` row):**

```django
        <tr>
          <th>#</th>
          <th>{% trans "Nombre" %}</th>
          <th>{% trans "Correo" %}</th>
          <th>{% trans "Teléfono" %}</th>
          <th>{% trans "Foto" %}</th>
          <th>{% trans "Validez" %}</th>
          <th>{% trans "Código" %}</th>
          <th>{% trans "Enviado" %}</th>
          <th>{% trans "Acciones" %}</th>
        </tr>
```

**After:**

```django
        <tr>
          <th>#</th>
          <th>{% trans "Nombre" %}</th>
          <th>{% trans "Correo" %}</th>
          <th>{% trans "Teléfono" %}</th>
          <th>{% trans "Foto" %}</th>
          <th>{% trans "Validez" %}</th>
          <th>{% trans "Estado" %}</th>
          <th>{% trans "Código" %}</th>
          <th>{% trans "Enviado" %}</th>
          <th>{% trans "Acciones" %}</th>
        </tr>
```

Then find the corresponding `<tbody>` row that loops over submissions. The empty-state colspan needs updating from 9 to 10. Find:

```django
          <td colspan="9" class="text-center py-5 text-muted">
```

Replace with:

```django
          <td colspan="10" class="text-center py-5 text-muted">
```

In the loop body for each submission row, insert a new `<td>` cell BETWEEN the Validez column and the Código column. The exact change depends on the existing markup; locate the `<td>` containing `submission.is_valid` (the Validez cell) and insert the following AFTER it:

```django
          <td>
            {% if submission.participated_at %}
              <span class="badge bg-warning text-dark" title="{{ submission.participated_at|date:'d/m/Y H:i' }}">
                <i class="bi bi-check2-square me-1"></i>{% trans "Ya participó" %}
              </span>
              <button type="button" class="btn btn-sm btn-link p-0 ms-2"
                      title="{% trans 'Restaurar elegibilidad' %}"
                      aria-label="{% trans 'Restaurar elegibilidad' %}"
                      data-bs-toggle="modal" data-bs-target="#restoreEligibilityModal"
                      data-submission-id="{{ submission.id }}"
                      data-submission-name="{{ submission.full_name }}"
                      data-action-url="{% url 'submission_restore_eligibility' campaign.id submission.id %}">
                <i class="bi bi-arrow-counterclockwise"></i>
              </button>
            {% else %}
              <span class="badge bg-success-subtle text-success border border-success-subtle">
                <i class="bi bi-check-circle me-1"></i>{% trans "Elegible" %}
              </span>
            {% endif %}
          </td>
```

- [ ] **Step 5: Include the modal partial + add the wiring JS**

In `campaigns/templates/campaigns/campaign_detail.html`, find the existing `{% include "campaigns/_prize_modals.html" %}` line near the bottom of the template. Add immediately after it:

```django
{% include "campaigns/_restore_eligibility_modal.html" %}
```

Then find the existing `{% block extra_js %}` in the same template (added in the prize-CRUD plan). Inside the existing IIFE, just before the closing `})();`, add:

```javascript

  // --- Restore eligibility modal wiring ---
  const restoreModal = document.getElementById('restoreEligibilityModal');
  const restoreForm = document.getElementById('restoreEligibilityForm');
  const restoreName = document.getElementById('restoreEligibilitySubmissionName');
  const restoreReason = document.getElementById('restoreEligibilityReason');

  if (restoreModal && restoreForm && restoreName && restoreReason) {
    restoreModal.addEventListener('show.bs.modal', (e) => {
      const trigger = e.relatedTarget;
      if (!trigger) return;
      restoreForm.action = trigger.dataset.actionUrl || '';
      restoreName.textContent = trigger.dataset.submissionName || '';
      restoreReason.value = '';
    });
  }
```

- [ ] **Step 6: Run the tests**

```bash
docker exec raffle-web python manage.py test campaigns.tests.test_raffle_audit.CampaignDetailParticipationUITests -v 2
```

Expected: 3/3 pass.

- [ ] **Step 7: Commit AND PUSH**

```bash
git add campaigns/templates/campaigns/campaign_detail.html campaigns/templates/campaigns/_restore_eligibility_modal.html campaigns/tests/test_raffle_audit.py
git commit -m "feat(audit): Estado column + restore-eligibility modal on campaign detail"
git push origin main
```

---

## Task 9: Audit button on raffle history table + raffle.html new form fields

**Files:**
- Modify: `campaigns/templates/campaigns/campaign_detail.html`
- Modify: `campaigns/templates/campaigns/raffle.html`
- Modify: `campaigns/tests/test_raffle_audit.py`

- [ ] **Step 1: Append the rendering smoke tests**

Append to `campaigns/tests/test_raffle_audit.py`:

```python


class RaffleHistoryAuditButtonTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.alice = User.objects.create_user("alice", password="pw", is_staff=True)
        cls.campaign = _campaign(manager=cls.alice)
        cls.subs = [
            _submission(cls.campaign, first_name=f"S{i}", email=f"s{i}@example.com")
            for i in range(3)
        ]
        cls.prize = Prize.objects.create(campaign=cls.campaign, name="P", quantity=1)

    def test_raffle_history_row_has_audit_button(self):
        from campaigns.utils import conduct_raffle
        from django.urls import reverse
        raffle = conduct_raffle(
            campaign=self.campaign,
            prizes_with_quantities=[(self.prize, 1)],
            submission_qs=self.campaign.submissions.all(),
            conducted_by=self.alice,
            consume_pool=False,
        )
        self.client.force_login(self.alice)
        resp = self.client.get(reverse("campaign_detail", args=[self.campaign.id]))
        body = resp.content.decode()
        audit_url = reverse("raffle_audit", args=[raffle.id])
        self.assertIn(audit_url, body)


class RafflePageNewFieldsTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.alice = User.objects.create_user("alice", password="pw", is_staff=True)
        cls.campaign = _campaign(manager=cls.alice)
        Prize.objects.create(campaign=cls.campaign, name="P", quantity=1)

    def test_raffle_page_renders_new_filter_fields(self):
        from django.urls import reverse
        self.client.force_login(self.alice)
        resp = self.client.get(reverse("raffle", args=[self.campaign.id]))
        self.assertEqual(resp.status_code, 200)
        body = resp.content.decode()
        for name in ['name="search"', 'name="store"',
                     'name="include_already_participated"', 'name="consume_pool"']:
            self.assertIn(name, body)
```

- [ ] **Step 2: Run the tests to verify they fail**

```bash
docker exec raffle-web python manage.py test campaigns.tests.test_raffle_audit.RaffleHistoryAuditButtonTests campaigns.tests.test_raffle_audit.RafflePageNewFieldsTests -v 2
```

Expected: failures — Audit button absent in history; new form fields not rendered in raffle.html.

- [ ] **Step 3: Add the Audit button to the raffle history table**

Open `campaigns/templates/campaigns/campaign_detail.html`. Find the raffle history table (search for `Historial de Sorteos`). Inside the loop body for each `raffle` row, find the existing actions cell containing the link to `raffle_results`. Append (in the same `<td>`) an Audit button:

```django
            <a href="{% url 'raffle_audit' raffle.id %}" class="btn btn-sm btn-outline-secondary ms-1" title="{% trans 'Ver auditoría' %}">
              <i class="bi bi-shield-check me-1"></i>{% trans "Auditoría" %}
            </a>
```

(The exact insertion point is wherever the existing "Ver Resultados" / `raffle_results` button lives in your template. Place the new button immediately after.)

- [ ] **Step 4: Render the new form fields in raffle.html**

Open `campaigns/templates/campaigns/raffle.html`. The existing template renders `{{ segment_form.state }}`, `{{ segment_form.county }}`, etc. Find that block and add the four new fields in a sensible layout. A complete recommended block is:

```django
        <div class="row g-3">
          <div class="col-md-6">
            <label class="form-label" for="{{ segment_form.search.id_for_label }}">{% trans "Buscar" %}</label>
            {{ segment_form.search }}
          </div>
          <div class="col-md-6">
            <label class="form-label" for="{{ segment_form.store.id_for_label }}">{% trans "Tienda" %}</label>
            {{ segment_form.store }}
          </div>
        </div>
        <div class="row g-3 mt-1">
          <div class="col-12">
            <div class="form-check">
              {{ segment_form.include_already_participated }}
              <label class="form-check-label" for="{{ segment_form.include_already_participated.id_for_label }}">
                {% trans "Incluir participantes que ya han participado" %}
              </label>
            </div>
            <div class="form-check">
              {{ segment_form.consume_pool }}
              <label class="form-check-label" for="{{ segment_form.consume_pool.id_for_label }}">
                {% trans "Marcar participantes como \"ya participaron\" después del sorteo" %}
              </label>
            </div>
          </div>
        </div>
```

Place this block adjacent to the existing state/county/date inputs (anywhere inside the raffle segment form). The exact position doesn't matter for tests — they only check the `name="..."` attribute.

You may need to add Bootstrap classes to the form widgets via `__init__` overrides in `RaffleSegmentForm`, but the basic rendering will work regardless.

- [ ] **Step 5: Run the tests to verify they pass**

```bash
docker exec raffle-web python manage.py test campaigns.tests.test_raffle_audit.RaffleHistoryAuditButtonTests campaigns.tests.test_raffle_audit.RafflePageNewFieldsTests -v 2
```

Expected: 2/2 pass.

Run the full test suite:

```bash
docker exec raffle-web python manage.py test -v 1
```

- [ ] **Step 6: Commit AND PUSH**

```bash
git add campaigns/templates/campaigns/campaign_detail.html campaigns/templates/campaigns/raffle.html campaigns/tests/test_raffle_audit.py
git commit -m "feat(audit): Audit button in raffle history; new filter fields rendered in raffle.html"
git push origin main
```

---

## Task 10: Admin readonly audit fields, final sweep, push, memory update

**Files:**
- Modify: `campaigns/admin.py`

- [ ] **Step 1: Expose new audit fields as readonly on `RaffleAdmin`**

In `campaigns/admin.py`, find `RaffleAdmin`. Append the following to its `readonly_fields` list (or create the attribute if absent):

**Before** (the existing class header — exact lines depend on current admin.py state):

```python
@admin.register(Raffle)
class RaffleAdmin(CampaignScopedAdminMixin, ModelAdmin):
    list_display = ['campaign', 'conducted_at', 'conducted_by', 'total_participants', 'winner_count']
    list_filter = ['campaign']
    readonly_fields = ['conducted_at', 'total_participants']
```

**After:**

```python
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
```

This makes the audit fields visible-but-uneditable on the Django admin Raffle change page — useful for superuser inspection without risking accidental tampering. (Editing them would defeat the audit trail.)

- [ ] **Step 2: Commit AND PUSH**

```bash
git add campaigns/admin.py
git commit -m "feat(audit): expose Raffle audit fields as readonly on RaffleAdmin"
git push origin main
```

- [ ] **Step 3: Confirm clean test run**

```bash
docker exec raffle-web python manage.py test -v 1
```

Expected: every test passes (71 prior + ~24 new from this plan).

- [ ] **Step 4: Restart container and smoke-check the new surfaces**

```bash
RAFFLE_CAMPAIGN_WEB_PORT=8500 docker compose restart web
sleep 4
echo "--- Surfaces ---"
curl -s -o /dev/null -w "GET /dashboard/campaign/1/raffle/    %{http_code}\n" http://localhost:8500/dashboard/campaign/1/raffle/
echo "--- Public surfaces ---"
curl -s -o /dev/null -w "GET /dashboard/campaign/1/             %{http_code}\n" http://localhost:8500/dashboard/campaign/1/
```

Expected: 302 (auth redirects); after login, both render 200.

- [ ] **Step 5: Manual visual smoke check (logged in)**

In a browser, log in as `manager` / `manager123` (or `admin` / `admin123`). Visit `/dashboard/campaign/1/raffle/` and confirm the form now has Search, Store dropdown, "Include already-participated" checkbox, and "Consume pool" checkbox (default checked). Run a draw. Visit the raffle history table on `/dashboard/campaign/1/`. Click the new "Auditoría" button on the most recent row. Confirm the audit page shows the seed, algorithm, pool, prizes, winners, and a green "Auditoría verificada" banner. Click "Descargar JSON" and confirm a downloaded file matches the page contents.

Back on `/dashboard/campaign/1/`, find a participant in the submissions table whose Estado is "Ya participó". Click the restore arrow icon. Modal opens. Type a reason. Submit. Page reloads, status flips to "Elegible", green flash appears.

- [ ] **Step 6: Push (already done per task — verify clean)**

```bash
git status
git log --oneline origin/main..HEAD || echo "All pushed"
```

- [ ] **Step 7: Update project memory**

Append to `/home/elgran/.claude/projects/-home-elgran-Projects-raffle-campaign/memory/MEMORY.md`:

```markdown
- [Auditable raffle draws + consumable pool](project_raffle_audit.md) — every raffle is reproducible (seeded RNG + pool snapshot persisted); pool filtering expanded; submissions gain Already-Participated lifecycle with operator-restorable eligibility (shipped 2026-05-11)
```

Create `/home/elgran/.claude/projects/-home-elgran-Projects-raffle-campaign/memory/project_raffle_audit.md`:

```markdown
---
name: Auditable raffle draws + consumable pool
description: Status of the raffle audit log, expanded filters, and Already-Participated lifecycle
type: project
---
**Status as of 2026-05-11: SHIPPED to `main`.**

**What's in place:**
- Migration `0006_raffle_audit_and_submission_participated_at` adds: `Submission.participated_at`, `eligibility_restored_at/_by/_reason`; `Raffle.seed`, `algorithm`, `algorithm_version`, `participant_pool_snapshot` (JSONField), `prize_quantities` (JSONField), `consumed_pool`, `excluded_already_participated`, `filter_search`, `filter_store_id`.
- `conduct_raffle()` takes an explicit `seed` (auto-generated 32-char hex from `secrets.token_hex(16)` if absent) and uses an isolated `random.Random(seed)`. Pool is `submission_qs.order_by('id')` for canonical snapshot. Post-draw, if `consume_pool=True`, all pool members get `participated_at=raffle.conducted_at`.
- `verify_raffle_audit(raffle)` re-runs the recorded inputs and returns `{'status': 'ok' | 'mismatch' | 'unverifiable', ...}`.
- Pool filter expansion: `RaffleSegmentForm` adds `search`, `store`, `include_already_participated`, `consume_pool`. `raffle_view` and `ajax_filter_count` honor them. Default behavior: invalid submissions excluded; already-participated excluded; pool consumed after draw.
- Audit page at `/dashboard/raffle/<id>/audit/` and JSON export at `/dashboard/raffle/<id>/audit/json/`. Both gated by the existing manager check (raffle.campaign.managers).
- Restore-eligibility flow: POST `/dashboard/campaign/<id>/submission/<sid>/restore-eligibility/` with `reason` form field. Modal trigger on each "Ya participó" row in the submissions table.
- 24 tests in `test_raffle_audit.py`.

**Why:** Compliance / dispute resolution (anyone can re-run the draw with the saved seed and verify the same winners), and operational hygiene (a participant should normally be drawn from once per campaign, with an opt-out for repeat-pool draws and a manual restore for mistakes).

**Spec:** `docs/superpowers/specs/2026-05-11-auditable-raffle-draws.md`
**Plan:** `docs/superpowers/plans/2026-05-11-auditable-raffle-draws.md`

**Deferred (in the spec's Out of Scope):** cryptographic verification (NIST beacon / commit-reveal), per-row include/exclude during draw, named pool segments, bulk restoration, audit logs for non-raffle entities.
```

---

## Verification Summary

| Surface | Behavior |
|---|---|
| `/dashboard/campaign/<id>/raffle/` | Filter form shows Search / Store / Include-already-participated / Consume-pool; live count honors all filters |
| `POST /dashboard/campaign/<id>/raffle/` | `conduct_raffle()` runs with `seed=secrets.token_hex(16)`; saves snapshot, JSON prize list, audit metadata; if `consume_pool=True`, marks pool members as participated |
| `/dashboard/raffle/<id>/audit/` | Renders audit page with verify status banner |
| `/dashboard/raffle/<id>/audit/json/` | Downloadable JSON export with full audit blob + verify result |
| `POST /dashboard/campaign/<id>/submission/<sid>/restore-eligibility/` | Clears `participated_at`, records who/when/why; redirects with success flash |
| `/dashboard/campaign/<id>/` (submissions table) | New Estado column with "Elegible" / "Ya participó" badges; restore button opens modal |
| `/dashboard/campaign/<id>/` (raffle history) | Each row gains an Auditoría button linking to the audit page |
| Cross-campaign URL tampering | 403 (manager check) for audit + restore |
| Pre-feature raffles (no seed) | Audit page shows "unverifiable" banner; verify button hidden |

Tests: ~24 new in `campaigns/tests/test_raffle_audit.py` covering reproducibility, consume-pool toggle, pool filters, restore-eligibility flow, audit page render + 403 + verify status, JSON export, audit button + form-field rendering smoke.

No model deletions or destructive migrations. Pre-existing raffle rows migrate cleanly with empty seed/snapshot and are flagged as "unverifiable" on the audit page.
