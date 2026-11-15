"""
Talentradar - dashboard (Streamlit).

Start lokalt:     streamlit run dashboard.py
Demo uden data:   DEMO=1 streamlit run dashboard.py
I skyen:          sæt DATABASE_URL under App settings > Secrets (se README).
"""
import html
import os
from datetime import datetime
from io import BytesIO

import pandas as pd
import streamlit as st

from core import (STATUSES, build_rows, demo_engine, get_engine, get_statuses, pipeline_stats, q, seed_demo,
                  set_status)
from exports import prompt_text, write_excel

import base64
from pathlib import Path


def _brand(name, default):
    """Branding kan sættes i Secrets/miljø uden at ændre koden."""
    v = os.environ.get(name)
    if not v:
        try:
            v = st.secrets.get(name)
        except Exception:
            v = None
    return v or default


def _logo_uri():
    """Læser assets/logo.(png|svg|jpg|webp) og indlejrer den i siden. Tom, hvis der ikke er en logofil."""
    for ext, mime in (("svg", "image/svg+xml"), ("png", "image/png"), ("jpg", "image/jpeg"), ("webp", "image/webp")):
        f = Path(__file__).parent / "assets" / f"logo.{ext}"
        if f.exists():
            return f"data:{mime};base64," + base64.b64encode(f.read_bytes()).decode()
    return ""


BRAND_NAME = _brand("BRAND_NAME", "AROS")
ACCENT = _brand("BRAND_COLOR", "#FFFFFF")
LOGO = _logo_uri()
_icon = next((str(f) for f in (Path(__file__).parent / "assets").glob("icon.*")), None)
st.set_page_config(page_title=f"Talentradar · {BRAND_NAME}", page_icon=_icon or "📡", layout="wide")

GREEN, INK, PANEL, MUTED = "#FFFFFF", "#000000", "#0A0A0A", "#8C8C8C"

import hashlib
import math

