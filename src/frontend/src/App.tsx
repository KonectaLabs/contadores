import { FormEvent, useCallback, useEffect, useMemo, useState } from "react";
import { apiFetch } from "./api";
import { compactNumber, humanize, lastInteractionAt, relativeTime, shortDate } from "./format";
import type {
  BulkActionResponse,
  ContadoresConfig,
  ContadoresMetrics,
  EventItem,
  FunnelDefinition,
  FunnelListResponse,
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
  { value: "send-manual-ping", title: "Manual ping", help: "Send the approved ping template to reopen WhatsApp." },
  { value: "send-opener", title: "Opener", help: "Queue the default opener template." },
  { value: "send-loom", title: "Loom sequence", help: "Queue the Loom video introduction messages." },
  { value: "send-video-check", title: "Video check", help: "Ask if they watched the Loom." },
  { value: "send-calendly", title: "Calendly sequence", help: "Share Calendly link and booking instructions." },
] as const;

type ManualReplyFilter = "" | "needs_reply" | "answered";
type DetailTab = "messages" | "events" | "strategies";
type SendKind = (typeof sendOptions)[number]["value"];
type BulkSendKind = SendKind;
type StrategyWeights = Record<string, Record<string, number>>;
type FunnelEditorMode = "create" | "edit";
type TemplateTextField = "opener_text" | "opener_followup_text" | "manual_ping_text";
type TemplateNameField = "opener_template_name" | "opener_followup_template_name" | "manual_ping_template_name";
type TemplateChoice = {
  label: string;
  templateId: string;
  text: string;
};
type QuickActionName =
  | "send-opener"
  | "send-manual-ping"
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
  const [funnels, setFunnels] = useState<FunnelDefinition[]>([]);
  const [funnelConfigPath, setFunnelConfigPath] = useState("");
  const [selectedFunnelId, setSelectedFunnelId] = useState("contadores");
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
  const [showFunnelEditor, setShowFunnelEditor] = useState(false);
  const [funnelEditorMode, setFunnelEditorMode] = useState<FunnelEditorMode>("edit");
  const [showSendModal, setShowSendModal] = useState(false);
  const [showBulkSendModal, setShowBulkSendModal] = useState(false);
  const [sendKind, setSendKind] = useState<SendKind>("custom");
  const [bulkSendKind, setBulkSendKind] = useState<BulkSendKind>("send-manual-ping");
  const [manualText, setManualText] = useState("");
  const [selectedLeadIds, setSelectedLeadIds] = useState<string[]>([]);
  const debouncedQuery = useDebouncedValue(query, 250);

  const metrics = leadList?.metrics;
  const config = leadList?.config ?? detail?.config ?? null;
  const selectedFunnel = funnels.find((funnel) => funnel.id === selectedFunnelId) ?? funnels[0] ?? null;
  const isContadoresFunnel = true;

  const selectedLead = useMemo(() => {
    if (detail?.lead.id === selectedLeadId) {
      return detail.lead;
    }
    if (!selectedLeadId || !leadList) {
      return null;
    }
    return leadList.leads.find((lead) => lead.id === selectedLeadId) ?? null;
  }, [detail, leadList, selectedLeadId]);
  const visibleLeadIds = useMemo(() => (leadList?.leads ?? []).map((lead) => lead.id), [leadList]);
  const selectedVisibleCount = selectedLeadIds.filter((leadId) => visibleLeadIds.includes(leadId)).length;
  const allVisibleSelected = visibleLeadIds.length > 0 && selectedVisibleCount === visibleLeadIds.length;

  const loadDashboard = useCallback(async () => {
    setError(null);
    const [runtimePayload, funnelPayload] = await Promise.all([
      apiFetch<RuntimeSettings>("/api/runtime"),
      apiFetch<FunnelListResponse>("/api/funnels"),
    ]);

    setRuntime(runtimePayload);
    setFunnels(funnelPayload.funnels ?? []);
    setFunnelConfigPath(funnelPayload.config_path || "");

    if (!selectedFunnelId || !funnelPayload.funnels.some((funnel) => funnel.id === selectedFunnelId)) {
      setSelectedFunnelId(funnelPayload.funnels[0]?.id ?? "contadores");
    }

    const activeFunnelId = funnelPayload.funnels.some((funnel) => funnel.id === selectedFunnelId)
      ? selectedFunnelId
      : funnelPayload.funnels[0]?.id ?? "contadores";
    const params = new URLSearchParams({ limit: "500", archived: "false", funnel_id: activeFunnelId });
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

    const [leadsPayload, strategyPayload] = await Promise.all([
      apiFetch<LeadListResponse>(`/api/contadores/leads?${params.toString()}`),
      apiFetch<StrategyStatsResponse>(`/api/contadores/strategy-stats?funnel_id=${encodeURIComponent(activeFunnelId)}`),
    ]);

    setLeadList(leadsPayload);
    setStrategyStats(strategyPayload.items ?? []);

    setSelectedLeadId((current) => {
      if (current && leadsPayload.leads.some((lead) => lead.id === current)) {
        return current;
      }
      return leadsPayload.leads[0]?.id ?? null;
    });
  }, [debouncedQuery, manualReplyFilter, selectedFunnelId, stageFilter, strategyFilter.step, strategyFilter.strategyId]);

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
    setSelectedLeadIds((current) => current.filter((leadId) => visibleLeadIds.includes(leadId)));
  }, [visibleLeadIds]);

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
    if (!selectedLeadId || !isContadoresFunnel) {
      setDetail(null);
      return;
    }
    setActiveTab("messages");
    loadDetail(selectedLeadId).catch((reason) => {
      setError(reason instanceof Error ? reason.message : "Could not load the lead.");
    });
  }, [isContadoresFunnel, loadDetail, selectedLeadId]);

  async function refreshAll() {
    setLoading(true);
    try {
      await loadDashboard();
      if (selectedLeadId && isContadoresFunnel) {
        await loadDetail(selectedLeadId);
      }
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Could not refresh funnels.");
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
        await queueCustomManualMessage(leadId, text);
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

  async function submitBulkSendModal(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const leadIds = selectedLeadIds.filter((leadId) => visibleLeadIds.includes(leadId));
    if (!leadIds.length) {
      return;
    }

    setActionBusy("bulk-send-modal");
    try {
      const payload = await apiFetch<BulkActionResponse>("/api/contadores/leads/bulk-action", {
        method: "POST",
        body: JSON.stringify({
          lead_ids: leadIds,
          action: bulkSendKind,
          text: bulkSendKind === "custom" ? manualText.trim() : null,
        }),
      });
      if (payload.failed) {
        setError(`${payload.succeeded} sent, ${payload.failed} failed. Check selection and funnel templates.`);
      }
      setShowBulkSendModal(false);
      setSelectedLeadIds([]);
      if (bulkSendKind === "custom") {
        setManualText("");
      }
      await loadDashboard();
      if (selectedLeadId && isContadoresFunnel) {
        await loadDetail(selectedLeadId);
      }
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Could not run the bulk action.");
    } finally {
      setActionBusy(null);
    }
  }

  async function submitManualDock(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const leadId = selectedLead?.id ?? selectedLeadId;
    const text = manualText.trim();
    if (!leadId || !text) {
      return;
    }

    setActionBusy("manual-dock");
    try {
      await queueCustomManualMessage(leadId, text);
      await loadDashboard();
      await loadDetail(leadId);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Could not send the message.");
    } finally {
      setActionBusy(null);
    }
  }

  async function queueCustomManualMessage(leadId: string, text: string) {
    await apiFetch<QuickActionResponse>(`/api/contadores/leads/${leadId}/messages/manual`, {
      method: "POST",
      body: JSON.stringify({ text }),
    });
    setManualText("");
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

  async function saveFunnel(nextFunnel: FunnelDefinition) {
    setActionBusy("funnel-config");
    try {
      const method = funnelEditorMode === "create" ? "POST" : "PUT";
      const path = funnelEditorMode === "create" ? "/api/funnels" : `/api/funnels/${nextFunnel.id}`;
      const saved = await apiFetch<FunnelDefinition>(path, {
        method,
        body: JSON.stringify(nextFunnel),
      });
      setSelectedFunnelId(saved.id);
      setShowFunnelEditor(false);
      await loadDashboard();
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Could not save funnel.");
    } finally {
      setActionBusy(null);
    }
  }

  function openCreateFunnel() {
    setFunnelEditorMode("create");
    setShowFunnelEditor(true);
  }

  function openEditFunnel() {
    setFunnelEditorMode("edit");
    setShowFunnelEditor(true);
  }

  function toggleLeadSelection(leadId: string) {
    setSelectedLeadIds((current) => (
      current.includes(leadId)
        ? current.filter((item) => item !== leadId)
        : [...current, leadId]
    ));
  }

  function toggleAllVisibleLeads() {
    setSelectedLeadIds(allVisibleSelected ? [] : visibleLeadIds);
  }

  const visibleCount = leadList?.leads.length ?? 0;
  const totalCount = metrics?.total ?? 0;
  const syncStatus = config?.last_sheet_sync_status
    ? `${config.last_sheet_sync_status} · ${config.last_sheet_sync_at ? relativeTime(config.last_sheet_sync_at) : "never"}`
    : isContadoresFunnel && runtime
      ? `${runtime.source_mode} mode`
      : selectedFunnel
        ? `${selectedFunnel.source_mode} mode`
        : "Sync idle";

  return (
    <section id="contadoresView" className="contadores-view" data-app="contadores">
      <header className="ct-topbar">
        <div className="ct-topbar-brand">
          <span className="ct-brand-mark" aria-hidden="true">{monogram(selectedFunnel?.label || "Funnels")}</span>
          <div className="ct-brand-copy">
            <p className="ct-brand-word">{selectedFunnel?.label || "Funnels"}</p>
            <span className={`ct-sync-badge ${config?.last_sheet_sync_status === "ok" ? "has-unread" : ""}`}>{syncStatus}</span>
          </div>
        </div>

        <nav className="ct-topbar-nav" aria-label="Backoffice sections">
          {funnels.map((funnel) => (
            <button
              key={funnel.id}
              type="button"
              className={`ct-nav-btn ${selectedFunnelId === funnel.id ? "active" : ""}`}
              onClick={() => setSelectedFunnelId(funnel.id)}
            >
              {funnel.label}
            </button>
          ))}
          <button type="button" className="ct-nav-btn ct-nav-add" onClick={openCreateFunnel}>+ Funnel</button>
        </nav>

        <div className="ct-topbar-tools">
          <label className="ct-search" hidden={!isContadoresFunnel}>
            <span className="ct-search-icon" aria-hidden="true" />
            <input
              value={query}
              onChange={(event) => setQuery(event.target.value)}
              type="text"
              placeholder="Search name, phone, email, lead id"
              autoComplete="off"
            />
          </label>
          <button type="button" className="ct-icon-btn" onClick={openEditFunnel} disabled={!selectedFunnel}>Funnel</button>
          {isContadoresFunnel ? (
            <button type="button" className="ct-icon-btn" onClick={() => setShowConfig(true)}>Runtime</button>
          ) : null}
          <button type="button" className="ct-icon-btn" onClick={refreshAll} disabled={loading}>Refresh</button>
        </div>
      </header>

      {error ? (
        <div className="ct-error" role="alert">
          <span>{error}</span>
          <button type="button" className="ct-icon-btn" onClick={() => setError(null)}>Dismiss</button>
        </div>
      ) : null}

      {!isContadoresFunnel ? (
        <FunnelSetupView
          funnel={selectedFunnel}
          configPath={funnelConfigPath}
          onEdit={openEditFunnel}
        />
      ) : (
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
            <div className="ct-bulk-toolbar">
              <label className="ct-bulk-check">
                <input
                  type="checkbox"
                  checked={allVisibleSelected}
                  disabled={!visibleLeadIds.length}
                  onChange={toggleAllVisibleLeads}
                />
                <span>{allVisibleSelected ? "All visible selected" : "Select visible"}</span>
              </label>
              <button
                type="button"
                className="ct-btn ct-btn-ghost"
                disabled={!selectedLeadIds.length || Boolean(actionBusy)}
                onClick={() => {
                  setBulkSendKind("send-manual-ping");
                  setShowBulkSendModal(true);
                }}
              >
                Bulk action
              </button>
            </div>
            <LeadList
              leads={leadList?.leads ?? []}
              selectedLeadId={selectedLeadId}
              selectedLeadIds={selectedLeadIds}
              loading={loading}
              onSelect={setSelectedLeadId}
              onToggleSelected={toggleLeadSelection}
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
              onSubmit={submitManualDock}
            />
          </section>
        </div>
      </div>
      )}

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

      {showFunnelEditor ? (
        <FunnelEditorDrawer
          mode={funnelEditorMode}
          funnel={funnelEditorMode === "edit" ? selectedFunnel : null}
          saving={actionBusy === "funnel-config"}
          onClose={() => setShowFunnelEditor(false)}
          onSave={saveFunnel}
        />
      ) : null}

      {showSendModal ? (
        <SendModal
          kind={sendKind}
          text={manualText}
          funnel={selectedFunnel}
          busy={actionBusy === "send-modal"}
          onKindChange={setSendKind}
          onTextChange={setManualText}
          onClose={() => setShowSendModal(false)}
          onSubmit={submitSendModal}
        />
      ) : null}

      {showBulkSendModal ? (
        <BulkSendModal
          kind={bulkSendKind}
          text={manualText}
          funnel={selectedFunnel}
          selectedCount={selectedLeadIds.length}
          busy={actionBusy === "bulk-send-modal"}
          onKindChange={setBulkSendKind}
          onTextChange={setManualText}
          onClose={() => setShowBulkSendModal(false)}
          onSubmit={submitBulkSendModal}
        />
      ) : null}
    </section>
  );
}

function FunnelSetupView({
  funnel,
  configPath,
  onEdit,
}: {
  funnel: FunnelDefinition | null;
  configPath: string;
  onEdit: () => void;
}) {
  if (!funnel) {
    return (
      <div className="ct-funnel-setup">
        <p className="ct-empty">No funnel selected.</p>
      </div>
    );
  }

  const mp4Strategy = funnel.strategies.find((strategy) => strategy.delivery === "video");
  const linkStrategy = funnel.strategies.find((strategy) => strategy.delivery === "link");

  return (
    <section className="ct-funnel-setup" aria-label="Funnel setup">
      <header className="ct-funnel-hero">
        <div>
          <p className="ct-detail-kicker">Niche funnel</p>
          <h2>{funnel.label}</h2>
          <p>
            This funnel is configured but does not have a dedicated lead workspace yet. Edit the funnel copy,
            sheet source, video strategy, and Calendly step here; Contadores remains the live operational section.
          </p>
        </div>
        <button type="button" className="ct-btn ct-btn-primary" onClick={onEdit}>Edit funnel</button>
      </header>

      <div className="ct-funnel-grid">
        <article className="ct-funnel-card">
          <span>Source</span>
          <strong>{funnel.source_mode}</strong>
          <p>{funnel.sheet_url ? "Sheet connected" : "No sheet URL yet"}{funnel.sheet_gid ? ` · gid ${funnel.sheet_gid}` : ""}</p>
        </article>
        <article className="ct-funnel-card">
          <span>Testing</span>
          <strong>{funnel.test_phone || "No phone"}</strong>
          <p>{funnel.test_name || "Synthetic lead name not set"}</p>
        </article>
        <article className="ct-funnel-card">
          <span>Video</span>
          <strong>{mp4Strategy?.media_path ? "WhatsApp MP4" : linkStrategy ? "Link" : "Not configured"}</strong>
          <p>{mp4Strategy?.media_path || funnel.loom_url || "-"}</p>
        </article>
        <article className="ct-funnel-card">
          <span>Calendly</span>
          <strong>{funnel.calendly_base_url ? "Ready" : "Missing"}</strong>
          <p>{funnel.calendly_base_url || "-"}</p>
        </article>
      </div>

      <section className="ct-funnel-copy">
        <h3>Sequence copy</h3>
        <div className="ct-copy-row">
          <span>Opener template</span>
          <p>{funnel.opener_template_name || "No template"}</p>
          <blockquote>{funnel.opener_text}</blockquote>
        </div>
        <div className="ct-copy-row">
          <span>Manual ping template</span>
          <p>{funnel.manual_ping_template_name || "No template"}</p>
          <blockquote>{funnel.manual_ping_text}</blockquote>
        </div>
        <div className="ct-copy-row">
          <span>Video intro</span>
          <blockquote>{funnel.loom_intro_text}</blockquote>
        </div>
        <div className="ct-copy-row">
          <span>Calendly handoff</span>
          <blockquote>{funnel.calendly_intro_text}</blockquote>
        </div>
      </section>

      <p className="ct-config-path">Config file: {configPath || "data/funnels.json"}</p>
    </section>
  );
}

function FunnelEditorDrawer({
  mode,
  funnel,
  saving,
  onClose,
  onSave,
}: {
  mode: FunnelEditorMode;
  funnel: FunnelDefinition | null;
  saving: boolean;
  onClose: () => void;
  onSave: (funnel: FunnelDefinition) => Promise<void>;
}) {
  const [draft, setDraft] = useState<FunnelDefinition>(() => funnel ?? buildBlankFunnel());
  const videoStrategy = draft.strategies.find((strategy) => strategy.delivery === "video") ?? draft.strategies[1];

  function update<K extends keyof FunnelDefinition>(key: K, value: FunnelDefinition[K]) {
    setDraft((current) => ({ ...current, [key]: value }));
  }

  function updateStrategyMediaPath(value: string) {
    setDraft((current) => ({
      ...current,
      strategies: current.strategies.map((strategy) => (
        strategy.delivery === "video" ? { ...strategy, media_path: value.trim() || null } : strategy
      )),
    }));
  }

  function updateStrategyWeight(strategyId: string, value: string) {
    const weight = Math.min(100, Math.max(0, Number.parseInt(value || "0", 10) || 0));
    setDraft((current) => ({
      ...current,
      strategies: current.strategies.map((strategy) => (
        strategy.id === strategyId ? { ...strategy, weight } : strategy
      )),
    }));
  }

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    await onSave({
      ...draft,
      id: slugifyClient(draft.id || draft.label),
      alert_emails: draft.alert_emails.map((item) => item.trim()).filter(Boolean),
      sheet_url: draft.sheet_url?.trim() || null,
      sheet_gid: draft.sheet_gid?.trim() || null,
      sheet_source_filter: draft.sheet_source_filter?.trim() || null,
      opener_template_name: draft.opener_template_name?.trim() || null,
      opener_followup_template_name: draft.opener_followup_template_name?.trim() || null,
      manual_ping_template_name: draft.manual_ping_template_name?.trim() || null,
      manual_ping_text: draft.manual_ping_text.trim(),
    });
  }

  return (
    <aside className="ct-drawer open" aria-hidden="false" aria-label="Funnel editor">
      <button className="ct-drawer-overlay" type="button" onClick={onClose} aria-label="Close funnel editor" />
      <form className="ct-drawer-panel wide" role="dialog" aria-modal="false" aria-labelledby="ctFunnelDrawerTitle" onSubmit={submit}>
        <header className="ct-drawer-head">
          <div>
            <p className="ct-drawer-kicker">{mode === "create" ? "New funnel" : "Funnel config"}</p>
            <h3 id="ctFunnelDrawerTitle">{mode === "create" ? "Add Niche Funnel" : draft.label}</h3>
            <p className="ct-drawer-note">Saved to the shared funnel config file used by the UI and Codex.</p>
          </div>
          <button type="button" className="ct-icon-btn" onClick={onClose}>Close</button>
        </header>

        <div className="ct-drawer-body">
          <div className="ct-field-grid">
            <label className="ct-field">
              <span>Funnel ID</span>
              <input value={draft.id} disabled={mode === "edit"} onChange={(event) => update("id", slugifyClient(event.target.value))} />
            </label>
            <label className="ct-field">
              <span>Label</span>
              <input value={draft.label} onChange={(event) => update("label", event.target.value)} />
            </label>
          </div>

          <label className="ct-field ct-field-toggle">
            <span>Enabled</span>
            <div className="ct-toggle-row">
              <input type="checkbox" checked={draft.enabled} onChange={(event) => update("enabled", event.target.checked)} />
              <p className="ct-field-hint">Disabled funnels stay visible but should not run automation.</p>
            </div>
          </label>

          <div className="ct-field-grid">
            <label className="ct-field">
              <span>Source Mode</span>
              <select value={draft.source_mode} onChange={(event) => update("source_mode", event.target.value as FunnelDefinition["source_mode"])}>
                <option value="testing">testing</option>
                <option value="live">live</option>
              </select>
            </label>
            <label className="ct-field">
              <span>Sheet Poll Seconds</span>
              <input type="number" min="30" value={draft.sheet_poll_seconds} onChange={(event) => update("sheet_poll_seconds", Number(event.target.value) || 30)} />
            </label>
          </div>

          <div className="ct-field-grid">
            <label className="ct-field">
              <span>Test Phone</span>
              <input value={draft.test_phone} onChange={(event) => update("test_phone", event.target.value)} />
            </label>
            <label className="ct-field">
              <span>Test Name</span>
              <input value={draft.test_name} onChange={(event) => update("test_name", event.target.value)} />
            </label>
          </div>

          <label className="ct-field">
            <span>Sheet URL</span>
            <input value={draft.sheet_url ?? ""} onChange={(event) => update("sheet_url", event.target.value || null)} />
          </label>

          <div className="ct-field-grid">
            <label className="ct-field">
              <span>Sheet GID</span>
              <input value={draft.sheet_gid ?? ""} onChange={(event) => update("sheet_gid", event.target.value || null)} />
            </label>
            <label className="ct-field">
              <span>Sheet Source Filter</span>
              <input value={draft.sheet_source_filter ?? ""} onChange={(event) => update("sheet_source_filter", event.target.value || null)} />
            </label>
          </div>

          <label className="ct-field">
            <span>Opener Template</span>
            <input value={draft.opener_template_name ?? ""} onChange={(event) => update("opener_template_name", event.target.value || null)} />
          </label>
          <label className="ct-field">
            <span>Opener Text</span>
            <textarea value={draft.opener_text} onChange={(event) => update("opener_text", event.target.value)} rows={3} />
          </label>

          <label className="ct-field">
            <span>Follow-up Template</span>
            <input value={draft.opener_followup_template_name ?? ""} onChange={(event) => update("opener_followup_template_name", event.target.value || null)} />
          </label>
          <label className="ct-field">
            <span>Follow-up Text</span>
            <textarea value={draft.opener_followup_text} onChange={(event) => update("opener_followup_text", event.target.value)} rows={3} />
          </label>

          <label className="ct-field">
            <span>Manual Ping Template</span>
            <input value={draft.manual_ping_template_name ?? ""} onChange={(event) => update("manual_ping_template_name", event.target.value || null)} />
          </label>
          <label className="ct-field">
            <span>Manual Ping Text</span>
            <textarea value={draft.manual_ping_text} onChange={(event) => update("manual_ping_text", event.target.value)} rows={3} />
          </label>

          <label className="ct-field">
            <span>Video Intro Text</span>
            <textarea value={draft.loom_intro_text} onChange={(event) => update("loom_intro_text", event.target.value)} rows={4} />
          </label>

          <div className="ct-field-grid">
            <label className="ct-field">
              <span>Loom URL</span>
              <input value={draft.loom_url} onChange={(event) => update("loom_url", event.target.value)} />
            </label>
            <label className="ct-field">
              <span>MP4 Path</span>
              <input value={videoStrategy?.media_path ?? ""} onChange={(event) => updateStrategyMediaPath(event.target.value)} />
            </label>
          </div>

          <div className="ct-field-grid">
            {draft.strategies.map((strategy) => (
              <label className="ct-field" key={strategy.id}>
                <span>{strategy.label} Weight</span>
                <input type="number" min="0" max="100" value={strategy.weight} onChange={(event) => updateStrategyWeight(strategy.id, event.target.value)} />
              </label>
            ))}
          </div>

          <label className="ct-field">
            <span>Video Check Text</span>
            <input value={draft.video_check_text} onChange={(event) => update("video_check_text", event.target.value)} />
          </label>

          <label className="ct-field">
            <span>Calendly Text</span>
            <textarea value={draft.calendly_intro_text} onChange={(event) => update("calendly_intro_text", event.target.value)} rows={4} />
          </label>
          <label className="ct-field">
            <span>Calendly URL</span>
            <input value={draft.calendly_base_url} onChange={(event) => update("calendly_base_url", event.target.value)} />
          </label>
          <label className="ct-field">
            <span>Alert Emails</span>
            <input value={draft.alert_emails.join(", ")} onChange={(event) => update("alert_emails", event.target.value.split(",").map((item) => item.trim()))} />
          </label>
        </div>

        <footer className="ct-drawer-foot">
          <button type="button" className="ct-btn ct-btn-ghost" onClick={onClose}>Cancel</button>
          <button type="submit" className="ct-btn ct-btn-primary" disabled={saving}>{saving ? "Saving..." : "Save funnel"}</button>
        </footer>
      </form>
    </aside>
  );
}

function LeadList({
  leads,
  selectedLeadId,
  selectedLeadIds,
  loading,
  onSelect,
  onToggleSelected,
}: {
  leads: LeadSummary[];
  selectedLeadId: string | null;
  selectedLeadIds: string[];
  loading: boolean;
  onSelect: (leadId: string) => void;
  onToggleSelected: (leadId: string) => void;
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
        const checked = selectedLeadIds.includes(lead.id);
        return (
          <div
            className={`ct-lead-row ${lead.id === selectedLeadId ? "active" : ""} ${checked ? "selected" : ""}`}
            key={lead.id}
          >
            <label className="ct-lead-check" aria-label={`Select ${lead.full_name || lead.phone || "lead"}`}>
              <input
                type="checkbox"
                checked={checked}
                onChange={() => onToggleSelected(lead.id)}
              />
            </label>
            <button
              type="button"
              className="ct-lead"
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
          </div>
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
              <MessageMedia message={message} />
              <p className="crm-message-body">{message.text || ""}</p>
            </article>
          </div>
        );
      })}
    </div>
  );
}

