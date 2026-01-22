# app/celery_utils.py
from celery import Celery

celery_app = Celery(__name__)