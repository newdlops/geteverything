from django import forms
from django.core.exceptions import FieldDoesNotExist
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
        model = self.modeladmin.model
        choices = []
        for field_name in self.modeladmin.list_display:
            try:
                field = model._meta.get_field(field_name)
                verbose = getattr(field, 'verbose_name', None)
                label = str(verbose) if verbose else field_name.replace('_', ' ').capitalize()
            except FieldDoesNotExist:
                label = field_name.replace('_', ' ').capitalize()
            choices.append((field_name, label))
        self.fields['fields_to_export'].choices = choices
        self.fields['fields_to_export'].initial = [name for name, _ in choices]
