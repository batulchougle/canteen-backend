#!/usr/bin/env bash
set -o errexit

pip install -r requirements.txt
python manage.py collectstatic --no-input
python manage.py migrate

echo "from users.models import User; User.objects.filter(is_superuser=True).exists() or User.objects.create_superuser('Admin', 'admin', 'admin123', role='admin', is_email_verified=True)" | python manage.py shell
