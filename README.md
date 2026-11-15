# Talentradar

Ugentlig radar over de hurtigst voksende danske Twitch-streamere, bygget på Twitchs officielle Helix API (ingen skrabning). Claude kommenterer listen; teamet tager kemitjekket.

```
GitHub Actions (4 gange i døgnet)  →  Database (Supabase/Postgres)  ←  Dashboard (Streamlit, med login)
   henter fra Twitch                    streams, følgertal, status       liste, grafer, ugens fem, pipeline
```

- `core.py` database, vækstberegning, status pr. kandidat, demodata
- `talentradar.py` indsamling og kommandolinje (`collect`, `report`, `prompt`, `check`, `demo`)
- `dashboard.py` dashboardet
- `.github/workflows/collect.yml` den planlagte indsamling

## 1. Prøv det lokalt uden nøgler (2 min)

```
pip install -r requirements.txt
DEMO=1 streamlit run dashboard.py          # Windows PowerShell:  $env:DEMO=1; streamlit run dashboard.py
```

## 2. Gør det rigtigt: opsætning (ca. 45 min, én gang)

**A. Twitch-nøgler (gratis).** dev.twitch.tv/console → *Register Your Application* (OAuth Redirect URL `http://localhost`, kategori *Analytics Tool*). Kopiér *Client ID* og opret *Client Secret*. Kræver 2-faktor på Twitch-kontoen.

**B. Database (gratis).** Opret et projekt på supabase.com. Under *Connect* skal du kopiere forbindelsesstrengen. Vælg **Session pooler** (ikke *Direct*), fordi GitHubs maskiner kun bruger IPv4. Den ser ud som `postgresql://postgres.xxxx:ADGANGSKODE@aws-0-....pooler.supabase.com:5432/postgres`. Tabellerne oprettes automatisk første gang.

**C. GitHub.** Opret et **privat** repository og læg alle filerne her ind. Under *Settings → Secrets and variables → Actions* opretter du: `TWITCH_CLIENT_ID`, `TWITCH_CLIENT_SECRET`, `DATABASE_URL` (og evt. `TWITCH_USER_TOKEN`, se nedenfor). Under *Actions* vælger du *Hent Twitch-data → Run workflow* for at teste. Derefter kører den selv kl. 05:15, 10:15, 15:15 og 20:15 UTC.

**D. Dashboard med login.** På share.streamlit.io: *Create app* → vælg repoet → hovedfil `dashboard.py`. Under *Advanced settings → Secrets* indsætter du `DATABASE_URL = "postgresql://..."`. Sæt appen til **privat** og inviter holdets og Aros' e-mails under *Share*. Statusændringer gemmes med brugerens e-mail.

## 3. Ugentlig rutine

1. Åbn dashboardet mandag. Fanen *Ugens fem* viser kandidaterne.
2. Kopiér prompten fra *Prompt til Claude* og indsæt den i Claude for at få begrundelserne.
3. Sæt status på dem, der kontaktes (fanen *Radar* → klik på en række). *Pipeline* og nøgletallene øverst følger succesmålene: kontakter, møder, kontrakter og tid til kontrakt.

## Vigtigt at vide

- **Historik kan ikke hentes bagud.** Twitch giver kun følgertal for i dag. 7-dages vækst kræver ca. en uges kørsel, 30-dages ca. en måned. Før da viser dashboardet, at der ikke er nok data.
- **Følgertal og 401.** Twitchs dokumentation kræver en brugertoken med scope `moderator:read:followers` til *Get Channel Followers*, mens andre kilder siger, at det samlede antal kan hentes uden. Kør `python talentradar.py check` med jeres nøgler. Giver den 401, så generér en brugertoken med dette scope (fx `twitch token -u -s moderator:read:followers` i Twitch CLI) og læg den som `TWITCH_USER_TOKEN`.
- **Alder og forhold til spilreklame** fremgår ikke af data og skal tjekkes manuelt, før Aros kontakter et navn.
- Sprogfilteret (`da`) bygger på det sprog, streameren selv har sat.
- `IRL` er ikke længere en kategori på Twitch (slået sammen med Just Chatting i 2022), så Just Chatting vægter højest.
- Dashboardet viser navngivne personer. Hold repoet privat, appen privat og invitér kun dem, der skal bruge det.

## Tilpasning

Øverst i `core.py`: kategorivægte, spilkategorier, bureau-navne, minimumsgrænser og `MAX_FOLLOWERS`. Filtre kan også ændres i dashboardets sidebjælke.

## Når Aros vil overtage

Alt ligger i et repo og en database, så det kan flyttes. Skift `DATABASE_URL` til Aros' egen database, flyt repoet til deres GitHub eller server, og hosting af dashboardet til en løsning med firma-login (fx Streamlit i Snowflake eller en intern server).

## Kommandolinje

| Kommando | Hvad |
|---|---|
| `python talentradar.py check` | Test nøgler og API-adgang |
| `python talentradar.py collect` | Hent streams og følgertal (det Actions gør) |
| `python talentradar.py report` | Excel-liste i `output/` |
| `python talentradar.py prompt` | Claude-prompt i `output/` |
| `python talentradar.py demo` | Demodata + Excel + prompt |
