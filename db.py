import sqlite3, os, time, threading, math, secrets
from datetime import datetime, timedelta, timezone

DATA_DIR = os.environ.get("DATA_DIR", "/data")
if not os.path.isdir(DATA_DIR):
    # lokal sinov uchun
    DATA_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(DATA_DIR, "moshina.db")

TZ = timezone(timedelta(hours=5))  # Asia/Tashkent
def now_tk(): return datetime.now(TZ)
def today_tk(): return now_tk().date()

_lock = threading.Lock()

def _conn():
    c = sqlite3.connect(DB_PATH, timeout=30)
    c.row_factory = sqlite3.Row
    c.execute("PRAGMA journal_mode=WAL")
    return c

def init_db():
    with _lock, _conn() as c:
        # foydalanuvchilar (ega tasdiqlaydi)
        c.execute("""CREATE TABLE IF NOT EXISTS users(
            tg_id INTEGER PRIMARY KEY,
            name TEXT,
            role TEXT DEFAULT 'kutilmoqda',   -- ega / haydovchi / nazoratchi / kutilmoqda / rad / nofaol
            car_id INTEGER,                    -- haydovchi qaysi moshinada
            prev_role TEXT,                    -- nofaol qilinganda eski rol
            created INTEGER
        )""")
        # eski bazaga prev_role ustunini qo'shish (migration)
        try:
            cols = [r[1] for r in c.execute("PRAGMA table_info(users)").fetchall()]
            if "prev_role" not in cols:
                c.execute("ALTER TABLE users ADD COLUMN prev_role TEXT")
        except Exception as e:
            print("migration prev_role:", e)
        # moshinalar
        c.execute("""CREATE TABLE IF NOT EXISTS cars(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT, raqam TEXT, driver TEXT,
            olindi INTEGER DEFAULT 0,
            sotilsa INTEGER DEFAULT 0,
            oylik INTEGER DEFAULT 0,
            amort INTEGER DEFAULT 50,
            b_kirim INTEGER DEFAULT 0,
            b_chiqim INTEGER DEFAULT 0,
            b_oylik INTEGER DEFAULT 0,
            b_sana TEXT
        )""")
        # eski cars jadvaliga boshlang'ich ustunlar (migration)
        try:
            ccols = [r[1] for r in c.execute("PRAGMA table_info(cars)").fetchall()]
            for col in ["b_kirim","b_chiqim","b_oylik"]:
                if col not in ccols:
                    c.execute(f"ALTER TABLE cars ADD COLUMN {col} INTEGER DEFAULT 0")
            if "b_sana" not in ccols:
                c.execute("ALTER TABLE cars ADD COLUMN b_sana TEXT")
        except Exception as e:
            print("migration cars:", e)
        # yozuvlar (yolkira/xarajat)
        c.execute("""CREATE TABLE IF NOT EXISTS logs(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            car_id INTEGER,
            t TEXT,           -- yolkira/gaz/ovqat/tamir/yuvish/shina/moy/shtraf/zapchast
            amt INTEGER,
            note TEXT,
            pul TEXT,         -- naqd / bonus (ish qildi)
            who TEXT,
            who_id INTEGER,
            ts INTEGER,
            st TEXT DEFAULT 'wait',  -- wait/ok/no
            rej TEXT,
            chek INTEGER DEFAULT 0,
            katta INTEGER DEFAULT 0,
            chek_img TEXT
        )""")
        # migratsiya: eski bazaga chek_img ustuni
        try:
            cols = [r[1] for r in c.execute("PRAGMA table_info(logs)").fetchall()]
            if "chek_img" not in cols:
                c.execute("ALTER TABLE logs ADD COLUMN chek_img TEXT")
        except Exception as e:
            print("migr err", e)
        # oylik/avans
        c.execute("""CREATE TABLE IF NOT EXISTS salary(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            car_id INTEGER,
            t TEXT,          -- oylik / avans
            amt INTEGER,
            note TEXT,
            ts INTEGER
        )""")
        # sozlama (kurs va h.k.)
        c.execute("""CREATE TABLE IF NOT EXISTS settings(
            k TEXT PRIMARY KEY, v TEXT
        )""")
        # ===== GPS: haydovchi joylashuvi (car_id bo'yicha) =====
        c.execute("""CREATE TABLE IF NOT EXISTS gps_nuqta(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            car_id INTEGER, lat REAL, lon REAL, vaqt TEXT, acc REAL
        )""")
        c.execute("CREATE INDEX IF NOT EXISTS ix_gps ON gps_nuqta(car_id, vaqt)")
        # GPS uchun moshinaga qo'shimcha ustunlar (kuzat tokeni, kod, last_seen)
        try:
            ccols2 = [r[1] for r in c.execute("PRAGMA table_info(cars)").fetchall()]
            for col, ddl in [("kuzat_token","TEXT"),("share_token","TEXT"),
                             ("gps_kod","TEXT"),("last_seen","TEXT"),("offline_xabar","INTEGER DEFAULT 0"),
                             ("tel","TEXT")]:
                if col not in ccols2:
                    c.execute(f"ALTER TABLE cars ADD COLUMN {col} {ddl}")
        except Exception as e:
            print("migration gps cars:", e)
        # yetkazish (mijozga jonli ssilka)
        c.execute("""CREATE TABLE IF NOT EXISTS yetkazish(
            token TEXT PRIMARY KEY, car_id INTEGER,
            mlat REAL, mlon REAL, izoh TEXT,
            holat TEXT DEFAULT 'faol', created TEXT, yakun TEXT
        )""")
        c.commit()

