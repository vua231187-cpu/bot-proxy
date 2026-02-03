import telebot
from telebot import types
import sqlite3
import time
import json
import random
import string
import urllib3
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
import requests
from datetime import datetime
import os

BOT_TOKEN = os.getenv("BOT_TOKEN")
bot = telebot.TeleBot(BOT_TOKEN)


# ================= CONFIG =================
ADMIN_IDS = [6500271609]  # ID admin
PROXY_API_URL = "https://proxy.vn/apiv2/muaproxy.php"
PROXY_API_KEY = "AHiZEhkiFvmMxgGZNOwenP"
PROXY_PRICE_PER_DAY = 4000
PROXY_DURATION_HOURS = 24

# ================= DATABASE =================
conn = sqlite3.connect("bot.db", check_same_thread=False)
cur = conn.cursor()

cur.execute("""
CREATE TABLE IF NOT EXISTS users (
    user_id INTEGER PRIMARY KEY,
    balance INTEGER DEFAULT 0,
    total_deposit INTEGER DEFAULT 0
)
""")

cur.execute("""
CREATE TABLE IF NOT EXISTS deposits (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER,
    amount INTEGER,
    status TEXT,
    time INTEGER
)
""")

cur.execute("""
CREATE TABLE IF NOT EXISTS proxies (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER,
    proxy TEXT,
    expire_time INTEGER
)
""")
conn.commit()

buy_proxy_state = {}
# uid: {
#   "step": "day" | "account",
#   "days": int
# }

# ================= HELPERS =================
def buy_proxy_real(days, username, password):
    payload = {
        "key": PROXY_API_KEY,
        "day": days,
        "type": "http"
    }

    try:
        r = requests.post(PROXY_API_URL, data=payload, timeout=20)
        text = r.content.decode("utf-8-sig")
        data = json.loads(text)

    except Exception as e:
        return False, f"❌ Lỗi kết nối API: {e}"

    if "data" not in data or not data["data"]:
        return False, "❌ API không trả proxy"

    p = data["data"][0]

    proxy = f'{p["ip"]}:{p["port"]}:{username}:{password}'

    expire_time = int(datetime.strptime(
        p["expired_at"], "%Y-%m-%d %H:%M:%S"
    ).timestamp())

    return True, proxy, expire_time

def is_admin(uid):
    return uid in ADMIN_IDS

def mua_proxy_tu_dong(days):
    url = "https://proxy.vn/apiv2/muaproxy.php"
    params = {
        "loaiproxy": "4Gvinaphone",
        "key": "AHiZEhkiFvmMxgGZNOwenP",
        "soluong": 1,
        "ngay": days,
        "type": "HTTP",
        "user": "random",
        "password": "random"
    }

    try:
        r = requests.get(url, params=params, timeout=20, verify=False)
        text = r.content.decode("utf-8-sig")
        data = json.loads(text)

        print("DEBUG PROXY API:", data)

    except Exception as e:
        return False, f"Lỗi kết nối API: {e}", None

    # API trả LIST
    if not isinstance(data, list) or len(data) == 0:
        return False, "API không trả proxy", None

    p = data[0]

    proxy = p.get("proxy")
    live_seconds = p.get("time")

    if not proxy or not live_seconds:
        return False, "Thiếu dữ liệu proxy", None

    expire_time = int(time.time()) + int(live_seconds)

    return True, proxy, expire_time

def get_user(uid):
    cur.execute("SELECT * FROM users WHERE user_id=?", (uid,))
    u = cur.fetchone()
    if not u:
        cur.execute("INSERT INTO users (user_id) VALUES (?)", (uid,))
        conn.commit()
        return get_user(uid)
    return u

def now():
    return int(time.time())

def admin_deposit_keyboard(deposit_id):
    kb = types.InlineKeyboardMarkup()
    kb.row(
        types.InlineKeyboardButton("✅ Duyệt", callback_data=f"duyet_nap_{deposit_id}"),
        types.InlineKeyboardButton("❌ Từ chối", callback_data=f"tu_choi_{deposit_id}")
    )
    return kb

