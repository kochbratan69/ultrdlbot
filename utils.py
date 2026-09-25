import os
import re
import random
import secrets
from urllib.parse import urlparse
import config

def load_plus_ids() -> int:
    """Загружает Telegram ID из файла plusids в память ✨"""
    if not os.path.exists(config.PLUS_FILE):
        with open(config.PLUS_FILE, "w", encoding="utf-8") as f:
            pass
        config.PLUS_USERS = set()
        return 0

    with open(config.PLUS_FILE, "r", encoding="utf-8") as f:
        ids = set()
        for line in f:
            line_str = line.strip()
            if line_str.isdigit():
                ids.add(int(line_str))
        config.PLUS_USERS = ids
        return len(config.PLUS_USERS)

def get_random_filename() -> str:
    random_hash = secrets.token_hex(8)
    return f"{config.BOT_USERNAME}_{random_hash}"

def is_supported_url(text: str) -> bool:
    urls = re.findall(r'https?://[^\s]+', text)
    if not urls:
        return False
    for url in urls:
        domain = urlparse(url).netloc.lower()
        if any(sup in domain for sup in config.SUPPORTED_DOMAINS):
            return True
    return False

def get_first_url(text: str) -> str:
    urls = re.findall(r'https?://[^\s]+', text)
    return urls[0] if urls else ""