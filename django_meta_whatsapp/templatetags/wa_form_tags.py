from django import template
from django.utils.safestring import mark_safe

register = template.Library()

FIELD_CLASS = (
    "block w-full rounded-lg border border-gray-200 bg-white px-3 py-2 text-sm "
    "text-gray-700 placeholder-gray-400 focus:border-emerald-500 focus:outline-none "
    "focus:ring-2 focus:ring-emerald-500 transition-colors"
)

TEXTAREA_CLASS = FIELD_CLASS + " resize-vertical min-h-[80px]"
SELECT_CLASS = FIELD_CLASS
CHECKBOX_CLASS = "h-4 w-4 rounded border-gray-300 text-emerald-600 focus:ring-emerald-500"


@register.filter(name="add_form_class")
def add_form_class(field):
    widget = field.field.widget
    widget_type = widget.__class__.__name__
    if widget_type == "Textarea":
        css = TEXTAREA_CLASS
    elif widget_type in ("Select", "NullBooleanSelect"):
        css = SELECT_CLASS
    elif widget_type == "CheckboxInput":
        css = CHECKBOX_CLASS
    else:
        css = FIELD_CLASS
    return field.as_widget(attrs={"class": css})
