from collections import defaultdict
from datetime import timedelta
from typing import Dict

from dateutil.relativedelta import relativedelta

from django.conf import settings
from django.contrib import messages
from django.urls import reverse
from django.http import HttpResponseRedirect, HttpResponse, HttpRequest
from django.shortcuts import render
from django.utils import timezone

from django.db.models import Count, Q
from dojo.utils import add_breadcrumb, get_punchcard_data
from dojo.models import Answered_Survey
from dojo.authorization.roles_permissions import Permissions
from dojo.engagement.queries import get_authorized_engagements
from dojo.finding.queries import get_authorized_findings
from dojo.authorization.authorization import user_has_configuration_permission


def home(request: HttpRequest) -> HttpResponse:
    return HttpResponseRedirect(reverse('dashboard'))


def dashboard(request: HttpRequest) -> HttpResponse:
    # No one wants a slow dashboard
    engagements = get_authorized_engagements(Permissions.Engagement_View).distinct()
    findings = get_authorized_findings(Permissions.Finding_View).filter(duplicate=False).distinct()\
        .only('severity', 'id', 'created', 'mitigated').prefetch_related('risk_acceptance_set')

    engagement_count = engagements.filter(active=True).count()

    today = timezone.now().date()
    beginning_date = today - timedelta(days=6)

    finding_count = findings.filter(created__gte=beginning_date, created__lte=today).order_by().count()

    mitigated_count = findings.filter(mitigated__gte=beginning_date, mitigated__lte=today).only('id').order_by().count()

    accepted_count = findings.filter(risk_acceptance__created__gte=beginning_date, risk_acceptance__created__lte=today).only('id').order_by().count()

    severity_count_all = get_severities_all(findings)

    severity_count_by_month = get_severities_by_month(findings, today)

    punchcard, ticks = get_punchcard_data(findings, today - relativedelta(weeks=26), 26)

    if user_has_configuration_permission(request.user, 'dojo.view_engagement_survey', 'staff'):
        unassigned_surveys = Answered_Survey.objects.filter(assignee_id__isnull=True, completed__gt=0, ) \
            .filter(Q(engagement__isnull=True) | Q(engagement__in=engagements))
    else:
        unassigned_surveys = None

    if request.user.is_superuser and not settings.FEATURE_CONFIGURATION_AUTHORIZATION:
        message = '''Legacy authorization for changing configurations based on staff users will be
                     removed with version 2.12.0 / 5. July 2022. If you have set
                     `FEATURE_CONFIGURATION_AUTHORIZATION` to `False` in your local configuration,
                     remove this local setting and start using the new authorization.'''
        messages.add_message(request, messages.WARNING, message, extra_tags='alert-warning')

    add_breadcrumb(request=request, clear=True)
    return render(request, 'dojo/dashboard.html', {
        'engagement_count': engagement_count,
        'finding_count': finding_count,
        'mitigated_count': mitigated_count,
        'accepted_count': accepted_count,
        'critical': severity_count_all['Critical'],
        'high': severity_count_all['High'],
        'medium': severity_count_all['Medium'],
        'low': severity_count_all['Low'],
        'info': severity_count_all['Info'],
        'by_month': severity_count_by_month,
        'punchcard': punchcard,
        'ticks': ticks,
        'surveys': unassigned_surveys,
    })


def get_severities_all(findings) -> Dict[str, int]:
    severities_all = findings.values('severity').annotate(count=Count('severity')).order_by()
    return defaultdict(lambda: 0, {s['severity']: s['count'] for s in severities_all})


def get_severities_by_month(findings, today):
    severities_by_month = findings\
        .filter(created__date__gte=(today - relativedelta(months=6)))\
        .values('created__year', 'created__month', 'severity')\
        .annotate(count=Count('severity'))\
        .order_by()

    # The chart expects a, b, c, d, e instead of Critical, High, ...
    SEVERITY_MAP = {
        'Critical': 'a',
        'High':     'b',  # noqa: E241
        'Medium':   'c',  # noqa: E241
        'Low':      'd',  # noqa: E241
        'Info':     'e',  # noqa: E241
    }

    results = {}
    for ms in severities_by_month:
        key = f"{ms['created__year']}-{ms['created__month']:02}"
        month_stats = results.setdefault(key, {'y': key, 'a': 0, 'b': 0, 'c': 0, 'd': 0, 'e': 0, None: 0})
        month_stats[SEVERITY_MAP.get(ms['severity'])] += ms['count']

    return [v for k, v in sorted(results.items())]
