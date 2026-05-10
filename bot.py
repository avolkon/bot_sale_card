import os
import re
import tempfile
from typing import Dict, Any, List, Tuple

import aiohttp
import requests
from bs4 import BeautifulSoup
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton, FSInputFile
from aiogram.utils.markdown import hbold
from dotenv import load_dotenv

# Загружаем переменные окружения из .env
load_dotenv()

# ---------- НАСТРОЙКИ ----------
BOT_TOKEN = os.getenv("BOT_TOKEN")
DEEPSEEK_API_KEY = os.getenv("DEEPSEEK_API_KEY")
DEEPSEEK_API_URL = "https://api.deepseek.com/v1/chat/completions"
USE_OPENROUTER = os.getenv("USE_OPENROUTER", "False").lower() == "true"
OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY")
OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"

# Проверка наличия токена
if not BOT_TOKEN:
    raise ValueError("BOT_TOKEN не найден в .env файле!")


# Шаблон структуры карточки
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

**[Задача 2]**  
- ...

---

С нами комфортно работать!  
- принцип 1  
- принцип 2  
"""

# ---------- СОСТОЯНИЯ FSM ----------
class ProductCardState(StatesGroup):
    waiting_for_url = State()
    card_review = State()
    waiting_for_edit = State()

# ---------- ИНИЦИАЛИЗАЦИЯ ----------
bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()


