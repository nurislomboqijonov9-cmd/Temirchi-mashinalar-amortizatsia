import os, time, json, threading, requests
import db

BOT_TOKEN = os.environ.get("BOT_TOKEN", "")
OWNER_ID = int(os.environ.get("OWNER_ID", "7589459697"))
WEBAPP_URL = os.environ.get("WEBAPP_URL", "")  # web ilova manzili (oxirida / yo'q)

API = f"https://api.telegram.org/bot{BOT_TOKEN}"

def _api(method, **params):
    try:
        r = requests.post(f"{API}/{method}", json=params, timeout=20)
        return r.json()
    except Exception as e:
        print("api err", e)
        return {}

def send(chat_id, text, keyboard=None, web_button=False):
    kb = None
    if keyboard:
        kb = {"inline_keyboard": keyboard}
    elif web_button and WEBAPP_URL:
        # URL ga foydalanuvchi ID qo'shamiz -> ilova kim ekanini biladi
        url = WEBAPP_URL + ("&" if "?" in WEBAPP_URL else "?") + f"uid={chat_id}"
        kb = {"inline_keyboard": [[{"text": "📊 Ilovani ochish", "web_app": {"url": url}}]]}
    params = {"chat_id": chat_id, "text": text, "parse_mode": "HTML"}
    if kb:
        params["reply_markup"] = kb
    return _api("sendMessage", **params)

def answer_cb(cb_id, text=""):
    _api("answerCallbackQuery", callback_query_id=cb_id, text=text)

# ---------- START: yangi odam -> egaga so'rov ----------
def handle_start(user):
    tg_id = user["id"]
    name = user.get("first_name", "") + " " + user.get("last_name", "")
    name = name.strip() or user.get("username", "Nomsiz")

    # ega bo'lsa
    if tg_id == OWNER_ID:
        db.set_owner(tg_id)
        send(tg_id, "👑 Assalomu alaykum, <b>Ega</b>!\nMoshina hisobot tizimi.", web_button=True)
        return

    u = db.get_user(tg_id)
    if u and u["role"] == "ega":
        send(tg_id, "👑 Xush kelibsiz, Ega!", web_button=True)
        return
    if u and u["role"] in ("haydovchi", "nazoratchi"):
        rol = "🚗 Haydovchi" if u["role"] == "haydovchi" else "👁 Nazoratchi"
        send(tg_id, f"✅ Xush kelibsiz! Siz: {rol}", web_button=True)
        return
    if u and u["role"] == "rad":
        send(tg_id, "❌ Sizga ruxsat berilmagan.")
        return
    if u and u["role"] == "nofaol":
        send(tg_id, "⛔ Hisobingiz vaqtincha to'xtatilgan. Ega bilan bog'laning.")
        return
    if u and u["role"] == "kutilmoqda":
        send(tg_id, "⏳ So'rovingiz hali ko'rib chiqilmoqda. Iltimos kuting.")
        return

    # yangi -> pending qo'shamiz va egaga yuboramiz
    db.add_pending_user(tg_id, name)
    send(tg_id, "⏳ So'rovingiz egaga yuborildi.\nTasdiqlansa, xabar beramiz.")
    # egaga so'rov
    kb = [
        [{"text": "🚗 Haydovchi", "callback_data": f"ok_haydovchi_{tg_id}"},
         {"text": "👁 Nazoratchi", "callback_data": f"ok_nazoratchi_{tg_id}"}],
        [{"text": "❌ Rad etish", "callback_data": f"ok_rad_{tg_id}"}]
    ]
    send(OWNER_ID, f"👤 <b>Yangi odam</b> botga kirdi:\n\n<b>{name}</b>\nID: <code>{tg_id}</code>\n\nKim bu?", keyboard=kb)

