#!/usr/bin/env python3
"""
Talentradar - scouting på data for Aros.

Finder de hurtigst voksende danske Twitch-streamere via Twitchs officielle Helix API.
Ingen skrabning af hjemmesider.

Kommandoer:
  check     Test at nøgler og API-adgang virker (1 kald)
  collect   Hent danske live-streams (kør flere gange dagen) og tag ugentligt følgertal
  report    Lav Excel-listen ud fra den gemte historik
  prompt    Lav den faste prompt til Claude med ugens kandidater
  demo      Lav demodata + Excel + prompt uden Twitch-nøgler

Dashboardet startes separat:  streamlit run dashboard.py
"""
import argparse
import os
import sys
import time
from datetime import date, datetime, timedelta, timezone

from sqlalchemy import text

from core import (LANGUAGE, MAX_FOLLOWERS, MAX_STREAM_PAGES, MIN_FOLLOWERS, OUT_DIR, SNAPSHOT_EVERY_DAYS,
                  build_rows, demo_engine, get_engine, load_env, now_iso, q, seed_demo)
from exports import write_excel, write_prompt

HELIX = "https://api.twitch.tv/helix"
TOKEN_URL = "https://id.twitch.tv/oauth2/token"


class Twitch:
    def __init__(self):
        import requests  # importeres her, så demo virker uden netforbindelse

        self.requests = requests
        self.client_id = os.environ.get("TWITCH_CLIENT_ID")
        self.client_secret = os.environ.get("TWITCH_CLIENT_SECRET")
        if not self.client_id or not self.client_secret:
            sys.exit("Mangler TWITCH_CLIENT_ID og TWITCH_CLIENT_SECRET (se README.md).")
        self.user_token = os.environ.get("TWITCH_USER_TOKEN") or None  # valgfri, se README
        r = requests.post(TOKEN_URL, data={"client_id": self.client_id, "client_secret": self.client_secret,
                                           "grant_type": "client_credentials"}, timeout=30)
        if r.status_code != 200:
            sys.exit(f"Kunne ikke hente adgangstoken ({r.status_code}): {r.text}")
        self.app_token = r.json()["access_token"]

    def get(self, path, params, use_user_token=False):
        token = self.user_token if (use_user_token and self.user_token) else self.app_token
        headers = {"Client-Id": self.client_id, "Authorization": f"Bearer {token}"}
        for _ in range(5):
            r = self.requests.get(f"{HELIX}/{path}", params=params, headers=headers, timeout=30)
            if r.status_code == 429:  # rate limit: vent til nulstilling
                reset = int(r.headers.get("Ratelimit-Reset", time.time() + 5))
                time.sleep(max(1, reset - time.time() + 1))
                continue
            return r
        return r


def collect(eng, tw):
    now = now_iso()
    cursor, seen, pages, batch = None, [], 0, []
    while pages < MAX_STREAM_PAGES:
        params = {"language": LANGUAGE, "first": 100}
        if cursor:
            params["after"] = cursor
        r = tw.get("streams", params)
        if r.status_code != 200:
            sys.exit(f"Fejl fra Twitch ved hentning af streams ({r.status_code}): {r.text}")
        body = r.json()
        for s in body["data"]:
            if s.get("type") != "live":
                continue
            seen.append(s["user_id"])
            batch.append(dict(ts=now, u=s["user_id"], v=s["viewer_count"], g=s.get("game_name", ""),
                              t=s.get("title", "")))
        cursor = body.get("pagination", {}).get("cursor")
        pages += 1
        if not cursor:
            break
    if batch:
        with eng.begin() as c:
            c.execute(text("INSERT INTO samples(ts, user_id, viewers, game_name, title) VALUES (:ts,:u,:v,:g,:t)"), batch)
    print(f"{len(seen)} danske live-streams gemt.")
    refresh_users(eng, tw, seen)
    snapshot_followers(eng, tw)


