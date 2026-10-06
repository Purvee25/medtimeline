from django.contrib import admin

from .models import AccessLog, Observation, Report

admin.site.register(Report)
admin.site.register(Observation)
admin.site.register(AccessLog)
