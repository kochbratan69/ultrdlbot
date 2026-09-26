import re
import os

XML_PATH = "messages.xml"
I18N_PATH = "i18n.py"

def sync_xml_to_i18n():
    if not os.path.exists(XML_PATH):
        print(f"❌ Файл {XML_PATH} не найден!")
        return

    if not os.path.exists(I18N_PATH):
        print(f"❌ Файл {I18N_PATH} не найден!")
        return

    with open(XML_PATH, "r", encoding="utf-8") as f:
        xml_content = f.read().strip()

    with open(I18N_PATH, "r", encoding="utf-8") as f:
        i18n_code = f.read()

    # Заменяем содержимое DEFAULT_XML_CONTENT = """..."""
    pattern = r'DEFAULT_XML_CONTENT\s*=\s*""".*?"""'
    replacement = f'DEFAULT_XML_CONTENT = """{xml_content}"""'

    new_i18n_code = re.sub(pattern, replacement, i18n_code, flags=re.DOTALL)

    with open(I18N_PATH, "w", encoding="utf-8") as f:
        f.write(new_i18n_code)

    print(f"✨ Содержимое {XML_PATH} успешно вшито в {I18N_PATH}!")

if __name__ == "__main__":
    sync_xml_to_i18n()