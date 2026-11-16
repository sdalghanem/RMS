from django.shortcuts import render
from django.utils import timezone
from .report_forms import SponsorReportForm, AssociationReportForm
from django.core.exceptions import PermissionDenied
from .reporting import current_sponsor_scope, current_sponsor_expenses, association_benefits

NOTICE = 'المصروفات المستوردة بتاريخ 5 نوفمبر 2026 تظهر وفق تاريخ تسجيلها الحالي؛ معالجة تواريخها التاريخية مؤجلة.'

def requesting_donor(request):
    profile = getattr(request.user, 'profile', None)
    if request.user.is_superuser or getattr(profile,'role',None) != 'donor':
        return None
    scope=current_sponsor_scope(profile)
    requested=request.GET.getlist('beneficiary')
    if (not scope or any(value != str(profile.pk) for value in request.GET.getlist('donor'))
            or any(value not in {str(k) for k in scope} for value in requested)):
        raise PermissionDenied
    return profile

def setup(request, association=False, form=None, status=200):
    role = getattr(getattr(request.user, 'profile', None), 'role', None)
    if form is None:
        form=(AssociationReportForm if association else SponsorReportForm)(initial={
            'report_type':'annual','year':timezone.localdate().year,'quarter':1,'half':1})
    donor=None if association else requesting_donor(request)
    if donor:
        form.fields['donor'].queryset=form.fields['donor'].queryset.filter(pk=donor.pk)
        form.initial['donor']=donor.pk
    return render(request, 'Accounting/sponsorship_reports.html', {
        'association': association,
        'can_association': request.user.is_superuser or role in ('system_admin', 'accountant'),
        'form':form,
        'date_notice': NOTICE}, status=status)

def validated_form(request, form_class):
    data = request.GET.copy()
    # Existing links default to the sponsor annual report.
    data.setdefault('report_type', 'annual')
    data['report_type'] = {'year': 'annual', 'quarter': 'quarterly'}.get(data['report_type'], data['report_type'])
    if form_class is SponsorReportForm:
        donor=requesting_donor(request)
        if donor:
            data['donor']=str(donor.pk)
    return form_class(data)

def sponsor_print(request):
    form = validated_form(request, SponsorReportForm)
    if not form.is_valid():
        return setup(request, form=form, status=400)
    data = form.cleaned_data
    result = current_sponsor_expenses(data['donor'], data['start'], data['end'])
    result.update(start=data['start'], end=data['end'], issued=timezone.localtime(), date_notice=NOTICE,
                  title='تقرير مصروفات فترة الكفالة')
    return render(request, 'Accounting/sponsorship_report_print.html', result)

def association_print(request):
    form = validated_form(request, AssociationReportForm)
    if not form.is_valid():
        return setup(request, association=True, form=form, status=400)
    data = form.cleaned_data
    filters = {key: data.get(key) for key in ('beneficiary', 'main_program', 'sub_program', 'donor')}
    result = association_benefits(data['start'], data['end'], **filters)
    result.update(start=data['start'], end=data['end'], issued=timezone.localtime(), date_notice=NOTICE,
                  title='تقرير إجمالي استفادة المستفيدين من البرامج', filters=filters)
    return render(request, 'Accounting/association_report_print.html', result)
