import os

from django.core.management.base import BaseCommand

from accounts.models import User

DEMO_USERS = [
    ("analyst", User.Role.ANALYST, False),
    ("manager", User.Role.MANAGER, False),
    ("admin", User.Role.ADMIN, True),
]


class Command(BaseCommand):
    help = "Create demo users (analyst / manager / admin). Idempotent."

    def handle(self, *args, **options):
        password = os.environ.get("DEMO_USER_PASSWORD", "finguard123")
        for username, role, is_super in DEMO_USERS:
            user, created = User.objects.get_or_create(
                username=username,
                defaults={"role": role, "is_staff": is_super, "is_superuser": is_super},
            )
            if created:
                user.set_password(password)
                user.save()
                self.stdout.write(self.style.SUCCESS(f"Created demo user '{username}' ({role})"))
