import logging
import os
import time
import asyncio
import shutil
import sys
import secrets
import zipfile
from fastapi import FastAPI, HTTPException, Request, Query
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel

import config
import database
from preupdater import check_and_update_binaries
from services import extract_video_qualities, get_spotify_track_info, search_youtube_info
from downloader import execute_download_task

IS_DEBUG = "--debug" in sys.argv
DISABLE_COOKIES = "--disable-cookies" in sys.argv

logging.basicConfig(
    level=logging.DEBUG if IS_DEBUG else logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s"
)

config.DEBUG = IS_DEBUG
config.DISABLE_COOKIES = DISABLE_COOKIES

app = FastAPI(title="Worker")

# 🔒 Middleware для проверки Bearer-авторизации
@app.middleware("http")
async def auth_middleware(request: Request, call_next):
    path = request.url.path
    
    # Разрешаем свободный доступ к скачиванию по шорткодам /{shortcode}
    if request.method == "GET" and path != "/" and path.count("/") == 1 and not path.startswith("/docs") and not path.startswith("/openapi.json"):
        return await call_next(request)

    # Проверяем Bearer токен для всех API эндпоинтов
    auth_header = request.headers.get("Authorization")
    if not auth_header or not auth_header.startswith("Bearer "):
        return JSONResponse(status_code=401, content={"detail": "Unauthorized: missing or invalid bearer token"})
    
    token = auth_header.split(" ", 1)[1]
    if token != config.AUTH_TOKEN:
        return JSONResponse(status_code=403, content={"detail": "Forbidden: invalid bearer token"})

    return await call_next(request)

class QualitiesReq(BaseModel):
    url: str

class SpotifyReq(BaseModel):
    url: str

class DownloadReq(BaseModel):
    cache_id: str
    mode: str
    quality: int = 0
    payload: dict = {}

class ShareReq(BaseModel):
    cache_id: str

async def background_cleanup_loop():
    while True:
        try:
            database.clean_expired_shares()
            
            now = time.time()
            if os.path.exists(config.DOWNLOAD_DIR):
                for folder in os.listdir(config.DOWNLOAD_DIR):
                    folder_path = os.path.join(config.DOWNLOAD_DIR, folder)
                    if os.path.isdir(folder_path):
                        if now - os.path.getmtime(folder_path) > 2400:  # 40 минут
                            shutil.rmtree(folder_path, ignore_errors=True)
        except Exception as e:
            logging.error(f"Ошибка фоновой очистки: {e}")

        await asyncio.sleep(300)

@app.on_event("startup")
async def startup_event():
    database.init_db()
    asyncio.create_task(background_cleanup_loop())
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

@app.post("/createshare")
async def create_share_endpoint(req: ShareReq):
    task_dir = os.path.join(config.DOWNLOAD_DIR, req.cache_id)
    if not os.path.exists(task_dir):
        raise HTTPException(status_code=404, detail="Файлы не найдены или устарели")

    files = [
        os.path.join(task_dir, f) for f in os.listdir(task_dir)
        if not f.endswith((".json", ".tmp")) and os.path.isfile(os.path.join(task_dir, f))
    ]

    if not files:
        raise HTTPException(status_code=404, detail="Медиафайлы не найдены")

    shortcode = secrets.token_hex(3)
    access_key = secrets.token_hex(4)
    expires_at = int(time.time()) + 3600

    if len(files) == 1:
        source_file = files[0]
        ext = os.path.splitext(source_file)[1]
        target_filename = f"{shortcode}{ext}"
        target_path = os.path.join(config.SHARE_DIR, target_filename)
        shutil.copy2(source_file, target_path)
        download_name = os.path.basename(source_file)
    else:
        target_filename = f"{shortcode}.zip"
        target_path = os.path.join(config.SHARE_DIR, target_filename)
        with zipfile.ZipFile(target_path, 'w') as zipf:
            for f in files:
                zipf.write(f, arcname=os.path.basename(f))
        download_name = f"gallery_{req.cache_id}.zip"

    database.add_share_link(
        shortcode=shortcode,
        file_path=target_path,
        filename=download_name,
        expires_at=expires_at,
        access_key=access_key
    )

    return {"shortcode": shortcode, "key": access_key}

# 📥 Скачивание файла по короткой ссылке с проверкой параметров ?k=
@app.get("/{shortcode}")
async def download_shared_file(shortcode: str, k: str = Query(None)):
    if not k:
        raise HTTPException(status_code=403, detail="Доступ запрещен: отсутствует ключ доступа")

    clean_code = shortcode.split("#")[0].strip()
    data = database.get_share_link(clean_code)

    if not data:
        raise HTTPException(status_code=404, detail="Ссылка не найдена или истекла")

    if data["access_key"] != k:
        raise HTTPException(status_code=403, detail="Неверный ключ доступа")

    if time.time() > data["expires_at"]:
        raise HTTPException(status_code=410, detail="Срок действия ссылки истек")

    file_path = data["file_path"]
    if not os.path.exists(file_path):
        raise HTTPException(status_code=404, detail="Файл не найден на сервере")

    return FileResponse(
        path=file_path,
        filename=data["filename"],
        media_type="application/octet-stream"
    )

if __name__ == "__main__":
    import uvicorn

    if config.ENABLE_SSL:
        if not os.path.exists(config.SSL_CERT_FILE) or not os.path.exists(config.SSL_KEY_FILE):
            logging.error(
                f"❌ ENABLE_SSL=true, но файлы сертификатов не найдены!\n"
                f"Cert: {config.SSL_CERT_FILE}\nKey: {config.SSL_KEY_FILE}"
            )
            sys.exit(1)

        logging.info(f"🔒 SSL включен! Запускаем Worker на порту {config.WORKER_PORT} (HTTPS)... ✨")
        uvicorn.run(
            app,
            host="0.0.0.0",
            port=config.WORKER_PORT,
            ssl_keyfile=config.SSL_KEY_FILE,
            ssl_certfile=config.SSL_CERT_FILE
        )
    else:
        logging.info(f"🔓 SSL выключен. Запускаем Worker на порту {config.WORKER_PORT} (HTTP)...")
        uvicorn.run(app, host="0.0.0.0", port=config.WORKER_PORT)