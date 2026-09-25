from urllib.parse import urlparse
from aiogram import Router, F, types
from aiogram.filters import Command, CommandStart
from aiogram.types import CallbackQuery
from aiogram.utils.keyboard import InlineKeyboardBuilder

import config
from utils import load_plus_ids, is_supported_url, get_first_url
from services import extract_video_qualities, get_spotify_track_info, search_youtube_info
from downloader import download_and_send

router = Router()

@router.message(CommandStart())
async def cmd_start(message: types.Message):
    await message.answer(
        "приветик! :3 отправь мне ссылку на то, что хочешь скачать и я попробую это сделать для тебя UwU ~✨"
    )

@router.message(Command("plusreload"))
async def cmd_plus_reload(message: types.Message):
    count = load_plus_ids()
    await message.answer(
        f"список Plus-пользователей успешно обновлен! ✨\n"
        f"всего загружено ID: **{count}** (⁠≧⁠◡⁠≦⁠) ♡",
        parse_mode="Markdown"
    )

@router.message(F.text)
async def handle_message(message: types.Message):
    text = message.text
    if not is_supported_url(text):
        return

    url = get_first_url(text)
    domain = urlparse(url).netloc.lower()

    status_msg = await message.answer("анализирую твою ссылочку... (⁠｡⁠•̀⁠ᴗ⁠-⁠)⁠✧")
    cache_id = str(message.message_id)

    if any(d in domain for d in ["tiktok.com", "tiktokv.com", "x.com", "twitter.com", "pinterest.com", "pin.it"]):
        config.URL_CACHE[cache_id] = url
        await status_msg.edit_text("скачиваю медиа через gallery-dl... ^w^ ✨")
        await download_and_send(message, cache_id, mode="gallery_dl", status_msg=status_msg)
        return

    if "soundcloud.com" in domain:
        config.URL_CACHE[cache_id] = url
        await status_msg.edit_text("начинаю скачивать для тебя.. ^w^")
        await download_and_send(message, cache_id, mode="audio_sc", status_msg=status_msg)
        return

    if "spotify.com" in domain:
        await status_msg.edit_text("ищу альбомную версию без шумов клипа... ♡")
        sp_title, sp_artist, sp_cover_url, sp_album = await get_spotify_track_info(url)
        
        search_query = f"{sp_artist} - {sp_title}" if (sp_artist and sp_title) else url
        yt_url, yt_title = await search_youtube_info(sp_artist, sp_title, sp_album, search_query)

        config.URL_CACHE[cache_id] = {
            "url": url,
            "sp_title": sp_title,
            "sp_artist": sp_artist,
            "sp_cover_url": sp_cover_url,
            "yt_url": yt_url,
            "query": search_query
        }

        builder = InlineKeyboardBuilder()
        builder.button(text="скачать с ют (чистый звук) ✨", callback_data=f"dl:{cache_id}:audio_sp_yt:0")
        builder.button(text="найти в ск ☁️", callback_data=f"dl:{cache_id}:audio_sp_sc:0")
        builder.adjust(1)

        artist_str = f"{sp_artist} — " if sp_artist else ""
        album_str = f" 💿 *[{sp_album}]*" if sp_album else ""
        yt_info_str = f"🎥 **нашел идеальный альбомный трек:**\n[{yt_title or 'Ссылка'}]({yt_url})\n\n" if yt_url else ""

        text_msg = (
            f"🎵 **{artist_str}{sp_title or 'трек'}**{album_str}\n\n"
            f"{yt_info_str}"
            f"💡 *если что, всегда можно попробовать саундклауд! :3*"
        )

        await status_msg.edit_text(
            text_msg, 
            reply_markup=builder.as_markup(), 
            parse_mode="Markdown",
            disable_web_page_preview=False
        )
        return

    config.URL_CACHE[cache_id] = url
    qualities = await extract_video_qualities(url)

    builder = InlineKeyboardBuilder()
    if qualities:
        for q in qualities:
            label = f"видео ({q}p) ⭐" if q > 1080 else f"видео ({q}p)"
            builder.button(text=label, callback_data=f"dl:{cache_id}:video:{q}")
    else:
        for q in [1080, 720, 480, 360]:
            builder.button(text=f"видео ({q}p)", callback_data=f"dl:{cache_id}:video:{q}")

    builder.button(text="трек (m4a)", callback_data=f"dl:{cache_id}:audio_yt:0")
    builder.adjust(2)

    await status_msg.edit_text(
        "выбери качество видео или сохрани как трек :3",
        reply_markup=builder.as_markup()
    )

@router.callback_query(F.data.startswith("dl:"))
async def process_download_callback(callback: CallbackQuery):
    _, cache_id, mode, quality_str = callback.data.split(":")
    quality = int(quality_str)
    user_id = callback.from_user.id

    if mode == "video" and quality > 1080 and user_id not in config.PLUS_USERS:
        await callback.answer(
            "❌ скачивание в 2K/4K доступно только для Plus-пользователей! TwT",
            show_alert=True
        )
        return

    await callback.answer()

    if cache_id not in config.URL_CACHE:
        await callback.message.edit_text("отправь мне ссылочку ещё раз, я её чутка упустил >3<")
        return

    status_msg = await callback.message.edit_text("начинаю скачивать для тебя.. ^w^ ✨")
    await download_and_send(
        message=callback.message, 
        cache_id=cache_id, 
        mode=mode, 
        quality=int(quality), 
        status_msg=status_msg
    )