# ---------- users ----------
def get_user(tg_id):
    with _conn() as c:
        r = c.execute("SELECT * FROM users WHERE tg_id=?", (tg_id,)).fetchone()
        return dict(r) if r else None

def add_pending_user(tg_id, name):
    with _lock, _conn() as c:
        ex = c.execute("SELECT tg_id FROM users WHERE tg_id=?", (tg_id,)).fetchone()
        if not ex:
            c.execute("INSERT INTO users(tg_id,name,role,created) VALUES(?,?,'kutilmoqda',?)",
                      (tg_id, name, int(time.time())))
            c.commit()
            return True
        return False

def set_user_role(tg_id, role, car_id=None):
    with _lock, _conn() as c:
        c.execute("UPDATE users SET role=?, car_id=? WHERE tg_id=?", (role, car_id, tg_id))
        c.commit()

def set_owner(tg_id):
    with _lock, _conn() as c:
        ex = c.execute("SELECT tg_id FROM users WHERE tg_id=?", (tg_id,)).fetchone()
        if ex:
            c.execute("UPDATE users SET role='ega' WHERE tg_id=?", (tg_id,))
        else:
            c.execute("INSERT INTO users(tg_id,name,role,created) VALUES(?,?, 'ega',?)",
                      (tg_id, "Ega", int(time.time())))
        c.commit()

def all_users():
    with _conn() as c:
        return [dict(r) for r in c.execute("SELECT * FROM users ORDER BY created DESC").fetchall()]

def set_user_car(tg_id, car_id):
    with _lock, _conn() as c:
        c.execute("UPDATE users SET car_id=? WHERE tg_id=?", (car_id, tg_id))
        c.commit()

def deactivate_user(tg_id):
    # nofaol qilish: eski rolni saqlab, 'nofaol' qo'yamiz
    with _lock, _conn() as c:
        r = c.execute("SELECT role FROM users WHERE tg_id=?", (tg_id,)).fetchone()
        if r and r["role"] not in ("nofaol", "ega"):
            c.execute("UPDATE users SET role='nofaol', prev_role=? WHERE tg_id=?", (r["role"], tg_id))
            c.commit()

def reactivate_user(tg_id):
    # qayta tiklash: prev_role ga qaytaramiz
    with _lock, _conn() as c:
        r = c.execute("SELECT prev_role FROM users WHERE tg_id=?", (tg_id,)).fetchone()
        role = (r["prev_role"] if r and r["prev_role"] else "haydovchi")
        c.execute("UPDATE users SET role=? WHERE tg_id=?", (role, tg_id))
        c.commit()

# ---------- cars ----------
def all_cars():
    with _conn() as c:
        return [dict(r) for r in c.execute("SELECT * FROM cars ORDER BY id").fetchall()]

def add_car(name, raqam, driver, olindi=0, oylik=0, amort=50):
    with _lock, _conn() as c:
        cur = c.execute("INSERT INTO cars(name,raqam,driver,olindi,oylik,amort) VALUES(?,?,?,?,?,?)",
                        (name, raqam, driver, olindi, oylik, amort))
        c.commit()
        return cur.lastrowid