def nap_confirm_keyboard():
    kb = types.InlineKeyboardMarkup()
    kb.add(
        types.InlineKeyboardButton(
            "✅ Tôi đã chuyển khoản",
            callback_data="nap_da_chuyen"
        )
    )
    return kb

def has_pending_deposit(uid):
    cur.execute(
        "SELECT COUNT(*) FROM deposits WHERE user_id=? AND status='pending'",
        (uid,)
    )
    return cur.fetchone()[0] > 0

# ================= MENUS =================
def user_menu():
    kb = types.ReplyKeyboardMarkup(resize_keyboard=True)
    kb.row("🛒 Mua proxy", "💰 Nạp tiền")
    kb.row("📜 Lịch sử mua", "📘 Lịch sử nạp")
    kb.row("ℹ️ Thông tin", "📞 Hỗ trợ")
    return kb

def admin_menu():
    kb = types.ReplyKeyboardMarkup(resize_keyboard=True)
    kb.row("💰 Duyệt nạp tiền", "🌐 Quản lý proxy")
    kb.row("📊 Thống kê", "👥 Người dùng")
    kb.row("⚙️ Cấu hình")
    return kb

# ================= START =================
@bot.message_handler(commands=["start"])
def start(msg):
    uid = msg.from_user.id
    if is_admin(uid):
        bot.send_message(uid, "👑 CHẾ ĐỘ QUẢN TRỊ VIÊN", reply_markup=admin_menu())
    else:
        get_user(uid)
        bot.send_message(uid, "👋 Chào mừng bạn!", reply_markup=user_menu())

# ================= USER =================
@bot.message_handler(func=lambda m: m.text == "🛒 Mua proxy")
def buy_proxy_start(msg):
    uid = msg.from_user.id
    buy_proxy_state[uid] = {"step": "day"}

    bot.send_message(
        uid,
        "🌐 PROXY HTTP\n\n"
        f"💰 Giá: {format(PROXY_PRICE_PER_DAY, ',')} VND / ngày"
        "✍️ Nhập số ngày muốn mua\n"
        "📌 Ví dụ: 7",
        reply_markup=types.ReplyKeyboardMarkup(resize_keyboard=True).row("⬅️ Quay lại")
    )

@bot.message_handler(func=lambda m: m.from_user.id in buy_proxy_state and
                     buy_proxy_state[m.from_user.id]["step"] == "day")
def buy_proxy_day(msg):
    uid = msg.from_user.id

    try:
        days = int(msg.text)
        if days <= 0:
            raise ValueError
    except:
        bot.reply_to(msg, "❌ Nhập số ngày hợp lệ")
        return

    total_price = days * PROXY_PRICE_PER_DAY
    buy_proxy_state[uid]["days"] = days

    kb = types.InlineKeyboardMarkup()
    kb.add(
        types.InlineKeyboardButton("✅ Xác nhận mua", callback_data="confirm_buy_proxy"),
        types.InlineKeyboardButton("❌ Hủy", callback_data="cancel_buy_proxy")
    )

    bot.send_message(
        uid,
        f"""🔐 XÁC NHẬN MUA PROXY

📅 Số ngày: {days}
💰 Giá: {total_price:,} VND
🌐 Loại: 4G Datacenter (HTTP)
👤 User/Pass: Tự động
""",
        reply_markup=kb
    )

@bot.message_handler(func=lambda m: m.text == "💰 Nạp tiền")
def nap_tien(msg):
    uid = msg.from_user.id
    bot.send_message(
        uid,
        f"""💰 HƯỚNG DẪN NẠP TIỀN

    🏦 CAKE
    🔢 0374306676
    👤 VU TUAN ANH

    ✍️ Nội dung CK:
    {uid}

    📌 CÁCH NẠP:
    👉 Gõ: /nap + số tiền
    📎 Ví dụ: /nap 50000

    💵 Nạp tối thiểu: 20,000 VND
    """
    )

