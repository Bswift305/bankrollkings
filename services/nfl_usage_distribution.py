"""NFL usage-distribution model — committee backfields and receiver-room splits.

Pure Python, standard library only (no pandas), so it can be unit-tested from
the command line and imported cheaply by the prop scorer.

What it does
------------
As a season progresses a backfield or receiver room changes shape: a second
back develops into a real workload (the Detroit "dual-back" Gibbs/Montgomery
look) or a second receiver grows into a co-#1. That shift is hard evidence
about role, and role drives prop volume. This module:

  1. classifies each team's backfield (bell_cow / dual_back / committee) and
     receiver room (wr_alpha / wr_two_headed / wr_spread) from usage shares,
  2. reads an in-season *trend* (recent-window share vs. season share) so an
     emerging RB2/WR2 is picked up while it is happening, and
  3. turns a player's role in that scheme into a signed prop-score delta
     (fade the capped lead man's over, buy the developing second option).

The prop scorer (`calculate_nfl_prop_score.py`) consumes `usage_signal()` as an
additive component, exactly like its other contextual boosts/penalties.
"""
from __future__ import annotations

from dataclasses import dataclass, field


# ── classification thresholds ────────────────────────────────────────────────
BELL_COW_LEAD = 0.68      # RB1 carry share at/above this = bell-cow
DUAL_BACK_RB2 = 0.28      # RB2 carry share at/above this = real second back
COMMITTEE_RB3 = 0.20      # RB3 carry share at/above this (with soft lead)
WR_ALPHA_LEAD = 0.30      # WR1 target share at/above this…
WR_ALPHA_GAP = 0.08       # …and this far clear of WR2 = alpha
WR_TWO_HEADED_2 = 0.22    # WR2 target share at/above this = co-#1s
WR_SPREAD_LEAD = 0.26     # WR1 target share below this = spread-it-around
TREND_HOT = 0.06          # recent-vs-season share jump we call "developing"

# Max absolute delta this component contributes to BK_NFL_PropScore. Kept modest
# — role is hard evidence but should not swamp exact-line hit-rate signals.
SIGNAL_CLAMP = 7.0


def _clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


# ── per-player usage record ──────────────────────────────────────────────────
@dataclass
class PlayerUsage:
    player: str
    team: str
    position: str          # "RB" | "WR"
    rank: int              # 0-based within the position group (0 = lead)
    carries: float = 0.0
    targets: float = 0.0
    recent_carries: float = 0.0
    recent_targets: float = 0.0
    carry_share: float = 0.0
    target_share: float = 0.0
    trend: float = 0.0     # recent group share − season group share

    @property
    def role(self) -> str:
        return f"{self.position}{self.rank + 1}"


@dataclass
class TeamUsage:
    team: str
    rb_scheme: str = "unknown"
    wr_scheme: str = "unknown"
    players: list[PlayerUsage] = field(default_factory=list)


# ── position inference ───────────────────────────────────────────────────────
def infer_position(carries: float, targets: float, receptions: float, explicit: str | None = None) -> str | None:
    if explicit:
        e = explicit.strip().upper()
        if e in {"RB", "HB", "FB"}:
            return "RB"
        if e in {"WR", "TE"}:
            return "WR"
    if carries >= 20 or carries > receptions:
        return "RB"
    if targets > 0 or receptions > 0:
        return "WR"
    return None


# ── classification ───────────────────────────────────────────────────────────
def classify_backfield(carry_shares: list[float]) -> str:
    shares = sorted((s for s in carry_shares if s > 0), reverse=True)
    if not shares:
        return "unknown"
    s1 = shares[0]
    s2 = shares[1] if len(shares) > 1 else 0.0
    s3 = shares[2] if len(shares) > 2 else 0.0
    if s3 >= COMMITTEE_RB3 and s1 < 0.5:
        return "committee"
    if s2 >= DUAL_BACK_RB2 and s1 <= 0.62:
        return "dual_back"
    if s1 >= BELL_COW_LEAD:
        return "bell_cow"
    if s2 >= DUAL_BACK_RB2:
        return "dual_back"
    return "committee"


def classify_receiver_room(target_shares: list[float]) -> str:
    shares = sorted((s for s in target_shares if s > 0), reverse=True)
    if not shares:
        return "unknown"
    s1 = shares[0]
    s2 = shares[1] if len(shares) > 1 else 0.0
    if s1 >= WR_ALPHA_LEAD and (s1 - s2) >= WR_ALPHA_GAP:
        return "wr_alpha"
    # No receiver commands the room -> targets are spread around.
    if s1 < WR_SPREAD_LEAD:
        return "wr_spread"
    if s2 >= WR_TWO_HEADED_2 and (s1 - s2) < WR_ALPHA_GAP:
        return "wr_two_headed"
    return "wr_two_headed"


# ── aggregation ──────────────────────────────────────────────────────────────
def build_team_usage(rows: list[dict]) -> dict[str, TeamUsage]:
    """Aggregate per-player usage rows into per-team scheme classifications.

    Each row: {player, team, carries, targets, receptions,
               recent_carries?, recent_targets?, position?}.
    Values are season totals; `recent_*` are last-window totals (optional).
    """
    by_team: dict[str, dict[str, PlayerUsage]] = {}
    for r in rows:
        team = str(r.get("team") or "").strip()
        player = str(r.get("player") or "").strip()
        if not team or not player:
            continue
        carries = float(r.get("carries") or 0)
        targets = float(r.get("targets") or 0)
        receptions = float(r.get("receptions") or 0)
        pos = infer_position(carries, targets, receptions, r.get("position"))
        if pos is None:
            continue
        pu = by_team.setdefault(team, {}).get(player)
        if pu is None:
            pu = PlayerUsage(player=player, team=team, position=pos, rank=0)
            by_team[team][player] = pu
        pu.carries += carries
        pu.targets += targets
        pu.recent_carries += float(r.get("recent_carries") or 0)
        pu.recent_targets += float(r.get("recent_targets") or 0)

    result: dict[str, TeamUsage] = {}
    for team, players in by_team.items():
        rbs = [p for p in players.values() if p.position == "RB"]
        wrs = [p for p in players.values() if p.position == "WR"]
        _finalize_group(rbs, "RB")
        _finalize_group(wrs, "WR")
        tu = TeamUsage(team=team)
        tu.rb_scheme = classify_backfield([p.carry_share for p in rbs])
        tu.wr_scheme = classify_receiver_room([p.target_share for p in wrs])
        tu.players = rbs + wrs
        result[team] = tu
    return result


