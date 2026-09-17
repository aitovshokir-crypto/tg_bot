import asyncio
import logging
import aiosqlite
import os
import json
from collections import defaultdict
from aiohttp import web
from aiogram import Bot, Dispatcher, F, types
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup, ReplyKeyboardRemove

# --- SOZLAMALAR ---
BOT_TOKEN = os.getenv("BOT_TOKEN", "8822913008:AAFNlFturFsjnTgJFN2GJHzMRIeHwFToYTk")
ADMIN_ID = int(os.getenv("ADMIN_ID", "6052580480"))
CHANNEL_ID = int(os.getenv("CHANNEL_ID", "-1003724147872"))

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher(storage=MemoryStorage())

# Albomlarni (media group) vaqtincha saqlash uchun lug'at
media_groups = defaultdict(list)

# --- FSM (HOLATLAR) ---
class Form(StatesGroup):
    forward_post = State()
    edit_title = State()
    edit_text = State()
    edit_photo = State()
    edit_video = State()
    edit_buttons = State()

# --- BAZA BILAN ISHLASH ---
async def init_db():
    async with aiosqlite.connect("bot_data.db") as db:
        await db.execute("""
            CREATE TABLE IF NOT EXISTS templates (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                title TEXT,
                text_html TEXT,
                photo_id TEXT,
                video_id TEXT,
                buttons_json TEXT
            )
        """)
        await db.commit()

async def create_empty_template():
    async with aiosqlite.connect("bot_data.db") as db:
        cursor = await db.execute("INSERT INTO templates (title) VALUES ('Yangi Shablon')")
        await db.commit()
        return cursor.lastrowid

async def save_full_template(title, text_html, photo_id, video_id, buttons_json=None):
    async with aiosqlite.connect("bot_data.db") as db:
        cursor = await db.execute(
            "INSERT INTO templates (title, text_html, photo_id, video_id, buttons_json) VALUES (?, ?, ?, ?, ?)",
            (title, text_html, photo_id, video_id, buttons_json)
        )
        await db.commit()
        return cursor.lastrowid

async def get_all_templates():
    async with aiosqlite.connect("bot_data.db") as db:
        async with db.execute("SELECT id, title FROM templates ORDER BY id DESC") as cursor:
            return await cursor.fetchall()

async def get_template_by_id(temp_id):
    async with aiosqlite.connect("bot_data.db") as db:
        async with db.execute("SELECT title, text_html, photo_id, video_id, buttons_json FROM templates WHERE id = ?", (temp_id,)) as cursor:
            return await cursor.fetchone()

async def update_template_field(temp_id, field, value):
    async with aiosqlite.connect("bot_data.db") as db:
        await db.execute(f"UPDATE templates SET {field} = ? WHERE id = ?", (value, temp_id))
        await db.commit()

async def delete_template(temp_id):
    async with aiosqlite.connect("bot_data.db") as db:
        await db.execute("DELETE FROM templates WHERE id = ?", (temp_id,))
        await db.commit()

# --- TUGMALARNI QAYTA ISHLASH (JSON) ---
def parse_inline_buttons(text):
    """Foydalanuvchi yuborgan matndan tugmalar yasash"""
    keyboard = []
    lines = text.strip().split('\n')
    for line in lines:
        row = []
        for btn in line.split('|'):
            parts = btn.split('-', 1)
            if len(parts) == 2:
                row.append({'text': parts[0].strip(), 'url': parts[1].strip()})
        if row:
            keyboard.append(row)
    return json.dumps(keyboard) if keyboard else None

def build_keyboard(buttons_json):
    """JSON dan InlineKeyboardMarkup yasash"""
    if not buttons_json: 
        return None
    try:
        data = json.loads(buttons_json)
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text=btn['text'], url=btn['url']) for btn in row]
            for row in data
        ])
        return kb
    except:
        return None

