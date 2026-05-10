import os
import tempfile
from typing import List, Tuple

import aiohttp
from bs4 import BeautifulSoup
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton, FSInputFile
from dotenv import load_dotenv

load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN")
DEEPSEEK_API_KEY = os.getenv("DEEPSEEK_API_KEY")
DEEPSEEK_API_URL = "https://api.deepseek.com/v1/chat/completions"

if not BOT_TOKEN:
    raise ValueError("BOT_TOKEN не найден в .env файле!")

CARD_TEMPLATE = """
1. Карточка [Название продукта]
Текст карточки: [короткий продающий абзац]

---

### 1. Что мешает [ЦА] сейчас достичь [цели]?

**Внешние факторы**  
- факт1  
- факт2  

**Внутренние факторы**  
- факт1  
- факт2  

---

### 2. Что у нас лучше чем у конкурентов

[Показатель 1] [значение]  
[Показатель 2] [значение]  

**Вишенка на торте**  
[уникальное преимущество]

---

### 3. Наши Инструменты для решения ключевых задач [роль]:

**[Задача 1]**  
- инструмент 1  
- инструмент 2  

---

С нами комфортно работать!  
- принцип 1  
- принцип 2  
"""

class ProductCardState(StatesGroup):
    waiting_for_url = State()
    card_review = State()
    waiting_for_edit = State()

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()

async def fetch_html(url: str) -> str:
    async with aiohttp.ClientSession() as session:
        async with session.get(url, timeout=15) as resp:
            return await resp.text()

def parse_into_blocks(html: str) -> List[Tuple[str, List[str]]]:
    soup = BeautifulSoup(html, 'html.parser')
    for script in soup(["script", "style", "nav", "footer", "header"]):
        script.decompose()
    
    blocks = []
    current_title = "Общее описание"
    current_texts = []
    
    for element in soup.find_all(['h1', 'h2', 'h3', 'p', 'ul', 'ol']):
        if element.name in ['h1', 'h2', 'h3']:
            if current_texts:
                blocks.append((current_title, current_texts))
                current_texts = []
            current_title = element.get_text(strip=True)
        elif element.name == 'p':
            text = element.get_text(strip=True)
            if len(text) > 20:
                current_texts.append(text)
        elif element.name in ['ul', 'ol']:
            items = [li.get_text(strip=True) for li in element.find_all('li')]
            current_texts.extend(items)
    
    if current_texts:
        blocks.append((current_title, current_texts))
    
    return blocks if blocks else [("Общий текст", [soup.get_text(separator="\n", strip=True)])]

def save_text_to_txt(content: str) -> str:
    fd, path = tempfile.mkstemp(suffix=".txt", text=True)
    with os.fdopen(fd, 'w', encoding='utf-8') as f:
        f.write(content)
    return path

async def call_llm(prompt: str) -> str:
    headers = {
        "Authorization": f"Bearer {DEEPSEEK_API_KEY}",
        "Content-Type": "application/json"
    }
    payload = {
        "model": "deepseek-chat",
        "messages": [
            {"role": "system", "content": "Ты эксперт по B2B-маркетингу."},
            {"role": "user", "content": prompt}
        ],
        "temperature": 0.5,
        "max_tokens": 2000
    }
    async with aiohttp.ClientSession() as session:
        async with session.post(DEEPSEEK_API_URL, json=payload, headers=headers) as resp:
            data = await resp.json()
            return data["choices"][0]["message"]["content"]

async def generate_card_from_text(parsed_blocks: List[Tuple[str, List[str]]]) -> str:
    raw_text = ""
    for title, texts in parsed_blocks:
        raw_text += f"\n=== {title} ===\n" + "\n".join(texts) + "\n"
    
    prompt = f"""
    Используя шаблон, создай карточку продукта на основе текста.

    ШАБЛОН:
    {CARD_TEMPLATE}

    ТЕКСТ О ПРОДУКТЕ:
    {raw_text}

    Заполни все блоки. Если данных нет, напиши "Информация отсутствует".
    """
    return await call_llm(prompt)