st.markdown("""
<style>
@import url('https://fonts.googleapis.com/css2?family=Instrument+Serif:ital@0;1&family=Hanken+Grotesk:wght@300;400;500;600&display=swap');
:root { --line: rgba(255,255,255,.16); --glass: rgba(255,255,255,.04); --dim: #8C8C8C; --serif: "Instrument Serif", "Iowan Old Style", Georgia, serif; }
html, body, .stApp, [class*="css"] { font-family: "Hanken Grotesk", "Helvetica Neue", Arial, sans-serif; color: #fff; }
.stApp { background: #000; }
#MainMenu, footer { visibility: hidden; }
header[data-testid="stHeader"] { background: transparent; }
.block-container { padding-top: 1.6rem; max-width: 1320px; }
section[data-testid="stSidebar"] { background: #050505; border-right: 1px solid var(--line); }
section[data-testid="stSidebar"] h3 { font-family: var(--serif); font-weight: 400; font-size: 1.5rem; }
h1, h2, h3, h4 { font-family: var(--serif); font-weight: 400; letter-spacing: -0.01em; }
h4 { font-size: 1.7rem; }

/* Topbjælke */
.mast { display: flex; align-items: center; justify-content: space-between; padding-bottom: 14px; border-bottom: 1px solid var(--line); }
.mast .brand { display: flex; align-items: center; gap: 16px; }
.mast img { height: 52px; width: auto; display: block; }
.wordmark { font-weight: 600; font-size: 1.15rem; letter-spacing: .34em; }
.mast .prod { font-family: var(--serif); font-style: italic; font-size: 1.35rem; padding-left: 16px; border-left: 1px solid var(--line); }
.mast .upd { color: var(--dim); font-size: .85rem; font-variant-numeric: tabular-nums; }

/* Hero: sætning + radar */
.hero { display: grid; grid-template-columns: minmax(0, 1.15fr) minmax(320px, 470px); gap: 48px; align-items: center; margin: 30px 0 34px; }
.lede { font-family: var(--serif); font-weight: 400; font-size: clamp(2.2rem, 4.2vw, 4rem); line-height: 1.04; letter-spacing: -0.02em; margin: 0 0 18px; }
.lede em { font-style: italic; border-bottom: 1px solid #fff; }
.lede-sub { color: var(--dim); font-size: 1.02rem; line-height: 1.65; max-width: 34em; font-weight: 300; }
@media (max-width: 900px) { .hero { grid-template-columns: 1fr; } }

/* Radar */
.rdr { position: relative; width: 100%; aspect-ratio: 1 / 1; border: 1px solid var(--line); border-radius: 28px; padding: 7%;
       background: var(--glass); -webkit-backdrop-filter: blur(18px); backdrop-filter: blur(18px);
       box-shadow: inset 0 1px 0 rgba(255,255,255,.12); }
.rdr .disc { position: relative; width: 100%; height: 100%; }
.rdr svg { position: absolute; inset: 0; width: 100%; height: 100%; overflow: visible; }
.rdr .sweep { position: absolute; inset: 0; border-radius: 50%; animation: spin 7s linear infinite;
              background: conic-gradient(from 0deg, rgba(255,255,255,0) 0deg, rgba(255,255,255,0) 255deg, rgba(255,255,255,.07) 300deg, rgba(255,255,255,.34) 356deg, rgba(255,255,255,.95) 360deg);
              -webkit-mask: radial-gradient(circle, #000 0 69.5%, transparent 70%); mask: radial-gradient(circle, #000 0 69.5%, transparent 70%);
              filter: drop-shadow(0 0 10px rgba(255,255,255,.55)); }
.rdr .corner { position: absolute; font-size: .68rem; color: var(--dim); font-variant-numeric: tabular-nums; letter-spacing: .04em; }
.rdr .tl { top: 3.2%; left: 5%; } .rdr .tr { top: 3.2%; right: 5%; } .rdr .bl { bottom: 3.2%; left: 5%; }
.rdr .blip { fill: #fff; } .rdr .blip.big { filter: drop-shadow(0 0 1.6px #fff); }
.rdr .ping { fill: none; stroke: #fff; stroke-width: .35; transform-box: fill-box; transform-origin: center; animation: ping 3.2s ease-out infinite; }
.rdr .lab { fill: #fff; font-size: 2.5px; font-family: "Hanken Grotesk", Arial, sans-serif; letter-spacing: .02em; }
.rdr .grid { fill: none; stroke: rgba(255,255,255,.26); stroke-width: .22; }
.rdr .tick { stroke: rgba(255,255,255,.4); stroke-width: .2; }
@keyframes spin { to { transform: rotate(360deg); } }
@keyframes ping { 0% { transform: scale(1); opacity: .9; } 100% { transform: scale(4.5); opacity: 0; } }
@media (prefers-reduced-motion: reduce) { .rdr .sweep, .rdr .ping { animation: none; } }

/* Rangliste */
.bench { border-top: 1px solid #fff; }
.row { display: grid; grid-template-columns: 70px minmax(170px, 1.1fr) 3fr minmax(150px, .9fr); align-items: center; gap: 18px; padding: 18px 0; border-bottom: 1px solid var(--line); }
.row .rk { font-family: var(--serif); font-style: italic; font-size: 2.6rem; line-height: 1; font-variant-numeric: tabular-nums; }
.row .nm { font-family: var(--serif); font-size: 1.55rem; line-height: 1.1; }
.row .nm a { color: #fff; text-decoration: none; } .row .nm a:hover { text-decoration: underline; text-underline-offset: 5px; }
.row .meta { color: var(--dim); font-size: .85rem; }
.row .barwrap { display: flex; align-items: center; gap: 14px; }
.row .bar { height: 1px; background: #fff; position: relative; min-width: 6px; }
.row .bar::after { content: ""; position: absolute; right: -3px; top: -3px; width: 7px; height: 7px; border-radius: 50%; background: #fff; box-shadow: 0 0 8px #fff; }
.row .gv { font-variant-numeric: tabular-nums; white-space: nowrap; margin-left: 6px; }
.row .chk { font-size: .78rem; color: var(--dim); margin-top: 4px; }
@media (max-width: 900px) { .row { grid-template-columns: 48px 1fr; } .row .barwrap, .row .chk { grid-column: 2; } }

/* Tags og poster */
.pill { display: inline-block; padding: 1px 10px; border-radius: 999px; font-size: .74rem; border: 1px solid rgba(255,255,255,.55); color: #fff; margin-right: 6px; }
.pill.warn { border-style: dashed; } .pill.mute { color: var(--dim); border-color: var(--line); }
.pill.s-Ny { color: var(--dim); border-color: var(--line); }
.pill.s-Møde { background: rgba(255,255,255,.16); }
.pill.s-Kontrakt { background: #fff; color: #000; border-color: #fff; font-weight: 600; }
.pill.s-Afvist { text-decoration: line-through; color: var(--dim); }
.pill.s-Ikke { color: #5a5a5a; border-color: #2a2a2a; }
.five { border: 1px solid var(--line); background: var(--glass); border-radius: 18px; padding: 14px 16px; margin-bottom: 10px;
        -webkit-backdrop-filter: blur(14px); backdrop-filter: blur(14px); }
.five .rk { font-family: var(--serif); font-style: italic; font-size: 1.6rem; line-height: 1; }
.five .nm { font-family: var(--serif); font-size: 1.3rem; margin: 2px 0; } .five .nm a { color: #fff; text-decoration: none; }
.five .st { color: var(--dim); font-size: .88rem; margin: 6px 0; }
.five .tj { color: var(--dim); font-size: .78rem; border-top: 1px solid var(--line); padding-top: 6px; }
.demo { border: 1px dashed rgba(255,255,255,.5); color: #fff; padding: 8px 14px; font-size: .85rem; margin-bottom: 14px; border-radius: 999px; text-align: center; }

/* Streamlit-komponenter */
div[data-baseweb="tab-list"] { gap: 26px; border-bottom: 1px solid var(--line); }
button[data-baseweb="tab"] { background: transparent; padding: 10px 0; font-family: var(--serif); font-size: 1.25rem; }
div[data-baseweb="tab-highlight"] { background-color: #fff; height: 1px; }
div[data-testid="stDataFrame"] { border: 1px solid var(--line); border-radius: 14px; overflow: hidden; }
div[data-testid="stMetric"] { background: var(--glass); border: 1px solid var(--line); border-radius: 14px; padding: 10px 14px; }
.stButton > button, .stDownloadButton > button { border-radius: 999px; border: 1px solid rgba(255,255,255,.6); background: transparent; color: #fff; font-weight: 500; }
.stButton > button[kind="primary"] { background: #fff; color: #000; border-color: #fff; }
.footer { margin-top: 48px; padding-top: 12px; border-top: 1px solid var(--line); color: var(--dim); font-size: .78rem; display: flex; justify-content: space-between; flex-wrap: wrap; gap: 8px; }
</style>
""", unsafe_allow_html=True)


