import hashlib
import os
import sys
import json
import urllib.request
import platform
import stat
import subprocess

# 🛠 Укажи имя и владельца репозитория
GITHUB_OWNER = "kochbratan69"
GITHUB_REPO = "ultrdlbot"

def get_file_sha256(file_path: str) -> str:
    """Вычисляет SHA-256 хэш локального файла. Если файла нет, возвращает пустую строку."""
    if not os.path.exists(file_path):
        return ""
    sha256_hash = hashlib.sha256()
    with open(file_path, "rb") as f:
        for byte_block in iter(lambda: f.read(4096), b""):
            sha256_hash.update(byte_block)
    return sha256_hash.hexdigest().strip().lower()


def fetch_text(url: str) -> str:
    """Загружает текстовое содержимое (например, .sha256) по URL."""
    req = urllib.request.Request(url, headers={"User-Agent": "Python-Self-Updater"})
    with urllib.request.urlopen(req) as resp:
        return resp.read().decode("utf-8").strip().lower()


def check_and_update_all() -> bool:
    """
    Проверяет и обновляет ВСЕ бинарники (и bot, и worker) в рабочей директории.
    """
    system_os = platform.system().lower()
    if system_os not in ["linux", "windows"]:
        print(f"[Updater] ОС {system_os} не поддерживается.")
        return False

    ext = ".exe" if system_os == "windows" else ""

    # Проверка: запущен ли скомпилированный PyInstaller бинарник
    if not getattr(sys, 'frozen', False):
        print("[Updater] Запущен сырой .py скрипт. Автообновление пропущено.")
        return False

    current_exe_path = os.path.abspath(sys.executable)
    exe_dir = os.path.dirname(current_exe_path)

    # 1. Запрашиваем информацию о последнем релизе из GitHub
    url = f"https://api.github.com/repos/{GITHUB_OWNER}/{GITHUB_REPO}/releases/latest"
    req = urllib.request.Request(url, headers={"User-Agent": "Python-Self-Updater"})

    try:
        with urllib.request.urlopen(req) as resp:
            data = json.loads(resp.read().decode("utf-8"))
    except Exception as e:
        print(f"[Updater] Ошибка обращения к GitHub API: {e}")
        return False

    assets = {asset.get("name"): asset.get("browser_download_url") for asset in data.get("assets", [])}

    # Список всех бинарников, которые нужно обновить
    apps = ["dlbot", "dlworker"]
    restart_self = False
    any_updated = False

    for app_name in apps:
        expected_bin_name = f"{app_name}-{system_os}{ext}"
        expected_hash_name = f"{expected_bin_name}.sha256"

        bin_url = assets.get(expected_bin_name)
        hash_url = assets.get(expected_hash_name)

        if not bin_url or not hash_url:
            print(f"[Updater] Файлы {expected_bin_name} / {expected_hash_name} не найдены в релизе.")
            continue

        # Путь к проверяемому файлу на диске
        is_current_app = (os.path.basename(current_exe_path).lower() == expected_bin_name.lower())
        local_app_path = current_exe_path if is_current_app else os.path.join(exe_dir, expected_bin_name)

        local_hash = get_file_sha256(local_app_path)

        try:
            remote_hash = fetch_text(hash_url)
        except Exception as e:
            print(f"[Updater] Ошибка скачивания хэша для {app_name}: {e}")
            continue

        # Сравниваем хэш
        if local_hash == remote_hash and local_hash != "":
            print(f"✅ [Updater] {app_name} уже актуальной версии.")
            continue

        print(f"🚀 [Updater] Найдено обновление для {app_name}...")

        tmp_path = os.path.join(exe_dir, f"tmp_{app_name}{ext}")

        try:
            # Скачиваем бинарник
            req_dl = urllib.request.Request(bin_url, headers={"User-Agent": "Python-Self-Updater"})
            with urllib.request.urlopen(req_dl) as response, open(tmp_path, "wb") as out_file:
                out_file.write(response.read())

            # Сверяем хэш скачанного файла с удалённым
            downloaded_hash = get_file_sha256(tmp_path)
            if downloaded_hash != remote_hash:
                print(f"💥 [Updater] Ошибка целостности файла {app_name}: хэш не совпал! Пропуск.")
                if os.path.exists(tmp_path):
                    os.remove(tmp_path)
                continue

            # Выставляем права на исполнение для Linux
            if system_os == "linux":
                st = os.stat(tmp_path)
                os.chmod(tmp_path, st.st_mode | stat.S_IEXEC)

            # Заменяем старый файл на новый
            if os.path.exists(local_app_path):
                old_path = local_app_path + ".old"
                if os.path.exists(old_path):
                    os.remove(old_path)
                os.rename(local_app_path, old_path)

            os.rename(tmp_path, local_app_path)
            print(f"✅ [Updater] Файл {app_name} успешно обновлён!")
            any_updated = True

            # Если мы обновили запущенный прямо сейчас процесс — ставим флаг на перезапуск
            if is_current_app:
                restart_self = True

        except Exception as e:
            print(f"💥 [Updater] Ошибка при обновлении {app_name}: {e}")
            if os.path.exists(tmp_path):
                os.remove(tmp_path)

    # Завершение работы / Перезапуск
    if restart_self:
        print("🔄 [Updater] Текущий процесс был обновлён. Выполняется перезапуск...")
        subprocess.Popen([current_exe_path] + sys.argv[1:])
        sys.exit(0)

    return any_updated


if __name__ == "__main__":
    # Просто вызываем функцию при старте бота или воркера
    check_and_update_all()