# Alexa Flash Briefing — Current State Audit

Snapshot of Derek's existing Alexa Flash Briefing plumbing as of 2026-04-16.
This document is read-only — it captures what exists today so the Phase 3
migration to GitHub Actions can make a faithful swap without regressions.

## 30-second summary

- 5 GitHub gists hold Flash Briefing JSON. Alexa polls each via its public raw
  URL and reads the `mainText` aloud.
- A local scheduled task (`alexa-feed-updater`) fetches fresh data on Derek's
  Mac each morning, then runs `~/Documents/Claude/scripts/push_gists.py`, which
  PATCHes all 5 gists in one pass.
- The script itself is ALSO cached as a private gist (`4713c651...`), downloaded
  over HTTPS at run time. Both the PAT that downloads it and the PAT that
  pushes briefing content are the **same hardcoded token** inside the script.
- Content today = weather (wttr.in) + AP/ArsTechnica/ESPN RSS + a random fun
  fact + dining hall menus scraped from DineOnCampus + iMessage snippets from
  `~/Library/Messages/chat.db` + Apple Reminders from SQLite + calendar/email
  JSON dumped to `/tmp` by the scheduled task. No vault awareness.

## The 5 gists

Each gist contains one JSON file in Alexa Flash Briefing feed format:
```json
[{"uid":"...","updateDate":"...","titleText":"...","mainText":"...","redirectionUrl":"https://www.amazon.com"}]
```

| Nickname          | Gist ID                              | Filename                | Notes                                    |
|-------------------|--------------------------------------|-------------------------|------------------------------------------|
| `morning_brief`   | `f31ac4df35577f97c764c0cfa2ad1f32`   | `morning-brief.json`    | Long narrative — everything combined     |
| `message_summary` | `cf29d59382563aa7bec0bb8c3fbdd3b2`   | `message-summary.json`  | Recent iMessages grouped by conversation |
| `email_summary`   | `3fcf22dd978927b34c79e289433d6e78`   | `email-summary.json`    | Top relevant emails (non-promo)          |
| `upcoming_events` | `60af9d0ddec44f05abcb3de4ceeb075c`   | `upcoming-events.json`  | Weather + calendar + reminders + dining  |
| `news_and_weather`| `eb2e18e7cb7041a0384489cdd1540e14`   | `news-and-weather.json` | Weather + dining + news headlines        |

The "script cache" gist (separate from the 5 feeds above):
- `4713c651faca5d35304eb329dc744c7d` — holds `push_gists.py` so scheduled tasks
  on other machines can `curl` it instead of relying on the local filesystem.

## Tokens and secrets discovered in the wild

- **GitHub PAT** (classic, `ghp_...`): hardcoded in two places.
  - `~/Documents/Claude/scripts/push_gists.py` line 35
  - `~/Documents/Claude/Scheduled/alexa-feed-updater/SKILL.md` (in the curl line)
  This token has `gist` scope (read + write). Phase 3 will rotate it and move it
  to GitHub Secrets. Mark this token for revocation after cutover.
- **No Google OAuth tokens** on the cloud side yet. The local flow sidesteps
  Google auth entirely because a different scheduled task (`morning-brief`)
  already dumped cached JSON to `/tmp` before `push_gists.py` ran. Cloud
  migration has to do its own Google OAuth with a refresh token kept as a
  GitHub Secret.

## Data sources today

| Source            | Mechanism                                    | Cloud-reachable?     |
|-------------------|----------------------------------------------|----------------------|
| Google Calendar   | `/tmp/gcal_events.json` dumped by upstream   | Yes, via refresh token |
| Gmail             | `/tmp/gmail_recent.json` dumped by upstream  | Yes, via refresh token |
| iMessages         | Local SQLite `~/Library/Messages/chat.db`    | **No** — Mac-only     |
| Apple Reminders   | Local SQLite in `group.com.apple.reminders`  | **No** — Mac-only     |
| Weather           | `wttr.in` public API                         | Yes                  |
| News              | AP / ArsTechnica / ESPN RSS                  | Yes                  |
| Fun fact          | `uselessfacts.jsph.pl` public API            | Yes                  |
| Dining            | DineOnCampus GraphQL (Cloudflare, needs `curl_cffi` impersonation) | Yes but flaky |
| Obsidian vault    | Filesystem — `~/Documents/Obsidian Vault`    | **No** unless synced |

