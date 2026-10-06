from django.contrib import admin
from django.contrib.auth.admin import UserAdmin

from .models import Center, Consent, User


@admin.register(User)
class MedTimelineUserAdmin(UserAdmin):
    fieldsets = UserAdmin.fieldsets + (("Role", {"fields": ("role", "center")}),)
    list_display = ("username", "email", "role", "center")


admin.site.register(Center)
admin.site.register(Consent)