def refresh_users(eng, tw, user_ids):
    week_ago = (datetime.now(timezone.utc) - timedelta(days=7)).isoformat()
    known = {r[0]: r[1] for r in q(eng, "SELECT user_id, updated FROM users")}
    todo = [u for u in set(user_ids) if u not in known or known[u] < week_ago]
    for i in range(0, len(todo), 100):
        chunk = todo[i:i + 100]
        r = tw.get("users", [("id", u) for u in chunk])
        if r.status_code != 200:
            print(f"Advarsel: kunne ikke hente brugerprofiler ({r.status_code}).")
            return
        rows = [dict(u=u["id"], l=u["login"], n=u["display_name"], d=u.get("description", ""),
                     b=u.get("broadcaster_type", ""), t=now_iso()) for u in r.json()["data"]]
        with eng.begin() as c:
            c.execute(text(
                """INSERT INTO users(user_id, login, display_name, description, broadcaster_type, updated)
                   VALUES (:u,:l,:n,:d,:b,:t)
                   ON CONFLICT (user_id) DO UPDATE SET login=excluded.login, display_name=excluded.display_name,
                     description=excluded.description, broadcaster_type=excluded.broadcaster_type,
                     updated=excluded.updated"""), rows)
    print(f"{len(todo)} profiler opdateret.")


def snapshot_followers(eng, tw):
    today = date.today()
    cutoff_seen = (today - timedelta(days=14)).isoformat()
    cutoff_snap = (today - timedelta(days=SNAPSHOT_EVERY_DAYS)).isoformat()
    ids = [r[0] for r in q(
        eng,
        """SELECT DISTINCT s.user_id FROM samples s
           WHERE s.ts >= :seen AND NOT EXISTS (
               SELECT 1 FROM followers f WHERE f.user_id = s.user_id AND f.day > :snap)""",
        seen=cutoff_seen, snap=cutoff_snap)]
    if not ids:
        print("Ingen nye følgertal skal tages i dag.")
        return
    done = 0
    for uid in ids:
        r = tw.get("channels/followers", {"broadcaster_id": uid, "first": 1}, use_user_token=True)
        if r.status_code == 401:
            print("\nTwitch afviser opslag af følgertal (401). Det kræver muligvis en brugertoken.\n"
                  "Se README.md, afsnittet 'Hvis følgertal giver 401'. Stream-data er gemt alligevel.")
            break
        if r.status_code != 200:
            continue
        with eng.begin() as c:
            c.execute(text(
                """INSERT INTO followers(day, user_id, total) VALUES (:d,:u,:t)
                   ON CONFLICT (day, user_id) DO UPDATE SET total=excluded.total"""),
                dict(d=today.isoformat(), u=uid, t=r.json()["total"]))
        done += 1
        time.sleep(0.08)  # holder os langt under raten på 800 kald i minuttet
    print(f"Følgertal taget for {done} kanaler.")


def check(tw):
    r = tw.get("streams", {"language": LANGUAGE, "first": 1})
    print("Streams:", r.status_code)
    if r.status_code == 200 and r.json()["data"]:
        s = r.json()["data"][0]
        r2 = tw.get("channels/followers", {"broadcaster_id": s["user_id"], "first": 1}, use_user_token=True)
        print("Følgertal:", r2.status_code, r2.json().get("total") if r2.status_code == 200 else r2.text)


def main():
    load_env()
    p = argparse.ArgumentParser(description="Talentradar")
    p.add_argument("command", choices=["check", "collect", "report", "prompt", "demo"])
    p.add_argument("--min-followers", type=int, default=MIN_FOLLOWERS)
    p.add_argument("--max-followers", type=int, default=MAX_FOLLOWERS)
    a = p.parse_args()
    stamp = date.today().isoformat()

    if a.command == "demo":
        eng = demo_engine()
        seed_demo(eng)
        rows, excl, dropped = build_rows(eng, a.min_followers, a.max_followers)
        x = write_excel(rows, excl, dropped, OUT_DIR / f"DEMO_talentradar_{stamp}.xlsx", demo=True)
        pr = write_prompt(rows, OUT_DIR / f"DEMO_ugens_prompt_{stamp}.md", demo=True)
        print(f"Demo: {len(rows)} kanaler på listen, {len(excl)} fravalgt.\n  {x}\n  {pr}")
        return

    eng = get_engine()
    if a.command == "check":
        check(Twitch())
    elif a.command == "collect":
        collect(eng, Twitch())
    elif a.command == "report":
        rows, excl, dropped = build_rows(eng, a.min_followers, a.max_followers)
        if not rows:
            sys.exit("Listen er tom: der skal mindst ca. en uges historik til (kør 'collect' flere dage).")
        print(write_excel(rows, excl, dropped, OUT_DIR / f"talentradar_{stamp}.xlsx"))
    elif a.command == "prompt":
        rows, _, _ = build_rows(eng, a.min_followers, a.max_followers)
        print(write_prompt(rows, OUT_DIR / f"ugens_prompt_{stamp}.md"))


if __name__ == "__main__":
    main()
