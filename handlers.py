import os
import aiohttp
from urllib.parse import urlparse
from aiogram import Router, F, types
from aiogram.filters import Command, CommandStart
from aiogram.types import CallbackQuery, FSInputFile, InputMediaPhoto, InputMediaVideo
from aiogram.utils.keyboard import InlineKeyboardBuilder

import config
from utils import load_plus_ids, is_supported_url, get_first_url

router = Router()

async def call_worker(endpoint: str, json_data: dict) -> dict:
    url = f"{config.WORKER_URL}{endpoint}"
    timeout = aiohttp.ClientTimeout(total=600)
    async with aiohttp.ClientSession(timeout=timeout) as session:
        async with session.post(url, json=json_data) as resp:
            data = await resp.json()
            if resp.status != 200:
                raise Exception(data.get("detail", "Worker error"))
            return data

@router.message(CommandStart())
async def cmd_start(message: types.Message):
    await message.answer("приветик! :3 отправь мне ссылку, и я скачаю её для тебя UwU ~✨")

@router.message(Command("plusreload"))
async def cmd_plus_reload(message: types.Message):
    count = load_plus_ids()
    await message.answer(f"список Plus-пользователей обновлен! ✨\nВсего ID: **{count}**", parse_mode="Markdown")

@router.message(F.text)
async def handle_message(message: types.Message):
    text = message.text
    if not is_supported_url(text): # type: ignore
        return

    url = get_first_url(text) # type: ignore
    domain = urlparse(url).netloc.lower()
    status_msg = await message.answer("анализирую твою ссылочку... (⁠｡⁠•̀⁠ᴗ⁠-⁠)⁠✧")
    cache_id = str(message.message_id)

    # 1. Instagram
    if "instagram.com" in domain:
        config.URL_CACHE[cache_id] = {"url": url}
        await status_msg.edit_text("скачиваю пост из Instagram... ^w^ ✨")
        await process_worker_download(message, cache_id, mode="instagram", status_msg=status_msg)
        return

    # 2. Gallery-Dl (TikTok, X, Pinterest)
    if any(d in domain for d in ["tiktok.com", "tiktokv.com", "x.com", "twitter.com", "pinterest.com", "pin.it"]):
        config.URL_CACHE[cache_id] = {"url": url}
        await status_msg.edit_text("скачиваю медиа... ^w^ ✨")
        await process_worker_download(message, cache_id, mode="gallery_dl", status_msg=status_msg)
        return

    # 2. SoundCloud
    if "soundcloud.com" in domain:
        config.URL_CACHE[cache_id] = {"url": url}
        await status_msg.edit_text("начинаю скачивать для тебя.. ^w^")
        await process_worker_download(message, cache_id, mode="audio_sc", status_msg=status_msg)
        return

    # 3. Spotify
    if "spotify.com" in domain:
        await status_msg.edit_text("ищу альбомную версию без шумов клипа... ♡")
        try:
            sp_data = await call_worker("/spotifyinfo", {"url": url})
            sp_data["url"] = url
            config.URL_CACHE[cache_id] = sp_data

            builder = InlineKeyboardBuilder()
            builder.button(text="скачать с ют (чистый звук) ✨", callback_data=f"dl:{cache_id}:audio_sp_yt:0")
            builder.button(text="найти в ск ☁️", callback_data=f"dl:{cache_id}:audio_sp_sc:0")
            builder.adjust(1)

            artist_str = f"{sp_data['sp_artist']} — " if sp_data.get('sp_artist') else ""
            album_str = f" 💿 *[{sp_data['sp_album']}]*" if sp_data.get('sp_album') else ""
            yt_info_str = f"🎥 **нашел альбомный трек:**\n[{sp_data.get('yt_title') or 'Ссылка'}]({sp_data.get('yt_url')})\n\n" if sp_data.get('yt_url') else ""

            text_msg = (
                f"🎵 **{artist_str}{sp_data.get('sp_title') or 'трек'}**{album_str}\n\n"
                f"{yt_info_str}💡 *всегда можно попробовать саундклауд! :3*"
            )

            await status_msg.edit_text(text_msg, reply_markup=builder.as_markup(), parse_mode="Markdown")
        except Exception as e:
            await status_msg.edit_text(f"ошибка Spotify TwT: {e}")
        return

    # 4. YouTube / Обычные видео
    config.URL_CACHE[cache_id] = {"url": url}
    try:
        q_data = await call_worker("/extractqualities", {"url": url})
        qualities = q_data.get("qualities", [])
    except Exception:
        qualities = []

    builder = InlineKeyboardBuilder()
    if qualities:
        for q in qualities:
            builder.button(text=f"видео ({q}p) ⭐" if q > 1080 else f"видео ({q}p)", callback_data=f"dl:{cache_id}:video:{q}")
    else:
        for q in [1080, 720, 480, 360]:
            builder.button(text=f"видео ({q}p)", callback_data=f"dl:{cache_id}:video:{q}")

    builder.button(text="трек (m4a)", callback_data=f"dl:{cache_id}:audio_yt:0")
    builder.adjust(2)

    await status_msg.edit_text("выбери качество видео или сохрани как трек :3", reply_markup=builder.as_markup())

