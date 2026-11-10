import hashlib
from datetime import timedelta

from django.contrib.auth.backends import BaseBackend
from django.contrib.auth.hashers import make_password
from django.db import transaction
from django.utils import timezone

from .models import Account, LoginThrottle


class AccountBackend(BaseBackend):
    def authenticate(self, request, username=None, password=None, email=None, **kwargs):
        normalized = Account.objects.normalize_email(email or username)
        if not normalized or password is None:
            return None
        key = hashlib.sha256(normalized.encode("utf-8")).hexdigest()
        with transaction.atomic():
            throttle, _ = LoginThrottle.objects.select_for_update().get_or_create(key=key)
            now = timezone.now()
            cutoff = now.timestamp() - 900
            if throttle.blocked_until and throttle.blocked_until > now:
                return None
            recent = [value for value in throttle.failures if isinstance(value, (int, float)) and value > cutoff]
            try:
                account = Account.objects.get(email=normalized)
            except Account.DoesNotExist:
                account = None
            if account is None or not account.is_active:
                make_password(password)
                valid = False
            else:
                valid = account.check_password(password)
            if valid:
                throttle.failures = []
                throttle.blocked_until = None
                throttle.save(update_fields=["failures", "blocked_until", "updated_at"])
                return account
            recent.append(now.timestamp())
            throttle.failures = recent
            throttle.blocked_until = now + timedelta(minutes=15) if len(recent) >= 5 else None
            throttle.save(update_fields=["failures", "blocked_until", "updated_at"])
        return None

    def get_user(self, user_id):
        try:
            account = Account.objects.get(pk=user_id)
        except (Account.DoesNotExist, ValueError, TypeError):
            return None
        return account if account.is_active else None
