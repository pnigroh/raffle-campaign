# Prize CRUD on the campaign dashboard — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let campaign managers add, edit, and delete prizes from `/dashboard/campaign/<id>/` without leaving the page or opening Django admin.

**Architecture:** Three POST-only Django views (`prize_add` / `prize_edit` / `prize_delete`) gated by the existing `_get_managed_campaign_or_403` helper. A single Bootstrap modal in the campaign detail template doubles as the add/edit form (mutated on `show.bs.modal` from the trigger button's `data-` attributes); a separate small modal handles delete confirmation. Server-side validation; on failure, flash an error message and redirect.

**Tech Stack:** Django 4.2 forms + ModelForm, Bootstrap 5.3.2 modals, vanilla JS (~25 lines) for trigger→modal population.

**Spec:** `docs/superpowers/specs/2026-05-11-prize-crud-dashboard.md`

---

## File Structure

**Create:**
- `campaigns/templates/campaigns/_prize_modals.html` — partial holding the add/edit modal and the delete-confirm modal.
- `campaigns/tests/test_prize_crud.py` — 13 tests per spec.

**Modify:**
- `campaigns/forms.py` — append `PrizeForm` ModelForm.
- `campaigns/views.py` — three new view functions; augment `campaign_detail` context with `next_prize_order`.
- `campaigns/urls.py` — three new URL entries.
- `campaigns/templates/campaigns/campaign_detail.html` — swap card-header link → add-prize button; add edit/delete icons to each prize card; swap empty-state link → modal trigger; include `_prize_modals.html`; small inline `<script>` for modal population.

**Out of scope:** Models, migrations, admin (PrizeInline kept for ops).

---

## Task 1: PrizeForm

**Files:**
- Modify: `campaigns/forms.py` (append at end)
- Create: `campaigns/tests/test_prize_crud.py`

- [ ] **Step 1: Create the test file with the form-level tests**

Create `campaigns/tests/test_prize_crud.py`:

```python
"""Tests for the in-dashboard prize CRUD feature.

Spec: docs/superpowers/specs/2026-05-11-prize-crud-dashboard.md
"""

from datetime import timedelta

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from campaigns.forms import PrizeForm
from campaigns.models import Campaign, Prize

User = get_user_model()


def _campaign(name, slug, manager=None):
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


class PrizeFormTests(TestCase):
    def test_valid_data_passes_validation(self):
        form = PrizeForm(data={
            "name": "Camiseta",
            "description": "Talla M",
            "quantity": 1,
            "order": 10,
        })
        self.assertTrue(form.is_valid(), form.errors)

    def test_empty_name_fails_validation(self):
        form = PrizeForm(data={
            "name": "",
            "description": "",
            "quantity": 1,
            "order": 0,
        })
        self.assertFalse(form.is_valid())
        self.assertIn("name", form.errors)

    def test_quantity_below_one_is_rejected(self):
        form = PrizeForm(data={
            "name": "Premio",
            "description": "",
            "quantity": 0,
            "order": 0,
        })
        self.assertFalse(form.is_valid())
        self.assertIn("quantity", form.errors)
```

- [ ] **Step 2: Run the form tests to verify they fail**

```bash
docker exec raffle-web python manage.py test campaigns.tests.test_prize_crud.PrizeFormTests -v 2
```

Expected: All 3 tests ERROR with `ImportError: cannot import name 'PrizeForm' from 'campaigns.forms'`.

- [ ] **Step 3: Add PrizeForm to forms.py**

Append to `campaigns/forms.py`:

```python


class PrizeForm(forms.ModelForm):
    class Meta:
        model = Prize
        fields = ["name", "description", "quantity", "order"]
        widgets = {
            "name": forms.TextInput(attrs={"class": "form-control", "maxlength": 200}),
            "description": forms.Textarea(attrs={"class": "form-control", "rows": 3}),
            "quantity": forms.NumberInput(attrs={"class": "form-control", "min": 1}),
            "order": forms.NumberInput(attrs={"class": "form-control", "min": 0}),
        }

    def clean_quantity(self):
        qty = self.cleaned_data["quantity"]
        if qty < 1:
            raise forms.ValidationError("Cantidad debe ser al menos 1.")
        return qty
```

(`Prize` is already imported at the top of `forms.py`.)

- [ ] **Step 4: Run the form tests again to verify they pass**

```bash
docker exec raffle-web python manage.py test campaigns.tests.test_prize_crud.PrizeFormTests -v 2
```

Expected: 3 tests pass.

- [ ] **Step 5: Commit**

```bash
git add campaigns/forms.py campaigns/tests/test_prize_crud.py
git commit -m "feat(prize): add PrizeForm ModelForm with validation tests"
```

---

## Task 2: prize_add view + URL + happy-path test + 403/405 guards

**Files:**
- Modify: `campaigns/urls.py`
- Modify: `campaigns/views.py`
- Modify: `campaigns/tests/test_prize_crud.py` (add a new test class)

- [ ] **Step 1: Append the prize_add tests**

Append to `campaigns/tests/test_prize_crud.py`:

```python


class PrizeAddTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.alice = User.objects.create_user("alice", password="pw", is_staff=True)
        cls.bob = User.objects.create_user("bob", password="pw", is_staff=True)
        cls.charlie = User.objects.create_superuser("charlie", "c@x.com", "pw")
        cls.camp_x = _campaign("Campaign X", "camp-x", manager=cls.alice)
        cls.camp_y = _campaign("Campaign Y", "camp-y", manager=cls.bob)

    def test_prize_add_creates_and_redirects(self):
        self.client.force_login(self.alice)
        resp = self.client.post(
            reverse("prize_add", args=[self.camp_x.id]),
            data={"name": "Camiseta", "description": "M", "quantity": 1, "order": 10},
        )
        self.assertEqual(resp.status_code, 302)
        self.assertEqual(resp.url, reverse("campaign_detail", args=[self.camp_x.id]))
        self.assertTrue(
            Prize.objects.filter(campaign=self.camp_x, name="Camiseta").exists()
        )

    def test_prize_add_non_manager_gets_403(self):
        self.client.force_login(self.alice)
        resp = self.client.post(
            reverse("prize_add", args=[self.camp_y.id]),
            data={"name": "Hijack", "description": "", "quantity": 1, "order": 0},
        )
        self.assertEqual(resp.status_code, 403)
        self.assertFalse(Prize.objects.filter(name="Hijack").exists())

    def test_prize_add_get_returns_405(self):
        self.client.force_login(self.alice)
        resp = self.client.get(reverse("prize_add", args=[self.camp_x.id]))
        self.assertEqual(resp.status_code, 405)
```

- [ ] **Step 2: Run the new tests to verify they fail**

```bash
docker exec raffle-web python manage.py test campaigns.tests.test_prize_crud.PrizeAddTests -v 2
```

Expected: 3 tests ERROR with `NoReverseMatch: Reverse for 'prize_add' not found`.

- [ ] **Step 3: Add the URL pattern**

In `campaigns/urls.py`, append inside the `urlpatterns` list (after the existing `submission_set_validity` line):

```python
    path('dashboard/campaign/<int:campaign_id>/prize/add/', views.prize_add, name='prize_add'),
```

- [ ] **Step 4: Add the prize_add view**

At the bottom of `campaigns/views.py`, add:

```python
@login_required
@require_POST
def prize_add(request, campaign_id):
    campaign = _get_managed_campaign_or_403(request.user, campaign_id)
    form = PrizeForm(request.POST)
    if form.is_valid():
        prize = form.save(commit=False)
        prize.campaign = campaign
        prize.save()
        messages.success(request, 'Premio guardado.')
    else:
        errs = '; '.join(f"{k}: {', '.join(v)}" for k, v in form.errors.items())
        messages.error(request, f'No se pudo guardar el premio: {errs}')
    return redirect('campaign_detail', campaign_id=campaign.id)
```

And update the imports at the top of `campaigns/views.py`. Find the existing import line:

```python
from .forms import SubmissionForm, RaffleSegmentForm, CodeImportForm
```

Replace with:

```python
from .forms import SubmissionForm, RaffleSegmentForm, CodeImportForm, PrizeForm
```

- [ ] **Step 5: Run the prize_add tests to verify they pass**

```bash
docker exec raffle-web python manage.py test campaigns.tests.test_prize_crud.PrizeAddTests -v 2
```

Expected: 3 tests pass. (`PermissionDenied` from the helper produces 403; `@require_POST` produces 405 on GET; happy path persists.)

- [ ] **Step 6: Commit**

```bash
git add campaigns/urls.py campaigns/views.py campaigns/tests/test_prize_crud.py
git commit -m "feat(prize): add POST /dashboard/campaign/<id>/prize/add/ view"
```

---

## Task 3: prize_edit view + URL + tests (happy + 403 + cross-campaign 404 + 405)

**Files:**
- Modify: `campaigns/urls.py`
- Modify: `campaigns/views.py`
- Modify: `campaigns/tests/test_prize_crud.py`

- [ ] **Step 1: Append the prize_edit tests**

Append to `campaigns/tests/test_prize_crud.py`:

```python


class PrizeEditTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.alice = User.objects.create_user("alice", password="pw", is_staff=True)
        cls.bob = User.objects.create_user("bob", password="pw", is_staff=True)
        cls.camp_x = _campaign("Campaign X", "camp-x", manager=cls.alice)
        cls.camp_y = _campaign("Campaign Y", "camp-y", manager=cls.bob)
        cls.prize_x = Prize.objects.create(
            campaign=cls.camp_x, name="Original", quantity=1, order=10
        )
        cls.prize_y = Prize.objects.create(
            campaign=cls.camp_y, name="Bob's prize", quantity=1, order=10
        )

    def test_prize_edit_persists_changes(self):
        self.client.force_login(self.alice)
        resp = self.client.post(
            reverse("prize_edit", args=[self.camp_x.id, self.prize_x.id]),
            data={"name": "Updated", "description": "new", "quantity": 5, "order": 20},
        )
        self.assertEqual(resp.status_code, 302)
        self.prize_x.refresh_from_db()
        self.assertEqual(self.prize_x.name, "Updated")
        self.assertEqual(self.prize_x.quantity, 5)
        self.assertEqual(self.prize_x.order, 20)

    def test_prize_edit_non_manager_gets_403(self):
        self.client.force_login(self.alice)
        resp = self.client.post(
            reverse("prize_edit", args=[self.camp_y.id, self.prize_y.id]),
            data={"name": "Hijacked", "description": "", "quantity": 1, "order": 0},
        )
        self.assertEqual(resp.status_code, 403)
        self.prize_y.refresh_from_db()
        self.assertEqual(self.prize_y.name, "Bob's prize")

    def test_cross_campaign_prize_edit_returns_404(self):
        # Alice tries to edit her OWN campaign's URL but with bob's prize_id
        self.client.force_login(self.alice)
        resp = self.client.post(
            reverse("prize_edit", args=[self.camp_x.id, self.prize_y.id]),
            data={"name": "Hijack", "description": "", "quantity": 1, "order": 0},
        )
        self.assertEqual(resp.status_code, 404)

    def test_prize_edit_get_returns_405(self):
        self.client.force_login(self.alice)
        resp = self.client.get(
            reverse("prize_edit", args=[self.camp_x.id, self.prize_x.id])
        )
        self.assertEqual(resp.status_code, 405)
```

- [ ] **Step 2: Run the new tests to verify they fail**

```bash
docker exec raffle-web python manage.py test campaigns.tests.test_prize_crud.PrizeEditTests -v 2
```

Expected: All 4 tests ERROR with `NoReverseMatch: Reverse for 'prize_edit' not found`.

- [ ] **Step 3: Add the URL pattern**

In `campaigns/urls.py`, append:

```python
    path('dashboard/campaign/<int:campaign_id>/prize/<int:prize_id>/edit/', views.prize_edit, name='prize_edit'),
```

- [ ] **Step 4: Add the prize_edit view**

At the bottom of `campaigns/views.py`, add:

```python
@login_required
@require_POST
def prize_edit(request, campaign_id, prize_id):
    campaign = _get_managed_campaign_or_403(request.user, campaign_id)
    prize = get_object_or_404(Prize, id=prize_id, campaign=campaign)
    form = PrizeForm(request.POST, instance=prize)
    if form.is_valid():
        form.save()
        messages.success(request, 'Premio guardado.')
    else:
        errs = '; '.join(f"{k}: {', '.join(v)}" for k, v in form.errors.items())
        messages.error(request, f'No se pudo guardar el premio: {errs}')
    return redirect('campaign_detail', campaign_id=campaign.id)
```

- [ ] **Step 5: Run the prize_edit tests to verify they pass**

```bash
docker exec raffle-web python manage.py test campaigns.tests.test_prize_crud.PrizeEditTests -v 2
```

Expected: 4 tests pass.

- [ ] **Step 6: Commit**

```bash
git add campaigns/urls.py campaigns/views.py campaigns/tests/test_prize_crud.py
git commit -m "feat(prize): add POST /dashboard/campaign/<id>/prize/<pid>/edit/ view"
```

---

## Task 4: prize_delete view + URL + tests

**Files:**
- Modify: `campaigns/urls.py`
- Modify: `campaigns/views.py`
- Modify: `campaigns/tests/test_prize_crud.py`

- [ ] **Step 1: Append the prize_delete tests**

Append to `campaigns/tests/test_prize_crud.py`:

```python


class PrizeDeleteTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.alice = User.objects.create_user("alice", password="pw", is_staff=True)
        cls.bob = User.objects.create_user("bob", password="pw", is_staff=True)
        cls.camp_x = _campaign("Campaign X", "camp-x", manager=cls.alice)
        cls.camp_y = _campaign("Campaign Y", "camp-y", manager=cls.bob)

    def setUp(self):
        # Create a fresh prize per test so deletion is isolated.
        self.prize_x = Prize.objects.create(
            campaign=self.camp_x, name="Delete me", quantity=1, order=10
        )
        self.prize_y = Prize.objects.create(
            campaign=self.camp_y, name="Bob's prize", quantity=1, order=10
        )

    def test_prize_delete_removes_prize(self):
        self.client.force_login(self.alice)
        resp = self.client.post(
            reverse("prize_delete", args=[self.camp_x.id, self.prize_x.id])
        )
        self.assertEqual(resp.status_code, 302)
        self.assertFalse(Prize.objects.filter(id=self.prize_x.id).exists())

    def test_prize_delete_non_manager_gets_403(self):
        self.client.force_login(self.alice)
        resp = self.client.post(
            reverse("prize_delete", args=[self.camp_y.id, self.prize_y.id])
        )
        self.assertEqual(resp.status_code, 403)
        self.assertTrue(Prize.objects.filter(id=self.prize_y.id).exists())

    def test_prize_delete_get_returns_405(self):
        self.client.force_login(self.alice)
        resp = self.client.get(
            reverse("prize_delete", args=[self.camp_x.id, self.prize_x.id])
        )
        self.assertEqual(resp.status_code, 405)
```

- [ ] **Step 2: Run the new tests to verify they fail**

```bash
docker exec raffle-web python manage.py test campaigns.tests.test_prize_crud.PrizeDeleteTests -v 2
```

Expected: 3 tests ERROR with `NoReverseMatch: Reverse for 'prize_delete' not found`.

- [ ] **Step 3: Add the URL pattern**

In `campaigns/urls.py`, append:

```python
    path('dashboard/campaign/<int:campaign_id>/prize/<int:prize_id>/delete/', views.prize_delete, name='prize_delete'),
```

- [ ] **Step 4: Add the prize_delete view**

At the bottom of `campaigns/views.py`, add:

```python
@login_required
@require_POST
def prize_delete(request, campaign_id, prize_id):
    campaign = _get_managed_campaign_or_403(request.user, campaign_id)
    prize = get_object_or_404(Prize, id=prize_id, campaign=campaign)
    prize_name = prize.name
    prize.delete()
    messages.success(request, f'Premio "{prize_name}" borrado.')
    return redirect('campaign_detail', campaign_id=campaign.id)
```

- [ ] **Step 5: Run the prize_delete tests to verify they pass**

```bash
docker exec raffle-web python manage.py test campaigns.tests.test_prize_crud.PrizeDeleteTests -v 2
```

Expected: 3 tests pass.

- [ ] **Step 6: Commit**

```bash
git add campaigns/urls.py campaigns/views.py campaigns/tests/test_prize_crud.py
git commit -m "feat(prize): add POST /dashboard/campaign/<id>/prize/<pid>/delete/ view"
```

---

## Task 5: Superuser bypass + invalid form flash + next_prize_order context

**Files:**
- Modify: `campaigns/views.py` (campaign_detail view)
- Modify: `campaigns/tests/test_prize_crud.py`

- [ ] **Step 1: Append the remaining tests**

Append to `campaigns/tests/test_prize_crud.py`:

```python


class PrizeMiscTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.alice = User.objects.create_user("alice", password="pw", is_staff=True)
        cls.bob = User.objects.create_user("bob", password="pw", is_staff=True)
        cls.charlie = User.objects.create_superuser("charlie", "c@x.com", "pw")
        cls.camp_x = _campaign("Campaign X", "camp-x", manager=cls.alice)
        cls.camp_y = _campaign("Campaign Y", "camp-y", manager=cls.bob)

    def test_superuser_can_add_prize_to_any_campaign(self):
        self.client.force_login(self.charlie)
        resp = self.client.post(
            reverse("prize_add", args=[self.camp_y.id]),
            data={"name": "Super-added", "description": "", "quantity": 1, "order": 0},
        )
        self.assertEqual(resp.status_code, 302)
        self.assertTrue(
            Prize.objects.filter(campaign=self.camp_y, name="Super-added").exists()
        )

    def test_invalid_form_redirects_with_error_flash(self):
        self.client.force_login(self.alice)
        resp = self.client.post(
            reverse("prize_add", args=[self.camp_x.id]),
            data={"name": "", "description": "", "quantity": 0, "order": 0},
            follow=True,  # follow the redirect so messages are surfaced
        )
        self.assertEqual(resp.status_code, 200)
        self.assertFalse(Prize.objects.filter(campaign=self.camp_x).exists())
        flash = [m.message for m in resp.context["messages"]]
        self.assertTrue(any("No se pudo guardar el premio" in m for m in flash), flash)

    def test_next_prize_order_defaults_to_max_plus_ten(self):
        # No existing prizes → next is 10.
        self.client.force_login(self.alice)
        resp = self.client.get(reverse("campaign_detail", args=[self.camp_x.id]))
        self.assertEqual(resp.context["next_prize_order"], 10)

        # With prizes at orders 5 and 15 → next is 25.
        Prize.objects.create(campaign=self.camp_x, name="A", quantity=1, order=5)
        Prize.objects.create(campaign=self.camp_x, name="B", quantity=1, order=15)
        resp = self.client.get(reverse("campaign_detail", args=[self.camp_x.id]))
        self.assertEqual(resp.context["next_prize_order"], 25)
```

- [ ] **Step 2: Run the tests to verify failure**

```bash
docker exec raffle-web python manage.py test campaigns.tests.test_prize_crud.PrizeMiscTests -v 2
```

Expected: `test_superuser_can_add_prize_to_any_campaign` and `test_invalid_form_redirects_with_error_flash` already pass (existing helper + view handle these). `test_next_prize_order_defaults_to_max_plus_ten` FAILS with `KeyError: 'next_prize_order'`.

- [ ] **Step 3: Add next_prize_order to campaign_detail context**

In `campaigns/views.py`, find the `campaign_detail` view's render call and the `from django.db.models import Count, Q` import.

First, update the import line:

```python
from django.db.models import Count, Q, Max
```

Then find the existing block in `campaign_detail` that begins with `prizes = campaign.prizes.all()` and modify the area just before `return render(...)`.

**Before:**

```python
    prizes = campaign.prizes.all()
```

**After:**

```python
    prizes = campaign.prizes.all()
    next_prize_order = (campaign.prizes.aggregate(m=Max('order'))['m'] or 0) + 10
```

In the same view, find the `return render(request, 'campaigns/campaign_detail.html', { ... })` block. Add `'next_prize_order': next_prize_order,` to the context dict.

- [ ] **Step 4: Run the tests to verify they pass**

```bash
docker exec raffle-web python manage.py test campaigns.tests.test_prize_crud.PrizeMiscTests -v 2
```

Expected: 3 tests pass.

- [ ] **Step 5: Commit**

```bash
git add campaigns/views.py campaigns/tests/test_prize_crud.py
git commit -m "feat(prize): expose next_prize_order to campaign_detail context for the add-modal default"
```

---

## Task 6: Add the modals partial + include + smoke test

**Files:**
- Create: `campaigns/templates/campaigns/_prize_modals.html`
- Modify: `campaigns/templates/campaigns/campaign_detail.html`
- Modify: `campaigns/tests/test_prize_crud.py`

- [ ] **Step 1: Add the smoke test**

Append to `campaigns/tests/test_prize_crud.py`:

```python


class PrizeModalRenderTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.alice = User.objects.create_user("alice", password="pw", is_staff=True)
        cls.camp_x = _campaign("Campaign X", "camp-x", manager=cls.alice)

    def test_prize_modals_present_in_campaign_detail(self):
        self.client.force_login(self.alice)
        resp = self.client.get(reverse("campaign_detail", args=[self.camp_x.id]))
        self.assertEqual(resp.status_code, 200)
        body = resp.content.decode()
        self.assertIn('id="prizeModal"', body)
        self.assertIn('id="prizeDeleteModal"', body)
```

- [ ] **Step 2: Run the test to verify it fails**

```bash
docker exec raffle-web python manage.py test campaigns.tests.test_prize_crud.PrizeModalRenderTests -v 2
```

Expected: FAIL with `'id="prizeModal"' not found in '<body>'`.

- [ ] **Step 3: Create the modals partial**

Create `campaigns/templates/campaigns/_prize_modals.html`:

```django
{% load i18n %}

{# === Add / Edit prize modal === #}
<div class="modal fade" id="prizeModal" tabindex="-1" aria-labelledby="prizeModalTitle" aria-hidden="true">
  <div class="modal-dialog">
    <div class="modal-content">
      <form id="prizeForm" method="post" action="">
        {% csrf_token %}
        <div class="modal-header">
          <h5 class="modal-title pd-display" id="prizeModalTitle">{% trans "Premio" %}</h5>
          <button type="button" class="btn-close" data-bs-dismiss="modal" aria-label="{% trans 'Cerrar' %}"></button>
        </div>
        <div class="modal-body">
          <div class="mb-3">
            <label class="form-label" for="prizeForm_name">{% trans "Nombre" %}</label>
            <input type="text" name="name" id="prizeForm_name" class="form-control" maxlength="200" required>
          </div>
          <div class="mb-3">
            <label class="form-label" for="prizeForm_description">{% trans "Descripción" %}</label>
            <textarea name="description" id="prizeForm_description" class="form-control" rows="3"></textarea>
          </div>
          <div class="row g-3">
            <div class="col-6">
              <label class="form-label" for="prizeForm_quantity">{% trans "Cantidad" %}</label>
              <input type="number" name="quantity" id="prizeForm_quantity" class="form-control" min="1" value="1" required>
            </div>
            <div class="col-6">
              <label class="form-label" for="prizeForm_order">{% trans "Orden" %}</label>
              <input type="number" name="order" id="prizeForm_order" class="form-control" min="0" value="0" required>
            </div>
          </div>
        </div>
        <div class="modal-footer">
          <button type="button" class="btn btn-outline-secondary" data-bs-dismiss="modal">{% trans "Cancelar" %}</button>
          <button type="submit" class="btn btn-primary">{% trans "Guardar" %}</button>
        </div>
      </form>
    </div>
  </div>
</div>

{# === Delete confirmation modal === #}
<div class="modal fade" id="prizeDeleteModal" tabindex="-1" aria-labelledby="prizeDeleteModalTitle" aria-hidden="true">
  <div class="modal-dialog modal-sm">
    <div class="modal-content">
      <form id="prizeDeleteForm" method="post" action="">
        {% csrf_token %}
        <div class="modal-header">
          <h5 class="modal-title pd-display" id="prizeDeleteModalTitle">{% trans "Borrar premio" %}</h5>
          <button type="button" class="btn-close" data-bs-dismiss="modal" aria-label="{% trans 'Cerrar' %}"></button>
        </div>
        <div class="modal-body">
          <p class="mb-0">
            {% blocktrans with name='<strong id="prizeDeleteName"></strong>' %}¿Borrar el premio {{ name }}? Esta acción no se puede deshacer.{% endblocktrans %}
          </p>
        </div>
        <div class="modal-footer">
          <button type="button" class="btn btn-outline-secondary" data-bs-dismiss="modal">{% trans "Cancelar" %}</button>
          <button type="submit" class="btn btn-danger">{% trans "Borrar" %}</button>
        </div>
      </form>
    </div>
  </div>
</div>
```

- [ ] **Step 4: Include the partial in campaign_detail.html**

Open `campaigns/templates/campaigns/campaign_detail.html`. At the very bottom of the file, just before the final `{% endblock %}`, add:

```django

{# Prize CRUD modals (templates/campaigns/_prize_modals.html) #}
{% include "campaigns/_prize_modals.html" %}
```

- [ ] **Step 5: Run the smoke test to verify it passes**

```bash
docker exec raffle-web python manage.py test campaigns.tests.test_prize_crud.PrizeModalRenderTests -v 2
```

Expected: 1 test passes.

- [ ] **Step 6: Commit**

```bash
git add campaigns/templates/campaigns/_prize_modals.html campaigns/templates/campaigns/campaign_detail.html campaigns/tests/test_prize_crud.py
git commit -m "feat(prize): add add/edit + delete-confirm modals partial to campaign detail"
```

---

## Task 7: Wire trigger buttons (card-header, per-card actions, empty state)

**Files:**
- Modify: `campaigns/templates/campaigns/campaign_detail.html`
- Modify: `campaigns/tests/test_prize_crud.py`

- [ ] **Step 1: Add the trigger-button smoke test**

Append to the existing `PrizeModalRenderTests` class in `campaigns/tests/test_prize_crud.py`:

```python

    def test_existing_prize_card_has_edit_and_delete_triggers(self):
        prize = Prize.objects.create(
            campaign=self.camp_x, name="Trigger test", quantity=2, order=10
        )
        self.client.force_login(self.alice)
        resp = self.client.get(reverse("campaign_detail", args=[self.camp_x.id]))
        body = resp.content.decode()
        self.assertIn(f'data-prize-id="{prize.id}"', body)
        self.assertIn('data-prize-action="edit"', body)
        self.assertIn('data-bs-target="#prizeModal"', body)
        self.assertIn('data-bs-target="#prizeDeleteModal"', body)

    def test_card_header_has_add_prize_trigger(self):
        self.client.force_login(self.alice)
        resp = self.client.get(reverse("campaign_detail", args=[self.camp_x.id]))
        body = resp.content.decode()
        self.assertIn('data-prize-action="add"', body)
```

- [ ] **Step 2: Run the new tests to verify they fail**

```bash
docker exec raffle-web python manage.py test campaigns.tests.test_prize_crud.PrizeModalRenderTests -v 2
```

Expected: `test_existing_prize_card_has_edit_and_delete_triggers` and `test_card_header_has_add_prize_trigger` FAIL with `'data-prize-action="…"' not found`.

- [ ] **Step 3: Replace the prizes card-header link**

Open `campaigns/templates/campaigns/campaign_detail.html`. Find the existing prizes section. Replace this block:

**Before:**

```django
{% if prizes %}
<div class="card mb-4">
  <div class="card-header d-flex align-items-center justify-content-between">
    <span><i class="bi bi-trophy me-2 text-warning"></i>{% trans "Premios" %}</span>
    <a href="/admin/campaigns/prize/?campaign__id__exact={{ campaign.id }}" class="btn btn-sm btn-outline-secondary">
      <i class="bi bi-pencil me-1"></i>{% trans "Editar Premios" %}
    </a>
  </div>
```

**After:**

```django
{% if prizes %}
<div class="card mb-4">
  <div class="card-header d-flex align-items-center justify-content-between">
    <span><i class="bi bi-trophy me-2 text-warning"></i>{% trans "Premios" %}</span>
    <button type="button" class="btn btn-sm btn-primary"
            data-bs-toggle="modal" data-bs-target="#prizeModal"
            data-prize-action="add"
            data-prize-action-url="{% url 'prize_add' campaign.id %}"
            data-next-order="{{ next_prize_order }}">
      <i class="bi bi-plus-lg me-1"></i>{% trans "Añadir Premio" %}
    </button>
  </div>
```

- [ ] **Step 4: Add edit/delete buttons to each prize card**

Still in `campaigns/templates/campaigns/campaign_detail.html`, find the inner card markup for each prize. Replace this block:

**Before:**

```django
      {% for prize in prizes %}
      <div class="col-md-4 col-lg-3">
        <div class="p-3 rounded-3 border" style="background:#fafbff;">
          <div class="fw-semibold text-dark">{{ prize.name }}</div>
          {% if prize.description %}
            <div class="text-muted-sm mt-1">{{ prize.description }}</div>
          {% endif %}
          <div class="mt-2">
            <span class="badge bg-primary rounded-pill">{% blocktrans with qty=prize.quantity %}Cant: {{ qty }}{% endblocktrans %}</span>
            <span class="badge bg-light text-muted border ms-1">{% blocktrans with order=prize.order %}Orden: {{ order }}{% endblocktrans %}</span>
          </div>
        </div>
      </div>
      {% endfor %}
```

**After:**

```django
      {% for prize in prizes %}
      <div class="col-md-4 col-lg-3">
        <div class="p-3 rounded-3 border position-relative" style="background:#fafbff;">
          <div class="position-absolute top-0 end-0 p-2 d-flex gap-1">
            <button type="button" class="btn btn-sm btn-link p-0 text-secondary" title="{% trans 'Editar' %}"
                    data-bs-toggle="modal" data-bs-target="#prizeModal"
                    data-prize-action="edit"
                    data-prize-action-url="{% url 'prize_edit' campaign.id prize.id %}"
                    data-prize-id="{{ prize.id }}"
                    data-prize-name="{{ prize.name }}"
                    data-prize-description="{{ prize.description }}"
                    data-prize-quantity="{{ prize.quantity }}"
                    data-prize-order="{{ prize.order }}">
              <i class="bi bi-pencil"></i>
            </button>
            <button type="button" class="btn btn-sm btn-link p-0 text-danger" title="{% trans 'Borrar' %}"
                    data-bs-toggle="modal" data-bs-target="#prizeDeleteModal"
                    data-prize-id="{{ prize.id }}"
                    data-prize-name="{{ prize.name }}"
                    data-prize-action-url="{% url 'prize_delete' campaign.id prize.id %}">
              <i class="bi bi-trash"></i>
            </button>
          </div>
          <div class="fw-semibold text-dark pe-5">{{ prize.name }}</div>
          {% if prize.description %}
            <div class="text-muted-sm mt-1">{{ prize.description }}</div>
          {% endif %}
          <div class="mt-2">
            <span class="badge bg-primary rounded-pill">{% blocktrans with qty=prize.quantity %}Cant: {{ qty }}{% endblocktrans %}</span>
            <span class="badge bg-light text-muted border ms-1">{% blocktrans with order=prize.order %}Orden: {{ order }}{% endblocktrans %}</span>
          </div>
        </div>
      </div>
      {% endfor %}
```

- [ ] **Step 5: Replace the empty-state link with a modal trigger**

Still in `campaigns/templates/campaigns/campaign_detail.html`, find the `{% else %}` branch of the prizes block:

**Before:**

```django
{% else %}
<div class="alert alert-warning d-flex align-items-center gap-2 mb-4">
  <i class="bi bi-exclamation-triangle-fill"></i>
  <span>{% trans "No hay premios configurados para esta campaña." %}
    <a href="/admin/campaigns/prize/add/?campaign={{ campaign.id }}" class="alert-link">{% trans "Agrega premios" %}</a>
    {% trans "antes de realizar un sorteo." %}
  </span>
</div>
{% endif %}
```

**After:**

```django
{% else %}
<div class="alert alert-warning d-flex align-items-center gap-2 mb-4">
  <i class="bi bi-exclamation-triangle-fill"></i>
  <span>{% trans "No hay premios configurados para esta campaña." %}
    <a href="#" class="alert-link"
       data-bs-toggle="modal" data-bs-target="#prizeModal"
       data-prize-action="add"
       data-prize-action-url="{% url 'prize_add' campaign.id %}"
       data-next-order="{{ next_prize_order }}">{% trans "Agrega premios" %}</a>
    {% trans "antes de realizar un sorteo." %}
  </span>
</div>
{% endif %}
```

- [ ] **Step 6: Run all PrizeModalRenderTests to verify they pass**

```bash
docker exec raffle-web python manage.py test campaigns.tests.test_prize_crud.PrizeModalRenderTests -v 2
```

Expected: 3 tests pass.

- [ ] **Step 7: Commit**

```bash
git add campaigns/templates/campaigns/campaign_detail.html campaigns/tests/test_prize_crud.py
git commit -m "feat(prize): wire add/edit/delete triggers in campaign detail prizes section"
```

---

## Task 8: Modal-population JavaScript

**Files:**
- Modify: `campaigns/templates/campaigns/campaign_detail.html`

This task is JS-only and is verified manually in the browser. No new tests.

- [ ] **Step 1: Append the modal-population script**

In `campaigns/templates/campaigns/campaign_detail.html`, scroll to the very bottom of the file. The file currently ends with `{% endblock %}` (and just above it, the `{% include "campaigns/_prize_modals.html" %}` you added in Task 6). Insert this `{% block extra_js %}` block immediately above `{% endblock %}`:

```django

{% block extra_js %}
<script>
(function () {
  const prizeModal = document.getElementById('prizeModal');
  const prizeForm = document.getElementById('prizeForm');
  const prizeTitle = document.getElementById('prizeModalTitle');

  if (prizeModal && prizeForm) {
    prizeModal.addEventListener('show.bs.modal', (e) => {
      const trigger = e.relatedTarget;
      if (!trigger) return;
      const action = trigger.dataset.prizeAction;
      prizeForm.action = trigger.dataset.prizeActionUrl || '';
      if (action === 'edit') {
        prizeTitle.textContent = 'Editar Premio';
        prizeForm.elements['name'].value = trigger.dataset.prizeName || '';
        prizeForm.elements['description'].value = trigger.dataset.prizeDescription || '';
        prizeForm.elements['quantity'].value = trigger.dataset.prizeQuantity || '1';
        prizeForm.elements['order'].value = trigger.dataset.prizeOrder || '0';
      } else {
        prizeTitle.textContent = 'Añadir Premio';
        prizeForm.elements['name'].value = '';
        prizeForm.elements['description'].value = '';
        prizeForm.elements['quantity'].value = '1';
        prizeForm.elements['order'].value = trigger.dataset.nextOrder || '0';
      }
    });
  }

  const prizeDeleteModal = document.getElementById('prizeDeleteModal');
  const prizeDeleteForm = document.getElementById('prizeDeleteForm');
  const prizeDeleteName = document.getElementById('prizeDeleteName');

  if (prizeDeleteModal && prizeDeleteForm) {
    prizeDeleteModal.addEventListener('show.bs.modal', (e) => {
      const trigger = e.relatedTarget;
      if (!trigger) return;
      prizeDeleteForm.action = trigger.dataset.prizeActionUrl || '';
      prizeDeleteName.textContent = trigger.dataset.prizeName || '';
    });
  }
})();
</script>
{% endblock %}
```

(The base template already has a `{% block extra_js %}` placeholder near the end — see `base.html` line ~508 — which is why this block lands in the right place.)

- [ ] **Step 2: Restart the container so the template change is picked up**

```bash
RAFFLE_CAMPAIGN_WEB_PORT=8500 docker compose restart web
sleep 4
```

- [ ] **Step 3: Manual browser smoke check**

Open `http://localhost:8500/dashboard/login/` (admin / admin123). Navigate to a campaign detail page (e.g. `/dashboard/campaign/1/`). Verify:

1. The "Premios" card-header now shows a coral **+ Añadir Premio** button (replacing the old "Editar Premios" link).
2. Clicking it opens a modal titled "Añadir Premio" with empty Name + Description fields, Quantity = 1, Order = `next_prize_order`.
3. Submit a new prize. The page reloads, the prize appears in the grid, and a green "Premio guardado." flash appears at the top.
4. Each prize card has small pencil + trash icons in the top-right.
5. Clicking the pencil opens the same modal, this time titled "Editar Premio" and pre-populated.
6. Edit the name, submit. Page reloads with updated card and success flash.
7. Click the trash on a prize. The small confirm modal appears with the prize name. Click Borrar. Card disappears, success flash.
8. If the campaign has zero prizes, the empty-state alert's "Agrega premios" link opens the same add modal.

- [ ] **Step 4: Run the full test suite to confirm no regressions**

```bash
docker exec raffle-web python manage.py test -v 1
```

Expected: All tests pass.

- [ ] **Step 5: Commit**

```bash
git add campaigns/templates/campaigns/campaign_detail.html
git commit -m "feat(prize): wire modal population JS for add/edit/delete triggers"
```

---

## Task 9: Final sweep, push, memory update

**Files:**
- (verification only)

- [ ] **Step 1: Confirm clean test run**

```bash
docker exec raffle-web python manage.py test -v 1
```

Expected: every test passes (50 prior + 16 new from this plan).

- [ ] **Step 2: Confirm no stray RaffleManager / RaffleAdmin paths broken**

```bash
grep -rnE "/admin/campaigns/prize/" campaigns/templates/ || echo "✓ No remaining admin links to the prize endpoint"
```

Expected: only the previously-removed lines (none present after Task 7).

- [ ] **Step 3: Push all commits**

```bash
git push origin main
```

- [ ] **Step 4: Update the project memory**

Append a new line to `~/.claude/projects/-home-elgran-Projects-raffle-campaign/memory/MEMORY.md`:

```markdown
- [Prize CRUD on dashboard](project_prize_crud_dashboard.md) — managers add/edit/delete prizes from /dashboard/campaign/<id>/ via Bootstrap modals, no admin trip required (shipped 2026-05-11)
```

And create the file `~/.claude/projects/-home-elgran-Projects-raffle-campaign/memory/project_prize_crud_dashboard.md`:

```markdown
---
name: Prize CRUD on dashboard
description: Status of the in-dashboard prize add/edit/delete feature
type: project
---
**Status as of 2026-05-11: SHIPPED to `main`.**

**What's in place:**
- `PrizeForm(ModelForm)` in `campaigns/forms.py`.
- Three POST-only views in `campaigns/views.py`: `prize_add`, `prize_edit`, `prize_delete`. All gated by `_get_managed_campaign_or_403`. Cross-campaign edit/delete returns 404.
- URL patterns `prize_add` / `prize_edit` / `prize_delete` in `campaigns/urls.py`.
- `_prize_modals.html` partial with shared add/edit modal + delete-confirm modal, included from `campaign_detail.html`.
- Trigger buttons on the prizes card-header, each prize card, and the empty-state alert. Modal is populated via `show.bs.modal` JS reading `data-` attributes.
- `next_prize_order` context var on `campaign_detail` defaults the order field to `(max + 10)` for sane new-prize ordering.
- 16 tests in `test_prize_crud.py`: form validation, view scoping (403/404/405), happy-path CRUD, superuser bypass, invalid-form flash, modal/trigger smoke.

**Why:** Managers shouldn't need Django admin access to run a campaign. Combined with the per-user campaign access work, a non-superuser staff member added to "Campaign Managers" group + listed on `Campaign.managers` can now do everything from `/dashboard/`.
```

---

## Verification Summary

After all tasks:

| Surface | Behavior |
|---|---|
| `/dashboard/campaign/<id>/` (Premios card-header) | "+ Añadir Premio" coral button → opens prize modal |
| `/dashboard/campaign/<id>/` (each prize card) | Pencil + trash icons in top-right → open prize / delete modals respectively |
| `/dashboard/campaign/<id>/` (empty state) | "Agrega premios" link opens prize modal |
| `POST /dashboard/campaign/<id>/prize/add/` | Creates prize, redirects, flashes success |
| `POST /dashboard/campaign/<id>/prize/<pid>/edit/` | Updates prize, redirects, flashes success |
| `POST /dashboard/campaign/<id>/prize/<pid>/delete/` | Deletes prize, redirects, flashes success |
| Cross-campaign URL tampering | 403 (non-manager) or 404 (manager but wrong prize) |
| GET on any prize endpoint | 405 |

Tests: 16 new in `campaigns/tests/test_prize_crud.py`. No model or migration changes. PrizeInline in CampaignAdmin remains for ops.
