import asyncio
import logging
import os
import re
import base64
from io import BytesIO
from typing import List, Dict, Optional

from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from dotenv import load_dotenv
import aiosqlite
import httpx

load_dotenv()
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY")

if not TELEGRAM_BOT_TOKEN or not OPENROUTER_API_KEY:
    raise ValueError("Добавь TELEGRAM_BOT_TOKEN и OPENROUTER_API_KEY в .env")

DB_PATH = "secretary_bot.db"
OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"
MODEL = "google/gemini-3.5-flash"

bot = Bot(token=TELEGRAM_BOT_TOKEN)
dp = Dispatcher(storage=MemoryStorage())

class UserStates(StatesGroup):
    waiting_for_key = State()
    waiting_for_task_text = State()

# Load environment
load_dotenv()

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
if not TELEGRAM_BOT_TOKEN:
    raise ValueError("TELEGRAM_BOT_TOKEN not found in .env file!")

bot = Bot(token=TELEGRAM_BOT_TOKEN)
dp = Dispatcher(storage=MemoryStorage())

# States for FSM (e.g. waiting for API key)
class UserStates(StatesGroup):
    waiting_for_api_key = State()
    waiting_for_task_text = State()


# ==================== HANDLERS ====================

@dp.message(CommandStart())
async def cmd_start(message: types.Message, state: FSMContext):
    user_id = message.from_user.id
    username = message.from_user.username
    first_name = message.from_user.first_name
    
    await get_or_create_user(user_id, username, first_name)
    
    key = await get_openrouter_key(user_id)
    
    if not key:
        await message.answer(
            "👋 Привет! Я — **Клод Секретарь**, твой персональный ИИ-помощник на базе Claude.\n\n"
            "Чтобы начать, мне нужен твой **OpenRouter API ключ** (он используется для доступа к Claude).\n\n"
            "1. Перейди на https://openrouter.ai/keys\n"
            "2. Создай ключ (бесплатно при регистрации)\n"
            "3. Отправь мне ключ в следующем сообщении.\n\n"
            "🔒 Ключ хранится только у тебя в базе данных этого бота."
        )
        await state.set_state(UserStates.waiting_for_api_key)
    else:
        await message.answer(
            f"С возвращением, {first_name or 'друг'}! 👋\n\n"
            "Я готов помогать. Просто пиши мне как обычному секретарю.\n\n"
            "Доступные команды:\n"
            "/tasks — список задач\n"
            "/addtask — добавить задачу\n"
            "/help — помощь\n\n"
            "Что нужно сделать сегодня?"
        )


@dp.message(UserStates.waiting_for_api_key)
async def process_api_key(message: types.Message, state: FSMContext):
    user_id = message.from_user.id
    key = message.text.strip()
    
    if not key.startswith("sk-or-") and not key.startswith("sk-"):
        await message.answer("❌ Похоже, это не OpenRouter ключ. Ключи обычно начинаются с `sk-or-`.\nПопробуй ещё раз.")
        return
    
    await set_openrouter_key(user_id, key)
    await state.clear()
    
    await message.answer(
        "✅ Отлично! API ключ сохранён.\n\n"
        "Теперь я — твой полноценный ИИ-секретарь.\n"
        "Пиши мне что угодно: задачи, вопросы, планы, мысли.\n\n"
        "Я буду помнить всё и помогать организовывать жизнь.\n\n"
        "Попробуй написать что-нибудь или используй /tasks"
    )


@dp.message(Command("help"))
async def cmd_help(message: types.Message):
    await message.answer(
        "📖 **Помощь — Клод Секретарь**\n\n"
        "Я — твой личный помощник на базе Claude 3.5 Sonnet.\n\n"
        "**Основные команды:**\n"
        "• `/start` — перезапуск\n"
        "• `/tasks` или `/todo` — показать активные задачи\n"
        "• `/addtask Текст задачи` — добавить новую задачу\n"
        "• `/completetask ID` — отметить задачу выполненной\n"
        "• `/deletetask ID` — удалить задачу\n"
        "• `/setkey` — изменить OpenRouter ключ\n"
        "• `/clearhistory` — очистить память разговоров\n"
        "• `/help` — эта справка\n\n"
        "**Как пользоваться:**\n"
        "Просто пиши мне обычными сообщениями. Я понимаю контекст, "
        "помню предыдущие разговоры и твои задачи.\n\n"
        "Примеры:\n"
        "• «Добавь задачу купить молоко»\n"
        "• «Что у меня на сегодня?»\n"
        "• «Напомни про проект X»\n"
        "• «Суммируй наш последний разговор»"
    )


