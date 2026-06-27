import asyncio
import os
import base64
from datetime import datetime, date

from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import CommandStart, Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from dotenv import load_dotenv
import aiosqlite
import httpx

load_dotenv()

TELEGRAM_BOT_TOKEN = os.getenv(TELEGRAM_BOT_TOKEN)
OPENROUTER_API_KEY = os.getenv(OPENROUTER_API_KEY)

bot = Bot(token=TELEGRAM_BOT_TOKEN)
dp = Dispatcher()

MODEL = googlegemini-3.5-flash
OPENROUTER_URL = httpsopenrouter.aiapiv1chatcompletions
DB_PATH = secretary_bot.db
DAILY_LIMIT = 40   # ← можешь поменять на любое число

class States(StatesGroup)
    waiting_key = State()

async def init_db()
    async with aiosqlite.connect(DB_PATH) as db
        await db.execute(CREATE TABLE IF NOT EXISTS users (
            user_id INTEGER PRIMARY KEY,
            api_key TEXT
        ))
        await db.execute(CREATE TABLE IF NOT EXISTS tasks (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            text TEXT,
            status TEXT DEFAULT 'pending'
        ))
        await db.execute(CREATE TABLE IF NOT EXISTS daily_usage (
            user_id INTEGER,
            usage_date DATE,
            count INTEGER DEFAULT 0,
            PRIMARY KEY (user_id, usage_date)
        ))
        await db.commit()

async def get_key(user_id)
    async with aiosqlite.connect(DB_PATH) as db
        cur = await db.execute(SELECT api_key FROM users WHERE user_id = , (user_id,))
        row = await cur.fetchone()
        return row[0] if row else None

async def save_key(user_id, key)
    async with aiosqlite.connect(DB_PATH) as db
        await db.execute(INSERT OR REPLACE INTO users (user_id, api_key) VALUES (, ), (user_id, key))
        await db.commit()

async def get_today_usage(user_id)
    today = date.today().isoformat()
    async with aiosqlite.connect(DB_PATH) as db
        cur = await db.execute(
            SELECT count FROM daily_usage WHERE user_id =  AND usage_date = ,
            (user_id, today)
        )
        row = await cur.fetchone()
        return row[0] if row else 0

async def increment_usage(user_id)
    today = date.today().isoformat()
    async with aiosqlite.connect(DB_PATH) as db
        await db.execute(
            INSERT INTO daily_usage (user_id, usage_date, count)
            VALUES (, , 1)
            ON CONFLICT(user_id, usage_date) DO UPDATE SET count = count + 1
        , (user_id, today))
        await db.commit()

async def check_and_increment(user_id)
    usage = await get_today_usage(user_id)
    if usage = DAILY_LIMIT
        return False
    await increment_usage(user_id)
    return True

@dp.message(CommandStart())
async def start(message types.Message, state FSMContext)
    key = await get_key(message.from_user.id)
    if not key
        await message.answer(Пришли свой OpenRouter ключ)
        await state.set_state(States.waiting_key)
    else
        await message.answer(Готов работать! Пиши или отправляй фото.)

@dp.message(States.waiting_key)
async def savekey(message types.Message, state FSMContext)
    await save_key(message.from_user.id, message.text.strip())
    await state.clear()
    await message.answer(Ключ сохранён!)

@dp.message(F.photo)
async def handle_photo(message types.Message)
    user_id = message.from_user.id
    if not await check_and_increment(user_id)
        return await message.answer(fДневной лимит ({DAILY_LIMIT} запросов) исчерпан. Попробуй завтра.)

    key = await get_key(user_id)
    if not key
        return await message.answer(Сначала пришли ключ через start)

    # Скачиваем фото
    photo = message.photo[-1]
    file = await bot.get_file(photo.file_id)
    file_bytes = await bot.download_file(file.file_path)

    # Конвертируем в base64
    image_base64 = base64.b64encode(file_bytes.read()).decode(utf-8)

    prompt = message.caption or Что ты видишь на этом фото Опиши подробно.

    content = [
        {type text, text prompt},
        {type image_url, image_url {url fdataimagejpeg;base64,{image_base64}}}
    ]

    messages = [{role user, content content}]
    headers = {Authorization fBearer {key}, Content-Type applicationjson}
    payload = {model MODEL, messages messages, max_tokens 4000}

    async with httpx.AsyncClient(timeout=120) as client
        r = await client.post(OPENROUTER_URL, headers=headers, json=payload)
        answer = r.json()[choices][0][message][content]

    await message.answer(answer)

@dp.message(F.text & ~F.text.startswith())
async def chat(message types.Message)
    user_id = message.from_user.id
    if not await check_and_increment(user_id)
        return await message.answer(fДневной лимит ({DAILY_LIMIT} запросов) исчерпан. Попробуй завтра.)

    key = await get_key(user_id)
    if not key
        return await message.answer(Сначала пришли ключ через start)

    messages = [{role user, content message.text}]
    headers = {Authorization fBearer {key}, Content-Type applicationjson}
    payload = {model MODEL, messages messages, max_tokens 4000}

    async with httpx.AsyncClient(timeout=120) as client
        r = await client.post(OPENROUTER_URL, headers=headers, json=payload)
        answer = r.json()[choices][0][message][content]

    await message.answer(answer)

async def main()
    await init_db()
    print(Бот запущен с vision и дневным лимитом)
    await dp.start_polling(bot)

if __name__ == __main__
    asyncio.run(main())
