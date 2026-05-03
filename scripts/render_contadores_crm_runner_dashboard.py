#!/usr/bin/env python3
"""Render a local HTML dashboard for the macOS CRM follow-up LaunchAgent."""

from __future__ import annotations

import argparse
import html
import os
import subprocess
from datetime import datetime, timezone
from pathlib import Path


ROOT_DEFAULT = "/Users/fgoiriz/private/repos/contadores"
LABEL = "com.konecta.contadores.crm-followup"


def read_text(path: Path) -> str:
    """Read a text file for the local dashboard."""
    try:
        return path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""


def read_tail(path: Path | None, max_lines: int) -> str:
    """Read the last N lines of a text file."""
    if path is None:
        return ""
    text = read_text(path)
    if not text:
        return ""
    return "\n".join(text.splitlines()[-max_lines:])


def file_mtime(path: Path) -> str:
    """Return a readable file modified timestamp."""
    try:
        modified_at = datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc)
    except OSError:
        return "-"
    return modified_at.astimezone().strftime("%Y-%m-%d %H:%M:%S %Z")


def file_size(path: Path) -> str:
    """Return a compact file size."""
    try:
        size = path.stat().st_size
    except OSError:
        return "0 B"
    if size < 1024:
        return f"{size} B"
    if size < 1024 * 1024:
        return f"{size / 1024:.1f} KB"
    return f"{size / (1024 * 1024):.1f} MB"


def latest_logs(reports_dir: Path, limit: int) -> list[Path]:
    """Return recent runner log files."""
    if not reports_dir.exists():
        return []
    return sorted(
        reports_dir.glob("contadores-crm-followup-*.log"),
        key=lambda path: path.stat().st_mtime if path.exists() else 0,
        reverse=True,
    )[:limit]


