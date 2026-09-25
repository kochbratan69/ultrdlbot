import os
import glob
import json
import shutil
import asyncio
import logging
from aiogram import types
from aiogram.types import FSInputFile, InputMediaPhoto, InputMediaVideo

import config
from utils import get_random_filename
from services import download_spotify_cover

async def download_and_send(message: types.Message, cache_id: str, mode: str, quality: int = 0, status_msg=None):
    cache_data = config.URL_CACHE.get(cache_id)

    if not cache_data:
        if status_msg:
            await status_msg.edit_text("❌ ой, ссылочка устарела или не найдена.. TwT")
        return

    if isinstance(cache_data, dict):
        url = cache_data.get("url", "")
        sp_title = cache_data.get("sp_title")
        sp_artist = cache_data.get("sp_artist")
        sp_cover_url = cache_data.get("sp_cover_url")
        yt_url = cache_data.get("yt_url")
        query = cache_data.get("query", url)
    else:
        url = str(cache_data)
        sp_title, sp_artist, sp_cover_url, yt_url, query = None, None, None, None, url

    task_dir = os.path.join(config.DOWNLOAD_DIR, cache_id)
    os.makedirs(task_dir, exist_ok=True)

    random_name = get_random_filename(5)
    out_template = os.path.join(task_dir, f"{random_name}.%(ext)s")

    # ================= ОБРАБОТКА GALLERY-DL (TikTok & X/Twitter) =================
    if mode == "gallery_dl":
        url = cache_data.get("url", cache_data) if isinstance(cache_data, dict) else str(cache_data)
        task_dir = os.path.join(config.DOWNLOAD_DIR, cache_id)
        os.makedirs(task_dir, exist_ok=True)

        # Команда скачивания gallery-dl напрямую в папку задачи
        cmd = [
            "gallery-dl",
            "-d", task_dir,
            "-o", "directory=[\".\"]",
            "-o", "filename={num}.{extension}",
            url
        ]

        try:
            proc = await asyncio.create_subprocess_exec(
                *cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
            )
            _, stderr = await proc.communicate()

            if proc.returncode != 0:
                err_text = stderr.decode("utf-8", errors="ignore")
                logging.error(f"Ошибка gallery-dl: {err_text}")
                if status_msg:
                    await status_msg.edit_text(f"ошибочка gallery-dl TwT:\n`{err_text[-300:]}`", parse_mode="Markdown")
                return

            # Находим все сохраненные медиафайлы
            media_files = sorted([
                os.path.join(task_dir, f) for f in os.listdir(task_dir)
                if f.lower().endswith((".jpg", ".jpeg", ".png", ".webp", ".mp4", ".mov", ".mkv"))
            ])

            if not media_files:
                if status_msg:
                    await status_msg.edit_text("прости, не удалось найти картинки или видео.. TwT")
                return

            if status_msg:
                await status_msg.edit_text("отправляю медиа... >w< ~✨")

            caption = f"скачано! by @{config.BOT_USERNAME} ♡"

            # 1. Если файл всего один
            if len(media_files) == 1:
                file_path = media_files[0]
                ext = os.path.splitext(file_path)[1].lower()
                if ext in [".mp4", ".mov", ".mkv"]:
                    await message.bot.send_video(chat_id=message.chat.id, video=FSInputFile(file_path), caption=caption)
                else:
                    await message.bot.send_photo(chat_id=message.chat.id, photo=FSInputFile(file_path), caption=caption)

            # 2. Если файлов несколько (альбом / карусель TikTok)
            else:
                # Telegram принимает не более 10 медиафайлов в одном альбоме
                chunks = [media_files[i:i + 10] for i in range(0, len(media_files), 10)]
                for idx, chunk in enumerate(chunks):
                    group = []
                    for file_path in chunk:
                        ext = os.path.splitext(file_path)[1].lower()
                        if ext in [".mp4", ".mov", ".mkv"]:
                            group.append(InputMediaVideo(media=FSInputFile(file_path)))
                        else:
                            group.append(InputMediaPhoto(media=FSInputFile(file_path)))
                    
                    if idx == 0:
                        group[0].caption = caption
                        
                    await message.bot.send_media_group(chat_id=message.chat.id, media=group)

            if status_msg:
                await status_msg.delete()

        except Exception as e:
            logging.error(f"Ошибка gallery-dl: {e}")
            if status_msg:
                await status_msg.edit_text("произошла ошибочка при выкачивании картинок :cc")
        finally:
            if os.path.exists(task_dir):
                shutil.rmtree(task_dir, ignore_errors=True)
        return
    # ==============================================================================

    if mode in ["audio_sp_yt", "audio_sp_sc"] and sp_cover_url:
        sp_cover_path = os.path.join(task_dir, "spotify.jpg")
        await download_spotify_cover(sp_cover_url, sp_cover_path)

    def build_cmd(run_mode: str) -> tuple[list[str], str]:
        cmd_list = [config.YT_DLP, "--socket-timeout", "10"]

        if run_mode == "audio_sp_yt":
            target = yt_url if yt_url else f"ytsearch1:{query} Audio"
            cmd_list.extend([
                "-f", "ba/b",
                "-S", "abr",
                "-x",
                "--audio-format", "m4a",
                "--audio-quality", "160K",
                "--embed-thumbnail",
                "--write-thumbnail",
                "--embed-metadata",
                "--write-info-json",
                "--convert-thumbnails", "jpg",
                "--ppa", "ThumbnailsConvertor+ffmpeg_o:-vf crop=ih:ih,scale=320:320",
                "--check-formats",
                "--rm-cache-dir",
                "--concurrent-fragments", "1",
                "--js-runtimes", "node",
                "-o", out_template
            ])
            if os.path.exists(config.COOKIE_FILE):
                cmd_list.extend(["--cookies", config.COOKIE_FILE])

        elif run_mode in ["audio_sp_sc", "audio_sc"]:
            target = f"scsearch1:{query}" if run_mode == "audio_sp_sc" else url
            cmd_list.extend([
                "-f", "bestaudio",
                "--embed-thumbnail",
                "--write-thumbnail",
                "--embed-metadata",
                "--write-info-json",
                "--convert-thumbnails", "jpg",
                "--ppa", "ThumbnailsConvertor+ffmpeg_o:-vf scale=320:320",
                "--concurrent-fragments", "1",
                "-o", out_template
            ])

        elif run_mode == "audio_yt":
            target = url
            cmd_list.extend([
                "-f", "ba/b",
                "-S", "abr",
                "-x",
                "--audio-format", "m4a",
                "--audio-quality", "160K",
                "--embed-thumbnail",
                "--write-thumbnail",
                "--embed-metadata",
                "--write-info-json",
                "--convert-thumbnails", "jpg",
                "--ppa", "ThumbnailsConvertor+ffmpeg_o:-vf crop=ih:ih,scale=320:320",
                "--check-formats",
                "--rm-cache-dir",
                "--concurrent-fragments", "1",
                "--js-runtimes", "node",
                "-o", out_template
            ])
            if os.path.exists(config.COOKIE_FILE):
                cmd_list.extend(["--cookies", config.COOKIE_FILE])

        else:
            target = url
            fmt = f"bestvideo[height<={quality}]+bestaudio/best[height<={quality}]/best"
            cmd_list.extend([
                "-f", fmt,
                "--merge-output-format", "mp4",
                "--concurrent-fragments", "1",
                "--js-runtimes", "node",
                "-o", out_template
            ])
            if os.path.exists(config.COOKIE_FILE):
                cmd_list.extend(["--cookies", config.COOKIE_FILE])

        cmd_list.append(str(target))
        return cmd_list, str(target)

    current_mode = mode
    cmd, target_url = build_cmd(current_mode)

    try:
        proc = await asyncio.create_subprocess_exec(
            *cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
        )
        _, stderr = await proc.communicate()

        if proc.returncode != 0 and current_mode == "audio_sp_sc":
            err_text = stderr.decode("utf-8", errors="ignore")
            logging.warning(f"Ошибка SoundCloud. Фоллбэк на YouTube: {err_text[-200:]}")

            if status_msg:
                await status_msg.edit_text("в SoundCloud стояла защита >w< качаю альбомную версию с YouTube... 🔄✨")

            current_mode = "audio_sp_yt"
            cmd, target_url = build_cmd(current_mode)

            proc = await asyncio.create_subprocess_exec(
                *cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
            )
            _, stderr = await proc.communicate()

        if proc.returncode != 0:
            err_text = stderr.decode("utf-8", errors="ignore")
            logging.error(f"Ошибка yt-dlp: {err_text}")
            if status_msg:
                short_err = (err_text[-300:] if len(err_text) > 300 else err_text)
                await status_msg.edit_text(
                    f"ошибочка при скачивании TwT:\n`{short_err}`", parse_mode="Markdown"
                )
            return

        caption = f"скачано! by @{config.BOT_USERNAME} ♡"

        if current_mode in ["audio_yt", "audio_sc", "audio_sp_yt", "audio_sp_sc"]:
            audio_files = glob.glob(os.path.join(task_dir, "*.m4a"))
            if not audio_files:
                audio_files = [
                    f for f in glob.glob(os.path.join(task_dir, "*"))
                    if not f.endswith((".jpg", ".jpeg", ".png", ".webp", ".json"))
                ]

            if not audio_files:
                if status_msg:
                    await status_msg.edit_text("прости, но я потерял скачанный трек.. TwT напиши админу чтобы починил :3")
                return

            audio_path = audio_files[0]

            sp_cover_path = os.path.join(task_dir, "spotify.jpg")
            if os.path.exists(sp_cover_path):
                thumb_path = sp_cover_path
            else:
                thumb_files = glob.glob(os.path.join(task_dir, "*.jpg")) + glob.glob(
                    os.path.join(task_dir, "*.jpeg")
                )
                thumb_path = thumb_files[0] if thumb_files else None

            if sp_title and sp_artist:
                track_title = sp_title
                track_artist = sp_artist
            else:
                track_title = "a track :3"
                track_artist = "suicidaldownloadbot"
            
                info_files = glob.glob(os.path.join(task_dir, "*.info.json"))
                if info_files:
                    with open(info_files[0], "r", encoding="utf-8") as f:
                        info = json.load(f)
                        track_title = info.get("track") or info.get("title") or "a track :3"
                        track_artist = info.get("artist") or info.get("uploader") or info.get("channel") or "suicidaldownloadbot"

            if status_msg:
                await status_msg.edit_text("отправляю тебе песенку... >w< ~🎵")

            await message.bot.send_audio(
                chat_id=message.chat.id,
                audio=FSInputFile(audio_path),
                caption=caption,
                title=track_title,
                performer=track_artist,
                thumbnail=FSInputFile(thumb_path) if thumb_path else None,
            )

        else:
            video_files = glob.glob(os.path.join(task_dir, "*.mp4")) + glob.glob(
                os.path.join(task_dir, "*.mkv")
            )
            if not video_files:
                video_files = [f for f in glob.glob(os.path.join(task_dir, "*"))]

            if not video_files:
                if status_msg:
                    await status_msg.edit_text("прости, но я потерял видео.. TwT попробуй ещё раз :3")
                return

            video_path = video_files[0]

            if status_msg:
                await status_msg.edit_text("отправляю тебе видео... >w< ~🎬")

            await message.bot.send_video(
                chat_id=message.chat.id,
                video=FSInputFile(video_path),
                caption=caption,
            )

        if status_msg:
            await status_msg.delete()

    except Exception as e:
        logging.error(f"Ошибка выполнения: {e}")
        if status_msg:
            await status_msg.edit_text("произошла ошибочка :cc")
    finally:
        if os.path.exists(task_dir):
            shutil.rmtree(task_dir, ignore_errors=True)