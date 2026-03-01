from django.db import models
from django.contrib.auth.models import AbstractBaseUser, PermissionsMixin
from .manager import UserManager
from rest_framework_simplejwt.tokens import RefreshToken
from django.utils.translation import gettext_lazy as _
from django.contrib.auth import authenticate
from django.conf import settings
from django.utils import timezone
import secrets
from decimal import Decimal


class College(models.Model):
    name = models.CharField(max_length=255, unique=True)
    # Optional domain for future enforcement of one admin per domain
    domain = models.CharField(max_length=255, blank=True, null=True, unique=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL if hasattr(settings, "AUTH_USER_MODEL") else "users.User",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="owned_colleges",
    )

    def __str__(self) -> str:
        return self.name


class User(AbstractBaseUser, PermissionsMixin):
    ROLE_ADMIN = "admin"
    ROLE_STUDENT = "student"
    ROLE_OWNER = "owner"

    ROLE_CHOICES = (
        (ROLE_ADMIN, "Admin"),
        (ROLE_STUDENT, "Student"),
        (ROLE_OWNER, "Owner"),
    )

    id = models.BigAutoField(primary_key=True, editable=False)
    name = models.CharField(max_length=255, verbose_name=_("Name"))
    username = models.CharField(max_length=100, unique=True, verbose_name=_("Username"))
    email = models.EmailField(max_length=255, blank=True, null=True)

    is_staff = models.BooleanField(default=False)
    is_superuser = models.BooleanField(default=False)
    is_active = models.BooleanField(default=True)
    date_joined = models.DateTimeField(auto_now_add=True)
    last_login = models.DateTimeField(auto_now=True)

    role = models.CharField(max_length=20, choices=ROLE_CHOICES)
    college = models.ForeignKey(College, on_delete=models.CASCADE, null=True, blank=True)
    # Optional: store the e-canteen card code used at signup for student/owner
    ecard_code = models.CharField(max_length=20, null=True, blank=True)

    # Admin email verification flag (only enforced for admins at signup phase via OTP flow)
    is_email_verified = models.BooleanField(default=False)

    USERNAME_FIELD = "username"
    REQUIRED_FIELDS = ["name"]

    objects = UserManager()

    def __str__(self) -> str:
        return self.get_username()

    @property
    def get_name(self) -> str:
        return self.name

    @property
    def get_role(self) -> str:
        return self.role

    def tokens(self) -> dict:
        refresh = RefreshToken.for_user(self)
        return {"refresh": str(refresh), "access": str(refresh.access_token)}

    # ===== Helper methods to be used by serializers/views =====
    @classmethod
    def signup_admin(cls, *, name: str, username: str, password: str, email: str | None, college: College | None = None):
        user = cls.objects.create_user(
            name=name,
            username=username,
            password=password,
            role=cls.ROLE_ADMIN,
            email=email,
            college=college,
            is_staff=True,
        )
        return user

    @classmethod
    def signup_student(cls, *, name: str, username: str, password: str, college: College | None = None):
        user = cls.objects.create_user(
            name=name,
            username=username,
            password=password,
            role=cls.ROLE_STUDENT,
            college=college,
        )
        return user

    @classmethod
    def signup_owner(cls, *, name: str, username: str, password: str, college: College | None = None):
        user = cls.objects.create_user(
            name=name,
            username=username,
            password=password,
            role=cls.ROLE_OWNER,
            college=college,
        )
        return user

    @staticmethod
    def login_with_credentials(*, username: str, password: str, request=None):
        return authenticate(request, username=username, password=password)

    @staticmethod
    def blacklist_refresh_token(refresh_token: str):
        token = RefreshToken(refresh_token)
        token.blacklist()


class OneTimePassword(models.Model):
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL if hasattr(settings, "AUTH_USER_MODEL") else "users.User",
        on_delete=models.CASCADE,
        related_name="otps",
    )
    code = models.CharField(max_length=6)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self) -> str:
        return f"OTP for {self.user_id}"


