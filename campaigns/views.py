from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.contrib.auth import views as auth_views
from django.contrib import messages
from django.core.exceptions import PermissionDenied
from django.utils import timezone
from django.views.decorators.http import require_POST
from django.db.models import Count, Q, Max
from django.http import JsonResponse, HttpResponseRedirect
import json

from .models import Campaign, Prize, Submission, SubmissionCode, Raffle, RaffleWinner
from .forms import SubmissionForm, RaffleSegmentForm, CodeImportForm, PrizeForm
from .utils import import_codes_from_csv, conduct_raffle, export_winners_csv, export_submissions_csv


def _campaigns_for(user):
    """Queryset of campaigns the user can manage (superusers see all)."""
    if user.is_superuser:
        return Campaign.objects.all()
    return user.managed_campaigns.all()


def _get_managed_campaign_or_403(user, campaign_id):
    if user.is_superuser:
        return get_object_or_404(Campaign, id=campaign_id)
    try:
        return user.managed_campaigns.get(id=campaign_id)
    except Campaign.DoesNotExist:
        raise PermissionDenied("You don't have access to this campaign.")


def _get_campaign_for_host(request, slug):
    """Look up an active campaign bound to the request's host.

    Returns the Campaign or raises Http404. The host portion of
    ``request.get_host()`` is split on ``:`` because the reverse proxy
    terminates TLS and may forward ``a.test:8500`` in dev. We never
    expose port numbers in Domain.hostname.
    """
    host = request.get_host().split(":")[0]
    return get_object_or_404(
        Campaign,
        domain__hostname=host,
        slug=slug,
        is_active=True,
    )


def submission_form(request, campaign_slug):
    campaign = get_object_or_404(Campaign, slug=campaign_slug, is_active=True)
    now = timezone.now()

    campaign_open = campaign.start_date <= now <= campaign.end_date

    if request.method == 'POST':
        if not campaign_open:
            messages.error(request, 'This campaign is not currently accepting submissions.')
            return redirect('submission_form', campaign_slug=campaign_slug)

        form = SubmissionForm(request.POST, request.FILES, campaign=campaign)
        if form.is_valid():
            submission = form.save(commit=False)
            submission.campaign = campaign
            x_forwarded_for = request.META.get('HTTP_X_FORWARDED_FOR')
            if x_forwarded_for:
                submission.ip_address = x_forwarded_for.split(',')[0]
            else:
                submission.ip_address = request.META.get('REMOTE_ADDR')

            sc = form.cleaned_data.get('submission_code_obj')
            if sc:
                submission.submission_code = sc
                sc.is_used = True
                sc.used_at = timezone.now()
                sc.save()

            submission.save()
            return redirect('submission_success', campaign_slug=campaign_slug)
    else:
        form = SubmissionForm(campaign=campaign)

    return render(request, 'campaigns/submission_form.html', {
        'campaign': campaign,
        'form': form,
        'campaign_open': campaign_open,
    })


def submission_success(request, campaign_slug):
    campaign = get_object_or_404(Campaign, slug=campaign_slug)
    return render(request, 'campaigns/submission_success.html', {'campaign': campaign})


def submission_form_preview(request, campaign_slug, variant):
    from django.http import Http404
    if variant not in ('a', 'b', 'c'):
        raise Http404("Unknown preview variant")
    campaign = get_object_or_404(Campaign, slug=campaign_slug)
    form = SubmissionForm(campaign=campaign)
    return render(request, f'campaigns/_proposals/form_{variant}.html', {
        'campaign': campaign,
        'form': form,
        'campaign_open': True,
    })


@login_required
def dashboard(request):
    campaigns = _campaigns_for(request.user).order_by('-is_active', '-created_at')

    active_campaigns = campaigns.filter(is_active=True)
    inactive_campaigns = campaigns.filter(is_active=False)

    submissions_qs = Submission.objects.filter(campaign__in=campaigns)
    total_submissions = submissions_qs.count()
    total_campaigns = campaigns.count()
    recent_submissions = submissions_qs.select_related('campaign').order_by('-submitted_at')[:10]

    return render(request, 'campaigns/dashboard.html', {
        'active_campaigns': active_campaigns,
        'inactive_campaigns': inactive_campaigns,
        'total_submissions': total_submissions,
        'total_campaigns': total_campaigns,
        'recent_submissions': recent_submissions,
    })


