"""
Talentradar - fælles kerne: database, beregning af vækst, status pr. kandidat og demodata.

Databasen er SQLite lokalt (data/talentradar.db) og Postgres i skyen (sæt DATABASE_URL).
Samme kode kører begge steder.
"""
import os
import random
import re
from collections import Counter
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

from sqlalchemy import create_engine, text

BASE = Path(__file__).resolve().parent
DATA_DIR = BASE / "data"
OUT_DIR = BASE / "output"

# ---------------------------------------------------------------- Indstillinger
LANGUAGE = "da"
MAX_STREAM_PAGES = 20            # 20 x 100 = op til 2.000 live-streams pr. hentning
SNAPSHOT_EVERY_DAYS = 6          # følgertal tages ca. en gang om ugen pr. kanal
MIN_FOLLOWERS = 25
MIN_AVG_VIEWERS = 2
MAX_FOLLOWERS = None             # fx 30000 hvis listen kun skal vise "næste Aggo"

# Kategorivægt: Just Chatting højest (tættest på Aros' kunder).
# IRL blev slået sammen med Just Chatting på Twitch i 2022, men står med for en sikkerheds skyld.
CATEGORY_WEIGHTS = {
    "Just Chatting": 1.5, "IRL": 1.5, "Travel & Outdoors": 1.3, "Talk Shows & Podcasts": 1.3,
    "Food & Drink": 1.3, "Music": 1.2, "Art": 1.2, "Sports": 1.1,
}
DEFAULT_WEIGHT = 1.0

# Sorteres fra af hensyn til Aros' code of conduct og lovforslag L 127 om spilreklame.
GAMBLING_CATEGORIES = {"Slots", "Poker", "Casino", "Virtual Casino", "Sports Betting", "Gambling", "Crypto"}
GAMBLING_TITLE_RE = re.compile(
    r"\b(casino|slots?|poker|bonus ?buy|betting|bet365|roulette|blackjack|stake\.com)\b", re.I)
GAMBLING_SHARE = 0.25

AGENCIES = ["DAYZERO", "AA Agency", "Micky Creatives", "Bark", "Agergaard"]
AGENCY_RE = re.compile(r"(?<![\w])(" + "|".join(re.escape(a) for a in AGENCIES) + r")(?![\w])", re.I)
EMAIL_RE = re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+")

STATUSES = ["Ny", "Kontaktet", "Møde", "Kontrakt", "Afvist", "Ikke relevant"]

SCHEMA = [
    """CREATE TABLE IF NOT EXISTS users(
        user_id TEXT PRIMARY KEY, login TEXT, display_name TEXT,
        description TEXT, broadcaster_type TEXT, updated TEXT)""",
    """CREATE TABLE IF NOT EXISTS samples(
        ts TEXT, user_id TEXT, viewers INTEGER, game_name TEXT, title TEXT)""",
    "CREATE INDEX IF NOT EXISTS ix_samples ON samples(user_id, ts)",
    """CREATE TABLE IF NOT EXISTS followers(
        day TEXT, user_id TEXT, total INTEGER, PRIMARY KEY(day, user_id))""",
    """CREATE TABLE IF NOT EXISTS candidates(
        user_id TEXT PRIMARY KEY, login TEXT, display_name TEXT,
        status TEXT, note TEXT, owner TEXT, updated TEXT)""",
    """CREATE TABLE IF NOT EXISTS status_log(
        ts TEXT, user_id TEXT, status TEXT, note TEXT, by_user TEXT)""",
]


# ---------------------------------------------------------------- Database
def load_env():
    """Læser .env (KEY=VALUE) uden ekstra pakker."""
    env_file = BASE / ".env"
    if env_file.exists():
        for line in env_file.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


def get_engine(url=None):
    url = url or os.environ.get("DATABASE_URL")
    if not url:
        DATA_DIR.mkdir(exist_ok=True)
        url = f"sqlite:///{DATA_DIR / 'talentradar.db'}"
    if url.startswith("postgres://"):
        url = "postgresql://" + url[len("postgres://"):]
    if url.startswith("postgresql://"):
        url = "postgresql+psycopg2://" + url[len("postgresql://"):]
    eng = create_engine(url, pool_pre_ping=True)
    with eng.begin() as c:
        for stmt in SCHEMA:
            c.execute(text(stmt))
    return eng


def q(eng, sql, **params):
    with eng.connect() as c:
        return c.execute(text(sql), params).fetchall()


def now_iso():
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


# ---------------------------------------------------------------- Beregning
def baseline(snaps, latest_day, days):
    """Følgertal ca. `days` dage før seneste måling (maks. 4 dage for tidligt, 2 for sent)."""
    target = latest_day - timedelta(days=days)
    ok = [s for s in snaps if target - timedelta(days=4) <= s[0] <= target + timedelta(days=2)]
    return max(ok, key=lambda s: s[0]) if ok else None


