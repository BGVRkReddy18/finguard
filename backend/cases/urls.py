from rest_framework.routers import SimpleRouter

from .views import AuditLogViewSet, FraudCaseViewSet

router = SimpleRouter()
router.register("cases", FraudCaseViewSet, basename="case")
router.register("audit-logs", AuditLogViewSet, basename="auditlog")

urlpatterns = router.urls
