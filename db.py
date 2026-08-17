import sqlite3, os, time, threading

DATA_DIR = os.environ.get("DATA_DIR", "/data")
if not os.path.isdir(DATA_DIR):
    # lokal sinov uchun
    DATA_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(DATA_DIR, "moshina.db")

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
            amort INTEGER DEFAULT 50
        )""")
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
    if field not in ("name","raqam","driver","olindi","sotilsa","oylik","amort"):
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
