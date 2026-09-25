import asyncio
import logging
from aiogram import Bot, Dispatcher

import config
from utils import load_plus_ids
from updater import check_and_update_binaries
from handlers import router

logging.basicConfig(level=logging.INFO)

dp = Dispatcher()
dp.include_router(router)

async def main():
    # 1. Проверяем и скачиваем утилиты (yt-dlp, gallery-dl, ffmpeg) в фоновом потоке
    print("🔍 Проверяем бинарники при старте... ✨")
    await asyncio.to_thread(check_and_update_binaries)

    # 2. Загружаем Plus-ID
    load_plus_ids()

    # 3. Запуск бота
    bot = Bot(token=config.BOT_TOKEN)
    print(f"бот @{config.BOT_USERNAME} запущен ^3^ ~✨")
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())