def update_car(car_id, field, value):
    if field not in ("name","raqam","driver","olindi","sotilsa","oylik","amort","b_kirim","b_chiqim","b_oylik","b_sana"):
        return
    with _lock, _conn() as c:
        c.execute(f"UPDATE cars SET {field}=? WHERE id=?", (value, car_id))
        c.commit()

# ---------- logs ----------
def add_log(car_id, t, amt, note, pul, who, who_id, st="wait", chek=0, katta=0, chek_img=None):
    with _lock, _conn() as c:
        cur = c.execute("""INSERT INTO logs(car_id,t,amt,note,pul,who,who_id,ts,st,chek,katta,chek_img)
                           VALUES(?,?,?,?,?,?,?,?,?,?,?,?)""",
                        (car_id, t, amt, note, pul, who, who_id, int(time.time()), st, chek, katta, chek_img))
        c.commit()
        return cur.lastrowid

def delete_car(car_id):
    with _lock, _conn() as c:
        c.execute("DELETE FROM cars WHERE id=?", (car_id,))
        c.commit()

def set_log_state(log_id, st, rej=None):
    with _lock, _conn() as c:
        c.execute("UPDATE logs SET st=?, rej=? WHERE id=?", (st, rej, log_id))
        c.commit()

def delete_log(log_id):
    with _lock, _conn() as c:
        c.execute("DELETE FROM logs WHERE id=?", (log_id,))
        c.commit()

def edit_log(log_id, amt, note, pul=None):
    with _lock, _conn() as c:
        if pul is not None:
            c.execute("UPDATE logs SET amt=?, note=?, pul=? WHERE id=?", (amt, note, pul, log_id))
        else:
            c.execute("UPDATE logs SET amt=?, note=? WHERE id=?", (amt, note, log_id))
        c.commit()

def get_log(log_id):
    with _conn() as c:
        r = c.execute("SELECT * FROM logs WHERE id=?", (log_id,)).fetchone()
        return dict(r) if r else None

def all_logs():
    with _conn() as c:
        return [dict(r) for r in c.execute("SELECT * FROM logs ORDER BY ts DESC").fetchall()]

def pending_logs():
    with _conn() as c:
        return [dict(r) for r in c.execute("SELECT * FROM logs WHERE st='wait' ORDER BY ts DESC").fetchall()]

# ---------- salary ----------
def add_salary(car_id, t, amt, note, ts=None):
    with _lock, _conn() as c:
        c.execute("INSERT INTO salary(car_id,t,amt,note,ts) VALUES(?,?,?,?,?)",
                  (car_id, t, amt, note, ts or int(time.time())))
        c.commit()

def all_salary():
    with _conn() as c:
        return [dict(r) for r in c.execute("SELECT * FROM salary ORDER BY ts DESC").fetchall()]

# ---------- settings ----------
def get_setting(k, default=None):
    with _conn() as c:
        r = c.execute("SELECT v FROM settings WHERE k=?", (k,)).fetchone()
        return r["v"] if r else default

def set_setting(k, v):
    with _lock, _conn() as c:
        c.execute("INSERT INTO settings(k,v) VALUES(?,?) ON CONFLICT(k) DO UPDATE SET v=?",
                  (k, str(v), str(v)))
        c.commit()

def add_amort_for_month(kurs, ym):
    """Har moshinaga oylik eskirishni salary jadvaliga 'eskirish' turida yozadi.
    ym = 'YYYY-MM' — shu oy uchun bir marta yoziladi (dublikat bo'lmasin)."""
    if get_setting("amort_done_"+ym):
        return 0
    n = 0
    with _lock, _conn() as c:
        cars = c.execute("SELECT id, amort FROM cars").fetchall()
        for car in cars:
            summa = int((car["amort"] or 50) * kurs)
            c.execute("INSERT INTO salary(car_id,t,amt,note,ts) VALUES(?,?,?,?,?)",
                      (car["id"], "eskirish", summa, ym+" eskirishi", int(time.time())))
            n += 1
        c.commit()
    set_setting("amort_done_"+ym, "1")
    return n


