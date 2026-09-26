import os
import platform
import re
import glob
import json
import secrets
import asyncio
import logging
import sys
import traceback
import urllib.request

import yt_dlp
import gallery_dl.config
import gallery_dl.job
import instaloader
from PIL import Image

# Импорты для работы с M4A и MP3
from mutagen.mp4 import MP4, MP4Cover
from mutagen.mp3 import MP3
from mutagen.id3 import ID3, APIC, TIT2, TPE1, TALB, COMM, ID3NoHeaderError

import config
from services import download_spotify_cover

class YTDLPLogger:
    def debug(self, msg):
        logging.debug(f"[yt-dlp] {msg}")

    def info(self, msg):
        logging.info(f"[yt-dlp] {msg}")

    def warning(self, msg):
        logging.warning(f"[yt-dlp] {msg}")

    def error(self, msg):
        logging.error(f"[yt-dlp] {msg}")


def _prepare_thumbnail(task_dir: str) -> str | None:
    """Ищет обложку локально или скачивает её по URL из JSON, делая квадратный JPG 320x320 ✨"""
    images = []

    # 1. Проверяем, скачалась ли обложка Spotify
    sp_cover = os.path.join(task_dir, "spotify.jpg")
    if os.path.exists(sp_cover):
        images.append(sp_cover)

    # 2. Ищем картинки, скачанные локально через yt-dlp
    for ext in ("*.jpg", "*.jpeg", "*.png", "*.webp"):
        images.extend(glob.glob(os.path.join(task_dir, ext)))
    
    # 3. Если локального файла нет, парсим .info.json и качаем по прямой ссылке
    if not images:
        info_files = glob.glob(os.path.join(task_dir, "*.info.json"))
        if info_files:
            try:
                with open(info_files[0], "r", encoding="utf-8") as f:
                    info = json.load(f)
                    
                thumb_url = info.get("thumbnail")
                
                # Ищем обложку наивысшего качества из массива thumbnails (например, 'original')
                if info.get("thumbnails") and isinstance(info["thumbnails"], list):
                    sorted_thumbs = sorted(
                        info["thumbnails"], 
                        key=lambda x: (x.get("preference", 0) or 0, x.get("width", 0) or 0)
                    )
                    if sorted_thumbs:
                        thumb_url = sorted_thumbs[-1].get("url") or thumb_url

                if thumb_url:
                    downloaded_img = os.path.join(task_dir, "downloaded_cover.tmp")
                    req = urllib.request.Request(
                        thumb_url, 
                        headers={'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)'}
                    )
                    with urllib.request.urlopen(req) as resp, open(downloaded_img, 'wb') as out:
                        out.write(resp.read())
                    images.append(downloaded_img)
            except Exception as e:
                logging.error(f"Ошибка скачивания обложки по URL из json: {e}")

    if not images:
        return None
        
    thumb_src = images[0]
    thumb_dst = os.path.join(task_dir, "thumb_final.jpg")
    
    # 4. Преобразуем в квадратный RGB JPEG
    try:
        with Image.open(thumb_src) as img:
            img = img.convert("RGB")
            w, h = img.size
            min_side = min(w, h)
            left = (w - min_side) // 2
            top = (h - min_side) // 2
            right = left + min_side
            bottom = top + min_side
            
            img = img.crop((left, top, right, bottom))
            img = img.resize((320, 320), Image.Resampling.LANCZOS)
            img.save(thumb_dst, "JPEG", quality=90)
        return thumb_dst
    except Exception as e:
        logging.error(f"Ошибка при обработке обложки Pillow: {e}")
        return thumb_src


def _update_audio_metadata(
    audio_path: str, 
    title: str = None, # type: ignore
    artist: str = None, # type: ignore
    album: str = None, # type: ignore
    comment: str = None, # type: ignore
    image_path: str = None # type: ignore
):
    """Универсально вшивает теги и обложку в .m4a и .mp3 файлы ✨"""
    ext = os.path.splitext(audio_path)[1].lower()

    # --- Поддержка M4A / MP4 ---
    if ext in [".m4a", ".mp4"]:
        try:
            audio = MP4(audio_path)
            if title: audio["\xa9nam"] = [title]
            if artist: audio["\xa9ART"] = [artist]
            if album: audio["\xa9alb"] = [album]
            if comment: audio["\xa9cmt"] = [comment]

            if image_path and os.path.exists(image_path):
                with open(image_path, "rb") as f:
                    audio["covr"] = [MP4Cover(f.read(), imageformat=MP4Cover.FORMAT_JPEG)]
                    
            audio.save()
        except Exception as e:
            logging.error(f"Ошибка записи M4A тегов: {e}")

    # --- Поддержка MP3 ---
    elif ext == ".mp3":
        try:
            try:
                audio = MP3(audio_path, ID3=ID3)
            except ID3NoHeaderError:
                audio = MP3(audio_path)
                audio.add_tags()

            if title: audio.tags.add(TIT2(encoding=3, text=title)) # type: ignore
            if artist: audio.tags.add(TPE1(encoding=3, text=artist)) # type: ignore
            if album: audio.tags.add(TALB(encoding=3, text=album)) # type: ignore 
            if comment: audio.tags.add(COMM(encoding=3, lang='eng', desc='Comment', text=comment)) # type: ignore

            if image_path and os.path.exists(image_path):
                with open(image_path, "rb") as f:
                    audio.tags.add( # type: ignore
                        APIC(
                            encoding=3,
                            mime='image/jpeg',
                            type=3, # Front Cover
                            desc='Cover',
                            data=f.read()
                        )
                    )
            audio.save()
            logging.info(f"✅ [MP3] Метаданные и обложка записаны в {os.path.basename(audio_path)}")
        except Exception as e:
            logging.error(f"Ошибка записи MP3 тегов: {e}")


