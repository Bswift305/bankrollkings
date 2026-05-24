"""
Bankroll Kings - Injury Report Fetcher
======================================
Fetches NBA injury reports and calculates teammate boost opportunities.
"""

from datetime import datetime, timedelta
from html import unescape
from io import BytesIO
from pathlib import Path
import re

import pandas as pd
import requests
from pypdf import PdfReader

BASE_DIR = Path(__file__).parent.resolve()
DATA_DIR = BASE_DIR / 'data'
INJURIES_DIR = DATA_DIR / 'injuries'
INJURIES_DIR.mkdir(parents=True, exist_ok=True)
INJURIES_PATH = INJURIES_DIR / 'NBA_Injuries.csv'
INJURIES_BACKUP_PATH = INJURIES_DIR / 'NBA_Injuries_last_good.csv'
INJURIES_MANUAL_PATH = INJURIES_DIR / 'NBA_Injuries_Manual.csv'

TEAM_NAME_TO_ABBREV = {
    'Atlanta Hawks': 'ATL', 'Boston Celtics': 'BOS', 'Brooklyn Nets': 'BKN',
    'Charlotte Hornets': 'CHA', 'Chicago Bulls': 'CHI', 'Cleveland Cavaliers': 'CLE',
    'Dallas Mavericks': 'DAL', 'Denver Nuggets': 'DEN', 'Detroit Pistons': 'DET',
    'Golden State Warriors': 'GSW', 'Houston Rockets': 'HOU', 'Indiana Pacers': 'IND',
    'Los Angeles Clippers': 'LAC', 'Los Angeles Lakers': 'LAL', 'Memphis Grizzlies': 'MEM',
    'Miami Heat': 'MIA', 'Milwaukee Bucks': 'MIL', 'Minnesota Timberwolves': 'MIN',
    'New Orleans Pelicans': 'NOP', 'New York Knicks': 'NYK', 'Oklahoma City Thunder': 'OKC',
    'Orlando Magic': 'ORL', 'Philadelphia 76ers': 'PHI', 'Phoenix Suns': 'PHX',
    'Portland Trail Blazers': 'POR', 'Sacramento Kings': 'SAC', 'San Antonio Spurs': 'SAS',
    'Toronto Raptors': 'TOR', 'Utah Jazz': 'UTA', 'Washington Wizards': 'WAS'
}

TEAM_NAMES_BY_LENGTH = sorted(TEAM_NAME_TO_ABBREV.keys(), key=len, reverse=True)
STATUS_PATTERN = r'Out|Doubtful|Questionable|Probable|Available|Inactive|Suspended'
PLAYER_PATTERN = (
    r"[A-Z][A-Za-z'\.-]+(?:\s(?:Jr\.|Sr\.|II|III|IV))?,\s"
    r"(?:[A-Z][A-Za-z'\.-]*)(?:\s[A-Z][A-Za-z'\.-]*)*"
)


def load_existing_injuries():
    if not INJURIES_PATH.exists():
        return pd.DataFrame()
    try:
        return pd.read_csv(INJURIES_PATH)
    except Exception:
        return pd.DataFrame()


def load_last_good_injuries():
    for path in [INJURIES_BACKUP_PATH, INJURIES_PATH]:
        if not path.exists():
            continue
        try:
            df = pd.read_csv(path)
        except Exception:
            continue
        if not df.empty and {'Player', 'Team', 'Status'}.issubset(df.columns):
            return df
    return pd.DataFrame()


def ensure_manual_injuries_template():
    required_cols = ['Player', 'Team', 'Status', 'Reason', 'Updated', 'Active', 'ExpiresOn']
    if not INJURIES_MANUAL_PATH.exists():
        pd.DataFrame(columns=required_cols).to_csv(INJURIES_MANUAL_PATH, index=False)
        return
    try:
        df = pd.read_csv(INJURIES_MANUAL_PATH)
    except Exception:
        pd.DataFrame(columns=required_cols).to_csv(INJURIES_MANUAL_PATH, index=False)
        return
    changed = False
    for col in required_cols:
        if col not in df.columns:
            df[col] = ''
            changed = True
    if changed or list(df.columns) != required_cols:
        df = df[required_cols].copy()
        df.to_csv(INJURIES_MANUAL_PATH, index=False)


