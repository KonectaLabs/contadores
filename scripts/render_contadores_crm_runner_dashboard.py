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
    history_path = reports_dir / "contadores-crm-followup-history.md"
    latest_summary = read_text(latest_summary_path) or "No final summary yet."
    history_markdown = read_text(history_path) or latest_summary

    timeline_items = "\n".join(
        f"""
        <li>
          <div class="dot"></div>
          <div>
            <strong>{esc(relative_time(log_path))}</strong>
            <span>{esc(file_mtime(log_path))}</span>
            <code>{esc(log_path.name)} · {esc(file_size(log_path))}</code>
          </div>
        </li>
        """
        for log_path in recent_logs
    ) or '<li><div class="dot"></div><div><strong>No runs yet</strong><span>-</span></div></li>'

    generated_at = datetime.now().astimezone().strftime("%Y-%m-%d %H:%M:%S %Z")
    pid = parse_pid(lock_dir / "pid") if lock_dir.exists() else None
    started_at = read_text(lock_dir / "started_at").strip() or "-"
    latest_label = f"{relative_time(latest_summary_path)} · {file_mtime(latest_summary_path)}"
    prompt_context = {
        "root": str(root),
        "latest_summary": latest_summary,
        "history_markdown": history_markdown,
    }
    context_json = json.dumps(prompt_context, ensure_ascii=False).replace("</", "<\\/")

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
      --bg: #f5f7f6;
      --surface: #ffffff;
      --surface-2: #f8faf9;
      --line: #dfe5e2;
      --ink: #1f2423;
      --muted: #65706d;
      --soft: #8a9491;
      --accent: #0f766e;
      --accent-soft: #e5f4f1;
      --danger: #a33b3b;
      --shadow: 0 20px 50px rgba(31, 36, 35, 0.08);
    }}
    * {{ box-sizing: border-box; }}
    body {{
      margin: 0;
      background: var(--bg);
      color: var(--ink);
      font: 14px/1.5 -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
    }}
    main {{ max-width: 1320px; margin: 0 auto; padding: 28px; }}
    header {{ display: flex; align-items: flex-start; justify-content: space-between; gap: 18px; margin-bottom: 18px; }}
    h1 {{ margin: 0; font-size: 26px; line-height: 1.08; letter-spacing: 0; }}
    .sub {{ margin: 6px 0 0; color: var(--muted); font-size: 13px; }}
    .badge {{
      display: inline-flex; align-items: center; min-height: 32px; padding: 0 12px;
      border-radius: 8px; background: var(--surface); border: 1px solid var(--line);
      color: var(--accent); font: 800 12px/1 ui-monospace, SFMono-Regular, Menlo, monospace;
    }}
    .badge[data-status="failed"], .badge[data-status="stale lock"] {{ color: var(--danger); }}
    .badge[data-status="idle"] {{ color: var(--muted); }}
    .overview {{ display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 12px; margin-bottom: 14px; }}
    .metric, .panel {{
      background: var(--surface); border: 1px solid var(--line); border-radius: 8px; padding: 16px;
      box-shadow: var(--shadow);
    }}
    .metric span, .panel-kicker {{
      display: block; color: var(--muted); font: 800 10px/1 ui-monospace, SFMono-Regular, Menlo, monospace;
      letter-spacing: .08em; text-transform: uppercase;
    }}
    .metric strong {{ display: block; margin-top: 8px; overflow-wrap: anywhere; font-size: 16px; line-height: 1.25; }}
    .workspace {{ display: grid; grid-template-columns: minmax(0, 1.45fr) minmax(330px, .75fr); gap: 14px; align-items: start; }}
    .panel-head {{ display: flex; align-items: flex-start; justify-content: space-between; gap: 12px; margin-bottom: 12px; }}
    .panel-head strong {{ display: block; margin-top: 4px; font-size: 18px; line-height: 1.2; }}
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
    .last-run {{ max-height: 640px; overflow: auto; padding-right: 8px; }}
    .history {{ margin-top: 14px; }}
    .history .markdown {{ max-height: 760px; overflow: auto; padding-right: 8px; }}
    .timeline {{ display: grid; gap: 0; margin: 0; padding: 0; list-style: none; }}
    .timeline li {{ display: grid; grid-template-columns: 18px minmax(0, 1fr); gap: 10px; padding: 0 0 18px; }}
    .dot {{ width: 9px; height: 9px; margin-top: 7px; border-radius: 99px; background: var(--accent); box-shadow: 0 0 0 5px var(--accent-soft); }}
    .timeline strong {{ display: block; font-size: 14px; }}
    .timeline span, .timeline code {{ display: block; margin-top: 3px; color: var(--muted); overflow-wrap: anywhere; font-size: 12px; }}
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
    details {{ margin-top: 14px; }}
    summary {{ cursor: pointer; color: var(--muted); font-weight: 750; }}
    pre {{
      margin: 10px 0 0; max-height: 360px; overflow: auto; white-space: pre-wrap; overflow-wrap: anywhere;
      background: var(--surface-2); border: 1px solid var(--line); border-radius: 8px; padding: 12px;
      font: 12px/1.5 ui-monospace, SFMono-Regular, Menlo, monospace;
    }}
    @media (max-width: 920px) {{ main {{ padding: 18px; }} .overview, .workspace {{ grid-template-columns: 1fr; }} }}
  </style>