# ---------- tasdiqlash (ega bosadi) ----------
def handle_callback(cb):
    data = cb["data"]
    from_id = cb["from"]["id"]
    cb_id = cb["id"]

    if from_id != OWNER_ID:
        answer_cb(cb_id, "Faqat ega tasdiqlaydi")
        return

    # ok_haydovchi_123 / ok_nazoratchi_123 / ok_rad_123
    if data.startswith("ok_"):
        parts = data.split("_")
        role = parts[1]
        target = int(parts[2])
        u = db.get_user(target)
        nm = u["name"] if u else str(target)

        if role == "rad":
            db.set_user_role(target, "rad")
            answer_cb(cb_id, "Rad etildi")
            send(OWNER_ID, f"❌ {nm} rad etildi.")
            send(target, "❌ Kechirasiz, sizga ruxsat berilmadi.")
            return

        if role == "nazoratchi":
            db.set_user_role(target, "nazoratchi")
            answer_cb(cb_id, "Nazoratchi qilindi")
            send(OWNER_ID, f"✅ {nm} — 👁 Nazoratchi qilindi.")
            send(target, "✅ Siz <b>Nazoratchi</b> sifatida tasdiqlandingiz!", web_button=True)
            return

        if role == "haydovchi":
            # qaysi moshina? -> moshina tanlash
            cars = db.all_cars()
            if not cars:
                db.set_user_role(target, "haydovchi", None)
                answer_cb(cb_id, "Haydovchi qilindi")
                send(target, "✅ Siz <b>Haydovchi</b> sifatida tasdiqlandingiz!", web_button=True)
                return
            kb = [[{"text": f"{c['name']} ({c['raqam']})", "callback_data": f"car_{target}_{c['id']}"}] for c in cars]
            answer_cb(cb_id)
            send(OWNER_ID, f"🚗 {nm} qaysi moshinada?", keyboard=kb)
            return

    # car_123_2 -> haydovchini moshinaga biriktirish
    if data.startswith("car_"):
        parts = data.split("_")
        target = int(parts[1]); car_id = int(parts[2])
        db.set_user_role(target, "haydovchi", car_id)
        u = db.get_user(target); nm = u["name"] if u else str(target)
        cars = {c["id"]: c for c in db.all_cars()}
        cname = cars.get(car_id, {}).get("name", "?")
        answer_cb(cb_id, "Biriktirildi")
        send(OWNER_ID, f"✅ {nm} — 🚗 {cname} haydovchisi qilindi.")
        send(target, f"✅ Siz <b>{cname}</b> haydovchisi sifatida tasdiqlandingiz!", web_button=True)
        return

    # log tasdiqlash: logok_5 / logno_5
    if data.startswith("logok_"):
        log_id = int(data.split("_")[1])
        l = db.get_log(log_id)
        if not l:
            answer_cb(cb_id, "Yozuv o'chirilgan")
            _api("editMessageReplyMarkup", chat_id=cb["message"]["chat"]["id"],
                 message_id=cb["message"]["message_id"], reply_markup={"inline_keyboard": []})
            return
        if l["st"] != "wait":
            # allaqachon hal qilingan (web yoki bot orqali)
            holat = "tasdiqlangan ✅" if l["st"]=="ok" else "rad etilgan ❌"
            answer_cb(cb_id, f"Allaqachon {holat}")
            _api("editMessageReplyMarkup", chat_id=cb["message"]["chat"]["id"],
                 message_id=cb["message"]["message_id"], reply_markup={"inline_keyboard": []})
            return
        db.set_log_state(log_id, "ok")
        answer_cb(cb_id, "Tasdiqlandi")
        _api("editMessageReplyMarkup", chat_id=cb["message"]["chat"]["id"],
             message_id=cb["message"]["message_id"], reply_markup={"inline_keyboard": []})
        send(OWNER_ID, "✅ Yozuv tasdiqlandi.")
        return
    if data.startswith("logno_"):
        log_id = int(data.split("_")[1])
        l = db.get_log(log_id)
        if not l:
            answer_cb(cb_id, "Yozuv o'chirilgan")
            _api("editMessageReplyMarkup", chat_id=cb["message"]["chat"]["id"],
                 message_id=cb["message"]["message_id"], reply_markup={"inline_keyboard": []})
            return
        if l["st"] != "wait":
            holat = "tasdiqlangan ✅" if l["st"]=="ok" else "rad etilgan ❌"
            answer_cb(cb_id, f"Allaqachon {holat}")
            _api("editMessageReplyMarkup", chat_id=cb["message"]["chat"]["id"],
                 message_id=cb["message"]["message_id"], reply_markup={"inline_keyboard": []})
            return
        db.set_log_state(log_id, "no", "Rad etildi")
        answer_cb(cb_id, "Rad etildi")
        _api("editMessageReplyMarkup", chat_id=cb["message"]["chat"]["id"],
             message_id=cb["message"]["message_id"], reply_markup={"inline_keyboard": []})
        send(OWNER_ID, "❌ Yozuv rad etildi.")
        return

# ---------- egaga yangi yozuv xabari (haydovchi qo'shganda) ----------
def notify_owner_newlog(log_id):
    l = db.get_log(log_id)
    if not l: return
    cars = {c["id"]: c for c in db.all_cars()}
    cname = cars.get(l["car_id"], {}).get("name", "?")
    TYPE = {"yolkira":"💵 Yo'lkira","gaz":"⛽ Gaz","ovqat":"🍽 Ovqat","tamir":"🔧 Ta'mir",
            "yuvish":"🚿 Yuvish","shina":"🛞 Shina","moy":"🛢 Moy","shtraf":"🚧 Shtraf","zapchast":"⚙️ Zapchast"}
    tn = TYPE.get(l["t"], l["t"])
    pul = ""
    if l["t"] == "yolkira":
        pul = " · 🟢 Naqd" if l["pul"] == "naqd" else " · 🟡 Ish qildi"
    txt = (f"🆕 <b>Yangi yozuv</b> (tasdiq kutmoqda)\n\n"
           f"🚗 {cname}\n{tn}: <b>{l['amt']:,}</b> so'm{pul}\n"
           f"{('📝 '+l['note']) if l['note'] else ''}\n🧑 {l['who']}")
    kb = [[{"text": "✅ Tasdiqlash", "callback_data": f"logok_{log_id}"},
           {"text": "❌ Rad etish", "callback_data": f"logno_{log_id}"}]]
    send(OWNER_ID, txt, keyboard=kb)