# ==================== GPS FUNKSIYALAR (car_id bo'yicha) ====================
def _dist_m(a, b):
    R = 6371000.0
    la1, lo1, la2, lo2 = map(math.radians, [a["lat"], a["lon"], b["lat"], b["lon"]])
    dla, dlo = la2 - la1, lo2 - lo1
    h = math.sin(dla/2)**2 + math.cos(la1)*math.cos(la2)*math.sin(dlo/2)**2
    return 2 * R * math.asin(min(1, math.sqrt(h)))

def _min(t1, t2):
    try:
        return (datetime.fromisoformat(str(t2)[:19]) - datetime.fromisoformat(str(t1)[:19])).total_seconds()/60.0
    except Exception:
        return 0.0

def car_gps_token(car_id):
    """Kuzat tokenini oladi (bo'lmasa yaratadi) — haydovchi GPS yuborish uchun."""
    with _lock, _conn() as c:
        r = c.execute("SELECT kuzat_token FROM cars WHERE id=?", (car_id,)).fetchone()
        tok = r["kuzat_token"] if r and r["kuzat_token"] else None
        if not tok:
            tok = secrets.token_urlsafe(10)
            c.execute("UPDATE cars SET kuzat_token=? WHERE id=?", (tok, car_id))
            c.commit()
        return tok

def car_by_kuzat_token(token):
    with _conn() as c:
        r = c.execute("SELECT * FROM cars WHERE kuzat_token=?", (token,)).fetchone()
        return dict(r) if r else None

def car_gps_kod(car_id):
    """6 xonali kirish kodi (haydovchi kuzat sahifasiga kiradi)."""
    import random
    with _lock, _conn() as c:
        r = c.execute("SELECT gps_kod FROM cars WHERE id=?", (car_id,)).fetchone()
        kod = r["gps_kod"] if r and r["gps_kod"] else None
        if not kod:
            for _ in range(50):
                k = str(random.randint(100000, 999999))
                if not c.execute("SELECT 1 FROM cars WHERE gps_kod=?", (k,)).fetchone():
                    kod = k; break
            c.execute("UPDATE cars SET gps_kod=? WHERE id=?", (kod, car_id))
            c.commit()
        return kod

def car_by_gps_kod(kod):
    with _conn() as c:
        r = c.execute("SELECT * FROM cars WHERE gps_kod=?", (str(kod).strip(),)).fetchone()
        return dict(r) if r else None

def car_share_token(car_id):
    """Mijozga jonli kuzatuv tokeni."""
    with _lock, _conn() as c:
        r = c.execute("SELECT share_token FROM cars WHERE id=?", (car_id,)).fetchone()
        tok = r["share_token"] if r and r["share_token"] else None
        if not tok:
            tok = secrets.token_urlsafe(8)
            c.execute("UPDATE cars SET share_token=? WHERE id=?", (tok, car_id))
            c.commit()
        return tok

def car_by_share(token):
    with _conn() as c:
        r = c.execute("SELECT * FROM cars WHERE share_token=?", (token,)).fetchone()
        return dict(r) if r else None

def gps_qosh(car_id, points):
    if not points: return 0
    with _lock, _conn() as c:
        c.executemany("INSERT INTO gps_nuqta(car_id,lat,lon,vaqt,acc) VALUES(?,?,?,?,?)",
            [(car_id, float(p["lat"]), float(p["lon"]), str(p.get("vaqt") or "")[:19], float(p.get("acc") or 0))
             for p in points if p.get("lat") is not None and p.get("lon") is not None])
        c.commit()
    return len(points)

def gps_oxirgi(car_id):
    with _conn() as c:
        r = c.execute("SELECT lat,lon,vaqt,acc FROM gps_nuqta WHERE car_id=? ORDER BY vaqt DESC LIMIT 1", (car_id,)).fetchone()
        return dict(r) if r else None

def gps_kunlik(car_id, sana):
    with _conn() as c:
        rows = c.execute("SELECT lat,lon,vaqt,acc FROM gps_nuqta WHERE car_id=? AND substr(vaqt,1,10)=? ORDER BY vaqt",
                         (car_id, str(sana)[:10])).fetchall()
        return [dict(r) for r in rows]

