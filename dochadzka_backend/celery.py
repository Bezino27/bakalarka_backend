# dochadzka_backend/celery.py
from __future__ import absolute_import, unicode_literals
import os
from celery import Celery
from celery.schedules import crontab

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'dochadzka_backend.settings')

app = Celery('dochadzka_backend')

app.config_from_object('django.conf:settings', namespace='CELERY')

app.autodiscover_tasks()

app.conf.beat_schedule = {
    "process-training-schedules-every-5-min": {
        "task": "dochadzka_app.tasks.process_training_schedules",
        "schedule": crontab(minute="*/5"),
    },
}

app.conf.beat_schedule = {
    "process-training-schedules-every-5-min": {
        "task": "dochadzka_app.tasks.process_training_schedules",
        "schedule": crontab(minute="*/5"),
    },
    "process-training-vote-reminders-every-5-min": {
        "task": "dochadzka_app.tasks.process_training_vote_reminders",
        "schedule": crontab(minute="*/5"),
    },
}