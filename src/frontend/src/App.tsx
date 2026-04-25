import { FormEvent, useCallback, useEffect, useMemo, useState } from "react";
import {
  Archive,
  ArrowClockwise,
  CalendarCheck,
  ChatCenteredText,
  CheckCircle,
  Clock,
  EnvelopeSimple,
  Funnel,
  GearSix,
  ListChecks,
  MagnifyingGlass,
  PaperPlaneTilt,
  PauseCircle,
  Phone,
  Play,
  RocketLaunch,
  UserFocus,
  WarningCircle,
  XCircle,
} from "@phosphor-icons/react";
import { apiFetch } from "./api";
import { compactNumber, humanize, lastInteractionAt, percent, relativeTime, shortDate, stageLabel } from "./format";
import type {
  ContadoresConfig,
  ContadoresMetrics,
  LeadDetailResponse,
  LeadListResponse,
  LeadStage,
  LeadSummary,
  MessageItem,
  QuickActionResponse,
  RuntimeSettings,
  StrategyStatsResponse,
} from "./types";

const REFRESH_MS = 12000;

const stageFilters: Array<{ value: LeadStage | "all"; label: string; metric?: keyof ContadoresMetrics }> = [
  { value: "all", label: "All", metric: "total" },
  { value: "needs_human", label: "Needs human", metric: "needs_human" },
  { value: "awaiting_initial_reply", label: "Initial reply", metric: "awaiting_initial_reply" },
  { value: "awaiting_video_reply", label: "Video reply", metric: "awaiting_video_reply" },
  { value: "calendly_sent", label: "Calendly", metric: "calendly_sent" },
  { value: "booked", label: "Booked", metric: "booked" },
  { value: "closed", label: "Closed", metric: "closed" },
];

const sendActions = [
  { action: "send-opener", label: "Opener", icon: RocketLaunch },
  { action: "send-loom", label: "Loom", icon: Play },
  { action: "send-video-check", label: "Video check", icon: ChatCenteredText },
  { action: "send-calendly", label: "Calendly", icon: CalendarCheck },
] as const;

const stateActions = [
  { action: "mark-answered", label: "Answered", icon: CheckCircle },
  { action: "mark-booked", label: "Booked", icon: CalendarCheck },
  { action: "close", label: "Close", icon: XCircle },
  { action: "archive", label: "Archive", icon: Archive },
] as const;

type QuickActionName = (typeof sendActions)[number]["action"] | (typeof stateActions)[number]["action"] | "reopen" | "unarchive";

function useDebouncedValue<T>(value: T, delayMs: number): T {
  const [debounced, setDebounced] = useState(value);

  useEffect(() => {
    const timer = window.setTimeout(() => setDebounced(value), delayMs);
    return () => window.clearTimeout(timer);
  }, [delayMs, value]);

  return debounced;
}