# --- ASOSIY MENYU TUGMALARI ---
def get_main_keyboard():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="➕ Yangi shablon yaratish", callback_data="create_new")],
        [InlineKeyboardButton(text="📥 Tayyor postdan saqlash", callback_data="add_forward")],
        [InlineKeyboardButton(text="📂 Shablonlar bo'limi", callback_data="list_templates")]
    ])

# --- TAHRIRLASH PANELI (EDITOR) ---
def get_editor_keyboard(temp_id):
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="🏷 Nomni o'zgartirish", callback_data=f"edtitle_{temp_id}"),
            InlineKeyboardButton(text="📝 Matnni o'zgartirish", callback_data=f"edtext_{temp_id}")
        ],
        [
            InlineKeyboardButton(text="🖼 Rasmni o'zgartirish", callback_data=f"edphoto_{temp_id}"),
            InlineKeyboardButton(text="🎥 Videoni o'zgartirish", callback_data=f"edvideo_{temp_id}")
        ],
        [InlineKeyboardButton(text="🔗 Tugmalarni tahrirlash", callback_data=f"edbtns_{temp_id}")],
        [InlineKeyboardButton(text="🚀 Kanalga yuborish", callback_data=f"pub_{temp_id}")],
        [
            InlineKeyboardButton(text="🗑 Shablonni o'chirish", callback_data=f"del_{temp_id}"),
            InlineKeyboardButton(text="⬅️ Menyu", callback_data="back_main")
        ]
    ])

# --- HANDLERLAR ---
@dp.message(Command("start"))
async def cmd_start(message: types.Message, state: FSMContext):
    if message.from_user.id != ADMIN_ID:
        return
    await state.clear()
    await message.answer("👋 <b>Boshqaruv paneliga xush kelibsiz!</b>\nO'zingizga kerakli bo'limni tanlang:", reply_markup=get_main_keyboard(), parse_mode="HTML")

# --- 1. BO'SH SHABLON YARATISH VA EDITORGA KIRISH ---
@dp.callback_query(F.data == "create_new")
async def create_new_template(call: types.CallbackQuery, state: FSMContext):
    temp_id = await create_empty_template()
    await call.answer("Yangi shablon yaratildi!")
    await show_editor(call.message, temp_id, state)

async def show_editor(message: types.Message, temp_id: int, state: FSMContext):
    template = await get_template_by_id(temp_id)
    if not template:
        await message.answer("❌ Shablon topilmadi.")
        return

    title, text_html, photo_id, video_id, buttons_json = template
    
    # 1. Shablonni ko'rsatamiz
    await message.answer(f"📋 <b>Shablon:</b> {title}\n👇 <b>Ko'rinishi:</b>", parse_mode="HTML")
    
    kb = build_keyboard(buttons_json)
    text_content = text_html if text_html else ""

    try:
        if photo_id and video_id:
            # Rasm va Video bitta postda bo'lsa (Albom)
            media = [
                types.InputMediaPhoto(media=photo_id, caption=text_content, parse_mode="HTML"),
                types.InputMediaVideo(media=video_id)
            ]
            await bot.send_media_group(chat_id=message.chat.id, media=media)
            if kb:
                await message.answer("👆 <i>(Albom ostidagi tugmalar)</i>", reply_markup=kb, parse_mode="HTML")
        elif photo_id:
            await bot.send_photo(chat_id=message.chat.id, photo=photo_id, caption=text_content, parse_mode="HTML", reply_markup=kb)
        elif video_id:
            await bot.send_video(chat_id=message.chat.id, video=video_id, caption=text_content, parse_mode="HTML", reply_markup=kb)
        elif text_content.strip():
            await bot.send_message(chat_id=message.chat.id, text=text_content, parse_mode="HTML", reply_markup=kb)
        else:
            await message.answer("<i>Shablon hozircha bo'sh... O'zgartirish kiritish uchun quyidagi tugmalardan foydalaning.</i>", parse_mode="HTML")
    except Exception as e:
        await message.answer(f"⚠️ Shablonni ko'rsatishda xatolik: {e}")

    # 2. Boshqaruv menyusini chiqaramiz
    await message.answer("⚙️ <b>Tahrirlash menyusi:</b>\nIstalgan qismini tahrirlang yoki saqlab chiqing.", reply_markup=get_editor_keyboard(temp_id), parse_mode="HTML")