def load_manual_injuries():
    ensure_manual_injuries_template()
    try:
        df = pd.read_csv(INJURIES_MANUAL_PATH)
    except Exception:
        return pd.DataFrame(columns=['Player', 'Team', 'Status', 'Reason', 'Updated', 'Active', 'ExpiresOn'])
    for col in ['Player', 'Team', 'Status', 'Reason', 'Updated', 'Active', 'ExpiresOn']:
        if col not in df.columns:
            df[col] = ''
    for col in ['Player', 'Team', 'Status', 'Reason', 'Updated', 'Active', 'ExpiresOn']:
        df[col] = df[col].fillna('').astype(str).str.strip()

    df = df[df['Player'] != ''].copy()
    if df.empty:
        return df

    now = pd.Timestamp.now()
    updated_dt = pd.to_datetime(df['Updated'], errors='coerce')
    expires_dt = pd.to_datetime(df['ExpiresOn'], errors='coerce')
    active_flag = df['Active'].str.lower().isin({'1', 'true', 'yes', 'y', 'active'})
    recent_flag = updated_dt >= (now - pd.Timedelta(days=3))
    unexpired_flag = expires_dt.isna() | (expires_dt >= now.normalize())

    # Legacy manual rows without an explicit Active flag only count if they were updated recently.
    keep_mask = unexpired_flag & (active_flag | recent_flag)
    return df[keep_mask].copy()


def standardize_status(value):
    value = str(value or '').strip()
    if not value:
        return 'Unknown'
    status_map = {
        'Out': 'OUT',
        'Doubtful': 'DOUBTFUL',
        'Questionable': 'QUESTIONABLE',
        'Probable': 'PROBABLE',
        'Day-To-Day': 'GTD',
        'Day To Day': 'GTD',
        'Game Time Decision': 'GTD',
        'Available': 'AVAILABLE',
        'Active': 'ACTIVE',
    }
    return status_map.get(value, value.upper())


def merge_manual_injuries(df):
    manual = load_manual_injuries()
    if manual.empty:
        return df
    if df is None or df.empty:
        merged = manual.copy()
    else:
        merged = pd.concat([df, manual], ignore_index=True)
    merged['Status'] = merged['Status'].apply(standardize_status)
    merged['Player'] = merged['Player'].fillna('').astype(str).str.strip()
    merged = merged[merged['Player'] != ''].copy()
    return merged.drop_duplicates(subset=['Player'], keep='last').reset_index(drop=True)


def save_injuries(df):
    df.to_csv(INJURIES_PATH, index=False)
    if not df.empty:
        df.to_csv(INJURIES_BACKUP_PATH, index=False)


def build_safe_session():
    session = requests.Session()
    session.trust_env = False
    session.proxies.clear()
    return session


def parse_primary_injury_payload(data):
    injuries = []
    if not isinstance(data, dict):
        return injuries
    teams = data.get('payload', {}).get('teams', [])
    for team_data in teams:
        team_name = team_data.get('teamName', '')
        team_city = team_data.get('teamCity', '')
        full_name = f"{team_city} {team_name}".strip()
        team_abbrev = TEAM_NAME_TO_ABBREV.get(full_name, str(team_name or '')[:3].upper())
        for player in team_data.get('players', []):
            injuries.append({
                'Player': player.get('playerName', ''),
                'Team': team_abbrev,
                'Status': player.get('injuryStatus', 'Unknown'),
                'Reason': player.get('injuryDescription', 'Unknown'),
                'Updated': datetime.now().strftime('%Y-%m-%d %H:%M'),
            })
    return injuries