@login_required
def campaign_detail(request, campaign_id):
    campaign = _get_managed_campaign_or_403(request.user, campaign_id)

    submissions = campaign.submissions.select_related('submission_code').order_by('-submitted_at')

    state_filter = request.GET.get('state', '')
    county_filter = request.GET.get('county', '')
    search = request.GET.get('search', '')

    if state_filter:
        submissions = submissions.filter(state=state_filter)
    if county_filter:
        submissions = submissions.filter(county__icontains=county_filter)
    if search:
        submissions = submissions.filter(
            Q(first_name__icontains=search) |
            Q(last_name__icontains=search) |
            Q(email__icontains=search) |
            Q(phone__icontains=search)
        )

    states = campaign.submissions.values_list('state', flat=True).distinct().order_by('state')

    prizes = campaign.prizes.all()
    next_prize_order = (campaign.prizes.aggregate(m=Max('order'))['m'] or 0) + 10
    codes_total = campaign.submission_codes.count()
    codes_used = campaign.submission_codes.filter(is_used=True).count()
    codes_available = codes_total - codes_used
    raffles = campaign.raffles.prefetch_related('winners__prize', 'winners__submission').order_by('-conducted_at')

    return render(request, 'campaigns/campaign_detail.html', {
        'campaign': campaign,
        'submissions': submissions,
        'prizes': prizes,
        'next_prize_order': next_prize_order,
        'states': states,
        'state_filter': state_filter,
        'county_filter': county_filter,
        'search': search,
        'codes_total': codes_total,
        'codes_used': codes_used,
        'codes_available': codes_available,
        'raffles': raffles,
    })


@login_required
@require_POST
def submission_set_validity(request, campaign_id, submission_id):
    """Toggle a submission's is_valid state. Used by the per-row buttons in
    the campaign detail page. Only managers of the campaign may invoke this."""
    campaign = _get_managed_campaign_or_403(request.user, campaign_id)
    submission = get_object_or_404(Submission, id=submission_id, campaign=campaign)

    action = request.POST.get('action')
    if action == 'invalidate':
        submission.is_valid = False
        submission.invalidation_reason = request.POST.get('reason', '').strip()[:200]
        submission.validated_at = timezone.now()
        submission.validated_by = request.user
        submission.save(update_fields=['is_valid', 'invalidation_reason', 'validated_at', 'validated_by'])
        messages.warning(request, f'{submission.full_name}\'s submission marked invalid.')
    elif action == 'validate':
        submission.is_valid = True
        submission.invalidation_reason = ''
        submission.validated_at = timezone.now()
        submission.validated_by = request.user
        submission.save(update_fields=['is_valid', 'invalidation_reason', 'validated_at', 'validated_by'])
        messages.success(request, f'{submission.full_name}\'s submission marked valid.')
    else:
        messages.error(request, 'Unknown action.')

    from django.urls import reverse
    next_url = request.POST.get('next') or reverse('campaign_detail', args=[campaign_id])
    return HttpResponseRedirect(next_url)


@login_required
def export_campaign_submissions(request, campaign_id):
    campaign = _get_managed_campaign_or_403(request.user, campaign_id)
    submissions = campaign.submissions.select_related('submission_code')

    state_filter = request.GET.get('state', '')
    county_filter = request.GET.get('county', '')
    if state_filter:
        submissions = submissions.filter(state=state_filter)
    if county_filter:
        submissions = submissions.filter(county__icontains=county_filter)

    return export_submissions_csv(campaign, submissions)


@login_required
def raffle_view(request, campaign_id):
    campaign = _get_managed_campaign_or_403(request.user, campaign_id)
    prizes = campaign.prizes.all()

    if not prizes.exists():
        messages.error(request, 'This campaign has no prizes configured. Please add prizes in the admin first.')
        return redirect('campaign_detail', campaign_id=campaign_id)

    segment_form = RaffleSegmentForm(request.POST or None)

    # Only valid submissions are eligible for raffles
    submissions = campaign.submissions.filter(is_valid=True)

    if request.method == 'POST' and segment_form.is_valid():
        state = segment_form.cleaned_data.get('state')
        county = segment_form.cleaned_data.get('county')
        date_from = segment_form.cleaned_data.get('date_from')
        date_to = segment_form.cleaned_data.get('date_to')

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

        prizes_with_quantities = []
        for prize in prizes:
            qty_key = f'prize_qty_{prize.id}'
            try:
                qty = int(request.POST.get(qty_key, 0))
                if qty > 0:
                    prizes_with_quantities.append((prize, qty))
            except (ValueError, TypeError):
                pass

        if not prizes_with_quantities:
            messages.error(request, 'Please select at least one prize with a quantity greater than 0.')
        elif filtered_submissions.count() == 0:
            messages.error(request, 'No participants match the selected filters.')
        else:
            total_winners_needed = sum(q for _, q in prizes_with_quantities)
            if total_winners_needed > filtered_submissions.count():
                messages.warning(
                    request,
                    f'Requested {total_winners_needed} winners but only {filtered_submissions.count()} '
                    f'participants in pool. Some prizes may have fewer winners.'
                )

            consume_pool = segment_form.cleaned_data.get('consume_pool', True)
            segment_data = dict(segment_form.cleaned_data)
            # Persist the store id (FK object isn't JSON-serializable downstream)
            segment_data['store_id'] = store.id if store else None
            segment_data.pop('store', None)  # drop the unserializable Store object
            raffle = conduct_raffle(
                campaign=campaign,
                prizes_with_quantities=prizes_with_quantities,
                submission_qs=filtered_submissions,
                conducted_by=request.user,
                segment_data=segment_data,
                consume_pool=consume_pool,
                excluded_already_participated=not include_already_participated,
            )
            messages.success(request, f'Raffle conducted successfully! {raffle.winners.count()} winners selected.')
            return redirect('raffle_results', raffle_id=raffle.id)

    states = campaign.submissions.values_list('state', flat=True).distinct().order_by('state')

    return render(request, 'campaigns/raffle.html', {
        'campaign': campaign,
        'prizes': prizes,
        'segment_form': segment_form,
        'total_submissions': submissions.count(),
        'states': states,
    })


