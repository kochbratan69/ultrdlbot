import os
import sys
import secrets
from dotenv import load_dotenv

load_dotenv()

DEBUG = False
DISABLE_COOKIES = False

# 🔒 SSL / HTTPS Настройки через .env
ENABLE_SSL = os.getenv("ENABLE_SSL", "false").lower() in ("true", "1", "yes")

SSL_CERT_FILE = os.getenv("SSL_CERT_FILE", os.path.join(os.path.dirname(os.path.abspath(__file__)), "cert.pem"))
SSL_KEY_FILE = os.getenv("SSL_KEY_FILE", os.path.join(os.path.dirname(os.path.abspath(__file__)), "key.pem"))

# По умолчанию порт 443 для SSL и 8000 без SSL
DEFAULT_PORT = 443 if ENABLE_SSL else 8000
WORKER_PORT = int(os.getenv("WORKER_PORT", DEFAULT_PORT))

# Настройки подключения бота к воркеру
DEFAULT_WORKER_URL = f"https://127.0.0.1:{WORKER_PORT}" if ENABLE_SSL else f"http://127.0.0.1:{WORKER_PORT}"
WORKER_URL = os.getenv("WORKER_URL", DEFAULT_WORKER_URL)

DOMAIN = os.getenv("DOMAIN", "https://ultra.qd.je")

# Настройки бота
BOT_TOKEN = os.getenv("BOT_TOKEN")
BOT_USERNAME = os.getenv("BOT_USERNAME", "ultrdlbot")

# Пути
BASE_DIR = os.path.dirname(os.path.abspath(sys.executable if hasattr(sys, '_MEIPASS') else __file__))
DOWNLOAD_DIR = os.path.join(BASE_DIR, "DOWNLOADS")
SHARE_DIR = os.path.join(BASE_DIR, "SHARES")
COOKIE_FILE = os.path.join(BASE_DIR, "cookiefile.txt")

os.makedirs(DOWNLOAD_DIR, exist_ok=True)
os.makedirs(SHARE_DIR, exist_ok=True)

# 🔑 Bearer-токен авторизации
AUTH_TOKEN_FILE = os.path.join(BASE_DIR, ".authtoken")
if os.path.exists(AUTH_TOKEN_FILE):
    with open(AUTH_TOKEN_FILE, "r", encoding="utf-8") as f:
        AUTH_TOKEN = f.read().strip()
else:
    AUTH_TOKEN = secrets.token_hex(32)
    with open(AUTH_TOKEN_FILE, "w", encoding="utf-8") as f:
        f.write(AUTH_TOKEN)

# Плюс-пользователи и кэш
PLUS_FILE = os.path.join(BASE_DIR, "plusids")
PLUS_USERS: set[int] = set()
URL_CACHE: dict[str, dict | str] = {}

SUPPORTED_DOMAINS = [
    "youtube.com", "youtu.be", "soundcloud.com", "spotify.com",
    "tiktok.com", "tiktokv.com", "instagram.com", "vk.com", 
    "x.com", "twitter.com", "pinterest.com", "pin.it"
]