import os
import time
import aiohttp
from urllib.parse import urlparse
from aiogram import Router, F, types
from aiogram.filters import Command, CommandStart
from aiogram.types import CallbackQuery, FSInputFile, InputMediaPhoto, InputMediaVideo, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.utils.keyboard import InlineKeyboardBuilder

import config
from utils import load_plus_ids, is_supported_url, get_first_url
from i18n import get_msg

router = Router()

def get_user_lang(event: types.Message | CallbackQuery) -> str:
    """Определяет язык пользователя Telegram (ru, en и т.д.)"""
    code = event.from_user.language_code if event.from_user else "ru"
    return code[:2] if code else "ru"

async def call_worker(endpoint: str, json_data: dict) -> dict:
    url = f"{config.WORKER_URL}{endpoint}"
    headers = {"Authorization": f"Bearer {config.AUTH_TOKEN}"}
    timeout = aiohttp.ClientTimeout(total=600)
    
    connector = aiohttp.TCPConnector(ssl=False) if config.ENABLE_SSL else None

    async with aiohttp.ClientSession(timeout=timeout, headers=headers, connector=connector) as session:
        async with session.post(url, json=json_data) as resp:
            data = await resp.json()
            if resp.status != 200:
                raise Exception(data.get("detail", "Worker error"))
            return data

@router.message(CommandStart())
async def cmd_start(message: types.Message):
    lang = get_user_lang(message)
    await message.answer(get_msg("cmd_start", lang))

@router.message(Command("plusreload"))
async def cmd_plus_reload(message: types.Message):
    lang = get_user_lang(message)
    count = load_plus_ids()
    await message.answer(get_msg("cmd_plus_reload", lang, count=count), parse_mode="Markdown")

@router.callback_query(F.data.startswith("share:"))
async def process_share_callback(callback: CallbackQuery):
    lang = get_user_lang(callback)
    _, cache_id, created_at_str = callback.data.split(":")
    created_at = int(created_at_str)
    now = int(time.time())

    if now - created_at > 1800:
        await callback.answer(get_msg("alert_share_expired", lang), show_alert=True)
        return

    await callback.answer(get_msg("msg_share_generating", lang))

    try:
        res = await call_worker("/createshare", {"cache_id": cache_id})
        shortcode = res.get("shortcode")
        access_key = res.get("key")
        
        share_url = f"{config.DOMAIN}/{shortcode}?k={access_key}#1hr"

        await callback.message.reply(
            get_msg("msg_share_result", lang, share_url=share_url, shortcode=shortcode, key=access_key, domain=config.DOMAIN),
            parse_mode="Markdown",
            disable_web_page_preview=True
        )
    except Exception as e:
        await callback.message.reply(get_msg("err_share", lang, error=e), parse_mode="Markdown")

@router.message(F.text)
async def handle_message(message: types.Message):
    lang = get_user_lang(message)
    text = message.text
    if not is_supported_url(text):
        return

    url = get_first_url(text)
    domain = urlparse(url).netloc.lower()
    status_msg = await message.answer(get_msg("msg_analyzing", lang))
    cache_id = str(message.message_id)

    if "instagram.com" in domain:
        config.URL_CACHE[cache_id] = {"url": url}
        await status_msg.edit_text(get_msg("msg_downloading_ig", lang))
        await process_worker_download(message, cache_id, mode="instagram", status_msg=status_msg)
        return

    if any(d in domain for d in ["tiktok.com", "tiktokv.com", "x.com", "twitter.com", "pinterest.com", "pin.it"]):
        config.URL_CACHE[cache_id] = {"url": url}
        await status_msg.edit_text(get_msg("msg_downloading_media", lang))
        await process_worker_download(message, cache_id, mode="gallery_dl", status_msg=status_msg)
        return

    if "soundcloud.com" in domain:
        config.URL_CACHE[cache_id] = {"url": url}
        await status_msg.edit_text(get_msg("msg_downloading_audio", lang))
        await process_worker_download(message, cache_id, mode="audio_sc", status_msg=status_msg)
        return

    if "spotify.com" in domain:
        await status_msg.edit_text(get_msg("msg_spotify_searching", lang))
        try:
            sp_data = await call_worker("/spotifyinfo", {"url": url})
            sp_data["url"] = url
            config.URL_CACHE[cache_id] = sp_data

            builder = InlineKeyboardBuilder()
            builder.button(text=get_msg("btn_spotify_yt", lang), callback_data=f"dl:{cache_id}:audio_sp_yt:0")
            builder.button(text=get_msg("btn_spotify_sc", lang), callback_data=f"dl:{cache_id}:audio_sp_sc:0")
            builder.adjust(1)

            artist_str = f"{sp_data['sp_artist']} — " if sp_data.get('sp_artist') else ""
            album_str = f" 💿 *[{sp_data['sp_album']}]*" if sp_data.get('sp_album') else ""
            yt_info_str = f"🎥 **нашел альбомный трек:**\n[{sp_data.get('yt_title') or 'Ссылка'}]({sp_data.get('yt_url')})\n\n" if sp_data.get('yt_url') else ""

            text_msg = get_msg(
                "msg_spotify_info", lang,
                artist_str=artist_str, title=sp_data.get('sp_title') or 'трек',
                album_str=album_str, yt_info_str=yt_info_str
            )

            await status_msg.edit_text(text_msg, reply_markup=builder.as_markup(), parse_mode="Markdown")
        except Exception as e:
            await status_msg.edit_text(get_msg("err_spotify", lang, error=e))
        return

    config.URL_CACHE[cache_id] = {"url": url}
    try:
        q_data = await call_worker("/extractqualities", {"url": url})
        qualities = q_data.get("qualities", [])
    except Exception:
        qualities = []

    builder = InlineKeyboardBuilder()
    if qualities:
        for q in qualities:
            btn_text = get_msg("btn_video_star", lang, quality=q) if q > 1080 else get_msg("btn_video", lang, quality=q)
            builder.button(text=btn_text, callback_data=f"dl:{cache_id}:video:{q}")
    else:
        for q in [1080, 720, 480, 360]:
            builder.button(text=get_msg("btn_video", lang, quality=q), callback_data=f"dl:{cache_id}:video:{q}")

    builder.button(text=get_msg("btn_audio_track", lang), callback_data=f"dl:{cache_id}:audio_yt:0")
    builder.adjust(2)

    await status_msg.edit_text(get_msg("msg_choose_quality", lang), reply_markup=builder.as_markup())