def _finalize_group(group: list[PlayerUsage], position: str) -> None:
    key = (lambda p: p.carries) if position == "RB" else (lambda p: p.targets)
    group.sort(key=key, reverse=True)
    carry_total = sum(p.carries for p in group) or 0.0
    target_total = sum(p.targets for p in group) or 0.0
    recent_total = sum((p.recent_carries if position == "RB" else p.recent_targets) for p in group) or 0.0
    for rank, p in enumerate(group):
        p.rank = rank
        p.carry_share = round(p.carries / carry_total, 3) if carry_total else 0.0
        p.target_share = round(p.targets / target_total, 3) if target_total else 0.0
        season_val = p.carries if position == "RB" else p.targets
        recent_val = p.recent_carries if position == "RB" else p.recent_targets
        season_total = carry_total if position == "RB" else target_total
        if season_total and recent_total and recent_val:
            p.trend = round((recent_val / recent_total) - (season_val / season_total), 3)
        else:
            p.trend = 0.0


# ── prop-score signal ────────────────────────────────────────────────────────
def _is_rushing(stat: str) -> bool:
    return stat.startswith("RUSH") or "CARR" in stat

def _is_receiving(stat: str) -> bool:
    return "REC" in stat or "TARGET" in stat


def usage_signal(player_usage: PlayerUsage | None, scheme: str, stat: str, direction: str) -> dict:
    """Return {score_delta, tags, note} for one prop row.

    Positive delta supports the row's chosen side; negative fades it.
    Lead men in a committee get their over faded; developing second options get
    their over bought. Mirrored for unders.
    """
    if player_usage is None:
        return {"score_delta": 0.0, "tags": [], "note": ""}
    stat = (stat or "").upper()
    direction = (direction or "OVER").upper()
    rushing = _is_rushing(stat)
    receiving = _is_receiving(stat)
    if not rushing and not receiving:
        return {"score_delta": 0.0, "tags": [], "note": ""}

    is_lead = player_usage.rank == 0
    is_second = player_usage.rank == 1
    over = direction == "OVER"
    raw = 0.0
    tags: list[str] = []
    note = ""

    if rushing and scheme in {"dual_back", "committee"}:
        if is_lead:
            raw = -6.0 if over else 4.0
            tags.append("COMMITTEE_LEAD_RUSH_CAP")
            note = f"{player_usage.role} in a {scheme.replace('_', '-')} backfield — carries capped."
        elif is_second:
            raw = 5.0 if over else -4.0
            tags.append("COMMITTEE_RB2_RUSH_SUPPORT")
            note = f"{player_usage.role} carries a real share of a {scheme.replace('_', '-')} backfield."
    elif rushing and scheme == "bell_cow":
        if is_lead:
            raw = 3.0 if over else -3.0
            tags.append("BELLCOW_LEAD_RUSH_SUPPORT")
            note = f"{player_usage.role} is the bell-cow — workload secure."
        elif player_usage.rank >= 1:
            raw = -4.0 if over else 3.0
            tags.append("BELLCOW_BACKUP_RUSH_FADE")
            note = f"{player_usage.role} sits behind a bell-cow — little volume."

    if receiving and scheme == "wr_two_headed":
        if is_lead:
            raw = -3.0 if over else 2.0
            tags.append("TWO_HEADED_WR1_CAP")
            note = f"{player_usage.role} shares targets in a two-headed room — ceiling capped."
        elif is_second:
            raw = 4.0 if over else -3.0
            tags.append("TWO_HEADED_WR2_SUPPORT")
            note = f"{player_usage.role} is a co-#1 in a two-headed room."
    elif receiving and scheme == "wr_alpha":
        if is_lead:
            raw = 4.0 if over else -3.0
            tags.append("ALPHA_WR1_SUPPORT")
            note = f"{player_usage.role} is the alpha target — funnel receiver."
        elif player_usage.rank >= 1:
            raw = -3.0 if over else 2.0
            tags.append("ALPHA_SECONDARY_WR_FADE")
            note = f"{player_usage.role} plays behind an alpha WR1 — targets scarce."
    elif receiving and scheme == "wr_spread":
        if is_lead and over:
            raw = -2.0
            tags.append("SPREAD_WR_DILUTION")
            note = "Targets spread around — top receiver's ceiling diluted."

    # amplify by in-season development for the emerging second option
    if raw != 0.0 and is_second and player_usage.trend >= TREND_HOT:
        boost = 2.0 if over else -1.0
        raw += boost if raw > 0 else 0.0  # only strengthen a supportive read
        tags.append("SECOND_OPTION_DEVELOPING")
        note = (note + f" Trending up +{round(player_usage.trend * 100)}% recently.").strip()

    return {"score_delta": round(_clamp(raw, -SIGNAL_CLAMP, SIGNAL_CLAMP), 1), "tags": tags, "note": note}
