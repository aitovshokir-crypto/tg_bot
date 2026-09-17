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

# --- SOZLAMALAR ---
BOT_TOKEN = os.getenv("BOT_TOKEN", "8822913008:AAEQRM4QLiBXOzEV5qj9nt3NAp1tdMrpAxs")
ADMIN_ID = int(os.getenv("ADMIN_ID", "6052580480"))
CHANNEL_ID = int(os.getenv("CHANNEL_ID", "-1003724147872"))

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher(storage=MemoryStorage())

# --- FSM (HOLATLAR) ---
class Form(StatesGroup):
    title = State()
    text = State()
    photo = State()
    video = State()
    forward_post = State()
    edit_text = State()

# --- BAZA BILAN ISHLASH ---
async def init_db():
    async with aiosqlite.connect("bot_data.db") as db:
        await db.execute("""
            CREATE TABLE IF NOT EXISTS templates (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                title TEXT,
                text_html TEXT,
                photo_id TEXT,
                video_id TEXT
            )
        """)
        await db.commit()

async def save_template(title, text_html, photo_id, video_id):
    async with aiosqlite.connect("bot_data.db") as db:
        await db.execute(
            "INSERT INTO templates (title, text_html, photo_id, video_id) VALUES (?, ?, ?, ?)",
            (title, text_html, photo_id, video_id)
        )
        await db.commit()

async def get_all_templates():
    async with aiosqlite.connect("bot_data.db") as db:
        async with db.execute("SELECT id, title FROM templates") as cursor:
            return await cursor.fetchall()

async def get_template_by_id(temp_id):
    async with aiosqlite.connect("bot_data.db") as db:
        async with db.execute("SELECT title, text_html, photo_id, video_id FROM templates WHERE id = ?", (temp_id,)) as cursor:
            return await cursor.fetchone()

async def update_template_text(temp_id, new_text_html):
    async with aiosqlite.connect("bot_data.db") as db:
        await db.execute("UPDATE templates SET text_html = ? WHERE id = ?", (new_text_html, temp_id))
        await db.commit()

async def delete_template(temp_id):
    async with aiosqlite.connect("bot_data.db") as db:
        await db.execute("DELETE FROM templates WHERE id = ?", (temp_id,))
        await db.commit()

# --- TUGMALAR ---
def get_main_keyboard():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="➕ Yangi shablon (Bo'lib-bo'lib)", callback_data="add_step_by_step")],
        [InlineKeyboardButton(text="📥 Tayyor postdan saqlash", callback_data="add_forward")],
        [InlineKeyboardButton(text="📂 Shablonlar bo'limi", callback_data="list_templates")]
    ])

# --- HANDLERLAR ---
@dp.message(Command("start"))
async def cmd_start(message: types.Message):
    if message.from_user.id != ADMIN_ID:
        return
    await message.answer("👋 **Boshqaruv paneliga xush kelibsiz!**\nQuyidagi menyudan kerakli bo'limni tanlang:", reply_markup=get_main_keyboard(), parse_mode="HTML")

# --- 1. BO'LIB-BO'LIB YASASH ---
@dp.callback_query(F.data == "add_step_by_step")
async def start_step_by_step(call: types.CallbackQuery, state: FSMContext):
    await call.message.answer("🏷 **Shablon uchun nom kiriting:** (Masalan: *Aksiya Posti*)", parse_mode="HTML")
    await state.set_state(Form.title)
    await call.answer()

@dp.message(Form.title)
async def process_title(message: types.Message, state: FSMContext):
    await state.update_data(title=message.text)
    await message.answer("📝 **1. Shablon uchun matnni yuboring:**\n(Premium emojilar va formatlashlar saqlanadi)", parse_mode="HTML")
    await state.set_state(Form.text)

@dp.message(Form.text)
async def process_text(message: types.Message, state: FSMContext):
    text_html = message.html_text or message.caption_html
    if not text_html:
        await message.answer("Iltimos, matn yuboring!")
        return
    
    await state.update_data(text_html=text_html)
    await message.answer("🖼 **2. Shablon uchun 1 ta rasm yuboring:**")
    await state.set_state(Form.photo)

@dp.message(Form.photo, F.photo)
async def process_photo(message: types.Message, state: FSMContext):
    photo_id = message.photo[-1].file_id
    await state.update_data(photo_id=photo_id)
    await message.answer("🎥 **3. Shablon uchun 1 ta video yuboring:**")
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
    await save_template(
        title=data.get('title'),
        text_html=data.get('text_html'),
        photo_id=data.get('photo_id'),
        video_id=video_id
    )
    
    await state.clear()
    await message.answer("✅ **Shablon muvaffaqiyatli saqlandi!**", reply_markup=get_main_keyboard(), parse_mode="HTML")

# --- 2. TAYYOR POSTDAN SAQLASH ---
@dp.callback_query(F.data == "add_forward")
async def start_forward_save(call: types.CallbackQuery, state: FSMContext):
    await call.message.answer("📥 **Tayyor post xabarini yuboring yoki forward qiling:**\n(Xabarda rasm, video va matn bo'lishi kerak)", parse_mode="HTML")
    await state.set_state(Form.forward_post)
    await call.answer()

