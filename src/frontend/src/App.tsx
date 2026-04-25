import { FormEvent, useCallback, useEffect, useMemo, useState } from "react";
import {
  Archive,
  ArrowClockwise,
  CalendarCheck,
  ChatCenteredText,
  CheckCircle,
  Clock,
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
import { compactNumber, humanize, lastInteractionAt, relativeTime, shortDate, stageLabel } from "./format";
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
  StrategyAssignment,
} from "./types";

const REFRESH_MS = 12000;

const stageFilters: Array<{ value: LeadStage | "all"; label: string; metric?: keyof ContadoresMetrics; tone: string }> = [
  { value: "all", label: "Todos", metric: "total", tone: "all" },
  { value: "awaiting_initial_reply", label: "Primer mensaje", metric: "awaiting_initial_reply", tone: "initial" },
  { value: "awaiting_video_reply", label: "Video enviado", metric: "awaiting_video_reply", tone: "video" },
  { value: "calendly_sent", label: "Calendly", metric: "calendly_sent", tone: "calendly" },
  { value: "booked", label: "Reservados", metric: "booked", tone: "booked" },
  { value: "closed", label: "Cerrados", metric: "closed", tone: "closed" },
  { value: "needs_human", label: "Manual", metric: "needs_human", tone: "manual" },
];

const sendActions = [
  { action: "send-opener", label: "Enviar primer mensaje", description: "Usa el template inicial.", icon: RocketLaunch, tone: "initial" },
  { action: "send-loom", label: "Enviar Loom", description: "Pausa automatizacion.", icon: Play, tone: "video" },
  { action: "send-video-check", label: "Pedir respuesta", description: "Follow-up del video.", icon: ChatCenteredText, tone: "manual" },
  { action: "send-calendly", label: "Enviar Calendly", description: "No pausa el flujo.", icon: CalendarCheck, tone: "calendly" },
] as const;

const stateActions = [
  { action: "mark-answered", label: "Ya respondi", icon: CheckCircle },
  { action: "mark-booked", label: "Marcar reservado", icon: CalendarCheck },
  { action: "close", label: "Cerrar lead", icon: XCircle },
] as const;

