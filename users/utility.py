import random
import threading
from typing import Optional
from django.conf import settings
import resend
from .models import User, OneTimePassword

def generate_otp(length: int = 6) -> str:
    return ''.join(str(random.randint(0, 9)) for _ in range(length))

def _send_email(name, to_email, otp_code):
    try:
        resend.api_key = settings.RESEND_API_KEY
        resend.Emails.send({
            "from": "onboarding@resend.dev",
            "to": to_email,
            "subject": "One-Time Passcode for Email Verification",
            "text": f"Dear {name},\n\nYour OTP is: {otp_code}\n\nDo not share this with anyone."
        })
        print(f"EMAIL SENT to {to_email}")
    except Exception as e:
        print(f"EMAIL ERROR: {e}")

def send_code_to_user(email: str, user: Optional[User] = None) -> None:
    user = user or User.objects.get(email=email)
    otp_code = generate_otp()
    OneTimePassword.objects.create(user=user, code=otp_code)
    thread = threading.Thread(target=_send_email, args=(user.name, user.email, otp_code))
    thread.daemon = True
    thread.start()
