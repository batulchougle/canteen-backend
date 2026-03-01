#!/usr/bin/env bash
set -o errexit

pip install -r requirements.txt
python manage.py collectstatic --no-input
python manage.py migrate
```

**`Procfile`** (create this in root):
```
web: gunicorn canteen_system.wsgi:application
```

Make sure `gunicorn` and `whitenoise` are in your `requirements.txt`:
```
gunicorn
whitenoise