@router.callback_query(F.data.startswith("dl:"))
async def process_download_callback(callback: CallbackQuery):
    _, cache_id, mode, quality_str = callback.data.split(":") # type: ignore
    quality = int(quality_str)

    if mode == "video" and quality > 1080 and callback.from_user.id not in config.PLUS_USERS:
        await callback.answer("❌ Скачивание в 2K/4K только для Plus-пользователей! TwT", show_alert=True)
        return

    await callback.answer()
    if cache_id not in config.URL_CACHE:
        await callback.message.edit_text("ссылочка устарела >3<") # type: ignore
        return

    status_msg = await callback.message.edit_text("начинаю скачивать для тебя.. ^w^ ✨") # type: ignore
    await process_worker_download(callback.message, cache_id, mode, quality, status_msg) # type: ignore

async def process_worker_download(message: types.Message, cache_id: str, mode: str, quality: int = 0, status_msg=None):
    payload = config.URL_CACHE.get(cache_id, {})
    if isinstance(payload, str):
        payload = {"url": payload}

    user_msg_id = int(cache_id) if cache_id.isdigit() else message.message_id

    try:
        res = await call_worker("/download", {
            "cache_id": cache_id,
            "mode": mode,
            "quality": quality,
            "payload": payload
        })
        caption = f"скачано! by @{config.BOT_USERNAME} ♡"

        # Отправка Галереи
        if res.get("type") == "gallery":
            files = res.get("files", [])
            if len(files) == 1:
                f_path = files[0]
                if f_path.lower().endswith((".mp4", ".mov", ".mkv")):
                    await message.bot.send_video( # type: ignore
                        message.chat.id, 
                        FSInputFile(f_path), 
                        caption=caption, 
                        reply_to_message_id=user_msg_id
                    )
                else:
                    await message.bot.send_photo( # type: ignore
                        message.chat.id, 
                        FSInputFile(f_path), 
                        caption=caption, 
                        reply_to_message_id=user_msg_id
                    )
            else:
                chunks = [files[i:i + 10] for i in range(0, len(files), 10)]
                for idx, chunk in enumerate(chunks):
                    group = []
                    for f_idx, f_path in enumerate(chunk):
                        item_caption = caption if (idx == 0 and f_idx == 0) else None
                        if f_path.lower().endswith((".mp4", ".mov", ".mkv")):
                            group.append(InputMediaVideo(media=FSInputFile(f_path), caption=item_caption))
                        else:
                            group.append(InputMediaPhoto(media=FSInputFile(f_path), caption=item_caption))

                    # Отвечаем на исходное сообщение первой группой медиа
                    reply_id = user_msg_id if idx == 0 else None
                    await message.bot.send_media_group( # type: ignore
                        message.chat.id, 
                        media=group, 
                        reply_to_message_id=reply_id
                    )

        # Отправка Аудио
        elif res.get("type") == "audio":
            thumb = FSInputFile(res["thumb"]) if res.get("thumb") else None
            await message.bot.send_audio( # type: ignore
                message.chat.id,
                audio=FSInputFile(res["file"]),
                caption=caption,
                title=res.get("title"),
                performer=res.get("artist"),
                thumbnail=thumb,
                reply_to_message_id=user_msg_id
            )

        # Отправка Видео
        elif res.get("type") == "video":
            await message.bot.send_video( # type: ignore
                message.chat.id, 
                video=FSInputFile(res["file"]), 
                caption=caption, 
                reply_to_message_id=user_msg_id
            )

        if status_msg:
            await status_msg.delete()

    except Exception as e:
        if status_msg:
            await status_msg.edit_text(f"ошибочка при скачивании TwT:\n`{e}`", parse_mode="Markdown")
    finally:
        # Очищаем временную папку на воркере
        try:
            await call_worker("/cleanup", {"cache_id": cache_id})
        except Exception:
            pass