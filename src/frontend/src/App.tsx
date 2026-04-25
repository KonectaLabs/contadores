import { FormEvent, useCallback, useEffect, useMemo, useState } from "react";
import { apiFetch } from "./api";
import { compactNumber, humanize, lastInteractionAt, relativeTime, shortDate } from "./format";
import type {
  ContadoresConfig,
  ContadoresMetrics,
  EventItem,
  LeadDetailResponse,
  LeadListResponse,
  LeadStage,
  LeadSummary,
  MessageItem,
  QuickActionResponse,
  RuntimeSettings,
  StrategyStatsItem,
  StrategyStatsResponse,
} from "./types";

const REFRESH_MS = 12000;

const stageFilters: Array<{
  value: LeadStage | "all";
  label: string;
  metric: keyof ContadoresMetrics;
  tone: "all" | "neutral" | "accent" | "success" | "warn" | "muted";
}> = [
  { value: "all", label: "All", metric: "total", tone: "all" },
  { value: "awaiting_initial_reply", label: "Opener sent", metric: "awaiting_initial_reply", tone: "neutral" },
  { value: "awaiting_video_reply", label: "Loom sent", metric: "awaiting_video_reply", tone: "neutral" },
  { value: "calendly_sent", label: "Calendly sent", metric: "calendly_sent", tone: "accent" },
  { value: "booked", label: "Booked", metric: "booked", tone: "success" },
  { value: "needs_human", label: "Manual", metric: "needs_human", tone: "warn" },
  { value: "closed", label: "Closed", metric: "closed", tone: "muted" },
];

const sendOptions = [
  { value: "custom", title: "Custom message", help: "Write your own WhatsApp reply." },
  { value: "send-opener", title: "Opener", help: "Queue the default opener template." },
  { value: "send-loom", title: "Loom sequence", help: "Queue the Loom video introduction messages." },
  { value: "send-video-check", title: "Video check", help: "Ask if they watched the Loom." },
  { value: "send-calendly", title: "Calendly sequence", help: "Share Calendly link and booking instructions." },
] as const;