def parse_fallback_injury_payload(data):
    injuries = []
    if not isinstance(data, dict):
        return injuries
    candidate_rows = []
    for key in ['injuryCards', 'items', 'list', 'players']:
        if isinstance(data.get(key), list):
            candidate_rows = data[key]
            break
    for row in candidate_rows:
        player_name = row.get('playerName') or row.get('name') or row.get('player')
        team_name = row.get('team') or row.get('teamName') or row.get('teamTricode')
        team_abbrev = TEAM_NAME_TO_ABBREV.get(team_name, str(team_name or '')[:3].upper())
        status = row.get('injuryStatus') or row.get('status') or row.get('designation') or 'Unknown'
        reason = row.get('injuryDescription') or row.get('reason') or row.get('comment') or 'Unknown'
        if player_name and team_abbrev:
            injuries.append({
                'Player': player_name,
                'Team': team_abbrev,
                'Status': status,
                'Reason': reason,
                'Updated': datetime.now().strftime('%Y-%m-%d %H:%M'),
            })
    return injuries


def parse_espn_injury_table(html):
    injuries = []
    section_pattern = re.compile(
        r'<span class="injuries__teamName ml2">(.*?)</span>.*?<tbody class="Table__TBODY">(.*?)</tbody>',
        re.IGNORECASE | re.DOTALL,
    )
    row_pattern = re.compile(
        r'<td class="col-name Table__TD">.*?>(.*?)</a></td>.*?'
        r'<td class="col-date Table__TD">(.*?)</td>.*?'
        r'<td class="col-stat Table__TD">.*?>(.*?)</span></td>.*?'
        r'<td class="col-desc Table__TD">(.*?)</td>',
        re.IGNORECASE | re.DOTALL,
    )

    for team_name, tbody in section_pattern.findall(html):
        team_name = unescape(re.sub(r'<.*?>', '', team_name)).strip()
        team_code = TEAM_NAME_TO_ABBREV.get(team_name)
        if not team_code:
            continue
        for player_name, return_date, status, comment in row_pattern.findall(tbody):
            player_name = unescape(re.sub(r'<.*?>', '', player_name)).strip()
            return_date = unescape(re.sub(r'<.*?>', '', return_date)).strip()
            status = unescape(re.sub(r'<.*?>', '', status)).strip()
            comment = unescape(re.sub(r'<.*?>', '', comment)).strip()
            if player_name and status:
                reason = comment
                if return_date and return_date.lower() != 'nan':
                    reason = f"{return_date} | {comment}" if comment else return_date
                injuries.append({
                    'Player': player_name,
                    'Team': team_code,
                    'Status': status,
                    'Reason': reason or 'ESPN injury report',
                    'Updated': datetime.now().strftime('%Y-%m-%d %H:%M'),
                })
    return injuries


def extract_latest_official_injury_report_url(html):
    matches = re.findall(
        r'https://ak-static\.cms\.nba\.com/referee/injury/Injury-Report_(\d{4}-\d{2}-\d{2})_(\d{2})_(\d{2})(AM|PM)\.pdf',
        html,
        re.IGNORECASE,
    )
    if not matches:
        return None

    def sort_key(match):
        date_part, hour_text, minute_text, meridiem = match
        hour = int(hour_text)
        minute = int(minute_text)
        if meridiem.upper() == 'PM' and hour != 12:
            hour += 12
        if meridiem.upper() == 'AM' and hour == 12:
            hour = 0
        return (date_part, hour, minute)

    latest = max(matches, key=sort_key)
    date_part, hour_text, minute_text, meridiem = latest
    return f"https://ak-static.cms.nba.com/referee/injury/Injury-Report_{date_part}_{hour_text}_{minute_text}{meridiem.upper()}.pdf"


