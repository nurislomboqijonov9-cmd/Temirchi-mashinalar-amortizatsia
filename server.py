import os, time, requests
from flask import Flask, request, jsonify, send_from_directory
import db, bot

app = Flask(__name__)
db.init_db()

DATA_DIR2 = os.environ.get("DATA_DIR", "/data")
if not os.path.isdir(DATA_DIR2):
    DATA_DIR2 = os.path.dirname(os.path.abspath(__file__))

OWNER_ID = int(os.environ.get("OWNER_ID", "7589459697"))
KIRISH_KODI = os.environ.get("KIRISH_KODI", "Temirchi-2015")

# ega yozib qo'yiladi
db.set_owner(OWNER_ID)

# ilk ishga tushganda 3 moshina avtomat qo'shiladi (baza bo'sh bo'lsa)
if not db.all_cars():
    db.add_car("Labo-1", "10 240 VCA", "Davron",   12000, 6000000, 50)
    db.add_car("Labo-2", "10 562 VCA", "Saidolim", 12000, 6000000, 50)
    db.add_car("Gazel",  "10 067 VCA", "Nodir",    18000, 6500000, 100)
    print("3 moshina qo'shildi (Davron, Saidolim, Nodir)")

# ---------- KURS (cbu.uz avtomat + qo'lda tuzatish) ----------
def fetch_kurs():
    """cbu.uz dan rasmiy kurs; qo'lda qo'yilgan bo'lsa o'sha ishlatiladi."""
    manual = db.get_setting("kurs_manual")
    if manual:
        try: return int(float(manual))
        except: pass
    # avtomat
    cached = db.get_setting("kurs_auto")
    cached_ts = db.get_setting("kurs_auto_ts")
    now = int(time.time())
    if cached and cached_ts and now - int(cached_ts) < 6*3600:
        return int(float(cached))
    try:
        r = requests.get("https://cbu.uz/uz/arkhiv-kursov-valyut/json/USD/", timeout=10)
        rate = float(r.json()[0]["Rate"])
        db.set_setting("kurs_auto", int(rate))
        db.set_setting("kurs_auto_ts", now)
        return int(rate)
    except Exception as e:
        print("kurs err", e)
        return int(float(cached)) if cached else 12000

# ---------- auth helper ----------
def check_code():
    code = request.headers.get("X-Code") or request.args.get("code")
    return code == KIRISH_KODI

# ---------- static: web ilova ----------
@app.route("/")
def index():
    return send_from_directory(".", "moshina.html")

@app.route("/logo.png")
def logo():
    return send_from_directory(".", "logo.png")

# ---------- API: hamma ma'lumot ----------
@app.route("/api/data")
def api_data():
    if not check_code():
        return jsonify({"err": "kod"}), 401
    uid = request.args.get("uid")
    me = {"role": "ega", "tg_id": OWNER_ID, "car_id": None}  # web kod = ega
    if uid:
        try:
            u = db.get_user(int(uid))
            if u:
                # nofaol yoki rad qilingan odam kira olmaydi
                if u["role"] in ("nofaol", "rad", "kutilmoqda"):
                    return jsonify({"err": "bloklangan", "role": u["role"]}), 403
                me = {"role": u["role"], "tg_id": u["tg_id"], "car_id": u["car_id"], "name": u["name"]}
        except: pass
    return jsonify({
        "cars": db.all_cars(),
        "logs": db.all_logs(),
        "salary": db.all_salary(),
        "users": db.all_users(),
        "kurs": fetch_kurs(),
        "owner_id": OWNER_ID,
        "me": me,
    })