type ManualReplyFilter = "" | "needs_reply" | "answered";
type DetailTab = "messages" | "events" | "strategies";
type SendKind = (typeof sendOptions)[number]["value"];
type StrategyWeights = Record<string, Record<string, number>>;
type QuickActionName =
  | "send-opener"
  | "send-loom"
  | "send-video-check"
  | "send-calendly"
  | "mark-answered"
  | "mark-booked"
  | "close"
  | "reopen"
  | "archive"
  | "unarchive";

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
  const [strategyStats, setStrategyStats] = useState<StrategyStatsItem[]>([]);
  const [detail, setDetail] = useState<LeadDetailResponse | null>(null);
  const [selectedLeadId, setSelectedLeadId] = useState<string | null>(null);
  const [stageFilter, setStageFilter] = useState<LeadStage | "all">("all");
  const [manualReplyFilter, setManualReplyFilter] = useState<ManualReplyFilter>("");
  const [strategyFilter, setStrategyFilter] = useState<{ step: string; strategyId: string }>({ step: "", strategyId: "" });
  const [activeTab, setActiveTab] = useState<DetailTab>("messages");
  const [query, setQuery] = useState("");
  const [loading, setLoading] = useState(true);
  const [detailLoading, setDetailLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [actionBusy, setActionBusy] = useState<string | null>(null);
  const [showConfig, setShowConfig] = useState(false);
  const [showSendModal, setShowSendModal] = useState(false);
  const [sendKind, setSendKind] = useState<SendKind>("custom");
  const [manualText, setManualText] = useState("");
  const debouncedQuery = useDebouncedValue(query, 250);

  const metrics = leadList?.metrics;
  const config = leadList?.config ?? detail?.config ?? null;

  const selectedLead = useMemo(() => {
    if (detail?.lead.id === selectedLeadId) {
      return detail.lead;
    }
    if (!selectedLeadId || !leadList) {
      return null;
    }
    return leadList.leads.find((lead) => lead.id === selectedLeadId) ?? null;
  }, [detail, leadList, selectedLeadId]);

  const loadDashboard = useCallback(async () => {
    const params = new URLSearchParams({ limit: "500", archived: "false" });
    if (stageFilter !== "all") {
      params.set("stage", stageFilter);
    }
    if (stageFilter === "needs_human" && manualReplyFilter) {
      params.set("manual_reply_status", manualReplyFilter);
      params.set("needs_human", "true");
    }
    if (strategyFilter.step) {
      params.set("strategy_step", strategyFilter.step);
    }
    if (strategyFilter.strategyId) {
      params.set("strategy_id", strategyFilter.strategyId);
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
    setStrategyStats(strategyPayload.items ?? []);

    setSelectedLeadId((current) => {
      if (current && leadsPayload.leads.some((lead) => lead.id === current)) {
        return current;
      }
      return leadsPayload.leads[0]?.id ?? null;
    });
  }, [debouncedQuery, manualReplyFilter, stageFilter, strategyFilter.step, strategyFilter.strategyId]);

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
    if (stageFilter !== "needs_human" && manualReplyFilter) {
      setManualReplyFilter("");
    }
  }, [manualReplyFilter, stageFilter]);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    loadDashboard()
      .catch((reason) => {
        if (!cancelled) {
          setError(reason instanceof Error ? reason.message : "Could not load Contadores.");
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
          setError(reason instanceof Error ? reason.message : "Automatic refresh failed.");
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
    setActiveTab("messages");
    loadDetail(selectedLeadId).catch((reason) => {
      setError(reason instanceof Error ? reason.message : "Could not load the lead.");
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
      setError(reason instanceof Error ? reason.message : "Could not refresh Contadores.");
    } finally {
      setLoading(false);
    }
  }

  async function runAction(action: QuickActionName) {
    const leadId = selectedLead?.id ?? selectedLeadId;
    if (!leadId) {
      return;
    }
    setActionBusy(action);
    try {
      await apiFetch<QuickActionResponse>(`/api/contadores/leads/${leadId}/actions/${action}`, {
        method: "POST",
      });
      await loadDashboard();
      await loadDetail(leadId);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Could not run the action.");
    } finally {
      setActionBusy(null);
    }
  }

  async function resumeAutomation() {
    const leadId = selectedLead?.id ?? selectedLeadId;
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
      setError(reason instanceof Error ? reason.message : "Could not resume automation.");
    } finally {
      setActionBusy(null);
    }
  }

  async function submitSendModal(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const leadId = selectedLead?.id ?? selectedLeadId;
    if (!leadId) {
      return;
    }

    setActionBusy("send-modal");
    try {
      if (sendKind === "custom") {
        const text = manualText.trim();
        if (!text) {
          return;
        }
        await apiFetch<QuickActionResponse>(`/api/contadores/leads/${leadId}/messages/manual`, {
          method: "POST",
          body: JSON.stringify({ text }),
        });
        setManualText("");
      } else {
        await apiFetch<QuickActionResponse>(`/api/contadores/leads/${leadId}/actions/${sendKind}`, {
          method: "POST",
        });
      }
      setShowSendModal(false);
      await loadDashboard();
      await loadDetail(leadId);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Could not send the message.");
    } finally {
      setActionBusy(null);
    }
  }

  async function deleteLead() {
    const leadId = selectedLead?.id ?? selectedLeadId;
    if (!leadId || !window.confirm("Delete this chat and its local history?")) {
      return;
    }
    setActionBusy("delete");
    try {
      await apiFetch<{ status: string; lead_id: string }>(`/api/contadores/leads/${leadId}`, {
        method: "DELETE",
      });
      setDetail(null);
      setSelectedLeadId(null);
      await loadDashboard();
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Could not delete the chat.");
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
      setShowConfig(false);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Could not save config.");
    } finally {
      setActionBusy(null);
    }
  }

  const visibleCount = leadList?.leads.length ?? 0;
  const totalCount = metrics?.total ?? 0;
  const syncStatus = config?.last_sheet_sync_status
    ? `${config.last_sheet_sync_status} · ${config.last_sheet_sync_at ? relativeTime(config.last_sheet_sync_at) : "never"}`
    : runtime
      ? `${runtime.source_mode} mode`
      : "Sync idle";

  return (
    <section id="contadoresView" className="contadores-view" data-app="contadores">
      <header className="ct-topbar">
        <div className="ct-topbar-brand">
          <span className="ct-brand-mark" aria-hidden="true">CT</span>
          <div className="ct-brand-copy">
            <p className="ct-brand-word">Contadores</p>
            <span className={`ct-sync-badge ${config?.last_sheet_sync_status === "ok" ? "has-unread" : ""}`}>{syncStatus}</span>
          </div>
        </div>

        <nav className="ct-topbar-nav" aria-label="Backoffice sections">
          <button type="button" className="ct-nav-btn active">Contadores</button>
        </nav>

        <div className="ct-topbar-tools">
          <label className="ct-search">
            <span className="ct-search-icon" aria-hidden="true" />
            <input
              value={query}
              onChange={(event) => setQuery(event.target.value)}
              type="text"
              placeholder="Search name, phone, email, lead id"
              autoComplete="off"
            />
          </label>
          <button type="button" className="ct-icon-btn" onClick={() => setShowConfig(true)}>Settings</button>
          <button type="button" className="ct-icon-btn" onClick={refreshAll} disabled={loading}>Refresh</button>
        </div>
      </header>

      {error ? (
        <div className="ct-error" role="alert">
          <span>{error}</span>
          <button type="button" className="ct-icon-btn" onClick={() => setError(null)}>Dismiss</button>
        </div>
      ) : null}

      <div className="ct-surface">
        <section className="ct-pipeline" aria-label="Lead stages">
          {stageFilters.map((filter) => (
            <button
              key={filter.value}
              type="button"
              className={`ct-stage ${stageFilter === filter.value ? "active" : ""}`}
              data-tone={filter.tone}
              aria-pressed={stageFilter === filter.value}
              onClick={() => setStageFilter(filter.value)}
            >
              <span className="ct-stage-count">{compactNumber(Number(metrics?.[filter.metric] ?? 0))}</span>
              <span className="ct-stage-label">{filter.label}</span>
            </button>
          ))}
        </section>

        <div className="ct-secondary">
          <div className="ct-manual-segment" role="tablist" aria-label="Manual reply status" hidden={stageFilter !== "needs_human"}>
            <button type="button" className={`ct-manual-btn ${manualReplyFilter === "" ? "active" : ""}`} onClick={() => setManualReplyFilter("")}>All manual</button>
            <button type="button" className={`ct-manual-btn ${manualReplyFilter === "needs_reply" ? "active" : ""}`} onClick={() => setManualReplyFilter("needs_reply")}>Needs answer</button>
            <button type="button" className={`ct-manual-btn ${manualReplyFilter === "answered" ? "active" : ""}`} onClick={() => setManualReplyFilter("answered")}>Answered</button>
          </div>

          <div className="ct-strategy-filter" role="group" aria-label="Strategy filter">
            {strategyStats.length ? (
              <>
                <button
                  type="button"
                  className={`ct-strategy-filter-btn ${!strategyFilter.step && !strategyFilter.strategyId ? "active" : ""}`}
                  onClick={() => setStrategyFilter({ step: "", strategyId: "" })}
                >
                  All strategies
                </button>
                {strategyStats.map((item) => {
                  const active = item.step === strategyFilter.step && item.strategy_id === strategyFilter.strategyId;
                  return (
                    <button
                      type="button"
                      className={`ct-strategy-filter-btn ${active ? "active" : ""}`}
                      key={`${item.step}:${item.strategy_id}`}
                      onClick={() => setStrategyFilter({ step: item.step, strategyId: item.strategy_id })}
                    >
                      {formatStrategyLabel(item.step)}: {item.strategy_label || formatStrategyLabel(item.strategy_id)}
                    </button>
                  );
                })}
              </>
            ) : null}
          </div>

          <p className="ct-secondary-note">
            {totalCount ? `${visibleCount} of ${totalCount} ${totalCount === 1 ? "lead" : "leads"}` : "No leads yet"}
          </p>
        </div>

        <div className="ct-workspace">
          <aside className="ct-leads">
            <div className="ct-leads-head">
              <h3>Leads</h3>
              <p className="ct-leads-summary">{visibleCount ? `${visibleCount} ${visibleCount === 1 ? "lead" : "leads"}` : "No matches"}</p>
            </div>
            <LeadList
              leads={leadList?.leads ?? []}
              selectedLeadId={selectedLeadId}
              loading={loading}
              onSelect={setSelectedLeadId}
            />
          </aside>

          <section className="ct-detail">
            <LeadDetailHeader
              lead={selectedLead}
              actionBusy={actionBusy}
              onOpenSend={() => {
                setSendKind("custom");
                setShowSendModal(true);
              }}
              onMarkAnswered={() => runAction("mark-answered")}
              onToggleClosed={() => runAction(selectedLead?.stage === "closed" ? "reopen" : "close")}
              onDelete={deleteLead}
            />

            <PausedBanner lead={selectedLead} actionBusy={actionBusy} onResume={resumeAutomation} />

            <div className="ct-tabs" role="tablist" aria-label="Lead detail sections">
              {(["messages", "events", "strategies"] as DetailTab[]).map((tab) => (
                <button
                  key={tab}
                  type="button"
                  className={`ct-tab ${activeTab === tab ? "active" : ""}`}
                  role="tab"
                  aria-selected={activeTab === tab}
                  onClick={() => setActiveTab(tab)}
                >
                  {humanize(tab)}
                </button>
              ))}
            </div>

            <div className="ct-panes">
              <section className={`ct-pane ${activeTab === "messages" ? "active" : ""}`}>
                <MessageTimeline messages={detail?.messages ?? []} loading={detailLoading} hasLead={Boolean(selectedLead)} />
              </section>

              <section className={`ct-pane ${activeTab === "events" ? "active" : ""}`}>
                <EventTimeline events={detail?.events ?? []} loading={detailLoading} hasLead={Boolean(selectedLead)} />
              </section>

              <section className={`ct-pane ${activeTab === "strategies" ? "active" : ""}`}>
                <LeadStrategies messages={detail?.messages ?? []} loading={detailLoading} hasLead={Boolean(selectedLead)} />
              </section>
            </div>

            <ManualDock
              disabled={!selectedLead || Boolean(actionBusy)}
              value={manualText}
              onChange={setManualText}
              onSubmit={submitSendModal}
            />
          </section>
        </div>
      </div>

      {showConfig ? (
        <ConfigDrawer
          config={config}
          runtime={runtime}
          strategyStats={strategyStats}
          saving={actionBusy === "config"}
          onClose={() => setShowConfig(false)}
          onSave={saveConfig}
        />
      ) : null}

      {showSendModal ? (
        <SendModal
          kind={sendKind}
          text={manualText}
          busy={actionBusy === "send-modal"}
          onKindChange={setSendKind}
          onTextChange={setManualText}
          onClose={() => setShowSendModal(false)}
          onSubmit={submitSendModal}
        />
      ) : null}
    </section>
  );
}

function LeadList({
  leads,
  selectedLeadId,
  loading,
  onSelect,
}: {
  leads: LeadSummary[];
  selectedLeadId: string | null;
  loading: boolean;
  onSelect: (leadId: string) => void;
}) {
  if (loading && !leads.length) {
    return <div className="ct-leads-list"><p className="ct-empty">Loading leads...</p></div>;
  }

  if (!leads.length) {
    return <div className="ct-leads-list"><p className="ct-empty">No leads match the current filters.</p></div>;
  }

  return (
    <div className="ct-leads-list">
      {leads.map((lead) => {
        const tone = leadTone(lead);
        const turn = manualTurn(lead);
        const strategyTag = strategyTagForLead(lead);
        return (
          <button
            type="button"
            className={`ct-lead ${lead.id === selectedLeadId ? "active" : ""}`}
            key={lead.id}
            onClick={() => onSelect(lead.id)}
          >
            <div className="ct-lead-avatar" data-tone={tone}>{monogram(lead.full_name || lead.phone || "CT")}</div>
            <div className="ct-lead-body">
              <div className="ct-lead-top">
                <h4 className="ct-lead-name">{lead.full_name || lead.phone || "Lead"}</h4>
                <div className="ct-lead-tags">
                  <span className="ct-lead-stage" data-tone={tone}>{formatStageLabel(lead.stage)}</span>
                  {strategyTag ? <span className="ct-lead-strategy-tag">{strategyTag}</span> : null}
                  {turn ? <span className={`ct-lead-turn ${turn}`}>{turn === "needs_reply" ? "Needs reply" : "Answered"}</span> : null}
                </div>
              </div>
              <div className="ct-lead-meta">
                <span className="ct-lead-meta-main">{lead.phone || "-"}</span>
                <span className="ct-lead-time">{relativeTime(lastInteractionAt(lead))}</span>
              </div>
              <p className="ct-lead-preview">{leadPreview(lead)}</p>
            </div>
          </button>
        );
      })}
    </div>
  );
}

function LeadDetailHeader({
  lead,
  actionBusy,
  onOpenSend,
  onMarkAnswered,
  onToggleClosed,
  onDelete,
}: {
  lead: LeadSummary | null;
  actionBusy: string | null;
  onOpenSend: () => void;
  onMarkAnswered: () => void;
  onToggleClosed: () => void;
  onDelete: () => void;
}) {
  const closed = lead?.stage === "closed";
  const canMarkAnswered = lead?.manual_reply_status === "needs_reply" && !closed;

  return (
    <header className="ct-detail-head">
      <div className="ct-detail-head-main">
        <div className="ct-detail-avatar">{lead ? monogram(lead.full_name || lead.phone || "CT") : "CT"}</div>
        <div className="ct-detail-head-copy">
          <p className="ct-detail-kicker">{lead ? formatStageLabel(lead.stage) : "Select a lead"}</p>
          <h3>{lead?.full_name || lead?.phone || "No lead selected"}</h3>
          <p className="ct-detail-meta">
            {lead ? [lead.phone || "-", lead.email || "-", lead.platform || "-", lead.external_lead_id || "-"].join(" · ") : "Open a lead to inspect messages, automation events, and manual controls."}
          </p>
        </div>
      </div>
      <div className="ct-detail-head-actions">
        <button type="button" className="ct-btn ct-btn-primary" disabled={!lead || closed || Boolean(actionBusy)} onClick={onOpenSend}>Send message...</button>
        {canMarkAnswered ? (
          <button type="button" className="ct-btn ct-btn-ghost" disabled={Boolean(actionBusy)} onClick={onMarkAnswered}>Mark answered</button>
        ) : null}
        <button type="button" className={`ct-btn ct-btn-ghost ${closed ? "" : "btn-destructive"}`} disabled={!lead || Boolean(actionBusy)} onClick={onToggleClosed}>
          {closed ? "Reopen lead" : "Close lead"}
        </button>
        <button type="button" className="ct-btn ct-btn-ghost btn-destructive" disabled={!lead || Boolean(actionBusy)} onClick={onDelete}>Delete chat</button>
      </div>
    </header>
  );
}

function PausedBanner({
  lead,
  actionBusy,
  onResume,
}: {
  lead: LeadSummary | null;
  actionBusy: string | null;
  onResume: () => void;
}) {
  const closed = lead?.stage === "closed";
  const paused = Boolean(lead?.automation_paused);
  if (!lead || (!closed && !paused)) {
    return null;
  }

  return (
    <div className="ct-paused-banner">
      <div className="ct-paused-copy">
        <strong>{closed ? "Lead closed" : "Automation paused"}</strong>
        <span>
          {closed
            ? `Closed ${lead.closed_at ? relativeTime(lead.closed_at) : "just now"}. Reopen to continue with this lead.`
            : lead.automation_paused_reason
              ? `Paused by operator (${humanize(lead.automation_paused_reason)}). Resume to let the bot continue.`
              : "The bot won't send anything until you resume."}
        </span>
      </div>
      {!closed ? (
        <button type="button" className="ct-btn ct-btn-ghost" disabled={!paused || Boolean(actionBusy)} onClick={onResume}>Resume automation</button>
      ) : null}
    </div>
  );
}

function MessageTimeline({ messages, loading, hasLead }: { messages: MessageItem[]; loading: boolean; hasLead: boolean }) {
  if (!hasLead) {
    return <p className="empty-note">Select a lead from the list.</p>;
  }
  if (loading && !messages.length) {
    return <p className="empty-note">Loading messages...</p>;
  }
  if (!messages.length) {
    return <p className="empty-note">No messages for this lead yet.</p>;
  }

  return (
    <div className="ct-timeline">
      {messages.map((message) => {
        const direction = message.from_me ? "outbound" : "inbound";
        const meta = [
          shortDate(message.created_at),
          message.sequence_step,
          message.strategy_label || (message.strategy_id ? formatStrategyLabel(message.strategy_id) : ""),
          message.media_type,
          message.from_me ? message.delivery_status : "",
        ].filter(Boolean);
        return (
          <div className={`crm-message-shell ${direction}`} key={message.id}>
            <div className="crm-message-rail">
              <span className={`crm-message-dot ${direction}`} />
            </div>
            <article className={`crm-message-card ${direction} ${message.delivery_status === "undelivered" ? "pending" : ""}`}>
              <div className="crm-message-meta">
                <div className="crm-message-eyebrow">
                  <span className={`crm-message-author ${direction}`}>{message.from_me ? "Bot / Operator" : "Lead"}</span>
                  <span>{meta.join(" · ")}</span>
                </div>
              </div>
              <p className="crm-message-body">{message.text || ""}</p>
            </article>
          </div>
        );
      })}
    </div>
  );
}

function EventTimeline({ events, loading, hasLead }: { events: EventItem[]; loading: boolean; hasLead: boolean }) {
  if (!hasLead) {
    return <p className="empty-note">Events will appear when you select a lead.</p>;
  }
  if (loading && !events.length) {
    return <p className="empty-note">Loading events...</p>;
  }
  if (!events.length) {
    return <p className="empty-note">No automation events yet.</p>;
  }

  return (
    <div className="ct-event-timeline">
      {events.map((event) => (
        <article className="ct-event-card" key={event.id}>
          <div className="ct-event-head">
            <strong>{humanize(event.event_type || "event")}</strong>
            <time>{shortDate(event.created_at)}</time>
          </div>
          <p>{event.summary || ""}</p>
        </article>
      ))}
    </div>
  );
}

function LeadStrategies({ messages, loading, hasLead }: { messages: MessageItem[]; loading: boolean; hasLead: boolean }) {
  if (!hasLead) {
    return <p className="empty-note">Strategies will appear when you select a lead.</p>;
  }
  if (loading && !messages.length) {
    return <p className="empty-note">Loading strategies...</p>;
  }

  const groups = new Map<string, { step: string; strategyId: string; strategyLabel: string; messages: MessageItem[] }>();
  messages
    .filter((message) => message.from_me && message.strategy_id)
    .forEach((message) => {
      const key = `${message.strategy_step || ""}:${message.strategy_id || ""}`;
      const group = groups.get(key) ?? {
        step: message.strategy_step || "",
        strategyId: message.strategy_id || "",
        strategyLabel: message.strategy_label || formatStrategyLabel(message.strategy_id),
        messages: [],
      };
      group.messages.push(message);
      groups.set(key, group);
    });

  if (!groups.size) {
    return <p className="empty-note">No strategy assignment for this lead yet.</p>;
  }

  return (
    <div className="ct-lead-strategies">
      {[...groups.values()].map((group) => {
        const sent = group.messages.filter((message) => ["sent", "delivered"].includes(String(message.delivery_status || "").toLowerCase())).length;
        const delivered = group.messages.filter((message) => String(message.delivery_status || "").toLowerCase() === "delivered").length;
        const mediaTypes = [...new Set(group.messages.map((message) => message.media_type).filter(Boolean))];
        return (
          <article className="ct-lead-strategy-card" key={`${group.step}:${group.strategyId}`}>
            <div className="ct-lead-strategy-head">
              <div>
                <strong>{group.strategyLabel}</strong>
                <span>{formatStrategyLabel(group.step)}</span>
              </div>
              <span className="ct-strategy-chip">{sent}/{group.messages.length} sent</span>
            </div>
            <div className="ct-lead-strategy-meta">
              <span>{delivered} delivered</span>
              {mediaTypes.map((mediaType) => <span key={mediaType}>{mediaType}</span>)}
            </div>
            <ul>
              {group.messages.map((message) => (
                <li key={message.id}>
                  <span>{message.sequence_step || "message"}</span>
                  <strong>{message.delivery_status || "pending"}</strong>
                </li>
              ))}
            </ul>
          </article>
        );
      })}
    </div>
  );
}

function ManualDock({
  disabled,
  value,
  onChange,
  onSubmit,
}: {
  disabled: boolean;
  value: string;
  onChange: (value: string) => void;
  onSubmit: (event: FormEvent<HTMLFormElement>) => void;
}) {
  return (
    <form className="ct-manual" onSubmit={onSubmit}>
      <div className="ct-manual-head">
        <span className="ct-manual-lock">Manual outbound</span>
        <p className="ct-manual-hint">Sending a custom message pauses automation for this lead.</p>
      </div>
      <textarea
        value={value}
        onChange={(event) => onChange(event.target.value)}
        disabled={disabled}
        rows={3}
        placeholder="Write the WhatsApp message to send..."
      />
      <div className="ct-manual-actions">
        <button type="submit" className="ct-btn ct-btn-primary" disabled={disabled || !value.trim()}>Send and pause automation</button>
      </div>
    </form>
  );
}

function ConfigDrawer({
  config,
  runtime,
  strategyStats,
  saving,
  onClose,
  onSave,
}: {
  config: ContadoresConfig | null;
  runtime: RuntimeSettings | null;
  strategyStats: StrategyStatsItem[];
  saving: boolean;
  onClose: () => void;
  onSave: (config: Partial<ContadoresConfig>) => Promise<void>;
}) {
  const [draft, setDraft] = useState({
    enabled: true,
    loom_url: "",
    calendly_base_url: "",
    alert_emails: "",
    strategy_weights: {} as StrategyWeights,
  });
  const [draftReady, setDraftReady] = useState(false);

  useEffect(() => {
    if (!config || draftReady) {
      return;
    }
    const strategyWeights: StrategyWeights = {};
    for (const item of strategyStats) {
      strategyWeights[item.step] = strategyWeights[item.step] ?? {};
      strategyWeights[item.step][item.strategy_id] =
        config.strategy_weights?.[item.step]?.[item.strategy_id] ?? item.weight ?? 0;
    }
    setDraft({
      enabled: config.enabled,
      loom_url: config.loom_url,
      calendly_base_url: config.calendly_base_url,
      alert_emails: config.alert_emails.join(", "),
      strategy_weights: strategyWeights,
    });
    setDraftReady(true);
  }, [config, draftReady, strategyStats]);

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    await onSave({
      enabled: draft.enabled,
      loom_url: draft.loom_url,
      calendly_base_url: draft.calendly_base_url,
      alert_emails: draft.alert_emails.split(",").map((item) => item.trim()).filter(Boolean),
      strategy_weights: draft.strategy_weights,
    });
  }

  function updateStrategyWeight(item: StrategyStatsItem, value: string) {
    const nextWeight = Math.min(100, Math.max(0, Number.parseInt(value || "0", 10) || 0));
    setDraft((current) => ({
      ...current,
      strategy_weights: {
        ...current.strategy_weights,
        [item.step]: {
          ...(current.strategy_weights[item.step] ?? {}),
          [item.strategy_id]: nextWeight,
        },
      },
    }));
  }

  return (
    <aside className="ct-drawer open" aria-hidden="false" aria-label="Rollout controls">
      <button className="ct-drawer-overlay" type="button" onClick={onClose} aria-label="Close rollout controls" />
      <form className="ct-drawer-panel" role="dialog" aria-modal="false" aria-labelledby="ctDrawerTitle" onSubmit={handleSubmit}>
        <header className="ct-drawer-head">
          <div>
            <p className="ct-drawer-kicker">Automation Config</p>
            <h3 id="ctDrawerTitle">Rollout Controls</h3>
            <p className="ct-drawer-note">
              Sheet: {config?.last_sheet_sync_status || "idle"} · Mode: {runtime?.source_mode ?? "-"} · Ready: {runtime?.ready ? "yes" : "review"}
            </p>
          </div>
          <button type="button" className="ct-icon-btn" onClick={onClose}>Close</button>
        </header>
        <div className="ct-drawer-body">
          <label className="ct-field ct-field-toggle">
            <span>Enabled</span>
            <div className="ct-toggle-row">
              <input type="checkbox" checked={draft.enabled} onChange={(event) => setDraft((current) => ({ ...current, enabled: event.target.checked }))} />
              <p className="ct-field-hint">When disabled, no automatic opener/automation runs.</p>
            </div>
          </label>
          <label className="ct-field">
            <span>Loom URL</span>
            <input value={draft.loom_url} onChange={(event) => setDraft((current) => ({ ...current, loom_url: event.target.value }))} />
          </label>
          <label className="ct-field">
            <span>Calendly Base URL</span>
            <input value={draft.calendly_base_url} onChange={(event) => setDraft((current) => ({ ...current, calendly_base_url: event.target.value }))} />
          </label>
          <label className="ct-field">
            <span>Alert Emails</span>
            <input value={draft.alert_emails} onChange={(event) => setDraft((current) => ({ ...current, alert_emails: event.target.value }))} />
          </label>
          <StrategyStatsPanel
            items={strategyStats}
            weights={draft.strategy_weights}
            onWeightChange={updateStrategyWeight}
          />
        </div>
        <footer className="ct-drawer-foot">
          <button type="submit" className="ct-btn ct-btn-primary" disabled={saving || !config}>{saving ? "Saving..." : "Save Config"}</button>
        </footer>
      </form>
    </aside>
  );
}

