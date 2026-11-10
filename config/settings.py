"""Local and container configuration; credentials come from .env/environment."""
from pathlib import Path
from decouple import AutoConfig, Csv
from django.core.exceptions import ImproperlyConfigured

BASE_DIR = Path(__file__).resolve().parent.parent
config = AutoConfig(search_path=BASE_DIR)
DEBUG = config("DEBUG", default=True, cast=bool)
SECRET_KEY = config("SECRET_KEY", default="")
if not SECRET_KEY:
    raise ImproperlyConfigured("Thiếu SECRET_KEY. Tạo .env theo .env.example trước khi chạy.")
ALLOWED_HOSTS = config("ALLOWED_HOSTS", default="localhost,127.0.0.1", cast=Csv())
INSTALLED_APPS = [
    "django.contrib.admin", "django.contrib.auth", "django.contrib.contenttypes",
    "django.contrib.sessions", "django.contrib.messages", "django.contrib.staticfiles",
    "apps.accounts.apps.AccountsConfig", "apps.dormitory.apps.DormitoryConfig",
    "apps.core.apps.CoreConfig",
]
MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "whitenoise.middleware.WhiteNoiseMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "apps.accounts.middleware.AccountSessionMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]
ROOT_URLCONF = "config.urls"
TEMPLATES = [{
    "BACKEND": "django.template.backends.django.DjangoTemplates",
    "DIRS": [BASE_DIR / "templates"], "APP_DIRS": True,
    "OPTIONS": {"context_processors": [
        "django.template.context_processors.request",
        "django.contrib.auth.context_processors.auth",
        "django.contrib.messages.context_processors.messages",
        "apps.core.context_processors.navigation",
    ]},
}]
WSGI_APPLICATION = "config.wsgi.application"
ASGI_APPLICATION = "config.asgi.application"
DATABASES = {"default": {
    "ENGINE": "django.db.backends.mysql",
    "NAME": config("DB_NAME", default="dormitory_management"),
    "USER": config("DB_USER", default="root"),
    "PASSWORD": config("DB_PASSWORD", default=""),
    "HOST": config("DB_HOST", default="127.0.0.1"),
    "PORT": config("DB_PORT", default="3306"),
    "CONN_MAX_AGE": 60, "CONN_HEALTH_CHECKS": True,
    "OPTIONS": {
        "charset": "utf8mb4", "connect_timeout": 10, "isolation_level": "read committed",
        "init_command": "SET time_zone = '+07:00', sql_mode = 'STRICT_TRANS_TABLES,NO_ZERO_IN_DATE,NO_ZERO_DATE,ERROR_FOR_DIVISION_BY_ZERO,NO_ENGINE_SUBSTITUTION'",
    },
}}
if config("DMS_MYSQL_DEFAULTS_FILE", default=""):
    DATABASES["default"]["OPTIONS"]["read_default_file"] = config("DMS_MYSQL_DEFAULTS_FILE")
database_ssl_ca = config("DB_SSL_CA", default="")
database_ssl_mode = config("DB_SSL_MODE", default="")
if database_ssl_ca:
    DATABASES["default"]["OPTIONS"]["ssl"] = {"ca": database_ssl_ca}
    DATABASES["default"]["OPTIONS"]["ssl_mode"] = database_ssl_mode or "VERIFY_IDENTITY"
elif database_ssl_mode:
    DATABASES["default"]["OPTIONS"]["ssl_mode"] = database_ssl_mode
AUTH_USER_MODEL = "accounts.Account"
AUTHENTICATION_BACKENDS = ["apps.accounts.backends.AccountBackend"]
AUTH_PASSWORD_VALIDATORS = [{"NAME": "apps.accounts.validators.DMSPasswordValidator"}]
LOGIN_URL = "accounts:login"
LOGIN_REDIRECT_URL = "dashboard"
LOGOUT_REDIRECT_URL = "accounts:login"
LANGUAGE_CODE = "vi"
TIME_ZONE = "Asia/Ho_Chi_Minh"
USE_I18N = True
# Original SQL DATETIME columns store Vietnamese local time.
USE_TZ = False
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"
STATIC_URL = "/static/"
STATICFILES_DIRS = [BASE_DIR / "static"]
STATIC_ROOT = BASE_DIR / "staticfiles"
STORAGES = {
    "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
    "staticfiles": {"BACKEND": "whitenoise.storage.CompressedManifestStaticFilesStorage"},
}
WHITENOISE_USE_FINDERS = DEBUG
SESSION_ENGINE = "django.contrib.sessions.backends.db"
SESSION_COOKIE_HTTPONLY = True
SESSION_COOKIE_SAMESITE = "Lax"
SESSION_COOKIE_AGE = 1800
SESSION_EXPIRE_AT_BROWSER_CLOSE = True
SESSION_COOKIE_SECURE = config("SESSION_COOKIE_SECURE", default=not DEBUG, cast=bool)
CSRF_COOKIE_SECURE = config("CSRF_COOKIE_SECURE", default=not DEBUG, cast=bool)
CSRF_TRUSTED_ORIGINS = config("CSRF_TRUSTED_ORIGINS", default="", cast=Csv())
SECURE_SSL_REDIRECT = config("SECURE_SSL_REDIRECT", default=not DEBUG, cast=bool)
SECURE_REDIRECT_EXEMPT = [r"^api/v1/health/?$"]
SECURE_HSTS_SECONDS = config("SECURE_HSTS_SECONDS", default=0 if DEBUG else 31536000, cast=int)
SECURE_HSTS_INCLUDE_SUBDOMAINS = config(
    "SECURE_HSTS_INCLUDE_SUBDOMAINS", default=False, cast=bool
)
SECURE_HSTS_PRELOAD = config("SECURE_HSTS_PRELOAD", default=False, cast=bool)
SECURE_CONTENT_TYPE_NOSNIFF = True
X_FRAME_OPTIONS = "DENY"
if config("TRUST_PROXY", default=False, cast=bool):
    SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
ALLOW_DEMO_SETUP = config("ALLOW_DEMO_SETUP", default=False, cast=bool)
CSRF_FAILURE_VIEW = "apps.core.views.csrf_failure"