@dp.message(Command("setkey"))
async def cmd_setkey(message: types.Message, state: FSMContext):
    await message.answer("Отправь новый OpenRouter API ключ:")
    await state.set_state(UserStates.waiting_for_api_key)


@dp.message(Command(commands=["tasks", "todo"]))
async def cmd_tasks(message: types.Message):
    user_id = message.from_user.id
    tasks = await get_user_tasks(user_id, "pending")
    
    if not tasks:
        await message.answer("📭 У тебя пока нет активных задач.\n\nНапиши мне, что нужно сделать, или используй /addtask")
        return
    
    text = "📋 **Твои текущие задачи:**\n\n"
    for task in tasks:
        due = f" (до {task['due_date']})" if task.get('due_date') else ""
        text += f"**#{task['id']}** — {task['text']}{due}\n"
    
    text += "\nИспользуй `/completetask ID` или `/deletetask ID`"
    await message.answer(text, parse_mode="Markdown")


@dp.message(Command("addtask"))
async def cmd_addtask(message: types.Message, state: FSMContext):
    # If command has arguments
    args = message.text.split(maxsplit=1)
    if len(args) > 1:
        task_text = args[1].strip()
        if task_text:
            task_id = await add_task(message.from_user.id, task_text)
            await message.answer(f"✅ Задача #{task_id} добавлена: «{task_text}»")
            await state.clear()
            return
    
    # Otherwise ask for text via state
    await message.answer("Какую задачу добавить? Напиши текст задачи:")
    await state.set_state(UserStates.waiting_for_task_text)


@dp.message(UserStates.waiting_for_task_text)
async def process_new_task(message: types.Message, state: FSMContext):
    task_text = message.text.strip()
    if task_text:
        task_id = await add_task(message.from_user.id, task_text)
        await message.answer(f"✅ Задача #{task_id} добавлена: «{task_text}»")
    else:
        await message.answer("Текст задачи не может быть пустым.")
    await state.clear()


@dp.message(F.text.startswith("/completetask"))
async def cmd_complete_task(message: types.Message):
    try:
        task_id = int(message.text.split()[1])
    except (IndexError, ValueError):
        await message.answer("Используй формат: `/completetask 5` (ID задачи)")
        return
    
    success = await update_task_status(task_id, message.from_user.id, "completed")
    if success:
        await message.answer(f"✅ Задача #{task_id} отмечена как выполненная!")
    else:
        await message.answer("❌ Задача не найдена или уже завершена.")


@dp.message(F.text.startswith("/deletetask"))
async def cmd_delete_task(message: types.Message):
    try:
        task_id = int(message.text.split()[1])
    except (IndexError, ValueError):
        await message.answer("Используй формат: `/deletetask 5`")
        return
    
    success = await delete_task(task_id, message.from_user.id)
    if success:
        await message.answer(f"🗑 Задача #{task_id} удалена.")
    else:
        await message.answer("❌ Задача не найдена.")


@dp.message(Command("clearhistory"))
async def cmd_clear_history(message: types.Message):
    await clear_conversation_history(message.from_user.id)
    await message.answer("🧹 История разговоров очищена. Я начну с чистого листа.")


# ==================== MAIN CHAT HANDLER ====================

@dp.message(F.text & ~F.text.startswith("/"))
async def handle_chat(message: types.Message):
    user_id = message.from_user.id
    user_name = message.from_user.first_name or message.from_user.username or "Пользователь"
    
    # Check if user has API key
    api_key = await get_openrouter_key(user_id)
    if not api_key:
        await message.answer("Сначала настрой API ключ командой /start или /setkey")
        return
    
    # Show typing
    await bot.send_chat_action(chat_id=message.chat.id, action="typing")
    
    # Get current tasks
    tasks_text = await get_all_pending_tasks_text(user_id)
    
    # Get conversation history
    history = await get_conversation_history(user_id, limit=25)
    
    # Save user message to history
    await add_message_to_history(user_id, "user", message.text)
    
    # Get response from Claude
    response = await get_claude_response(
        api_key=api_key,
        user_name=user_name,
        user_message=message.text,
        history=history,
        tasks_text=tasks_text
    )
    
    # === АВТО-ЗАДАЧИ: парсим теги [ADD_TASK]...[/ADD_TASK] ===
    import re
    task_pattern = r'\[ADD_TASK\](.*?)\[/ADD_TASK\]'
    tasks_to_add = re.findall(task_pattern, response, re.DOTALL)
    
    added_tasks = []
    for task_text in tasks_to_add:
        task_text = task_text.strip()
        if task_text:
            task_id = await add_task(user_id, task_text)
            added_tasks.append(f"#{task_id} — {task_text}")
    
    # Убираем теги из ответа, который увидит пользователь
    clean_response = re.sub(task_pattern, '', response).strip()
    
    if added_tasks:
        clean_response += "\n\n✅ **Автоматически добавил задачи:**\n" + "\n".join(added_tasks)
    
    # Save assistant response (чистый)
    await add_message_to_history(user_id, "assistant", clean_response)
    
    # Send response
    if len(clean_response) > 4000:
        for i in range(0, len(clean_response), 4000):
            await message.answer(clean_response[i:i+4000])
    else:
        await message.answer(clean_response, parse_mode="Markdown")


