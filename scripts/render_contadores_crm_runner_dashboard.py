#!/usr/bin/env python3
"""Render a local HTML dashboard for the macOS CRM follow-up LaunchAgent."""

from __future__ import annotations

import argparse
import html
import json
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


def read_json(path: Path) -> dict[str, object] | None:
    """Read a JSON object if it exists."""
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return value if isinstance(value, dict) else None


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


def relative_time(path: Path) -> str:
    """Return a short relative modified time for a file."""
    try:
        modified_at = datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc)
    except OSError:
        return "-"
    seconds = max(0, int((datetime.now(timezone.utc) - modified_at).total_seconds()))
    if seconds < 60:
        return f"{seconds}s ago"
    minutes = seconds // 60
    if minutes < 60:
        return f"{minutes}m ago"
    hours = minutes // 60
    if hours < 48:
        return f"{hours}h ago"
    days = hours // 24
    return f"{days}d ago"


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
    return html.escape("" if value is None else str(value), quote=True)


def metric_int(metrics: dict[object, object], key: str) -> int:
    """Read one integer metric without trusting the JSON shape."""
    try:
        return int(metrics.get(key, 0) or 0)
    except (TypeError, ValueError):
        return 0


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

    recent_logs = latest_logs(reports_dir, 10)
    latest_log = active_log if active_log and active_log.exists() else (recent_logs[0] if recent_logs else None)
    local_status = infer_status(status, lock_dir)
    latest_summary_path = reports_dir / "contadores-crm-followup-latest.md"
    history_path = reports_dir / "contadores-crm-followup-history.md"
    delta_path = reports_dir / "contadores-crm-followup-delta-latest.json"
    latest_summary = read_text(latest_summary_path) or "No final summary yet."
    history_markdown = read_text(history_path) or latest_summary
    delta = read_json(delta_path) or {}
    delta_metrics = delta.get("metrics") if isinstance(delta.get("metrics"), dict) else {}
    attention_events = delta.get("attention_events") if isinstance(delta.get("attention_events"), list) else []
    delta_markdown = str(delta.get("markdown") or "No structured delta has been written yet.")

    timeline_items = "\n".join(
        f"""
        <li class="timeline-item">
          <span class="timeline-dot"></span>
          <div class="timeline-meta">
            <strong>{esc(relative_time(log_path))}</strong>
            <span>{esc(file_mtime(log_path))}</span>
            <code>{esc(log_path.name)} / {esc(file_size(log_path))}</code>
          </div>
        </li>
        """
        for log_path in recent_logs
    ) or '<li class="timeline-item"><span class="timeline-dot is-muted"></span><div class="timeline-meta"><strong>No runs</strong><span>-</span></div></li>'

    generated_at = datetime.now().astimezone().strftime("%Y-%m-%d %H:%M:%S %Z")
    pid = parse_pid(lock_dir / "pid") if lock_dir.exists() else None
    started_at = read_text(lock_dir / "started_at").strip() or "-"
    prompt_context = {
        "root": str(root),
        "delta_markdown": delta_markdown,
        "latest_summary": latest_summary,
        "history_markdown": history_markdown,
    }
    context_json = json.dumps(prompt_context, ensure_ascii=False).replace("</", "<\\/")
    needs_action = metric_int(delta_metrics, "needs_action")
    new_replies = metric_int(delta_metrics, "new_replies")
    delivery_changes = metric_int(delta_metrics, "delivery_changes")
    new_outbound = metric_int(delta_metrics, "new_outbound")
    due_next_steps = metric_int(delta_metrics, "due_next_steps")
    status_tone = {
        "running": "live",
        "completed": "ok",
        "idle": "idle",
        "failed": "danger",
        "stale lock": "danger",
    }.get(local_status, "idle")
    status_icon = {
        "running": "RUN",
        "completed": "OK",
        "idle": "IDLE",
        "failed": "!",
        "stale lock": "LOCK",
    }.get(local_status, "AUTO")
    signal_rows = [
        ("!", "Action", needs_action, "danger" if needs_action else "ok"),
        ("@", "Replies", new_replies, "hot" if new_replies else "neutral"),
        ("+/-", "Delivery", delivery_changes, "warn" if delivery_changes else "neutral"),
        (">", "Outbound", new_outbound, "neutral"),
        ("...", "Due", due_next_steps, "hot" if due_next_steps else "neutral"),
    ]
    signals_html = "\n".join(
        f"""
        <article class="signal" data-tone="{esc(tone)}">
          <span class="signal-icon">{esc(icon)}</span>
          <span class="signal-label">{esc(label)}</span>
          <strong>{esc(value)}</strong>
        </article>
        """
        for icon, label, value, tone in signal_rows
    )
    attention_event_dicts = [event for event in attention_events[:8] if isinstance(event, dict)]
    attention_cards = "\n".join(
        f"""
        <article class="attention-card">
          <span>{esc(event.get("kind", "change"))}</span>
          <strong>{esc(event.get("full_name") or event.get("phone") or "Unknown lead")}</strong>
          <p>{esc(event.get("detail", ""))}</p>
          <em>{esc(event.get("suggested_action", ""))}</em>
        </article>
        """
        for event in attention_event_dicts
    )
    attention_html = (
        f"""
        <section class="attention-strip" aria-label="Attention">
          <div class="strip-head">
            <span class="panel-kicker">Attention</span>
            <strong>{len(attention_event_dicts)} card(s)</strong>
          </div>
          <div class="attention-grid">{attention_cards}</div>
        </section>
        """
        if attention_cards
        else ""
    )

    html_text = f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <meta http-equiv="refresh" content="60">
  <title>Contadores CRM Follow-Up</title>
  <script src="https://cdn.jsdelivr.net/npm/marked/marked.min.js"></script>
  <style>
    :root {{
      color-scheme: light;
      --bg: #f4f5f2;
      --surface: #ffffff;
      --surface-2: #f8f8f5;
      --line: #dde1da;
      --ink: #202321;
      --muted: #66706a;
      --soft: #909891;
      --accent: #147d71;
      --accent-soft: #def2ee;
      --danger: #b33a3a;
      --danger-soft: #ffe8e6;
      --warn: #9d6726;
      --warn-soft: #fff0d9;
      --hot: #315d9a;
      --hot-soft: #e5efff;
      --shadow: 0 14px 34px rgba(32, 35, 33, 0.07);
    }}
    * {{ box-sizing: border-box; }}
    body {{
      margin: 0;
      background: var(--bg);
      color: var(--ink);
      font: 14px/1.5 -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
    }}
    main {{ max-width: 1260px; margin: 0 auto; padding: 24px; }}
    header {{ display: flex; align-items: center; justify-content: space-between; gap: 18px; margin-bottom: 14px; }}
    h1 {{ margin: 0; font-size: 24px; line-height: 1.08; letter-spacing: 0; }}
    .topline {{ display: flex; flex-wrap: wrap; align-items: center; gap: 8px; margin-top: 8px; color: var(--muted); font-size: 12px; }}
    .status-stack {{ display: flex; flex-wrap: wrap; justify-content: flex-end; gap: 8px; }}
    .badge, .mini-chip {{
      display: inline-flex; align-items: center; gap: 7px; min-height: 32px; padding: 0 10px;
      border-radius: 8px; background: var(--surface); border: 1px solid var(--line);
      color: var(--muted); font: 800 11px/1 ui-monospace, SFMono-Regular, Menlo, monospace;
    }}
    .badge::before {{
      content: attr(data-icon);
      display: inline-grid; place-items: center; min-width: 22px; height: 22px; padding: 0 4px;
      border-radius: 6px; background: var(--surface-2); color: currentColor;
    }}
    .badge[data-tone="live"], .badge[data-tone="ok"] {{ color: var(--accent); }}
    .badge[data-tone="danger"] {{ color: var(--danger); }}
    .signals {{ display: grid; grid-template-columns: repeat(5, minmax(0, 1fr)); gap: 10px; margin-bottom: 12px; }}
    .signal {{
      position: relative; min-height: 112px; display: grid; grid-template-rows: auto 1fr auto;
      gap: 6px; padding: 14px; border: 1px solid var(--line); border-radius: 8px;
      background: var(--surface); box-shadow: var(--shadow); overflow: hidden;
    }}
    .signal::after {{
      content: ""; position: absolute; inset: auto 12px 10px 12px; height: 5px; border-radius: 99px; background: var(--line);
    }}
    .signal-icon {{
      display: inline-grid; place-items: center; width: 32px; height: 32px; border-radius: 8px;
      background: var(--surface-2); color: var(--muted); font: 900 11px/1 ui-monospace, SFMono-Regular, Menlo, monospace;
    }}
    .signal-label {{ color: var(--muted); font: 800 10px/1 ui-monospace, SFMono-Regular, Menlo, monospace; letter-spacing: .08em; text-transform: uppercase; }}
    .signal strong {{ color: var(--ink); font: 900 34px/1 ui-monospace, SFMono-Regular, Menlo, monospace; }}
    .signal[data-tone="danger"] {{ border-color: rgba(179, 58, 58, .28); background: var(--danger-soft); }}
    .signal[data-tone="danger"]::after, .signal[data-tone="danger"] .signal-icon {{ background: var(--danger); color: #fff; }}
    .signal[data-tone="danger"] strong {{ color: var(--danger); }}
    .signal[data-tone="warn"] {{ border-color: rgba(157, 103, 38, .28); background: var(--warn-soft); }}
    .signal[data-tone="warn"]::after, .signal[data-tone="warn"] .signal-icon {{ background: var(--warn); color: #fff; }}
    .signal[data-tone="hot"] {{ border-color: rgba(49, 93, 154, .24); background: var(--hot-soft); }}
    .signal[data-tone="hot"]::after, .signal[data-tone="hot"] .signal-icon {{ background: var(--hot); color: #fff; }}
    .signal[data-tone="ok"]::after, .signal[data-tone="ok"] .signal-icon {{ background: var(--accent); color: #fff; }}
    .signal[data-tone="ok"] strong {{ color: var(--accent); }}
    .panel, .attention-strip {{
      background: var(--surface); border: 1px solid var(--line); border-radius: 8px; padding: 16px;
      box-shadow: var(--shadow);
    }}
    .panel-kicker {{
      display: block; color: var(--muted); font: 800 10px/1 ui-monospace, SFMono-Regular, Menlo, monospace;
      letter-spacing: .08em; text-transform: uppercase;
    }}
    .workspace {{ display: grid; grid-template-columns: minmax(0, .9fr) minmax(360px, 1.1fr); gap: 12px; align-items: start; }}
    .panel-head, .strip-head {{ display: flex; align-items: flex-start; justify-content: space-between; gap: 12px; margin-bottom: 10px; }}
    .panel-head strong, .strip-head strong {{ display: block; margin-top: 4px; font-size: 17px; line-height: 1.2; }}
    .markdown {{ color: var(--ink); }}
    .markdown h1, .markdown h2, .markdown h3 {{ margin: 18px 0 8px; line-height: 1.16; letter-spacing: 0; }}
    .markdown h1 {{ font-size: 24px; }}
    .markdown h2 {{ font-size: 19px; padding-top: 8px; border-top: 1px solid var(--line); }}
    .markdown h3 {{ font-size: 16px; }}
    .markdown p {{ margin: 8px 0; }}
    .markdown ul {{ margin: 8px 0 14px; padding-left: 22px; }}
    .markdown li {{ margin: 4px 0; }}
    .markdown code {{
      padding: 1px 5px; border-radius: 5px; background: var(--surface-2);
      color: #3c4643; font: 12px/1.35 ui-monospace, SFMono-Regular, Menlo, monospace;
    }}
    .details-stack {{ display: grid; gap: 10px; }}
    .details-stack details {{ margin: 0; }}
    .details-stack .markdown {{ max-height: 560px; overflow: auto; padding: 10px 4px 0 0; }}
    .attention-strip {{ margin-bottom: 12px; border-color: rgba(179, 58, 58, .22); }}
    .attention-grid {{ display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 10px; }}
    .attention-card {{ display: grid; gap: 7px; padding: 12px; border: 1px solid rgba(179, 58, 58, .22); border-left: 5px solid var(--danger); border-radius: 8px; background: var(--danger-soft); }}
    .attention-card span {{ color: var(--danger); font: 800 10px/1 ui-monospace, SFMono-Regular, Menlo, monospace; letter-spacing: .08em; text-transform: uppercase; }}
    .attention-card strong {{ font-size: 16px; }}
    .attention-card p, .attention-card em {{ margin: 0; color: var(--muted); font-style: normal; }}
    .attention-card em {{ padding: 8px 9px; border-radius: 6px; background: var(--surface); color: var(--ink); font-weight: 650; }}
    .timeline {{ position: relative; display: grid; gap: 0; margin: 0; padding: 2px 0 0; list-style: none; }}
    .timeline::before {{ content: ""; position: absolute; top: 10px; bottom: 14px; left: 7px; width: 2px; background: var(--line); }}
    .timeline-item {{ position: relative; display: grid; grid-template-columns: 18px minmax(0, 1fr); gap: 10px; padding: 0 0 18px; }}
    .timeline-dot {{ z-index: 1; width: 12px; height: 12px; margin-top: 6px; border: 2px solid var(--surface); border-radius: 99px; background: var(--accent); box-shadow: 0 0 0 4px var(--accent-soft); }}
    .timeline-dot.is-muted {{ background: var(--soft); box-shadow: 0 0 0 4px var(--surface-2); }}
    .timeline-meta strong {{ display: block; font-size: 14px; }}
    .timeline-meta span, .timeline-meta code {{ display: block; margin-top: 3px; color: var(--muted); overflow-wrap: anywhere; font-size: 12px; }}
    textarea {{
      width: 100%; min-height: 132px; resize: vertical; padding: 12px;
      border: 1px solid var(--line); border-radius: 8px; background: var(--surface-2);
      color: var(--ink); font: 14px/1.45 -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
    }}
    .actions {{ display: flex; flex-wrap: wrap; gap: 8px; margin-top: 10px; }}
    button {{
      min-height: 38px; padding: 0 13px; border: 1px solid var(--line); border-radius: 8px;
      background: var(--surface); color: var(--ink); cursor: pointer; font-weight: 750;
    }}
    button.primary {{ border-color: var(--accent); background: var(--accent); color: #fff; }}
    .hint {{ margin: 9px 0 0; color: var(--muted); font-size: 12px; }}
    details {{ margin-top: 12px; }}
    summary {{ cursor: pointer; color: var(--ink); font-weight: 750; }}
    pre {{
      margin: 10px 0 0; max-height: 360px; overflow: auto; white-space: pre-wrap; overflow-wrap: anywhere;
      background: var(--surface-2); border: 1px solid var(--line); border-radius: 8px; padding: 12px;
      font: 12px/1.5 ui-monospace, SFMono-Regular, Menlo, monospace;
    }}
    @media (max-width: 920px) {{ main {{ padding: 18px; }} header {{ align-items: flex-start; flex-direction: column; }} .status-stack {{ justify-content: flex-start; }} .signals, .workspace, .attention-grid {{ grid-template-columns: 1fr; }} }}
  </style>
</head>
<body>
  <main>
    <header>
      <div>
        <h1>CRM runner</h1>
        <div class="topline">
          <span>{esc(generated_at)}</span>
          <span>/</span>
          <span>60s refresh</span>
        </div>
      </div>
      <div class="status-stack" aria-label="Runner status">
        <span class="badge" data-tone="{esc(status_tone)}" data-icon="{esc(status_icon)}">{esc(local_status)}</span>
        <span class="mini-chip">pid {esc(pid or "-")}</span>
        <span class="mini-chip">start {esc(started_at)}</span>
      </div>
    </header>

    <section class="signals" aria-label="What changed">
      {signals_html}
    </section>

    {attention_html}

    <section class="workspace">
      <aside class="panel">
        <div class="panel-head">
          <div>
            <span class="panel-kicker">Timeline</span>
            <strong>Runs</strong>
          </div>
        </div>
        <ol class="timeline">{timeline_items}</ol>
      </aside>

      <article class="panel details-stack">
        <div class="panel-head">
          <div>
            <span class="panel-kicker">Notes</span>
            <strong>Details</strong>
          </div>
        </div>
        <details>
          <summary>Delta</summary>
          <div id="deltaMarkdown" class="markdown"></div>
        </details>
        <details>
          <summary>Last run</summary>
          <div id="latestMarkdown" class="markdown"></div>
        </details>
        <details>
          <summary>History</summary>
          <div id="historyMarkdown" class="markdown"></div>
        </details>
      </article>
    </section>

    <section class="panel">
      <div class="panel-head">
        <div>
          <span class="panel-kicker">Ask Codex</span>
          <strong>Context prompt</strong>
        </div>
      </div>
      <textarea id="codexRequest" placeholder="Ej: Revisa el caso de Daniel y decime el proximo paso."></textarea>
      <div class="actions">
        <button class="primary" type="button" id="copyPrompt">Copiar prompt</button>
        <button type="button" id="copyCommand">Copiar comando codex exec</button>
      </div>
      <p class="hint" id="copyStatus">Listo para copiar.</p>
    </section>

    <details>
      <summary>Detalles tecnicos</summary>
      {pre_block("Active/latest runner log", read_tail(latest_log, tail_lines))}
    </details>
  </main>

  <script id="runner-context" type="application/json">{context_json}</script>
  <script>
    const context = JSON.parse(document.getElementById("runner-context").textContent);
    const statusEl = document.getElementById("copyStatus");

    function renderMarkdown(targetId, markdown) {{
      const target = document.getElementById(targetId);
      if (window.marked && typeof window.marked.parse === "function") {{
        target.innerHTML = window.marked.parse(escapeMarkdownHtml(neutralizeMarkdownImages(markdown || "")));
      }} else {{
        target.textContent = markdown || "";
      }}
    }}

    function neutralizeMarkdownImages(value) {{
      return String(value)
        .replace(/!\\[([^\\]]*)\\]\\(([^)]*)\\)/g, "[$1]($2)")
        .replace(/!\\[([^\\]]*)\\]/g, "$1");
    }}

    function escapeMarkdownHtml(value) {{
      return String(value)
        .replace(/&/g, "&amp;")
        .replace(/</g, "&lt;")
        .replace(/>/g, "&gt;");
    }}

    function buildPrompt() {{
      const request = document.getElementById("codexRequest").value.trim();
      return [
        "In " + context.root + ", read .codex/skills/contadores-crm-followup-automation/SKILL.md first.",
        "Use the CRM follow-up run context below and answer/act on my request.",
        "Do not send live messages unless the request explicitly asks you to and the skill allows it.",
        "",
        "## My request",
        request || "(write the request here)",
        "",
        "## Delta since previous run",
        context.delta_markdown || "",
        "",
        "## Latest run",
        context.latest_summary || "",
        "",
        "## Accumulated run notes",
        context.history_markdown || ""
      ].join("\\n");
    }}

    function shellQuote(value) {{
      return "'" + String(value).replace(/'/g, "'\\\\''") + "'";
    }}

    function fallbackCopy(text) {{
      const textarea = document.createElement("textarea");
      textarea.value = text;
      textarea.setAttribute("readonly", "true");
      textarea.style.position = "fixed";
      textarea.style.left = "-9999px";
      document.body.appendChild(textarea);
      textarea.select();
      const copied = document.execCommand("copy");
      document.body.removeChild(textarea);
      if (!copied) {{
        throw new Error("clipboard unavailable");
      }}
    }}

    async function copyText(text, label) {{
      if (navigator.clipboard && typeof navigator.clipboard.writeText === "function") {{
        await navigator.clipboard.writeText(text);
      }} else {{
        fallbackCopy(text);
      }}
      statusEl.textContent = label + " copiado.";
    }}

    document.getElementById("copyPrompt").addEventListener("click", () => {{
      copyText(buildPrompt(), "Prompt").catch(() => {{
        statusEl.textContent = "No pude copiar automaticamente. Selecciona el texto manualmente.";
      }});
    }});

    document.getElementById("copyCommand").addEventListener("click", () => {{
      const command = "cat <<'CODEX_PROMPT' | codex exec -C " + shellQuote(context.root) + " -m gpt-5.5 --dangerously-bypass-approvals-and-sandbox -\\n" + buildPrompt() + "\\nCODEX_PROMPT";
      copyText(command, "Comando").catch(() => {{
        statusEl.textContent = "No pude copiar automaticamente. Copia el prompt y corre codex exec manualmente.";
      }});
    }});

    renderMarkdown("latestMarkdown", context.latest_summary);
    renderMarkdown("deltaMarkdown", context.delta_markdown);
    renderMarkdown("historyMarkdown", context.history_markdown);
  </script>
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
