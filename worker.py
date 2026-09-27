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

# 📌 Кэш активных ссылок: cache_id -> {"shortcode": str, "key": str, "expires_at": int}
ACTIVE_SHARES: dict[str, dict] = {}

def load_preview_html(filename: str, player_html: str, download_url: str, download_btn_text: str, expires_at: int, bot_username: str) -> str:
    base_dir = os.path.dirname(os.path.abspath(sys.executable if getattr(sys, 'frozen', False) else __file__))
    template_path = os.path.join(base_dir, "preview.html")

    meipass_dir = getattr(sys, '_MEIPASS', None)
    if not os.path.exists(template_path) and meipass_dir:
        template_path = os.path.join(meipass_dir, "preview.html")

    content = None
    if os.path.exists(template_path):
        try:
            with open(template_path, "r", encoding="utf-8") as f:
                content = f.read()
        except Exception as e:
            logging.error(f"Ошибка чтения preview.html: {e}")

    if not content:
        content = """<!DOCTYPE html><html><body><pre>error</pre></body></html>"""

    return content.replace("{{filename}}", filename)\
                  .replace("{{player_html}}", player_html)\
                  .replace("{{download_url}}", download_url)\
                  .replace("{{download_btn_text}}", download_btn_text)\
                  .replace("{{expires_at}}", str(expires_at))\
                  .replace("{{bot_username}}", bot_username)

# 🔒 Middleware для проверки Bearer-авторизации
@app.middleware("http")
async def auth_middleware(request: Request, call_next):
    path = request.url.path
    
    # Разрешаем свободный доступ по GET и HEAD к предпросмотру, скачиванию файла, обложкам и элементам галереи
    if request.method in ["GET", "HEAD"] and path != "/" and not path.startswith("/docs") and not path.startswith("/openapi.json"):
        parts = [p for p in path.split("/") if p]
        if len(parts) == 1 or (len(parts) >= 2 and parts[1] in ["file", "raw", "thumb"]):
            return await call_next(request)

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
            # Очищаем устаревшие записи из локального реестра ссылок
            expired_cache_ids = [cid for cid, s in ACTIVE_SHARES.items() if s["expires_at"] <= now]
            for cid in expired_cache_ids:
                ACTIVE_SHARES.pop(cid, None)

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
    now = int(time.time())

    # 1. Проверяем, существует ли уже активная ссылка для этого cache_id (ограничение в 1 ссылку)
    if req.cache_id in ACTIVE_SHARES:
        existing = ACTIVE_SHARES[req.cache_id]
        if existing["expires_at"] > now:
            db_data = database.get_share_link(existing["shortcode"])
            if db_data and os.path.exists(db_data["file_path"]):
                return {"shortcode": existing["shortcode"], "key": existing["key"]}
        ACTIVE_SHARES.pop(req.cache_id, None)

    task_dir = os.path.join(config.DOWNLOAD_DIR, req.cache_id)
    if not os.path.exists(task_dir):
        raise HTTPException(status_code=404, detail="Файлы не найдены или устарели")

    # Берём все медиафайлы
    all_files = [
        os.path.join(task_dir, f) for f in os.listdir(task_dir)
        if not f.endswith((".json", ".tmp")) and os.path.isfile(os.path.join(task_dir, f))
    ]

    has_thumb_final = os.path.exists(os.path.join(task_dir, "thumb_final.jpg"))

    # Исключаем техническую обложку thumb_final.jpg из общего списка медиафайлов
    media_files = [
        f for f in all_files 
        if os.path.basename(f) != "thumb_final.jpg" and f.lower().endswith(
            (".jpg", ".jpeg", ".png", ".webp", ".gif", ".mp4", ".mkv", ".mov", ".webm", ".mp3", ".m4a", ".flac", ".ogg", ".wav")
        )
    ]

    if not media_files:
        raise HTTPException(status_code=404, detail="Медиафайлы не найдены")

    shortcode = secrets.token_hex(3)
    access_key = secrets.token_hex(4)
    expires_at = now + 3600

    audio_files = [f for f in media_files if f.lower().endswith((".mp3", ".m4a", ".flac", ".ogg", ".wav"))]

    # 2. Если есть thumb_final.jpg и аудиофайл — это скачанный ТРЕК (не создаём ZIP!)
    if has_thumb_final and audio_files:
        source_file = audio_files[0]
        ext = os.path.splitext(source_file)[1]
        target_filename = f"{shortcode}{ext}"
        target_path = os.path.join(config.SHARE_DIR, target_filename)
        shutil.copy2(source_file, target_path)
        download_name = os.path.basename(source_file)

        # Копируем обложку для веб-плеера
        shutil.copy2(os.path.join(task_dir, "thumb_final.jpg"), os.path.join(config.SHARE_DIR, f"{shortcode}_thumb.jpg"))

    elif len(media_files) == 1:
        source_file = media_files[0]
        ext = os.path.splitext(source_file)[1]
        target_filename = f"{shortcode}{ext}"
        target_path = os.path.join(config.SHARE_DIR, target_filename)
        shutil.copy2(source_file, target_path)
        download_name = os.path.basename(source_file)

    else:
        # Для нескольких файлов пост-пакета упаковываем в ZIP
        target_filename = f"{shortcode}.zip"
        target_path = os.path.join(config.SHARE_DIR, target_filename)
        with zipfile.ZipFile(target_path, 'w') as zipf:
            for f in media_files:
                zipf.write(f, arcname=os.path.basename(f))
        download_name = f"post_{req.cache_id}.zip"

    database.add_share_link(
        shortcode=shortcode,
        file_path=target_path,
        filename=download_name,
        expires_at=expires_at,
        access_key=access_key
    )

    # Сохраняем ссылку в активном кэше
    ACTIVE_SHARES[req.cache_id] = {
        "shortcode": shortcode,
        "key": access_key,
        "expires_at": expires_at
    }

    return {"shortcode": shortcode, "key": access_key}