def extract_official_pdf_text(pdf_bytes):
    reader = PdfReader(BytesIO(pdf_bytes))
    tokens = []
    for page in reader.pages:
        text = page.extract_text() or ''
        for raw_line in text.splitlines():
            line = re.sub(r'\s+', ' ', raw_line).strip()
            if line:
                tokens.append(line)
    return ' '.join(tokens)


def parse_team_section(section_text, team_code, update_stamp):
    injuries = []
    if not section_text or 'NOT YET SUBMITTED' in section_text.upper():
        return injuries
    pattern = re.compile(
        rf'(?P<player>{PLAYER_PATTERN})\s+(?P<status>{STATUS_PATTERN})\s+'
        rf'(?P<reason>.*?)(?=(?P<next>{PLAYER_PATTERN}\s+(?:{STATUS_PATTERN}))|$)',
        re.IGNORECASE,
    )
    for match in pattern.finditer(section_text):
        player = match.group('player').strip()
        status = match.group('status').strip()
        reason = re.sub(r'\s+', ' ', (match.group('reason') or '')).strip()
        injuries.append({
            'Player': player,
            'Team': team_code,
            'Status': status,
            'Reason': reason,
            'Updated': update_stamp,
        })
    return injuries


def parse_official_pdf_text(pdf_text):
    injuries = []
    update_stamp = datetime.now().strftime('%Y-%m-%d %H:%M')
    text = re.sub(r'\s+', ' ', pdf_text).strip()
    if 'Reason ' in text:
        text = text.split('Reason ', 1)[1]
    game_split = re.split(r'(?=\d{2}/\d{2}/\d{4}\s+\d{2}:\d{2}\s+\(ET\)\s+[A-Z0-9]{2,4}@[A-Z0-9]{2,4}\s+)', text)

    for block in game_split:
        block = block.strip()
        if not block:
            continue
        block = re.sub(r'^\d{2}/\d{2}/\d{4}\s+\d{2}:\d{2}\s+\(ET\)\s+[A-Z0-9]{2,4}@[A-Z0-9]{2,4}\s+', '', block)
        team_hits = []
        for team_name in TEAM_NAMES_BY_LENGTH:
            idx = block.find(team_name)
            if idx >= 0:
                team_hits.append((idx, team_name))
        team_hits.sort(key=lambda item: item[0])

        unique_hits = []
        seen_teams = set()
        for idx, team_name in team_hits:
            if team_name not in seen_teams:
                unique_hits.append((idx, team_name))
                seen_teams.add(team_name)
            if len(unique_hits) >= 2:
                break

        for i, (idx, team_name) in enumerate(unique_hits):
            start = idx + len(team_name)
            end = unique_hits[i + 1][0] if i + 1 < len(unique_hits) else len(block)
            section = block[start:end].strip()
            injuries.extend(parse_team_section(section, TEAM_NAME_TO_ABBREV[team_name], update_stamp))
    return injuries


def fetch_official_nba_injury_report(session):
    print("  Trying official NBA injury report page...")
    page_url = "https://official.nba.com/nba-injury-report-2025-26-season/"
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
        'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
        'Referer': 'https://official.nba.com/',
    }
    page_response = session.get(page_url, headers=headers, timeout=20)
    if page_response.status_code != 200:
        print(f"  Official NBA injury page returned status {page_response.status_code}")
        return []

    pdf_url = extract_latest_official_injury_report_url(page_response.text)
    if not pdf_url:
        print("  Official NBA injury page did not expose a report PDF")
        return []

    pdf_response = session.get(pdf_url, headers=headers, timeout=20)
    if pdf_response.status_code != 200:
        print(f"  Official NBA injury PDF returned status {pdf_response.status_code}")
        return []

    pdf_text = extract_official_pdf_text(pdf_response.content)
    injuries = parse_official_pdf_text(pdf_text)
    if injuries:
        print(f"  Official NBA report returned {len(injuries)} injuries")
    else:
        print("  Official NBA report returned 0 parsed injuries")
    return injuries