function StrategyStatsPanel({
  items,
  weights,
  onWeightChange,
}: {
  items: StrategyStatsItem[];
  weights: StrategyWeights;
  onWeightChange: (item: StrategyStatsItem, value: string) => void;
}) {
  if (!items.length) {
    return (
      <section className="ct-strategy-panel" aria-label="Strategy performance">
        <div className="ct-strategy-head">
          <span>Strategies</span>
          <strong>No data</strong>
        </div>
      </section>
    );
  }

  return (
    <section className="ct-strategy-panel" aria-label="Strategy performance">
      <div className="ct-strategy-head">
        <span>Strategies</span>
        <strong>{items.length} active</strong>
      </div>
      <div className="ct-strategy-list">
        {items.map((item) => (
          <article className="ct-strategy-row" key={`${item.step}:${item.strategy_id}`}>
            <div>
              <strong>{item.strategy_label || formatStrategyLabel(item.strategy_id)}</strong>
              <span>{formatStrategyLabel(item.step)} · current weight</span>
            </div>
            <label className="ct-strategy-weight">
              <input
                type="number"
                min="0"
                max="100"
                value={weights[item.step]?.[item.strategy_id] ?? item.weight}
                onChange={(event) => onWeightChange(item, event.target.value)}
              />
              <span>%</span>
            </label>
            <div className="ct-strategy-metrics">
              <span>{item.assigned} assigned</span>
              <span>{formatRate(item.calendly_rate)} Calendly</span>
              <span>{formatRate(item.booked_rate)} booked</span>
            </div>
          </article>
        ))}
      </div>
    </section>
  );
}

