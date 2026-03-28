from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.contrib.auth import views as auth_views
from django.contrib import messages
from django.utils import timezone
from django.db.models import Count, Q
from django.http import JsonResponse
import json

from .models import Campaign, Prize, Submission, SubmissionCode, Raffle, RaffleWinner
from .forms import SubmissionForm, RaffleSegmentForm, CodeImportForm
from .utils import import_codes_from_csv, conduct_raffle, export_winners_csv, export_submissions_csv


def submission_form(request, campaign_slug):
    campaign = get_object_or_404(Campaign, slug=campaign_slug, is_active=True)
    now = timezone.now()

    campaign_open = campaign.start_date <= now <= campaign.end_date

    if request.method == 'POST':
        if not campaign_open:
            messages.error(request, 'This campaign is not currently accepting submissions.')
            return redirect('submission_form', campaign_slug=campaign_slug)

        form = SubmissionForm(request.POST, campaign=campaign)
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


@login_required
def dashboard(request):
    campaigns = Campaign.objects.annotate(
        submission_count=Count('submissions'),
    ).order_by('-is_active', '-created_at')

    active_campaigns = campaigns.filter(is_active=True)
    inactive_campaigns = campaigns.filter(is_active=False)

    total_submissions = Submission.objects.count()
    total_campaigns = Campaign.objects.count()
    recent_submissions = Submission.objects.select_related('campaign').order_by('-submitted_at')[:10]

    return render(request, 'campaigns/dashboard.html', {
        'active_campaigns': active_campaigns,
        'inactive_campaigns': inactive_campaigns,
        'total_submissions': total_submissions,
        'total_campaigns': total_campaigns,
        'recent_submissions': recent_submissions,
    })


@login_required
def campaign_detail(request, campaign_id):
    campaign = get_object_or_404(Campaign, id=campaign_id)

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
    codes_total = campaign.submission_codes.count()
    codes_used = campaign.submission_codes.filter(is_used=True).count()
    codes_available = codes_total - codes_used
    raffles = campaign.raffles.prefetch_related('winners__prize', 'winners__submission').order_by('-conducted_at')

    return render(request, 'campaigns/campaign_detail.html', {
        'campaign': campaign,
        'submissions': submissions,
        'prizes': prizes,
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
def export_campaign_submissions(request, campaign_id):
    campaign = get_object_or_404(Campaign, id=campaign_id)
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
    campaign = get_object_or_404(Campaign, id=campaign_id)
    prizes = campaign.prizes.all()

    if not prizes.exists():
        messages.error(request, 'This campaign has no prizes configured. Please add prizes in the admin first.')
        return redirect('campaign_detail', campaign_id=campaign_id)

    segment_form = RaffleSegmentForm(request.POST or None)

    submissions = campaign.submissions.all()

    if request.method == 'POST' and segment_form.is_valid():
        state = segment_form.cleaned_data.get('state')
        county = segment_form.cleaned_data.get('county')
        date_from = segment_form.cleaned_data.get('date_from')
        date_to = segment_form.cleaned_data.get('date_to')

        filtered_submissions = campaign.submissions.all()
        if state:
            filtered_submissions = filtered_submissions.filter(state=state)
        if county:
            filtered_submissions = filtered_submissions.filter(county__icontains=county)
        if date_from:
            filtered_submissions = filtered_submissions.filter(submitted_at__date__gte=date_from)
        if date_to:
            filtered_submissions = filtered_submissions.filter(submitted_at__date__lte=date_to)

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

            raffle = conduct_raffle(
                campaign=campaign,
                prizes_with_quantities=prizes_with_quantities,
                submission_qs=filtered_submissions,
                conducted_by=request.user,
                segment_data=segment_form.cleaned_data,
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
    winners = raffle.winners.select_related('submission', 'prize').order_by('prize__order', 'position')

    prizes_winners = {}
    for winner in winners:
        if winner.prize not in prizes_winners:
            prizes_winners[winner.prize] = []
        prizes_winners[winner.prize].append(winner)

    return render(request, 'campaigns/raffle_results.html', {
        'raffle': raffle,
        'prizes_winners': prizes_winners,
        'winners': winners,
    })


@login_required
def export_raffle_winners(request, raffle_id):
    raffle = get_object_or_404(Raffle, id=raffle_id)
    return export_winners_csv(raffle)


@login_required
def import_codes_view(request, campaign_id):
    campaign = get_object_or_404(Campaign, id=campaign_id)

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
    """AJAX endpoint to get submission count for given filters."""
    campaign = get_object_or_404(Campaign, id=campaign_id)

    state = request.GET.get('state', '')
    county = request.GET.get('county', '')
    date_from = request.GET.get('date_from', '')
    date_to = request.GET.get('date_to', '')

    qs = campaign.submissions.all()
    if state:
        qs = qs.filter(state=state)
    if county:
        qs = qs.filter(county__icontains=county)
    if date_from:
        qs = qs.filter(submitted_at__date__gte=date_from)
    if date_to:
        qs = qs.filter(submitted_at__date__lte=date_to)

    return JsonResponse({'count': qs.count()})
