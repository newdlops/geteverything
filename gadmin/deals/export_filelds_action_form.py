from django import forms
from django_admin_action_forms import AdminActionForm

class ExportFieldsActionForm(AdminActionForm):
    fields_to_export = forms.MultipleChoiceField(
        label="내보낼 컬럼 선택",
        widget=forms.CheckboxSelectMultiple,
        required=True
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # self.modeladmin, self.request, self.queryset 사용 가능
        choices = [(f, f) for f in self.modeladmin.list_display]
        self.fields['fields_to_export'].choices = choices
        self.fields['fields_to_export'].initial = [f for f, _ in choices]
