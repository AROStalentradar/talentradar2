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

st.set_page_config(page_title="Talentradar", page_icon="📡", layout="wide")

GREEN, INK, PANEL, MUTED = "#36D399", "#0F1720", "#18232F", "#9FB0BF"
STATUS_COLOR = {"Ny": "#9FB0BF", "Kontaktet": "#FFB020", "Møde": "#5AB0FF", "Kontrakt": GREEN,
                "Afvist": "#E5707A", "Ikke relevant": "#6B7885"}

st.markdown(f"""
<style>
#MainMenu, footer {{visibility: hidden;}}
.block-container {{padding-top: 2rem; max-width: 1500px;}}
.hero h1 {{font-size: 2.4rem; margin: 0; letter-spacing: -0.02em;}}
.hero p {{color: {MUTED}; margin: .2rem 0 0 0;}}
.kpi {{background: {PANEL}; border: 1px solid #243445; border-radius: 14px; padding: 18px 22px; height: 100%;}}
.kpi .l {{font-size: .75rem; letter-spacing: .12em; color: {MUTED}; text-transform: uppercase;}}
.kpi .v {{font-size: 2.1rem; font-weight: 700; color: {GREEN}; line-height: 1.2;}}
.kpi .s {{color: #B7C4D0; font-size: .9rem;}}
.pill {{display: inline-block; padding: 2px 12px; border-radius: 20px; font-size: .78rem; font-weight: 600;
        border: 1px solid {GREEN}; color: {GREEN}; margin-right: 6px;}}
.pill.warn {{border-color: #FFB020; color: #FFB020;}}
.pill.mute {{border-color: #6B7885; color: #9FB0BF;}}
.five {{background: {PANEL}; border: 1px solid #243445; border-radius: 16px; padding: 20px 22px; height: 100%;}}
.five .rk {{font-size: 2.2rem; font-weight: 700; color: {GREEN}; line-height: 1;}}
.five .nm {{font-size: 1.25rem; font-weight: 600; margin: 6px 0 2px 0;}}
.five .nm a {{color: #E6EDF3; text-decoration: none;}}
.five .st {{color: #B7C4D0; font-size: .95rem; margin: 8px 0;}}
.five .tj {{color: {MUTED}; font-size: .82rem; margin-top: 10px; border-top: 1px solid #243445; padding-top: 8px;}}
.demo {{background: #FFC7CE; color: #9C0006; padding: 8px 16px; border-radius: 10px; font-weight: 600; margin-bottom: 14px;}}
</style>
""", unsafe_allow_html=True)


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
    c = STATUS_COLOR.get(s, MUTED)
    return f'<span class="pill" style="border-color:{c};color:{c}">{html.escape(s)}</span>'


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

# ---------------------------------------------------------------- Header
if DEMO:
    st.markdown('<div class="demo">DEMODATA – opdigtede kanaler til visning af værktøjet</div>', unsafe_allow_html=True)
updated = "ingen data endnu"
if last_ts:
    try:
        updated = datetime.fromisoformat(last_ts).astimezone().strftime("%d-%m-%Y kl. %H:%M")
    except Exception:
        updated = last_ts
st.markdown(f'<div class="hero"><h1>📡 Talentradar</h1><p>Danske Twitch-streamere i hurtigst vækst · '
            f'Seneste hentning: {html.escape(updated)}</p></div>', unsafe_allow_html=True)
st.write("")

if not rows:
    st.info("Der er ikke nok data endnu. Vækst kan først beregnes, når indsamlingen har kørt i ca. en uge "
            "(7 dage) eller en måned (30 dage). Prøv demoen med `DEMO=1 streamlit run dashboard.py`.")
    st.stop()

counts, avg_days = pipeline_stats(EN)
free = [r for r in rows if not r["flag"]]
top = rows[0]
k = st.columns(4)
tiles = [
    ("Kandidater på listen", str(len(rows)), f"{len(free)} uden bureau/mail i bio"),
    ("Hurtigst voksende", html.escape(top["name"]),
     f"{top['g30']:+,} følgere/30 d".replace(",", ".") if top["g30"] is not None else f"{top['g7']:+,} følgere/7 d".replace(",", ".")),
    ("Kontakter · møder · kontrakter", f"{counts['Kontaktet']} · {counts['Møde']} · {counts['Kontrakt']}", "seneste 90 dage"),
    ("Tid til kontrakt", f"{avg_days:.0f} dage" if avg_days is not None else "–", "fra første kontakt, gennemsnit"),
]
for col, (l, v, s) in zip(k, tiles):
    col.markdown(f'<div class="kpi"><div class="l">{l}</div><div class="v">{v}</div><div class="s">{s}</div></div>',
                 unsafe_allow_html=True)
st.write("")

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
                st.area_chart(hist, color=GREEN, height=220)
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
    cols = st.columns(5)
    for col, r in zip(cols, cand):
        g = f"{r['g30']:+,}".replace(",", ".") + " / 30 d" if r["g30"] is not None else f"{r['g7']:+,}".replace(",", ".") + " / 7 d"
        col.markdown(
            f'<div class="five"><div class="rk">#{rows.index(r) + 1}</div>'
            f'<div class="nm"><a href="https://www.twitch.tv/{html.escape(r["login"])}" target="_blank">{html.escape(r["name"])}</a></div>'
            f'{status_pill(r["status"])}'
            f'<div class="st">{r["followers"]:,} følgere<br><b style="color:{GREEN}">{g}</b><br>'
            f'{r["viewers"]:.0f} gns. seere<br>{html.escape(r["category"] or "")}</div>'
            f'<div class="tj">Tjek: alder 18+, spilreklame, code of conduct</div></div>'.replace(",", "."),
            unsafe_allow_html=True)
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