@login_required
def raffle_results(request, raffle_id):
    raffle = get_object_or_404(Raffle, id=raffle_id)
    if not request.user.is_superuser and not raffle.campaign.managers.filter(id=request.user.id).exists():
        raise PermissionDenied("You don't have access to this raffle.")
    winners = raffle.winners.select_related('submission', 'prize').order_by('prize__order', 'position')

    prizes_winners = {}
    for winner in winners:
        if winner.prize not in prizes_winners:
            prizes_winners[winner.prize] = []
        prizes_winners[winner.prize].append(winner)

    return render(request, 'campaigns/raffle_results.html', {
        'raffle': raffle,
        'campaign': raffle.campaign,
        'prizes_winners': prizes_winners,
        'winners': winners,
    })


@login_required
def export_raffle_winners(request, raffle_id):
    raffle = get_object_or_404(Raffle, id=raffle_id)
    if not request.user.is_superuser and not raffle.campaign.managers.filter(id=request.user.id).exists():
        raise PermissionDenied("You don't have access to this raffle.")
    return export_winners_csv(raffle)


@login_required
def import_codes_view(request, campaign_id):
    campaign = _get_managed_campaign_or_403(request.user, campaign_id)

    if request.method == 'POST':
        form = CodeImportForm(request.POST, request.FILES)
        if form.is_valid():
            csv_file = request.FILES['csv_file']
            skip_dup = form.cleaned_data.get('skip_duplicates', True)

            try:
                created, skipped, errors = import_codes_from_csv(campaign, csv_file, skip_dup)
                messages.success(
                    request,
                    f'Import complete: {created} codes added, {skipped} skipped.'
                )
                if errors:
                    for err in errors[:5]:
                        messages.warning(request, err)
            except Exception as e:
                messages.error(request, f'Error importing file: {str(e)}')

            return redirect('campaign_detail', campaign_id=campaign_id)
    else:
        form = CodeImportForm()

    return render(request, 'campaigns/import_codes.html', {
        'campaign': campaign,
        'form': form,
    })


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


@login_required
@require_POST
def prize_delete(request, campaign_id, prize_id):
    campaign = _get_managed_campaign_or_403(request.user, campaign_id)
    prize = get_object_or_404(Prize, id=prize_id, campaign=campaign)
    if prize.winners.exists():
        messages.error(
            request,
            f'No se puede borrar "{prize.name}": tiene ganadores asociados a un sorteo.',
        )
        return redirect('campaign_detail', campaign_id=campaign.id)
    prize_name = prize.name
    prize.delete()
    messages.success(request, f'Premio "{prize_name}" borrado.')
    return redirect('campaign_detail', campaign_id=campaign.id)


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


@login_required
def raffle_audit(request, raffle_id):
    """Render the audit page for a raffle, including verification status."""
    from .utils import verify_raffle_audit
    raffle = get_object_or_404(
        Raffle.objects.select_related('campaign', 'conducted_by'),
        id=raffle_id,
    )
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


@login_required
def raffle_audit_json(request, raffle_id):
    """Return the full audit blob as a downloadable JSON file."""
    from .utils import verify_raffle_audit
    raffle = get_object_or_404(
        Raffle.objects.select_related('campaign', 'conducted_by'),
        id=raffle_id,
    )
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