@bot.message_handler(commands=["nap"])
def user_nap(msg):
    uid = msg.from_user.id

    # 🚫 Đang có pending
    if has_pending_deposit(uid):
        bot.reply_to(
            msg,
            "⏳ Bạn đang có **giao dịch nạp chờ duyệt**.\n"
            "Vui lòng đợi admin xác nhận trước khi nạp tiếp."
        )
        return

    try:
        amount = int(msg.text.split()[1])
    except:
        bot.reply_to(msg, "❌ Dùng đúng cú pháp: /nap 50000")
        return

    if amount < 20000:
        bot.reply_to(msg, "❌ Nạp tối thiểu 20,000 VND")
        return

    cur.execute(
        "INSERT INTO deposits (user_id, amount, status, time) VALUES (?,?,?,?)",
        (uid, amount, "pending", now())
    )
    conn.commit()

    bot.send_message(
        uid,
        f"📨 ĐÃ GHI NHẬN NẠP TIỀN\n\n"
        f"💵 Số tiền: {amount:,} VND\n"
        f"⏳ Trạng thái: Chờ admin xác nhận",
        reply_markup=user_menu()
    )


@bot.callback_query_handler(func=lambda call: call.data == "back_main_menu")
def back_main_menu(call):
    uid = call.from_user.id
    chat_id = call.message.chat.id

    markup = types.ReplyKeyboardMarkup(resize_keyboard=True)
    markup.add("🛒 Mua proxy", "💰 Nạp tiền")
    markup.add("📜 Lịch sử", "📞 Hỗ trợ")

    bot.send_message(
        chat_id,
        "🏠 Menu chính",
        reply_markup=markup
    )

@bot.message_handler(func=lambda m: m.text == "📘 Lịch sử nạp")
def lich_su_nap(msg):
    uid = msg.from_user.id
    cur.execute("""
        SELECT amount, status, time 
        FROM deposits 
        WHERE user_id=? 
        ORDER BY time DESC 
        LIMIT 5
    """, (uid,))
    rows = cur.fetchall()

    if not rows:
        bot.send_message(uid, "📘 LỊCH SỬ NẠP\n\n❌ Bạn chưa có giao dịch nào.")
        return

    text = "📘 **LỊCH SỬ NẠP TIỀN**\n\n"

    for amount, status, t in rows:
        time_str = datetime.fromtimestamp(t).strftime("%d/%m/%Y %H:%M")

        if status == "success":
            icon = "🟢"
            stt = "Thành công"
        elif status == "pending":
            icon = "🟡"
            stt = "Chờ duyệt"
        else:
            icon = "🔴"
            stt = "Thất bại"

        text += (
            f"{icon} {amount:,} VND\n"
            f"📌 Trạng thái: {stt}\n"
            f"🕒 Thời gian: {time_str}\n\n"
        )

    bot.send_message(uid, text, parse_mode="Markdown")

@bot.message_handler(func=lambda m: m.text == "📜 Lịch sử mua")
def lich_su_mua(msg):
    uid = msg.from_user.id
    cur.execute("SELECT proxy FROM proxies WHERE user_id=? AND expire_time>?", (uid, now()))
    rows = cur.fetchall()

    text = "📜 PROXY CÒN HẠN\n\n"
    for p in rows:
        text += f"`{p[0]}`\n"
    bot.send_message(uid, text, parse_mode="Markdown")

@bot.message_handler(func=lambda m: m.text == "ℹ️ Thông tin")
def thong_tin(msg):
    uid = msg.from_user.id
    u = get_user(uid)

    cur.execute("SELECT COUNT(*) FROM proxies WHERE user_id=?", (uid,))
    total_proxy = cur.fetchone()[0]

    bot.send_message(uid,
        f"""ℹ️ THÔNG TIN

🆔 {uid}
💰 Số dư: {u[1]:,} VND
🌐 Proxy đã mua: {total_proxy}
💳 Tổng nạp: {u[2]:,} VND"""
    )

@bot.message_handler(func=lambda m: m.text == "📞 Hỗ trợ")
def ho_tro(msg):
    bot.send_message(msg.chat.id,
        "📞 HỖ TRỢ\nAdmin: @tuananhdz\nID: 6500271609"
    )