# --- 2. TAYYOR POSTDAN SAQLASH ---
@dp.callback_query(F.data == "add_forward")
async def start_forward_save(call: types.CallbackQuery, state: FSMContext):
    await call.message.answer("📥 <b>Tayyor postni yuboring yoki forward qiling:</b>\n(Barcha rasm, video, matn va tugmalar saqlanadi)", parse_mode="HTML")
    await state.set_state(Form.forward_post)
    await call.answer()

async def save_media_group_data(mg_id, chat_id, state: FSMContext):
    await asyncio.sleep(1.5)  # Albom to'liq yetib kelishini kutamiz
    messages = media_groups.pop(mg_id, [])
    if not messages:
        return

    text_html = ""
    photo_id = None
    video_id = None

    for msg in messages:
        if not text_html and (msg.html_text or msg.caption_html):
            text_html = msg.html_text or msg.caption_html
        if msg.photo and not photo_id:
            photo_id = msg.photo[-1].file_id
        if (msg.video or msg.animation or msg.document) and not video_id:
            video_id = msg.video.file_id if msg.video else (msg.animation.file_id if msg.animation else msg.document.file_id)

    title = f"Post ({messages[0].date.strftime('%d.%m.%Y %H:%M')})"
    temp_id = await save_full_template(title=title, text_html=text_html, photo_id=photo_id, video_id=video_id)
    await state.clear()
    await show_editor(messages[0], temp_id, state)

@dp.message(Form.forward_post)
async def process_forward(message: types.Message, state: FSMContext):
    # Albom kelsa
    if message.media_group_id:
        mg_id = message.media_group_id
        is_first = len(media_groups[mg_id]) == 0
        media_groups[mg_id].append(message)
        if is_first:
            asyncio.create_task(save_media_group_data(mg_id, message.chat.id, state))
        return

    # Yakkalik xabar kelsa
    text_html = message.html_text or message.caption_html or ""
    photo_id = message.photo[-1].file_id if message.photo else None
    video_id = message.video.file_id if message.video else (message.animation.file_id if message.animation else None)
    
    buttons_json = None
    if message.reply_markup and message.reply_markup.inline_keyboard:
        keyboard = []
        for row in message.reply_markup.inline_keyboard:
            new_row = [{'text': btn.text, 'url': btn.url} for btn in row if btn.url]
            if new_row:
                keyboard.append(new_row)
        if keyboard:
            buttons_json = json.dumps(keyboard)

    title = f"Post ({message.date.strftime('%d.%m.%Y %H:%M')})"
    temp_id = await save_full_template(title=title, text_html=text_html, photo_id=photo_id, video_id=video_id, buttons_json=buttons_json)
    await state.clear()
    await show_editor(message, temp_id, state)

# --- 3. SHABLONLAR RO'YXATI ---
@dp.callback_query(F.data == "list_templates")
async def list_templates(call: types.CallbackQuery):
    templates = await get_all_templates()
    if not templates:
        await call.message.answer("📂 Hozircha hech qanday shablon yaratilmagan.")
        await call.answer()
        return

    buttons = []
    for temp_id, title in templates:
        buttons.append([InlineKeyboardButton(text=f"📋 {title}", callback_data=f"open_{temp_id}")])
    
    buttons.append([InlineKeyboardButton(text="⬅️ Orqaga", callback_data="back_main")])
    kb = InlineKeyboardMarkup(inline_keyboard=buttons)
    await call.message.answer("📂 <b>Mavjud shablonlar ro'yxati:</b>", reply_markup=kb, parse_mode="HTML")
    await call.answer()

