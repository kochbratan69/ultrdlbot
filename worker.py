import logging
import os
import time
import asyncio
import shutil
import sys
import secrets
import zipfile
import mimetypes
from fastapi import FastAPI, HTTPException, Request, Query, Response
from fastapi.responses import FileResponse, JSONResponse, HTMLResponse
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
    
    # Разрешаем свободный доступ к предпросмотру, скачиванию файла и элементам галереи
    if request.method == "GET" and path != "/" and not path.startswith("/docs") and not path.startswith("/openapi.json"):
        parts = [p for p in path.split("/") if p]
        if len(parts) == 1 or (len(parts) >= 2 and parts[1] in ["file", "raw"]):
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

    # Берём все медиафайлы (исключая технические кэш-файлы)
    files = [
        os.path.join(task_dir, f) for f in os.listdir(task_dir)
        if not f.endswith((".json", ".tmp")) and os.path.isfile(os.path.join(task_dir, f))
    ]

    # Если присутствуют аудио/видео файлы, убираем картинки обложек
    media_files = [f for f in files if f.lower().endswith((".mp4", ".mkv", ".mov", ".webm", ".mp3", ".m4a", ".flac", ".ogg", ".wav"))]
    if media_files:
        files = media_files

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
        # Для каруселей (TikTok, Instagram) упаковываем все фото/видео в ZIP
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

# 🖼️ Роут для отображения отдельных файлов из ZIP-архива (для карусели фото)
@app.get("/{shortcode}/raw/{inner_filename:path}")
async def get_raw_zip_item(shortcode: str, inner_filename: str, k: str = Query(None)):
    if not k:
        raise HTTPException(status_code=403, detail="Доступ запрещен")

    clean_code = shortcode.split("#")[0].strip()
    data = database.get_share_link(clean_code)

    if not data or data["access_key"] != k:
        raise HTTPException(status_code=403, detail="Неверная ссылка или ключ")

    if time.time() > data["expires_at"]:
        raise HTTPException(status_code=410, detail="Ссылка истекла")

    file_path = data["file_path"]
    if not os.path.exists(file_path):
        raise HTTPException(status_code=404, detail="Файл не найден")

    if file_path.endswith(".zip"):
        try:
            with zipfile.ZipFile(file_path, 'r') as zipf:
                if inner_filename not in zipf.namelist():
                    raise HTTPException(status_code=404, detail="Файл в архиве не найден")
                
                file_bytes = zipf.read(inner_filename)
                media_type, _ = mimetypes.guess_type(inner_filename)
                return Response(content=file_bytes, media_type=media_type or "application/octet-stream")
        except zipfile.BadZipFile:
            raise HTTPException(status_code=500, detail="Ошибка чтения архива")
    else:
        raise HTTPException(status_code=400, detail="Файл не является архивом")

# 👁️ Страница предпросмотра файла или всей карусели в браузере
@app.get("/{shortcode}", response_class=HTMLResponse)
async def preview_shared_file(shortcode: str, k: str = Query(None)):
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
    filename = data["filename"]
    ext = os.path.splitext(filename)[1].lower()
    download_url = f"/{clean_code}/file?k={k}"

    player_html = ""
    download_btn_text = "Скачать файл 🚀"

    # Если это ZIP-архив с каруселью картинок/видео
    if ext == ".zip" and os.path.exists(file_path):
        download_btn_text = "Скачать всё (ZIP) 🚀"
        try:
            with zipfile.ZipFile(file_path, 'r') as zipf:
                inner_files = [f for f in zipf.namelist() if not f.startswith("__MACOSX")]
                media_files = [
                    f for f in inner_files 
                    if os.path.splitext(f)[1].lower() in [".jpg", ".jpeg", ".png", ".webp", ".gif", ".mp4", ".mov", ".webm"]
                ]

                if media_files:
                    gallery_items = []
                    for f in media_files:
                        f_ext = os.path.splitext(f)[1].lower()
                        raw_url = f"/{clean_code}/raw/{f}?k={k}"
                        if f_ext in [".mp4", ".mov", ".webm"]:
                            gallery_items.append(f'<video controls src="{raw_url}" style="width:100%; max-height:400px; border-radius:12px; margin-bottom:12px; object-fit:contain;"></video>')
                        else:
                            gallery_items.append(f'<img src="{raw_url}" style="width:100%; max-height:450px; border-radius:12px; margin-bottom:12px; object-fit:contain;" />')
                    
                    player_html = f'<div class="gallery-container" style="max-height:500px; overflow-y:auto; margin:15px 0; padding-right:5px;">{"".join(gallery_items)}</div>'
                else:
                    player_html = f'<div style="font-size:64px; margin:20px 0;">📦</div>'
        except Exception as e:
            player_html = f'<div style="font-size:64px; margin:20px 0;">📦</div>'

    elif ext in [".mp4", ".mov", ".webm", ".mkv"]:
        player_html = f'<video controls autoplay src="{download_url}" style="max-width:100%; max-height:360px; border-radius:12px; margin: 15px 0;"></video>'
    elif ext in [".mp3", ".m4a", ".ogg", ".wav", ".flac"]:
        player_html = f'<audio controls autoplay src="{download_url}" style="width:100%; margin: 25px 0;"></audio>'
    elif ext in [".jpg", ".jpeg", ".png", ".webp", ".gif"]:
        player_html = f'<img src="{download_url}" style="max-width:100%; max-height:360px; border-radius:12px; object-fit:contain; margin: 15px 0;" />'
    else:
        player_html = f'<div style="font-size:64px; margin:20px 0;">📦</div>'

    html_content = f"""
    <!DOCTYPE html>
    <html lang="ru">
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <title>Предпросмотр — {filename}</title>
        <style>
            body {{
                font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif;
                background: #0f172a;
                color: #f8fafc;
                display: flex;
                justify-content: center;
                align-items: center;
                min-height: 100vh;
                margin: 0;
                padding: 20px;
                box-sizing: border-box;
            }}
            .card {{
                background: #1e293b;
                padding: 28px;
                border-radius: 20px;
                box-shadow: 0 20px 25px -5px rgba(0, 0, 0, 0.5);
                max-width: 480px;
                width: 100%;
                text-align: center;
            }}
            .filename {{
                font-size: 15px;
                font-weight: 600;
                word-break: break-all;
                color: #cbd5e1;
            }}
            .gallery-container::-webkit-scrollbar {{
                width: 6px;
            }}
            .gallery-container::-webkit-scrollbar-thumb {{
                background: #475569;
                border-radius: 4px;
            }}
            .btn-download {{
                display: block;
                width: 100%;
                padding: 14px 0;
                background: linear-gradient(135deg, #6366f1 0%, #a855f7 100%);
                color: white;
                text-decoration: none;
                font-weight: bold;
                border-radius: 12px;
                font-size: 16px;
                transition: transform 0.2s, opacity 0.2s;
                box-sizing: border-box;
            }}
            .btn-download:hover {{
                opacity: 0.9;
                transform: translateY(-2px);
            }}
            .footer {{
                margin-top: 16px;
                font-size: 12px;
                color: #64748b;
            }}
        </style>
    </head>
    <body>
        <div class="card">
            <div class="filename">📁 {filename}</div>
            {player_html}
            <a href="{download_url}" class="btn-download" download>{download_btn_text}</a>
            <div class="footer">Ссылка действительна 1 час</div>
        </div>
    </body>
    </html>
    """
    return HTMLResponse(content=html_content)

# 📥 Прямое скачивание файла/архива
@app.get("/{shortcode}/file")
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