# ================= ADMIN =================
@bot.message_handler(func=lambda m: is_admin(m.from_user.id) and m.text == "💰 Duyệt nạp tiền")
def admin_duyet(msg):
    cur.execute("SELECT id, user_id, amount FROM deposits WHERE status='pending'")
    rows = cur.fetchall()

    if not rows:
        bot.send_message(msg.chat.id, "✅ Không có giao dịch chờ duyệt")
        return

    for did, uid, amount in rows:
        bot.send_message(
            msg.chat.id,
            f"💰 GIAO DỊCH NẠP\n\n"
            f"🆔 ID GD: {did}\n"
            f"👤 User: {uid}\n"
            f"💵 Số tiền: {amount:,} VND",
            reply_markup=admin_deposit_keyboard(did)
        )

@bot.message_handler(commands=["xacnhan"])
def admin_confirm(msg):
    if not is_admin(msg.from_user.id):
        return
    did = int(msg.text.split()[1])
    cur.execute("SELECT user_id,amount FROM deposits WHERE id=?", (did,))
    d = cur.fetchone()
    if not d:
        return

    uid, amount = d
    cur.execute("UPDATE deposits SET status='success' WHERE id=?", (did,))
    cur.execute("UPDATE users SET balance=balance+?, total_deposit=total_deposit+? WHERE user_id=?",
                (amount, amount, uid))
    conn.commit()

    bot.send_message(uid,
        f"✅ NẠP TIỀN THÀNH CÔNG\n💵 {amount:,} VND"
    )

@bot.message_handler(commands=["tracuu"])
def admin_tracuu(msg):
    if not is_admin(msg.from_user.id):
        return
    try:
        uid = int(msg.text.split()[1])
    except:
        bot.reply_to(msg, "Dùng: /tracuu <id>")
        return

    u = get_user(uid)
    cur.execute("SELECT COUNT(*) FROM proxies WHERE user_id=?", (uid,))
    p = cur.fetchone()[0]

    bot.send_message(msg.chat.id,
        f"""👤 THÔNG TIN USER

🆔 {uid}
💰 Số dư: {u[1]:,}
🌐 Proxy đã mua: {p}
💳 Tổng nạp: {u[2]:,}"""
    )

@bot.message_handler(commands=["cong"])
def admin_cong_tien(msg):
    if not is_admin(msg.from_user.id):
        return

    try:
        _, uid, amount = msg.text.split()
        uid = int(uid)
        amount = int(amount)
        if amount <= 0:
            raise ValueError
    except:
        bot.reply_to(msg, "❌ Dùng đúng cú pháp:\n/cong <user_id> <số tiền>")
        return

    get_user(uid)

    cur.execute(
        "UPDATE users SET balance = balance + ?, total_deposit = total_deposit + ? WHERE user_id=?",
        (amount, amount, uid)
    )
    conn.commit()

    bot.send_message(
        msg.chat.id,
        f"✅ ĐÃ CỘNG TIỀN\n\n"
        f"👤 User: {uid}\n"
        f"💰 +{amount:,} VND"
    )

    bot.send_message(
        uid,
        f"💰 TÀI KHOẢN ĐƯỢC CỘNG TIỀN\n\n"
        f"➕ {amount:,} VND\n"
        f"👑 Bởi admin"
    )
 @bot.message_handler(commands=["tru"])
def admin_tru_tien(msg):
    if not is_admin(msg.from_user.id):
        return

    try:
        _, uid, amount = msg.text.split()
        uid = int(uid)
        amount = int(amount)
        if amount <= 0:
            raise ValueError
    except:
        bot.reply_to(msg, "❌ Dùng đúng cú pháp:\n/tru <user_id> <số tiền>")
        return

    u = get_user(uid)
    balance = u[1]

    if balance < amount:
        bot.reply_to(
            msg,
            f"❌ Không đủ tiền để trừ\n"
            f"💰 Số dư hiện tại: {balance:,} VND"
        )
        return

    cur.execute(
        "UPDATE users SET balance = balance - ? WHERE user_id=?",
        (amount, uid)
    )
    conn.commit()

    bot.send_message(
        msg.chat.id,
        f"✅ ĐÃ TRỪ TIỀN\n\n"
        f"👤 User: {uid}\n"
        f"💰 -{amount:,} VND"
    )

    bot.send_message(
        uid,
        f"⚠️ TÀI KHOẢN BỊ TRỪ TIỀN\n\n"
        f"➖ {amount:,} VND\n"
        f"👑 Bởi admin"
    )   
    
