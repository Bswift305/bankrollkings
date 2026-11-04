# Integrity + D4 production receipt — `4afcab9` (2026-11-04)

**Status: DEPLOYED and healthy. Acceptance found a release-introduced, production-only quote-time defect.
Per the owner's decision, it is being fixed forward by a narrow hotfix (separate receipt:
`docs/props_source_time_hotfix_receipt_20261104.md`). `4afcab9` was not reverted.**

## Deploy

- **Owner approval:** exact `4afcab9178f189341140223eecb7f5f96ce67f6e`, recorded with the editor-wording known gap
  (below).
- **Pre-push recheck at 13:36:47Z** (read-only SSM `deaf3eb5-4b7f-4561-bf17-e1a3ef14cfaa`, script sha256
  `3842eb37…7825cb557`):
  - production HEAD `6bdb73f`; `tracked_dirty=0` (only `?? venv/`);
  - no active or activating `bk-*` service (`bk-daily` had ended at 13:29:04Z);
  - capture names 0 in `.env`, the unit and MainPID 1626528 plus workers 1626532 and 1626535;
  - service active, 0 restarts, local health 200.
- **Push at 13:37:12Z:** `git ls-remote` master was `6bdb73f`; fast-forward `6bdb73f..4afcab9`, no force.
  `origin/master` is now `4afcab9`.

## Post-deploy (read-only SSM, 13:38:03Z, script sha256 `538e97d5…6de77834`)

| Check | Result |
|---|---|
| `bk-deploy` | pulled and restarted; prewarm ok (disk artifacts written; `[PREWARM] … nfl_floor_board`, `nfl_matchup_center`, …) |
| Production HEAD | exact `4afcab9…`; `tracked_dirty=0` |
| Service | active/running; `ActiveEnterTimestamp` 13:37:36Z; `NRestarts=0`; new MainPID 1626783 with workers 1626788 and 1626789 booted |
| Journal since 13:36 | 0 Traceback/error lines |
| earlyoom | 0 kills; memory 7816 MB total / 6558 MB available |
| Health | local `/healthz` 200 |
| Capture | OFF — 0 names in `.env`, the unit, MainPID and both workers |
| Cache | new `nfl_floor_board_q1k2_24_78_8.pkl` and `nfl_matchup_center_src2.pkl` (13:37) written after the restart; old `nfl_floor_board_24_78_8.pkl`, `_90_52_8.pkl` and `nfl_matchup_center.pkl` left in place, not read; no purge |

**Standing `bk-daily` result (not this deployment):** `bk-daily.service` ended 13:29:04Z with
`Result=exit-code`, `ExecMainStatus=1`, eight minutes **before** the push. This is the standing daily failure
recorded since 2026-10-27 and is not attributable to `4afcab9`.

## Acceptance finding — production-only quote-time defect (release-introduced)

- **Surface:** signed-in Today's Cards (13:39Z). There were no executable legs; every NFL prop read "Quote not
  current — quote from future", labelled "updated 2026-11-04 13:00 ET".
- **Evidence** (read-only SSM `0f07a4ed-dbd9-40dc-b0c4-8b37c404be46`, script sha256 `4cf6596f…8dfbcd55`):
  - prod `TZ=Etc/UTC`; `NFL_Props.csv` mtime 13:00:39Z, 1,619 rows;
  - `LastUpdated` = `"2026-11-04 13:00"` on 1,619/1,619 rows;
  - `SourceUpdatedAtUTC` filled 1,619/1,619, range `2026-11-04T12:58:47Z`–`13:00:38Z`.
- **Cause:**
  - `fetch_player_props` writes `LastUpdated` as the bookmaker `last_update`, but falls back to the fetch time
    (`datetime.now().astimezone()`), zone-less, in the process zone. The bookmaker field is absent from event
    odds, so it always falls back.
  - The executable-quote contract added in this release (`f642091`) read that stamp through
    `_feed_stamp_to_utc`, which treats zone-less values as Eastern. On the UTC box, 13:00Z therefore became
    18:00Z.
  - A US-zone dev box never reproduces this.
- **Effect if left:**
  - until ~17:45Z, every prop is blocked (fail-closed, but the label is false);
  - ~17:45Z–24:00Z, the quotes pass as executable;
  - **from 19:00Z they are past the real 6h rule** while carrying payouts and a false update time.
- **Proof that it reproduces:** the new `qc_props_quote_source_time.py` fails 48/58 on `4afcab9` with exactly
  `updated_utc=2026-11-04T18:00:00Z`, `QUOTE_FROM_FUTURE` and "updated 2026-11-04 13:00 ET".
- **Owner decision:** ship the narrow `SourceUpdatedAtUTC` correction; do not revert `4afcab9`. The owner
  conditionally authorized the gated successor to deploy without a further approval.

## Known non-blocking UX gap (owner-classified; not an acceptance failure)

- The shared ticket editor's UI cap is **5** legs (`TICKET_EDITOR_MAX_LEGS`).
- The server's executable-ticket contract is **2–8** (`TICKET_SUBMIT_MIN_LEGS`/`TICKET_SUBMIT_MAX_LEGS`).
- The existing tooltip and screen-reader text, "A ticket holds at most 5 legs", wrongly implies that five is the
  global ticket maximum.
- No leg is silently trimmed; the editor only refuses to add a sixth. Integrity and server enforcement are
  unaffected.
- **Future correction**, to be bundled with the next ticket-editor/UI release rather than shipped standalone:
  - visible text `This editor builds up to 5 legs`;
  - the same wording in the tooltip and screen-reader copy;
  - the server contract stays `2–8 legs`.

## Resolution and acceptance

- **Hotfix:** `17b5e69` was gated (offline 46/46 and the exact-SHA Linux gate 46/46, `qc_odds_feed` rc 3) and
  deployed at 14:09:56Z.
- **Acceptance:** the full signed-in matrix and the owner's explicit probes ran on `17b5e69`, which carries every
  `4afcab9` behaviour, and passed. See `docs/props_source_time_hotfix_receipt_20261104.md`.
- **Integrity + D4 status:** **PRODUCTION ACCEPTED** (as `4afcab9` + hotfix `17b5e69`).