def radar_html(rows, updated=""):
    """Radar: hver prik er en kandidat. Tættere på midten = vokser hurtigere. Retningen er kun til at sprede prikkerne."""
    pool = [r for r in rows if not r["flag"]][:24] or rows[:24]
    mx = max([r["score"] for r in pool] + [1])
    svg = ['<svg viewBox="0 0 100 100" aria-hidden="true">']
    for rad in (48, 36, 24, 12):
        svg.append(f'<circle class="grid" cx="50" cy="50" r="{rad}"/>')
    svg.append('<line class="grid" x1="2" y1="50" x2="98" y2="50"/><line class="grid" x1="50" y1="2" x2="50" y2="98"/>')
    for d in range(0, 360, 10):
        c, sn = math.cos(math.radians(d)), math.sin(math.radians(d))
        ln = 2.2 if d % 30 == 0 else 1.1
        svg.append(f'<line class="tick" x1="{50 + 48 * c:.2f}" y1="{50 + 48 * sn:.2f}" x2="{50 + (48 + ln) * c:.2f}" y2="{50 + (48 + ln) * sn:.2f}"/>')
    placed = []
    for i, r in enumerate(pool):
        h = int(hashlib.md5(r["login"].encode()).hexdigest()[:8], 16)
        ang = (h % 3600) / 3600 * 2 * math.pi
        rad = 8 + 36 * (1 - r["score"] / mx) ** 0.8
        x, y = 50 + rad * math.cos(ang), 50 + rad * math.sin(ang)
        big = i < 3
        delay = (h % 60) / 10
        svg.append(f'<circle class="ping" cx="{x:.2f}" cy="{y:.2f}" r="{1.2 if big else .8}" style="animation-delay:-{delay:.1f}s"/>')
        svg.append(f'<circle class="blip{" big" if big else ""}" cx="{x:.2f}" cy="{y:.2f}" r="{1.2 if big else .75}"/>')
        if i < 5:
            left = x > 62
            ly = y + .9
            for px, py in placed:  # undgå at labels ligger oven i hinanden
                if abs(ly - py) < 3.4 and abs(x - px) < 28:
                    ly = py + 3.6
            placed.append((x, ly))
            svg.append(f'<text class="lab" x="{x + (-2.2 if left else 2.2):.2f}" y="{ly:.2f}" text-anchor="{"end" if left else "start"}">{html.escape(r["name"])}</text>')
    svg.append('</svg>')
    return (f'<div class="rdr"><div class="disc">{"".join(svg)}<div class="sweep"></div></div>'
            f'<span class="corner tl">{len(pool)} kandidater</span><span class="corner tr">{html.escape(updated)}</span>'
            f'<span class="corner bl">tættere på midten = hurtigere vækst</span></div>')