export function App() {
  const [runtime, setRuntime] = useState<RuntimeSettings | null>(null);
  const [leadList, setLeadList] = useState<LeadListResponse | null>(null);
  const [detail, setDetail] = useState<LeadDetailResponse | null>(null);
  const [strategyStats, setStrategyStats] = useState<StrategyStatsResponse | null>(null);
  const [selectedLeadId, setSelectedLeadId] = useState<string | null>(null);
  const [stageFilter, setStageFilter] = useState<LeadStage | "all">("all");
  const [includeArchived, setIncludeArchived] = useState(false);
  const [query, setQuery] = useState("");
  const [loading, setLoading] = useState(true);
  const [detailLoading, setDetailLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [actionBusy, setActionBusy] = useState<string | null>(null);
  const [manualText, setManualText] = useState("");
  const [lastRefreshAt, setLastRefreshAt] = useState<string | null>(null);
  const debouncedQuery = useDebouncedValue(query, 250);

  const selectedLead = useMemo(() => {
    if (!selectedLeadId || !leadList) {
      return null;
    }
    return leadList.leads.find((lead) => lead.id === selectedLeadId) ?? null;
  }, [leadList, selectedLeadId]);

  const loadDashboard = useCallback(async () => {
    const params = new URLSearchParams({ limit: "500" });
    if (stageFilter !== "all") {
      params.set("stage", stageFilter);
    }
    if (!includeArchived) {
      params.set("archived", "false");
    }
    if (debouncedQuery.trim()) {
      params.set("query", debouncedQuery.trim());
    }

    setError(null);
    const [runtimePayload, leadsPayload, strategyPayload] = await Promise.all([
      apiFetch<RuntimeSettings>("/api/runtime"),
      apiFetch<LeadListResponse>(`/api/contadores/leads?${params.toString()}`),
      apiFetch<StrategyStatsResponse>("/api/contadores/strategy-stats"),
    ]);

    setRuntime(runtimePayload);
    setLeadList(leadsPayload);
    setStrategyStats(strategyPayload);
    setLastRefreshAt(new Date().toISOString());

    setSelectedLeadId((current) => {
      if (current && leadsPayload.leads.some((lead) => lead.id === current)) {
        return current;
      }
      return leadsPayload.leads[0]?.id ?? null;
    });
  }, [debouncedQuery, includeArchived, stageFilter]);

  const loadDetail = useCallback(async (leadId: string) => {
    setDetailLoading(true);
    try {
      const payload = await apiFetch<LeadDetailResponse>(`/api/contadores/leads/${leadId}`);
      setDetail(payload);
    } finally {
      setDetailLoading(false);
    }
  }, []);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    loadDashboard()
      .catch((reason) => {
        if (!cancelled) {
          setError(reason instanceof Error ? reason.message : "Failed to load dashboard.");
        }
      })
      .finally(() => {
        if (!cancelled) {
          setLoading(false);
        }
      });
    return () => {
      cancelled = true;
    };
  }, [loadDashboard]);

  useEffect(() => {
    const timer = window.setInterval(() => {
      if (document.visibilityState === "visible") {
        loadDashboard().catch((reason) => {
          setError(reason instanceof Error ? reason.message : "Auto-refresh failed.");
        });
      }
    }, REFRESH_MS);
    return () => window.clearInterval(timer);
  }, [loadDashboard]);

  useEffect(() => {
    if (!selectedLeadId) {
      setDetail(null);
      return;
    }
    loadDetail(selectedLeadId).catch((reason) => {
      setError(reason instanceof Error ? reason.message : "Failed to load lead detail.");
    });
  }, [loadDetail, selectedLeadId]);

  async function refreshAll() {
    setLoading(true);
    try {
      await loadDashboard();
      if (selectedLeadId) {
        await loadDetail(selectedLeadId);
      }
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Refresh failed.");
    } finally {
      setLoading(false);
    }
  }

  async function runAction(action: QuickActionName) {
    const leadId = detail?.lead.id ?? selectedLeadId;
    if (!leadId) {
      return;
    }
    setActionBusy(action);
    try {
      const payload = await apiFetch<QuickActionResponse>(`/api/contadores/leads/${leadId}/actions/${action}`, {
        method: "POST",
      });
      setDetail((current) => (current ? { ...current, lead: payload.lead } : current));
      await loadDashboard();
      await loadDetail(leadId);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Action failed.");
    } finally {
      setActionBusy(null);
    }
  }

  async function resumeAutomation() {
    const leadId = detail?.lead.id ?? selectedLeadId;
    if (!leadId) {
      return;
    }
    setActionBusy("resume");
    try {
      await apiFetch<QuickActionResponse>(`/api/contadores/leads/${leadId}/resume-automation`, {
        method: "POST",
      });
      await loadDashboard();
      await loadDetail(leadId);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Resume failed.");
    } finally {
      setActionBusy(null);
    }
  }

  async function sendManualMessage(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const leadId = detail?.lead.id ?? selectedLeadId;
    const text = manualText.trim();
    if (!leadId || !text) {
      return;
    }
    setActionBusy("manual");
    try {
      await apiFetch<QuickActionResponse>(`/api/contadores/leads/${leadId}/messages/manual`, {
        method: "POST",
        body: JSON.stringify({ text }),
      });
      setManualText("");
      await loadDashboard();
      await loadDetail(leadId);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Could not queue manual message.");
    } finally {
      setActionBusy(null);
    }
  }

  async function saveConfig(nextConfig: Partial<ContadoresConfig>) {
    setActionBusy("config");
    try {
      await apiFetch<ContadoresConfig>("/api/contadores/config", {
        method: "PUT",
        body: JSON.stringify(nextConfig),
      });
      await loadDashboard();
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Could not save config.");
    } finally {
      setActionBusy(null);
    }
  }

  const metrics = leadList?.metrics;

  return (
    <div className="app-shell">
      <header className="topbar">
        <div>
          <div className="product-mark">
            <span className="mark-dot" />
            <span>Contadores Ops</span>
          </div>
          <h1>WhatsApp follow-up control room</h1>
        </div>
        <div className="topbar-actions">
          <RuntimePill runtime={runtime} />
          <button className="icon-button" type="button" onClick={refreshAll} disabled={loading} title="Refresh">
            <ArrowClockwise size={18} weight="bold" />
          </button>
        </div>
      </header>

      {error ? (
        <div className="error-banner" role="alert">
          <WarningCircle size={18} weight="bold" />
          <span>{error}</span>
          <button type="button" onClick={() => setError(null)} aria-label="Dismiss error">
            <XCircle size={18} weight="bold" />
          </button>
        </div>
      ) : null}

      <section className="status-strip" aria-label="Current status">
        <StatusItem label="Runtime" value={runtime?.source_mode ?? "-"} tone={runtime?.source_mode === "live" ? "live" : "testing"} />
        <StatusItem label="Ready" value={runtime?.ready ? "Yes" : "Check"} tone={runtime?.ready ? "ok" : "warn"} />
        <StatusItem label="Auto refresh" value={lastRefreshAt ? relativeTime(lastRefreshAt) : "Starting"} tone="neutral" />
        <StatusItem label="Last sheet sync" value={shortDate(leadList?.config.last_sheet_sync_at)} tone="neutral" />
      </section>

      <MetricsBar metrics={metrics} activeStage={stageFilter} onStageChange={setStageFilter} />

      <main className="workspace">
        <section className="lead-column" aria-label="Lead list">
          <div className="toolbar">
            <label className="search-box">
              <MagnifyingGlass size={17} weight="bold" />
              <input value={query} onChange={(event) => setQuery(event.target.value)} placeholder="Search leads" />
            </label>
            <button
              className={`filter-button ${includeArchived ? "active" : ""}`}
              type="button"
              onClick={() => setIncludeArchived((value) => !value)}
            >
              <Funnel size={16} weight="bold" />
              Archived
            </button>
          </div>

          <LeadList
            leads={leadList?.leads ?? []}
            loading={loading}
            selectedLeadId={selectedLeadId}
            onSelect={setSelectedLeadId}
          />
        </section>

        <section className="detail-column" aria-label="Lead detail">
          <LeadDetail
            detail={detail}
            fallbackLead={selectedLead}
            loading={detailLoading}
            actionBusy={actionBusy}
            manualText={manualText}
            onManualTextChange={setManualText}
            onManualSubmit={sendManualMessage}
            onQuickAction={runAction}
            onResume={resumeAutomation}
          />
        </section>

        <aside className="side-column" aria-label="Configuration and strategy">
          <ConfigPanel config={leadList?.config ?? null} runtime={runtime} saving={actionBusy === "config"} onSave={saveConfig} />
          <StrategyPanel stats={strategyStats} />
        </aside>
      </main>
    </div>
  );
}

