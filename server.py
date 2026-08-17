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
    # ega qo'shsa ok, boshqa wait
    u = db.get_user(who_id)
    st = "ok" if (u and u["role"] == "ega") else "wait"
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

# ---------- bot ishga tushirish ----------
bot.start_bot_thread()

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8080))
    app.run(host="0.0.0.0", port=port)
