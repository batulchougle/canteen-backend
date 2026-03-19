import random
import threading
from typing import Optional
from django.conf import settings
from django.core.mail import EmailMessage
from .models import User, OneTimePassword

def generate_otp(length: int = 6) -> str:
    return ''.join(str(random.randint(0, 9)) for _ in range(length))

def _send_email(subject, body, from_email, to_email):
    try:
        message = EmailMessage(subject=subject, body=body, from_email=from_email, to=[to_email])
        message.send(fail_silently=False)
    except Exception as e:
        print(f"EMAIL ERROR: {e}")

def send_code_to_user(email: str, user: Optional[User] = None) -> None:
    user = user or User.objects.get(email=email)
    otp_code = generate_otp()
    OneTimePassword.objects.create(user=user, code=otp_code)
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
    from_email = settings.DEFAULT_FROM_EMAIL
    # Send in background thread so signup response returns immediately
    thread = threading.Thread(target=_send_email, args=(subject, email_body, from_email, user.email))
    thread.daemon = True
    thread.start()