function RuntimePill({ runtime }: { runtime: RuntimeSettings | null }) {
  const ready = runtime?.ready ?? false;
  return (
    <div className={`runtime-pill ${ready ? "ready" : "blocked"}`}>
      {ready ? <CheckCircle size={16} weight="fill" /> : <WarningCircle size={16} weight="fill" />}
      <span>{runtime ? `${runtime.source_mode} mode` : "loading"}</span>
    </div>
  );
}

function StatusItem({ label, value, tone }: { label: string; value: string; tone: string }) {
  return (
    <div className={`status-item ${tone}`}>
      <span>{label}</span>
      <strong>{value}</strong>
    </div>
  );
}

function MetricsBar({
  metrics,
  activeStage,
  onStageChange,
}: {
  metrics: ContadoresMetrics | undefined;
  activeStage: LeadStage | "all";
  onStageChange: (stage: LeadStage | "all") => void;
}) {
  return (
    <section className="metric-rail" aria-label="Stage filters">
      {stageFilters.map((filter) => {
        const count = filter.metric && metrics ? metrics[filter.metric] : 0;
        return (
          <button
            key={filter.value}
            type="button"
            className={`metric-tile ${activeStage === filter.value ? "active" : ""}`}
            onClick={() => onStageChange(filter.value)}
          >
            <span>{filter.label}</span>
            <strong>{compactNumber(Number(count ?? 0))}</strong>
          </button>
        );
      })}
    </section>
  );
}