</head>
<body>
  <main>
    <header>
      <div>
        <h1>CRM follow-up runs</h1>
        <p class="sub">Vista local de la Mac. Renderiza las notas de la automation y se actualiza cada 60 segundos.</p>
      </div>
      <span class="badge" data-status="{esc(local_status)}">{esc(local_status)}</span>
    </header>

    <section class="overview" aria-label="Timeline summary">
      <div class="metric"><span>Last run</span><strong>{esc(latest_label)}</strong></div>
      <div class="metric"><span>Previous runs</span><strong>{esc(len(recent_logs))} recent logs</strong></div>
      <div class="metric"><span>LaunchAgent</span><strong>{esc(launchctl_summary["state"])} · exit {esc(launchctl_summary["last exit code"])}</strong></div>
    </section>

    <section class="workspace">
      <article class="panel">
        <div class="panel-head">
          <div>
            <span class="panel-kicker">Last run</span>
            <strong>Resumen final</strong>
          </div>
        </div>
        <div id="latestMarkdown" class="markdown last-run"></div>
      </article>

      <aside class="panel">
        <div class="panel-head">
          <div>
            <span class="panel-kicker">Timeline</span>
            <strong>Corridas recientes</strong>
          </div>
        </div>
        <ol class="timeline">{timeline_items}</ol>
      </aside>
    </section>

    <section class="panel history">
      <div class="panel-head">
        <div>
          <span class="panel-kicker">Accumulated notes</span>
          <strong>Historial human-readable</strong>
        </div>
      </div>
      <div id="historyMarkdown" class="markdown"></div>
    </section>

    <section class="panel history">
      <div class="panel-head">
        <div>
          <span class="panel-kicker">Ask Codex</span>
          <strong>Usar el resultado de esta corrida como contexto</strong>
        </div>
      </div>
      <textarea id="codexRequest" placeholder="Ej: Ese mensaje a Daniel esta mal, corregilo y decime que harias ahora. O: mandale a X una pregunta para coordinar llamada."></textarea>
      <div class="actions">
        <button class="primary" type="button" id="copyPrompt">Copiar prompt</button>
        <button type="button" id="copyCommand">Copiar comando codex exec</button>
      </div>
      <p class="hint" id="copyStatus">Esto arma un prompt nuevo con el last run y el historial. Lo pegas en Codex o corres el comando copiado en Terminal.</p>
    </section>

    <details>
      <summary>Detalles tecnicos</summary>
      {pre_block("Active/latest runner log", read_tail(latest_log, tail_lines))}
      {pre_block("launchctl raw state", launchctl_output)}
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
