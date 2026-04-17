#!/usr/bin/env python3
"""Sheldon Corp terminal console.

Single-screen UI for checking on Sheldon's always-on Telegram system.
Shows daemon status, bot connection, recent log tail, and lets you attach,
restart, run triage, or open the vault log. Uses `rich` for the UI.
"""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

try:
    from rich.align import Align
    from rich.console import Console, Group
    from rich.live import Live
    from rich.panel import Panel
    from rich.prompt import Prompt
    from rich.table import Table
    from rich.text import Text
    from rich import box
except ImportError:
    print("installing rich...")
    subprocess.run([sys.executable, "-m", "pip", "install", "rich",
                    "--break-system-packages", "-q"], check=False)
    from rich.align import Align
    from rich.console import Console, Group
    from rich.live import Live
    from rich.panel import Panel
    from rich.prompt import Prompt
    from rich.table import Table
    from rich.text import Text
    from rich import box

console = Console()
HOME = Path.home()
REPO = Path(__file__).resolve().parent.parent
LOG_DIR = HOME / "Library" / "Logs" / "sheldon-telegram"
CLAUDE_LOG = LOG_DIR / "claude.log"
DAEMON_OUT = LOG_DIR / "daemon.out.log"
DAEMON_ERR = LOG_DIR / "daemon.err.log"
TMUX_SESSION = "sheldon-tg"
LAUNCH_LABEL = "com.nagel.sheldon-telegram"
VAULT_LOG = HOME / "Documents" / "Obsidian Vault" / "_AI Memory" / "Telegram Log.md"
ACCESS_JSON = HOME / ".claude" / "channels" / "telegram" / "access.json"

LOGO = r"""
   ██████  ██   ██ ███████ ██      ██████   ██████  ███    ██
  ██       ██   ██ ██      ██      ██   ██ ██    ██ ████   ██
   █████   ███████ █████   ██      ██   ██ ██    ██ ██ ██  ██
       ██  ██   ██ ██      ██      ██   ██ ██    ██ ██  ██ ██
  ██████   ██   ██ ███████ ███████ ██████   ██████  ██   ████
"""


# ── helpers ──────────────────────────────────────────────────────────────────

def sh(*args: str, timeout: int = 5) -> tuple[int, str]:
    try:
        r = subprocess.run(args, capture_output=True, text=True, timeout=timeout)
        return r.returncode, (r.stdout + r.stderr).strip()
    except Exception as e:
        return 1, str(e)


def tmux_alive() -> bool:
    rc, _ = sh("tmux", "has-session", "-t", TMUX_SESSION)
    return rc == 0


def launchd_loaded() -> bool:
    rc, out = sh("launchctl", "list", LAUNCH_LABEL)
    return rc == 0


def launchd_pid() -> str:
    rc, out = sh("launchctl", "list", LAUNCH_LABEL)
    if rc != 0:
        return "-"
    for line in out.splitlines():
        line = line.strip()
        if line.startswith('"PID"'):
            return line.split("=")[-1].rstrip(";").strip()
    return "-"


def claude_running_in_tmux() -> bool:
    rc, out = sh("pgrep", "-lf", "claude --dangerously-skip-permissions")
    return rc == 0 and out.strip() != ""


def poller_running() -> bool:
    rc, out = sh("pgrep", "-lf", "bun.*telegram.*server.ts")
    return rc == 0 and out.strip() != ""


def bot_username() -> str:
    token = None
    env_file = HOME / ".claude" / "channels" / "telegram" / ".env"
    if env_file.exists():
        for line in env_file.read_text().splitlines():
            if line.startswith("TELEGRAM_BOT_TOKEN="):
                token = line.split("=", 1)[1].strip()
                break
    if not token:
        return "-"
    import urllib.request, json
    try:
        req = urllib.request.Request(
            f"https://api.telegram.org/bot{token}/getMe",
            headers={"User-Agent": "sheldon-console"},
        )
        with urllib.request.urlopen(req, timeout=3) as r:
            data = json.load(r)
        if data.get("ok"):
            return "@" + data["result"]["username"]
    except Exception:
        pass
    return "unreachable"


def allowlist_count() -> int:
    try:
        import json
        data = json.loads(ACCESS_JSON.read_text())
        return len(data.get("allowFrom", [])) + len(data.get("groups", {}))
    except Exception:
        return 0