@app.route("/api/log", methods=["POST"])
def api_add_log():
    if not check_code():
        return jsonify({"err": "kod"}), 401
    d = request.json
    who_id = int(d.get("who_id", 0))
    rol = d.get("rol", "")
    # faqat HAQIQIY ega qo'shsa "ok" — haydovchi rejimida bo'lsa doim "wait"
    u = db.get_user(who_id)
    is_ega = (rol == "ega") and (who_id == OWNER_ID or (u and u["role"] == "ega"))
    st = "ok" if is_ega else "wait"
    katta = 1 if (d["t"] == "tamir" and int(d["amt"]) >= 800000) else 0
    chek_img = d.get("chek_img")
    chek_flag = 1 if chek_img else int(d.get("chek",0))
    log_id = db.add_log(d["car_id"], d["t"], int(d["amt"]), d.get("note",""),
                        d.get("pul","naqd"), d.get("who","?"), who_id,
                        st=st, chek=chek_flag, katta=katta, chek_img=chek_img)
    # wait bo'lsa egaga xabar
    if st == "wait":
        try: bot.notify_owner_newlog(log_id)
        except Exception as e: print("notify err", e)
    return jsonify({"ok": True, "id": log_id, "st": st})

@app.route("/api/log/state", methods=["POST"])
def api_log_state():
    if not check_code():
        return jsonify({"err": "kod"}), 401
    d = request.json
    db.set_log_state(int(d["id"]), d["st"], d.get("rej"))
    return jsonify({"ok": True})

@app.route("/api/log/delete", methods=["POST"])
def api_log_delete():
    if not check_code():
        return jsonify({"err": "kod"}), 401
    d = request.json
    db.delete_log(int(d["id"]))
    return jsonify({"ok": True})

@app.route("/api/log/edit", methods=["POST"])
def api_log_edit():
    if not check_code():
        return jsonify({"err": "kod"}), 401
    d = request.json
    db.edit_log(int(d["id"]), int(d["amt"]), d.get("note",""), d.get("pul"))
    return jsonify({"ok": True})

@app.route("/api/salary", methods=["POST"])
def api_salary():
    if not check_code():
        return jsonify({"err": "kod"}), 401
    d = request.json
    if d.get("action") == "oylik_ozgar":
        db.update_car(int(d["car_id"]), "oylik", int(d["amt"]))
    else:
        db.add_salary(int(d["car_id"]), d["t"], int(d["amt"]), d.get("note",""))
    return jsonify({"ok": True})

@app.route("/api/car", methods=["POST"])
def api_car():
    if not check_code():
        return jsonify({"err": "kod"}), 401
    d = request.json
    if d.get("action") == "add":
        cid = db.add_car(d["name"], d.get("raqam",""), d.get("driver",""),
                         int(d.get("olindi",0)), int(d.get("oylik",0)), int(d.get("amort",50)))
        return jsonify({"ok": True, "id": cid})
    elif d.get("action") == "delete":
        db.delete_car(int(d["car_id"]))
        return jsonify({"ok": True})
    else:
        db.update_car(int(d["car_id"]), d["field"], d["value"])
        return jsonify({"ok": True})

# ---------- odamlarni boshqarish ----------
@app.route("/api/user", methods=["POST"])
def api_user():
    if not check_code():
        return jsonify({"err": "kod"}), 401
    d = request.json
    act = d.get("action")
    tg_id = int(d["tg_id"])
    if act == "role":
        # rol o'zgartirish (haydovchi/nazoratchi)
        db.set_user_role(tg_id, d["role"], d.get("car_id"))
    elif act == "car":
        # haydovchini boshqa moshinaga
        db.set_user_car(tg_id, int(d["car_id"]) if d.get("car_id") else None)
    elif act == "deactivate":
        db.deactivate_user(tg_id)  # nofaol (chiqarish)
    elif act == "reactivate":
        db.reactivate_user(tg_id)  # qayta tiklash
    return jsonify({"ok": True})

# chek rasm saqlash (base64) -> faylga
@app.route("/api/chek", methods=["POST"])
def api_chek():
    if not check_code():
        return jsonify({"err": "kod"}), 401
    import base64, uuid
    d = request.json
    img = d.get("img","")  # data:image/...;base64,XXXX
    if "," in img: img = img.split(",",1)[1]
    try:
        raw = base64.b64decode(img)
        if len(raw) > 3_000_000:  # 3MB limit
            return jsonify({"err": "katta"}), 400
        cheklar_dir = os.path.join(DATA_DIR2, "cheklar")
        os.makedirs(cheklar_dir, exist_ok=True)
        fn = uuid.uuid4().hex + ".jpg"
        with open(os.path.join(cheklar_dir, fn), "wb") as f:
            f.write(raw)
        return jsonify({"ok": True, "img": fn})
    except Exception as e:
        return jsonify({"err": str(e)}), 400