def gps_stops(points, min_daq=5, radius_m=60):
    stops=[]; n=len(points); i=0
    while i<n:
        j=i+1
        while j<n and _dist_m(points[i],points[j])<=radius_m: j+=1
        dur=_min(points[i]["vaqt"],points[j-1]["vaqt"]) if j-1>i else 0
        if dur>=min_daq:
            seg=points[i:j]
            stops.append({"lat":sum(p["lat"] for p in seg)/len(seg),"lon":sum(p["lon"] for p in seg)/len(seg),
                "boshlanish":points[i]["vaqt"],"tugash":points[j-1]["vaqt"],"daqiqa":round(dur)})
            i=j
        else: i+=1
    return stops

def kunlik_xulosa(car_id, sana):
    pts=gps_kunlik(car_id,sana); stops=gps_stops(pts)
    # km — sakrashsiz: har segment aniqligini va tezligini tekshiramiz
    dist=0.0
    for k in range(1,len(pts)):
        a,b=pts[k-1],pts[k]
        m=_dist_m(a,b)
        # juda noaniq nuqta (60m+) yoki juda kichik harakat (8m-) hisoblanmaydi
        acc_b=b.get("acc") or 0
        if m<8 or acc_b>60:
            continue
        # tezlik tekshiruvi (sakrash = imkonsiz tez)
        dt=_min(a["vaqt"],b["vaqt"])*60  # sekund
        if dt>0:
            tez=m/dt  # m/s
            if tez>40:  # 144 km/soat dan tez = GPS xatosi
                continue
        dist+=m
    ish=""
    if pts: ish=pts[0]["vaqt"][11:16]+" – "+pts[-1]["vaqt"][11:16]
    return {"nuqtalar":pts,"toxtashlar":stops,"km":round(dist/1000,1),"soni":len(pts),
            "ish_vaqti":ish,"toxtash_daq":sum(s["daqiqa"] for s in stops)}

def car_seen(car_id):
    with _lock, _conn() as c:
        r=c.execute("SELECT offline_xabar FROM cars WHERE id=?", (car_id,)).fetchone()
        edi=bool(r and r["offline_xabar"])
        c.execute("UPDATE cars SET last_seen=?, offline_xabar=0 WHERE id=?", (now_tk().isoformat(), car_id))
        c.commit()
    return edi

def mark_offline_xabar(car_id):
    """Offline xabar berildi deb belgilaymiz (takror xabar bo'lmasin)."""
    with _lock, _conn() as c:
        c.execute("UPDATE cars SET offline_xabar=1 WHERE id=?", (car_id,))
        c.commit()

def car_online(car_id, daqiqa=5):
    with _conn() as c:
        r=c.execute("SELECT last_seen FROM cars WHERE id=?", (car_id,)).fetchone()
    if not r or not r["last_seen"]: return False
    try:
        return (now_tk()-datetime.fromisoformat(r["last_seen"])).total_seconds()/60 <= daqiqa
    except: return False

def gps_age_daqiqa(vaqt):
    try:
        d=datetime.fromisoformat(str(vaqt)[:19]); now=now_tk().replace(tzinfo=None)
        return (now-d).total_seconds()/60
    except: return None

# yetkazish (mijozga jonli ssilka)
def yetkazish_qosh(car_id, lat, lon, izoh=None):
    tok=secrets.token_urlsafe(8)
    with _lock, _conn() as c:
        c.execute("INSERT INTO yetkazish(token,car_id,mlat,mlon,izoh,holat,created) VALUES(?,?,?,?,?,'faol',?)",
                  (tok,int(car_id),float(lat),float(lon),izoh,now_tk().isoformat()))
        c.commit()
    return tok

def yetkazish_get(token):
    with _conn() as c:
        r=c.execute("SELECT * FROM yetkazish WHERE token=?", (token,)).fetchone()
        return dict(r) if r else None

def yetkazish_faol_car(car_id):
    """Moshinaga biriktirilgan faol (yakunlanmagan) yetkazish."""
    with _conn() as c:
        r=c.execute("SELECT * FROM yetkazish WHERE car_id=? AND holat='faol' ORDER BY created DESC LIMIT 1",
                    (car_id,)).fetchone()
        return dict(r) if r else None

def yetkazish_yakunla(token):
    with _lock, _conn() as c:
        c.execute("UPDATE yetkazish SET holat='yakunlandi', yakun=? WHERE token=?", (now_tk().isoformat(),token))
        c.commit()

def set_car_tel(car_id, tel):
    with _lock, _conn() as c:
        c.execute("UPDATE cars SET tel=? WHERE id=?", (tel, car_id))
        c.commit()