## Life-context engine (worth preserving)

`push_gists.py` carries a surprisingly good relevance scorer that Phase 3 must
keep:
- `LIFE_CONTEXT.inner_circle` — `["Jillian","Mom","Sarah","Diana","Oma","Kyle","Matias"]`
- `LIFE_CONTEXT.important_people` — Jordan, Brady Quinnan, Donald Osborn, etc.
- `LIFE_CONTEXT.email_boost_keywords` — Tesla, GMU, Canvas, HIST-378, lease, etc.
- `LIFE_CONTEXT.news_boost_keywords` — Tesla, AI, GMU, NASA, NoVA, etc.
- `CAL_CONTEXT` — rewrites cryptic event titles into Sheldon-voice narration
  (e.g. "Kyle" -> "rehab session with your athletic trainer").
- `PROMO_KEYWORDS` + Gmail `CATEGORY_PROMOTIONS` label check for filtering noise.

Phase 3 carries these forward into `briefing/voice.py` and
`briefing/sources/email.py` rather than re-inventing them.

## Alexa skill side (what Derek already configured in Amazon Developer Console)

- Skill type: **Flash Briefing Skill** (not Custom Skill).
- 5 feeds, one per gist, each pointing at
  `https://gist.githubusercontent.com/<user>/<gist_id>/raw/<filename>` plus a
  feed name like "Morning Brief", "Messages", "Emails", "Events", "News".
- Content type: **Text**. Update frequency: hourly.
- Invocation: "Alexa, what's my Flash Briefing?" OR "Alexa, play news."
- No Lambda, no account linking, no two-way voice. Purely read-only.
- Skill ID format is `amzn1.ask.skill.<uuid>` — Derek has it in his Alexa
  developer dashboard. Not needed for Phase 3 cloud push (gists are the
  interface), but noted here for Part 4 (two-way eval).

## Known failure modes

1. **`/tmp` cache missing in cloud.** The biggest single blocker — entire
   reason Phase 3 exists.
2. **Hardcoded PAT leaks.** If the script gist goes public, the token is
   exfiltrated in cleartext. Rotate + move to Secrets.
3. **iMessage section dies in cloud.** Can't be helped — iMessage is a local
   macOS concept. Phase 3 drops iMessage from the Alexa briefing and keeps it
   only in local-mode. A nightly push from the Mac can still refresh a
   "messages" gist if Derek wants.
4. **Reminders section dies in cloud** — same reason. Dropped cleanly.
5. **Obsidian vault dies in cloud** — GitHub Actions runners can't see
   `~/Documents/Obsidian Vault`. Phase 3 solves this via a nightly local task
   that snapshots vault priorities to a *private gist*, which the cloud job
   reads. See Part 3 / `sources/vault.py` / `README.md`.
6. **Dining scraper is flaky** — DineOnCampus sits behind Cloudflare;
   `curl_cffi` works most days but isn't guaranteed. Treated as best-effort.

## What changes in Phase 3

- Push moves from Mac launchd to GitHub Actions cron, 3×/day (7am, 1pm, 6pm ET).
- Calendar + Gmail fetched live inside the runner using refresh-token OAuth.
- iMessage/Reminders removed from cloud path (kept in local backup).
- New `vault` source reads a private-gist snapshot for deadlines/priorities.
- New `deadlines` source merges Gmail dates + vault frontmatter into the
  "Top 3 time-sensitive" bucket.
- New `athletics` source surfaces next volleyball practice/match.
- Voice layer (`voice.py`) is split out and made swap-able (morning vs evening
  tone; terser Sheldon vs longer narrative).
- Old local `push_gists.py` stays in place untouched as a manual fallback.