@app.route("/chek/<fn>")
def get_chek(fn):
    cheklar_dir = os.path.join(DATA_DIR2, "cheklar")
    return send_from_directory(cheklar_dir, fn)

@app.route("/api/excel")
def api_excel():
    if not check_code():
        return jsonify({"err": "kod"}), 401
    from flask import Response
    cars = {c["id"]: c for c in db.all_cars()}
    logs = db.all_logs()
    rows = ["Sana,Moshina,Haydovchi,Tur,Summa,Pul holati,Holat,Izoh"]
    TYPE = {"yolkira":"Yo'lkira","gaz":"Gaz","ovqat":"Ovqat","tamir":"Ta'mir","yuvish":"Yuvish","shina":"Shina","moy":"Moy","shtraf":"Shtraf","zapchast":"Zapchast"}
    import datetime
    for l in logs:
        car = cars.get(l["car_id"], {})
        dt = datetime.datetime.fromtimestamp(l["ts"]+5*3600).strftime("%Y-%m-%d %H:%M")
        tn = TYPE.get(l["t"], l["t"])
        pul = "Naqd" if l["pul"]=="naqd" else ("Ish qildi" if l["pul"]=="bonus" else "")
        st = {"ok":"Tasdiqlangan","wait":"Kutmoqda","no":"Rad"}.get(l["st"], l["st"])
        note = (l["note"] or "").replace(",", " ")
        rows.append(f'{dt},{car.get("name","")},{car.get("driver","")},{tn},{l["amt"]},{pul},{st},{note}')
    csv = "\uFEFF" + "\n".join(rows)
    return Response(csv, mimetype="text/csv",
                    headers={"Content-Disposition": "attachment; filename=temirchi_moshina.csv"})
def api_kurs():
    if not check_code():
        return jsonify({"err": "kod"}), 401
    d = request.json
    if d.get("manual"):
        db.set_setting("kurs_manual", int(d["value"]))
    else:
        db.set_setting("kurs_manual", "")  # avtomatga qaytar
    return jsonify({"ok": True, "kurs": fetch_kurs()})

# ==================== GPS ROUTES ====================
import datetime as _dt
def _osmand_vaqt(ts):
    try:
        if ts is None: raise ValueError
        ts = str(ts)
        if ts.isdigit():
            d = _dt.datetime.fromtimestamp(int(ts), db.TZ)
        else:
            d = _dt.datetime.fromisoformat(ts.replace("Z","+00:00")).astimezone(db.TZ)
        return d.strftime("%Y-%m-%dT%H:%M:%S")
    except Exception:
        return db.now_tk().strftime("%Y-%m-%dT%H:%M:%S")

def _tg_msg(chat_id, matn):
    try:
        import bot as _b
        if _b.BOT_TOKEN:
            requests.post(f"https://api.telegram.org/bot{_b.BOT_TOKEN}/sendMessage",
                          json={"chat_id":chat_id,"text":matn,"parse_mode":"HTML"}, timeout=10)
    except Exception as e:
        print("tg_msg err", e)

# haydovchi GPS yuboradi (kuzat.html dan)
@app.route("/api/gps", methods=["POST"])
def api_gps():
    b = request.json or {}
    car = db.car_by_kuzat_token(b.get("token") or "")
    if not car:
        return jsonify({"ok": False, "xato": "token"}), 404
    n = db.gps_qosh(car["id"], b.get("points") or [])
    if db.car_seen(car["id"]) and OWNER_ID:
        _tg_msg(OWNER_ID, f"🟢 <b>{car.get('driver') or car.get('name')}</b> — qayta ulandi")
    # haydovchiga biriktirilgan faol yetkazish bormi?
    y = db.yetkazish_faol_car(car["id"])
    manzil = None
    if y:
        manzil = {"lat": y["mlat"], "lon": y["mlon"], "izoh": y.get("izoh") or "", "token": y["token"]}
    return jsonify({"ok": True, "saqlandi": n, "yetkazish": manzil})