function LeadList({
  leads,
  loading,
  selectedLeadId,
  onSelect,
}: {
  leads: LeadSummary[];
  loading: boolean;
  selectedLeadId: string | null;
  onSelect: (leadId: string) => void;
}) {
  if (loading && !leads.length) {
    return (
      <div className="lead-list">
        {Array.from({ length: 8 }, (_, index) => (
          <div className="lead-skeleton" key={index} />
        ))}
      </div>
    );
  }

  if (!leads.length) {
    return (
      <div className="empty-state">
        <ListChecks size={26} weight="bold" />
        <h2>No leads in this view</h2>
        <p>Adjust filters or wait for the next source sync.</p>
      </div>
    );
  }

  return (
    <div className="lead-list">
      {leads.map((lead) => {
        const active = lead.id === selectedLeadId;
        const lastAt = lastInteractionAt(lead);
        return (
          <button key={lead.id} className={`lead-row ${active ? "active" : ""}`} type="button" onClick={() => onSelect(lead.id)}>
            <div className="lead-row-top">
              <strong>{lead.full_name || "Unnamed lead"}</strong>
              <StageBadge stage={lead.stage} />
            </div>
            <div className="lead-row-meta">
              <span>{lead.phone}</span>
              <span>{relativeTime(lastAt)}</span>
            </div>
            <div className="lead-row-bottom">
              <span>{lead.platform || "unknown source"}</span>
              {lead.manual_reply_status === "needs_reply" ? <em>reply needed</em> : null}
            </div>
          </button>
        );
      })}
    </div>
  );
}

function LeadDetail({
  detail,
  fallbackLead,
  loading,
  actionBusy,
  manualText,
  onManualTextChange,
  onManualSubmit,
  onQuickAction,
  onResume,
}: {
  detail: LeadDetailResponse | null;
  fallbackLead: LeadSummary | null;
  loading: boolean;
  actionBusy: string | null;
  manualText: string;
  onManualTextChange: (value: string) => void;
  onManualSubmit: (event: FormEvent<HTMLFormElement>) => void;
  onQuickAction: (action: QuickActionName) => void;
  onResume: () => void;
}) {
  const lead = detail?.lead ?? fallbackLead;

  if (!lead) {
    return (
      <div className="detail-empty">
        <UserFocus size={32} weight="bold" />
        <h2>Select a lead</h2>
        <p>Open a lead to inspect messages, automation state, and manual controls.</p>
      </div>
    );
  }

  return (
    <div className="detail-panel">
      <div className="detail-head">
        <div>
          <div className="detail-kicker">
            <Phone size={15} weight="bold" />
            <span>{lead.phone}</span>
          </div>
          <h2>{lead.full_name || "Unnamed lead"}</h2>
          <p>{lead.email || "No email"} · {lead.platform || "unknown source"}</p>
        </div>
        <StageBadge stage={lead.stage} large />
      </div>

      <div className="lead-facts">
        <Fact label="Last inbound" value={shortDate(lead.last_inbound_at)} />
        <Fact label="Last outbound" value={shortDate(lead.last_outbound_at)} />
        <Fact label="Updated" value={relativeTime(lead.updated_at)} />
        <Fact label="Manual" value={lead.manual_reply_status ? humanize(lead.manual_reply_status) : "Clear"} />
      </div>

      {lead.automation_paused ? (
        <div className="pause-callout">
          <PauseCircle size={18} weight="fill" />
          <div>
            <strong>Automation paused</strong>
            <span>{humanize(lead.automation_paused_reason || "manual review")}</span>
          </div>
          <button type="button" onClick={onResume} disabled={actionBusy === "resume"}>
            Resume
          </button>
        </div>
      ) : null}

      <div className="action-grid" aria-label="Quick actions">
        {sendActions.map((item) => {
          const Icon = item.icon;
          return (
            <button key={item.action} type="button" onClick={() => onQuickAction(item.action)} disabled={Boolean(actionBusy)}>
              <Icon size={16} weight="bold" />
              {item.label}
            </button>
          );
        })}
      </div>

      <form className="manual-form" onSubmit={onManualSubmit}>
        <label>
          <span>Manual WhatsApp message</span>
          <textarea
            value={manualText}
            onChange={(event) => onManualTextChange(event.target.value)}
            placeholder="Write the exact message to queue..."
            rows={4}
          />
        </label>
        <button type="submit" disabled={!manualText.trim() || Boolean(actionBusy)}>
          <PaperPlaneTilt size={16} weight="bold" />
          Queue message
        </button>
      </form>

      <div className="secondary-actions">
        {stateActions.map((item) => {
          const Icon = item.icon;
          return (
            <button key={item.action} type="button" onClick={() => onQuickAction(item.action)} disabled={Boolean(actionBusy)}>
              <Icon size={15} weight="bold" />
              {item.label}
            </button>
          );
        })}
        {lead.stage === "closed" ? (
          <button type="button" onClick={() => onQuickAction("reopen")} disabled={Boolean(actionBusy)}>
            <Play size={15} weight="bold" />
            Reopen
          </button>
        ) : null}
        {lead.stage === "archived" ? (
          <button type="button" onClick={() => onQuickAction("unarchive")} disabled={Boolean(actionBusy)}>
            <Archive size={15} weight="bold" />
            Unarchive
          </button>
        ) : null}
      </div>

      <div className="timeline-wrap">
        <div className="section-title">
          <h3>Conversation</h3>
          <span>{loading ? "Refreshing" : `${detail?.messages.length ?? 0} messages`}</span>
        </div>
        <MessageTimeline messages={detail?.messages ?? []} loading={loading} />
      </div>

      <div className="timeline-wrap compact">
        <div className="section-title">
          <h3>Events</h3>
          <span>{detail?.events.length ?? 0} entries</span>
        </div>
        <EventTimeline events={detail?.events ?? []} />
      </div>
    </div>
  );
}