# ---------------------------------------------------------------- Data
def secrets_to_env():
    try:
        for k in ("DATABASE_URL",):
            if k in st.secrets and not os.environ.get(k):
                os.environ[k] = st.secrets[k]
    except Exception:
        pass  # ingen secrets-fil lokalt, det er fint


DEMO = os.environ.get("DEMO") == "1"


@st.cache_resource
def engine():
    if DEMO:
        eng = demo_engine()
        if not q(eng, "SELECT 1 FROM users LIMIT 1"):
            seed_demo(eng)
        return eng
    secrets_to_env()
    return get_engine()


EN = engine()


@st.cache_data(ttl=120)
def load(min_f, max_f, _v=0):
    rows, excluded, dropped = build_rows(EN, min_f, max_f or None)
    last = q(EN, "SELECT MAX(ts) FROM samples")[0][0]
    return rows, excluded, dropped, last


def current_user():
    for attr in ("user", "experimental_user"):
        u = getattr(st, attr, None)
        try:
            email = getattr(u, "email", None) or (u.get("email") if hasattr(u, "get") else None)
            if email:
                return str(email)
        except Exception:
            pass
    return "ukendt"


def status_pill(s):
    return f'<span class="pill s-{html.escape(s.split()[0])}">{html.escape(s)}</span>'


# ---------------------------------------------------------------- Sidebar
with st.sidebar:
    st.markdown("### Filtre")
    min_f = st.number_input("Min. følgere", 0, 100000, 25, step=25)
    max_f = st.number_input("Maks. følgere (0 = ingen grænse)", 0, 1000000, 0, step=1000)
    only_free = st.toggle("Kun uden bureau/mail i bio", value=False)
    search = st.text_input("Søg kanal")

rows, excluded, dropped, last_ts = load(int(min_f), int(max_f))
statuses = get_statuses(EN)
for r in rows:
    r["status"] = statuses.get(r["uid"], {}).get("status", "Ny")

cats = sorted({r["category"] for r in rows if r["category"]})
with st.sidebar:
    pick_cats = st.multiselect("Kategori", cats)
    pick_status = st.multiselect("Status", STATUSES)

view = [r for r in rows
        if (not only_free or not r["flag"])
        and (not pick_cats or r["category"] in pick_cats)
        and (not pick_status or r["status"] in pick_status)
        and (not search or search.lower() in r["name"].lower() or search.lower() in r["login"].lower())]

