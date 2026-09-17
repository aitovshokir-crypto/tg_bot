import asyncio
import logging
import aiosqlite
import os
from aiohttp import web
from aiogram import Bot, Dispatcher, F, types
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

# --- SOZLAMALAR (TUZATILGAN QISM) ---
BOT_TOKEN = os.getenv("BOT_TOKEN", "8822913008:AAEQRM4QLiBXOzEV5qj9nt3NAp1tdMrpAxs")
ADMIN_ID = int(os.getenv("ADMIN_ID", "6052580480"))
CHANNEL_ID = int(os.getenv("CHANNEL_ID", "-1003724147872"))

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher(storage=MemoryStorage())

# --- FSM (Holatlar) ---
class Form(StatesGroup):
    text = State()
    photo = State()
    video = State()

# --- BAZA BILAN ISHLASH ---
async def init_db():
    async with aiosqlite.connect("bot_data.db") as db:
        await db.execute("""
            CREATE TABLE IF NOT EXISTS template (
                id INTEGER PRIMARY KEY,
                text TEXT,
                photo_id TEXT,
                video_id TEXT
            )
        """)
        await db.commit()

async def get_template():
    async with aiosqlite.connect("bot_data.db") as db:
        async with db.execute("SELECT text, photo_id, video_id FROM template WHERE id = 1") as cursor:
            row = await cursor.fetchone()
            if row and row[0] and row[1] and row[2]:
                return row
            return None, None, None

# --- TUGMALAR ---
def get_main_keyboard():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="⚙️ Shablonni sozlash", callback_data="setup_template")],
        [InlineKeyboardButton(text="👁 Shablonni ko'rish", callback_data="view_template")],
        [InlineKeyboardButton(text="🚀 Kanalga post qilish", callback_data="publish_post")]
    ])

# --- HANDLERLAR ---
@dp.message(Command("start"))
async def cmd_start(message: types.Message):
    if message.from_user.id != ADMIN_ID:
        return
    await message.answer("Boshqaruv paneli:", reply_markup=get_main_keyboard())

@dp.callback_query(F.data == "setup_template")
async def start_setup(call: types.CallbackQuery, state: FSMContext):
    await call.message.answer("1. Shablon uchun matnni yuboring:")
    await state.set_state(Form.text)
    await call.answer()

@dp.message(Form.text)
async def process_text(message: types.Message, state: FSMContext):
    text_content = message.text or message.caption
    if not text_content:
        await message.answer("Iltimos, matn yuboring!")
        return
    
    await state.update_data(text=text_content)
    await message.answer("2. Shablon uchun 1 ta rasm yuboring:")
    await state.set_state(Form.photo)

@dp.message(Form.photo)
async def process_photo(message: types.Message, state: FSMContext):
    photo_id = message.photo[-1].file_id
    await state.update_data(photo_id=photo_id)
    await message.answer("3. Shablon uchun 1 ta video yuboring:")
    await state.set_state(Form.video)

@dp.message(Form.video, F.video | F.animation | F.document)
async def process_video(message: types.Message, state: FSMContext):
    if message.video:
        video_id = message.video.file_id
    elif message.animation:
        video_id = message.animation.file_id
    elif message.document:
        video_id = message.document.file_id
    else:
        await message.answer("⚠️ Video topilmadi. Iltimos, video yuboring!")
        return

    data = await state.get_data()
    
    async with aiosqlite.connect("bot_data.db") as db:
        await db.execute(
            "INSERT OR REPLACE INTO template (id, text, photo_id, video_id) VALUES (1, ?, ?, ?)",
            (data.get('text'), data.get('photo_id'), video_id)
        )
        await db.commit()
    
    await state.clear()
    await message.answer("✅ Shablon muvaffaqiyatli saqlandi!", reply_markup=get_main_keyboard())

@dp.callback_query(F.data == "view_template")
async def view_template(call: types.CallbackQuery):
    text, photo_id, video_id = await get_template()
    if not text:
        await call.message.answer("Shablon hali yaratilmagan yoki to'liq saqlanmagan.")
        await call.answer()
        return

    await call.message.answer("📋 **Amaldagi shablon:**")
    await call.message.answer_photo(photo=photo_id, caption="Rasm")
    try:
        await call.message.answer_video(video=video_id, caption="Video")
    except Exception:
        await call.message.answer_document(document=video_id, caption="Video (fayl shaklida)")
    
    await call.message.answer(f"**Matn:**\n{text}")
    await call.answer()

@dp.callback_query(F.data == "publish_post")
async def publish_post(call: types.CallbackQuery):
    text, photo_id, video_id = await get_template()
    if not text or not photo_id or not video_id:
        await call.message.answer("❌ Shablon to'liq emas. Avval sozlamalarni kiriting.")
        await call.answer()
        return

    try:
        media = [
            types.InputMediaPhoto(media=photo_id, caption=text),
            types.InputMediaVideo(media=video_id)
        ]
        await bot.send_media_group(chat_id=CHANNEL_ID, media=media)
        await call.message.answer("🚀 Post kanalga muvaffaqiyatli joylandi!")
    except Exception as e:
        await call.message.answer(f"Xatolik yuz berdi: {e}")
    
    await call.answer()

# --- RENDER UCHUN VEB SERVER (PORT XATOLIGINI OLISH UCHUN) ---
async def handle_ping(request):
    return web.Response(text="Bot muvaffaqiyatli ishlamoqda!")

async def start_web_server():
    app = web.Application()
    app.router.add_get('/', handle_ping)
    runner = web.AppRunner(app)
    await runner.setup()
    
    port = int(os.environ.get("PORT", 10000))
    site = web.TCPSite(runner, '0.0.0.0', port)
    await site.start()

async def main():
    logging.basicConfig(level=logging.INFO)
    await init_db()
    
    # 1. Render talab qiladigan Veb-serverni fonda ishga tushirish
    asyncio.create_task(start_web_server())
    
    # 2. Telegram botni ishga tushirish
    await bot.delete_webhook(drop_pending_updates=True)
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
    
