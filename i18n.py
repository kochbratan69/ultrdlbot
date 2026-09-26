import os
import xml.etree.ElementTree as ET
from string import Template
import config

# 📦 Дефолтный XML, вшитый прямо в код (попадёт внутрь бинарника)
DEFAULT_XML_CONTENT = """"""

MESSAGES_CACHE: dict[str, dict[str, str]] = {}
DEFAULT_LANG = "ru"

def init_i18n(xml_path: str = None):
    """
    Проверяет наличие файла messages.xml на диске.
    Если файла нет, извлекает встроенный XML прямо в папку с ботом,
    чтобы пользователь мог отредактировать все текста под себя! :3
    """
    if xml_path is None:
        xml_path = getattr(config, "MESSAGES_FILE", os.path.join(config.BASE_DIR, "messages.xml"))

    if not os.path.exists(xml_path):
        try:
            with open(xml_path, "w", encoding="utf-8") as f:
                f.write(DEFAULT_XML_CONTENT.strip())
            print(f"✨ Распакован файл {os.path.basename(xml_path)} для кастомизации сообщений!")
        except Exception as e:
            print(f"Ошибка при создании messages.xml: {e}")

    load_messages(xml_path)

def load_messages(xml_path: str = None):
    global MESSAGES_CACHE, DEFAULT_LANG
    if xml_path is None:
        xml_path = getattr(config, "MESSAGES_FILE", os.path.join(config.BASE_DIR, "messages.xml"))

    if not os.path.exists(xml_path):
        return

    try:
        tree = ET.parse(xml_path)
        root = tree.getroot()
        DEFAULT_LANG = root.attrib.get("default_lang", "ru")

        cache = {}
        for lang_node in root:
            lang = lang_node.tag
            cache[lang] = {}
            for msg_node in lang_node:
                cache[lang][msg_node.tag] = msg_node.text or ""

        MESSAGES_CACHE = cache
    except Exception as e:
        print(f"Ошибка при считывании messages.xml: {e}")

def get_msg(key: str, lang: str = None, **kwargs) -> str:
    """Получение сообщения по ключу с поддержкой плейсхолдеров ($key,$share_url и т.д.)"""
    if not MESSAGES_CACHE:
        init_i18n()

    if not lang or lang not in MESSAGES_CACHE:
        lang = DEFAULT_LANG

    msg_text = MESSAGES_CACHE.get(lang, {}).get(key)
    if msg_text is None:
        msg_text = MESSAGES_CACHE.get(DEFAULT_LANG, {}).get(key, f"[{key}]")

    if kwargs:
        template = Template(msg_text)
        safe_kwargs = {k: str(v) for k, v in kwargs.items()}
        return template.safe_substitute(safe_kwargs)

    return msg_text