def tail(path: Path, n: int = 12) -> list[str]:
    if not path.exists():
        return [f"(no log yet at {path})"]
    try:
        with path.open("rb") as f:
            f.seek(0, 2)
            size = f.tell()
            block = min(size, 8192)
            f.seek(-block, 2)
            data = f.read().decode(errors="replace")
        return data.splitlines()[-n:]
    except Exception as e:
        return [f"(log read error: {e})"]


def human_duration(seconds: float) -> str:
    s = int(seconds)
    if s < 60:
        return f"{s}s"
    if s < 3600:
        return f"{s // 60}m {s % 60}s"
    if s < 86400:
        return f"{s // 3600}h {(s % 3600) // 60}m"
    return f"{s // 86400}d {(s % 86400) // 3600}h"


def daemon_uptime() -> str:
    pid = launchd_pid()
    if pid in ("-", "0"):
        return "-"
    rc, out = sh("ps", "-p", pid, "-o", "etime=")
    if rc != 0:
        return "-"
    return out.strip()


# ── UI ───────────────────────────────────────────────────────────────────────

def status_panel() -> Panel:
    daemon_up = launchd_loaded()
    tmux_up = tmux_alive()
    claude_up = claude_running_in_tmux()
    poll_up = poller_running()

    def badge(ok: bool, yes="ONLINE", no="OFFLINE") -> Text:
        return Text(yes, style="bold green") if ok else Text(no, style="bold red")

    table = Table.grid(padding=(0, 2), expand=True)
    table.add_column(style="dim", width=22, no_wrap=True)
    table.add_column()

    table.add_row("LaunchAgent", badge(daemon_up))
    table.add_row("tmux session", badge(tmux_up, yes=f"attached ({TMUX_SESSION})", no="not running"))
    table.add_row("claude process", badge(claude_up))
    table.add_row("Telegram poller", badge(poll_up))
    table.add_row("Bot", Text(bot_username(), style="cyan"))
    table.add_row("Allowlist", Text(f"{allowlist_count()} entries", style="dim"))
    table.add_row("Daemon uptime", Text(daemon_uptime(), style="dim"))
    table.add_row("Time", Text(datetime.now().strftime("%Y-%m-%d %H:%M:%S"), style="dim"))
    return Panel(table, title="[bold cyan]STATUS[/bold cyan]", box=box.ROUNDED, border_style="cyan")


def log_panel(title: str, path: Path, n: int = 10) -> Panel:
    lines = tail(path, n=n)
    txt = Text("\n".join(lines) if lines else "(empty)", style="dim")
    return Panel(txt, title=f"[bold]{title}[/bold] [dim]{path.name}[/dim]",
                 box=box.ROUNDED, border_style="grey50")


def menu_panel() -> Panel:
    g = Table.grid(padding=(0, 3))
    g.add_column(style="bold yellow", no_wrap=True)
    g.add_column(style="white")
    g.add_row("[a]", "Attach to tmux (Ctrl-b d to detach)")
    g.add_row("[r]", "Restart daemon")
    g.add_row("[s]", "Start daemon")
    g.add_row("[x]", "Stop daemon")
    g.add_row("[l]", "Live-tail claude log")
    g.add_row("[v]", "Open Telegram vault log")
    g.add_row("[t]", "Run /triage in a new tmux window")
    g.add_row("[b]", "Send test DM to verify bot")
    g.add_row("[q]", "Quit")
    return Panel(g, title="[bold]COMMANDS[/bold]", box=box.ROUNDED, border_style="cyan")


def render_dashboard() -> Group:
    header = Panel(
        Align.center(Text(LOGO, style="bold cyan"), vertical="middle"),
        box=box.DOUBLE_EDGE, border_style="cyan",
        subtitle="[dim]always-on Telegram assistant[/dim]",
    )
    return Group(header, status_panel(), log_panel("claude.log", CLAUDE_LOG, n=10), menu_panel())


# ── actions ──────────────────────────────────────────────────────────────────

def action_attach():
    console.print("[dim]launching tmux. detach with Ctrl-b then d...[/dim]")
    time.sleep(0.6)
    os.execvp("tmux", ["tmux", "attach", "-t", TMUX_SESSION])