function StageBadge({ stage, large = false }: { stage: LeadStage; large?: boolean }) {
  return <span className={`stage-badge ${stage} ${large ? "large" : ""}`}>{stageLabel(stage)}</span>;
}

function Fact({ label, value }: { label: string; value: string }) {
  return (
    <div className="fact">
      <span>{label}</span>
      <strong>{value}</strong>
    </div>
  );
}

function MessageTimeline({ messages, loading }: { messages: MessageItem[]; loading: boolean }) {
  if (loading && !messages.length) {
    return <div className="timeline-skeleton" />;
  }

  if (!messages.length) {
    return (
      <div className="inline-empty">
        <ChatCenteredText size={20} weight="bold" />
        <span>No messages yet.</span>
      </div>
    );
  }

  return (
    <div className="message-list">
      {messages.map((message) => (
        <article key={message.id} className={`message ${message.from_me ? "outbound" : "inbound"}`}>
          <div className="message-meta">
            <strong>{message.from_me ? "Outbound" : "Inbound"}</strong>
            <span>{shortDate(message.created_at)}</span>
            {message.sequence_step ? <em>{humanize(message.sequence_step)}</em> : null}
          </div>
          <p>{message.text}</p>
          {message.from_me ? <span className="delivery">{humanize(message.delivery_status)}</span> : null}
        </article>
      ))}
    </div>
  );
}

function EventTimeline({ events }: { events: Array<{ id: number; event_type: string; summary: string; actor: string | null; created_at: string }> }) {
  if (!events.length) {
    return (
      <div className="inline-empty">
        <Clock size={20} weight="bold" />
        <span>No events yet.</span>
      </div>
    );
  }

  return (
    <div className="event-list">
      {events.slice(0, 10).map((event) => (
        <div className="event-row" key={event.id}>
          <span>{shortDate(event.created_at)}</span>
          <strong>{humanize(event.event_type)}</strong>
          <p>{event.summary}</p>
        </div>
      ))}
    </div>
  );
}