# ---------- 19:30 kunlik hisobot ----------
def daily_report():
    """Bugungi kun bo'yicha har moshina qancha ishladi."""
    import db as _db
    cars = {c["id"]: c for c in _db.all_cars()}
    logs = _db.all_logs()
    # bugungi (Toshkent UTC+5) boshlanishi
    tz = 5*3600
    now = int(time.time())
    day_start = ((now + tz) // 86400) * 86400 - tz
    TYPE = {"yolkira":"💵","gaz":"⛽","ovqat":"🍽","tamir":"🔧","yuvish":"🚿","shina":"🛞","moy":"🛢","shtraf":"🚧","zapchast":"⚙️"}
    lines = ["📊 <b>Bugungi kunlik hisobot</b>\n"]
    for cid, car in cars.items():
        rows = [l for l in logs if l["car_id"]==cid and l["st"]=="ok" and l["ts"]>=day_start]
        naqd = sum(l["amt"] for l in rows if l["t"]=="yolkira" and l["pul"]=="naqd")
        ish = sum(l["amt"] for l in rows if l["t"]=="yolkira" and l["pul"]=="bonus")
        xarajat = sum(l["amt"] for l in rows if l["t"]!="yolkira")
        if not rows:
            lines.append(f"🚗 <b>{car['name']}</b> ({car['driver']}) — yozuv yo'q")
            continue
        lines.append(f"🚗 <b>{car['name']}</b> ({car['driver']})\n"
                     f"   🟢 Naqd: {naqd:,} · 🟡 Ish: {ish:,} · 🔴 Xarajat: {xarajat:,}")
    send(OWNER_ID, "\n".join(lines))

def report_scheduler():
    """Har kuni 19:30 hisobot; har daqiqa GPS offline tekshiruvi (Toshkent)."""
    sent_today = None
    last_off_check = 0
    while True:
        try:
            tz = 5*3600
            t = time.time() + tz
            lt = time.gmtime(t)
            key = time.strftime("%Y-%m-%d", lt)
            # 19:30 kunlik hisobot
            if lt.tm_hour == 19 and lt.tm_min == 30 and sent_today != key:
                daily_report()
                sent_today = key
            # GPS offline tekshiruvi — har 60 sekundda
            if time.time() - last_off_check >= 60:
                last_off_check = time.time()
                check_gps_offline()
        except Exception as e:
            print("report err", e)
        time.sleep(30)

def check_gps_offline():
    """5 daqiqa signal bermagan (lekin ilgari faol bo'lgan) haydovchi -> botga bir marta xabar."""
    try:
        for c in db.all_cars():
            if not c.get("last_seen"):
                continue  # hech qachon ulanmagan — xabar bermaymiz
            online = db.car_online(c["id"], daqiqa=5)
            if not online and not c.get("offline_xabar"):
                # signal uzildi — bir marta xabar
                db.mark_offline_xabar(c["id"])
                haydovchi = c.get("driver") or c.get("name")
                send(OWNER_ID, f"🔴 <b>{haydovchi}</b> ({c['name']}) — GPS signal uzildi!\n"
                               f"5 daqiqadan beri joylashuv kelmayapti. Telefon o'chgan yoki ilova yopilgan bo'lishi mumkin.")
    except Exception as e:
        print("gps offline check err", e)

# ---------- polling ----------
def run_polling():
    if not BOT_TOKEN:
        print("BOT_TOKEN yo'q — bot ishlamaydi")
        return
    print("Bot ishga tushdi (polling)")
    offset = None
    while True:
        try:
            r = requests.get(f"{API}/getUpdates", params={"offset": offset, "timeout": 30}, timeout=40)
            data = r.json()
            for upd in data.get("result", []):
                offset = upd["update_id"] + 1
                if "message" in upd and upd["message"].get("text", "").startswith("/start"):
                    handle_start(upd["message"]["from"])
                elif "callback_query" in upd:
                    handle_callback(upd["callback_query"])
        except Exception as e:
            print("polling err", e)
            time.sleep(3)

def start_bot_thread():
    t = threading.Thread(target=run_polling, daemon=True)
    t.start()
    t2 = threading.Thread(target=report_scheduler, daemon=True)
    t2.start()
    return t