def _run_instaloader(url: str, target_dir: str, prefix: str):
    L = instaloader.Instaloader(
        dirname_pattern=target_dir,
        filename_pattern=f"{prefix}_{{shortcode}}",
        download_pictures=True,
        download_videos=True,
        download_video_thumbnails=False,
        download_geotags=False,
        download_comments=False,
        save_metadata=False,
        compress_json=False
    )
    
    match = re.search(r'/(?:p|reel|reels|tv)/([A-Za-z0-9_-]+)', url)
    if not match:
        raise ValueError("Не удалось найти shortcode поста в ссылке Instagram")
    
    shortcode = match.group(1)
    post = instaloader.Post.from_shortcode(L.context, shortcode)
    L.download_post(post, target=target_dir)


def _run_gallery_dl(url: str, target_dir: str, filename_template: str) -> int:
    gallery_dl.config.clear()
    gallery_dl.config.load()
    gallery_dl.config.set(("extractor",), "base-directory", target_dir)
    gallery_dl.config.set(("extractor",), "directory", ["."])
    gallery_dl.config.set(("extractor",), "filename", filename_template)
    
    job = gallery_dl.job.DownloadJob(url)
    return job.run()


def _run_ytdlp(ydl_opts: dict, target_url: str):
    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl: # type: ignore
            ydl.download([target_url])
    except Exception as e:
        logging.error(f"💥 Ошибка внутри yt-dlp: {e}")
        logging.error(traceback.format_exc())
        raise e