def run_launchctl() -> str:
    """Read LaunchAgent state from launchctl."""
    try:
        result = subprocess.run(
            ["launchctl", "print", f"gui/{os.getuid()}/{LABEL}"],
            check=False,
            capture_output=True,
            text=True,
            timeout=8,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        return f"launchctl unavailable: {type(exc).__name__}"
    output = (result.stdout or result.stderr or "").strip()
    return output or f"launchctl exited {result.returncode}"


def parse_launchctl_summary(output: str) -> dict[str, str]:
    """Extract the few fields operators care about."""
    wanted = {
        "state": "-",
        "program": "-",
        "runs": "-",
        "last exit code": "-",
        "run interval": "-",
    }
    for raw_line in output.splitlines():
        line = raw_line.strip()
        for key in list(wanted):
            if line.startswith(f"{key} ="):
                wanted[key] = line.split("=", 1)[1].strip()
    return wanted


def process_is_running(pid: int | None) -> bool:
    """Return True when the pid is visible as alive."""
    if pid is None:
        return False
    try:
        os.kill(pid, 0)
    except PermissionError:
        return True
    except OSError:
        return False
    return True


def parse_pid(path: Path) -> int | None:
    """Parse one pid file."""
    raw_value = read_text(path).strip()
    if not raw_value:
        return None
    try:
        value = int(raw_value)
    except ValueError:
        return None
    return value if value > 0 else None


def infer_status(status: str, lock_dir: Path) -> str:
    """Infer local runner status from explicit input and the lock."""
    if status != "auto":
        return status
    if not lock_dir.exists():
        return "idle"
    pid = parse_pid(lock_dir / "pid")
    return "running" if process_is_running(pid) else "stale lock"


def esc(value: object) -> str:
    """HTML-escape one value."""
    return html.escape(str(value or ""), quote=True)


def pre_block(title: str, text: str) -> str:
    """Render a titled pre block."""
    return f"""
      <section class="panel">
        <div class="panel-head"><span>Log</span><strong>{esc(title)}</strong></div>
        <pre>{esc(text or "No lines yet.")}</pre>
      </section>
    """


def render_dashboard(root: Path, status: str, active_log: Path | None, output: Path, tail_lines: int) -> None:
    """Render the HTML dashboard."""
    reports_dir = root / "data" / "reports"
    lock_dir = root / "data" / "locks" / "contadores-crm-hourly-followup.lock"
    reports_dir.mkdir(parents=True, exist_ok=True)

    launchctl_output = run_launchctl()
    launchctl_summary = parse_launchctl_summary(launchctl_output)
    recent_logs = latest_logs(reports_dir, 10)
    latest_log = active_log if active_log and active_log.exists() else (recent_logs[0] if recent_logs else None)
    local_status = infer_status(status, lock_dir)
    latest_summary_path = reports_dir / "contadores-crm-followup-latest.md"

    log_rows = "\n".join(
        f"""
        <tr>
          <td>{esc(log_path.name)}</td>
          <td>{esc(file_mtime(log_path))}</td>
          <td>{esc(file_size(log_path))}</td>
          <td><code>{esc(log_path)}</code></td>
        </tr>
        """
        for log_path in recent_logs
    ) or '<tr><td colspan="4">No timestamped runner logs yet.</td></tr>'

    generated_at = datetime.now().astimezone().strftime("%Y-%m-%d %H:%M:%S %Z")
    pid = parse_pid(lock_dir / "pid") if lock_dir.exists() else None
    started_at = read_text(lock_dir / "started_at").strip() or "-"

    html_text = f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <meta http-equiv="refresh" content="60">
  <title>Contadores CRM Runner</title>
  <style>
    :root {{
      color-scheme: light;
      --bg: #f7f8f5;
      --surface: #ffffff;
      --surface-2: #f8faf7;
      --line: #dce2dd;
      --ink: #202124;
      --muted: #68756c;
      --accent: #0f766e;
      --warn: #a7642b;
      --danger: #a33b3b;
    }}
    * {{ box-sizing: border-box; }}
    body {{
      margin: 0;
      background: var(--bg);
      color: var(--ink);
      font: 14px/1.45 -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
    }}
    main {{ max-width: 1440px; margin: 0 auto; padding: 24px; }}
    header {{ display: flex; align-items: flex-start; justify-content: space-between; gap: 16px; margin-bottom: 16px; }}
    h1 {{ margin: 0; font-size: 24px; letter-spacing: 0; }}
    .sub {{ margin: 4px 0 0; color: var(--muted); font-family: ui-monospace, SFMono-Regular, Menlo, monospace; font-size: 12px; }}
    .badge {{
      display: inline-flex; align-items: center; min-height: 30px; padding: 0 12px;
      border-radius: 8px; background: var(--surface); border: 1px solid var(--line);
      color: var(--accent); font-weight: 800; font-family: ui-monospace, SFMono-Regular, Menlo, monospace;
    }}
    .badge[data-status="failed"], .badge[data-status="stale lock"] {{ color: var(--danger); }}
    .badge[data-status="idle"] {{ color: var(--muted); }}
    .grid {{ display: grid; grid-template-columns: repeat(5, minmax(0, 1fr)); gap: 12px; margin-bottom: 12px; }}
    .metric, .panel {{
      background: var(--surface); border: 1px solid var(--line); border-radius: 8px; padding: 14px;
    }}
    .metric span, .panel-head span {{
      display: block; color: var(--muted); font: 700 10px/1 ui-monospace, SFMono-Regular, Menlo, monospace;
      letter-spacing: .08em; text-transform: uppercase;
    }}
    .metric strong {{ display: block; margin-top: 7px; overflow-wrap: anywhere; font: 700 13px/1.35 ui-monospace, SFMono-Regular, Menlo, monospace; }}
    .workspace {{ display: grid; grid-template-columns: minmax(0, 1.4fr) minmax(360px, .8fr); gap: 12px; align-items: start; }}
    .panel-head {{ display: flex; align-items: center; justify-content: space-between; gap: 12px; margin-bottom: 10px; }}
    .panel-head strong {{ font-size: 15px; }}
    pre {{
      margin: 0; max-height: 560px; overflow: auto; white-space: pre-wrap; overflow-wrap: anywhere;
      background: var(--surface-2); border: 1px solid var(--line); border-radius: 8px; padding: 12px;
      font: 12px/1.5 ui-monospace, SFMono-Regular, Menlo, monospace;
    }}
    table {{ width: 100%; border-collapse: collapse; font: 12px/1.35 ui-monospace, SFMono-Regular, Menlo, monospace; }}
    th, td {{ padding: 9px 8px; border-top: 1px solid var(--line); text-align: left; vertical-align: top; }}
    th {{ color: var(--muted); text-transform: uppercase; font-size: 10px; letter-spacing: .08em; }}
    code {{ color: var(--muted); overflow-wrap: anywhere; }}
    .tails {{ display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 12px; margin-top: 12px; }}
    @media (max-width: 1000px) {{ .grid, .workspace, .tails {{ grid-template-columns: 1fr; }} }}
  </style>
</head>
<body>
  <main>
    <header>
      <div>
        <h1>Contadores CRM Runner</h1>
        <p class="sub">Local MacBook dashboard. Auto-refreshes every 60s. Generated {esc(generated_at)}.</p>
      </div>
      <span class="badge" data-status="{esc(local_status)}">{esc(local_status)}</span>
    </header>

    <section class="grid" aria-label="Runner facts">
      <div class="metric"><span>LaunchAgent</span><strong>{esc(LABEL)}</strong></div>
      <div class="metric"><span>launchctl state</span><strong>{esc(launchctl_summary["state"])}</strong></div>
      <div class="metric"><span>runs</span><strong>{esc(launchctl_summary["runs"])}</strong></div>
      <div class="metric"><span>last exit</span><strong>{esc(launchctl_summary["last exit code"])}</strong></div>
      <div class="metric"><span>interval</span><strong>{esc(launchctl_summary["run interval"])}</strong></div>
      <div class="metric"><span>pid</span><strong>{esc(pid or "-")}</strong></div>
      <div class="metric"><span>started_at</span><strong>{esc(started_at)}</strong></div>
      <div class="metric"><span>latest summary</span><strong>{esc(file_mtime(latest_summary_path))}</strong></div>
      <div class="metric"><span>latest log</span><strong>{esc(latest_log.name if latest_log else "-")}</strong></div>
      <div class="metric"><span>dashboard file</span><strong>{esc(output)}</strong></div>
    </section>

    <section class="workspace">
      <div class="panel">
        <div class="panel-head"><span>Latest result</span><strong>Final summary</strong></div>
        <pre>{esc(read_text(latest_summary_path) or "No final summary yet.")}</pre>
      </div>
      <div class="panel">
        <div class="panel-head"><span>Recent logs</span><strong>Files</strong></div>
        <table>
          <thead><tr><th>Name</th><th>Modified</th><th>Size</th><th>Path</th></tr></thead>
          <tbody>{log_rows}</tbody>
        </table>
      </div>
    </section>

    <section class="tails">
      {pre_block("Active/latest runner log", read_tail(latest_log, tail_lines))}
      {pre_block("LaunchAgent stdout", read_tail(reports_dir / "launchd-contadores-crm-followup.out.log", tail_lines))}
      {pre_block("LaunchAgent stderr", read_tail(reports_dir / "launchd-contadores-crm-followup.err.log", tail_lines))}
    </section>

    <section class="panel" style="margin-top:12px">
      <div class="panel-head"><span>launchctl</span><strong>Raw state</strong></div>
      <pre>{esc(launchctl_output)}</pre>
    </section>
  </main>
</body>
</html>
"""
    output.write_text(html_text, encoding="utf-8")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", default=ROOT_DEFAULT)
    parser.add_argument("--status", default="auto", choices=["auto", "idle", "running", "completed", "failed"])
    parser.add_argument("--active-log", default="")
    parser.add_argument("--tail-lines", type=int, default=180)
    parser.add_argument("--output", default="")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    root = Path(args.root)
    output = Path(args.output) if args.output else root / "data" / "reports" / "contadores-crm-followup-dashboard.html"
    active_log = Path(args.active_log) if args.active_log else None
    render_dashboard(root, args.status, active_log, output, max(1, args.tail_lines))
    print(output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