@bot.message_handler(func=lambda m: is_admin(m.from_user.id) and m.text == "🌐 Quản lý proxy")
def admin_proxy(msg):
    cur.execute("SELECT COUNT(*) FROM proxies")
    total = cur.fetchone()[0]
    bot.send_message(msg.chat.id, f"🌐 Proxy đã bán: {total}")

@bot.message_handler(func=lambda m: is_admin(m.from_user.id) and m.text == "📊 Thống kê")
def admin_stats(msg):
    cur.execute("SELECT COUNT(*) FROM users")
    users = cur.fetchone()[0]
    cur.execute("SELECT SUM(total_deposit) FROM users")
    total = cur.fetchone()[0] or 0
    cur.execute("SELECT COUNT(*) FROM proxies")
    sold = cur.fetchone()[0]

    bot.send_message(msg.chat.id,
        f"""📊 THỐNG KÊ

👥 User: {users}
💰 Tổng nạp: {total:,}
🌐 Proxy bán: {sold}
📈 Thu nhập: {total:,}"""
    )

@bot.message_handler(func=lambda m: is_admin(m.from_user.id) and m.text == "👥 Người dùng")
def admin_users(msg):
    cur.execute("SELECT user_id, balance, total_deposit FROM users ORDER BY total_deposit DESC LIMIT 10")
    rows = cur.fetchall()

    if not rows:
        bot.send_message(msg.chat.id, "👥 CHƯA CÓ USER NÀO")
        return

    text = "👥 **DANH SÁCH USER (TOP 10)**\n\n"

    for uid, balance, total in rows:
        text += (
            f"🆔 {uid}\n"
            f"💰 Số dư: {balance:,} VND\n"
            f"💳 Tổng nạp: {total:,} VND\n"
            "──────────────\n"
        )

    bot.send_message(msg.chat.id, text, parse_mode="Markdown")

@bot.message_handler(func=lambda m: is_admin(m.from_user.id) and m.text == "⚙️ Cấu hình")
def admin_cfg(msg):
    bot.send_message(msg.chat.id,
        "⚙️ CẤU HÌNH\n💰 4,000 VND / ngày\n⏱ 24 giờ\n🏦 CAKE"
    )

@bot.callback_query_handler(func=lambda c: c.data == "back_user_menu")
def back_menu(call):
    bot.send_message(
        call.from_user.id,
        "⬅️ Quay về menu",
        reply_markup=user_menu()
    )

@bot.callback_query_handler(func=lambda c: c.data.startswith("duyet_nap_"))
def admin_duyet_nap(call):
    did = int(call.data.split("_")[-1])

    cur.execute(
        "SELECT user_id, amount FROM deposits WHERE id=? AND status='pending'",
        (did,)
    )
    d = cur.fetchone()
    if not d:
        bot.answer_callback_query(call.id, "❌ Giao dịch không hợp lệ")
        return

    uid, amount = d

    # 🔥 ĐẢM BẢO USER TỒN TẠI
    get_user(uid)

    cur.execute("UPDATE deposits SET status='success' WHERE id=?", (did,))
    cur.execute(
        "UPDATE users SET balance = balance + ?, total_deposit = total_deposit + ? WHERE user_id = ?",
        (amount, amount, uid)
    )
    conn.commit()

    bot.send_message(uid, f"✅ Nạp thành công: {amount:,} VND")
    bot.edit_message_text("✅ ĐÃ DUYỆT", call.message.chat.id, call.message.message_id)
    bot.answer_callback_query(call.id)