@router.callback_query(F.data.startswith("dl:"))
async def process_download_callback(callback: CallbackQuery):
    lang = get_user_lang(callback)
    _, cache_id, mode, quality_str = callback.data.split(":")
    quality = int(quality_str)

    if mode == "video" and quality > 1080 and callback.from_user.id not in config.PLUS_USERS:
        await callback.answer(get_msg("alert_plus_only_quality", lang), show_alert=True)
        return

    await callback.answer()
    if cache_id not in config.URL_CACHE:
        await callback.message.edit_text(get_msg("msg_link_expired", lang))
        return

    status_msg = await callback.message.edit_text(get_msg("msg_downloading_start", lang))
    await process_worker_download(callback.message, cache_id, mode, quality, status_msg)

async def process_worker_download(message: types.Message, cache_id: str, mode: str, quality: int = 0, status_msg=None):
    lang = get_user_lang(message)
    payload = config.URL_CACHE.get(cache_id, {})
    if isinstance(payload, str):
        payload = {"url": payload}

    user_msg_id = int(cache_id) if cache_id.isdigit() else message.message_id
    created_at = int(time.time())

    share_kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=get_msg("btn_share", lang), callback_data=f"share:{cache_id}:{created_at}")]
    ])

    try:
        res = await call_worker("/download", {
            "cache_id": cache_id,
            "mode": mode,
            "quality": quality,
            "payload": payload
        })
        caption = get_msg("caption_downloaded", lang, bot_username=config.BOT_USERNAME)

        if res.get("type") == "gallery":
            files = res.get("files", [])
            if len(files) == 1:
                f_path = files[0]
                if f_path.lower().endswith((".mp4", ".mov", ".mkv")):
                    await message.bot.send_video(
                        message.chat.id, FSInputFile(f_path), caption=caption, 
                        reply_to_message_id=user_msg_id, reply_markup=share_kb
                    )
                else:
                    await message.bot.send_photo(
                        message.chat.id, FSInputFile(f_path), caption=caption, 
                        reply_to_message_id=user_msg_id, reply_markup=share_kb
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

                    reply_id = user_msg_id if idx == 0 else None
                    await message.bot.send_media_group(message.chat.id, media=group, reply_to_message_id=reply_id)
                
                await message.bot.send_message(
                    message.chat.id, get_msg("msg_gallery_share_prompt", lang), 
                    reply_to_message_id=user_msg_id, reply_markup=share_kb
                )

        elif res.get("type") == "audio":
            thumb = FSInputFile(res["thumb"]) if res.get("thumb") else None
            await message.bot.send_audio(
                message.chat.id, audio=FSInputFile(res["file"]), caption=caption,
                title=res.get("title"), performer=res.get("artist"), thumbnail=thumb,
                reply_to_message_id=user_msg_id, reply_markup=share_kb
            )

        elif res.get("type") == "video":
            await message.bot.send_video(
                message.chat.id, video=FSInputFile(res["file"]), caption=caption, 
                reply_to_message_id=user_msg_id, reply_markup=share_kb
            )

        if status_msg:
            await status_msg.delete()

    except Exception as e:
        if status_msg:
            await status_msg.edit_text(get_msg("err_download", lang, error=e), parse_mode="Markdown")