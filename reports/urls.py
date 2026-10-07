from django.urls import path
from rest_framework.routers import DefaultRouter

from .trends import FhirExportView, MarkerListView, TrendView
from .views import ReportViewSet

router = DefaultRouter()
router.register("reports", ReportViewSet, basename="report")
urlpatterns = [
    *router.urls,
    path("trends/", TrendView.as_view(), name="trends"),
    path("markers/", MarkerListView.as_view(), name="markers"),
    path("fhir/Patient/$everything", FhirExportView.as_view(), name="fhir-export"),
]