class ECanteenCard(models.Model):
    ROLE_CHOICES = User.ROLE_CHOICES if 'User' in globals() else (
        ("student", "Student"),
        ("owner", "Owner"),
    )

    code = models.CharField(max_length=20, unique=True)
    role = models.CharField(max_length=20, choices=ROLE_CHOICES)
    college = models.ForeignKey(College, on_delete=models.CASCADE, related_name="ecards")
    is_used = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)
    expires_at = models.DateTimeField(null=True, blank=True)

    def is_valid(self) -> bool:
        if self.is_used:
            return False
        if self.expires_at and timezone.now() > self.expires_at:
            return False
        return True

    def __str__(self) -> str:
        return f"Card {self.code} ({self.role})"


class Shop(models.Model):
    name = models.CharField(max_length=255)
    owner = models.OneToOneField(
        settings.AUTH_USER_MODEL if hasattr(settings, "AUTH_USER_MODEL") else "users.User",
        on_delete=models.CASCADE,
        related_name="shop",
        null=True,
        blank=True,
    )
    college = models.ForeignKey(College, on_delete=models.CASCADE, related_name="shops")

    @staticmethod
    def _gen_code(n: int = 10) -> str:
        alphabet = 'ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789'
        return ''.join(secrets.choice(alphabet) for _ in range(n))

    # Step 1: make code nullable/non-unique to allow migration; we'll backfill and enforce uniqueness later
    code = models.CharField(max_length=20, null=True, blank=True)
    pending_owner_ecard_code = models.CharField(max_length=20, null=True, blank=True)
    owner_display_name = models.CharField(max_length=255, null=True, blank=True)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self) -> str:
        return f"{self.name} [{self.code}]"


class MenuItem(models.Model):
    shop = models.ForeignKey(Shop, on_delete=models.CASCADE, related_name="menu_items")
    name = models.CharField(max_length=255)
    price = models.DecimalField(max_digits=8, decimal_places=2)
    image_url = models.URLField(max_length=500, null=True, blank=True)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["name"]
        unique_together = ("shop", "name")

    def __str__(self) -> str:
        return f"{self.shop.name}: {self.name} ({self.price})"


class Order(models.Model):
    STATUS_PENDING = 'pending'
    STATUS_PREPARING = 'preparing'
    STATUS_READY = 'ready'
    STATUS_COMPLETED = 'completed'
    STATUS_CANCELLED = 'cancelled'

    STATUS_CHOICES = (
        (STATUS_PENDING, 'Pending'),
        (STATUS_PREPARING, 'Preparing'),
        (STATUS_READY, 'Ready'),
        (STATUS_COMPLETED, 'Completed'),
        (STATUS_CANCELLED, 'Cancelled'),
    )

    shop = models.ForeignKey(Shop, on_delete=models.CASCADE, related_name='orders')
    student = models.ForeignKey(
        settings.AUTH_USER_MODEL if hasattr(settings, "AUTH_USER_MODEL") else "users.User",
        on_delete=models.CASCADE,
        related_name='orders'
    )
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default=STATUS_PENDING)
    total_amount = models.DecimalField(max_digits=10, decimal_places=2, default=Decimal('0.00'))
    # Per-shop daily token tracking
    token_number = models.IntegerField(default=0)
    token_code = models.CharField(max_length=16, default='', blank=True)
    is_paid = models.BooleanField(default=False)
    is_picked = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self) -> str:
        return f"Order #{self.id} - {self.shop.name} - {self.student.name}"


class OrderItem(models.Model):
    order = models.ForeignKey(Order, on_delete=models.CASCADE, related_name='items')
    menu_item = models.ForeignKey(MenuItem, on_delete=models.SET_NULL, null=True, blank=True)
    name = models.CharField(max_length=255)
    price = models.DecimalField(max_digits=8, decimal_places=2)
    quantity = models.PositiveIntegerField(default=1)

    def line_total(self) -> Decimal:
        return (self.price or Decimal('0.00')) * Decimal(self.quantity or 0)

    def __str__(self) -> str:
        return f"{self.name} x {self.quantity}"


class DeviceToken(models.Model):
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL if hasattr(settings, "AUTH_USER_MODEL") else "users.User",
        on_delete=models.CASCADE,
        related_name='device_tokens'
    )
    token = models.CharField(max_length=255, unique=True)
    platform = models.CharField(max_length=20, blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self) -> str:
        return f"Token for {self.user_id}"
