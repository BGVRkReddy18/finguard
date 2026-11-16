from django.contrib.auth.models import AbstractUser
from django.db import models


class User(AbstractUser):
    """Custom user with a role — drives role-based access control (RBAC) across the API."""

    class Role(models.TextChoices):
        ANALYST = "ANALYST", "Fraud Analyst"
        MANAGER = "MANAGER", "Risk Manager"
        ADMIN = "ADMIN", "Administrator"

    role = models.CharField(max_length=16, choices=Role.choices, default=Role.ANALYST)

    @property
    def is_manager(self) -> bool:
        return self.is_superuser or self.role in {self.Role.MANAGER, self.Role.ADMIN}