def fetch_espn_injury_report(session):
    print("  Trying ESPN injuries fallback...")
    url = "https://www.espn.com/nba/injuries"
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
        'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
        'Referer': 'https://www.espn.com/nba/',
    }
    response = session.get(url, headers=headers, timeout=20)
    if response.status_code != 200:
        print(f"  ESPN injuries page returned status {response.status_code}")
        return []
    injuries = parse_espn_injury_table(response.text)
    if injuries:
        print(f"  ESPN fallback returned {len(injuries)} injuries")
    else:
        print("  ESPN fallback returned 0 parsed injuries")
    return injuries


def fetch_nba_injury_report():
    """
    Fetch official NBA injury report.
    Returns DataFrame with: Player, Team, Status, Reason, Updated
    """
    print("\n" + "=" * 60)
    print("  FETCHING NBA INJURY REPORT")
    print("=" * 60)

    ensure_manual_injuries_template()
    injuries = []
    existing_injuries = load_existing_injuries()
    last_good_injuries = load_last_good_injuries()
    session = build_safe_session()

    try:
        injuries = fetch_official_nba_injury_report(session)
    except Exception as e:
        print(f"  Official NBA report failed: {e}")

    try:
        if not injuries:
            url = "https://cdn.nba.com/static/json/liveData/injuries/injuries.json"
            headers = {
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
                'Accept': 'application/json',
                'Referer': 'https://www.nba.com/',
            }
            response = session.get(url, headers=headers, timeout=15)
            if response.status_code == 200:
                injuries = parse_primary_injury_payload(response.json())
                print(f"  Found {len(injuries)} injuries from NBA API")
            else:
                print(f"  NBA API returned status {response.status_code}")
    except Exception as e:
        print(f"  Error fetching from NBA API: {e}")

    if not injuries:
        try:
            print("  Trying stats.nba.com fallback...")
            url = "https://stats.nba.com/js/data/widgets/injuries.json"
            headers = {
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
                'Accept': 'application/json',
                'Referer': 'https://www.nba.com/',
                'x-nba-stats-origin': 'stats',
                'x-nba-stats-token': 'true',
            }
            response = session.get(url, headers=headers, timeout=15)
            if response.status_code == 200:
                injuries = parse_fallback_injury_payload(response.json())
                print(f"  Fallback returned {len(injuries)} injuries")
            else:
                print(f"  Fallback returned status {response.status_code}")
        except Exception as e:
            print(f"  Fallback also failed: {e}")

    if not injuries:
        try:
            injuries = fetch_espn_injury_report(session)
        except Exception as e:
            print(f"  ESPN fallback failed: {e}")

    if injuries:
        df = pd.DataFrame(injuries)
        df['Status'] = df['Status'].apply(standardize_status)
        df = merge_manual_injuries(df)
        save_injuries(df)
        print(f"\n  Saved {len(df)} injuries to {INJURIES_PATH}")
        print("\n  INJURY SUMMARY BY STATUS:")
        print("  " + "-" * 40)
        for status in ['OUT', 'DOUBTFUL', 'QUESTIONABLE', 'GTD', 'PROBABLE', 'AVAILABLE', 'ACTIVE']:
            count = len(df[df['Status'] == status])
            if count > 0:
                print(f"  {status}: {count} players")
        return df

    if not last_good_injuries.empty:
        preserved = merge_manual_injuries(last_good_injuries)
        save_injuries(preserved)
        print(f"\n  No live injuries found - preserved last good file with {len(preserved)} rows")
        return preserved

    if not existing_injuries.empty:
        preserved = merge_manual_injuries(existing_injuries)
        save_injuries(preserved)
        print(f"\n  No live injuries found - preserved existing file with {len(preserved)} rows")
        return preserved

    print("\n  No live injuries found and no prior injury file exists")
    df = merge_manual_injuries(pd.DataFrame(columns=['Player', 'Team', 'Status', 'Reason', 'Updated']))
    save_injuries(df)
    return df


