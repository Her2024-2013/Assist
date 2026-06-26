import asyncio
import os
import re
import base64
from io import BytesIO

from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import CommandStart, Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from dotenv import load_dotenv
import aiosqlite
import httpx

load_dotenv()

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY")

bot = Bot(token=TELEGRAM_BOT_TOKEN)
dp = Dispatcher()

MODEL = "google/gemini-3.5-flash"
OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"
DB_PATH = "secretary_bot.db"

class States(StatesGroup):
    waiting_key = State()

async def init_db():
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("""CREATE TABLE IF NOT EXISTS users (
            user_id INTEGER PRIMARY KEY,
            api_key TEXT
        )""")
        await db.execute("""CREATE TABLE IF NOT EXISTS tasks (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            text TEXT,
            status TEXT DEFAULT 'pending'
        )""")
        await db.execute("""CREATE TABLE IF NOT EXISTS messages (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            role TEXT,
            content TEXT
        )""")
        await db.commit()

async def get_key(user_id):
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute("SELECT api_key FROM users WHERE user_id = ?", (user_id,))
        row = await cur.fetchone()
        return row[0] if row else None

async def save_key(user_id, key):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "INSERT OR REPLACE INTO users (user_id, api_key) VALUES (?, ?)",
            (user_id, key)
        )
        await db.commit()

@dp.message(CommandStart())
async def start(message: types.Message, state: FSMContext):
    key = await get_key(message.from_user.id)
    if not key:
        await message.answer("Пришли свой OpenRouter ключ")
        await state.set_state(States.waiting_key)
    else:
        await message.answer("Готов работать! Пиши или отправляй фото.")

@dp.message(States.waiting_key)
async def savekey(message: types.Message, state: FSMContext):
    await save_key(message.from_user.id, message.text.strip())
    await state.clear()
    await message.answer("Ключ сохранён! Теперь можешь писать.")

@dp.message(F.text & ~F.text.startswith("/"))
async def chat(message: types.Message):
    key = await get_key(message.from_user.id)
    if not key:
        await message.answer("Сначала пришли ключ через /start")
        return

    messages = [{"role": "user", "content": message.text}]
    headers = {"Authorization": f"Bearer {key}", "Content-Type": "application/json"}
    payload = {"model": MODEL, "messages": messages, "max_tokens": 4000}

    async with httpx.AsyncClient(timeout=120) as client:
        r = await client.post(OPENROUTER_URL, headers=headers, json=payload)
        answer = r.json()["choices"][0]["message"]["content"]

    await message.answer(answer)

async def main():
    await init_db()
    print("Бот запущен")
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