function ConfigPanel({
  config,
  runtime,
  saving,
  onSave,
}: {
  config: ContadoresConfig | null;
  runtime: RuntimeSettings | null;
  saving: boolean;
  onSave: (config: Partial<ContadoresConfig>) => Promise<void>;
}) {
  const [draft, setDraft] = useState({
    enabled: true,
    loom_url: "",
    calendly_base_url: "",
    sheet_poll_seconds: 300,
    alert_emails: "",
    post_loom_min_seconds: 600,
  });

  useEffect(() => {
    if (!config) {
      return;
    }
    setDraft({
      enabled: config.enabled,
      loom_url: config.loom_url,
      calendly_base_url: config.calendly_base_url,
      sheet_poll_seconds: config.sheet_poll_seconds,
      alert_emails: config.alert_emails.join(", "),
      post_loom_min_seconds: config.post_loom_min_seconds,
    });
  }, [config]);

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    await onSave({
      enabled: draft.enabled,
      loom_url: draft.loom_url,
      calendly_base_url: draft.calendly_base_url,
      sheet_poll_seconds: Number(draft.sheet_poll_seconds),
      post_loom_min_seconds: Number(draft.post_loom_min_seconds),
      alert_emails: draft.alert_emails.split(",").map((item) => item.trim()).filter(Boolean),
    });
  }

  return (
    <section className="ops-panel config-panel">
      <div className="panel-head">
        <div>
          <span>Runtime</span>
          <h2>Source and sequence</h2>
        </div>
        <GearSix size={19} weight="bold" />
      </div>

      <div className="runtime-stack">
        <Fact label="Mode" value={runtime?.source_mode ?? "-"} />
        <Fact label="Sheet" value={runtime?.sheet_configured ? "Configured" : "Missing"} />
        <Fact label="Test phone" value={runtime?.testing_phone_configured ? "Configured" : "Missing"} />
      </div>

      <form className="config-form" onSubmit={handleSubmit}>
        <label className="toggle-line">
          <input type="checkbox" checked={draft.enabled} onChange={(event) => setDraft((current) => ({ ...current, enabled: event.target.checked }))} />
          <span>Automation enabled</span>
        </label>
        <label>
          <span>Loom URL</span>
          <input value={draft.loom_url} onChange={(event) => setDraft((current) => ({ ...current, loom_url: event.target.value }))} />
        </label>
        <label>
          <span>Calendly URL</span>
          <input value={draft.calendly_base_url} onChange={(event) => setDraft((current) => ({ ...current, calendly_base_url: event.target.value }))} />
        </label>
        <div className="form-grid">
          <label>
            <span>Sheet poll seconds</span>
            <input
              type="number"
              min={60}
              value={draft.sheet_poll_seconds}
              onChange={(event) => setDraft((current) => ({ ...current, sheet_poll_seconds: Number(event.target.value) }))}
            />
          </label>
          <label>
            <span>Post-Loom wait</span>
            <input
              type="number"
              min={60}
              value={draft.post_loom_min_seconds}
              onChange={(event) => setDraft((current) => ({ ...current, post_loom_min_seconds: Number(event.target.value) }))}
            />
          </label>
        </div>
        <label>
          <span>Alert emails</span>
          <input value={draft.alert_emails} onChange={(event) => setDraft((current) => ({ ...current, alert_emails: event.target.value }))} />
        </label>
        <button type="submit" disabled={saving || !config}>
          {saving ? "Saving" : "Save config"}
        </button>
      </form>
    </section>
  );
}

function StrategyPanel({ stats }: { stats: StrategyStatsResponse | null }) {
  const rows = stats?.items ?? [];
  const topRows = rows.slice(0, 6);

  return (
    <section className="ops-panel strategy-panel">
      <div className="panel-head">
        <div>
          <span>Experiments</span>
          <h2>Strategy performance</h2>
        </div>
        <ListChecks size={19} weight="bold" />
      </div>
      {!topRows.length ? (
        <div className="inline-empty">
          <ListChecks size={20} weight="bold" />
          <span>No strategy data yet.</span>
        </div>
      ) : (
        <div className="strategy-table">
          {topRows.map((row) => (
            <div className="strategy-row" key={`${row.step}-${row.strategy_id}`}>
              <div>
                <strong>{row.strategy_label}</strong>
                <span>{humanize(row.step)} · {row.assigned} assigned</span>
              </div>
              <div>
                <span>{percent(row.calendly_rate)}</span>
                <em>calendly</em>
              </div>
              <div>
                <span>{percent(row.booked_rate)}</span>
                <em>booked</em>
              </div>
            </div>
          ))}
        </div>
      )}
      <div className="support-line">
        <EnvelopeSimple size={15} weight="bold" />
        <span>Human alerts use the shared AgentMail inbox.</span>
      </div>
    </section>
  );
}