_upd_short = ""
if last_ts:
    try:
        _upd_short = datetime.fromisoformat(last_ts).astimezone().strftime("%d.%m kl. %H:%M")
    except Exception:
        _upd_short = ""
if st.query_params.get("overlay"):
    st.markdown("""<style>section[data-testid="stSidebar"], header, .mast {display:none !important}
    .block-container {max-width: 560px; padding-top: 1rem;} .stApp {background:#000}</style>""", unsafe_allow_html=True)
    st.markdown(radar_html(rows, _upd_short), unsafe_allow_html=True)
    st.stop()

# ---------------------------------------------------------------- Header
if DEMO:
    st.markdown('<div class="demo">DEMODATA – opdigtede kanaler til visning af værktøjet</div>', unsafe_allow_html=True)
updated = "ingen data endnu"
if last_ts:
    try:
        updated = datetime.fromisoformat(last_ts).astimezone().strftime("%d-%m-%Y kl. %H:%M")
    except Exception:
        updated = last_ts
_mark = (f'<img src="{LOGO}" alt="{html.escape(BRAND_NAME)}">' if LOGO
         else f'<div class="wordmark">{html.escape(BRAND_NAME)}</div>')
st.markdown(f'<div class="mast"><div class="brand">{_mark}<div class="prod">Talentradar</div></div>'
            f'<div class="upd">Opdateret {html.escape(updated)}</div></div>', unsafe_allow_html=True)
st.write("")

if not rows:
    st.info("Der er ikke nok data endnu. Vækst kan først beregnes, når indsamlingen har kørt i ca. en uge "
            "(7 dage) eller en måned (30 dage). Prøv demoen med `DEMO=1 streamlit run dashboard.py`.")
    st.stop()

counts, avg_days = pipeline_stats(EN)
free = [r for r in rows if not r["flag"]]
top = rows[0]
def _g(r):
    if r["g30"] is not None:
        return f"{r['g30']:+,} følgere på 30 dage".replace(",", ".")
    return f"{r['g7']:+,} følgere på 7 dage".replace(",", ".")


n_free = len(free)
_sub = [f"{len(rows)} kandidater er på listen, og {n_free} af dem har hverken bureau eller mail i bioen."]
if counts["Kontaktet"] or counts["Møde"] or counts["Kontrakt"]:
    _sub.append(f"De seneste 90 dage er {counts['Kontaktet']} kontaktet, {counts['Møde']} til møde og "
                f"{counts['Kontrakt']} endt med kontrakt"
                + (f", i gennemsnit {avg_days:.0f} dage efter første kontakt." if avg_days is not None else "."))
st.markdown(f'<div class="hero"><div><h1 class="lede"><em>{html.escape(top["name"])}</em> vokser hurtigst lige nu, '
            f'med {_g(top)}.</h1><div class="lede-sub">{" ".join(_sub)}</div></div>{radar_html(rows, _upd_short)}</div>',
            unsafe_allow_html=True)

tab_radar, tab_five, tab_pipe, tab_ex, tab_about = st.tabs(["Radar", "Ugens fem", "Pipeline", "Fravalgt", "Om"])

