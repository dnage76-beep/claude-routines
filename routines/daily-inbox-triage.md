# Daily inbox triage

Scan all three Derek accounts for the past 24 hours and surface action items.

## Accounts

**Gmail (via `gmail-multi` MCP):**
- `personal` — dnage76@gmail.com (primary)
- `secondary` — dereknagel05@gmail.com

**GMU Exchange (via `mail-exchange` MCP):**
- dnagel@gmu.edu — read from Apple Mail.app local cache

## Procedure

### Gmail accounts
For each Gmail nickname, call:
```
gmail_search(account=<nick>, query="after:YESTERDAY -category:promotions -category:social -is:newsletter", max_results=50)
```
Replace `YESTERDAY` with today's date minus 1 (YYYY/MM/DD).

### GMU Exchange
```
exchange_search(since_hours=24, max_results=50)
```
Optionally filter with `unread_only=True` if the inbox is noisy.

### Drilling in
For any message where subject/sender is ambiguous:
- Gmail: `gmail_read(account, message_id)`
- Exchange: `exchange_read(message_id)` (pass the integer ROWID from search results)

## What counts as an action item
- Emails requiring a reply
- Interview scheduling or follow-ups
- Deadlines or due dates
- Bills or payments due
- Requests from people Derek knows
- Application status changes
- Academic: deadlines, grades, professor emails

## What to skip
Marketing, newsletters, shipping notifications, social alerts, automated
receipts, CC-only threads where Derek isn't directly addressed. External-sender
Google/Microsoft security alerts unless they indicate an actual breach.

## Output format

Single sorted list across all three inboxes. Tag each line with the source.

### Urgent (respond today)
- [source] From: X — Subject — what's needed

### This week
- [source] From: X — Subject — what's needed

### FYI / low priority
- [source] From: X — Subject — no action needed but worth knowing

Source tags: `personal`, `secondary`, `gmu`. Skip any section that's empty.
If nothing actionable across all three, say so in one line and exit.
