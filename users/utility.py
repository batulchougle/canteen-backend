import random
import threading
import logging
from typing import Optional
from django.core.mail import EmailMessage
from django.conf import settings
from .models import User, OneTimePassword

logger = logging.getLogger(__name__)

def generate_otp(length: int = 6) -> str:
    return ''.join(str(random.randint(0, 9)) for _ in range(length))

def _send_email(name, to_email, otp_code):
    try:
        subject = "One-Time Passcode for Email Verification"
        body = (
            f"Dear {name},\n\n"
            f"Your OTP is: {otp_code}\n\n"
            f"Do not share this with anyone.\n\n"
            f"Best regards,\nCafe Queue Team"
        )
        message = EmailMessage(subject=subject, body=body, from_email=settings.DEFAULT_FROM_EMAIL, to=[to_email])
        message.send(fail_silently=False)
        logger.warning(f"EMAIL SENT to {to_email}")
    except Exception as e:
        logger.warning(f"EMAIL ERROR: {type(e).__name__}: {e}")

def send_code_to_user(email: str, user: Optional[User] = None) -> None:
    user = user or User.objects.get(email=email)
    otp_code = generate_otp()
    OneTimePassword.objects.create(user=user, code=otp_code)
    thread = threading.Thread(target=_send_email, args=(user.name, user.email, otp_code))
    thread.daemon = True
    thread.start()
