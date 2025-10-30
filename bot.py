import os
import random
import logging
from io import BytesIO
from PIL import Image, ImageDraw, ImageFont
from telegram import Update, InputFile, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, ContextTypes
import sqlite3

# ТОКЕН ИЗ RENDER (БЕЗ .env!)
TOKEN = os.environ['BOT_TOKEN']

logging.basicConfig(level=logging.INFO)
os.makedirs("assets", exist_ok=True)

# === БД ===
def init_db():
    conn = sqlite3.connect('lottery.db')
    c = conn.cursor()
    c.execute('''CREATE TABLE IF NOT EXISTS users (user_id INTEGER PRIMARY KEY, coins INTEGER DEFAULT 100)''')
    c.execute('''CREATE TABLE IF NOT EXISTS cards (
                 card_id INTEGER PRIMARY KEY AUTOINCREMENT,
                 user_id INTEGER,
                 prizes TEXT,
                 revealed TEXT
                 )''')
    conn.commit()
    conn.close()

init_db()

PRIZES = ["500", "200", "100", "50", "Пусто", "Пусто", "Пусто", "Пусто", "Пусто"]

def generate_card_image(prizes, revealed):
    size = 600
    cell = size // 3
    img = Image.new('RGB', (size, size), (30, 30, 50))
    draw = ImageDraw.Draw(img)

    try:
        overlay = Image.open("assets/scratch_overlay.png").resize((cell, cell))
    except:
        overlay = Image.new('RGBA', (cell, cell), (180, 180, 180, 200))

    try:
        font = ImageFont.truetype("arial.ttf", 50)
        small_font = ImageFont.truetype("arial.ttf", 30)
    except:
        font = ImageFont.load_default()
        small_font = font

    for i in range(9):
        x, y = (i % 3) * cell, (i // 3) * cell
        prize = prizes[i]
        prize_img = Image.new('RGB', (cell, cell), (255, 255, 255))
        pd = ImageDraw.Draw(prize_img)
        if prize == "Пусто":
            pd.text((cell//2 - 40, cell//2 - 30), "Пусто", font=font, fill=(100, 100, 100))
        else:
            pd.text((cell//2 - 50, cell//2 - 50), prize, font=font, fill=(255, 215, 0))
            pd.text((cell//2 - 60, cell//2 + 10), "монет", font=small_font, fill=(200, 200, 200))
        img.paste(prize_img, (x, y))
        if revealed[i] == '0':
            img.paste(overlay, (x, y), overlay if overlay.mode == 'RGBA' else None)

    bio = BytesIO()
    img.save(bio, 'PNG')
    bio.seek(0)
    return bio

# === Функции БД ===
def get_coins(user_id):
    conn = sqlite3.connect('lottery.db')
    c = conn.cursor()
    c.execute("INSERT OR IGNORE INTO users (user_id, coins) VALUES (?, 100)", (user_id,))
    c.execute("SELECT coins FROM users WHERE user_id = ?", (user_id,))
    row = c.fetchone()
    conn.close()
    return row[0] if row else 100

def spend_coins(user_id, amount):
    conn = sqlite3.connect('lottery.db')
    c = conn.cursor()
    c.execute("UPDATE users SET coins = coins - ? WHERE user_id = ?", (amount, user_id))
    conn.commit()
    conn.close()

def add_coins(user_id, amount):
    conn = sqlite3.connect('lottery.db')
    c = conn.cursor()
    c.execute("UPDATE users SET coins = coins + ? WHERE user_id = ?", (amount, user_id))
    conn.commit()
    conn.close()

def save_card(user_id, prizes):
    conn = sqlite3.connect('lottery.db')
    c = conn.cursor()
    c.execute("INSERT INTO cards (user_id, prizes, revealed) VALUES (?, ?, ?)",
              (user_id, ','.join(prizes), '0'*9))
    card_id = c.lastrowid
    conn.commit()
    conn.close()
    return card_id

def get_card(card_id):
    conn = sqlite3.connect('lottery.db')
    c = conn.cursor()
    c.execute("SELECT prizes, revealed, user_id FROM cards WHERE card_id = ?", (card_id,))
    row = c.fetchone()
    conn.close()
    if row:
        return row[0].split(','), list(row[1]), row[2]
    return None, None, None

def reveal_field(card_id, pos):
    conn = sqlite3.connect('lottery.db')
    c = conn.cursor()
    c.execute("SELECT revealed FROM cards WHERE card_id = ?", (card_id,))
    revealed = list(c.fetchone()[0])
    revealed[pos] = '1'
    c.execute("UPDATE cards SET revealed = ? WHERE card_id = ?", (''.join(revealed), card_id))
    conn.commit()
    conn.close()

# === Хендлеры ===
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    coins = get_coins(user_id)
    keyboard = [[InlineKeyboardButton("Купить карточку (50 монет)", callback_data="buy_card")]]
    await update.message.reply_text(
        f"*Лотерея!*\n\nУ тебя: {coins} монет\nКарточка — 50 монет",
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode='Markdown'
    )

async def buy_card(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id
    if get_coins(user_id) < 50:
        await query.edit_message_text("Недостаточно монет!")
        return
    spend_coins(user_id, 50)
    prizes = random.sample(PRIZES * 2, 9)
    card_id = save_card(user_id, prizes)
    img = generate_card_image(prizes, ['0']*9)
    keyboard = [[InlineKeyboardButton("Стереть", callback_data=f"scratch_{card_id}_{i*3+j}") 
                 for j in range(3)] for i in range(3)]
    await query.message.reply_photo(
        photo=img,
        caption=f"*Новая карточка!*\nОстаток: {get_coins(user_id)}",
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode='Markdown'
    )
    await query.delete_message()

async def scratch(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data.split("_")
    if data[0] != "scratch": return
    card_id, pos = int(data[1]), int(data[2])
    prizes, revealed, user_id = get_card(card_id)
    if not prizes or revealed[pos] == '1': return
    reveal_field(card_id, pos)
    prize = prizes[pos]
    if prize.isdigit():
        add_coins(user_id, int(prize))
    img = generate_card_image(prizes, revealed)
    keyboard = [[InlineKeyboardButton("Открыто" if revealed[i*3+j]=='1' else "Стереть", 
                                      callback_data="none" if revealed[i*3+j]=='1' else f"scratch_{card_id}_{i*3+j}") 
                 for j in range(3)] for i in range(3)]
    await query.message.edit_media(media=InputFile(img, "card.png"), reply_markup=InlineKeyboardMarkup(keyboard))
    await query.message.edit_caption(caption=f"Открыто: {prize}\nБаланс: {get_coins(user_id)}", parse_mode='Markdown')

# === Запуск ===
def main():
    app = Application.builder().token(TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CallbackQueryHandler(buy_card, pattern="^buy_card$"))
    app.add_handler(CallbackQueryHandler(scratch, pattern="^scratch_"))
    print("Бот запущен на Render!")
    app.run_polling()

if __name__ == '__main__':
    main()
