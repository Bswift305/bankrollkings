#!/usr/bin/env python3
"""Build the CFB per-team weekly log (season-long ATS / O-U record, auto-graded).

For each week, pull CFBD games + betting lines, grade every completed game that has
a consensus line against BOTH teams, and store a per-team weekly entry with a
plain-English comment. Output is committed to data/scenarios/cfb_team_log.json and
rendered on the Team Profile page (/tools/cfb-team).

Run:  source .env.local  (or have CFBD_API_KEY in .env.local)
      python research/cfb_favorites/build_cfb_team_log.py --year 2026 --weeks 1-3
Re-run each week; it rebuilds the whole log from scratch (idempotent).
"""
import argparse, json, os, pathlib, urllib.request, datetime

ROOT = pathlib.Path(__file__).resolve().parents[2]
OUT = ROOT / "data" / "scenarios" / "cfb_team_log.json"


def _key():
    k = os.environ.get("CFBD_API_KEY")
    if k:
        return k.strip()
    envf = ROOT / ".env.local"
    if envf.exists():
        for line in envf.read_text().splitlines():
            line = line.strip()
            if line.startswith("CFBD_API_KEY"):
                return line.split("=", 1)[1].strip().strip('"').strip("'")
    raise SystemExit("No CFBD_API_KEY found (env or .env.local)")


def _get(url, key):
    req = urllib.request.Request(url, headers={"Authorization": f"Bearer {key}"})
    return json.load(urllib.request.urlopen(req, timeout=45))


def _consensus(prov, field):
    vals = [float(p[field]) for p in prov if p.get(field) is not None]
    return (sum(vals) / len(vals)) if vals else None


def _ats(team_margin, team_line):
    """team_line is the spread from the team's perspective (favorite = negative).
    Cover when actual margin beats the number: margin + line > 0."""
    if team_line is None:
        return None, None
    edge = team_margin + team_line
    if abs(edge) < 1e-9:
        return "Push", 0.0
    return ("Cover" if edge > 0 else "No cover"), round(edge, 1)


def _comment(team_line, team_margin, ats_res, ats_edge, won):
    if team_line is None:
        return "No line posted."
    fav = team_line < 0
    num = abs(team_line)
    if fav:
        if not won:
            return f"Lost outright as a {num:.1f}-point favorite — a bad one."
        if ats_res == "Cover":
            return f"{num:.1f}-point favorite; covered, won by {team_margin:g} (+{ats_edge:g})."
        if ats_res == "Push":
            return f"{num:.1f}-point favorite; pushed, won by exactly {team_margin:g}."
        return f"{num:.1f}-point favorite; won by {team_margin:g} but failed to cover ({ats_edge:g})."
    else:
        if won:
            return f"{num:.1f}-point underdog; won outright (+{ats_edge:g} ATS)."
        if ats_res == "Cover":
            return f"{num:.1f}-point underdog; covered, lost by {-team_margin:g} (+{ats_edge:g})."
        if ats_res == "Push":
            return f"{num:.1f}-point underdog; pushed."
        return f"{num:.1f}-point underdog; didn't cover ({ats_edge:g})."


# Optional editorial overlay: our pre-game read, so the log ties back to what we said.
EDITORIAL = {
    ("Rutgers", 2026, 1): "We called this the cleanest spot on the slate — SP+ even said the number was too low. Lost outright. The loudest reminder that big-favorite reads are tendencies, not locks.",
    ("Utah", 2026, 1): "Our read held: top-30 overachiever with a veteran roster crushed the number despite a first-year head coach.",
    ("Missouri", 2026, 1): "We flagged 55.5 as simply too many points. Won by 40 — the number was the problem, exactly as called.",
    ("Minnesota", 2026, 1): "We flagged Minnesota as a fade risk (losing favorite-ATS record, wins-without-covering). They covered comfortably — one for the 'trend didn't hit' column.",
    ("UCF", 2026, 1): "We cautioned on Frost's personal big-favorite record. His debut back at UCF blew the doors off (+24.5). Caution overplayed this week.",
    ("Delaware", 2026, 1): "We said we couldn't rate a first-year FBS team. Barely covered (+3.5). Still building a book on them.",
}