def calculate_teammate_boosts(gamelogs_path=None):
    """
    Analyze game logs to calculate how teammates perform when key players are OUT.
    Returns DataFrame with boost percentages.
    """
    print("\n" + "=" * 60)
    print("  CALCULATING TEAMMATE BOOST OPPORTUNITIES")
    print("=" * 60)

    if gamelogs_path is None:
        gamelogs_path = DATA_DIR / 'gamelogs' / 'NBA_GameLogs.csv'
    if not gamelogs_path.exists():
        print(f"  Game logs not found at {gamelogs_path}")
        return pd.DataFrame()

    gamelogs = pd.read_csv(gamelogs_path)
    if gamelogs.empty:
        print("  Game logs are empty")
        return pd.DataFrame()

    print(f"  Loaded {len(gamelogs)} game log entries")
    boosts = []
    for team in gamelogs['Team'].unique():
        team_logs = gamelogs[gamelogs['Team'] == team].copy()
        if team_logs.empty:
            continue

        player_stats = team_logs.groupby('Player').agg({
            'MIN': 'mean',
            'PTS': 'mean',
            'Date': 'count',
        }).rename(columns={'Date': 'Games'})
        key_players = player_stats[(player_stats['MIN'] >= 25) & (player_stats['Games'] >= 10)].index.tolist()
        if not key_players:
            continue

        team_dates = team_logs['Date'].unique()
        for key_player in key_players:
            key_player_games = set(team_logs[team_logs['Player'] == key_player]['Date'].unique())
            games_without = [d for d in team_dates if d not in key_player_games]
            if len(games_without) < 2:
                continue

            other_players = [p for p in team_logs['Player'].unique() if p != key_player]
            for other_player in other_players:
                other_logs = team_logs[team_logs['Player'] == other_player]
                if len(other_logs) < 5:
                    continue

                with_key = other_logs[~other_logs['Date'].isin(games_without)]
                without_key = other_logs[other_logs['Date'].isin(games_without)]
                if len(with_key) < 3 or len(without_key) < 2:
                    continue

                for stat in ['PTS', 'REB', 'AST', '3PM', 'MIN']:
                    if stat not in other_logs.columns:
                        continue
                    avg_with = with_key[stat].mean()
                    avg_without = without_key[stat].mean()
                    if avg_with > 0:
                        boost_pct = ((avg_without - avg_with) / avg_with) * 100
                        if boost_pct >= 5:
                            boosts.append({
                                'Team': team,
                                'Key_Player_Out': key_player,
                                'Beneficiary': other_player,
                                'Stat': stat,
                                'Avg_With': round(avg_with, 1),
                                'Avg_Without': round(avg_without, 1),
                                'Boost_Pct': round(boost_pct, 1),
                                'Games_Without': len(without_key),
                                'Games_With': len(with_key),
                            })

    if boosts:
        df = pd.DataFrame(boosts).sort_values('Boost_Pct', ascending=False)
        output_path = INJURIES_DIR / 'Teammate_Boosts.csv'
        df.to_csv(output_path, index=False)
        print(f"\n  Found {len(df)} boost opportunities")
        print(f"  Saved to {output_path}")
        print("\n  TOP 15 BOOST OPPORTUNITIES:")
        print("  " + "-" * 70)
        for _, row in df.head(15).iterrows():
            message_1 = f"  When {row['Key_Player_Out']} is OUT: {row['Beneficiary']} gets +{row['Boost_Pct']}% {row['Stat']}"
            message_2 = f"       ({row['Avg_With']} -> {row['Avg_Without']}) based on {row['Games_Without']} games"
            try:
                print(message_1)
                print(message_2)
            except UnicodeEncodeError:
                print(message_1.encode("ascii", errors="ignore").decode("ascii"))
                print(message_2.encode("ascii", errors="ignore").decode("ascii"))
        return df

    print("\n  No significant boosts found")
    return pd.DataFrame()