# haydovchi yetkazishni yakunladi (yetib bordim)
@app.route("/api/yetkazish_yetdi", methods=["POST"])
def api_yetkazish_yetdi():
    b = request.json or {}
    car = db.car_by_kuzat_token(b.get("token") or "")
    if not car: return jsonify({"ok": False}), 404
    y = db.yetkazish_faol_car(car["id"])
    if y:
        db.yetkazish_yakunla(y["token"])
        if OWNER_ID:
            _tg_msg(OWNER_ID, f"✅ <b>{car.get('driver') or car.get('name')}</b> — mijozga yetkazib berdi!")
    return jsonify({"ok": True})

# Traccar/OsmAnd fon GPS (id = gps_kod)
@app.route("/osmand", methods=["GET","POST"])
def osmand():
    q = dict(request.args)
    if request.method == "POST":
        try:
            for k,v in request.form.items(): q.setdefault(k,v)
        except Exception: pass
    dev = (q.get("id") or q.get("deviceid") or "").strip()
    car = db.car_by_gps_kod(dev) or db.car_by_kuzat_token(dev)
    if not car:
        return "unknown device", 400
    lat=q.get("lat"); lon=q.get("lon")
    if (lat is None or lon is None) and q.get("location"):
        try: lat,lon = q["location"].split(",")[:2]
        except Exception: pass
    if lat is None or lon is None:
        db.car_seen(car["id"]); return "ok", 200
    try: lat=float(lat); lon=float(lon)
    except Exception: return "ok", 200
    try: acc=float(q.get("accuracy") or q.get("hdop") or 0)
    except Exception: acc=0.0
    vaqt=_osmand_vaqt(q.get("timestamp"))
    db.gps_qosh(car["id"], [{"lat":lat,"lon":lon,"vaqt":vaqt,"acc":acc}])
    if db.car_seen(car["id"]) and OWNER_ID:
        _tg_msg(OWNER_ID, f"🟢 <b>{car.get('driver') or car.get('name')}</b> — qayta ulandi")
    return "ok", 200

# ping (heartbeat)
@app.route("/api/ping", methods=["POST"])
def api_ping():
    b = request.json or {}
    car = db.car_by_kuzat_token(b.get("token") or "")
    if not car: return jsonify({"ok": False}), 404
    if db.car_seen(car["id"]) and OWNER_ID:
        _tg_msg(OWNER_ID, f"🟢 <b>{car.get('driver') or car.get('name')}</b> — qayta ulandi")
    return jsonify({"ok": True})

# haydovchi kuzat ilovasida pul kiritadi (token bilan) -> wait, egaga xabar
@app.route("/api/gps_pul", methods=["POST"])
def api_gps_pul():
    b = request.json or {}
    car = db.car_by_kuzat_token(b.get("token") or "")
    if not car: return jsonify({"ok": False}), 404
    katta = 1 if (b.get("t") == "tamir" and int(b.get("amt",0)) >= 800000) else 0
    log_id = db.add_log(car["id"], b.get("t"), int(b["amt"]), b.get("note",""),
                        b.get("pul","naqd"), car.get("driver") or car.get("name"), 0,
                        st="wait", katta=katta)
    try: bot.notify_owner_newlog(log_id)
    except Exception as e: print("notify err", e)
    return jsonify({"ok": True, "id": log_id})