@dp.callback_query(F.data.startswith("open_"))
async def open_template_editor(call: types.CallbackQuery, state: FSMContext):
    temp_id = int(call.data.split("_")[1])
    await call.answer()
    await show_editor(call.message, temp_id, state)

# --- 4. TAHRIRLASH JARAYONLARI (FSM) ---
@dp.callback_query(F.data.startswith("edtitle_"))
async def edit_title_start(call: types.CallbackQuery, state: FSMContext):
    temp_id = int(call.data.split("_")[1])
    await state.update_data(edit_temp_id=temp_id)
    await call.message.answer("🏷 <b>Yangi nomni yuboring:</b>", parse_mode="HTML")
    await state.set_state(Form.edit_title)
    await call.answer()

@dp.message(Form.edit_title)
async def edit_title_finish(message: types.Message, state: FSMContext):
    data = await state.get_data()
    temp_id = data.get("edit_temp_id")
    await update_template_field(temp_id, "title", message.text)
    await state.clear()
    await show_editor(message, temp_id, state)

@dp.callback_query(F.data.startswith("edtext_"))
async def edit_text_start(call: types.CallbackQuery, state: FSMContext):
    temp_id = int(call.data.split("_")[1])
    await state.update_data(edit_temp_id=temp_id)
    await call.message.answer("📝 <b>Yangi matnni yuboring:</b>\n<i>(Tozalash uchun /clear ni yuboring)</i>", parse_mode="HTML")
    await state.set_state(Form.edit_text)
    await call.answer()

@dp.message(Form.edit_text)
async def edit_text_finish(message: types.Message, state: FSMContext):
    data = await state.get_data()
    temp_id = data.get("edit_temp_id")
    new_text = "" if message.text == "/clear" else (message.html_text or message.caption_html or "")
    
    await update_template_field(temp_id, "text_html", new_text)
    await state.clear()
    await show_editor(message, temp_id, state)

@dp.callback_query(F.data.startswith("edphoto_"))
async def edit_photo_start(call: types.CallbackQuery, state: FSMContext):
    temp_id = int(call.data.split("_")[1])
    await state.update_data(edit_temp_id=temp_id)
    await call.message.answer("🖼 <b>Yangi rasm yuboring:</b>\n<i>(O'chirib tashlash uchun /clear ni yuboring)</i>", parse_mode="HTML")
    await state.set_state(Form.edit_photo)
    await call.answer()

@dp.message(Form.edit_photo)
async def edit_photo_finish(message: types.Message, state: FSMContext):
    data = await state.get_data()
    temp_id = data.get("edit_temp_id")
    photo_id = None if message.text == "/clear" else (message.photo[-1].file_id if message.photo else None)
    
    if message.text != "/clear" and not photo_id:
        await message.answer("⚠️ Iltimos rasm yuboring!")
        return

    await update_template_field(temp_id, "photo_id", photo_id)
    await state.clear()
    await show_editor(message, temp_id, state)

@dp.callback_query(F.data.startswith("edvideo_"))
async def edit_video_start(call: types.CallbackQuery, state: FSMContext):
    temp_id = int(call.data.split("_")[1])
    await state.update_data(edit_temp_id=temp_id)
    await call.message.answer("🎥 <b>Yangi video yuboring:</b>\n<i>(O'chirib tashlash uchun /clear ni yuboring)</i>", parse_mode="HTML")
    await state.set_state(Form.edit_video)
    await call.answer()

@dp.message(Form.edit_video)
async def edit_video_finish(message: types.Message, state: FSMContext):
    data = await state.get_data()
    temp_id = data.get("edit_temp_id")
    video_id = None
    if message.text != "/clear":
        video_id = message.video.file_id if message.video else (message.animation.file_id if message.animation else message.document.file_id if message.document else None)
        if not video_id:
            await message.answer("⚠️ Iltimos video yuboring!")
            return

    await update_template_field(temp_id, "video_id", video_id)
    await state.clear()
    await show_editor(message, temp_id, state)