@dp.message(Command("start"))
async def cmd_start(message: types.Message, state: FSMContext):
    await state.clear()
    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="📦 Создать карточку продукта", callback_data="create_card")]
        ]
    )
    await message.answer("Привет! Нажми на кнопку, чтобы начать.", reply_markup=keyboard)

@dp.callback_query(F.data == "create_card")
async def ask_url(callback: types.CallbackQuery, state: FSMContext):
    await callback.message.edit_text("Отправьте URL страницы с описанием продукта:")
    await state.set_state(ProductCardState.waiting_for_url)
    await callback.answer()

@dp.message(ProductCardState.waiting_for_url)
async def process_url(message: types.Message, state: FSMContext):
    url = message.text.strip()
    if not url.startswith("http"):
        await message.answer("❌ Введите корректный URL")
        return
    
    processing_msg = await message.answer("🔍 Парсинг страницы...")
    
    try:
        html = await fetch_html(url)
        blocks = parse_into_blocks(html)
        if not blocks:
            await processing_msg.edit_text("Не удалось извлечь текст.")
            return
        
        await processing_msg.edit_text("🧠 Генерация карточки (1-2 минуты)...")
        card_text = await generate_card_from_text(blocks)
        await state.update_data(generated_card=card_text)
        
        if len(card_text) > 4000:
            card_text = card_text[:4000] + "\n\n...(текст обрезан)"
        
        keyboard = InlineKeyboardMarkup(
            inline_keyboard=[
                [InlineKeyboardButton(text="✅ Всё хорошо", callback_data="approve_card")],
                [InlineKeyboardButton(text="✏️ Внести правки", callback_data="edit_card")]
            ]
        )
        
        await processing_msg.delete()
        await message.answer(f"✨ Карточка:\n\n{card_text}\n\nВсё устраивает?", reply_markup=keyboard)
        await state.set_state(ProductCardState.card_review)
        
    except Exception as e:
        await processing_msg.edit_text(f"❌ Ошибка: {str(e)}")

@dp.callback_query(F.data == "approve_card", ProductCardState.card_review)
async def approve_card(callback: types.CallbackQuery, state: FSMContext):
    data = await state.get_data()
    card_text = data["generated_card"]
    txt_path = save_text_to_txt(card_text)
    document = FSInputFile(txt_path, filename="product_card.txt")
    await callback.message.answer_document(document, caption="✅ Карточка сохранена")
    await callback.message.answer("Для новой карточки нажмите /start")
    await state.clear()
    await callback.answer()

@dp.callback_query(F.data == "edit_card", ProductCardState.card_review)
async def request_edit(callback: types.CallbackQuery, state: FSMContext):
    await callback.message.answer("✏️ Отправьте исправленный текст карточки:")
    await state.set_state(ProductCardState.waiting_for_edit)
    await callback.answer()

@dp.message(ProductCardState.waiting_for_edit)
async def apply_edit(message: types.Message, state: FSMContext):
    user_text = message.text
    data = await state.get_data()
    original = data["generated_card"]
    
    await message.answer("🔄 Применяю правки...")
    
    try:
        prompt = f"Верни исправленный вариант карточки. Оригинал: {original}. Текст пользователя: {user_text}"
        final = await call_llm(prompt)
        await state.update_data(generated_card=final)
        
        keyboard = InlineKeyboardMarkup(
            inline_keyboard=[
                [InlineKeyboardButton(text="✅ Всё хорошо", callback_data="approve_card")],
                [InlineKeyboardButton(text="✏️ Снова править", callback_data="edit_card")]
            ]
        )
        await message.answer(f"✨ Исправленная карточка:\n\n{final}\n\nТеперь всё подходит?", reply_markup=keyboard)
        await state.set_state(ProductCardState.card_review)
    except Exception as e:
        await message.answer(f"❌ Ошибка: {e}")

async def main():
    print("Бот запущен")
    await dp.start_polling(bot)

if __name__ == "__main__":
    import asyncio
    asyncio.run(main())

