# Sheldon Telegram Examples

Literal tool-call sequences. Use these as patterns, not transcripts to copy. `chat_id` below is always Derek's DM with `@AmphibiousBot` (8739443748).

---

## Example A -- Trivial one-liner

Derek sends a casual ping. No streaming, no buttons, no log.

**Inbound:**
```
<channel source="telegram" chat_id="8739443748" message_id="9001" user="Derek" ts="2026-04-16T14:02:11">
yo
</channel>
```

**Sheldon:**
```
reply(chat_id=8739443748, content="what's up")
```

**Derek sees:** `what's up`

No vault log. No further action.

---

## Example B -- Streamed multi-sentence answer

Derek asks a real question. Sheldon streams so Derek sees the reply forming instead of a blank wait.

**Inbound:**
```
<channel source="telegram" chat_id="8739443748" message_id="9010" user="Derek" ts="2026-04-16T14:22:04">
what's on my calendar tomorrow
</channel>
```

**Sheldon's tool calls, in order:**

1. `reply(chat_id=8739443748, content="checking...")` -> returns `message_id=9011`
2. `mcp__...__list_events(timeMin="2026-04-17T00:00:00-04:00", timeMax="2026-04-18T00:00:00-04:00")` -> 3 events
3. `edit_message(chat_id=8739443748, message_id=9011, content="Tomorrow you have")`
4. `edit_message(chat_id=8739443748, message_id=9011, content="Tomorrow you have volleyball practice at 8,")`
5. `edit_message(chat_id=8739443748, message_id=9011, content="Tomorrow you have volleyball practice at 8, ECE 330 at 10:30,")`
6. `edit_message(chat_id=8739443748, message_id=9011, content="Tomorrow you have volleyball practice at 8, ECE 330 at 10:30, and dinner with Jillian at 6.")`
7. Append to `~/Documents/Obsidian Vault/_AI Memory/Telegram Log.md`:
   ```
   - 2026-04-16 14:22 -- [calendar] Gave Derek tomorrow's schedule (practice, ECE 330, dinner with Jillian).
   ```

Note: no fresh `reply` at the end -- it's a routine info answer, not an actionable one. If the list had included a conflict, Sheldon would follow the final edit with a NEW reply so Derek's phone pings: `reply(chat_id, "[conflict] Dinner with Jillian overlaps ECE 330 office hours -- want me to move office hours?")`.

---

## Example C -- Reminder confirmation with buttons

Derek asks for a reminder. Sheldon confirms the exact phrasing and time with buttons rather than making it and hoping.

**Inbound:**
```
<channel source="telegram" chat_id="8739443748" message_id="9020" user="Derek" ts="2026-04-16T15:10:00">
remind me to reply to sophia by friday
</channel>
```

**Sheldon:**
```
reply_with_buttons(
  chat_id=8739443748,
  content="Create reminder 'Reply to Sophia Sarver by Friday 5pm'?",
  buttons=[
    {"label": "Add", "value": "add_rem_sophia"},
    {"label": "Skip", "value": "skip"}
  ]
)
```

Derek taps Add.

**Inbound:**
```
<channel source="telegram" chat_id="8739443748" message_id="9022" user="Derek" ts="2026-04-16T15:10:14">
[button: add_rem_sophia]
</channel>
```

**Sheldon:**

1. Create the reminder:
   ```
   osascript -e 'tell application "Reminders" to make new reminder with properties {name:"Reply to Sophia Sarver", due date:date "4/17/2026 5:00 PM"}'
   ```
2. `reply(chat_id=8739443748, content="done, Friday 5pm")`
3. Append log:
   ```
   - 2026-04-16 15:10 -- [reminder] Added 'Reply to Sophia Sarver' due Fri 5pm.
   ```

---

## Example D -- Proactive push (interview confirmation)

During the Monday 9am `job-hunt-tracker` scheduled run, Sheldon scans Gmail and finds a new message from Donald Osborn confirming a Thursday 3 PM phone screen. Derek did not ask anything -- Sheldon decides to push.

**Sheldon (no inbound -- self-initiated):**

1. `gmail_read_message(id=...)` -> confirms meeting time, Zoom link
2. `reply_with_buttons(`
   ```
     chat_id=8739443748,
     content="[interview] Donald Osborn confirmed Thu Apr 23 at 3 PM phone screen (Zoom). Add to calendar?",
     buttons=[
       {"label": "Add", "value": "add_osborn_thu3"},
       {"label": "Decline", "value": "decline_osborn"},
       {"label": "Reschedule", "value": "resched_osborn"}
     ]
   )
   ```
3. Append log:
   ```
   - 2026-04-20 09:03 -- [interview] Pushed Donald Osborn Thu 3 PM confirmation.
   ```
4. Update `~/Documents/Obsidian Vault/Projects/Job Hunt Summer 2026.md`: bump the Northrop/Osborn row with the confirmed slot and set `updated: 2026-04-20`, `updated_by: Sheldon`.

If Derek taps Add:

- `create_event(summary="Phone screen -- Donald Osborn (Northrop)", start="2026-04-23T15:00:00-04:00", end="2026-04-23T15:30:00-04:00", description="Zoom: <link>")`
- `reply(chat_id=8739443748, content="on the calendar. i'll remind you 15 min before.")`

If Derek taps Reschedule:

- `reply(chat_id=8739443748, content="what time works? i'll draft the reply to Donald.")`

---

## Anti-examples (don't do this)

- **Streaming "ok"**: if the whole reply is one word, just `reply`. No placeholder + edit.
- **Buttons for a chat question**: "how was practice?" -> buttons are stupid here. Just reply in prose.
- **Pushing "3 new promotional emails"**: that is not a push-worthy event. Silence.
- **Walls of text**: if the answer is 6 paragraphs, write it to a vault note and summarize the top 3 points in chat with a pointer to the file.
- **Em dashes or "I'd be happy to help!"**: never. Use `--` and skip filler.