async def execute_download_task(cache_id: str, mode: str, quality: int = 0, payload: dict = None ) -> dict: # type: ignore
    payload = payload or {}
    url = payload.get("url", "")
    sp_title = payload.get("sp_title")
    sp_artist = payload.get("sp_artist")
    sp_cover_url = payload.get("sp_cover_url")
    yt_url = payload.get("yt_url")
    query = payload.get("query", url)

    task_dir = os.path.join(config.DOWNLOAD_DIR, cache_id)
    os.makedirs(task_dir, exist_ok=True)

    random_hash = secrets.token_hex(8)

    # 1. INSTAGRAM
    if mode == "instagram":
        prefix = f"{config.BOT_USERNAME}_{random_hash}"
        try:
            await asyncio.to_thread(_run_instaloader, url, task_dir, prefix)
        except Exception as e:
            return {"success": False, "error": f"Instaloader error: {e}"}

        media_files = sorted([
            os.path.join(task_dir, f) for f in os.listdir(task_dir)
            if f.lower().endswith((".jpg", ".jpeg", ".png", ".webp", ".mp4", ".mov", ".mkv"))
        ])
        if not media_files:
            return {"success": False, "error": "Не удалось найти медиафайлы в Instagram"}
        return {"success": True, "type": "gallery", "files": media_files}

    # 2. GALLERY-DL
    if mode == "gallery_dl":
        filename_fmt = f"{config.BOT_USERNAME}_{random_hash}_{{num}}.{{extension}}"
        try:
            res_code = await asyncio.to_thread(_run_gallery_dl, url, task_dir, filename_fmt)
            if res_code != 0:
                return {"success": False, "error": "gallery-dl не смог выкачать файлы"}
        except Exception as e:
            return {"success": False, "error": str(e)}

        media_files = sorted([
            os.path.join(task_dir, f) for f in os.listdir(task_dir)
            if f.lower().endswith((".jpg", ".jpeg", ".png", ".webp", ".mp4", ".mov", ".mkv"))
        ])
        if not media_files:
            return {"success": False, "error": "Медиафайлы не найдены"}
        return {"success": True, "type": "gallery", "files": media_files}

    # 3. Spotify Cover
    if mode in ["audio_sp_yt", "audio_sp_sc"] and sp_cover_url:
        sp_cover_path = os.path.join(task_dir, "spotify.jpg")
        await download_spotify_cover(sp_cover_url, sp_cover_path)

    # 4. YT-DLP
    out_template = os.path.join(task_dir, f"{config.BOT_USERNAME}_{random_hash}.%(ext)s")

    is_debug = getattr(config, "DEBUG", False) or "--debug" in sys.argv
    disable_cookies = getattr(config, "DISABLE_COOKIES", False) or "--disable-cookies" in sys.argv

    ydl_opts = {
        'outtmpl': out_template,
        'socket_timeout': 10,
        'concurrent_fragment_downloads': 1,
        'js_runtimes': {'node': {}},
        'quiet': not is_debug,
        'no_warnings': not is_debug,
        'verbose': is_debug,
        'logger': YTDLPLogger() if is_debug else None,
        'force_ipv6': True,
        'extractor_args': {
            'youtube': {
                'player_client': ['android_vr', 'visionos', 'ios', 'mweb'],
            }
        },
    }

    if platform.system() == "Windows":
        ydl_opts['ffmpeg_location'] = os.getcwd()

    if os.path.exists(config.COOKIE_FILE) and not disable_cookies:
        ydl_opts['cookiefile'] = config.COOKIE_FILE

    if mode in ["audio_sp_yt", "audio_yt"]:
        target = (yt_url if mode == "audio_sp_yt" and yt_url else f"ytsearch1:{query} Audio") if mode == "audio_sp_yt" else url
        ydl_opts.update({
            'format': 'ba/b',
            'format_sort': ['abr'],
            'writethumbnails': True,
            'writeinfojson': True,
            'keepvideo': False,
            'postprocessors': [
                {'key': 'FFmpegExtractAudio', 'preferredcodec': 'm4a', 'preferredquality': '160'},
                {'key': 'FFmpegMetadata'},
            ]
        })
    elif mode in ["audio_sp_sc", "audio_sc"]:
        target = f"scsearch1:{query}" if mode == "audio_sp_sc" else url
        ydl_opts.update({
            'format': 'bestaudio',
            'writethumbnails': True,
            'writeinfojson': True,
            'keepvideo': False,
            'postprocessors': [
                {'key': 'FFmpegMetadata'},
            ]
        })
    else:
        target = url
        fmt = f"bestvideo[height<={quality}]+bestaudio/best[height<={quality}]/best"
        ydl_opts.update({
            'format': fmt,
            'merge_output_format': 'mp4',
        })

    try:
        await asyncio.to_thread(_run_ytdlp, ydl_opts, str(target))
    except Exception as e:
        logging.error(f"Ошибка yt-dlp API: {e}")
        return {"success": False, "error": str(e)}

    # 5. Возврат результатов
    if "audio" in mode:
        audio_files = (
            glob.glob(os.path.join(task_dir, "*.m4a")) + 
            glob.glob(os.path.join(task_dir, "*.mp3"))
        ) or [
            f for f in glob.glob(os.path.join(task_dir, "*"))
            if not f.endswith((".jpg", ".jpeg", ".png", ".webp", ".json", ".tmp"))
        ]

        if not audio_files:
            return {"success": False, "error": "Аудиофайл не найден"}

        audio_file = audio_files[0]
        sp_album = payload.get("sp_album")

        track_title = sp_title
        track_artist = sp_artist

        info_files = glob.glob(os.path.join(task_dir, "*.info.json"))
        if info_files and not (track_title and track_artist):
            with open(info_files[0], "r", encoding="utf-8") as f:
                info = json.load(f)
                track_title = info.get("track") or info.get("title") or "a track :3"
                track_artist = info.get("artist") or info.get("uploader") or f"@{config.BOT_USERNAME}"

        # Готовим/качаем обложку
        thumb_path = _prepare_thumbnail(task_dir)

        # Вшиваем обложку и теги внутрь аудиофайла (.m4a или .mp3)
        bot_comment = f"Downloaded by @{config.BOT_USERNAME} ♡"
        _update_audio_metadata(
            audio_path=audio_file,
            title=track_title or "a track :3",
            artist=track_artist or f"@{config.BOT_USERNAME}",
            album=sp_album, # type: ignore
            comment=bot_comment,
            image_path=thumb_path # type: ignore
        )

        return {
            "success": True,
            "type": "audio",
            "file": audio_file,
            "thumb": thumb_path,
            "title": track_title or "a track :3",
            "artist": track_artist or f"@{config.BOT_USERNAME}"
        }
    else:
        video_files = glob.glob(os.path.join(task_dir, "*.mp4")) + glob.glob(os.path.join(task_dir, "*.mkv"))
        if not video_files:
            return {"success": False, "error": "Видеофайл не найден"}
            
        return {"success": True, "type": "video", "file": video_files[0]}