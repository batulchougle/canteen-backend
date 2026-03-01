import random
from typing import Optional

from django.conf import settings
from django.core.mail import EmailMessage

from .models import User, OneTimePassword


def generate_otp(length: int = 6) -> str:
    # 6-digit numeric OTP
    return ''.join(str(random.randint(0, 9)) for _ in range(length))


def send_code_to_user(email: str, user: Optional[User] = None) -> None:
    """
    Generates a 6-digit OTP, stores it in OneTimePassword, and emails it to the user.
    - email: user's email address
    - user: optional user instance (if already available); otherwise fetched by email
    """
    # Resolve user instance if not provided
    user = user or User.objects.get(email=email)

    otp_code = generate_otp()

    # Persist OTP
    OneTimePassword.objects.create(user=user, code=otp_code)

    # Build email
    subject = "One-Time Passcode for Email Verification"
    current_site = "Cafe Queue"
    email_body = (
        f"Dear {user.name},\n\n"
        f"Thank you for signing up on {current_site}. "
        f"To verify your email, please use the OTP (One-Time Password) below:\n\n"
        f"   Your OTP: {otp_code}\n\n"
        f"Please do not share it with anyone for security reasons.\n"
        f"If you did not request this OTP, please ignore this email.\n\n"
        f"Best regards,\n"
        f"{current_site} Team"
    )

    from_email = settings.EMAIL_HOST_USER
    message = EmailMessage(subject=subject, body=email_body, from_email=from_email, to=[user.email])
    # In dev, fail silently to avoid raising if SMTP is misconfigured
    message.send(fail_silently=True)