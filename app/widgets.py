"""Custom WTForms widgets for the application."""
from wtforms.widgets import Input


class DateInput(Input):
    """
    Custom widget for rendering date fields.
    """
    input_type = 'date'
    validation_attrs = set(('required', 'min', 'max', 'step'))

    def __call__(self, field, **kwargs):
        if field.data:
            kwargs['value'] = field.data.isoformat() if hasattr(field.data, 'isoformat') else field.data
        return super().__call__(field, **kwargs)