@dp.message(Form.forward_post)
async def process_forward(message: types.Message, state: FSMContext):
    text_html = message.html_text or message.caption_html or "Matn mavjud emas"
    photo_id = message.photo[-1].file_id if message.photo else None
    video_id = message.video.file_id if message.video else None

    if not photo_id or not video_id:
        await message.answer("⚠️ Postda ham rasm, ham video bo'lishi kerak. Iltimos, qaytadan yuboring!")
        return

    title = f"Post ({message.date.strftime('%Y-%m-%d %H:%M')})"
    await save_template(title=title, text_html=text_html, photo_id=photo_id, video_id=video_id)
    await state.clear()
    await message.answer("✅ **Tayyor post shablon sifatida saqlandi!**", reply_markup=get_main_keyboard(), parse_mode="HTML")

# --- 3. SHABLONLAR RO'YXATI VA TAHRIRLASH ---
@dp.callback_query(F.data == "list_templates")
async def list_templates(call: types.CallbackQuery):
    templates = await get_all_templates()
    if not templates:
        await call.message.answer("📂 Hozircha hech qanday shablon yaratilmagan.")
        await call.answer()
        return

    buttons = []
    for temp_id, title in templates:
        buttons.append([InlineKeyboardButton(text=f"📋 {title}", callback_data=f"view_{temp_id}")])
    
    buttons.append([InlineKeyboardButton(text="⬅️ Orqaga", callback_data="back_main")])
    kb = InlineKeyboardMarkup(inline_keyboard=buttons)
    await call.message.answer("📂 **Mavjud shablonlar ro'yxati:**", reply_markup=kb, parse_mode="HTML")
    await call.answer()

@dp.callback_query(F.data.startswith("view_"))
async def view_single_template(call: types.CallbackQuery):
    temp_id = int(call.data.split("_")[1])
    template = await get_template_by_id(temp_id)
    
    if not template:
        await call.message.answer("❌ Shablon topilmadi.")
        await call.answer()
        return

    title, text_html, photo_id, video_id = template
    await call.message.answer(f"📋 **Shablon:** {title}\n\n👇 **Ko'rinishi:**", parse_mode="HTML")

    media = [
        types.InputMediaPhoto(media=photo_id, caption=text_html, parse_mode="HTML"),
        types.InputMediaVideo(media=video_id)
    ]
    await call.message.answer_media_group(media=media)

    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🚀 Kanalga chiqarish", callback_data=f"pub_{temp_id}")],
        [InlineKeyboardButton(text="✏️ Matnni tahrirlash", callback_data=f"edit_{temp_id}")],
        [InlineKeyboardButton(text="🗑 O'chirish", callback_data=f"del_{temp_id}")],
        [InlineKeyboardButton(text="⬅️ Ro'yxatga qaytish", callback_data="list_templates")]
    ])
    await call.message.answer("Amalni tanlang:", reply_markup=kb)
    await call.answer()

# --- TAHRIRLASH VA O'CHIRISH ---
@dp.callback_query(F.data.startswith("edit_"))
async def edit_template_start(call: types.CallbackQuery, state: FSMContext):
    temp_id = int(call.data.split("_")[1])
    await state.update_data(edit_temp_id=temp_id)
    await call.message.answer("📝 **Yangi matnni yuboring:**\n(Premium emojilar va formatlashlar qo'llab-quvvatlanadi)", parse_mode="HTML")
    await state.set_state(Form.edit_text)
    await call.answer()

@dp.message(Form.edit_text)
async def edit_template_finish(message: types.Message, state: FSMContext):
    new_text_html = message.html_text or message.caption_html
    data = await state.get_data()
    temp_id = data.get("edit_temp_id")

    await update_template_text(temp_id, new_text_html)
    await state.clear()
    await message.answer("✅ **Shablon matni muvaffaqiyatli yangilandi!**", reply_markup=get_main_keyboard(), parse_mode="HTML")

@dp.callback_query(F.data.startswith("del_"))
async def delete_template_handler(call: types.CallbackQuery):
    temp_id = int(call.data.split("_")[1])
    await delete_template(temp_id)
    await call.message.answer("🗑 **Shablon o'chirib tashlandi.**", parse_mode="HTML")
    await list_templates(call)

# --- POSTNI KANALGA CHIQARISH ---
@dp.callback_query(F.data.startswith("pub_"))
async def publish_post_handler(call: types.CallbackQuery):
    temp_id = int(call.data.split("_")[1])
    template = await get_template_by_id(temp_id)

    if not template:
        await call.message.answer("❌ Shablon topilmadi.")
        await call.answer()
        return

    title, text_html, photo_id, video_id = template
    try:
        media = [
            types.InputMediaPhoto(media=photo_id, caption=text_html, parse_mode="HTML"),
            types.InputMediaVideo(media=video_id)
        ]
        await bot.send_media_group(chat_id=CHANNEL_ID, media=media)
        await call.message.answer("🚀 **Post kanalga muvaffaqiyatli joylandi!**", parse_mode="HTML")
    except Exception as e:
        await call.message.answer(f"❌ Xatolik yuz berdi: {e}")

    await call.answer()

@dp.callback_query(F.data == "back_main")
async def back_main(call: types.CallbackQuery):
    await call.message.answer("Boshqaruv paneli:", reply_markup=get_main_keyboard())
    await call.answer()

# --- RENDER PORTI (DUMMY SERVER) ---
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
    asyncio.create_task(start_web_server())
    await bot.delete_webhook(drop_pending_updates=True)
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
    
