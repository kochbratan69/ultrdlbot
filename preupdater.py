import os
import sys
import platform
import urllib.request
import zipfile
import logging

FFMPEG_ZIP_URL = "https://github.com/BtbN/FFmpeg-Builds/releases/download/latest/ffmpeg-master-latest-win64-gpl.zip"

def ensure_ffmpeg(base_dir: str):
    # На Linux используем системный ffmpeg
    if platform.system() != "Windows":
        print("🐧 Linux обнаружен: используется системный ffmpeg из ОС")
        return

    # На Windows скачиваем ffmpeg.exe, если его нет
    ffmpeg_path = os.path.join(base_dir, "ffmpeg.exe")
    if os.path.exists(ffmpeg_path):
        print("✅ ffmpeg.exe на месте!")
        return

    print("📦 ffmpeg.exe не найден! Скачиваем архив...")
    zip_path = os.path.join(base_dir, "ffmpeg_temp.zip")
    req = urllib.request.Request(
        FFMPEG_ZIP_URL, 
        headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}
    )
    
    try:
        with urllib.request.urlopen(req) as resp, open(zip_path, "wb") as out_file:
            out_file.write(resp.read())
        
        with zipfile.ZipFile(zip_path, 'r') as zip_ref:
            for member in zip_ref.namelist():
                if member.endswith("ffmpeg.exe"):
                    with zip_ref.open(member) as source, open(ffmpeg_path, "wb") as target:
                        target.write(source.read())
                    break
        
        print("✨ ffmpeg.exe успешно извлечён!")
    except Exception as e:
        logging.error(f"Не удалось скачать ffmpeg: {e}")
    finally:
        if os.path.exists(zip_path):
            os.remove(zip_path)

def check_and_update_binaries(base_dir: str = "."):
    """Основная функция обновления, которую вызывает worker.py"""
    ensure_ffmpeg(base_dir)