# ega uchun: hamma haydovchi joylashuvi
@app.route("/api/haydovchilar")
def api_haydovchilar():
    if not check_code(): return jsonify({"err":"kod"}), 401
    res=[]
    for c in db.all_cars():
        g = db.gps_oxirgi(c["id"])
        online = db.car_online(c["id"])
        res.append({
            "id":c["id"], "ism":c["driver"], "moshina":c["name"], "raqam":c.get("raqam",""),
            "online":online, "gps":g,
            "yosh_daq": (round(db.gps_age_daqiqa(g["vaqt"]),1) if g else None),
            "kod": db.car_gps_kod(c["id"]),
        })
    return jsonify({"haydovchilar":res})

# bitta haydovchi kunlik yo'l (harita uchun)
@app.route("/api/haydovchi_kuzat")
def api_haydovchi_kuzat():
    if not check_code(): return jsonify({"err":"kod"}), 401
    cid=int(request.args.get("id",0))
    sana=request.args.get("sana") or str(db.today_tk())
    return jsonify(db.kunlik_xulosa(cid, sana))

# harita.html uchun — kunlik nuqtalar + to'xtashlar (issiqlik, yo'l, to'xtash)
@app.route("/api/gps_view")
def api_gps_view():
    # X-Token yoki kod bilan
    tok = request.headers.get("X-Token") or request.args.get("code")
    if tok != KIRISH_KODI:
        return jsonify({"err":"kod"}), 401
    cid=int(request.args.get("hid",0))
    sana=request.args.get("sana") or str(db.today_tk())
    x = db.kunlik_xulosa(cid, sana)
    return jsonify({"nuqtalar":x["nuqtalar"], "toxtashlar":x["toxtashlar"], "km":x["km"]})

# harita sahifasi (issiqlik, yo'l, to'xtashlar)
@app.route("/harita")
def harita_page():
    return send_from_directory(".", "harita.html")

# haydovchiga kuzat token/kod berish
@app.route("/api/haydovchi_kod")
def api_haydovchi_kod():
    if not check_code(): return jsonify({"err":"kod"}), 401
    cid=int(request.args.get("id",0))
    return jsonify({"token":db.car_gps_token(cid), "kod":db.car_gps_kod(cid), "share":db.car_share_token(cid)})

# ---- kuzat.html (haydovchi GPS yuboradigan sahifa) ----
@app.route("/kuzat")
def kuzat_page():
    return send_from_directory(".", "kuzat.html")

@app.route("/kuzat/<token>")
def kuzat_page_token(token):
    return send_from_directory(".", "kuzat.html")

@app.route("/api/kuzat_kirish", methods=["POST"])
def api_kuzat_kirish():
    b=request.json or {}
    car=db.car_by_gps_kod(str(b.get("kod","")).strip())
    if not car: return jsonify({"ok":False}), 404
    return jsonify({"ok":True, "token":db.car_gps_token(car["id"]),
                    "ism":car["driver"], "moshina":car["name"]})

# ---- jonli kuzatuv (ega) ----
@app.route("/jonli")
def jonli_page():
    return send_from_directory(".", "jonli.html")

@app.route("/jonli/<token>")
def jonli_page_token(token):
    return send_from_directory(".", "jonli.html")

@app.route("/api/jonli")
def api_jonli():
    # token (share) yoki id+code bilan
    token = request.args.get("token")
    if token and token != "jonli":
        car = db.car_by_share(token)
        if not car: return jsonify({"ok":False}), 404
        cid = car["id"]
    else:
        if not check_code(): return jsonify({"err":"kod"}), 401
        cid=int(request.args.get("id",0))
        car=[c for c in db.all_cars() if c["id"]==cid]
        car=car[0] if car else None
    g=db.gps_oxirgi(cid)
    return jsonify({"ok":True, "gps":g, "nuqta":g, "online":db.car_online(cid),
                    "ism":(car["driver"] if car else ""), "haydovchi":(car["driver"] if car else ""),
                    "moshina":(car["name"] if car else "")})

# ---- mijozga jonli ssilka (yol.html) ----
@app.route("/yol/<token>")
def yol_page(token):
    return send_from_directory(".", "yol.html")

