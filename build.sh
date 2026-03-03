#!/usr/bin/env bash
set -o errexit

pip install -r requirements.txt
python manage.py collectstatic --no-input
python manage.py migrate

echo "from django.contrib.auth import get_user_model; U = get_user_model(); U.objects.filter(is_superuser=True).exists() or U.objects.create_superuser('Admin', 'admin', 'admin123')" | python manage.py shell