def build_rows(eng, min_followers=MIN_FOLLOWERS, max_followers=MAX_FOLLOWERS):
    """Returnerer (kandidater rangeret efter score, fravalgte, antal udeladt)."""
    since = (datetime.now(timezone.utc) - timedelta(days=30)).isoformat()
    users = {r[0]: r for r in q(eng, "SELECT user_id, login, display_name, description, broadcaster_type FROM users")}
    samples = {}
    for uid, viewers, game, title in q(
            eng, "SELECT user_id, viewers, game_name, title FROM samples WHERE ts >= :s", s=since):
        samples.setdefault(uid, []).append((viewers, game, title))
    snaps = {}
    for uid, day, total in q(eng, "SELECT user_id, day, total FROM followers ORDER BY day"):
        snaps.setdefault(uid, []).append((date.fromisoformat(day), total))

    rows, excluded, dropped = [], [], 0
    for uid, sm in samples.items():
        if uid not in users or uid not in snaps:
            dropped += 1
            continue
        _, login, name, bio, _btype = users[uid]
        bio = bio or ""
        cats = Counter(g for _, g, _ in sm if g)
        category = cats.most_common(1)[0][0] if cats else ""
        gamble_hits = sum(1 for _, g, t in sm if g in GAMBLING_CATEGORIES or GAMBLING_TITLE_RE.search(t or ""))
        if gamble_hits / len(sm) >= GAMBLING_SHARE:
            excluded.append((name, login, category, f"Spilreklame/gambling i {gamble_hits} af {len(sm)} streams"))
            continue

        s = snaps[uid]
        latest_day, followers = s[-1]
        avg_viewers = sum(v for v, _, _ in sm) / len(sm)
        if followers < min_followers or avg_viewers < MIN_AVG_VIEWERS:
            dropped += 1
            continue
        if max_followers and followers > max_followers:
            dropped += 1
            continue

        b7, b30 = baseline(s, latest_day, 7), baseline(s, latest_day, 30)
        g7 = followers - b7[1] if b7 else None
        g30 = followers - b30[1] if b30 else None
        pct30 = (g30 / b30[1]) if b30 and b30[1] else None
        pace = g30 if g30 is not None else (g7 * 30 / 7 if g7 is not None else None)
        if pace is None:
            dropped += 1  # for kort historik til at sige noget om vækst
            continue
        score = pace * CATEGORY_WEIGHTS.get(category, DEFAULT_WEIGHT)

        flags = []
        m = AGENCY_RE.search(bio)
        if m:
            flags.append(f"Bureau: {m.group(1)}")
        if EMAIL_RE.search(bio):
            flags.append("Business-mail i bio")
        rows.append(dict(
            uid=uid, name=name, login=login, followers=followers, g7=g7, g30=g30, pct30=pct30,
            viewers=round(avg_viewers, 1), category=category, flag=", ".join(flags),
            score=round(score), days=(latest_day - s[0][0]).days, bio=bio,
            history=[(d.isoformat(), t) for d, t in s], last_day=latest_day.isoformat()))
    rows.sort(key=lambda r: r["score"], reverse=True)
    return rows, excluded, dropped


# ---------------------------------------------------------------- Status pr. kandidat
def get_statuses(eng):
    return {r[0]: dict(status=r[1], note=r[2] or "", owner=r[3] or "", updated=r[4], login=r[5], name=r[6])
            for r in q(eng, "SELECT user_id, status, note, owner, updated, login, display_name FROM candidates")}


def set_status(eng, uid, login, name, status, note, by):
    if status not in STATUSES:
        raise ValueError(f"Ukendt status: {status}")
    t = now_iso()
    with eng.begin() as c:
        c.execute(text(
            """INSERT INTO candidates(user_id, login, display_name, status, note, owner, updated)
               VALUES(:u, :l, :n, :s, :note, :o, :t)
               ON CONFLICT (user_id) DO UPDATE SET login=excluded.login, display_name=excluded.display_name,
                 status=excluded.status, note=excluded.note, owner=excluded.owner, updated=excluded.updated"""),
            dict(u=uid, l=login, n=name, s=status, note=note, o=by, t=t))
        c.execute(text("INSERT INTO status_log(ts, user_id, status, note, by_user) VALUES(:t,:u,:s,:note,:o)"),
                  dict(t=t, u=uid, s=status, note=note, o=by))


def pipeline_stats(eng):
    """Nøgletal til succesmålene: kontakter, møder og kontrakter de seneste 90 dage + tid til kontrakt."""
    since = (datetime.now(timezone.utc) - timedelta(days=90)).isoformat()
    counts = {s: 0 for s in ["Kontaktet", "Møde", "Kontrakt"]}
    for status, n in q(eng, "SELECT status, COUNT(DISTINCT user_id) FROM status_log WHERE ts >= :s GROUP BY status", s=since):
        if status in counts:
            counts[status] = n
    first = {}
    for uid, status, ts in q(eng, "SELECT user_id, status, ts FROM status_log ORDER BY ts"):
        first.setdefault(uid, {}).setdefault(status, ts)
    days = [(datetime.fromisoformat(v["Kontrakt"]) - datetime.fromisoformat(v["Kontaktet"])).days
            for v in first.values() if "Kontaktet" in v and "Kontrakt" in v]
    return counts, (sum(days) / len(days) if days else None)


