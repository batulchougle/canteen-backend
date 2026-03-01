from django.apps import AppConfig


class UsersConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'users'

    def ready(self):
        try:
            import os
            import firebase_admin
            from firebase_admin import credentials, initialize_app
            if not getattr(firebase_admin, "_apps", None):
                sa_path = os.environ.get("GOOGLE_APPLICATION_CREDENTIALS")
                if sa_path:
                    try:
                        cred = credentials.Certificate(sa_path)
                        bucket = os.environ.get("FIREBASE_STORAGE_BUCKET")
                        if bucket:
                            initialize_app(cred, {"storageBucket": bucket})
                        else:
                            initialize_app(cred)
                    except Exception:
                        pass
        except Exception:
            pass