function SendModal({
  kind,
  text,
  busy,
  onKindChange,
  onTextChange,
  onClose,
  onSubmit,
}: {
  kind: SendKind;
  text: string;
  busy: boolean;
  onKindChange: (kind: SendKind) => void;
  onTextChange: (value: string) => void;
  onClose: () => void;
  onSubmit: (event: FormEvent<HTMLFormElement>) => void;
}) {
  const pausesAutomation = kind !== "send-calendly";

  return (
    <div className="ct-modal open" aria-hidden="false">
      <button className="ct-modal-overlay" type="button" onClick={onClose} aria-label="Close send message" />
      <form className="ct-modal-panel" role="dialog" aria-modal="true" aria-labelledby="ctSendModalTitle" onSubmit={onSubmit}>
        <header className="ct-modal-head">
          <h3 id="ctSendModalTitle">Send message</h3>
          <button type="button" className="ct-icon-btn" onClick={onClose}>Close</button>
        </header>
        <div className="ct-modal-body">
          <p className="ct-modal-warning">
            <strong>Heads up:</strong> {pausesAutomation ? "sending this pauses the bot for this lead. You can resume automation after." : "sending Calendly marks the lead as Calendly sent and clears the manual handoff."}
          </p>

          <fieldset className="ct-send-options">
            <legend className="ct-sr-only">Message type</legend>
            {sendOptions.map((option) => (
              <label className="ct-send-option" key={option.value}>
                <input
                  type="radio"
                  name="ctSendKind"
                  value={option.value}
                  checked={kind === option.value}
                  onChange={() => onKindChange(option.value)}
                />
                <div>
                  <strong>{option.title}</strong>
                  <span>{option.help}</span>
                </div>
              </label>
            ))}
          </fieldset>

          <label className="ct-modal-field" hidden={kind !== "custom"}>
            <span>Custom message</span>
            <textarea
              value={text}
              onChange={(event) => onTextChange(event.target.value)}
              rows={4}
              placeholder="Write the WhatsApp message to send..."
            />
          </label>
        </div>
        <footer className="ct-modal-foot">
          <button type="button" className="ct-btn ct-btn-ghost" onClick={onClose}>Cancel</button>
          <button type="submit" className="ct-btn ct-btn-primary" disabled={busy || (kind === "custom" && !text.trim())}>
            {busy ? "Sending..." : pausesAutomation ? "Send and pause automation" : "Send and mark Calendly sent"}
          </button>
        </footer>
      </form>
    </div>
  );
}

