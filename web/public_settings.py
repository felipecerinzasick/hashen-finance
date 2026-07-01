from .settings import *
import os


DEBUG = False
PUBLIC_SITE_ONLY = os.environ.get('PUBLIC_SITE_ONLY', 'False') == 'True'

STATIC_URL = '/static/'
STATICFILES_STORAGE = 'whitenoise.storage.CompressedStaticFilesStorage'
DEFAULT_FILE_STORAGE = 'django.core.files.storage.FileSystemStorage'

EMAIL_BACKEND = 'django.core.mail.backends.console.EmailBackend'
SITE_ID = 1