@dp.callback_query(F.data.startswith("edbtns_"))
async def edit_buttons_start(call: types.CallbackQuery, state: FSMContext):
    temp_id = int(call.data.split("_")[1])
    await state.update_data(edit_temp_id=temp_id)
    await call.message.answer(
        "🔗 <b>Tugmalarni yaratish qoidalari:</b>\n\n"
        "Quyidagi formatda yuboring:\n"
        "<code>Tugma nomi - https://silka.uz</code>\n\n"
        "Yoki yonma-yon qilish uchun `|` ishlating:\n"
        "<code>Kanal 1 - https://t.me/kanal1 | Kanal 2 - https://t.me/kanal2</code>\n\n"
        "<i>(Tugmalarni butunlay o'chirish uchun /clear ni yuboring)</i>", 
        parse_mode="HTML"
    )
    await state.set_state(Form.edit_buttons)
    await call.answer()

@dp.message(Form.edit_buttons)
async def edit_buttons_finish(message: types.Message, state: FSMContext):
    data = await state.get_data()
    temp_id = data.get("edit_temp_id")
    
    if message.text == "/clear":
        buttons_json = None
    else:
        buttons_json = parse_inline_buttons(message.text)
        if not buttons_json:
            await message.answer("⚠️ Xato format! Iltimos ko'rsatilgan formatda yuboring.")
            return

    await update_template_field(temp_id, "buttons_json", buttons_json)
    await state.clear()
    await show_editor(message, temp_id, state)

# --- 5. O'CHIRISH, ORQAGA QAYTISH VA KANALGA CHIQARISH ---
@dp.callback_query(F.data.startswith("del_"))
async def delete_template_handler(call: types.CallbackQuery):
    temp_id = int(call.data.split("_")[1])
    await delete_template(temp_id)
    await call.message.answer("🗑 <b>Shablon o'chirildi.</b>", parse_mode="HTML")
    await list_templates(call)

@dp.callback_query(F.data == "back_main")
async def back_main(call: types.CallbackQuery, state: FSMContext):
    await state.clear()
    await call.message.answer("Boshqaruv paneli:", reply_markup=get_main_keyboard())
    await call.answer()

@dp.callback_query(F.data.startswith("pub_"))
async def publish_post_handler(call: types.CallbackQuery):
    temp_id = int(call.data.split("_")[1])
    template = await get_template_by_id(temp_id)

    if not template:
        await call.message.answer("❌ Shablon topilmadi.")
        await call.answer()
        return

    title, text_html, photo_id, video_id, buttons_json = template
    kb = build_keyboard(buttons_json)
    text_content = text_html if text_html else ""

    try:
        if photo_id and video_id:
            media = [
                types.InputMediaPhoto(media=photo_id, caption=text_content, parse_mode="HTML"),
                types.InputMediaVideo(media=video_id)
            ]
            msg = await bot.send_media_group(chat_id=CHANNEL_ID, media=media)
            if kb:
                await bot.send_message(chat_id=CHANNEL_ID, text="👆 Batafsil:", reply_markup=kb, reply_to_message_id=msg[0].message_id)
        
        elif photo_id:
            await bot.send_photo(chat_id=CHANNEL_ID, photo=photo_id, caption=text_content, parse_mode="HTML", reply_markup=kb)
        
        elif video_id:
            await bot.send_video(chat_id=CHANNEL_ID, video=video_id, caption=text_content, parse_mode="HTML", reply_markup=kb)
        
        elif text_content.strip():
            await bot.send_message(chat_id=CHANNEL_ID, text=text_content, parse_mode="HTML", reply_markup=kb)
        
        else:
            await call.message.answer("❌ Shablon bo'sh! Yuborish uchun hech narsa yo'q.")
            return

        await call.message.answer("🚀 <b>Post kanalga muvaffaqiyatli joylandi!</b>", parse_mode="HTML")
    except Exception as e:
        await call.message.answer(f"❌ Xatolik yuz berdi: {e}")

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
    
