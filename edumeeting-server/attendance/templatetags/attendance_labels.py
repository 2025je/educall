from django import template

from attendance.access import role_label

register = template.Library()
register.filter("role_label", role_label)