function formatStageLabel(stage: LeadStage | string | null | undefined): string {
  const labels: Record<string, string> = {
    awaiting_initial_reply: "Opener sent",
    awaiting_video_reply: "Loom sent",
    calendly_sent: "Calendly sent",
    needs_human: "Manual",
    booked: "Booked",
    closed: "Closed",
    archived: "Archived",
  };
  return labels[String(stage || "")] ?? humanize(stage || "Lead");
}

function formatStrategyLabel(value: string | null | undefined): string {
  return humanize(value || "Strategy");
}

function formatRate(value: number): string {
  if (!Number.isFinite(value) || value <= 0) {
    return "0%";
  }
  return `${Math.round(value * 100)}%`;
}

function leadTone(lead: LeadSummary): "accent" | "warn" | "success" | "muted" {
  if (lead.stage === "needs_human") {
    return "warn";
  }
  if (lead.stage === "booked" || lead.stage === "calendly_sent") {
    return "success";
  }
  if (lead.stage === "closed" || lead.stage === "archived") {
    return "muted";
  }
  return "accent";
}

function manualTurn(lead: LeadSummary): "" | "needs_reply" | "answered" {
  if (lead.stage !== "needs_human") {
    return "";
  }
  if (lead.manual_reply_status === "needs_reply" || lead.manual_reply_status === "answered") {
    return lead.manual_reply_status;
  }
  return "";
}

function strategyTagForLead(lead: LeadSummary): string {
  const assignments = lead.strategy_assignments ?? [];
  const loomAssignment = assignments.find((assignment) => assignment.step === "loom") ?? assignments[0];
  return loomAssignment?.strategy_label || "";
}

function leadPreview(lead: LeadSummary): string {
  if (lead.stage === "closed") {
    return "Lead marked as closed.";
  }
  if (lead.last_classification_reason) {
    return truncate(lead.last_classification_reason, 120);
  }
  if (lead.booked_at) {
    return "Booked through Calendly or manually marked.";
  }
  return truncate(`${lead.platform || "-"} · ${lead.email || lead.phone || "-"}`, 120);
}

function monogram(value: string): string {
  return value
    .split(/\s+/)
    .filter(Boolean)
    .slice(0, 2)
    .map((part) => part[0]?.toUpperCase() ?? "")
    .join("") || "CT";
}

function truncate(value: string, maxLength: number): string {
  if (value.length <= maxLength) {
    return value;
  }
  return `${value.slice(0, maxLength - 1)}...`;
}