type ManualReplyFilter = "" | "needs_reply" | "answered";
type QuickActionName = (typeof sendActions)[number]["action"] | (typeof stateActions)[number]["action"] | "archive" | "reopen" | "unarchive";

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
  const [selectedLeadId, setSelectedLeadId] = useState<string | null>(null);
  const [stageFilter, setStageFilter] = useState<LeadStage | "all">("all");
  const [includeArchived, setIncludeArchived] = useState(false);
  const [manualReplyFilter, setManualReplyFilter] = useState<ManualReplyFilter>("");
  const [showAdvancedFilters, setShowAdvancedFilters] = useState(false);
  const [showConfig, setShowConfig] = useState(false);
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
    if (manualReplyFilter) {
      params.set("manual_reply_status", manualReplyFilter);
      params.set("needs_human", "true");
    }
    if (debouncedQuery.trim()) {
      params.set("query", debouncedQuery.trim());
    }

    setError(null);
    const [runtimePayload, leadsPayload] = await Promise.all([
      apiFetch<RuntimeSettings>("/api/runtime"),
      apiFetch<LeadListResponse>(`/api/contadores/leads?${params.toString()}`),
    ]);

    setRuntime(runtimePayload);
    setLeadList(leadsPayload);
    setLastRefreshAt(new Date().toISOString());

    setSelectedLeadId((current) => {
      if (current && leadsPayload.leads.some((lead) => lead.id === current)) {
        return current;
      }
      return leadsPayload.leads[0]?.id ?? null;
    });
  }, [debouncedQuery, includeArchived, manualReplyFilter, stageFilter]);

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
          setError(reason instanceof Error ? reason.message : "No se pudo cargar el panel.");
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
          setError(reason instanceof Error ? reason.message : "Fallo la actualizacion automatica.");
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
      setError(reason instanceof Error ? reason.message : "No se pudo cargar el lead.");
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
      setError(reason instanceof Error ? reason.message : "No se pudo actualizar.");
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
      setError(reason instanceof Error ? reason.message : "No se pudo ejecutar la accion.");
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
      setError(reason instanceof Error ? reason.message : "No se pudo reactivar la automatizacion.");
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
      setError(reason instanceof Error ? reason.message : "No se pudo enviar el mensaje manual.");
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
      setError(reason instanceof Error ? reason.message : "No se pudo guardar la config.");
    } finally {
      setActionBusy(null);
    }
  }

  const metrics = leadList?.metrics;
  const activeFilterCount = [
    stageFilter !== "all",
    Boolean(debouncedQuery.trim()),
    Boolean(manualReplyFilter),
    includeArchived,
  ].filter(Boolean).length;

  function clearFilters() {
    setStageFilter("all");
    setManualReplyFilter("");
    setIncludeArchived(false);
    setQuery("");
  }

  return (
    <div className="app-shell">
      <header className="topbar">
        <div>
          <div className="product-mark">
            <span className="mark-dot" />
            <span>Contadores Ops</span>
          </div>
          <h1>Panel de seguimiento WhatsApp</h1>
        </div>
        <div className="topbar-actions">
          <RuntimePill runtime={runtime} />
          <button className="icon-button labeled" type="button" onClick={() => setShowAdvancedFilters((value) => !value)} title="Filtros">
            <Funnel size={18} weight="bold" />
            <span>Filtros{activeFilterCount ? ` (${activeFilterCount})` : ""}</span>
          </button>
          <button className="icon-button labeled" type="button" onClick={() => setShowConfig(true)} title="Config">
            <GearSix size={18} weight="bold" />
            <span>Config</span>
          </button>
          <button className="icon-button" type="button" onClick={refreshAll} disabled={loading} title="Actualizar">
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

      <section className="status-strip" aria-label="Estado actual">
        <StatusItem label="Modo" value={runtime?.source_mode ?? "-"} tone={runtime?.source_mode === "live" ? "live" : "testing"} />
        <StatusItem label="Listo" value={runtime?.ready ? "Si" : "Revisar"} tone={runtime?.ready ? "ok" : "warn"} />
        <StatusItem label="Actualizacion" value={lastRefreshAt ? relativeTime(lastRefreshAt) : "Iniciando"} tone="neutral" />
        <StatusItem label="Ultima sync" value={shortDate(leadList?.config.last_sheet_sync_at)} tone="neutral" />
      </section>

      <MetricsBar metrics={metrics} activeStage={stageFilter} onStageChange={setStageFilter} />

      {showAdvancedFilters ? (
        <AdvancedFilters
          includeArchived={includeArchived}
          manualReplyFilter={manualReplyFilter}
          activeFilterCount={activeFilterCount}
          onArchivedChange={setIncludeArchived}
          onManualReplyChange={setManualReplyFilter}
          onClear={clearFilters}
        />
      ) : null}

      <main className="workspace">
        <section className="lead-column" aria-label="Lista de leads">
          <div className="toolbar">
            <label className="search-box">
              <MagnifyingGlass size={17} weight="bold" />
              <input value={query} onChange={(event) => setQuery(event.target.value)} placeholder="Buscar leads" />
            </label>
            {activeFilterCount ? (
              <button className="filter-button" type="button" onClick={clearFilters}>
                Limpiar
              </button>
            ) : null}
          </div>

          <LeadList
            leads={leadList?.leads ?? []}
            loading={loading}
            selectedLeadId={selectedLeadId}
            onSelect={setSelectedLeadId}
          />
        </section>

        <section className="detail-column" aria-label="Detalle del lead">
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
      </main>

      {showConfig ? (
        <ConfigDrawer
          config={leadList?.config ?? null}
          runtime={runtime}
          saving={actionBusy === "config"}
          onClose={() => setShowConfig(false)}
          onSave={saveConfig}
        />
      ) : null}
    </div>
  );
}