def get_active_boost_plays():
    """
    Combine current injuries with boost data to find active opportunities.
    """
    print("\n" + "=" * 60)
    print("  FINDING ACTIVE BOOST PLAYS")
    print("=" * 60)

    injuries_path = INJURIES_DIR / 'NBA_Injuries.csv'
    boosts_path = INJURIES_DIR / 'Teammate_Boosts.csv'
    if not injuries_path.exists():
        print("  No injury report found. Run fetch_nba_injury_report() first.")
        return pd.DataFrame()
    if not boosts_path.exists():
        print("  No boost data found. Run calculate_teammate_boosts() first.")
        return pd.DataFrame()

    injuries = pd.read_csv(injuries_path)
    boosts = pd.read_csv(boosts_path)
    out_players = injuries[injuries['Status'].isin(['OUT', 'DOUBTFUL'])]['Player'].tolist()
    if not out_players:
        print("  No players currently OUT or DOUBTFUL")
        return pd.DataFrame()

    print(f"  Found {len(out_players)} players OUT/DOUBTFUL")
    active_boosts = boosts[boosts['Key_Player_Out'].isin(out_players)].copy()
    if active_boosts.empty:
        print("  No boost data for currently injured players")
        return pd.DataFrame()

    active_boosts = active_boosts.merge(
        injuries[['Player', 'Status', 'Reason']],
        left_on='Key_Player_Out',
        right_on='Player',
        how='left',
    )
    active_boosts = active_boosts.drop(columns=['Player'])
    active_boosts = active_boosts.rename(columns={'Status': 'Injury_Status', 'Reason': 'Injury_Reason'})
    active_boosts = active_boosts.sort_values('Boost_Pct', ascending=False)

    output_path = INJURIES_DIR / 'Active_Boost_Plays.csv'
    active_boosts.to_csv(output_path, index=False)
    print(f"\n  Found {len(active_boosts)} active boost plays")
    print(f"  Saved to {output_path}")

    print("\n  ACTIVE BOOST PLAYS FOR TONIGHT:")
    print("  " + "=" * 70)
    seen = set()
    for _, row in active_boosts.iterrows():
        key = (row['Beneficiary'], row['Stat'])
        if key in seen:
            continue
        seen.add(key)
        if len(seen) > 20:
            break
        print(f"\n  {row['Key_Player_Out']} is {row['Injury_Status']} ({row['Injury_Reason']})")
        print(f"  -> {row['Beneficiary']} {row['Stat']}: {row['Avg_With']} -> {row['Avg_Without']} (+{row['Boost_Pct']}%)")
        print(f"     Based on {row['Games_Without']} games without {row['Key_Player_Out']}")

    return active_boosts


def run_full_injury_update():
    """
    Run complete injury analysis pipeline.
    """
    print("\n" + "=" * 60)
    print("  BANKROLL KINGS - INJURY UPDATE")
    print(f"  {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 60)

    injuries = fetch_nba_injury_report()
    boosts_path = INJURIES_DIR / 'Teammate_Boosts.csv'
    if not boosts_path.exists():
        boosts = calculate_teammate_boosts()
    else:
        file_time = datetime.fromtimestamp(boosts_path.stat().st_mtime)
        if datetime.now() - file_time > timedelta(days=1):
            print("\n  Boost data is stale, recalculating...")
            boosts = calculate_teammate_boosts()
        else:
            print("\n  Using existing boost data (less than 1 day old)")
            boosts = pd.read_csv(boosts_path)

    active = get_active_boost_plays()
    print("\n" + "=" * 60)
    print("  INJURY UPDATE COMPLETE!")
    print("=" * 60)
    return {'injuries': injuries, 'boosts': boosts, 'active_plays': active}


if __name__ == '__main__':
    run_full_injury_update()
