import logging
import os
import asyncio
import shutil
import sys
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

import config
from preupdater import check_and_update_binaries
from services import extract_video_qualities, get_spotify_track_info, search_youtube_info
from downloader import execute_download_task

# Проверяем, передан ли флаг --debug
IS_DEBUG = "--debug" in sys.argv
DISABLE_COOKIES = "--disable-cookies" in sys.argv

# Настраиваем уровень логов для приложения
logging.basicConfig(
    level=logging.DEBUG if IS_DEBUG else logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s"
)

# Сохраняем флаг в config, чтобы к нему был доступ отовсюду
config.DEBUG = IS_DEBUG
config.DISABLE_COOKIES = DISABLE_COOKIES

if IS_DEBUG:
    logging.info("DEBUG Mode is enabled! Now you can see fully detailed logs.")

if DISABLE_COOKIES:
    logging.info("Cookies are now ignored because of --disable-cookies option.")

app = FastAPI(title="Worker")

class QualitiesReq(BaseModel):
    url: str

class SpotifyReq(BaseModel):
    url: str

class DownloadReq(BaseModel):
    cache_id: str
    mode: str
    quality: int = 0
    payload: dict = {}

class CleanupReq(BaseModel):
    cache_id: str

@app.on_event("startup")
async def startup_event():
    # Проверяем бинарники при старте воркера
    await asyncio.to_thread(check_and_update_binaries)

@app.post("/extractqualities")
async def extract_qualities_endpoint(req: QualitiesReq):
    qualities = await extract_video_qualities(req.url)
    return {"qualities": qualities}

@app.post("/spotifyinfo")
async def spotify_info_endpoint(req: SpotifyReq):
    sp_title, sp_artist, sp_cover_url, sp_album = await get_spotify_track_info(req.url)
    search_query = f"{sp_artist} - {sp_title}" if (sp_artist and sp_title) else req.url
    yt_url, yt_title = await search_youtube_info(sp_artist, sp_title, sp_album, search_query)
    
    return {
        "sp_title": sp_title,
        "sp_artist": sp_artist,
        "sp_cover_url": sp_cover_url,
        "sp_album": sp_album,
        "yt_url": yt_url,
        "yt_title": yt_title,
        "query": search_query
    }

@app.post("/download")
async def download_endpoint(req: DownloadReq):
    res = await execute_download_task(
        cache_id=req.cache_id,
        mode=req.mode,
        quality=req.quality,
        payload=req.payload
    )
    if not res.get("success"):
        raise HTTPException(status_code=500, detail=res.get("error", "Download error"))
    return res

@app.post("/cleanup")
async def cleanup_endpoint(req: CleanupReq):
    import config
    task_dir = os.path.join(config.DOWNLOAD_DIR, req.cache_id)
    if os.path.exists(task_dir):
        shutil.rmtree(task_dir, ignore_errors=True)
    return {"status": "ok"}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="127.0.0.1", port=8000)