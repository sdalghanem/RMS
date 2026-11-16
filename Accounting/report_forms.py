from calendar import monthrange
from datetime import date
from django import forms
from django.utils import timezone
from Management.models import Profile, Beneficiary, MainProgram, SubProgram
from .reporting import beneficiary_name

class BeneficiaryChoice(forms.ModelChoiceField):
    def label_from_instance(self, obj):
        return beneficiary_name(obj)

class PeriodForm(forms.Form):
    report_type = forms.ChoiceField(label='الفترة', choices=[('annual', 'سنوي'),
        ('quarterly', 'ربع سنوي'), ('half', 'نصف سنوي'), ('custom', 'فترة مخصصة')])
    year = forms.IntegerField(label='السنة', min_value=1900, max_value=9998, required=False)
    quarter = forms.TypedChoiceField(label='الربع', choices=[(1,'الأول'),(2,'الثاني'),(3,'الثالث'),(4,'الرابع')], coerce=int, required=False)
    half = forms.TypedChoiceField(label='النصف', choices=[(1,'الأول'),(2,'الثاني')], coerce=int, required=False)
    from_date = forms.DateField(label='من تاريخ', required=False, widget=forms.DateInput(attrs={'type':'date'}))
    to_date = forms.DateField(label='إلى تاريخ', required=False, widget=forms.DateInput(attrs={'type':'date'}))

    def clean(self):
        data = super().clean()
        if self.errors:
            return data
        kind = data['report_type']
        year = data.get('year') or timezone.localdate().year
        if kind == 'custom':
            start, end = data.get('from_date'), data.get('to_date')
            if not start or not end or end < start or end.year > 9998:
                raise forms.ValidationError('أدخل فترة صحيحة؛ تاريخ النهاية لا يسبق البداية.')
        else:
            month, count = 1, 12
            if kind == 'quarterly':
                if not data.get('quarter'):
                    raise forms.ValidationError('اختر الربع.')
                month, count = (data['quarter'] - 1) * 3 + 1, 3
            elif kind == 'half':
                if not data.get('half'):
                    raise forms.ValidationError('اختر نصف السنة.')
                month, count = (data['half'] - 1) * 6 + 1, 6
            last = month + count - 1
            start, end = date(year, month, 1), date(year, last, monthrange(year, last)[1])
        data.update(start=start, end=end)
        return data

class SponsorReportForm(PeriodForm):
    donor = forms.ModelChoiceField(label='الكافل', queryset=Profile.objects.filter(role=Profile.Roles.DONOR).select_related('user'))

class AssociationReportForm(PeriodForm):
    donor = forms.ModelChoiceField(label='الكافل (اختياري)', required=False, queryset=Profile.objects.filter(role=Profile.Roles.DONOR).select_related('user'))
    beneficiary = BeneficiaryChoice(label='المستفيد', required=False, queryset=Beneficiary.objects.all())
    main_program = forms.ModelChoiceField(label='البرنامج الرئيسي', required=False, queryset=MainProgram.objects.all())
    sub_program = forms.ModelChoiceField(label='البرنامج الفرعي', required=False, queryset=SubProgram.objects.select_related('main_program').all())

    def clean(self):
        data = super().clean()
        main, sub = data.get('main_program'), data.get('sub_program')
        if main and sub and sub.main_program_id != main.pk:
            self.add_error('sub_program', 'البرنامج الفرعي لا يتبع البرنامج الرئيسي المختار.')
        return data
