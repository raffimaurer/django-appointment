from .settings import *
EMAIL_BACKEND = 'django.core.mail.backends.locmem.EmailBackend'
USE_DJANGO_Q_FOR_EMAILS = False
PASSWORD_HASHERS = ['django.contrib.auth.hashers.MD5PasswordHasher']