# ==================== MEDIA HANDLERS (фото, видео, голос) ====================

async def download_photo_as_base64(message: types.Message) -> Optional[str]:
    """Download the largest photo and return as base64 string."""
    if not message.photo:
        return None
    try:
        # Get the highest resolution photo
        photo = message.photo[-1]
        file_info = await bot.get_file(photo.file_id)
        file_path = file_info.file_path
        
        # Download to bytes
        file_bytes = BytesIO()
        await bot.download_file(file_path, destination=file_bytes)
        file_bytes.seek(0)
        
        # Encode to base64
        image_base64 = base64.b64encode(file_bytes.read()).decode('utf-8')
        return image_base64
    except Exception as e:
        logger.error(f"Error downloading photo: {e}")
        return None


@dp.message(F.photo)
async def handle_photo(message: types.Message):
    user_id = message.from_user.id
    user_name = message.from_user.first_name or message.from_user.username or "Пользователь"
    
    api_key = await get_openrouter_key(user_id)
    if not api_key:
        await message.answer("Сначала настрой API ключ /start")
        return
    
    await bot.send_chat_action(chat_id=message.chat.id, action="typing")
    
    # Download image
    image_base64 = await download_photo_as_base64(message)
    if not image_base64:
        await message.answer("Не удалось скачать фото. Попробуй ещё раз.")
        return
    
    tasks_text = await get_all_pending_tasks_text(user_id)
    history = await get_conversation_history(user_id, limit=20)
    
    # Caption or default prompt
    prompt_text = message.caption or "Проанализируй это фото подробно в контексте моих задач и разговоров."
    
    # Save info about photo to history (text description)
    await add_message_to_history(user_id, "user", f"[Пользователь отправил фото] {prompt_text}")
    
    # Call vision
    response = await get_claude_vision_response(
        api_key=api_key,
        user_name=user_name,
        prompt_text=prompt_text,
        image_base64=image_base64,
        tasks_text=tasks_text,
        history=history
    )
    
    # Save response
    await add_message_to_history(user_id, "assistant", response)
    
    await message.answer(response, parse_mode="Markdown")


@dp.message(F.video)
async def handle_video(message: types.Message):
    await message.answer(
        "🎥 Я пока не анализирую видео напрямую (Claude пока не поддерживает видео).\n\n"
        "Но ты можешь:\n"
        "• Прислать **ключевой кадр** (скриншот) — я проанализирую его как фото\n"
        "• Описать видео текстом\n"
        "• Прислать голосовое сообщение с описанием"
    )


@dp.message(F.voice | F.audio)
async def handle_voice(message: types.Message):
    await message.answer(
        "🎙 Я пока не транскрибирую голосовые сообщения автоматически.\n\n"
        "Просто напиши текстом, что хотел сказать, или пришли **текстовое описание** + фото/видео.\n"
        "В будущем добавлю поддержку Whisper для транскрипции."
    )


@dp.message(F.document)
async def handle_document(message: types.Message):
    await message.answer(
        "📄 Документы я пока анализирую ограниченно.\n"
        "Если это PDF или текстовый файл — пришли его как фото страниц или опиши текстом.\n"
        "Для таблиц/Excel лучше пришли скрины или текст."
    )


# ==================== MAIN ====================

async def main():
    await init_db()
    logger.info("Database initialized")
    
    # Start polling
    logger.info("Starting Claude Secretary Bot...")
    await dp.start_polling(bot, allowed_updates=dp.resolve_used_update_types())


if __name__ == "__main__":
    asyncio.run(main())