def action_restart():
    console.print("[yellow]restarting daemon...[/yellow]")
    sh("launchctl", "kickstart", "-k", f"gui/{os.getuid()}/{LAUNCH_LABEL}")
    time.sleep(1.5)


def action_start():
    console.print("[yellow]starting daemon...[/yellow]")
    sh("launchctl", "kickstart", f"gui/{os.getuid()}/{LAUNCH_LABEL}")
    time.sleep(1.5)


def action_stop():
    console.print("[yellow]stopping daemon...[/yellow]")
    sh("launchctl", "kill", "TERM", f"gui/{os.getuid()}/{LAUNCH_LABEL}")
    sh("tmux", "kill-session", "-t", TMUX_SESSION)
    time.sleep(0.8)


def action_live_tail():
    if not CLAUDE_LOG.exists():
        console.print(f"[red]no log at {CLAUDE_LOG}[/red]")
        Prompt.ask("\npress enter to return")
        return
    console.print(f"[dim]tailing {CLAUDE_LOG}. ctrl-c to return.[/dim]\n")
    try:
        subprocess.run(["tail", "-n", "40", "-f", str(CLAUDE_LOG)])
    except KeyboardInterrupt:
        pass


def action_open_vault():
    VAULT_LOG.parent.mkdir(parents=True, exist_ok=True)
    if not VAULT_LOG.exists():
        VAULT_LOG.write_text("---\ntype: log\ntitle: Telegram Log\nupdated_by: Sheldon\n---\n\n")
    subprocess.run(["open", str(VAULT_LOG)])
    console.print(f"[dim]opened {VAULT_LOG}[/dim]")
    time.sleep(0.5)


def action_triage():
    if not tmux_alive():
        console.print("[red]daemon not running. start it first (s).[/red]")
        Prompt.ask("\npress enter to return")
        return
    subprocess.run(["tmux", "send-keys", "-t", TMUX_SESSION, "/triage", "Enter"])
    console.print("[green]sent /triage to the tmux session. attach (a) to watch.[/green]")
    time.sleep(1)


def action_test_dm():
    """Send a getMe + getWebhookInfo summary so Derek knows the bot is reachable."""
    import json
    import urllib.request
    token = None
    env_file = HOME / ".claude" / "channels" / "telegram" / ".env"
    if env_file.exists():
        for line in env_file.read_text().splitlines():
            if line.startswith("TELEGRAM_BOT_TOKEN="):
                token = line.split("=", 1)[1].strip()
    if not token:
        console.print("[red]no TELEGRAM_BOT_TOKEN in ~/.claude/channels/telegram/.env[/red]")
        Prompt.ask("\npress enter to return")
        return

    try:
        for name in ("getMe", "getWebhookInfo"):
            with urllib.request.urlopen(f"https://api.telegram.org/bot{token}/{name}", timeout=4) as r:
                data = json.load(r)
            console.print(Panel(json.dumps(data, indent=2), title=name, border_style="cyan"))
    except Exception as e:
        console.print(f"[red]error: {e}[/red]")

    console.print("\n[dim]now send the bot a DM on Telegram -- watch the log panel for the inbound.[/dim]")
    Prompt.ask("press enter to return")


# ── main loop ────────────────────────────────────────────────────────────────

def main():
    # Startup splash with live refresh for ~1.2s.
    with Live(render_dashboard(), console=console, refresh_per_second=6, screen=True) as live:
        start = time.time()
        while time.time() - start < 1.2:
            time.sleep(0.15)
            live.update(render_dashboard())

    while True:
        console.clear()
        console.print(render_dashboard())
        console.print()
        choice = Prompt.ask("[bold cyan]sheldon>[/bold cyan]", default="q").strip().lower()

        if choice in ("q", "quit", "exit"):
            console.print("[dim]sheldon corp signing off.[/dim]")
            return
        elif choice == "a":
            action_attach()
        elif choice == "r":
            action_restart()
        elif choice == "s":
            action_start()
        elif choice == "x":
            action_stop()
        elif choice == "l":
            action_live_tail()
        elif choice == "v":
            action_open_vault()
        elif choice == "t":
            action_triage()
        elif choice == "b":
            action_test_dm()
        else:
            console.print(f"[red]unknown command: {choice}[/red]")
            time.sleep(0.8)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        console.print("\n[dim]interrupted.[/dim]")