# 🖼️ Роут для получения обложки трека
@app.get("/{shortcode}/thumb")
async def get_share_thumb(shortcode: str, k: str = Query(None)):
    if not k:
        raise HTTPException(status_code=403, detail="Доступ запрещен")

    clean_code = shortcode.split("#")[0].strip()
    data = database.get_share_link(clean_code)

    if not data or data["access_key"] != k:
        raise HTTPException(status_code=403, detail="Неверная ссылка или ключ")

    thumb_path = os.path.join(config.SHARE_DIR, f"{clean_code}_thumb.jpg")
    if os.path.exists(thumb_path):
        return FileResponse(thumb_path, media_type="image/jpeg")
    
    raise HTTPException(status_code=404, detail="Обложка не найдена")

# 🖼️ Роут для отображения отдельных файлов из ZIP-архива
@app.api_route("/{shortcode}/raw/{inner_filename:path}", methods=["GET", "HEAD"])
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

# 👁️ Страница предпросмотра
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
    download_btn_text = "скачать файл"

    if ext == ".zip" and os.path.exists(file_path):
        download_btn_text = "скачать всё зипкой"
        try:
            with zipfile.ZipFile(file_path, 'r') as zipf:
                inner_files = [f for f in zipf.namelist() if not f.startswith("__MACOSX")]
                
                visual_files = [
                    f for f in inner_files 
                    if os.path.splitext(f)[1].lower() in [".jpg", ".jpeg", ".png", ".webp", ".gif", ".mp4", ".mov", ".webm"]
                ]
                audio_files = [
                    f for f in inner_files
                    if os.path.splitext(f)[1].lower() in [".mp3", ".m4a", ".ogg", ".wav", ".flac"]
                ]

                visual_html = ""
                audio_html = ""

                if visual_files:
                    items = []
                    for f in visual_files:
                        f_ext = os.path.splitext(f)[1].lower()
                        raw_url = f"/{clean_code}/raw/{f}?k={k}"
                        if f_ext in [".mp4", ".mov", ".webm"]:
                            items.append(f'<video controls src="{raw_url}" style="width:100%; max-height:450px; border-radius:12px; margin-bottom:12px; object-fit:contain;"></video>')
                        else:
                            items.append(f'<img src="{raw_url}" style="width:100%; max-height:450px; border-radius:12px; margin-bottom:12px; object-fit:contain;" />')
                    visual_html = f'<div class="gallery-container" style="max-height:540px; overflow-y:auto; margin:15px 0; padding-right:5px;">{"".join(items)}</div>'

                if audio_files:
                    audio_items = []
                    for f in audio_files:
                        raw_url = f"/{clean_code}/raw/{f}?k={k}"
                        audio_items.append(f'''
                        <div style="background:#230f29; padding:12px 16px; border-radius:14px; margin-top:12px; text-align:left; border: 1px solid #334155;">
                            <div style="font-size:12px; font-weight:600; color:#af94b8; margin-bottom:8px; display:flex; align-items:center; gap:6px;">
                                <span>музыка из поста</span>
                            </div>
                            <audio controls src="{raw_url}" style="width:100%; height:38px;"></audio>
                        </div>
                        ''')
                    audio_html = "".join(audio_items)

                if visual_html or audio_html:
                    player_html = visual_html + audio_html
                else:
                    player_html = f'<div style="font-size:64px; margin:20px 0;">📦</div>'

        except Exception as e:
            player_html = f'<div style="font-size:64px; margin:20px 0;">📦</div>'

    elif ext in [".mp4", ".mov", ".webm", ".mkv"]:
        player_html = f'<video controls autoplay src="{download_url}" style="max-width:100%; max-height:540px; border-radius:12px; margin: 15px 0;"></video>'

    elif ext in [".mp3", ".m4a", ".ogg", ".wav", ".flac"]:
        thumb_file = os.path.join(config.SHARE_DIR, f"{clean_code}_thumb.jpg")
        thumb_html = ""
        if os.path.exists(thumb_file):
            thumb_url = f"/{clean_code}/thumb?k={k}"
            thumb_html = f'<img src="{thumb_url}" style="max-width:280px; max-height:280px; width:100%; border-radius:16px; margin-bottom:15px; object-fit:cover; box-shadow:0 10px 20px rgba(0,0,0,0.5);" /><br>'

        player_html = f'''
        <div style="background:#230f29; padding:16px; border-radius:14px; margin: 15px 0; text-align:center; border: 1px solid #334155;">
            {thumb_html}
            <audio controls autoplay src="{download_url}" style="width:100%; height:40px;"></audio>
        </div>
        '''
        download_btn_text = "скачать трек"

    elif ext in [".jpg", ".jpeg", ".png", ".webp", ".gif"]:
        player_html = f'<img src="{download_url}" style="max-width:100%; max-height:720px; border-radius:12px; object-fit:contain; margin: 15px 0;" />'
    else:
        player_html = f'<div style="font-size:64px; margin:20px 0;">📦</div>'

    html_content = load_preview_html(
        filename=filename,
        player_html=player_html,
        download_url=download_url,
        download_btn_text=download_btn_text,
        expires_at=data["expires_at"],
        bot_username=config.BOT_USERNAME
    )
    return HTMLResponse(content=html_content)

# 📥 Прямое скачивание файла/архива
@app.api_route("/{shortcode}/file", methods=["GET", "HEAD"])
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