# ---------------------------------------------------------------- Radar
with tab_radar:
    if not view:
        st.warning("Ingen kanaler matcher filtrene.")
    else:
        df = pd.DataFrame([{
            "Rang": rows.index(r) + 1,
            "Kanal": f"https://www.twitch.tv/{r['login']}",
            "Følgere": r["followers"],
            "Vækst 7 d": r["g7"],
            "Vækst 30 d": r["g30"],
            "Vækst 30 d %": (r["pct30"] * 100) if r["pct30"] is not None else None,
            "Seere": r["viewers"],
            "Kategori": r["category"],
            "Bureau / mail": r["flag"] or "Ingen",
            "Status": r["status"],
            "Udvikling": [t for _, t in r["history"]],
            "Score": r["score"],
        } for r in view])
        c1, c2 = st.columns([1.1, 1], gap="large")
        with c1:
            ev = st.dataframe(
                df, hide_index=True, width="stretch", height=620,
                on_select="rerun", selection_mode="single-row", key="radar_table",
                column_config={
                    "Kanal": st.column_config.LinkColumn("Kanal", display_text=r"https://www\.twitch\.tv/(.*)"),
                    "Følgere": st.column_config.NumberColumn(format="%d"),
                    "Vækst 7 d": st.column_config.NumberColumn(format="%+d"),
                    "Vækst 30 d": st.column_config.NumberColumn(format="%+d"),
                    "Vækst 30 d %": st.column_config.NumberColumn(format="%.0f %%"),
                    "Seere": st.column_config.NumberColumn(format="%d"),
                    "Udvikling": st.column_config.LineChartColumn("Udvikling"),
                    "Score": st.column_config.ProgressColumn("Score", min_value=0, max_value=max(r["score"] for r in rows),
                                                              format="%d"),
                })
            buf = BytesIO()
            write_excel(rows, excluded, dropped, buf, demo=DEMO)
            st.download_button("Hent som Excel", buf.getvalue(), file_name="talentradar.xlsx",
                               mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
        with c2:
            sel = ev.selection.rows if ev and ev.selection else []
            if not sel:
                st.markdown("#### Vælg en kanal i listen")
                st.caption("Klik på en række for at se udvikling, bio og sætte status.")
            else:
                r = view[sel[0]]
                st.markdown(f"#### {html.escape(r['name'])}")
                st.markdown(f'<span class="pill">{html.escape(r["category"] or "ukendt kategori")}</span>'
                            f'{status_pill(r["status"])}'
                            + (f'<span class="pill warn">{html.escape(r["flag"])}</span>' if r["flag"] else ""),
                            unsafe_allow_html=True)
                m = st.columns(3)
                m[0].metric("Følgere", f"{r['followers']:,}".replace(",", "."))
                m[1].metric("Vækst 7 d", f"{r['g7']:+,}".replace(",", ".") if r["g7"] is not None else "–")
                m[2].metric("Vækst 30 d", f"{r['g30']:+,}".replace(",", ".") if r["g30"] is not None else "–")
                hist = pd.DataFrame({"Følgere": [t for _, t in r["history"]]},
                                    index=pd.to_datetime([d for d, _ in r["history"]]))
                st.area_chart(hist, color="#FFFFFF", height=220)
                with st.expander("Bio"):
                    st.write(r["bio"] or "Ingen bio.")
                st.caption("Tjek manuelt før kontakt: alder (18+) og forhold til spilreklame.")
                cur = statuses.get(r["uid"], {})
                with st.form(f"status_{r['uid']}"):
                    s = st.selectbox("Status", STATUSES, index=STATUSES.index(cur.get("status", "Ny")))
                    note = st.text_area("Note", value=cur.get("note", ""), height=90)
                    if st.form_submit_button("Gem status", type="primary"):
                        set_status(EN, r["uid"], r["login"], r["name"], s, note, current_user())
                        load.clear()
                        st.toast(f"Status gemt for {r['name']}")
                        st.rerun()

# ---------------------------------------------------------------- Ugens fem
with tab_five:
    st.markdown("#### Ugens fem mest interessante")
    st.caption("De fem højeste scorer uden bureau-flag og uden status Afvist/Ikke relevant. "
               "Claude kan skrive begrundelsen ud fra prompten nederst.")
    cand = [r for r in rows if not r["flag"] and r["status"] not in ("Afvist", "Ikke relevant")][:5]
    def _gv(r):
        return r["g30"] if r["g30"] is not None else (r["g7"] or 0) * 30 / 7
    mx = max([_gv(r) for r in cand] + [1])
    out = []
    for i, r in enumerate(cand):
        g = f"{r['g30']:+,} / 30 d" if r["g30"] is not None else f"{r['g7']:+,} / 7 d"
        out.append(
            f'<div class="row"><div class="rk">{rows.index(r) + 1}</div>'
            f'<div><div class="nm"><a href="https://www.twitch.tv/{html.escape(r["login"])}" target="_blank">{html.escape(r["name"])}</a></div>'
            f'<div class="meta">{html.escape(r["category"] or "")}</div></div>'
            f'<div class="barwrap"><div class="bar" style="width:{max(2, _gv(r) / mx * 70):.0f}%"></div>'
            f'<div class="gv">{g.replace(",", ".")}</div></div>'
            f'<div><div class="meta">{r["followers"]:,} følgere, {r["viewers"]:.0f} gns. seere</div>'.replace(",", ".") +
            f'<div style="margin-top:4px">{status_pill(r["status"])}</div>'
            f'<div class="chk">Tjek alder 18+, spilreklame og code of conduct</div></div></div>')
    st.markdown('<div class="bench">' + "".join(out) + '</div>', unsafe_allow_html=True)
    st.write("")
    with st.expander("Prompt til Claude (kopiér og indsæt)"):
        st.code(prompt_text(rows, demo=DEMO), language="markdown")

# ---------------------------------------------------------------- Pipeline
with tab_pipe:
    st.markdown("#### Kandidater i forløb")
    cols = st.columns(4)
    for col, s in zip(cols, ["Ny", "Kontaktet", "Møde", "Kontrakt"]):
        items = [(uid, v) for uid, v in statuses.items() if v["status"] == s]
        col.markdown(f"**{s}** · {len(items)}")
        if s == "Ny":
            col.caption("Alle kandidater uden status. Se fanen Radar.")
            continue
        for uid, v in sorted(items, key=lambda x: x[1]["updated"], reverse=True):
            col.markdown(
                f'<div class="five" style="padding:12px 16px;margin-bottom:10px">'
                f'<div class="nm" style="margin:0">{html.escape(v["name"] or v["login"] or uid)}</div>'
                f'<div class="st" style="margin:4px 0">{html.escape(v["note"] or "–")}</div>'
                f'<div class="tj" style="margin-top:6px;padding-top:6px">{html.escape(v["owner"] or "")} · {html.escape(v["updated"][:10])}</div>'
                f'</div>', unsafe_allow_html=True)
    closed = [(uid, v) for uid, v in statuses.items() if v["status"] in ("Afvist", "Ikke relevant")]
    with st.expander(f"Afvist / ikke relevant ({len(closed)})"):
        for uid, v in closed:
            st.write(f"**{v['name'] or v['login']}** · {v['status']} · {v['note'] or '–'}")

# ---------------------------------------------------------------- Fravalgt
with tab_ex:
    st.markdown("#### Sorteret fra pga. poker, slots og casino")
    st.caption("Af hensyn til Aros’ code of conduct og lovforslag L 127 om spilreklame.")
    if excluded:
        st.dataframe(pd.DataFrame(excluded, columns=["Kanal", "Login", "Kategori", "Årsag"]),
                     hide_index=True, width="stretch")
    else:
        st.write("Ingen kanaler er sorteret fra i øjeblikket.")
    st.caption(f"{dropped} kanaler er derudover udeladt: for små, for få seere eller for kort historik.")

# ---------------------------------------------------------------- Om
with tab_about:
    st.markdown("""
**Sådan læses listen**
- *Score* = vækst pr. 30 dage × kategorivægt. Just Chatting vægter højest. Før der er 30 dages historik bruges 7-dages væksten omregnet.
- *Bureau / mail*: bioen nævner DAYZERO, AA Agency, Micky Creatives, Bark, Agergaard eller en mailadresse.
- Data kommer fra Twitchs officielle API og hentes automatisk flere gange om dagen.

**Før Aros kontakter et navn**
1. Tjek alder (18+) og forhold til spilreklame. Det fremgår ikke af data.
2. Tjek at kanalen passer til Aros’ code of conduct.
3. Kemitjek over en kaffe. Radaren finder kandidater, mennesker vælger.
""")
    st.caption(f"Logget ind som: {current_user()}")

st.markdown(f'<div class="footer"><span>{html.escape(BRAND_NAME)} · Talentradar</span>'
            f'<span>Data fra Twitchs officielle API · Kun til internt brug</span></div>', unsafe_allow_html=True)
