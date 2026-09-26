import os
import asyncio
import logging
import urllib.request
import yt_dlp
from spotify_scraper import AsyncSpotifyClient

import config

async def extract_video_qualities(url: str) -> list[int]:

    ydl_opts = {
        'quiet': True,
        'no_warnings': True,
        'skip_download': True,
        'socket_timeout': 10,
        'js_runtimes': {'node': {}},
    }
    if os.path.exists(config.COOKIE_FILE):
        ydl_opts['cookiefile'] = config.COOKIE_FILE

    def _get_info():
        with yt_dlp.YoutubeDL(ydl_opts) as ydl: # type: ignore
            return ydl.extract_info(url, download=False)

    try:
        info = await asyncio.to_thread(_get_info)
        formats = info.get('formats', [])
        heights = set()
        for f in formats: # type: ignore
            h = f.get('height')
            vcodec = f.get('vcodec')
            if h and vcodec != 'none' and h >= 144:
                heights.add(h)
        return sorted(list(heights), reverse=True)
    except Exception as e:
        logging.error(f"ошибочка при получении разрешений: {e}")
        return []

async def get_spotify_track_info(url: str) -> tuple[str | None, str | None, str | None, str | None]:
    try:
        async with AsyncSpotifyClient() as client:
            track = await client.get_track(url)
            title = track.name

            if hasattr(track, 'artists') and track.artists:
                artist = ", ".join([a.name for a in track.artists if hasattr(a, 'name')])
            else:
                artist = "Unknown Artist"

            cover_url = None
            if hasattr(track, 'images') and track.images:
                first_img = track.images[0]
                if hasattr(first_img, 'url'):
                    cover_url = first_img.url

            album_name = None
            if hasattr(track, 'album') and track.album:
                if hasattr(track.album, 'name'):
                    album_name = track.album.name
                elif isinstance(track.album, str):
                    album_name = track.album

            return title, artist, cover_url, album_name
    except Exception as e:
        logging.error(f"Ошибка получения метаданных из spotifyscraper: {e}")
        return None, None, None, None

async def download_spotify_cover(cover_url: str, save_path: str) -> bool:
    try:
        def _download():
            req = urllib.request.Request(
                cover_url,
                headers={'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)'}
            )
            with urllib.request.urlopen(req) as resp, open(save_path, 'wb') as out_file:
                out_file.write(resp.read())

        await asyncio.to_thread(_download)
        return True
    except Exception as e:
        logging.error(f"Не удалось скачать обложку Spotify: {e}")
        return False

async def search_youtube_info(artist: str | None, title: str | None, album: str | None, raw_query: str) -> tuple[str | None, str | None]:
    """Умный поиск на YouTube с проверкой описания (Provided to YouTube by) ✨"""
    def _search():
        search_str = f"{artist} {title}" if (artist and title) else raw_query

        ydl_opts = {
            'quiet': True,
            'no_warnings': True,
            'skip_download': True,
            'socket_timeout': 10,
            'js_runtimes': {'node': {}},
        }

        with yt_dlp.YoutubeDL(ydl_opts) as ydl: # type: ignore
            info = ydl.extract_info(f"ytsearch5:{search_str}", download=False)
            if info and 'entries' in info and len(info['entries']) > 0: # type: ignore
                entries = [e for e in info['entries'] if e]
                
                def score_entry(entry):
                    score = 0
                    e_title = (entry.get('title') or '').lower()
                    e_uploader = (entry.get('uploader') or entry.get('channel') or '').lower()
                    e_desc = (entry.get('description') or '').lower()

                    if "provided to youtube by" in e_desc:
                        score += 200
                    if " · " in e_desc:
                        score += 50
                    if album or album.lower() in e_desc: # type: ignore
                        score += 80
                    if "topic" in e_uploader:
                        score += 100
                    if artist or artist.lower() in e_uploader: # type: ignore
                        score += 150
                    if "audio" in e_title:
                        score += 30
                    if any(bad in e_title for bad in ["official video", "official lyric", "lyric video", "music video", "official clip", " mv", "live"]):
                        score -= 150

                    return score

                best_entry = max(entries, key=score_entry)
                video_id = best_entry.get('id')
                video_title = best_entry.get('title')
                url = f"https://www.youtube.com/watch?v={video_id}" if video_id else best_entry.get('url')
                return url, video_title

        return None, None

    try:
        return await asyncio.to_thread(_search)
    except Exception as e:
        logging.error(f"Ошибка умного поиска на YouTube: {e}")
        return None, None