@bot.callback_query_handler(func=lambda c: c.data.startswith("tu_choi_"))
def admin_tu_choi(call):
    did = int(call.data.split("_")[-1])

    # Lấy thông tin giao dịch
    cur.execute(
        "SELECT user_id, amount FROM deposits WHERE id=? AND status='pending'",
        (did,)
    )
    d = cur.fetchone()

    if not d:
        bot.answer_callback_query(call.id, "❌ Giao dịch không hợp lệ")
        return

    uid, amount = d

    # Update trạng thái
    cur.execute("UPDATE deposits SET status='reject' WHERE id=?", (did,))
    conn.commit()

    # 🔔 THÔNG BÁO USER
    bot.send_message(
        uid,
        "❌ NẠP TIỀN THẤT BẠI\n\n"
        f"💵 Số tiền: {amount:,} VND\n"
        "📌 Lý do có thể:\n"
        "- Sai nội dung chuyển khoản\n"
        "- Admin chưa nhận được tiền\n\n"
        "👉 Nếu đã chuyển đúng, vui lòng liên hệ hỗ trợ."
    )

    # Update message admin
    bot.edit_message_text(
        "❌ ĐÃ TỪ CHỐI",
        call.message.chat.id,
        call.message.message_id


    )

    bot.answer_callback_query(call.id)

@bot.callback_query_handler(func=lambda c: c.data == "confirm_buy_proxy")
def confirm_buy_proxy(call):
    uid = call.from_user.id

    if uid not in buy_proxy_state:
        bot.answer_callback_query(call.id, "Phiên đã hết hạn")
        return

    days = buy_proxy_state[uid]["days"]
    total_price = days * PROXY_PRICE_PER_DAY

    cur.execute("SELECT balance FROM users WHERE user_id=?", (uid,))
    row = cur.fetchone()
    balance = row[0] if row else 0

    if balance < total_price:
        bot.send_message(uid, "❌ Số dư không đủ")
        bot.answer_callback_query(call.id)
        buy_proxy_state.pop(uid, None)
        return

    bot.edit_message_text(
        "⏳ Đang tự động mua proxy...",
        call.message.chat.id,
        call.message.message_id
    )

    ok, proxy, expire_time = mua_proxy_tu_dong(days)

    if not ok:
        bot.send_message(uid, f"❌ Mua proxy thất bại:\n{proxy}")
        bot.answer_callback_query(call.id)
        buy_proxy_state.pop(uid, None)
        return

    # Trừ tiền
    cur.execute(
        "UPDATE users SET balance = balance - ? WHERE user_id=?",
        (total_price, uid)
    )

    cur.execute(
        "INSERT INTO proxies (user_id, proxy, expire_time) VALUES (?,?,?)",
        (uid, proxy, expire_time)
    )
    conn.commit()

    buy_proxy_state.pop(uid, None)

    bot.send_message(
        uid,
        f"""✅ **MUA PROXY THÀNH CÔNG**

    🌐 Proxy:
    `{proxy}`

    ⏳ Hết hạn:
    {datetime.fromtimestamp(expire_time).strftime('%d/%m/%Y %H:%M')}

    📌 Định dạng: ip:port:user:pass
    """,
        parse_mode="Markdown",
        reply_markup=user_menu()
    )

@bot.callback_query_handler(func=lambda c: c.data == "cancel_buy_proxy")
def cancel_buy_proxy(call):
    uid = call.from_user.id
    buy_proxy_state.pop(uid, None)

    bot.answer_callback_query(call.id, "Đã hủy mua proxy")
    bot.send_message(
        uid,
        "❌ Đã hủy mua proxy",
        reply_markup=user_menu()
    )

@bot.message_handler(func=lambda m: m.text == "⬅️ Quay lại")
def back_to_menu(msg):
    uid = msg.from_user.id
    buy_proxy_state.pop(uid, None)
    bot.send_message(uid, "⬅️ Menu chính", reply_markup=user_menu())

# ================= RUN =================
print("BOT RUNNING...")
bot.infinity_polling()