function RuntimePill({ runtime }: { runtime: RuntimeSettings | null }) {
  const ready = runtime?.ready ?? false;
  return (
    <div className={`runtime-pill ${ready ? "ready" : "blocked"}`}>
      {ready ? <CheckCircle size={16} weight="fill" /> : <WarningCircle size={16} weight="fill" />}
      <span>{runtime ? `modo ${runtime.source_mode}` : "cargando"}</span>
    </div>
  );
}

function AdvancedFilters({
  includeArchived,
  manualReplyFilter,
  activeFilterCount,
  onArchivedChange,
  onManualReplyChange,
  onClear,
}: {
  includeArchived: boolean;
  manualReplyFilter: ManualReplyFilter;
  activeFilterCount: number;
  onArchivedChange: (value: boolean) => void;
  onManualReplyChange: (value: ManualReplyFilter) => void;
  onClear: () => void;
}) {
  return (
    <section className="filter-panel" aria-label="Filtros avanzados de leads">
      <div>
        <span>Filtros</span>
        <strong>{activeFilterCount ? `${activeFilterCount} activos` : "Vista principal"}</strong>
      </div>
      <div className="filter-segment" aria-label="Filtros de respuesta manual">
        <button
          type="button"
          className={!manualReplyFilter ? "active" : ""}
          onClick={() => onManualReplyChange("")}
        >
          Todos
        </button>
        <button
          type="button"
          className={manualReplyFilter === "needs_reply" ? "active warn" : ""}
          onClick={() => onManualReplyChange("needs_reply")}
        >
          Necesitan respuesta
        </button>
        <button
          type="button"
          className={manualReplyFilter === "answered" ? "active ok" : ""}
          onClick={() => onManualReplyChange("answered")}
        >
          Ya respondidos
        </button>
      </div>
      <label className="archive-toggle">
        <input type="checkbox" checked={includeArchived} onChange={(event) => onArchivedChange(event.target.checked)} />
        <span>Mostrar archivados</span>
      </label>
      <button className="filter-clear" type="button" onClick={onClear} disabled={!activeFilterCount}>
        Limpiar
      </button>
    </section>
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
    <section className="metric-rail" aria-label="Filtros por etapa">
      {stageFilters.map((filter) => {
        const count = filter.metric && metrics ? metrics[filter.metric] : 0;
        return (
          <button
            key={filter.value}
            type="button"
            className={`metric-tile tone-${filter.tone} ${activeStage === filter.value ? "active" : ""}`}
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
        <h2>No hay leads en esta vista</h2>
        <p>Ajusta filtros o espera la proxima sync.</p>
      </div>
    );
  }

  return (
    <div className="lead-list">
      {leads.map((lead) => {
        const active = lead.id === selectedLeadId;
        const lastAt = lastInteractionAt(lead);
        return (
          <button key={lead.id} className={`lead-row stage-${lead.stage} ${active ? "active" : ""}`} type="button" onClick={() => onSelect(lead.id)}>
            <div className="lead-row-top">
              <strong>{lead.full_name || "Lead sin nombre"}</strong>
              <StageBadge stage={lead.stage} />
            </div>
            <div className="lead-row-meta">
              <span>{lead.phone}</span>
              <span>{relativeTime(lastAt)}</span>
            </div>
            <div className="lead-row-bottom">
              <span>{lead.platform || "Sin origen"}</span>
              <StrategyChips assignments={lead.strategy_assignments} compact />
              {lead.manual_reply_status === "needs_reply" ? <em>requiere respuesta</em> : null}
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
  const [showEvents, setShowEvents] = useState(false);

  useEffect(() => {
    setShowEvents(false);
  }, [lead?.id]);

  if (!lead) {
    return (
      <div className="detail-empty">
        <UserFocus size={32} weight="bold" />
        <h2>Selecciona un lead</h2>
        <p>Abri un lead para ver mensajes, estado y controles manuales.</p>
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
          <h2>{lead.full_name || "Lead sin nombre"}</h2>
          <p>{lead.email || "Sin email"} · {lead.platform || "Sin origen"}</p>
        </div>
        <StageBadge stage={lead.stage} large />
      </div>

      <StrategyChips assignments={lead.strategy_assignments} />

      <div className="lead-facts">
        <Fact label="Entrante" value={shortDate(lead.last_inbound_at)} />
        <Fact label="Enviado" value={shortDate(lead.last_outbound_at)} />
        <Fact label="Manual" value={lead.manual_reply_status ? humanize(lead.manual_reply_status) : "Sin pendiente"} />
        <Fact label="Automatizacion" value={lead.automation_paused ? "Pausada" : "Activa"} />
      </div>

      {lead.automation_paused ? (
        <div className="pause-callout">
          <PauseCircle size={18} weight="fill" />
          <div>
            <strong>Automatizacion pausada</strong>
            <span>{humanize(lead.automation_paused_reason || "manual review")}</span>
          </div>
          <button type="button" onClick={onResume} disabled={actionBusy === "resume"}>
            Reactivar
          </button>
        </div>
      ) : null}

      <div className="preset-panel" aria-label="Mensajes preparados">
        <div className="preset-panel-head">
            <span>Mensajes</span>
            <strong>Enviar mensaje preparado</strong>
        </div>
        <div className="action-grid">
          {sendActions.map((item) => {
            const Icon = item.icon;
            return (
              <button
                key={item.action}
                className={`preset-action tone-${item.tone}`}
                type="button"
                onClick={() => onQuickAction(item.action)}
                disabled={Boolean(actionBusy)}
              >
                <Icon size={16} weight="bold" />
                <span>
                  <strong>{item.label}</strong>
                  <em>{item.description}</em>
                </span>
              </button>
            );
          })}
        </div>
      </div>

      <div className="conversation-area">
        <div className="timeline-wrap">
          <div className="section-title conversation-title">
            <h3>Conversacion</h3>
            <div className="section-actions">
              <span>{loading ? "Actualizando" : `${detail?.messages.length ?? 0} mensajes`}</span>
              <button className="events-toggle" type="button" onClick={() => setShowEvents((value) => !value)}>
                <Clock size={15} weight="bold" />
                {showEvents ? "Ocultar eventos" : `Eventos (${detail?.events.length ?? 0})`}
              </button>
            </div>
          </div>
          <MessageTimeline messages={detail?.messages ?? []} loading={loading} />
          {showEvents ? (
            <div className="events-panel">
              <EventTimeline events={detail?.events ?? []} />
            </div>
          ) : null}
        </div>
      </div>

      <section className="operator-dock" aria-label="Controles manuales">
        <div className="operator-dock-head">
          <div>
            <span>Manual</span>
            <h3>Mensaje y estado</h3>
          </div>
          <StageBadge stage="needs_human" />
        </div>

        <form className="manual-form" onSubmit={onManualSubmit}>
          <label>
            <span>Mensaje manual de WhatsApp</span>
            <textarea
              value={manualText}
              onChange={(event) => onManualTextChange(event.target.value)}
              placeholder="Escribi el mensaje exacto que queres enviar..."
              rows={2}
            />
          </label>
          <button type="submit" disabled={!manualText.trim() || Boolean(actionBusy)}>
            <PaperPlaneTilt size={16} weight="bold" />
            Enviar manual
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
              Reabrir
            </button>
          ) : null}
          {lead.stage === "archived" ? (
            <button type="button" onClick={() => onQuickAction("unarchive")} disabled={Boolean(actionBusy)}>
              <Archive size={15} weight="bold" />
              Desarchivar
            </button>
          ) : null}
        </div>
      </section>
    </div>
  );
}

function StageBadge({ stage, large = false }: { stage: LeadStage; large?: boolean }) {
  return <span className={`stage-badge ${stage} ${large ? "large" : ""}`}>{stageLabel(stage)}</span>;
}

function StrategyChips({
  assignments,
  compact = false,
}: {
  assignments: StrategyAssignment[];
  compact?: boolean;
}) {
  if (!assignments.length) {
    return null;
  }

  const visibleAssignments = compact ? assignments.slice(0, 1) : assignments.slice(0, 3);
  return (
    <div className={`strategy-chips ${compact ? "compact" : ""}`} aria-label="Estrategias asignadas">
      {visibleAssignments.map((assignment) => (
        <span
          className={`strategy-chip strategy-tone-${strategyToneIndex(assignment.strategy_id || assignment.strategy_label)}`}
          key={`${assignment.step}-${assignment.strategy_id}-${assignment.id}`}
        >
          {compact ? assignment.strategy_label : `${humanize(assignment.step)} · ${assignment.strategy_label}`}
        </span>
      ))}
    </div>
  );
}

function strategyToneIndex(value: string): number {
  let hash = 0;
  for (const character of value || "strategy") {
    hash = (hash + character.charCodeAt(0)) % 5;
  }
  return hash;
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
        <span>Sin mensajes todavia.</span>
      </div>
    );
  }

  return (
    <div className="message-list">
      {messages.map((message) => (
        <article key={message.id} className={`message ${message.from_me ? "outbound" : "inbound"}`}>
          <div className="message-meta">
            <strong>{message.from_me ? "Enviado" : "Recibido"}</strong>
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
        <span>Sin eventos todavia.</span>
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

function ConfigDrawer({
  config,
  runtime,
  saving,
  onClose,
  onSave,
}: {
  config: ContadoresConfig | null;
  runtime: RuntimeSettings | null;
  saving: boolean;
  onClose: () => void;
  onSave: (config: Partial<ContadoresConfig>) => Promise<void>;
}) {
  return (
    <div className="config-overlay" role="dialog" aria-modal="true" aria-label="Config">
      <button className="config-backdrop" type="button" aria-label="Cerrar config" onClick={onClose} />
      <section className="config-drawer">
        <header className="drawer-head">
          <div>
            <span>Config</span>
            <h2>Fuente y secuencia</h2>
          </div>
          <button className="icon-button" type="button" onClick={onClose} aria-label="Cerrar config">
            <XCircle size={18} weight="bold" />
          </button>
        </header>
        <ConfigPanel config={config} runtime={runtime} saving={saving} onSave={onSave} />
      </section>
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
          <h2>Fuente y secuencia</h2>
        </div>
        <GearSix size={19} weight="bold" />
      </div>

      <div className="runtime-stack">
        <Fact label="Modo" value={runtime?.source_mode ?? "-"} />
        <Fact label="Sheet" value={runtime?.sheet_configured ? "Configurado" : "Falta"} />
        <Fact label="Test phone" value={runtime?.testing_phone_configured ? "Configurado" : "Falta"} />
      </div>

      <form className="config-form" onSubmit={handleSubmit}>
        <label className="toggle-line">
          <input type="checkbox" checked={draft.enabled} onChange={(event) => setDraft((current) => ({ ...current, enabled: event.target.checked }))} />
          <span>Automatizacion activa</span>
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
            <span>Sync sheet cada</span>
            <input
              type="number"
              min={60}
              value={draft.sheet_poll_seconds}
              onChange={(event) => setDraft((current) => ({ ...current, sheet_poll_seconds: Number(event.target.value) }))}
            />
          </label>
          <label>
            <span>Espera post-Loom</span>
            <input
              type="number"
              min={60}
              value={draft.post_loom_min_seconds}
              onChange={(event) => setDraft((current) => ({ ...current, post_loom_min_seconds: Number(event.target.value) }))}
            />
          </label>
        </div>
        <label>
          <span>Emails de alerta</span>
          <input value={draft.alert_emails} onChange={(event) => setDraft((current) => ({ ...current, alert_emails: event.target.value }))} />
        </label>
        <button type="submit" disabled={saving || !config}>
          {saving ? "Guardando" : "Guardar config"}
        </button>
      </form>
    </section>
  );
}