# ---------------------------------------------------------------- Demodata
DEMO_NAMES = [
    "demo_nordlys", "demo_havregryn", "demo_kaffekop", "demo_bornholm", "demo_rygsaek", "demo_laks",
    "demo_vestkyst", "demo_pandekage", "demo_cykelmand", "demo_sofahyggen", "demo_roedgroed",
    "demo_aarhusnat", "demo_fyrtaarn", "demo_gadekaer", "demo_morgenhund", "demo_strikkeklub",
    "demo_lakridsbil", "demo_dybfryser", "demo_skovtur", "demo_togforsinket", "demo_kolonihave",
    "demo_vaffeljern", "demo_nattevagt", "demo_fjordfisk", "demo_halmtag", "demo_regnvejr",
    "demo_pizzabud", "demo_lommelygte", "demo_kaelkebakke", "demo_tebrev", "demo_vindmoelle",
    "demo_cafelatte", "demo_ostehaps", "demo_flaskepost", "demo_baadsmand", "demo_hoeloft",
    "demo_slotsmaskine", "demo_pokerfjes", "demo_casinokonge", "demo_jackpotjens",
]


def demo_engine():
    DATA_DIR.mkdir(exist_ok=True)
    return get_engine(f"sqlite:///{DATA_DIR / 'demo.db'}")


def seed_demo(eng):
    """Fylder databasen med opdigtede kanaler. Rører kun den engine, den får."""
    with eng.begin() as c:
        for t in ["users", "samples", "followers", "candidates", "status_log"]:
            c.execute(text(f"DELETE FROM {t}"))
    rng = random.Random(2026)
    today = date.today()
    cats = ["Just Chatting"] * 5 + ["Travel & Outdoors", "Music", "Art", "Food & Drink", "Valorant",
                                    "Counter-Strike", "Minecraft", "EA Sports FC 26", "League of Legends"]
    mails = ["bookings@example.dk", "kontakt@example.dk"]
    users, snaps, samples = [], [], []
    for i, name in enumerate(DEMO_NAMES):
        uid = str(9_000_000 + i)
        gamble = name in ("demo_slotsmaskine", "demo_pokerfjes", "demo_casinokonge", "demo_jackpotjens")
        cat = {"demo_slotsmaskine": "Slots", "demo_pokerfjes": "Poker",
               "demo_casinokonge": "Virtual Casino", "demo_jackpotjens": "Slots"}.get(name) or rng.choice(cats)
        bio = "Dansk streamer. God stemning og kaffe."
        if i % 9 == 3:
            bio = f"Repræsenteret af {rng.choice(AGENCIES)}."
        elif i % 7 == 2:
            bio = f"Samarbejde: {rng.choice(mails)}"
        start = rng.randint(60, 4000)
        weekly = rng.choice([0.004, 0.006, 0.01, 0.02, 0.03, 0.05, 0.08]) if i % 5 else 0.12
        users.append(dict(u=uid, l=name, n=name, d=bio, b="affiliate", t=now_iso()))
        total = start
        for k in range(6, -1, -1):  # 7 ugentlige målinger, 6 uger tilbage
            total = int(total * (1 + weekly * rng.uniform(0.6, 1.4)) + rng.randint(0, 12))
            snaps.append(dict(d=(today - timedelta(days=7 * k)).isoformat(), u=uid, t=total))
        avg = max(3, int(total * rng.uniform(0.01, 0.06)))
        for d in range(30):
            if rng.random() < 0.55:
                ts = (datetime.now(timezone.utc) - timedelta(days=d, hours=rng.randint(0, 6))).replace(microsecond=0).isoformat()
                samples.append(dict(ts=ts, u=uid, v=max(1, int(avg * rng.uniform(0.7, 1.3))), g=cat,
                                    title="Casino bonus buy i dag!" if gamble else "Hygge og snak"))
    with eng.begin() as c:
        c.execute(text("INSERT INTO users VALUES (:u,:l,:n,:d,:b,:t)"), users)
        c.execute(text("INSERT INTO followers VALUES (:d,:u,:t)"), snaps)
        c.execute(text("INSERT INTO samples VALUES (:ts,:u,:v,:g,:title)"), samples)
    # lidt status, så Pipeline-fanen ikke er tom i demoen
    rows, _, _ = build_rows(eng)
    for r, status, note in [(rows[0], "Møde", "Kaffe aftalt (demo)"), (rows[1], "Kontaktet", "Skrevet via mail (demo)"),
                            (rows[3], "Kontaktet", "Via Aggo (demo)"), (rows[7], "Afvist", "Har allerede bureau (demo)")]:
        set_status(eng, r["uid"], r["login"], r["name"], status, note, "demo")
