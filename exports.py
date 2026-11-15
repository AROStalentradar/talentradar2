"""Excel-liste og Claude-prompt ud fra kandidatlisten."""
from datetime import date, datetime
from pathlib import Path

from core import OUT_DIR

PROMPT_HEAD = """Du er scout for talentbureauet Aros. Nedenfor er denne uges danske Twitch-streamere med hurtigst vækst
(data fra Twitchs officielle API). Vælg de **fem** mest interessante og skriv for hver:

1. Navn og et link
2. Hvorfor lige nu (to sætninger, kun ud fra tallene nedenfor)
3. Hvad der taler for/imod Aros (Just Chatting og IRL ligger tættest på Aros' kunder)
4. Hvad teamet skal tjekke manuelt, før der tages kontakt

Regler:
- Opfind ingen fakta. Bruger du noget, der ikke står i tabellen, så skriv at det skal tjekkes.
- Kanaler med bureau-flag nævnes kun, hvis de er ekstraordinære, og der skrives at de sandsynligvis er bundet.
- Alder og forhold til spilreklame er ikke kendt og skal altid stå som tjek-punkt.
- Hold det kort. Dansk, uformelt men professionelt.

Uge: {week}
"""


def prompt_text(rows, demo=False):
    t = ["| # | Kanal | Følgere | +7 d | +30 d | Gns. seere | Kategori | Bureau/mail |",
         "|---|---|---|---|---|---|---|---|"]
    for n, r in enumerate(rows[:15], 1):
        g7 = f"{r['g7']:+d}" if r["g7"] is not None else "–"
        g30 = f"{r['g30']:+d}" if r["g30"] is not None else "–"
        t.append(f"| {n} | {r['name']} (twitch.tv/{r['login']}) | {r['followers']} | {g7} | {g30} | "
                 f"{r['viewers']} | {r['category']} | {r['flag'] or '–'} |")
    head = PROMPT_HEAD.format(week=date.today().strftime("%G-W%V"))
    if demo:
        head = "**DEMODATA - opdigtede kanaler.**\n\n" + head
    return head + "\n" + "\n".join(t) + "\n"


def write_prompt(rows, path, demo=False):
    OUT_DIR.mkdir(exist_ok=True)
    Path(path).write_text(prompt_text(rows, demo), encoding="utf-8")
    return path


def write_excel(rows, excluded, dropped, target, demo=False):
    """`target` er en filsti eller et filobjekt (fx BytesIO til download-knap)."""
    from openpyxl import Workbook
    from openpyxl.styles import Alignment, Font, PatternFill
    from openpyxl.utils import get_column_letter

    wb = Workbook()
    ws = wb.active
    ws.title = "Radar"
    head_fill = PatternFill("solid", fgColor="1F2937")
    head_font = Font(bold=True, color="FFFFFF")
    row0 = 1
    if demo:
        ws.merge_cells("A1:J1")
        ws["A1"] = "DEMODATA - opdigtede kanaler til visning af værktøjet. Ikke rigtige streamere."
        ws["A1"].font = Font(bold=True, color="9C0006")
        ws["A1"].fill = PatternFill("solid", fgColor="FFC7CE")
        row0 = 2
    cols = ["#", "Kanal", "Følgere", "Vækst 7 dage", "Vækst 30 dage", "Vækst 30 d (%)",
            "Gns. seere", "Kategori", "Bureau / mail i bio", "Score"]
    for i, c in enumerate(cols, 1):
        cell = ws.cell(row=row0, column=i, value=c)
        cell.fill, cell.font = head_fill, head_font
        cell.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
    for n, r in enumerate(rows, 1):
        y = row0 + n
        ws.cell(y, 1, n)
        c = ws.cell(y, 2, r["name"])
        c.hyperlink = f"https://www.twitch.tv/{r['login']}"
        c.font = Font(color="0563C1", underline="single")
        ws.cell(y, 3, r["followers"]).number_format = "#,##0"
        ws.cell(y, 4, r["g7"] if r["g7"] is not None else "–").number_format = "+#,##0;-#,##0;0"
        ws.cell(y, 5, r["g30"] if r["g30"] is not None else "–").number_format = "+#,##0;-#,##0;0"
        ws.cell(y, 6, r["pct30"] if r["pct30"] is not None else "–").number_format = "0%"
        ws.cell(y, 7, r["viewers"])
        ws.cell(y, 8, r["category"])
        ws.cell(y, 9, r["flag"] or "Ingen – kan være ledig")
        ws.cell(y, 10, r["score"]).number_format = "#,##0"
        if r["flag"]:
            for col in range(1, 11):
                ws.cell(y, col).font = Font(color="808080")
            ws.cell(y, 2).font = Font(color="808080", underline="single")
        else:
            ws.cell(y, 9).fill = PatternFill("solid", fgColor="E2F0D9")
    for i, w in enumerate([5, 24, 11, 13, 14, 14, 11, 22, 30, 10], 1):
        ws.column_dimensions[get_column_letter(i)].width = w
    ws.freeze_panes = ws.cell(row0 + 1, 3)
    ws.auto_filter.ref = f"A{row0}:J{row0 + max(len(rows), 1)}"

    ex = wb.create_sheet("Fravalgt")
    for i, c in enumerate(["Kanal", "Login", "Kategori", "Årsag"], 1):
        cell = ex.cell(1, i, c)
        cell.fill, cell.font = head_fill, head_font
    for n, e in enumerate(excluded, 2):
        for i, v in enumerate(e, 1):
            ex.cell(n, i, v)
    for i, w in enumerate([24, 24, 22, 50], 1):
        ex.column_dimensions[get_column_letter(i)].width = w

    om = wb.create_sheet("Om listen")
    lines = [
        ("Talentradar", True),
        (f"Lavet {datetime.now().strftime('%d-%m-%Y %H:%M')}. Kilde: Twitchs officielle Helix API.", False),
        ("", False),
        ("Sådan læses listen", True),
        ("Score = vækst pr. 30 dage × kategorivægt. Just Chatting vægter 1,5; Travel/Talk/Food 1,3; Musik/Kunst 1,2; øvrige 1,0.", False),
        ("Før der er 30 dages historik, bruges 7-dages væksten omregnet til 30 dage.", False),
        ("Bureau / mail: flag hvis bioen nævner DAYZERO, AA Agency, Micky Creatives, Bark, Agergaard eller en mailadresse.", False),
        ("Grå rækker har et bureau-flag. Grønne har intet, og er dem teamet taler med først.", False),
        ("", False),
        ("Sorteret fra", True),
        (f"{len(excluded)} kanaler er sorteret fra pga. poker/slots/casino (se fanen Fravalgt).", False),
        (f"{dropped} kanaler er udeladt: for små, for få seere eller for kort historik.", False),
        ("", False),
        ("Gøres manuelt, før Aros kontakter et navn", True),
        ("1. Tjek alder (18+) og forhold til spilreklame.", False),
        ("2. Tjek at kanalen passer til Aros' code of conduct.", False),
        ("3. Kemitjek over en kaffe – radaren finder kandidater, den vælger dem ikke.", False),
    ]
    for n, (t, bold) in enumerate(lines, 1):
        om.cell(n, 1, t).font = Font(bold=bold, size=14 if n == 1 else 11)
    om.column_dimensions["A"].width = 120
    if isinstance(target, (str, Path)):
        OUT_DIR.mkdir(exist_ok=True)
    wb.save(target)
    return target
