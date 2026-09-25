import asyncio
import logging
from aiogram import Bot, Dispatcher

import config
from utils import load_plus_ids
from handlers import router

logging.basicConfig(level=logging.INFO)

dp = Dispatcher()
dp.include_router(router)

async def main():
    load_plus_ids()
    if config.BOT_TOKEN == None:
        logging.fatal(" No Bot Token was found. Please add it as BOT_TOKEN=[token] to the dotenv (.env) file.")
        return
    bot = Bot(token=config.BOT_TOKEN)
    print(f"🤖 Легкий Бот @{config.BOT_USERNAME} запущен! ^3^ ~✨")
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())