def build(year, weeks):
    key = _key()
    teams = {}  # name -> list of week entries

    def touch(name):
        return teams.setdefault(name, [])

    for wk in weeks:
        try:
            games = _get(f"https://api.collegefootballdata.com/games?year={year}&week={wk}&seasonType=regular", key)
        except Exception as e:
            print(f"  wk{wk} games error: {e}")
            continue
        lines = {}
        try:
            for L in _get(f"https://api.collegefootballdata.com/lines?year={year}&week={wk}&seasonType=regular", key):
                lines[L.get("id")] = L.get("lines") or []
        except Exception as e:
            print(f"  wk{wk} lines error: {e}")
        graded = 0
        for g in games:
            if not g.get("completed"):
                continue
            hp, ap = g.get("homePoints"), g.get("awayPoints")
            if hp is None or ap is None:
                continue
            home, away = g.get("homeTeam"), g.get("awayTeam")
            prov = lines.get(g.get("id"), [])
            home_line = _consensus(prov, "spread")      # home perspective (fav = neg)
            total = _consensus(prov, "overUnder")
            if home_line is None:
                continue
            date = (g.get("startDate") or "")[:10]
            tot_actual = hp + ap
            ou = None
            if total is not None:
                ou = "Over" if tot_actual > total else ("Under" if tot_actual < total else "Push")
            for name, opp, pts, opp_pts, tline, is_home in (
                (home, away, hp, ap, home_line, True),
                (away, home, ap, hp, (-home_line if home_line is not None else None), False),
            ):
                margin = pts - opp_pts
                won = margin > 0
                ats_res, ats_edge = _ats(margin, tline)
                entry = {
                    "week": wk,
                    "date": date,
                    "opp": opp,
                    "loc": "vs" if is_home else "@",
                    "line": round(tline, 1) if tline is not None else None,
                    "total": round(total, 1) if total is not None else None,
                    "pts": pts,
                    "opp_pts": opp_pts,
                    "margin": margin,
                    "ats": ats_res,
                    "ats_edge": ats_edge,
                    "ou": ou,
                    "tot_actual": tot_actual,
                    "comment": _comment(tline, margin, ats_res, ats_edge, won),
                }
                ed = EDITORIAL.get((name, year, wk))
                if ed:
                    entry["editorial"] = ed
                touch(name).append(entry)
            graded += 1
        print(f"  wk{wk}: graded {graded} games")

    # season summary per team
    out_teams = {}
    for name, wks in teams.items():
        wks.sort(key=lambda e: e["week"])
        c = sum(1 for e in wks if e["ats"] == "Cover")
        n = sum(1 for e in wks if e["ats"] == "No cover")
        p = sum(1 for e in wks if e["ats"] == "Push")
        ov = sum(1 for e in wks if e["ou"] == "Over")
        un = sum(1 for e in wks if e["ou"] == "Under")
        out_teams[name] = {
            "ats": f"{c}-{n}" + (f"-{p}" if p else ""),
            "ou": f"{ov}-{un}",
            "weeks": wks,
        }

    payload = {
        "meta": {
            "title": "CFB Team Weekly Log",
            "season": year,
            "source": "CFBD games + consensus lines (avg of available books)",
            "built": datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%d %H:%MZ"),
            "weeks_covered": sorted({e["week"] for wks in teams.values() for e in wks}),
        },
        "teams": out_teams,
    }
    OUT.write_text(json.dumps(payload, indent=1))
    print(f"Wrote {OUT}  ({len(out_teams)} teams)")


def _parse_weeks(s):
    if "-" in s:
        a, b = s.split("-", 1)
        return list(range(int(a), int(b) + 1))
    return [int(x) for x in s.split(",")]


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--year", type=int, default=2026)
    ap.add_argument("--weeks", default="1-3")
    a = ap.parse_args()
    build(a.year, _parse_weeks(a.weeks))
