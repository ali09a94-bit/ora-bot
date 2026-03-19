import telebot
from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton
import yt_dlp
import os
import json
import time
from flask import Flask
from threading import Thread

# --- سيرفر وهمي للبقاء حياً على Render ---
app = Flask('')

@app.route('/')
def home():
    return "Ora Bot is Online!"

def run():
    port = int(os.environ.get("PORT", 8080))
    app.run(host='0.0.0.0', port=port)

def keep_alive():
    t = Thread(target=run)
    t.start()
# ---------------------------------------

# --- إعدادات البوت ---
TOKEN = "5232200010:AAErp2AjMsdw2E5bhI752MCAALlB0MM0JmY"
ADMIN_ID = 5289253636 
BOT_USER = "ali09a933BOT" 
bot = telebot.TeleBot(TOKEN)

DATA_FILE = "bot_data.json"
if not os.path.exists(DATA_FILE):
    with open(DATA_FILE, "w") as f:
        json.dump({"users": [], "total_dl": 0}, f)

def load_data():
    try:
        with open(DATA_FILE, "r") as f: return json.load(f)
    except: return {"users": [], "total_dl": 0}

def save_data(data):
    with open(DATA_FILE, "w") as f: json.dump(data, f)

def main_markup():
    markup = InlineKeyboardMarkup()
    markup.row(InlineKeyboardButton("اليوتيوب", callback_data="btn_yt"))
    markup.add(InlineKeyboardButton("الإنستغرام", callback_data="btn_ig"), 
               InlineKeyboardButton("فيسبوك", callback_data="btn_fb"))
    markup.add(InlineKeyboardButton("التيك توك", callback_data="btn_tk"), 
               InlineKeyboardButton("لايك", callback_data="btn_likee"))
    markup.add(InlineKeyboardButton("تويتر", callback_data="btn_tw"), 
               InlineKeyboardButton("سناب شات", callback_data="btn_snap"))
    markup.add(InlineKeyboardButton("بِنْتْرِست", callback_data="btn_pin"), 
               InlineKeyboardButton("تورنت", callback_data="btn_torrent"))
    markup.row(InlineKeyboardButton("أي موقع", callback_data="btn_all"))
    return markup

@bot.message_handler(commands=['start'])
def start(message):
    uid = message.chat.id
    data = load_data()
    if uid not in data["users"]:
        data["users"].append(uid)
        save_data(data)
        bot.send_message(ADMIN_ID, f"🆕 مستخدم جديد:\n👤 {message.from_user.first_name}\n🆔 `{uid}`")

    text = "📥 **بوت أورا للـتحـميـل** 📥\n⚡️ أرسل رابط الفيديو الآن.. ✨"
    bot.send_message(uid, text, parse_mode="Markdown", reply_markup=main_markup())

@bot.message_handler(func=lambda m: "http" in m.text)
def download(message):
    url = message.text.strip()
    uid = message.chat.id
    sent = bot.reply_to(message, "🚀 جاري التحميل...")
    
    file_path = f"vid_{uid}_{int(time.time())}"
    opts = {
        'format': 'bestvideo[ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]/best',
        'outtmpl': f'{file_path}.%(ext)s',
        'quiet': True,
    }

    try:
        with yt_dlp.YoutubeDL(opts) as ydl:
            info = ydl.extract_info(url, download=True)
            final_file = ydl.prepare_filename(info)
        
        with open(final_file, 'rb') as f:
            bot.send_video(uid, f, caption=f"✅ تم بواسطة: @{BOT_USER}")
        
        data = load_data()
        data["total_dl"] += 1
        save_data(data)
        bot.delete_message(uid, sent.message_id)
        if os.path.exists(final_file): os.remove(final_file)
    except:
        bot.edit_message_text("❌ فشل التحميل.", uid, sent.message_id)

@bot.callback_query_handler(func=lambda call: True)
def callback_query(call):
    if call.data == "back":
        bot.edit_message_text("📥 اختر المنصة:", call.message.chat.id, call.message.message_id, reply_markup=main_markup())
    elif call.data.startswith("btn_"):
        bot.edit_message_text("• أرسل الرابط الآن.. ✨", call.message.chat.id, call.message.message_id, 
                              reply_markup=InlineKeyboardMarkup().add(InlineKeyboardButton("⬅️ رجوع", callback_data="back")))

if __name__ == "__main__":
    keep_alive()
    bot.infinity_polling()
	