@app.route("/api/yol")
def api_yol():
    token=request.args.get("token","")
    y=db.yetkazish_get(token)
    if not y: return jsonify({"ok":False}), 404
    g=db.gps_oxirgi(y["car_id"])
    car=[c for c in db.all_cars() if c["id"]==y["car_id"]]
    return jsonify({"ok":True, "holat":y["holat"],
                    "mijoz":{"lat":y["mlat"],"lon":y["mlon"]}, "izoh":y.get("izoh"),
                    "haydovchi":g, "ism":(car[0]["driver"] if car else "Haydovchi"),
                    "online":db.car_online(y["car_id"])})

# mijozga ssilka yaratish (ega)
@app.route("/api/yetkazish", methods=["POST"])
def api_yetkazish():
    if not check_code(): return jsonify({"err":"kod"}), 401
    b=request.json or {}
    car_id=int(b["car_id"])
    lat=float(b["lat"]); lon=float(b["lon"])
    izoh=b.get("izoh") or ""
    soat=b.get("soat") or ""  # mijozga yetkazish vaqti (ixtiyoriy)
    tok=db.yetkazish_qosh(car_id, lat, lon, izoh)
    base=os.environ.get("WEBAPP_URL","").rstrip("/")
    url=f"{base}/yol/{tok}"
    # haydovchiga Telegram xabar
    car=[c for c in db.all_cars() if c["id"]==car_id]
    car=car[0] if car else None
    if car:
        # shu moshinaga biriktirilgan haydovchi(lar)ni topamiz
        hayd = [u for u in db.all_users() if u.get("car_id")==car_id and u["role"]=="haydovchi"]
        xabar = (f"📦 <b>Yangi yetkazib berish!</b>\n\n"
                 f"🚚 Moshina: {car['name']}\n"
                 f"📍 Mahsulotni belgilangan manzilga yetkazing\n"
                 + (f"🕐 Yetkazish vaqti: <b>{soat}</b>\n" if soat else "")
                 + (f"📝 Izoh: {izoh}\n" if izoh else "")
                 + f"\n🗺 Manzil xaritada: https://www.google.com/maps?q={lat},{lon}\n"
                 + f"\nMijoz sizni jonli kuzatmoqda — GPS yoniq bo'lsin!")
        for h in hayd:
            _tg_msg(h["tg_id"], xabar)
        if not hayd and OWNER_ID:
            _tg_msg(OWNER_ID, f"⚠️ {car['name']} haydovchisi botga ulanmagan — xabar yuborilmadi. Havolani qo'lda bering.")
    return jsonify({"ok":True, "token":tok, "url":url})

@app.route("/api/yetkazish_yakun", methods=["POST"])
def api_yetkazish_yakun():
    if not check_code(): return jsonify({"err":"kod"}), 401
    b=request.json or {}
    db.yetkazish_yakunla(b.get("token",""))
    return jsonify({"ok":True})

# GPS iconlar (PWA)
@app.route("/icon-180.png")
def icon180(): return send_from_directory(".", "icon-180.png")
@app.route("/icon-192.png")
def icon192(): return send_from_directory(".", "icon-192__2_.png")
@app.route("/icon-512.png")
def icon512(): return send_from_directory(".", "icon-512__2_.png")

# Service worker (fon GPS)
@app.route("/sw-gps.js")
def sw_gps():
    return send_from_directory(".", "sw-gps.js", mimetype="application/javascript")

# Haydovchi ilovasi manifest (PWA — bosh ekranga o'rnatish)
@app.route("/manifest-hayd.json")
def manifest_hayd():
    return jsonify({
        "name":"TEMIRCHI Haydovchi","short_name":"TEMIRCHI","start_url":"/kuzat",
        "display":"standalone","background_color":"#0f1720","theme_color":"#0f1720",
        "icons":[{"src":"/icon-192.png","sizes":"192x192","type":"image/png"},
                 {"src":"/icon-512.png","sizes":"512x512","type":"image/png"}]
    })

# ---------- bot ishga tushirish ----------
bot.start_bot_thread()

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8080))
    app.run(host="0.0.0.0", port=port)
