# Daily inbox triage

Scan all three Gmail accounts for the past 24 hours and extract action items.

## Accounts (nicknames via gmail-multi MCP)
- `personal` — dnage76@gmail.com (primary)
- `secondary` — dereknagel05@gmail.com
- `gmu` — dnagl@gmu.edu

## Procedure

For each account nickname, call:

```
gmail_search(account=<nick>, query="after:YESTERDAY -category:promotions -category:social -is:newsletter", max_results=50)
```

Replace `YESTERDAY` with the actual date (today minus 1, YYYY/MM/DD).
For any message whose subject/snippet is ambiguous, call
`gmail_read(account, message_id)` to see the body.

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
receipts, CC-only threads where Derek isn't directly addressed.

## Output format

Single sorted list across all three inboxes. Tag each line with the inbox
nickname.

### Urgent (respond today)
- [nickname] From: X — Subject — what's needed

### This week
- [nickname] From: X — Subject — what's needed

### FYI / low priority
- [nickname] From: X — Subject — no action needed but worth knowing

Skip any section that's empty. If nothing actionable across all three, exit
silently.