function MessageMedia({ message }: { message: MessageItem }) {
  if (!message.from_me || !message.media_url) {
    return null;
  }

  const mediaType = String(message.media_type || "").toLowerCase();
  const filename = message.media_filename || message.media_path?.split("/").pop() || "WhatsApp media";
  const label = message.media_caption || filename || humanize(mediaType || "file");

  if (mediaType === "image" || mediaType === "sticker") {
    return (
      <figure className={`crm-message-media ${mediaType}`}>
        <img src={message.media_url} alt={label} loading="lazy" />
        {message.media_caption ? <figcaption>{message.media_caption}</figcaption> : null}
      </figure>
    );
  }

  if (mediaType === "video") {
    return (
      <div className="crm-message-media video">
        <video controls preload="metadata" src={message.media_url} />
      </div>
    );
  }

  if (mediaType === "audio") {
    return (
      <div className="crm-message-media audio">
        <audio controls src={message.media_url} />
      </div>
    );
  }

  return (
    <a className="crm-message-file" href={message.media_url} target="_blank" rel="noreferrer">
      <span>{humanize(mediaType || "file")}</span>
      <strong>{filename}</strong>
    </a>
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
  funnel,
  busy,
  onKindChange,
  onTextChange,
  onClose,
  onSubmit,
}: {
  kind: SendKind;
  text: string;
  funnel: FunnelDefinition | null;
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

function BulkSendModal({
  kind,
  text,
  funnel,
  selectedCount,
  busy,
  onKindChange,
  onTextChange,
  onClose,
  onSubmit,
}: {
  kind: BulkSendKind;
  text: string;
  funnel: FunnelDefinition | null;
  selectedCount: number;
  busy: boolean;
  onKindChange: (kind: BulkSendKind) => void;
  onTextChange: (value: string) => void;
  onClose: () => void;
  onSubmit: (event: FormEvent<HTMLFormElement>) => void;
}) {
  const pausesAutomation = kind !== "send-calendly";

  return (
    <div className="ct-modal open" aria-hidden="false">
      <button className="ct-modal-overlay" type="button" onClick={onClose} aria-label="Close bulk action" />
      <form className="ct-modal-panel" role="dialog" aria-modal="true" aria-labelledby="ctBulkSendModalTitle" onSubmit={onSubmit}>
        <header className="ct-modal-head">
          <div>
            <h3 id="ctBulkSendModalTitle">Bulk action</h3>
            <p className="ct-modal-subtitle">{selectedCount} selected chats</p>
          </div>
          <button type="button" className="ct-icon-btn" onClick={onClose}>Close</button>
        </header>
        <div className="ct-modal-body">
          <p className="ct-modal-warning">
            <strong>Heads up:</strong> this will apply to every selected chat in the current list.
            {pausesAutomation ? " Sending this pauses automation for those leads." : " Calendly will mark them as Calendly sent."}
          </p>

          <fieldset className="ct-send-options">
            <legend className="ct-sr-only">Bulk message type</legend>
            {sendOptions.map((option) => (
              <label className="ct-send-option" key={option.value}>
                <input
                  type="radio"
                  name="ctBulkSendKind"
                  value={option.value}
                  checked={kind === option.value}
                  onChange={() => onKindChange(option.value)}
                />
                <div>
                  <strong>{option.title}</strong>
                  <span>{sendOptionPreview(option.value, funnel) || option.help}</span>
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
          <button type="submit" className="ct-btn ct-btn-primary" disabled={busy || !selectedCount || (kind === "custom" && !text.trim())}>
            {busy ? "Sending..." : `Apply to ${selectedCount}`}
          </button>
        </footer>
      </form>
    </div>
  );
}

function buildBlankFunnel(): FunnelDefinition {
  return {
    id: "nuevo-funnel",
    label: "Nuevo Funnel",
    enabled: true,
    source_mode: "testing",
    test_phone: "",
    test_name: "Lead Test",
    sheet_url: null,
    sheet_gid: null,
    sheet_source_filter: null,
    sheet_poll_seconds: 30,
    template_language: "es",
    opener_text: "Hola, completaste el formulario sobre como podemos ayudarte. Es correcto?",
    opener_template_name: "",
    opener_followup_text: "Queria compartirte informacion sobre la propuesta que viste en el anuncio.",
    opener_followup_template_name: "",
    manual_ping_text: "Hola, queria saber en que situacion quedamos y si queres que retomemos la conversacion",
    manual_ping_template_name: "",
    loom_intro_text: "Perfecto. Te cuento rapido como funciona y que obtenes si trabajamos juntos:",
    loom_url: "",
    video_check_text: "Terminaste de ver el video?",
    calendly_intro_text: "Para avanzar, el siguiente paso es elegir un horario en el calendario:",
    calendly_base_url: "https://calendly.com",
    alert_emails: [],
    initial_reply_quiet_seconds: 30,
    post_loom_min_seconds: 600,
    post_loom_quiet_seconds: 30,
    strategies: [
      {
        step: "loom",
        id: "loom_link",
        label: "Video link",
        weight: 0,
        delivery: "link",
        sequence_step: "loom_url",
        message_text: "",
        media_type: null,
        media_path: null,
        media_caption: null,
      },
      {
        step: "loom",
        id: "loom_mp4",
        label: "WhatsApp MP4",
        weight: 100,
        delivery: "video",
        sequence_step: "loom_video",
        message_text: "Video de explicacion enviado por WhatsApp.",
        media_type: "video",
        media_path: "",
        media_caption: null,
      },
    ],
  };
}

function buildTemplateChoices(funnel: FunnelDefinition): TemplateChoice[] {
  const rawChoices: TemplateChoice[] = [
    {
      label: "Opener",
      templateId: funnel.opener_template_name ?? "",
      text: funnel.opener_text,
    },
    {
      label: "Follow-up",
      templateId: funnel.opener_followup_template_name ?? "",
      text: funnel.opener_followup_text,
    },
    {
      label: "Manual ping",
      templateId: funnel.manual_ping_template_name ?? "",
      text: funnel.manual_ping_text,
    },
  ];

  const seen = new Set<string>();
  return rawChoices.filter((choice) => {
    const templateId = choice.templateId.trim();
    if (!templateId || seen.has(templateId)) {
      return false;
    }
    seen.add(templateId);
    return true;
  });
}

function truncateForOption(value: string): string {
  const cleanValue = value.replace(/\s+/g, " ").trim();
  if (cleanValue.length <= 96) {
    return cleanValue || "Sin contenido";
  }
  return `${cleanValue.slice(0, 93)}...`;
}

function sendOptionPreview(kind: SendKind, funnel: FunnelDefinition | null): string {
  if (!funnel) {
    return "";
  }
  const previews: Partial<Record<SendKind, string>> = {
    "send-manual-ping": funnel.manual_ping_text,
    "send-opener": funnel.opener_text,
    "send-loom": funnel.loom_intro_text,
    "send-video-check": funnel.video_check_text,
    "send-calendly": `${funnel.calendly_intro_text}\n${funnel.calendly_base_url}`,
  };
  const preview = previews[kind]?.trim();
  return preview ? truncateForOption(preview) : "";
}

function slugifyClient(value: string): string {
  const normalized = value.trim().toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/^-+|-+$/g, "");
  return normalized || "nuevo-funnel";
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
