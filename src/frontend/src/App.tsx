import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import type { ClipboardEvent, DragEvent, FormEvent, ReactNode } from "react";
import {
  ArrowsClockwise,
  ArrowSquareOut,
  BellRinging,
  Camera,
  CaretDown,
  ChatCircleText,
  Check,
  CheckCircle,
  ClockCountdown,
  Copy,
  CurrencyDollar,
  DownloadSimple,
  FolderOpen,
  ListChecks,
  NotePencil,
  PaperPlaneTilt,
  Pulse,
  Robot,
  SpinnerGap,
  TrendUp,
  Trash,
  UploadSimple,
  WarningCircle,
  X,
} from "@phosphor-icons/react";
import { marked } from "marked";
import { apiFetch } from "./api";
import { compactNumber, humanize, lastInteractionAt, relativeTime, shortDate } from "./format";
import type {
  BulkActionResponse,
  ContadoresConfig,
  ContadoresMetrics,
  FunnelDefinition,
  FunnelListResponse,
  LeadDetailResponse,
  LeadListResponse,
  LeadStage,
  LeadSummary,
  ManualAttentionCountsResponse,
  MessageItem,
  QuickActionResponse,
  RunnerDeltaEvent,
  RunnerStatusResponse,
  RuntimeSettings,
  StrategyStatsItem,
  StrategyStatsResponse,
  WorkstationClientDetailResponse,
  WorkstationClientListResponse,
  WorkstationClientSummary,
  WorkstationCopyAllResponse,
  WorkstationMediaAsset,
  WorkstationProfessionalPhotoJobResponse,
  WorkstationProfessionalPhotoVersion,
} from "./types";

const REFRESH_MS = 12000;
const WORKSTATION_DETAIL_REFRESH_MS = 4000;
const WHATSAPP_CUSTOM_WINDOW_MS = 24 * 60 * 60 * 1000;
const DASHBOARD_FUNNEL_STORAGE_KEY = "contadores.dashboard.selectedFunnelId";
const DASHBOARD_STAGE_STORAGE_KEY = "contadores.dashboard.stageFilter";
const DASHBOARD_SECTION_STORAGE_KEY = "contadores.dashboard.activeSection";

type StageFilterValue = LeadStage | "all" | "manual_attention";
type ActiveSection = "crm" | "workstation" | "runner";
type LoadWorkstationDetailOptions = {
  syncNotes?: boolean;
  showLoading?: boolean;
};

const stageFilters: Array<{
  value: StageFilterValue;
  label: string;
  metric?: keyof ContadoresMetrics;
  tone: "all" | "neutral" | "accent" | "success" | "warn" | "muted";
}> = [
  { value: "all", label: "All", metric: "total", tone: "all" },
  { value: "awaiting_initial_reply", label: "Opener sent", metric: "awaiting_initial_reply", tone: "neutral" },
  { value: "awaiting_video_reply", label: "Loom sent", metric: "awaiting_video_reply", tone: "neutral" },
  { value: "calendly_sent", label: "Calendly sent", metric: "calendly_sent", tone: "accent" },
  { value: "booked", label: "Booked", metric: "booked", tone: "success" },
  { value: "needs_human", label: "Manual", metric: "needs_human", tone: "warn" },
  { value: "manual_attention", label: "Needs answer", tone: "warn" },
  { value: "closed", label: "Closed", metric: "closed", tone: "muted" },
];

const validStageFilterValues = new Set<StageFilterValue>(stageFilters.map((filter) => filter.value));

function readStoredValue(storageKey: string): string | null {
  try {
    return window.localStorage.getItem(storageKey);
  } catch {
    return null;
  }
}

function writeStoredValue(storageKey: string, value: string) {
  try {
    window.localStorage.setItem(storageKey, value);
  } catch {
    // Storage can be disabled in private or restricted browser contexts.
  }
}

function readStoredFunnelId(): string {
  return readStoredValue(DASHBOARD_FUNNEL_STORAGE_KEY) || "contadores";
}

function readStoredStageFilter(): StageFilterValue {
  const value = readStoredValue(DASHBOARD_STAGE_STORAGE_KEY);
  return validStageFilterValues.has(value as StageFilterValue) ? value as StageFilterValue : "all";
}

function readStoredActiveSection(): ActiveSection {
  const value = readStoredValue(DASHBOARD_SECTION_STORAGE_KEY);
  return value === "workstation" || value === "runner" ? value : "crm";
}

const moveStageOptions: Array<{ value: LeadStage; label: string }> = [
  { value: "needs_human", label: "Manual" },
  { value: "awaiting_initial_reply", label: "Opener sent" },
  { value: "awaiting_video_reply", label: "Loom sent" },
  { value: "calendly_sent", label: "Calendly sent" },
  { value: "booked", label: "Booked" },
  { value: "closed", label: "Closed" },
];

const sendOptions = [
  { value: "custom", title: "Custom message", help: "Write your own WhatsApp reply." },
  { value: "send-manual-ping", title: "Manual ping", help: "Send the approved ping template to reopen WhatsApp." },
  { value: "offer-solo-page-promo", title: "Promo solo pagina", help: "Offer the page-only promo and let automation handle the reply." },
  { value: "send-opener", title: "Opener", help: "Queue the default opener template." },
  { value: "send-loom", title: "Loom sequence", help: "Queue the Loom video introduction messages." },
  { value: "send-accountant-page-example-video", title: "Pagina contador", help: "Send the accountant page example video." },
  { value: "send-lawyer-page-example-video", title: "Pagina abogado", help: "Send the lawyer page example video." },
  { value: "send-video-check", title: "Video check", help: "Ask if they watched the Loom." },
  { value: "send-calendly", title: "Calendly with intro", help: "Send the booking instructions and then the Calendly link." },
  { value: "send-calendly-link", title: "Calendly link only", help: "Send only the Calendly link and mark Calendly sent." },
] as const;

type DetailTab = "messages" | "strategies";
type SendKind = (typeof sendOptions)[number]["value"];
type BulkSendKind = SendKind | "set-tags";
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
  | "offer-solo-page-promo"
  | "send-loom"
  | "send-accountant-page-example-video"
  | "send-lawyer-page-example-video"
  | "send-video-check"
  | "send-calendly"
  | "send-calendly-link"
  | "manual-handoff"
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
  const [activeSection, setActiveSection] = useState<ActiveSection>(readStoredActiveSection);
  const [runtime, setRuntime] = useState<RuntimeSettings | null>(null);
  const [funnels, setFunnels] = useState<FunnelDefinition[]>([]);
  const [funnelConfigPath, setFunnelConfigPath] = useState("");
  const [selectedFunnelId, setSelectedFunnelId] = useState(readStoredFunnelId);
  const [leadList, setLeadList] = useState<LeadListResponse | null>(null);
  const [manualAttentionList, setManualAttentionList] = useState<LeadSummary[]>([]);
  const [manualAttentionCounts, setManualAttentionCounts] = useState<Record<string, number>>({});
  const [strategyStats, setStrategyStats] = useState<StrategyStatsItem[]>([]);
  const [detail, setDetail] = useState<LeadDetailResponse | null>(null);
  const [selectedLeadId, setSelectedLeadId] = useState<string | null>(null);
  const [stageFilter, setStageFilter] = useState<StageFilterValue>(readStoredStageFilter);
  const [tagFilter, setTagFilter] = useState("");
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
  const [bulkSendKind, setBulkSendKind] = useState<BulkSendKind>("custom");
  const [bulkManualPingConfirmed, setBulkManualPingConfirmed] = useState(false);
  const [manualText, setManualText] = useState("");
  const [manualFiles, setManualFiles] = useState<File[]>([]);
  const [bulkTagsDraft, setBulkTagsDraft] = useState("");
  const [selectedLeadIds, setSelectedLeadIds] = useState<string[]>([]);
  const [workstationList, setWorkstationList] = useState<WorkstationClientListResponse | null>(null);
  const [workstationDetail, setWorkstationDetail] = useState<WorkstationClientDetailResponse | null>(null);
  const [selectedWorkstationClientId, setSelectedWorkstationClientId] = useState<string | null>(null);
  const [workstationQuery, setWorkstationQuery] = useState("");
  const [workstationNotesDraft, setWorkstationNotesDraft] = useState("");
  const [workstationFileTitle, setWorkstationFileTitle] = useState("");
  const [workstationFile, setWorkstationFile] = useState<File | null>(null);
  const [professionalPhotoMediaIds, setProfessionalPhotoMediaIds] = useState<string[]>([]);
  const [professionalPhotoContext, setProfessionalPhotoContext] = useState("");
  const [professionalPhotoEditPrompts, setProfessionalPhotoEditPrompts] = useState<Record<string, string>>({});
  const [professionalPhotoJob, setProfessionalPhotoJob] = useState<WorkstationProfessionalPhotoJobResponse | null>(null);
  const [workstationLoading, setWorkstationLoading] = useState(false);
  const [runnerStatus, setRunnerStatus] = useState<RunnerStatusResponse | null>(null);
  const [runnerLoading, setRunnerLoading] = useState(false);
  const [acknowledgingDeliveryErrorIds, setAcknowledgingDeliveryErrorIds] = useState<number[]>([]);
  const [leadContextCopyStatus, setLeadContextCopyStatus] = useState("");
  const detailRequestId = useRef(0);
  const debouncedQuery = useDebouncedValue(query, 250);
  const debouncedWorkstationQuery = useDebouncedValue(workstationQuery, 250);

  const metrics = leadList?.metrics;
  const tagOptions = leadList?.tag_options ?? [];
  const config = leadList?.config ?? detail?.config ?? null;
  const selectedFunnel = funnels.find((funnel) => funnel.id === selectedFunnelId) ?? funnels[0] ?? null;
  const isContadoresFunnel = true;
  const isInboxFunnel = selectedFunnel?.kind === "inbox";

  const selectedLead = useMemo(() => {
    if (detail?.lead.id === selectedLeadId) {
      return detail.lead;
    }
    if (!selectedLeadId || !leadList) {
      return null;
    }
    return leadList.leads.find((lead) => lead.id === selectedLeadId) ?? null;
  }, [detail, leadList, selectedLeadId]);
  const selectedLeadDetail = detail?.lead.id === selectedLeadId ? detail : null;
  const visibleLeadIds = useMemo(() => (leadList?.leads ?? []).map((lead) => lead.id), [leadList]);
  const selectedVisibleLeads = useMemo(
    () => (leadList?.leads ?? []).filter((lead) => selectedLeadIds.includes(lead.id)),
    [leadList, selectedLeadIds],
  );
  const selectedLeadCustomBlockReason = customMessageBlockReason(selectedLead);
  const bulkCustomBlockedCount = selectedVisibleLeads.filter((lead) => customMessageBlockReason(lead)).length;
  const bulkClosedCount = selectedVisibleLeads.filter((lead) => lead.stage === "closed").length;
  const workstationClients = workstationList?.clients ?? [];
  const selectedVisibleCount = selectedLeadIds.filter((leadId) => visibleLeadIds.includes(leadId)).length;
  const allVisibleSelected = visibleLeadIds.length > 0 && selectedVisibleCount === visibleLeadIds.length;

  const loadDashboard = useCallback(async () => {
    setError(null);
    const [runtimePayload, funnelPayload, attentionCountsPayload] = await Promise.all([
      apiFetch<RuntimeSettings>("/api/runtime"),
      apiFetch<FunnelListResponse>("/api/funnels"),
      apiFetch<ManualAttentionCountsResponse>("/api/contadores/manual-attention-counts"),
    ]);

    setRuntime(runtimePayload);
    setFunnels(funnelPayload.funnels ?? []);
    setFunnelConfigPath(funnelPayload.config_path || "");
    setManualAttentionCounts(attentionCountsPayload.counts ?? {});

    if (!selectedFunnelId || !funnelPayload.funnels.some((funnel) => funnel.id === selectedFunnelId)) {
      setSelectedFunnelId(funnelPayload.funnels[0]?.id ?? "contadores");
    }

    const activeFunnel = funnelPayload.funnels.find((funnel) => funnel.id === selectedFunnelId) ?? funnelPayload.funnels[0];
    const activeFunnelId = activeFunnel?.id ?? "contadores";
    const activeIsInbox = activeFunnel?.kind === "inbox";
    const params = new URLSearchParams({ limit: "500", archived: "false", funnel_id: activeFunnelId });
    if (!activeIsInbox && stageFilter === "manual_attention") {
      params.set("stage", "needs_human");
      params.set("manual_reply_status", "needs_reply");
      params.set("needs_human", "true");
    } else if (!activeIsInbox && stageFilter !== "all") {
      params.set("stage", stageFilter);
    }
    if (!activeIsInbox && strategyFilter.step) {
      params.set("strategy_step", strategyFilter.step);
    }
    if (!activeIsInbox && strategyFilter.strategyId) {
      params.set("strategy_id", strategyFilter.strategyId);
    }
    if (tagFilter) {
      params.set("tag", tagFilter);
    }
    if (debouncedQuery.trim()) {
      params.set("query", debouncedQuery.trim());
    }

    const manualAttentionParams = new URLSearchParams({
      limit: "200",
      archived: "false",
      funnel_id: activeFunnelId,
      stage: "needs_human",
      manual_reply_status: "needs_reply",
      needs_human: "true",
    });
    if (debouncedQuery.trim()) {
      manualAttentionParams.set("query", debouncedQuery.trim());
    }
    if (tagFilter) {
      manualAttentionParams.set("tag", tagFilter);
    }

    const [leadsPayload, manualAttentionPayload, strategyPayload] = await Promise.all([
      apiFetch<LeadListResponse>(`/api/contadores/leads?${params.toString()}`),
      apiFetch<LeadListResponse>(`/api/contadores/leads?${manualAttentionParams.toString()}`),
      apiFetch<StrategyStatsResponse>(`/api/contadores/strategy-stats?funnel_id=${encodeURIComponent(activeFunnelId)}`),
    ]);

    setLeadList(leadsPayload);
    setManualAttentionList(manualAttentionPayload.leads ?? []);
    setStrategyStats(strategyPayload.items ?? []);

    setSelectedLeadId((current) => {
      const currentLeadIsVisible = Boolean(current && leadsPayload.leads.some((lead) => lead.id === current));
      const currentLeadIsOpen = Boolean(current && detail?.lead.id === current);
      if (currentLeadIsVisible || currentLeadIsOpen) {
        return current;
      }
      return leadsPayload.leads[0]?.id ?? null;
    });
  }, [debouncedQuery, detail?.lead.id, selectedFunnelId, stageFilter, strategyFilter.step, strategyFilter.strategyId, tagFilter]);

  const loadWorkstation = useCallback(async () => {
    const params = new URLSearchParams({ limit: "500" });
    if (selectedFunnelId) {
      params.set("funnel_id", selectedFunnelId);
    }
    if (debouncedWorkstationQuery.trim()) {
      params.set("query", debouncedWorkstationQuery.trim());
    }

    const payload = await apiFetch<WorkstationClientListResponse>(`/api/workstation/clients?${params.toString()}`);
    setWorkstationList(payload);
    setSelectedWorkstationClientId((current) => {
      if (current && payload.clients.some((client) => client.id === current)) {
        return current;
      }
      return payload.clients[0]?.id ?? null;
    });
  }, [debouncedWorkstationQuery, selectedFunnelId]);

  const loadRunnerStatus = useCallback(async () => {
    const payload = await apiFetch<RunnerStatusResponse>(
      "/api/contadores/followup/runner/status?log_tail_lines=160&log_limit=12",
    );
    setRunnerStatus(payload);
  }, []);

  const loadDetail = useCallback(async (leadId: string) => {
    const requestId = detailRequestId.current + 1;
    detailRequestId.current = requestId;
    setDetailLoading(true);
    try {
      const payload = await apiFetch<LeadDetailResponse>(`/api/contadores/leads/${leadId}`);
      if (detailRequestId.current === requestId) {
        setDetail(payload);
      }
    } finally {
      if (detailRequestId.current === requestId) {
        setDetailLoading(false);
      }
    }
  }, []);

  const loadWorkstationDetail = useCallback(async (clientId: string, options: LoadWorkstationDetailOptions = {}) => {
    const syncNotes = options.syncNotes ?? true;
    const showLoading = options.showLoading ?? true;
    if (showLoading) {
      setWorkstationLoading(true);
    }
    try {
      const payload = await apiFetch<WorkstationClientDetailResponse>(`/api/workstation/clients/${clientId}`);
      setWorkstationDetail(payload);
      if (syncNotes) {
        setWorkstationNotesDraft(payload.notes ?? "");
      }
      return payload;
    } finally {
      if (showLoading) {
        setWorkstationLoading(false);
      }
    }
  }, []);

  useEffect(() => {
    writeStoredValue(DASHBOARD_FUNNEL_STORAGE_KEY, selectedFunnelId);
  }, [selectedFunnelId]);

  useEffect(() => {
    writeStoredValue(DASHBOARD_SECTION_STORAGE_KEY, activeSection);
  }, [activeSection]);

  useEffect(() => {
    writeStoredValue(DASHBOARD_STAGE_STORAGE_KEY, stageFilter);
  }, [stageFilter]);

  useEffect(() => {
    setSelectedLeadIds((current) => current.filter((leadId) => visibleLeadIds.includes(leadId)));
  }, [visibleLeadIds]);

  useEffect(() => {
    if (!isInboxFunnel) {
      return;
    }
    setStageFilter("all");
    setStrategyFilter({ step: "", strategyId: "" });
    setActiveTab("messages");
  }, [isInboxFunnel]);

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
        const loaders = [loadDashboard()];
        if (activeSection === "runner") {
          loaders.push(loadRunnerStatus());
        }
        Promise.all(loaders).catch((reason) => {
          setError(reason instanceof Error ? reason.message : "Automatic refresh failed.");
        });
      }
    }, REFRESH_MS);
    return () => window.clearInterval(timer);
  }, [activeSection, loadDashboard, loadRunnerStatus]);

  useEffect(() => {
    if (!selectedLeadId || !isContadoresFunnel) {
      setDetail(null);
      return;
    }
    setActiveTab("messages");
    setDetail((current) => current?.lead.id === selectedLeadId ? current : null);
    loadDetail(selectedLeadId).catch((reason) => {
      setError(reason instanceof Error ? reason.message : "Could not load the lead.");
    });
  }, [isContadoresFunnel, loadDetail, selectedLeadId]);

  useEffect(() => {
    setLeadContextCopyStatus("");
  }, [selectedLeadId]);

  useEffect(() => {
    loadWorkstation().catch((reason) => {
      setError(reason instanceof Error ? reason.message : "Could not load Workstation.");
    });
  }, [loadWorkstation]);

  useEffect(() => {
    if (activeSection !== "runner") {
      return;
    }
    let cancelled = false;
    setRunnerLoading(true);
    loadRunnerStatus()
      .catch((reason) => {
        if (!cancelled) {
          setError(reason instanceof Error ? reason.message : "Could not load the runner.");
        }
      })
      .finally(() => {
        if (!cancelled) {
          setRunnerLoading(false);
        }
      });
    return () => {
      cancelled = true;
    };
  }, [activeSection, loadRunnerStatus]);

  useEffect(() => {
    if (!selectedWorkstationClientId) {
      setWorkstationDetail(null);
      setWorkstationNotesDraft("");
      return;
    }
    loadWorkstationDetail(selectedWorkstationClientId).catch((reason) => {
      setError(reason instanceof Error ? reason.message : "Could not load the Workstation client.");
    });
  }, [loadWorkstationDetail, selectedWorkstationClientId]);

  useEffect(() => {
    if (activeSection !== "workstation" || !selectedWorkstationClientId) {
      return;
    }
    let cancelled = false;
    const pollWorkstation = async () => {
      if (document.visibilityState !== "visible") {
        return;
      }
      try {
        await Promise.all([
          loadWorkstation(),
          loadWorkstationDetail(selectedWorkstationClientId, { syncNotes: false, showLoading: false }),
        ]);
      } catch (reason) {
        if (!cancelled) {
          setError(reason instanceof Error ? reason.message : "Could not refresh Workstation status.");
        }
      }
    };
    const timer = window.setInterval(() => {
      pollWorkstation();
    }, WORKSTATION_DETAIL_REFRESH_MS);
    return () => {
      cancelled = true;
      window.clearInterval(timer);
    };
  }, [activeSection, loadWorkstation, loadWorkstationDetail, selectedWorkstationClientId]);

  useEffect(() => {
    if (!professionalPhotoJob || !["queued", "running"].includes(professionalPhotoJob.status)) {
      return;
    }

    let cancelled = false;
    const pollJob = async () => {
      try {
        const payload = await apiFetch<WorkstationProfessionalPhotoJobResponse>(
          `/api/workstation/clients/${professionalPhotoJob.client_id}/professional-photo/jobs/${professionalPhotoJob.job_id}`,
        );
        if (cancelled) {
          return;
        }
        setProfessionalPhotoJob(payload);
        if (payload.status === "completed") {
          await loadWorkstation();
          await loadWorkstationDetail(payload.client_id);
        } else if (payload.status === "failed") {
          setError(payload.error || "Could not create professional photo.");
        }
      } catch (reason) {
        if (!cancelled) {
          setError(reason instanceof Error ? reason.message : "Could not check professional photo status.");
        }
      }
    };

    pollJob();
    const timer = window.setInterval(() => {
      pollJob();
    }, 2500);
    return () => {
      cancelled = true;
      window.clearInterval(timer);
    };
  }, [loadWorkstation, loadWorkstationDetail, professionalPhotoJob?.client_id, professionalPhotoJob?.job_id, professionalPhotoJob?.status]);

  async function refreshAll() {
    setLoading(true);
    try {
      await loadDashboard();
      await loadWorkstation();
      await loadRunnerStatus();
      if (selectedLeadId && isContadoresFunnel) {
        await loadDetail(selectedLeadId);
      }
      if (selectedWorkstationClientId) {
        await loadWorkstationDetail(selectedWorkstationClientId);
      }
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Could not refresh funnels.");
    } finally {
      setLoading(false);
    }
  }

  async function copySelectedLeadContext() {
    if (!selectedLead) {
      return;
    }

    const text = buildLeadContextText({
      lead: selectedLead,
      funnel: selectedFunnel,
      messages: selectedLeadDetail?.messages ?? [],
      inboxMode: isInboxFunnel,
    });

    try {
      await copyTextToClipboard(text);
      setLeadContextCopyStatus("Lead context copied.");
      window.setTimeout(() => {
        setLeadContextCopyStatus((current) => current === "Lead context copied." ? "" : current);
      }, 2200);
    } catch {
      setLeadContextCopyStatus("");
      setError("Could not copy lead context.");
    }
  }

  async function convertLeadToWorkstation() {
    const leadId = selectedLead?.id ?? selectedLeadId;
    if (!leadId) {
      return;
    }
    setActionBusy("convert-workstation");
    try {
      const payload = await apiFetch<WorkstationClientDetailResponse>(`/api/workstation/clients/from-lead/${leadId}`, {
        method: "POST",
      });
      setWorkstationDetail(payload);
      setWorkstationNotesDraft(payload.notes ?? "");
      setSelectedWorkstationClientId(payload.client.id);
      setActiveSection("workstation");
      await loadDashboard();
      await loadWorkstation();
      await loadDetail(leadId);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Could not convert this lead.");
    } finally {
      setActionBusy(null);
    }
  }

  async function startSoloPageWorkstation() {
    const leadId = selectedLead?.id ?? selectedLeadId;
    if (!leadId) {
      return;
    }
    const params = new URLSearchParams({
      work_type: "solo_pagina",
      status: "pending_payment",
      automation_status: "intake",
    });
    setActionBusy("convert-solo-page");
    try {
      const payload = await apiFetch<WorkstationClientDetailResponse>(
        `/api/workstation/clients/from-lead/${leadId}?${params.toString()}`,
        { method: "POST" },
      );
      setWorkstationDetail(payload);
      setWorkstationNotesDraft(payload.notes ?? "");
      setSelectedWorkstationClientId(payload.client.id);
      setActiveSection("workstation");
      await loadDashboard();
      await loadWorkstation();
      await loadDetail(leadId);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Could not start solo page Workstation.");
    } finally {
      setActionBusy(null);
    }
  }

  async function openWorkstationClient(clientId: string) {
    setSelectedWorkstationClientId(clientId);
    setActiveSection("workstation");
    setProfessionalPhotoMediaIds([]);
    setProfessionalPhotoContext("");
    setProfessionalPhotoEditPrompts({});
    try {
      const payload = await apiFetch<WorkstationClientDetailResponse>(`/api/workstation/clients/${clientId}`);
      setSelectedFunnelId(payload.client.funnel_id || "contadores");
      setWorkstationDetail(payload);
      setWorkstationNotesDraft(payload.notes ?? "");
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Could not open Workstation client.");
    }
  }

  function openCrmLeadFromWorkstation(lead: LeadSummary | null | undefined) {
    if (!lead) {
      return;
    }
    setSelectedFunnelId(lead.funnel_id || "contadores");
    setSelectedLeadId(lead.id);
    setActiveSection("crm");
  }

  async function saveWorkstationNotes() {
    const clientId = workstationDetail?.client.id ?? selectedWorkstationClientId;
    if (!clientId) {
      return;
    }
    setActionBusy("workstation-notes");
    try {
      const payload = await apiFetch<WorkstationClientDetailResponse>(`/api/workstation/clients/${clientId}/notes`, {
        method: "PUT",
        body: JSON.stringify({ notes: workstationNotesDraft }),
      });
      setWorkstationDetail(payload);
      setWorkstationNotesDraft(payload.notes ?? "");
      await loadWorkstation();
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Could not save notes.");
    } finally {
      setActionBusy(null);
    }
  }

  async function uploadWorkstationMediaFile(fileToUpload: File, title: string) {
    const clientId = workstationDetail?.client.id ?? selectedWorkstationClientId;
    if (!clientId) {
      return;
    }
    const form = new FormData();
    form.append("title", title);
    form.append("file", fileToUpload);
    setActionBusy("workstation-upload");
    try {
      await apiFetch(`/api/workstation/clients/${clientId}/media`, {
        method: "POST",
        body: form,
      });
      setWorkstationFile(null);
      setWorkstationFileTitle("");
      await loadWorkstation();
      await loadWorkstationDetail(clientId);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Could not upload media.");
    } finally {
      setActionBusy(null);
    }
  }

  async function uploadWorkstationMedia(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!workstationFile) {
      return;
    }
    await uploadWorkstationMediaFile(workstationFile, workstationFileTitle);
  }

  async function uploadWorkstationMediaFromFile(fileToUpload: File) {
    setWorkstationFile(fileToUpload);
    await uploadWorkstationMediaFile(fileToUpload, workstationFileTitle);
  }

  async function deleteWorkstationMedia(asset: WorkstationMediaAsset) {
    const clientId = workstationDetail?.client.id ?? selectedWorkstationClientId;
    if (!clientId || !window.confirm(`Delete ${asset.title || asset.original_filename}?`)) {
      return;
    }
    setActionBusy(`delete-media-${asset.id}`);
    try {
      const payload = await apiFetch<WorkstationClientDetailResponse>(
        `/api/workstation/clients/${clientId}/media/${asset.id}`,
        { method: "DELETE" },
      );
      setWorkstationDetail(payload);
      await loadWorkstation();
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Could not delete media.");
    } finally {
      setActionBusy(null);
    }
  }

  async function updateWorkstationMedia(asset: WorkstationMediaAsset, title: string, originalFilename: string) {
    const clientId = workstationDetail?.client.id ?? selectedWorkstationClientId;
    if (!clientId) {
      return;
    }
    setActionBusy(`edit-media-${asset.id}`);
    try {
      await apiFetch<WorkstationMediaAsset>(`/api/workstation/clients/${clientId}/media/${asset.id}`, {
        method: "PUT",
        body: JSON.stringify({
          title,
          original_filename: originalFilename,
        }),
      });
      await loadWorkstation();
      await loadWorkstationDetail(clientId);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Could not update media.");
    } finally {
      setActionBusy(null);
    }
  }

  function toggleProfessionalPhotoMedia(assetId: string) {
    setProfessionalPhotoMediaIds((current) => (
      current.includes(assetId)
        ? current.filter((id) => id !== assetId)
        : [...current, assetId]
    ));
  }

  async function createProfessionalPhoto(mediaAssetIds = professionalPhotoMediaIds, context = professionalPhotoContext) {
    const clientId = workstationDetail?.client.id ?? selectedWorkstationClientId;
    if (!clientId || mediaAssetIds.length === 0) {
      setError("Select at least one image from client media.");
      return false;
    }
    setActionBusy("professional-photo-start");
    try {
      const job = await apiFetch<WorkstationProfessionalPhotoJobResponse>(
        `/api/workstation/clients/${clientId}/professional-photo/jobs`,
        {
          method: "POST",
          body: JSON.stringify({
            media_asset_ids: mediaAssetIds,
            context,
          }),
        },
      );
      setProfessionalPhotoJob(job);
      setProfessionalPhotoContext("");
      setProfessionalPhotoMediaIds([]);
      return true;
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Could not create professional photo.");
      return false;
    } finally {
      setActionBusy(null);
    }
  }

  async function startSoloPageCodexWork(operatorPrompt: string) {
    const clientId = workstationDetail?.client.id ?? selectedWorkstationClientId;
    const prompt = operatorPrompt.trim();
    if (!clientId || !prompt) {
      setError("Escribi un prompt para Codex.");
      return false;
    }
    setActionBusy("solo-page-work");
    try {
      const payload = await apiFetch<WorkstationClientDetailResponse>(
        `/api/workstation/clients/${clientId}/solo-page/work`,
        {
          method: "POST",
          body: JSON.stringify({ prompt }),
          timeoutMs: 120_000,
        },
      );
      setWorkstationDetail(payload);
      loadWorkstation().catch((reason) => {
        setError(reason instanceof Error ? reason.message : "Could not refresh Workstation status.");
      });
      return true;
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Could not start Codex for this page.");
      return false;
    } finally {
      setActionBusy(null);
    }
  }

  async function stopSoloPageCodexWork() {
    const clientId = workstationDetail?.client.id ?? selectedWorkstationClientId;
    if (!clientId) {
      return;
    }
    setActionBusy("solo-page-stop");
    try {
      const payload = await apiFetch<WorkstationClientDetailResponse>(
        `/api/workstation/clients/${clientId}/solo-page/stop`,
        { method: "POST" },
      );
      setWorkstationDetail(payload);
      await loadWorkstation();
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Could not stop Codex for this page.");
    } finally {
      setActionBusy(null);
    }
  }

  async function steerSoloPageCodexWork(message: string) {
    const clientId = workstationDetail?.client.id ?? selectedWorkstationClientId;
    const cleanMessage = message.trim();
    if (!clientId || !cleanMessage) {
      setError("Escribi un mensaje para Codex.");
      return false;
    }
    setActionBusy("solo-page-steer");
    try {
      const payload = await apiFetch<WorkstationClientDetailResponse>(
        `/api/workstation/clients/${clientId}/solo-page/steer`,
        {
          method: "POST",
          body: JSON.stringify({ message: cleanMessage }),
        },
      );
      setWorkstationDetail(payload);
      await loadWorkstation();
      return true;
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Could not steer Codex for this page.");
      return false;
    } finally {
      setActionBusy(null);
    }
  }

  function updateProfessionalPhotoEditPrompt(version: string, prompt: string) {
    setProfessionalPhotoEditPrompts((current) => ({ ...current, [version]: prompt }));
  }

  async function editProfessionalPhoto(version: string) {
    const clientId = workstationDetail?.client.id ?? selectedWorkstationClientId;
    const prompt = professionalPhotoEditPrompts[version]?.trim() || "";
    if (!clientId || !prompt) {
      setError("Write an edit instruction first.");
      return;
    }
    setActionBusy(`professional-photo-edit-${version}`);
    try {
      await apiFetch<WorkstationProfessionalPhotoVersion>(
        `/api/workstation/clients/${clientId}/professional-photo/edit`,
        {
          method: "POST",
          body: JSON.stringify({
            base_version: version,
            prompt,
            media_asset_ids: professionalPhotoMediaIds,
          }),
        },
      );
      updateProfessionalPhotoEditPrompt(version, "");
      await loadWorkstationDetail(clientId);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Could not edit professional photo.");
    } finally {
      setActionBusy(null);
    }
  }

  async function copyWorkstationNotes() {
    await navigator.clipboard.writeText(workstationNotesDraft || "");
  }

  async function copyWorkstationAll() {
    const clientId = workstationDetail?.client.id ?? selectedWorkstationClientId;
    if (!clientId) {
      return;
    }
    const payload = await apiFetch<WorkstationCopyAllResponse>(`/api/workstation/clients/${clientId}/copy-all`);
    await navigator.clipboard.writeText(payload.text);
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

  async function submitSendModal(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const leadId = selectedLead?.id ?? selectedLeadId;
    if (!leadId) {
      return;
    }

    setActionBusy("send-modal");
    try {
      if (selectedLead?.stage === "closed") {
        setError("This lead is closed. Reopen it before sending WhatsApp messages.");
        return;
      }
      if (sendKind === "custom") {
        const text = manualText.trim();
        if (!text) {
          return;
        }
        if (selectedLeadCustomBlockReason) {
          setError(selectedLeadCustomBlockReason);
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
      if (bulkSendKind !== "set-tags" && bulkClosedCount > 0) {
        setError(`${bulkClosedCount} selected lead${bulkClosedCount === 1 ? " is" : "s are"} closed. Reopen before sending WhatsApp messages.`);
        return;
      }
      if (bulkSendKind === "custom" && bulkCustomBlockedCount > 0) {
        setError(`Custom WhatsApp is blocked for ${bulkCustomBlockedCount} selected chat${bulkCustomBlockedCount === 1 ? "" : "s"} because the 24-hour window is closed. Use Manual ping template instead.`);
        return;
      }
      const payload = await apiFetch<BulkActionResponse>("/api/contadores/leads/bulk-action", {
        method: "POST",
        body: JSON.stringify({
          lead_ids: leadIds,
          action: bulkSendKind,
          manual_ping_confirmed: bulkSendKind === "send-manual-ping" ? bulkManualPingConfirmed : false,
          text: bulkSendKind === "custom" ? manualText.trim() : null,
          tags: bulkSendKind === "set-tags"
            ? bulkTagsDraft.split(",").map((tag) => tag.trim()).filter(Boolean)
            : [],
        }),
      });
      if (payload.failed) {
        setError(`${payload.succeeded} updated, ${payload.failed} failed. Check selection and action settings.`);
      }
      setShowBulkSendModal(false);
      setSelectedLeadIds([]);
      if (bulkSendKind === "custom") {
        setManualText("");
      }
      if (bulkSendKind === "set-tags") {
        setBulkTagsDraft("");
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
    if (!leadId || (!text && !manualFiles.length)) {
      return;
    }
    if (selectedLeadCustomBlockReason) {
      setError(selectedLeadCustomBlockReason);
      return;
    }

    setActionBusy("manual-dock");
    try {
      await queueCustomManualMessage(leadId, text, manualFiles);
      await loadDashboard();
      await loadDetail(leadId);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Could not send the message.");
    } finally {
      setActionBusy(null);
    }
  }

  async function queueCustomManualMessage(leadId: string, text: string, files: File[] = []) {
    if (files.length) {
      const form = new FormData();
      form.append("text", text);
      files.forEach((file) => form.append("file", file));
      await apiFetch<QuickActionResponse>(`/api/contadores/leads/${leadId}/messages/manual-media`, {
        method: "POST",
        body: form,
      });
    } else {
      await apiFetch<QuickActionResponse>(`/api/contadores/leads/${leadId}/messages/manual`, {
        method: "POST",
        body: JSON.stringify({ text }),
      });
    }
    setManualText("");
    setManualFiles([]);
  }

  async function acknowledgeDeliveryError(message: MessageItem) {
    const leadId = message.lead_id || selectedLeadId;
    if (!leadId || acknowledgingDeliveryErrorIds.includes(message.id)) {
      return;
    }
    const deliveryStatus = String(message.delivery_status || "").toLowerCase();
    if (!message.from_me || deliveryStatus !== "failed" || message.delivery_error_acknowledged_at) {
      return;
    }

    setAcknowledgingDeliveryErrorIds((current) => [...current, message.id]);
    try {
      await apiFetch<MessageItem>(`/api/contadores/messages/${message.id}/delivery-error/acknowledge`, {
        method: "POST",
      });
      await loadDashboard();
      await loadDetail(leadId);
      if (selectedWorkstationClientId) {
        await loadWorkstationDetail(selectedWorkstationClientId);
      }
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Could not mark the delivery error as seen.");
    } finally {
      setAcknowledgingDeliveryErrorIds((current) => current.filter((id) => id !== message.id));
    }
  }

  async function moveLeadToFunnel(targetFunnelId: string, targetStage: LeadStage) {
    const leadId = selectedLead?.id ?? selectedLeadId;
    if (!leadId) {
      return;
    }
    setActionBusy("move-lead");
    try {
      const moved = await apiFetch<LeadSummary>(`/api/contadores/leads/${leadId}/move`, {
        method: "POST",
        body: JSON.stringify({ funnel_id: targetFunnelId, stage: targetStage }),
      });
      setSelectedFunnelId(moved.funnel_id);
      setSelectedLeadId(moved.id);
      await loadDashboard();
      await loadDetail(moved.id);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Could not move the lead.");
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
  const totalManualAttentionCount = Object.values(manualAttentionCounts).reduce((total, count) => total + count, 0);
  const showGlobalCrmAttentionBadge = activeSection !== "crm" && totalManualAttentionCount > 0;
  const workstationTitle = selectedFunnel
    ? `Workstation · ${selectedFunnel.label}`
    : "Workstation";
  const syncStatus = activeSection === "runner"
    ? runnerStatus?.running
      ? `Running${runnerStatus.pid ? ` · pid ${runnerStatus.pid}` : ""}`
      : runnerStatus?.latest_summary_updated_at
        ? `Idle · ${relativeTime(runnerStatus.latest_summary_updated_at)}`
        : "Runner idle"
    : activeSection === "workstation"
    ? `${workstationClients.length} converted ${workstationClients.length === 1 ? "client" : "clients"}`
    : config?.last_sheet_sync_status
    ? `${config.last_sheet_sync_status} · ${config.last_sheet_sync_at ? relativeTime(config.last_sheet_sync_at) : "never"}`
    : runtime
      ? (runtime.ready ? "Ready" : "Review config")
      : "Sync idle";

  return (
    <section id="contadoresView" className="contadores-view" data-app="contadores">
      <header className="ct-topbar">
        <div className="ct-topbar-brand">
          <span className="ct-brand-mark" aria-hidden="true">{monogram(selectedFunnel?.label || "Funnels")}</span>
          <div className="ct-brand-copy">
            <p className="ct-brand-word">
              {activeSection === "runner" ? "Runner" : activeSection === "workstation" ? workstationTitle : selectedFunnel?.label || "Funnels"}
            </p>
            <span className={`ct-sync-badge ${config?.last_sheet_sync_status === "ok" ? "has-unread" : ""}`}>{syncStatus}</span>
          </div>
        </div>

        <nav className="ct-section-switch" aria-label="Primary workspace">
          <button
            type="button"
            className={activeSection === "crm" ? "active" : ""}
            aria-label={showGlobalCrmAttentionBadge ? `CRM, ${totalManualAttentionCount} needs answer` : "CRM"}
            onClick={() => setActiveSection("crm")}
          >
            CRM
            {showGlobalCrmAttentionBadge ? (
              <span className="ct-section-badge">{compactNumber(totalManualAttentionCount)}</span>
            ) : null}
          </button>
          <button
            type="button"
            className={activeSection === "workstation" ? "active" : ""}
            onClick={() => setActiveSection("workstation")}
          >
            Workstation
          </button>
          <button
            type="button"
            className={activeSection === "runner" ? "active" : ""}
            onClick={() => setActiveSection("runner")}
          >
            Runner
          </button>
        </nav>

        {activeSection === "crm" || activeSection === "workstation" ? (
          <nav className="ct-topbar-nav" aria-label={activeSection === "workstation" ? "Workstation funnels" : "Backoffice sections"}>
            {funnels.map((funnel) => {
              const attentionCount = manualAttentionCounts[funnel.id] ?? 0;

              return (
                <button
                  key={funnel.id}
                  type="button"
                  className={`ct-nav-btn ${selectedFunnelId === funnel.id ? "active" : ""}`}
                  onClick={() => setSelectedFunnelId(funnel.id)}
                >
                  <span>{funnel.label}</span>
                  {activeSection === "crm" && attentionCount > 0 ? (
                    <span className="ct-nav-badge" aria-label={`${attentionCount} needs answer`}>
                      {compactNumber(attentionCount)}
                    </span>
                  ) : null}
                </button>
              );
            })}
            {activeSection === "crm" ? (
              <button type="button" className="ct-nav-btn ct-nav-add" onClick={openCreateFunnel}>+ Funnel</button>
            ) : null}
          </nav>
        ) : null}

        <div className="ct-topbar-tools">
          {activeSection === "crm" ? (
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
          ) : activeSection === "workstation" ? (
          <label className="ct-search">
            <span className="ct-search-icon" aria-hidden="true" />
            <input
              value={workstationQuery}
              onChange={(event) => setWorkstationQuery(event.target.value)}
              type="text"
              placeholder="Search clients, phone, email, folder"
              autoComplete="off"
            />
          </label>
          ) : null}
          {activeSection !== "runner" ? (
            <button type="button" className="ct-icon-btn" onClick={openEditFunnel} disabled={!selectedFunnel}>Funnel</button>
          ) : null}
          {activeSection === "crm" && isContadoresFunnel ? (
            <button type="button" className="ct-icon-btn" onClick={() => setShowConfig(true)}>Runtime</button>
          ) : null}
          <button type="button" className="ct-icon-btn" onClick={refreshAll} disabled={loading}>Refresh</button>
        </div>
      </header>

      <main className="ct-main-slot">
        {error ? (
          <div className="ct-error" role="alert">
            <span>{error}</span>
            <button type="button" className="ct-icon-btn" onClick={() => setError(null)}>Dismiss</button>
          </div>
        ) : null}

        {activeSection === "runner" ? (
        <RunnerStatusView
          status={runnerStatus}
          loading={runnerLoading}
          onRefresh={() => {
            setRunnerLoading(true);
            loadRunnerStatus()
              .catch((reason) => setError(reason instanceof Error ? reason.message : "Could not refresh the runner."))
              .finally(() => setRunnerLoading(false));
          }}
        />
        ) : activeSection === "workstation" ? (
        <WorkstationView
          clients={workstationClients}
          detail={workstationDetail}
          funnel={selectedFunnel}
          selectedClientId={selectedWorkstationClientId}
          loading={workstationLoading}
          actionBusy={actionBusy}
          notesDraft={workstationNotesDraft}
          fileTitle={workstationFileTitle}
          file={workstationFile}
          selectedProfessionalPhotoMediaIds={professionalPhotoMediaIds}
          professionalPhotoContext={professionalPhotoContext}
          professionalPhotoEditPrompts={professionalPhotoEditPrompts}
          professionalPhotoJob={professionalPhotoJob}
          onSelectClient={(clientId) => {
            setSelectedWorkstationClientId(clientId);
            setProfessionalPhotoMediaIds([]);
            setProfessionalPhotoContext("");
            setProfessionalPhotoEditPrompts({});
          }}
          onNotesChange={setWorkstationNotesDraft}
          onSaveNotes={saveWorkstationNotes}
          onCopyNotes={() => copyWorkstationNotes().catch((reason) => setError(reason instanceof Error ? reason.message : "Could not copy notes."))}
          onCopyAll={() => copyWorkstationAll().catch((reason) => setError(reason instanceof Error ? reason.message : "Could not copy client context."))}
          onOpenCrmLead={openCrmLeadFromWorkstation}
          acknowledgingDeliveryErrorIds={acknowledgingDeliveryErrorIds}
          onAcknowledgeDeliveryError={acknowledgeDeliveryError}
          onFileTitleChange={setWorkstationFileTitle}
          onFileChange={setWorkstationFile}
          onUploadMedia={uploadWorkstationMedia}
          onUploadMediaFile={(fileToUpload) => {
            uploadWorkstationMediaFromFile(fileToUpload).catch((reason) => {
              setError(reason instanceof Error ? reason.message : "Could not upload media.");
            });
          }}
          onDeleteMedia={deleteWorkstationMedia}
          onUpdateMedia={(asset, title, originalFilename) => updateWorkstationMedia(asset, title, originalFilename)}
          onToggleProfessionalPhotoMedia={toggleProfessionalPhotoMedia}
          onProfessionalPhotoMediaIdsChange={setProfessionalPhotoMediaIds}
          onProfessionalPhotoContextChange={setProfessionalPhotoContext}
          onCreateProfessionalPhoto={createProfessionalPhoto}
          onStartSoloPageCodexWork={startSoloPageCodexWork}
          onStopSoloPageCodexWork={stopSoloPageCodexWork}
          onSteerSoloPageCodexWork={steerSoloPageCodexWork}
          onProfessionalPhotoEditPromptChange={updateProfessionalPhotoEditPrompt}
          onEditProfessionalPhoto={(version) => editProfessionalPhoto(version)}
        />
        ) : !isContadoresFunnel ? (
        <FunnelSetupView
          funnel={selectedFunnel}
          configPath={funnelConfigPath}
          onEdit={openEditFunnel}
        />
        ) : (
      <div className="ct-surface">
        {!isInboxFunnel ? (
          <section className="ct-pipeline" aria-label="Lead stages">
            {stageFilters.map((filter) => {
              const count = filter.value === "manual_attention"
                ? manualAttentionList.length
                : Number(metrics?.[filter.metric ?? "total"] ?? 0);

              return (
                <button
                  key={filter.value}
                  type="button"
                  className={`ct-stage ${stageFilter === filter.value ? "active" : ""}`}
                  data-tone={filter.tone}
                  aria-pressed={stageFilter === filter.value}
                  onClick={() => setStageFilter(filter.value)}
                >
                  <span className="ct-stage-count">{compactNumber(count)}</span>
                  <span className="ct-stage-label">{filter.label}</span>
                </button>
              );
            })}
          </section>
        ) : null}

        <div className="ct-secondary">
          <div className="ct-filter-strip" role="group" aria-label="Lead filters">
            {!isInboxFunnel && strategyStats.length ? (
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

            {tagOptions.length ? (
              <>
                <button
                  type="button"
                  className={`ct-strategy-filter-btn ${!tagFilter ? "active" : ""}`}
                  onClick={() => setTagFilter("")}
                >
                  All tags
                </button>
                {tagOptions.map((tag) => (
                  <button
                    type="button"
                    className={`ct-strategy-filter-btn ${tagFilter === tag ? "active" : ""}`}
                    key={tag}
                    onClick={() => setTagFilter(tag)}
                  >
                    #{tag}
                  </button>
                ))}
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
                  setBulkSendKind("custom");
                  setBulkManualPingConfirmed(false);
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
              inboxMode={isInboxFunnel}
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
              onManualBooked={() => runAction("mark-booked")}
              onManualHandoff={() => runAction("manual-handoff")}
              onMarkAnswered={() => runAction("mark-answered")}
              onToggleClosed={() => runAction(selectedLead?.stage === "closed" ? "reopen" : "close")}
              onDelete={deleteLead}
              onConvert={convertLeadToWorkstation}
              onStartSoloPage={startSoloPageWorkstation}
              onCopyContext={copySelectedLeadContext}
              onOpenWorkstation={openWorkstationClient}
              copyStatus={leadContextCopyStatus}
              inboxMode={isInboxFunnel}
            />

            {!isInboxFunnel ? (
              <PausedBanner lead={selectedLead} />
            ) : null}
            {isInboxFunnel ? (
              <MoveLeadPanel
                lead={selectedLead}
                funnels={funnels}
                busy={actionBusy === "move-lead"}
                onMove={moveLeadToFunnel}
              />
            ) : null}

            {!isInboxFunnel ? (
              <div className="ct-tabs" role="tablist" aria-label="Lead detail sections">
                {(["messages", "strategies"] as DetailTab[]).map((tab) => (
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
            ) : null}

            <div className="ct-panes">
              <section className={`ct-pane ${isInboxFunnel || activeTab === "messages" ? "active" : ""}`}>
                <MessageTimeline
                  messages={selectedLeadDetail?.messages ?? []}
                  loading={detailLoading}
                  hasLead={Boolean(selectedLead)}
                  acknowledgingIds={acknowledgingDeliveryErrorIds}
                  onAcknowledgeDeliveryError={acknowledgeDeliveryError}
                />
              </section>

              {!isInboxFunnel ? (
                <section className={`ct-pane ${activeTab === "strategies" ? "active" : ""}`}>
                  <LeadStrategies messages={selectedLeadDetail?.messages ?? []} loading={detailLoading} hasLead={Boolean(selectedLead)} />
                </section>
              ) : null}
            </div>

            <ManualDock
              disabled={!selectedLead || Boolean(actionBusy)}
              blockReason={selectedLeadCustomBlockReason}
              value={manualText}
              files={manualFiles}
              onChange={setManualText}
              onFilesChange={setManualFiles}
              onSubmit={submitManualDock}
            />
          </section>
        </div>
      </div>
        )}
      </main>

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
          customBlockReason={selectedLeadCustomBlockReason}
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
          tagsText={bulkTagsDraft}
          funnel={selectedFunnel}
          selectedCount={selectedLeadIds.length}
          customBlockedCount={bulkCustomBlockedCount}
          closedCount={bulkClosedCount}
          manualPingConfirmed={bulkManualPingConfirmed}
          busy={actionBusy === "bulk-send-modal"}
          onKindChange={(nextKind) => {
            setBulkSendKind(nextKind);
            setBulkManualPingConfirmed(false);
          }}
          onManualPingConfirmedChange={setBulkManualPingConfirmed}
          onTextChange={setManualText}
          onTagsTextChange={setBulkTagsDraft}
          onClose={() => setShowBulkSendModal(false)}
          onSubmit={submitBulkSendModal}
        />
      ) : null}
    </section>
  );
}

function RunnerStatusView({
  status,
  loading,
  onRefresh,
}: {
  status: RunnerStatusResponse | null;
  loading: boolean;
  onRefresh: () => void;
}) {
  const logs = status?.logs ?? [];
  const [codexRequest, setCodexRequest] = useState("");
  const [copyStatus, setCopyStatus] = useState("Arma un prompt nuevo con el delta, el ultimo run y el historial.");
  const delta = status?.delta ?? null;
  const attentionEvents = delta?.attention_events ?? [];
  const allEvents = delta?.events ?? [];
  const deltaMetrics = delta?.metrics ?? {
    total_leads: 0,
    new_replies: 0,
    needs_action: 0,
    new_outbound: 0,
    delivery_changes: 0,
    state_changes: 0,
    due_next_steps: 0,
    new_exclusions: 0,
  };
  const hasBaseline = Boolean(delta?.baseline_available);
  const latestSummaryUpdated = status?.latest_summary_updated_at ? relativeTime(status.latest_summary_updated_at) : "No run yet";
  const latestSummaryMarkdown = status?.latest_summary || "No run summary has been written yet.";
  const historyMarkdown = status?.history_markdown || latestSummaryMarkdown;
  const deltaMarkdown = delta?.markdown || "No structured delta has been written yet. The next run will create one.";
  const runnerMode = status?.running
    ? "running"
    : deltaMetrics.needs_action > 0
      ? "danger"
      : deltaMetrics.new_replies + deltaMetrics.delivery_changes + deltaMetrics.due_next_steps > 0
        ? "watch"
        : "clean";
  const runnerModeLabel = runnerMode === "running" ? "Running" : runnerMode === "danger" ? "Review" : runnerMode === "watch" ? "Watch" : "Clean";
  const visibleEvents = allEvents.slice(0, 12);
  const codexPrompt = buildRunnerCodexPrompt({
    request: codexRequest,
    deltaMarkdown,
    latestSummary: latestSummaryMarkdown,
    historyMarkdown,
  });

  async function copyRunnerText(value: string, label: string) {
    await copyTextToClipboard(value);
    setCopyStatus(`${label} copiado.`);
  }

  return (
    <div className="ct-surface runner-surface" data-runner-mode={runnerMode}>
      <section className="runner-hero" aria-label="Runner status">
        <div className="runner-status-symbol" aria-hidden="true">
          {runnerMode === "running" ? (
            <Pulse size={42} weight="fill" />
          ) : runnerMode === "danger" ? (
            <WarningCircle size={42} weight="fill" />
          ) : runnerMode === "watch" ? (
            <BellRinging size={42} weight="fill" />
          ) : (
            <CheckCircle size={42} weight="fill" />
          )}
        </div>
        <div className="runner-status-copy">
          <span>{latestSummaryUpdated}</span>
          <strong>{runnerModeLabel}</strong>
          <small>
            {hasBaseline ? `${shortRunnerTime(delta?.previous_generated_at)} -> ${shortRunnerTime(delta?.current_generated_at)}` : "baseline"}
          </small>
        </div>
        <div className="runner-status-sparks" aria-label="Recent run timeline">
          {logs.slice(0, 8).map((log, index) => (
            <span
              key={log.path}
              className="runner-spark"
              data-hot={index === 0}
              title={`${log.modified_at ? relativeTime(log.modified_at) : "-"} · ${formatBytes(log.size_bytes)}`}
            />
          ))}
          {!logs.length ? <span className="runner-spark" /> : null}
        </div>
        <button type="button" className="runner-refresh-button" onClick={onRefresh} disabled={loading} aria-label="Refresh runner">
          {loading ? <SpinnerGap size={18} weight="bold" /> : <ArrowsClockwise size={18} weight="bold" />}
        </button>
      </section>

      <section className="runner-command-center" aria-label="Runner command center">
        <RunnerSignal icon={<WarningCircle size={30} weight="fill" />} label="Action" value={deltaMetrics.needs_action} tone={deltaMetrics.needs_action > 0 ? "danger" : "ok"} />
        <RunnerSignal icon={<ChatCircleText size={30} weight="fill" />} label="Replies" value={deltaMetrics.new_replies} tone={deltaMetrics.new_replies > 0 ? "blue" : "neutral"} />
        <RunnerSignal icon={<ClockCountdown size={30} weight="fill" />} label="Due" value={deltaMetrics.due_next_steps} tone={deltaMetrics.due_next_steps > 0 ? "warn" : "neutral"} />
        <RunnerSignal icon={<PaperPlaneTilt size={30} weight="fill" />} label="Sent" value={deltaMetrics.new_outbound} tone={deltaMetrics.new_outbound > 0 ? "green" : "neutral"} />
        <RunnerSignal icon={<Pulse size={30} weight="fill" />} label="Delivery" value={deltaMetrics.delivery_changes} tone={deltaMetrics.delivery_changes > 0 ? "violet" : "neutral"} />
      </section>

      <section className="runner-layout">
        <div className="runner-priority-column">
          <RunnerPanel eyebrow={<ListChecks size={18} weight="fill" />} title="Action queue" meta={`${attentionEvents.length}`}>
            {attentionEvents.length ? (
              <div className="runner-event-stack">
                {attentionEvents.slice(0, 8).map((event) => (
                  <RunnerEventCard event={event} key={`${event.kind}:${event.lead_id}:${event.occurred_at || ""}`} />
                ))}
              </div>
            ) : (
              <RunnerEmpty
                tone="clean"
                icon={<CheckCircle size={44} weight="fill" />}
                title={hasBaseline ? "Clean" : "Baseline"}
                text={hasBaseline ? "0" : "1"}
              />
            )}
          </RunnerPanel>

          <RunnerPanel eyebrow={<TrendUp size={18} weight="fill" />} title="Delta stream" meta={`${visibleEvents.length}`}>
            <div className="runner-visual-feed">
              {visibleEvents.length ? visibleEvents.map((event) => (
                <RunnerCompactEvent event={event} key={`${event.kind}:${event.lead_id}:${event.occurred_at || ""}`} />
              )) : (
                <RunnerEmpty tone="quiet" icon={<Pulse size={38} weight="fill" />} title="Stable" text="0" />
              )}
            </div>
          </RunnerPanel>
        </div>

        <aside className="runner-side-column">
          <RunnerPanel eyebrow={<Robot size={18} weight="fill" />} title="Codex" meta="">
            <textarea
              className="runner-question"
              value={codexRequest}
              onChange={(event) => setCodexRequest(event.target.value)}
              placeholder="Que hago con Daniel?"
            />
            <div className="runner-actions">
              <button
                type="button"
                className="ct-btn ct-btn-primary"
                onClick={() => copyRunnerText(codexPrompt, "Prompt").catch(() => setCopyStatus("No pude copiar el prompt automaticamente."))}
              >
                Prompt
              </button>
              <button
                type="button"
                className="ct-btn ct-btn-ghost"
                onClick={() => copyRunnerText(buildRunnerCodexCommand(codexPrompt), "Comando").catch(() => setCopyStatus("No pude copiar el comando automaticamente."))}
              >
                Exec
              </button>
            </div>
            <p className="runner-copy-status">{copyStatus}</p>
          </RunnerPanel>

          <RunnerPanel eyebrow={<ClockCountdown size={18} weight="fill" />} title="Runs" meta={`${logs.length}`}>
            <ol className="runner-timeline">
              {logs.length ? logs.slice(0, 8).map((log, index) => (
                <li key={log.path} data-current={index === 0}>
                  <span className="runner-timeline-dot" />
                  <div>
                    <strong>{log.modified_at ? relativeTime(log.modified_at) : "-"}</strong>
                    <span>{formatBytes(log.size_bytes)}</span>
                  </div>
                </li>
              )) : (
                <li><span className="runner-timeline-dot" /><div><strong>-</strong><span>0</span></div></li>
              )}
            </ol>
          </RunnerPanel>
        </aside>
      </section>

      <div className="runner-disclosure-row">
        <details className="runner-history-details">
          <summary>Last run</summary>
          <MarkdownBlock markdown={latestSummaryMarkdown} className="runner-last-markdown" />
        </details>

        <details className="runner-history-details">
          <summary>Counts</summary>
          <RunnerDeltaTable
            bucketDeltas={delta?.bucket_deltas ?? []}
            failureDeltas={delta?.failure_deltas ?? []}
            exclusionDeltas={delta?.exclusion_deltas ?? []}
          />
        </details>

        <details className="runner-history-details">
          <summary>History</summary>
          <MarkdownBlock markdown={historyMarkdown} className="runner-history-markdown" />
        </details>

        <details className="runner-technical">
          <summary>Tech</summary>
          <div className="runner-tail-grid" aria-label="Runner log tails">
            <RunnerTail title="Latest run tail" text={status?.latest_log_tail || ""} />
            <RunnerTail title="LaunchAgent stdout" text={status?.launchd_out_tail || ""} />
            <RunnerTail title="LaunchAgent stderr" text={status?.launchd_err_tail || ""} />
          </div>
        </details>
      </div>
    </div>
  );
}

function RunnerSignal({
  icon,
  label,
  value,
  tone,
}: {
  icon: ReactNode;
  label: string;
  value: number;
  tone: "danger" | "warn" | "blue" | "green" | "violet" | "ok" | "neutral";
}) {
  return (
    <div className="runner-signal" data-tone={tone} aria-label={`${label}: ${value}`}>
      <div className="runner-signal-icon" aria-hidden="true">{icon}</div>
      <span>{label}</span>
      <strong>{compactNumber(value)}</strong>
    </div>
  );
}

function RunnerPanel({
  eyebrow,
  title,
  meta,
  children,
}: {
  eyebrow: ReactNode;
  title: string;
  meta: string;
  children: ReactNode;
}) {
  return (
    <section className="runner-panel">
      <div className="runner-panel-head">
        <div>
          <span>{eyebrow}</span>
          <strong>{title}</strong>
        </div>
        {meta ? <em>{meta}</em> : null}
      </div>
      {children}
    </section>
  );
}

function RunnerEventCard({ event }: { event: RunnerDeltaEvent }) {
  return (
    <article className="runner-event-card" data-severity={event.severity}>
      <div className="runner-event-icon" aria-hidden="true">{runnerKindIcon(event.kind)}</div>
      <div className="runner-event-topline">
        <span>{formatRunnerKind(event.kind)}</span>
        <time>{event.occurred_at ? relativeTime(event.occurred_at) : "changed"}</time>
      </div>
      <h3>{event.full_name || event.phone || "Unknown lead"}</h3>
      <div className="runner-event-action">{event.suggested_action}</div>
    </article>
  );
}

function RunnerCompactEvent({ event }: { event: RunnerDeltaEvent }) {
  return (
    <div className="runner-compact-event" data-severity={event.severity}>
      <span className="runner-compact-icon" aria-hidden="true">{runnerKindIcon(event.kind)}</span>
      <div>
        <strong>{event.full_name || event.title}</strong>
        <p>{formatRunnerKind(event.kind)}</p>
      </div>
      <time>{event.occurred_at ? relativeTime(event.occurred_at) : "-"}</time>
    </div>
  );
}

function RunnerDeltaTable({
  bucketDeltas,
  failureDeltas,
  exclusionDeltas,
}: {
  bucketDeltas: Array<{ key: string; previous: number; current: number; delta: number }>;
  failureDeltas: Array<{ key: string; previous: number; current: number; delta: number }>;
  exclusionDeltas: Array<{ key: string; previous: number; current: number; delta: number }>;
}) {
  const rows = [
    ...bucketDeltas.map((row) => ({ ...row, group: "Bucket" })),
    ...failureDeltas.map((row) => ({ ...row, group: "Provider" })),
    ...exclusionDeltas.map((row) => ({ ...row, group: "Excluded" })),
  ].slice(0, 14);

  if (!rows.length) {
    return <RunnerEmpty tone="quiet" icon={<CheckCircle size={34} weight="fill" />} title="Stable" text="0" />;
  }

  return (
    <div className="runner-delta-table">
      {rows.map((row) => (
        <div className="runner-delta-row" key={`${row.group}:${row.key}`}>
          <span>{row.group}</span>
          <strong>{humanize(row.key)}</strong>
          <code>{`${row.previous} -> ${row.current}`}</code>
          <em data-positive={row.delta > 0}>{row.delta > 0 ? `+${row.delta}` : row.delta}</em>
        </div>
      ))}
    </div>
  );
}

function RunnerEmpty({ tone, icon, title, text }: { tone: "clean" | "quiet"; icon: ReactNode; title: string; text: string }) {
  return (
    <div className="runner-empty-state" data-tone={tone}>
      <div aria-hidden="true">{icon}</div>
      <strong>{title}</strong>
      <p>{text}</p>
    </div>
  );
}

function formatRunnerKind(value: string): string {
  const labels: Record<string, string> = {
    booking_time_provided: "Booking intent",
    new_reply: "New reply",
    delivery_changed: "Delivery",
    state_changed: "State",
    due_next_step: "Due",
    outbound_sent: "Outbound",
    new_exclusion: "Excluded",
    new_lead: "New lead",
  };
  return labels[value] ?? humanize(value);
}

function runnerKindIcon(value: string): ReactNode {
  if (value === "booking_time_provided" || value === "due_next_step") {
    return <ClockCountdown size={18} weight="fill" />;
  }
  if (value === "new_reply") {
    return <ChatCircleText size={18} weight="fill" />;
  }
  if (value === "delivery_changed") {
    return <Pulse size={18} weight="fill" />;
  }
  if (value === "outbound_sent") {
    return <PaperPlaneTilt size={18} weight="fill" />;
  }
  if (value === "state_changed") {
    return <ListChecks size={18} weight="fill" />;
  }
  if (value === "new_exclusion") {
    return <WarningCircle size={18} weight="fill" />;
  }
  return <TrendUp size={18} weight="fill" />;
}

function shortRunnerTime(value: string | null | undefined): string {
  if (!value) {
    return "-";
  }
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) {
    return value;
  }
  return new Intl.DateTimeFormat("en", {
    hour: "2-digit",
    minute: "2-digit",
  }).format(date);
}

function MarkdownBlock({ markdown, className = "" }: { markdown: string; className?: string }) {
  const html = useMemo(() => {
    const escapedMarkdown = escapeMarkdownHtml(neutralizeMarkdownImages(markdown || ""));
    return marked.parse(escapedMarkdown, { async: false, breaks: true }) as string;
  }, [markdown]);

  return (
    <div
      className={`runner-markdown ${className}`}
      dangerouslySetInnerHTML={{ __html: html || "<p>No notes yet.</p>" }}
    />
  );
}

function neutralizeMarkdownImages(value: string): string {
  return value
    .replace(/!\[([^\]]*)\]\(([^)]*)\)/g, "[$1]($2)")
    .replace(/!\[([^\]]*)\]/g, "$1");
}

function escapeMarkdownHtml(value: string): string {
  return value
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;");
}

async function copyTextToClipboard(value: string): Promise<void> {
  if (navigator.clipboard?.writeText) {
    await navigator.clipboard.writeText(value);
    return;
  }
  const textarea = document.createElement("textarea");
  textarea.value = value;
  textarea.setAttribute("readonly", "true");
  textarea.style.position = "fixed";
  textarea.style.left = "-9999px";
  document.body.appendChild(textarea);
  textarea.select();
  const copied = document.execCommand("copy");
  document.body.removeChild(textarea);
  if (!copied) {
    throw new Error("clipboard unavailable");
  }
}

function buildRunnerCodexPrompt({
  request,
  deltaMarkdown,
  latestSummary,
  historyMarkdown,
}: {
  request: string;
  deltaMarkdown: string;
  latestSummary: string;
  historyMarkdown: string;
}): string {
  return [
    "In /Users/fgoiriz/private/repos/contadores, read .codex/skills/contadores-crm-followup-automation/SKILL.md first.",
    "Use the CRM follow-up run context below and answer or act on my request.",
    "Do not send live messages unless my request explicitly asks you to and the skill allows it.",
    "",
    "## My request",
    request.trim() || "(write the request here)",
    "",
    "## Delta since previous run",
    deltaMarkdown,
    "",
    "## Latest run",
    latestSummary,
    "",
    "## Accumulated run notes",
    historyMarkdown,
  ].join("\n");
}

function buildRunnerCodexCommand(prompt: string): string {
  return `cat <<'CODEX_PROMPT' | codex exec -C /Users/fgoiriz/private/repos/contadores -m gpt-5.5 --dangerously-bypass-approvals-and-sandbox -\n${prompt}\nCODEX_PROMPT`;
}

function RunnerTail({ title, text }: { title: string; text: string }) {
  return (
    <section className="workstation-panel runner-tail-panel">
      <div className="workstation-panel-head">
        <div>
          <span>Log tail</span>
          <strong>{title}</strong>
        </div>
      </div>
      <pre className="runner-pre">{text || "No lines yet."}</pre>
    </section>
  );
}

function WorkstationView({
  clients,
  detail,
  funnel,
  selectedClientId,
  loading,
  actionBusy,
  notesDraft,
  fileTitle,
  file,
  onSelectClient,
  onNotesChange,
  onSaveNotes,
  onCopyNotes,
  onCopyAll,
  onOpenCrmLead,
  acknowledgingDeliveryErrorIds,
  onAcknowledgeDeliveryError,
  onFileTitleChange,
  onFileChange,
  onUploadMedia,
  onUploadMediaFile,
  onDeleteMedia,
  onUpdateMedia,
  selectedProfessionalPhotoMediaIds,
  professionalPhotoContext,
  professionalPhotoEditPrompts,
  professionalPhotoJob,
  onToggleProfessionalPhotoMedia,
  onProfessionalPhotoMediaIdsChange,
  onProfessionalPhotoContextChange,
  onCreateProfessionalPhoto,
  onStartSoloPageCodexWork,
  onStopSoloPageCodexWork,
  onSteerSoloPageCodexWork,
  onProfessionalPhotoEditPromptChange,
  onEditProfessionalPhoto,
}: {
  clients: WorkstationClientSummary[];
  detail: WorkstationClientDetailResponse | null;
  funnel: FunnelDefinition | null;
  selectedClientId: string | null;
  loading: boolean;
  actionBusy: string | null;
  notesDraft: string;
  fileTitle: string;
  file: File | null;
  selectedProfessionalPhotoMediaIds: string[];
  professionalPhotoContext: string;
  professionalPhotoEditPrompts: Record<string, string>;
  professionalPhotoJob: WorkstationProfessionalPhotoJobResponse | null;
  onSelectClient: (clientId: string) => void;
  onNotesChange: (notes: string) => void;
  onSaveNotes: () => void;
  onCopyNotes: () => void;
  onCopyAll: () => void;
  onOpenCrmLead: (lead: LeadSummary | null | undefined) => void;
  acknowledgingDeliveryErrorIds: number[];
  onAcknowledgeDeliveryError: (message: MessageItem) => void | Promise<void>;
  onFileTitleChange: (value: string) => void;
  onFileChange: (file: File | null) => void;
  onUploadMedia: (event: FormEvent<HTMLFormElement>) => void;
  onUploadMediaFile: (file: File) => void;
  onDeleteMedia: (asset: WorkstationMediaAsset) => void;
  onUpdateMedia: (asset: WorkstationMediaAsset, title: string, originalFilename: string) => void | Promise<void>;
  onToggleProfessionalPhotoMedia: (assetId: string) => void;
  onProfessionalPhotoMediaIdsChange: (assetIds: string[]) => void;
  onProfessionalPhotoContextChange: (value: string) => void;
  onCreateProfessionalPhoto: (mediaAssetIds?: string[], context?: string) => boolean | Promise<boolean>;
  onStartSoloPageCodexWork: (operatorPrompt: string) => boolean | Promise<boolean>;
  onStopSoloPageCodexWork: () => void | Promise<void>;
  onSteerSoloPageCodexWork: (message: string) => boolean | Promise<boolean>;
  onProfessionalPhotoEditPromptChange: (version: string, prompt: string) => void;
  onEditProfessionalPhoto: (version: string) => void;
}) {
  const detailClient = detail?.client.id === selectedClientId ? detail.client : null;
  const selectedLead = detailClient?.lead ?? null;
  const activeClient = detailClient ?? clients.find((client) => client.id === selectedClientId) ?? null;
  const funnelLabel = funnel?.label ?? activeClient?.funnel_id ?? "selected funnel";
  const workstationMessages = detailClient ? detail?.messages ?? [] : [];
  const runtimeAlerts = detailClient ? detail?.runtime_alerts ?? [] : [];
  const automationState = detailClient ? detail?.automation_state ?? null : null;
  const openRuntimeAlerts = runtimeAlerts.filter((alert) => !alert.resolved_at);
  const latestRuntimeAlert = openRuntimeAlerts[0] ?? null;
  const workstationFailed = activeClient?.automation_status === "failed";
  const imageAssets = (detail?.media ?? []).filter((asset) => asset.content_type?.startsWith("image/"));
  const professionalPhotos = detail?.professional_photos ?? [];
  const [mediaDropActive, setMediaDropActive] = useState(false);
  const [notesOpen, setNotesOpen] = useState(false);
  const [editingMediaId, setEditingMediaId] = useState<string | null>(null);
  const [mediaEditTitle, setMediaEditTitle] = useState("");
  const [mediaEditFilename, setMediaEditFilename] = useState("");
  const [actionsOpen, setActionsOpen] = useState(false);
  const [professionalPhotoModalOpen, setProfessionalPhotoModalOpen] = useState(false);
  const [soloPagePromptModalOpen, setSoloPagePromptModalOpen] = useState(false);
  const [soloPageOperatorPrompt, setSoloPageOperatorPrompt] = useState("");
  const [soloPageSteerModalOpen, setSoloPageSteerModalOpen] = useState(false);
  const [soloPageSteerMessage, setSoloPageSteerMessage] = useState("");
  const canUploadMedia = Boolean(activeClient) && actionBusy !== "workstation-upload";
  const currentProfessionalPhotoJob = professionalPhotoJob?.client_id === activeClient?.id ? professionalPhotoJob : null;
  const professionalPhotoJobBusy = currentProfessionalPhotoJob?.status === "queued" || currentProfessionalPhotoJob?.status === "running";
  const soloPageBusy = actionBusy === "solo-page-work" || Boolean(automationState?.is_live_working);
  const canStopSoloPageWork = activeClient?.work_type === "solo_pagina" && Boolean(automationState?.is_live_working);
  const canStartSoloPageWork = activeClient?.work_type === "solo_pagina" && !soloPageBusy;
  const workstationStateIsReady = (automationState?.label ?? "").toLowerCase().includes("ready");
  const workstationHasMissingLiveProcess = activeClient?.automation_status === "drafting" || activeClient?.automation_status === "revision_requested"
    ? !automationState?.is_live_working && !automationState?.is_stale
    : false;
  const workstationStatePillLabel = automationState?.is_live_working
    ? "Live"
    : automationState?.is_stale
      ? "Stale"
      : workstationHasMissingLiveProcess
        ? "No process"
      : automationState?.is_waiting_backoff
        ? "Backoff"
        : workstationFailed
          ? "Failed"
          : workstationStateIsReady
            ? "Ready"
            : "Idle";
  const activeOffer = formatWorkstationOffer(activeClient);
  const automationTone = workstationFailed
    ? "failed"
    : automationState?.is_stale
      ? "stale"
    : automationState?.is_live_working
      ? "working"
      : workstationHasMissingLiveProcess
        ? "missing-live"
      : automationState?.is_waiting_backoff
        ? "waiting"
        : "idle";

  useEffect(() => {
    setNotesOpen(false);
    setEditingMediaId(null);
    setActionsOpen(false);
    setProfessionalPhotoModalOpen(false);
    setSoloPagePromptModalOpen(false);
    setSoloPageOperatorPrompt("");
    setSoloPageSteerModalOpen(false);
    setSoloPageSteerMessage("");
  }, [selectedClientId]);

  function openProfessionalPhotoModal() {
    onProfessionalPhotoMediaIdsChange([]);
    onProfessionalPhotoContextChange("");
    setActionsOpen(false);
    setProfessionalPhotoModalOpen(true);
  }

  function closeProfessionalPhotoModal() {
    setProfessionalPhotoModalOpen(false);
    onProfessionalPhotoMediaIdsChange([]);
    onProfessionalPhotoContextChange("");
  }

  function openSoloPagePromptModal() {
    setActionsOpen(false);
    setSoloPagePromptModalOpen(true);
  }

  function closeSoloPagePromptModal() {
    setSoloPagePromptModalOpen(false);
    setSoloPageOperatorPrompt("");
  }

  function openSoloPageSteerModal() {
    setActionsOpen(false);
    setSoloPageSteerModalOpen(true);
  }

  function closeSoloPageSteerModal() {
    setSoloPageSteerModalOpen(false);
    setSoloPageSteerMessage("");
  }

  function startMediaEdit(asset: WorkstationMediaAsset) {
    setEditingMediaId(asset.id);
    setMediaEditTitle(asset.title || asset.original_filename);
    setMediaEditFilename(asset.original_filename || asset.stored_filename);
  }

  async function saveMediaEdit(asset: WorkstationMediaAsset) {
    await onUpdateMedia(asset, mediaEditTitle, mediaEditFilename);
    setEditingMediaId(null);
  }

  function clipboardFile(event: ClipboardEvent<HTMLElement>): File | null {
    for (const fileItem of Array.from(event.clipboardData.files)) {
      if (fileItem.size > 0) {
        return fileItem;
      }
    }
    for (const item of Array.from(event.clipboardData.items)) {
      const fileItem = item.kind === "file" ? item.getAsFile() : null;
      if (fileItem && fileItem.size > 0) {
        return fileItem;
      }
    }
    return null;
  }

  function droppedFile(event: DragEvent<HTMLElement>): File | null {
    for (const fileItem of Array.from(event.dataTransfer.files)) {
      if (fileItem.size > 0) {
        return fileItem;
      }
    }
    return null;
  }

  function handleMediaDragOver(event: DragEvent<HTMLElement>) {
    if (!Array.from(event.dataTransfer.types).includes("Files")) {
      return;
    }
    event.preventDefault();
    event.dataTransfer.dropEffect = canUploadMedia ? "copy" : "none";
    setMediaDropActive(true);
  }

  function handleMediaDragLeave(event: DragEvent<HTMLElement>) {
    const nextTarget = event.relatedTarget;
    if (nextTarget instanceof Node && event.currentTarget.contains(nextTarget)) {
      return;
    }
    setMediaDropActive(false);
  }

  function handleMediaDrop(event: DragEvent<HTMLElement>) {
    if (!Array.from(event.dataTransfer.types).includes("Files")) {
      return;
    }
    event.preventDefault();
    setMediaDropActive(false);
    const fileToUpload = droppedFile(event);
    if (fileToUpload && canUploadMedia) {
      onUploadMediaFile(fileToUpload);
    }
  }

  function handleMediaPaste(event: ClipboardEvent<HTMLElement>) {
    const fileToUpload = clipboardFile(event);
    if (!fileToUpload || !canUploadMedia) {
      return;
    }
    event.preventDefault();
    onUploadMediaFile(fileToUpload);
  }

  async function submitProfessionalPhotoModal(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const started = await onCreateProfessionalPhoto(selectedProfessionalPhotoMediaIds, professionalPhotoContext);
    if (started) {
      closeProfessionalPhotoModal();
    }
  }

  async function submitSoloPagePromptModal(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const started = await onStartSoloPageCodexWork(soloPageOperatorPrompt);
    if (started) {
      closeSoloPagePromptModal();
    }
  }

  async function submitSoloPageSteerModal(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const sent = await onSteerSoloPageCodexWork(soloPageSteerMessage);
    if (sent) {
      closeSoloPageSteerModal();
    }
  }

  return (
    <div className="ct-surface workstation-surface">
      <div className="ct-secondary">
        <p className="ct-secondary-note">
          {clients.length
            ? `${clients.length} ${clients.length === 1 ? "client" : "clients"} in ${funnelLabel}`
            : `No converted clients in ${funnelLabel} yet`}
        </p>
      </div>

      <div className="ct-workspace workstation-layout">
        <aside className="ct-leads">
          <div className="ct-leads-head">
            <h3>Clients</h3>
            <p className="ct-leads-summary">{clients.length ? `${clients.length} active` : "Empty"}</p>
          </div>
          <div className="ct-leads-list">
            {clients.length ? clients.map((client) => (
              <button
                type="button"
                className={`workstation-client-row ${client.id === selectedClientId ? "active" : ""} ${client.automation_status === "failed" ? "failed" : ""}`}
                key={client.id}
                onClick={() => onSelectClient(client.id)}
              >
                <div className="ct-lead-avatar" data-tone="success">
                  {monogram(client.display_name || client.lead?.full_name || "CL")}
                </div>
                <div>
                  <div className="workstation-client-row-top">
                    <strong>{client.display_name || client.lead?.full_name || "Client"}</strong>
                    {client.automation_status === "failed" ? <span className="danger">Failed</span> : formatWorkstationOffer(client) ? <span>{formatWorkstationOffer(client)}</span> : null}
                  </div>
                  <p>{client.lead?.phone || client.folder_name}</p>
                  <small>
                    {humanize(client.work_type)} · {humanize(client.status)} · {humanize(client.automation_status)}
                  </small>
                  <small>{client.media_count} media · {client.folder_path}</small>
                </div>
              </button>
            )) : (
              <p className="ct-empty">Convert a paid lead from CRM to open a client workspace.</p>
            )}
          </div>
        </aside>

        <section className="ct-detail workstation-detail">
          {!activeClient ? (
            <p className="empty-note">Select a converted client.</p>
          ) : (
            <>
              <header className="ct-detail-head workstation-head">
                <div className="ct-detail-head-main">
                  <div className="ct-detail-avatar">{monogram(activeClient.display_name || "CL")}</div>
                  <div className="ct-detail-head-copy">
                    <p className="ct-detail-kicker">{activeClient.funnel_id}</p>
                    <h3>{activeClient.display_name}</h3>
                    <p className="ct-detail-meta">
                      {selectedLead
                        ? [selectedLead.phone || "-", selectedLead.email || "-", selectedLead.external_lead_id].join(" · ")
                        : activeClient.folder_path}
                    </p>
                    <p className="ct-detail-meta">
                      {humanize(activeClient.work_type)} · {humanize(activeClient.status)} · {humanize(activeClient.automation_status)}
                    </p>
                    {activeOffer ? (
                      <p className="ct-detail-meta">Oferta fija: {activeOffer}</p>
                    ) : null}
                  </div>
                </div>
                <div className="ct-detail-head-actions">
                  <div className="workstation-action-menu">
                    <button
                      type="button"
                      className={`ct-btn ct-btn-primary ${actionsOpen ? "active" : ""}`}
                      onClick={() => setActionsOpen((current) => !current)}
                      aria-expanded={actionsOpen}
                      aria-haspopup="menu"
                    >
                      Actions
                      <CaretDown size={14} weight="bold" />
                    </button>
                    {actionsOpen ? (
                      <div className="workstation-action-popover" role="menu">
                        <button
                          type="button"
                          role="menuitem"
                          onClick={openSoloPagePromptModal}
                          disabled={!canStartSoloPageWork}
                        >
                          <Robot size={16} weight="bold" />
                          <span>Poner Codex a trabajar</span>
                        </button>
                        <button
                          type="button"
                          role="menuitem"
                          onClick={() => {
                            setActionsOpen(false);
                            onStopSoloPageCodexWork();
                          }}
                          disabled={!canStopSoloPageWork || actionBusy === "solo-page-stop"}
                        >
                          <X size={16} weight="bold" />
                          <span>Stop Codex</span>
                        </button>
                        <button
                          type="button"
                          role="menuitem"
                          onClick={openSoloPageSteerModal}
                          disabled={!canStopSoloPageWork || actionBusy === "solo-page-steer"}
                        >
                          <PaperPlaneTilt size={16} weight="bold" />
                          <span>Steer Codex</span>
                        </button>
                        <button
                          type="button"
                          role="menuitem"
                          onClick={openProfessionalPhotoModal}
                          disabled={!imageAssets.length || professionalPhotoJobBusy || actionBusy === "professional-photo-start"}
                        >
                          <Camera size={16} weight="bold" />
                          <span>Hacer foto profesional</span>
                        </button>
                      </div>
                    ) : null}
                  </div>
                  <button
                    type="button"
                    className={`ct-btn ct-btn-ghost notes-toggle ${notesOpen ? "active" : ""}`}
                    onClick={() => setNotesOpen((current) => !current)}
                    aria-expanded={notesOpen}
                    aria-controls="workstation-notes-panel"
                  >
                    <NotePencil size={15} weight="bold" />
                    Notes
                  </button>
                  <button type="button" className="ct-btn ct-btn-ghost" onClick={() => onOpenCrmLead(selectedLead)}>
                    <ArrowSquareOut size={15} weight="bold" />
                    Open CRM chat
                  </button>
                  <button type="button" className="ct-btn ct-btn-ghost" onClick={onCopyAll}>
                    <Copy size={15} weight="bold" />
                    Copy all
                  </button>
                  <a className="ct-btn ct-btn-primary" href={`/api/workstation/clients/${activeClient.id}/zip`}>
                    <DownloadSimple size={15} weight="bold" />
                    Download ZIP
                  </a>
                </div>
              </header>

              {notesOpen ? (
                <section className="workstation-panel notes-panel" id="workstation-notes-panel">
                  <div className="workstation-panel-head">
                    <div>
                      <span>Meeting notes</span>
                      <strong>Client profile notes</strong>
                    </div>
                    <div className="workstation-panel-actions">
                      <button type="button" className="ct-btn ct-btn-ghost" onClick={onCopyNotes} disabled={!notesDraft.trim()}>
                        <Copy size={14} weight="bold" />
                        Copy notes
                      </button>
                      <button
                        type="button"
                        className="ct-btn ct-btn-primary"
                        disabled={actionBusy === "workstation-notes" || loading}
                        onClick={onSaveNotes}
                      >
                        {actionBusy === "workstation-notes" ? "Saving..." : "Save notes"}
                      </button>
                    </div>
                  </div>
                  <textarea
                    className="workstation-notes"
                    value={notesDraft}
                    onChange={(event) => onNotesChange(event.target.value)}
                    placeholder="Paste call notes, client answers, preferences, questions, offer context..."
                  />
                </section>
              ) : null}

              {workstationFailed || latestRuntimeAlert ? (
                <section className="workstation-failure-alert" role="alert">
                  <WarningCircle size={22} weight="bold" />
                  <div>
                    <span>Workstation alert</span>
                    <strong>{workstationFailed ? "Automation failed" : humanize(latestRuntimeAlert?.alert_type || "runtime alert")}</strong>
                    <p>{latestRuntimeAlert?.error || "No runtime alert details were attached. Review this client manually."}</p>
                    <small>
                      {latestRuntimeAlert?.resolved_at
                        ? `Resolved ${shortDate(latestRuntimeAlert.resolved_at)}`
                        : latestRuntimeAlert?.notified_at
                          ? `Email alert sent ${shortDate(latestRuntimeAlert.notified_at)}`
                          : "Email alert pending"}
                    </small>
                  </div>
                </section>
              ) : null}

              <section className={`workstation-panel workstation-automation-panel ${automationTone}`}>
                <div className="workstation-panel-head">
                  <div>
                    <span>Automation state</span>
                    <strong>{automationState?.label ?? humanize(activeClient.automation_status)}</strong>
                  </div>
                  <span className="workstation-state-pill">
                    {automationState?.is_live_working ? (
                      <SpinnerGap className="workstation-spinner" size={14} weight="bold" />
                    ) : automationState?.is_stale ? (
                      <WarningCircle size={14} weight="bold" />
                    ) : workstationHasMissingLiveProcess ? (
                      <WarningCircle size={14} weight="bold" />
                    ) : automationState?.is_waiting_backoff ? (
                      <ClockCountdown size={14} weight="bold" />
                    ) : workstationFailed ? (
                      <WarningCircle size={14} weight="bold" />
                    ) : (
                      <CheckCircle size={14} weight="bold" />
                    )}
                    {workstationStatePillLabel}
                  </span>
                </div>
                <p className="workstation-automation-detail">
                  {automationState?.detail ?? "No automation state loaded yet."}
                </p>
                <div className="workstation-automation-meta">
                  {automationState?.latest_inbound_at ? <span>Latest inbound: {shortDate(automationState.latest_inbound_at)}</span> : null}
                  {automationState?.backoff_until ? <span>Backoff until: {shortDate(automationState.backoff_until)}</span> : null}
                  <span>Live process: {automationState?.live_status ? humanize(automationState.live_status) : "Not running"}</span>
                  {automationState?.live_started_at ? <span>Live since: {shortDate(automationState.live_started_at)}</span> : null}
                  {automationState?.progress_updated_at ? <span>Progress updated: {shortDate(automationState.progress_updated_at)}</span> : null}
                  {automationState?.progress_path ? <code>{automationState.progress_path}</code> : null}
                </div>
                {automationState?.live_detail ? (
                  <p className="workstation-live-detail">{automationState.live_detail}</p>
                ) : null}
                <div className="workstation-progress">
                  <div className="workstation-progress-head">
                    <Robot size={15} weight="bold" />
                    <span>Codex progress</span>
                  </div>
                  {automationState?.progress_markdown?.trim() ? (
                    <pre>{automationState.progress_markdown}</pre>
                  ) : (
                    <p>No progress has been written for this client yet.</p>
                  )}
                </div>
              </section>

              <section
                className={`workstation-panel workstation-media-panel ${mediaDropActive ? "drag-active" : ""}`}
                onDragOver={handleMediaDragOver}
                onDragLeave={handleMediaDragLeave}
                onDrop={handleMediaDrop}
                onPaste={handleMediaPaste}
                tabIndex={0}
                aria-label="Workstation media"
              >
                <div className="workstation-panel-head">
                  <div>
                    <span>Media</span>
                    <strong>Client files</strong>
                  </div>
                </div>
                <form className="workstation-upload" onSubmit={onUploadMedia}>
                  <label className="ct-field">
                    <span>Title</span>
                    <input value={fileTitle} onChange={(event) => onFileTitleChange(event.target.value)} placeholder="Logo, fachada, referencia visual..." />
                  </label>
                  <label className="ct-field">
                    <span>File</span>
                    <input type="file" onChange={(event) => onFileChange(event.target.files?.[0] ?? null)} />
                  </label>
                  <button type="submit" className="ct-btn ct-btn-primary" disabled={!file || actionBusy === "workstation-upload"}>
                    <UploadSimple size={15} weight="bold" />
                    {actionBusy === "workstation-upload" ? "Uploading..." : "Upload"}
                  </button>
                </form>
                <div className="workstation-media-grid">
                  {(detail?.media ?? []).length ? (detail?.media ?? []).map((asset) => (
                    <article className="workstation-media-card" key={asset.id}>
                      <div className="workstation-media-preview">
                        {asset.content_type?.startsWith("image/") ? (
                          <img src={asset.media_url} alt={asset.title || asset.original_filename} loading="lazy" />
                        ) : (
                          <div className="workstation-file-icon"><FolderOpen size={28} weight="bold" /></div>
                        )}
                      </div>
                      {editingMediaId === asset.id ? (
                        <form
                          className="workstation-media-edit"
                          onSubmit={(event) => {
                            event.preventDefault();
                            saveMediaEdit(asset).catch((reason) => {
                              console.error(reason);
                            });
                          }}
                        >
                          <label className="ct-field">
                            <span>Name</span>
                            <input value={mediaEditTitle} onChange={(event) => setMediaEditTitle(event.target.value)} />
                          </label>
                          <label className="ct-field">
                            <span>Filename</span>
                            <input value={mediaEditFilename} onChange={(event) => setMediaEditFilename(event.target.value)} />
                          </label>
                          <div className="workstation-media-edit-actions">
                            <button type="submit" className="ct-btn ct-btn-primary" disabled={actionBusy === `edit-media-${asset.id}`}>
                              {actionBusy === `edit-media-${asset.id}` ? "Saving..." : "Save"}
                            </button>
                            <button type="button" className="ct-btn ct-btn-ghost" onClick={() => setEditingMediaId(null)}>Cancel</button>
                          </div>
                        </form>
                      ) : (
                        <div className="workstation-media-meta">
                          <strong>{asset.title || asset.original_filename}</strong>
                          <span>{asset.original_filename} · {formatBytes(asset.size_bytes)}</span>
                        </div>
                      )}
                      <div className="workstation-media-actions">
                        <button type="button" className="ct-btn ct-btn-ghost" onClick={() => startMediaEdit(asset)}>
                          <NotePencil size={15} weight="bold" />
                          Edit
                        </button>
                        <a className="ct-btn ct-btn-ghost" href={asset.media_url} target="_blank" rel="noreferrer">Open</a>
                        <button
                          type="button"
                          className="ct-btn ct-btn-ghost btn-destructive"
                          onClick={() => onDeleteMedia(asset)}
                          disabled={actionBusy === `delete-media-${asset.id}`}
                          aria-label={`Delete ${asset.title || asset.original_filename}`}
                        >
                          <Trash size={15} weight="bold" />
                        </button>
                      </div>
                    </article>
                  )) : (
                    <p className="empty-note">No media uploaded for this client yet.</p>
                  )}
                </div>
              </section>

              <section className="workstation-panel">
                <div className="workstation-panel-head">
                  <div>
                    <span>Professional photo</span>
                    <strong>Generated client portrait</strong>
                  </div>
                </div>
                {currentProfessionalPhotoJob ? (
                  <div className={`workstation-photo-job ${currentProfessionalPhotoJob.status}`}>
                    {professionalPhotoJobBusy ? <SpinnerGap className="workstation-spinner" size={18} weight="bold" /> : null}
                    {currentProfessionalPhotoJob.status === "completed" ? <Check size={18} weight="bold" /> : null}
                    {currentProfessionalPhotoJob.status === "failed" ? <X size={18} weight="bold" /> : null}
                    <div>
                      <strong>
                        {professionalPhotoJobBusy
                          ? "Procesando foto profesional"
                          : currentProfessionalPhotoJob.status === "completed"
                            ? "Foto profesional lista"
                            : "No se pudo crear la foto"}
                      </strong>
                      <span>
                        {currentProfessionalPhotoJob.status === "completed" && currentProfessionalPhotoJob.result
                          ? `${currentProfessionalPhotoJob.result.version} · ${currentProfessionalPhotoJob.result.image_path}`
                          : currentProfessionalPhotoJob.error || "El resultado va a aparecer aca cuando termine."}
                      </span>
                    </div>
                  </div>
                ) : null}
                <div className="workstation-photo-grid">
                  {professionalPhotos.length ? professionalPhotos.map((photo) => (
                    <article className="workstation-photo-card" key={photo.version}>
                      <a href={photo.image_url} target="_blank" rel="noreferrer">
                        <img src={photo.image_url} alt={`Professional photo ${photo.version}`} loading="lazy" />
                      </a>
                      <div className="workstation-photo-meta">
                        <strong>{photo.version}</strong>
                        <span>{photo.operation || "generated"} · {photo.created_at || photo.image_path}</span>
                        <code>{photo.image_path}</code>
                      </div>
                      <div className="workstation-photo-edit">
                        <input
                          value={professionalPhotoEditPrompts[photo.version] ?? ""}
                          onChange={(event) => onProfessionalPhotoEditPromptChange(photo.version, event.target.value)}
                          placeholder="Modify this version..."
                        />
                        <button
                          type="button"
                          className="ct-btn ct-btn-ghost"
                          onClick={() => onEditProfessionalPhoto(photo.version)}
                          disabled={
                            !(professionalPhotoEditPrompts[photo.version] ?? "").trim()
                            || actionBusy === `professional-photo-edit-${photo.version}`
                          }
                        >
                          {actionBusy === `professional-photo-edit-${photo.version}` ? "Editing..." : "Modify"}
                        </button>
                      </div>
                    </article>
                  )) : (
                    <p className="empty-note">
                      {professionalPhotoJobBusy ? "Waiting for the first result." : "No professional photo yet."}
                    </p>
                  )}
                </div>
              </section>

              <section className="workstation-panel workstation-chat-panel">
                <div className="workstation-panel-head">
                  <div>
                    <span>Conversation</span>
                    <strong>WhatsApp chat</strong>
                  </div>
                  <button type="button" className="ct-btn ct-btn-ghost workstation-crm-link" onClick={() => onOpenCrmLead(selectedLead)}>
                    <ArrowSquareOut size={15} weight="bold" />
                    Open CRM chat
                  </button>
                </div>
                <div className="workstation-chat-thread">
                  <MessageTimeline
                    messages={workstationMessages}
                    loading={loading}
                    hasLead={Boolean(selectedLead)}
                    acknowledgingIds={acknowledgingDeliveryErrorIds}
                    onAcknowledgeDeliveryError={onAcknowledgeDeliveryError}
                  />
                </div>
              </section>
            </>
          )}
        </section>
      </div>
      {professionalPhotoModalOpen ? (
        <ProfessionalPhotoModal
          imageAssets={imageAssets}
          selectedMediaIds={selectedProfessionalPhotoMediaIds}
          context={professionalPhotoContext}
          busy={actionBusy === "professional-photo-start"}
          onToggleMedia={onToggleProfessionalPhotoMedia}
          onContextChange={onProfessionalPhotoContextChange}
          onClose={closeProfessionalPhotoModal}
          onSubmit={submitProfessionalPhotoModal}
        />
      ) : null}
      {soloPagePromptModalOpen ? (
        <SoloPagePromptModal
          prompt={soloPageOperatorPrompt}
          busy={actionBusy === "solo-page-work"}
          onPromptChange={setSoloPageOperatorPrompt}
          onClose={closeSoloPagePromptModal}
          onSubmit={submitSoloPagePromptModal}
        />
      ) : null}
      {soloPageSteerModalOpen ? (
        <SoloPageSteerModal
          message={soloPageSteerMessage}
          busy={actionBusy === "solo-page-steer"}
          onMessageChange={setSoloPageSteerMessage}
          onClose={closeSoloPageSteerModal}
          onSubmit={submitSoloPageSteerModal}
        />
      ) : null}
    </div>
  );
}

function SoloPageSteerModal({
  message,
  busy,
  onMessageChange,
  onClose,
  onSubmit,
}: {
  message: string;
  busy: boolean;
  onMessageChange: (value: string) => void;
  onClose: () => void;
  onSubmit: (event: FormEvent<HTMLFormElement>) => void;
}) {
  return (
    <div className="ct-modal open" aria-hidden="false">
      <button className="ct-modal-overlay" type="button" onClick={onClose} aria-label="Cerrar steer de Codex" />
      <form className="ct-modal-panel workstation-solo-page-modal" role="dialog" aria-modal="true" aria-labelledby="workstationSoloPageSteerModalTitle" onSubmit={onSubmit}>
        <header className="ct-modal-head">
          <div>
            <p className="ct-drawer-kicker">Workstation</p>
            <h3 id="workstationSoloPageSteerModalTitle">Steer Codex</h3>
            <p className="ct-modal-subtitle">Mensaje adicional para el run activo.</p>
          </div>
          <button type="button" className="ct-btn ct-btn-ghost workstation-modal-close" onClick={onClose} aria-label="Cerrar">
            <X size={15} weight="bold" />
          </button>
        </header>
        <div className="ct-modal-body">
          <label className="ct-field workstation-prompt-field">
            <span>Mensaje para Codex</span>
            <textarea
              value={message}
              onChange={(event) => onMessageChange(event.target.value)}
              placeholder="Segui, pero usá un tono más sobrio y no uses la foto del logo..."
              rows={6}
              autoFocus
            />
          </label>
        </div>
        <footer className="ct-modal-foot">
          <button type="button" className="ct-btn ct-btn-ghost" onClick={onClose}>Cancel</button>
          <button type="submit" className="ct-btn ct-btn-primary" disabled={!message.trim() || busy}>
            {busy ? <SpinnerGap className="workstation-spinner" size={15} weight="bold" /> : <PaperPlaneTilt size={15} weight="bold" />}
            {busy ? "Enviando..." : "Enviar"}
          </button>
        </footer>
      </form>
    </div>
  );
}

function SoloPagePromptModal({
  prompt,
  busy,
  onPromptChange,
  onClose,
  onSubmit,
}: {
  prompt: string;
  busy: boolean;
  onPromptChange: (value: string) => void;
  onClose: () => void;
  onSubmit: (event: FormEvent<HTMLFormElement>) => void;
}) {
  return (
    <div className="ct-modal open" aria-hidden="false">
      <button className="ct-modal-overlay" type="button" onClick={onClose} aria-label="Cerrar prompt de Codex" />
      <form className="ct-modal-panel workstation-solo-page-modal" role="dialog" aria-modal="true" aria-labelledby="workstationSoloPageModalTitle" onSubmit={onSubmit}>
        <header className="ct-modal-head">
          <div>
            <p className="ct-drawer-kicker">Workstation</p>
            <h3 id="workstationSoloPageModalTitle">Poner Codex a trabajar</h3>
            <p className="ct-modal-subtitle">Usa cliente, notas, media y conversacion completa.</p>
          </div>
          <button type="button" className="ct-btn ct-btn-ghost workstation-modal-close" onClick={onClose} aria-label="Cerrar">
            <X size={15} weight="bold" />
          </button>
        </header>
        <div className="ct-modal-body">
          <label className="ct-field workstation-prompt-field">
            <span>Prompt para Codex</span>
            <textarea
              value={prompt}
              onChange={(event) => onPromptChange(event.target.value)}
              placeholder="Hey, ponete a trabajar y hacele la pagina. Usá lo que ya mandó, priorizá..."
              rows={7}
              autoFocus
            />
          </label>
        </div>
        <footer className="ct-modal-foot">
          <button type="button" className="ct-btn ct-btn-ghost" onClick={onClose}>Cancel</button>
          <button type="submit" className="ct-btn ct-btn-primary" disabled={!prompt.trim() || busy}>
            {busy ? <SpinnerGap className="workstation-spinner" size={15} weight="bold" /> : <Robot size={15} weight="bold" />}
            {busy ? "Arrancando..." : "Arrancar"}
          </button>
        </footer>
      </form>
    </div>
  );
}

function ProfessionalPhotoModal({
  imageAssets,
  selectedMediaIds,
  context,
  busy,
  onToggleMedia,
  onContextChange,
  onClose,
  onSubmit,
}: {
  imageAssets: WorkstationMediaAsset[];
  selectedMediaIds: string[];
  context: string;
  busy: boolean;
  onToggleMedia: (assetId: string) => void;
  onContextChange: (value: string) => void;
  onClose: () => void;
  onSubmit: (event: FormEvent<HTMLFormElement>) => void;
}) {
  return (
    <div className="ct-modal open" aria-hidden="false">
      <button className="ct-modal-overlay" type="button" onClick={onClose} aria-label="Cerrar foto profesional" />
      <form className="ct-modal-panel workstation-photo-modal" role="dialog" aria-modal="true" aria-labelledby="workstationPhotoModalTitle" onSubmit={onSubmit}>
        <header className="ct-modal-head">
          <div>
            <p className="ct-drawer-kicker">Workstation</p>
            <h3 id="workstationPhotoModalTitle">Hacer foto profesional</h3>
            <p className="ct-modal-subtitle">{selectedMediaIds.length} media selected</p>
          </div>
          <button type="button" className="ct-btn ct-btn-ghost workstation-modal-close" onClick={onClose} aria-label="Cerrar">
            <X size={15} weight="bold" />
          </button>
        </header>
        <div className="ct-modal-body">
          <label className="ct-field">
            <span>Direccion opcional</span>
            <input
              value={context}
              onChange={(event) => onContextChange(event.target.value)}
              placeholder="Abogado penalista, contador premium, mas formal, ciudad..."
            />
          </label>

          <section className="workstation-photo-picker" aria-label="Seleccionar media">
            <div className="workstation-photo-picker-head">
              <span>Seleccionar media</span>
              <strong>{selectedMediaIds.length}/{imageAssets.length}</strong>
            </div>
            <div className="workstation-photo-picker-grid">
              {imageAssets.length ? imageAssets.map((asset) => {
                const selected = selectedMediaIds.includes(asset.id);
                return (
                  <button
                    type="button"
                    className={`workstation-photo-picker-card ${selected ? "selected" : ""}`}
                    key={asset.id}
                    onClick={() => onToggleMedia(asset.id)}
                    aria-pressed={selected}
                  >
                    <img src={asset.media_url} alt={asset.title || asset.original_filename} loading="lazy" />
                    <div>
                      <strong>{asset.title || asset.original_filename}</strong>
                      <span>{asset.original_filename}</span>
                    </div>
                    <span className="workstation-select-pill">
                      {selected ? <Check size={14} weight="bold" /> : null}
                      {selected ? "Selected" : "Select"}
                    </span>
                  </button>
                );
              }) : (
                <p className="empty-note">No image media available.</p>
              )}
            </div>
          </section>
        </div>
        <footer className="ct-modal-foot">
          <button type="button" className="ct-btn ct-btn-ghost" onClick={onClose}>Cancel</button>
          <button type="submit" className="ct-btn ct-btn-primary" disabled={!selectedMediaIds.length || busy}>
            {busy ? <SpinnerGap className="workstation-spinner" size={15} weight="bold" /> : <Camera size={15} weight="bold" />}
            {busy ? "Haciendo..." : "Hacer"}
          </button>
        </footer>
      </form>
    </div>
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

  return (
    <section className="ct-funnel-setup" aria-label="Funnel setup">
      <header className="ct-funnel-hero">
        <div>
          <p className="ct-detail-kicker">Niche funnel</p>
          <h2>{funnel.label}</h2>
          <p>
            This funnel is configured but does not have a dedicated lead workspace yet. Edit the funnel copy,
            sheet source, video strategy, and Calendly step here; Contadores remains the primary operational section.
          </p>
        </div>
        <button type="button" className="ct-btn ct-btn-primary" onClick={onEdit}>Edit funnel</button>
      </header>

      <div className="ct-funnel-grid">
        <article className="ct-funnel-card">
          <span>Source</span>
          <strong>{funnel.sheet_url ? "Sheet connected" : "Missing sheet"}</strong>
          <p>{funnel.sheet_url ? "Sheet connected" : "No sheet URL yet"}{funnel.sheet_gid ? ` · gid ${funnel.sheet_gid}` : ""}</p>
        </article>
        <article className="ct-funnel-card">
          <span>Polling</span>
          <strong>{funnel.enabled ? "Enabled" : "Paused"}</strong>
          <p>Every {funnel.sheet_poll_seconds} seconds</p>
        </article>
        <article className="ct-funnel-card">
          <span>Video</span>
          <strong>{mp4Strategy?.media_path ? "WhatsApp MP4" : "Not configured"}</strong>
          <p>{mp4Strategy?.media_path || "-"}</p>
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
          {funnel.opener_template_name ? <code>{funnel.opener_template_name}</code> : null}
          <blockquote>{funnel.opener_text}</blockquote>
        </div>
        <div className="ct-copy-row">
          <span>Manual ping template</span>
          {funnel.manual_ping_template_name ? <code>{funnel.manual_ping_template_name}</code> : null}
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
  const templateChoices = buildTemplateChoices(draft);

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

  function deleteStrategy(strategyId: string) {
    setDraft((current) => {
      if (current.strategies.length <= 1) {
        return current;
      }
      return {
        ...current,
        strategies: current.strategies.filter((strategy) => strategy.id !== strategyId),
      };
    });
  }

  function updateTemplateChoice(nameKey: TemplateNameField, textKey: TemplateTextField, templateId: string) {
    const selected = templateChoices.find((choice) => choice.templateId === templateId);
    setDraft((current) => ({
      ...current,
      [nameKey]: templateId || null,
      [textKey]: selected?.text ?? current[textKey],
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
      whatsapp_referral_source_ids: draft.whatsapp_referral_source_ids.map((item) => item.trim()).filter(Boolean),
      strategies: draft.strategies.map((strategy) => ({
        ...strategy,
        label: strategy.label.trim() || strategy.id,
        message_text: strategy.message_text.trim(),
        media_path: strategy.media_path?.trim() || null,
        media_caption: strategy.media_caption?.trim() || null,
      })),
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

          <label className="ct-field">
            <span>Sheet Poll Seconds</span>
            <input type="number" min="30" value={draft.sheet_poll_seconds} onChange={(event) => update("sheet_poll_seconds", Number(event.target.value) || 30)} />
          </label>

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

          <TemplateSelectField
            label="Opener Template"
            value={draft.opener_template_name ?? ""}
            text={draft.opener_text}
            choices={templateChoices}
            onChange={(value) => updateTemplateChoice("opener_template_name", "opener_text", value)}
          />
          <label className="ct-field">
            <span>Opener Text</span>
            <textarea value={draft.opener_text} onChange={(event) => update("opener_text", event.target.value)} rows={3} />
          </label>

          <TemplateSelectField
            label="Follow-up Template"
            value={draft.opener_followup_template_name ?? ""}
            text={draft.opener_followup_text}
            choices={templateChoices}
            onChange={(value) => updateTemplateChoice("opener_followup_template_name", "opener_followup_text", value)}
          />
          <label className="ct-field">
            <span>Follow-up Text</span>
            <textarea value={draft.opener_followup_text} onChange={(event) => update("opener_followup_text", event.target.value)} rows={3} />
          </label>

          <TemplateSelectField
            label="Manual Ping Template"
            value={draft.manual_ping_template_name ?? ""}
            text={draft.manual_ping_text}
            choices={templateChoices}
            onChange={(value) => updateTemplateChoice("manual_ping_template_name", "manual_ping_text", value)}
          />
          <label className="ct-field">
            <span>Manual Ping Text</span>
            <textarea value={draft.manual_ping_text} onChange={(event) => update("manual_ping_text", event.target.value)} rows={3} />
          </label>

          <label className="ct-field">
            <span>Video Intro Text</span>
            <textarea value={draft.loom_intro_text} onChange={(event) => update("loom_intro_text", event.target.value)} rows={4} />
          </label>

          <label className="ct-field">
            <span>MP4 Path</span>
            <input value={videoStrategy?.media_path ?? ""} onChange={(event) => updateStrategyMediaPath(event.target.value)} />
          </label>

          <div className="ct-strategy-edit-list">
            {draft.strategies.map((strategy) => (
              <article className="ct-strategy-edit-row" key={strategy.id}>
                <div>
                  <strong>{strategy.label || formatStrategyLabel(strategy.id)}</strong>
                  <span>{strategy.id} · {strategy.delivery}</span>
                </div>
                <label className="ct-field">
                  <span>Weight</span>
                  <input type="number" min="0" max="100" value={strategy.weight} onChange={(event) => updateStrategyWeight(strategy.id, event.target.value)} />
                </label>
                <button
                  type="button"
                  className="ct-btn ct-btn-ghost btn-destructive"
                  disabled={draft.strategies.length <= 1}
                  onClick={() => deleteStrategy(strategy.id)}
                >
                  Delete
                </button>
              </article>
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
          <label className="ct-field">
            <span>WhatsApp Ad Source IDs</span>
            <input value={draft.whatsapp_referral_source_ids.join(", ")} onChange={(event) => update("whatsapp_referral_source_ids", event.target.value.split(",").map((item) => item.trim()))} />
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

function TemplateSelectField({
  label,
  value,
  text,
  choices,
  onChange,
}: {
  label: string;
  value: string;
  text: string;
  choices: TemplateChoice[];
  onChange: (value: string) => void;
}) {
  const selected = choices.find((choice) => choice.templateId === value);
  const selectedText = selected?.text || text;

  return (
    <label className="ct-field ct-template-field">
      <span>{label}</span>
      <select value={value} onChange={(event) => onChange(event.target.value)}>
        <option value="">No template</option>
        {choices.map((choice) => (
          <option value={choice.templateId} key={choice.templateId}>
            {choice.label}: {truncateForOption(choice.text)}
          </option>
        ))}
      </select>
      <div className="ct-template-preview">
        <span>Contenido seleccionado</span>
        <blockquote>{selectedText || "Sin contenido para este template."}</blockquote>
        {value ? <code>{value}</code> : null}
      </div>
    </label>
  );
}

function LeadList({
  leads,
  selectedLeadId,
  selectedLeadIds,
  inboxMode,
  loading,
  onSelect,
  onToggleSelected,
}: {
  leads: LeadSummary[];
  selectedLeadId: string | null;
  selectedLeadIds: string[];
  inboxMode: boolean;
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
        const hasOutboundError = (lead.outbound_error_count || 0) > 0;
        return (
          <div
            className={`ct-lead-row ${lead.id === selectedLeadId ? "active" : ""} ${checked ? "selected" : ""} ${hasOutboundError ? "has-error" : ""}`}
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
                    <span className="ct-lead-stage" data-tone={tone}>{inboxMode ? "Inbox" : formatStageLabel(lead.stage)}</span>
                    {lead.workstation_client_id ? (
                      <span className="ct-lead-converted">
                        Converted
                      </span>
                    ) : null}
                    {strategyTag ? <span className="ct-lead-strategy-tag">{strategyTag}</span> : null}
                    {(lead.tags ?? []).slice(0, 3).map((tag) => <span className="ct-lead-tag" key={tag}>#{tag}</span>)}
                    {turn ? <span className={`ct-lead-turn ${turn}`}>{turn === "needs_reply" ? "Needs reply" : "Answered"}</span> : null}
                    {hasOutboundError ? (
                      <span className="ct-lead-delivery-error" title={lead.latest_outbound_error || "WhatsApp delivery failed"}>
                        <WarningCircle size={13} weight="fill" />
                        Send failed
                      </span>
                    ) : null}
                  </div>
                </div>
                <div className="ct-lead-meta">
                  <span className="ct-lead-meta-main">
                    <PhoneCountryFlag phone={lead.phone || lead.normalized_phone} />
                    <span>{lead.phone || "-"}</span>
                  </span>
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
  inboxMode,
  onOpenSend,
  onManualBooked,
  onManualHandoff,
  onMarkAnswered,
  onToggleClosed,
  onDelete,
  onConvert,
  onStartSoloPage,
  onCopyContext,
  onOpenWorkstation,
  copyStatus,
}: {
  lead: LeadSummary | null;
  actionBusy: string | null;
  inboxMode: boolean;
  onOpenSend: () => void;
  onManualBooked: () => void;
  onManualHandoff: () => void;
  onMarkAnswered: () => void;
  onToggleClosed: () => void;
  onDelete: () => void;
  onConvert: () => void;
  onStartSoloPage: () => void;
  onCopyContext: () => void | Promise<void>;
  onOpenWorkstation: (clientId: string) => void | Promise<void>;
  copyStatus: string;
}) {
  const closed = lead?.stage === "closed";
  const booked = lead?.stage === "booked";
  const paused = Boolean(lead?.automation_paused);
  const canMarkAnswered = lead?.manual_reply_status === "needs_reply" && !closed;
  const converted = Boolean(lead?.workstation_client_id);

  return (
    <header className="ct-detail-head">
      <div className="ct-detail-head-main">
        <div className="ct-detail-avatar">{lead ? monogram(lead.full_name || lead.phone || "CT") : "CT"}</div>
        <div className="ct-detail-head-copy">
          <p className="ct-detail-kicker">{lead ? (inboxMode ? "Inbox" : formatStageLabel(lead.stage)) : "Select a lead"}</p>
          <h3>{lead?.full_name || lead?.phone || "No lead selected"}</h3>
          <p className="ct-detail-meta">
            {lead ? (
              <>
                <PhoneCountryFlag phone={lead.phone || lead.normalized_phone} />
                <span>{[lead.phone || "-", lead.email || "-", lead.platform || "-", lead.external_lead_id || "-"].join(" · ")}</span>
              </>
            ) : "Open a lead to inspect messages, strategy history, and manual controls."}
          </p>
        </div>
      </div>
      <div className="ct-detail-head-actions">
        <button type="button" className="ct-btn ct-btn-primary" disabled={!lead || closed || Boolean(actionBusy)} onClick={onOpenSend}>
          <PaperPlaneTilt size={15} weight="bold" />
          Send
        </button>
        <button type="button" className="ct-btn ct-btn-ghost" disabled={!lead} onClick={onCopyContext} title="Copy context">
          <Copy size={15} weight="bold" />
          Copy
        </button>
        {converted && lead?.workstation_client_id ? (
          <button
            type="button"
            className="ct-btn ct-btn-ghost"
            disabled={Boolean(actionBusy)}
            onClick={() => onOpenWorkstation(lead.workstation_client_id || "")}
          >
            <FolderOpen size={15} weight="bold" />
            Open Workstation
          </button>
        ) : (
          <>
            <button
              type="button"
              className="ct-btn ct-btn-ghost"
              disabled={!lead || Boolean(actionBusy)}
              onClick={onStartSoloPage}
            >
              <Robot size={15} weight="bold" />
              Solo page
            </button>
            <button
              type="button"
              className="ct-btn ct-btn-ghost"
              disabled={!lead || Boolean(actionBusy)}
              onClick={onConvert}
            >
              <CurrencyDollar size={15} weight="bold" />
              Convert
            </button>
          </>
        )}
        {!inboxMode ? (
          <button type="button" className="ct-btn ct-btn-ghost" disabled={!lead || closed || booked || Boolean(actionBusy)} onClick={onManualBooked}>
            <CheckCircle size={15} weight="bold" />
            Booked
          </button>
        ) : null}
        {!inboxMode ? (
          <button type="button" className="ct-btn ct-btn-ghost" disabled={!lead || closed || paused || Boolean(actionBusy)} onClick={onManualHandoff}>
            <NotePencil size={15} weight="bold" />
            Manual
          </button>
        ) : null}
        {canMarkAnswered && !inboxMode ? (
          <button type="button" className="ct-btn ct-btn-ghost" disabled={Boolean(actionBusy)} onClick={onMarkAnswered}>
            <Check size={15} weight="bold" />
            Answered
          </button>
        ) : null}
        <button type="button" className={`ct-btn ct-btn-ghost ${closed ? "" : "btn-destructive"}`} disabled={!lead || Boolean(actionBusy)} onClick={onToggleClosed}>
          {closed ? "Reopen" : "Close"}
        </button>
        <button type="button" className="ct-btn ct-btn-ghost btn-destructive" disabled={!lead || Boolean(actionBusy)} onClick={onDelete}>Delete</button>
        {copyStatus ? <span className="ct-lead-copy-status" aria-live="polite">{copyStatus}</span> : null}
      </div>
    </header>
  );
}

function PausedBanner({ lead }: {
  lead: LeadSummary | null;
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
              ? `Paused by operator (${humanize(lead.automation_paused_reason)}).`
              : "The bot won't send anything while automation is paused."}
        </span>
      </div>
    </div>
  );
}

function MoveLeadPanel({
  lead,
  funnels,
  busy,
  onMove,
}: {
  lead: LeadSummary | null;
  funnels: FunnelDefinition[];
  busy: boolean;
  onMove: (funnelId: string, stage: LeadStage) => Promise<void>;
}) {
  const campaignFunnels = funnels.filter((funnel) => funnel.kind !== "inbox");
  const [funnelId, setFunnelId] = useState(campaignFunnels[0]?.id ?? "contadores");
  const [stage, setStage] = useState<LeadStage>("needs_human");

  useEffect(() => {
    setFunnelId((current) => (
      campaignFunnels.some((funnel) => funnel.id === current)
        ? current
        : campaignFunnels[0]?.id ?? "contadores"
    ));
  }, [campaignFunnels]);

  if (!lead) {
    return null;
  }

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    await onMove(funnelId, stage);
  }

  return (
    <form className="ct-move-panel" onSubmit={submit}>
      <div>
        <strong>Move to campaign</strong>
        <span>Pick the funnel and the phase where this chat should continue.</span>
      </div>
      <label className="ct-field">
        <span>Campaign</span>
        <select value={funnelId} onChange={(event) => setFunnelId(event.target.value)}>
          {campaignFunnels.map((funnel) => (
            <option value={funnel.id} key={funnel.id}>{funnel.label}</option>
          ))}
        </select>
      </label>
      <label className="ct-field">
        <span>Phase</span>
        <select value={stage} onChange={(event) => setStage(event.target.value as LeadStage)}>
          {moveStageOptions.map((option) => (
            <option value={option.value} key={option.value}>{option.label}</option>
          ))}
        </select>
      </label>
      <button type="submit" className="ct-btn ct-btn-primary" disabled={busy || !campaignFunnels.length}>
        {busy ? "Moving..." : "Move chat"}
      </button>
    </form>
  );
}

function MessageTimeline({
  messages,
  loading,
  hasLead,
  acknowledgingIds,
  onAcknowledgeDeliveryError,
}: {
  messages: MessageItem[];
  loading: boolean;
  hasLead: boolean;
  acknowledgingIds: number[];
  onAcknowledgeDeliveryError: (message: MessageItem) => void | Promise<void>;
}) {
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
        const deliveryStatus = String(message.delivery_status || "").toLowerCase();
        const hasDeliveryError = message.from_me && deliveryStatus === "failed";
        const errorAcknowledged = Boolean(message.delivery_error_acknowledged_at);
        const needsDeliveryErrorAck = hasDeliveryError && !errorAcknowledged;
        const acknowledging = acknowledgingIds.includes(message.id);
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
              <span className={`crm-message-dot ${direction} ${needsDeliveryErrorAck ? "failed" : ""} ${errorAcknowledged ? "acknowledged" : ""}`} />
            </div>
            <article
              className={`crm-message-card ${direction} ${deliveryStatus === "undelivered" ? "pending" : ""} ${needsDeliveryErrorAck ? "failed" : ""} ${errorAcknowledged ? "acknowledged" : ""}`}
              data-clickable={needsDeliveryErrorAck ? "true" : undefined}
              onClick={needsDeliveryErrorAck ? () => onAcknowledgeDeliveryError(message) : undefined}
            >
              <div className="crm-message-meta">
                <div className="crm-message-eyebrow">
                  <span className={`crm-message-author ${direction}`}>{message.from_me ? "Bot / Operator" : "Lead"}</span>
                  <span>{meta.join(" · ")}</span>
                </div>
                {needsDeliveryErrorAck ? (
                  <button
                    type="button"
                    className="crm-message-ack"
                    disabled={acknowledging}
                    onClick={(event) => {
                      event.stopPropagation();
                      onAcknowledgeDeliveryError(message);
                    }}
                  >
                    <Check size={14} weight="bold" />
                    {acknowledging ? "Marking..." : "Seen"}
                  </button>
                ) : hasDeliveryError ? (
                  <span className="crm-message-ack-status">
                    <Check size={14} weight="bold" />
                    Seen
                  </span>
                ) : null}
              </div>
              <MessageMedia message={message} />
              <p className="crm-message-body">{message.text || ""}</p>
              {hasDeliveryError ? (
                <details className="crm-message-error">
                  <summary>Why it failed</summary>
                  <p>{message.last_delivery_error || "WhatsApp reported a delivery failure without details."}</p>
                  <span>{message.delivery_attempts ? `${message.delivery_attempts} send attempts` : "No retry metadata"}</span>
                  {message.delivery_error_acknowledged_at ? (
                    <span>Seen {relativeTime(message.delivery_error_acknowledged_at)}</span>
                  ) : null}
                </details>
              ) : null}
            </article>
          </div>
        );
      })}
    </div>
  );
}

function MessageMedia({ message }: { message: MessageItem }) {
  if (!message.media_url) {
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
  blockReason,
  value,
  files,
  onChange,
  onFilesChange,
  onSubmit,
}: {
  disabled: boolean;
  blockReason: string | null;
  value: string;
  files: File[];
  onChange: (value: string) => void;
  onFilesChange: (files: File[]) => void;
  onSubmit: (event: FormEvent<HTMLFormElement>) => void;
}) {
  const [dragActive, setDragActive] = useState(false);
  const hasContent = Boolean(value.trim() || files.length);
  const blocked = Boolean(blockReason);

  function usableFiles(fileList: FileList | File[]): File[] {
    return Array.from(fileList).filter((item) => item.size > 0);
  }

  function mergeFiles(nextFiles: File[]) {
    if (!nextFiles.length) {
      return;
    }
    const seen = new Set(files.map((item) => `${item.name}:${item.size}:${item.lastModified}`));
    const merged = [...files];
    nextFiles.forEach((item) => {
      const key = `${item.name}:${item.size}:${item.lastModified}`;
      if (!seen.has(key)) {
        seen.add(key);
        merged.push(item);
      }
    });
    onFilesChange(merged);
  }

  function filesFromClipboard(event: ClipboardEvent<HTMLElement>): File[] {
    const pastedFiles = usableFiles(event.clipboardData.files);
    if (pastedFiles.length) {
      return pastedFiles;
    }
    const result: File[] = [];
    for (const item of Array.from(event.clipboardData.items)) {
      const pastedFile = item.kind === "file" ? item.getAsFile() : null;
      if (pastedFile && pastedFile.size > 0) {
        result.push(pastedFile);
      }
    }
    return result;
  }

  function handleDragOver(event: DragEvent<HTMLFormElement>) {
    if (!Array.from(event.dataTransfer.types).includes("Files")) {
      return;
    }
    event.preventDefault();
    event.dataTransfer.dropEffect = disabled || blocked ? "none" : "copy";
    setDragActive(true);
  }

  function handleDragLeave(event: DragEvent<HTMLFormElement>) {
    const nextTarget = event.relatedTarget;
    if (nextTarget instanceof Node && event.currentTarget.contains(nextTarget)) {
      return;
    }
    setDragActive(false);
  }

  function handleDrop(event: DragEvent<HTMLFormElement>) {
    if (!Array.from(event.dataTransfer.types).includes("Files")) {
      return;
    }
    event.preventDefault();
    setDragActive(false);
    if (!disabled && !blocked) {
      mergeFiles(usableFiles(event.dataTransfer.files));
    }
  }

  function handlePaste(event: ClipboardEvent<HTMLFormElement>) {
    const pastedFiles = filesFromClipboard(event);
    if (!pastedFiles.length || disabled || blocked) {
      return;
    }
    event.preventDefault();
    mergeFiles(pastedFiles);
  }

  function removeFile(indexToRemove: number) {
    onFilesChange(files.filter((_, index) => index !== indexToRemove));
  }

  return (
    <form
      className={`ct-manual ${dragActive ? "drag-active" : ""}`}
      onSubmit={onSubmit}
      onDragOver={handleDragOver}
      onDragLeave={handleDragLeave}
      onDrop={handleDrop}
      onPaste={handlePaste}
    >
      <div className="ct-manual-head">
        <span className="ct-manual-lock">Manual outbound</span>
        <p className={`ct-manual-hint ${blocked ? "blocked" : ""}`}>
          {blockReason || "Sending a custom message pauses automation for this lead."}
        </p>
      </div>
      <textarea
        value={value}
        onChange={(event) => onChange(event.target.value)}
        disabled={disabled || blocked}
        rows={3}
        placeholder="Write the WhatsApp message to send, or drop/paste a file..."
      />
      <div className="ct-manual-file-row">
        <label className="ct-manual-file-picker">
          <UploadSimple size={14} weight="bold" />
          <span>{files.length ? "Add files" : "Attach files"}</span>
          <input
            type="file"
            multiple
            disabled={disabled || blocked}
            onChange={(event) => {
              mergeFiles(usableFiles(event.target.files ?? []));
              event.currentTarget.value = "";
            }}
          />
        </label>
        {files.length ? (
          <div className="ct-manual-file-list">
            {files.map((file, index) => (
              <div className="ct-manual-file-chip" key={`${file.name}:${file.size}:${file.lastModified}:${index}`}>
                <span>{file.name}</span>
                <strong>{formatBytes(file.size)}</strong>
                <button type="button" onClick={() => removeFile(index)} disabled={disabled || blocked} aria-label={`Remove ${file.name}`}>
                  <Trash size={13} weight="bold" />
                </button>
              </div>
            ))}
          </div>
        ) : (
          <p className="ct-manual-hint">Drop files here or paste images/files from clipboard.</p>
        )}
      </div>
      <div className="ct-manual-actions">
        <button type="submit" className="ct-btn ct-btn-primary" disabled={disabled || blocked || !hasContent}>Send and pause automation</button>
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
              Sheet: {config?.last_sheet_sync_status || "idle"} · Ready: {runtime?.ready ? "yes" : "review"}
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
  customBlockReason,
  busy,
  onKindChange,
  onTextChange,
  onClose,
  onSubmit,
}: {
  kind: SendKind;
  text: string;
  funnel: FunnelDefinition | null;
  customBlockReason: string | null;
  busy: boolean;
  onKindChange: (kind: SendKind) => void;
  onTextChange: (value: string) => void;
  onClose: () => void;
  onSubmit: (event: FormEvent<HTMLFormElement>) => void;
}) {
  const marksCalendlySent = kind === "send-calendly" || kind === "send-calendly-link";
  const pausesAutomation = !marksCalendlySent;
  const availableOptions = funnel?.kind === "inbox"
    ? sendOptions.filter((option) => ["custom", "send-opener", "send-manual-ping"].includes(option.value))
    : sendOptions;
  const customBlocked = Boolean(customBlockReason);

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
            <strong>Heads up:</strong> {pausesAutomation ? "sending this pauses the bot for this lead. You can resume automation after." : "sending Calendly marks the lead as Calendly sent and keeps it in Manual."}
          </p>

          <fieldset className="ct-send-options">
            <legend className="ct-sr-only">Message type</legend>
            {availableOptions.map((option) => (
              <label className="ct-send-option" key={option.value}>
                <input
                  type="radio"
                  name="ctSendKind"
                  value={option.value}
                  disabled={option.value === "custom" && customBlocked}
                  checked={kind === option.value}
                  onChange={() => onKindChange(option.value)}
                />
                <div>
                  <strong>{option.title}</strong>
                  <span>{option.value === "custom" && customBlockReason ? customBlockReason : sendOptionPreview(option.value, funnel) || option.help}</span>
                </div>
              </label>
            ))}
          </fieldset>

          <label className="ct-modal-field" hidden={kind !== "custom"}>
            <span>Custom message</span>
            <textarea
              value={text}
              onChange={(event) => onTextChange(event.target.value)}
              disabled={customBlocked}
              rows={4}
              placeholder="Write the WhatsApp message to send..."
            />
          </label>
        </div>
        <footer className="ct-modal-foot">
          <button type="button" className="ct-btn ct-btn-ghost" onClick={onClose}>Cancel</button>
          <button type="submit" className="ct-btn ct-btn-primary" disabled={busy || (kind === "custom" && (customBlocked || !text.trim()))}>
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
  tagsText,
  funnel,
  selectedCount,
  customBlockedCount,
  closedCount,
  manualPingConfirmed,
  busy,
  onKindChange,
  onManualPingConfirmedChange,
  onTextChange,
  onTagsTextChange,
  onClose,
  onSubmit,
}: {
  kind: BulkSendKind;
  text: string;
  tagsText: string;
  funnel: FunnelDefinition | null;
  selectedCount: number;
  customBlockedCount: number;
  closedCount: number;
  manualPingConfirmed: boolean;
  busy: boolean;
  onKindChange: (kind: BulkSendKind) => void;
  onManualPingConfirmedChange: (confirmed: boolean) => void;
  onTextChange: (value: string) => void;
  onTagsTextChange: (value: string) => void;
  onClose: () => void;
  onSubmit: (event: FormEvent<HTMLFormElement>) => void;
}) {
  const marksCalendlySent = kind === "send-calendly" || kind === "send-calendly-link";
  const pausesAutomation = kind !== "set-tags" && !marksCalendlySent;
  const sendActionOptions = funnel?.kind === "inbox"
    ? sendOptions.filter((option) => ["custom", "send-opener", "send-manual-ping"].includes(option.value))
    : sendOptions;
  const availableOptions = [
    ...sendActionOptions,
    { value: "set-tags" as const, title: "Set tags", help: "Replace tags for the selected leads." },
  ];
  const tagValues = tagsText.split(",").map((tag) => tag.trim()).filter(Boolean);
  const customBlocked = customBlockedCount > 0;
  const closedBlocked = closedCount > 0 && kind !== "set-tags";
  const manualPingNeedsConfirmation = kind === "send-manual-ping" && !manualPingConfirmed;

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
            {closedBlocked
              ? ` ${closedCount} selected lead${closedCount === 1 ? " is" : "s are"} closed. Reopen before sending WhatsApp messages.`
              : kind === "set-tags"
              ? " Tags will be replaced for those leads."
              : pausesAutomation
                ? " Sending this pauses automation for those leads."
                : " Calendly will mark them as Calendly sent and keep them in Manual."}
          </p>

          <fieldset className="ct-send-options">
            <legend className="ct-sr-only">Bulk action type</legend>
            {availableOptions.map((option) => (
              <label className="ct-send-option" key={option.value}>
                <input
                  type="radio"
                  name="ctBulkSendKind"
                  value={option.value}
                  disabled={(option.value !== "set-tags" && closedCount > 0) || (option.value === "custom" && customBlocked)}
                  checked={kind === option.value}
                  onChange={() => onKindChange(option.value)}
                />
                <div>
                  <strong>{option.title}</strong>
                  <span>
                    {option.value === "custom" && customBlocked
                      ? `Custom WhatsApp is blocked for ${customBlockedCount} selected chat${customBlockedCount === 1 ? "" : "s"} because the 24-hour window is closed.`
                      : option.value === "set-tags" ? option.help : sendOptionPreview(option.value, funnel) || option.help}
                  </span>
                </div>
              </label>
            ))}
          </fieldset>

          <label className="ct-modal-field" hidden={kind !== "custom"}>
            <span>Custom message</span>
            <textarea
              value={text}
              onChange={(event) => onTextChange(event.target.value)}
              disabled={customBlocked}
              rows={4}
              placeholder="Write the WhatsApp message to send..."
            />
          </label>

          <label className="ct-modal-field" hidden={kind !== "set-tags"}>
            <span>Tags</span>
            <input
              value={tagsText}
              onChange={(event) => onTagsTextChange(event.target.value)}
              placeholder="prioridad, whatsapp_funnel"
            />
          </label>

          <label className="ct-modal-field ct-modal-check" hidden={kind !== "send-manual-ping"}>
            <input
              type="checkbox"
              checked={manualPingConfirmed}
              onChange={(event) => onManualPingConfirmedChange(event.target.checked)}
            />
            <span>I explicitly want to send Manual ping to every selected chat.</span>
          </label>
        </div>
        <footer className="ct-modal-foot">
          <button type="button" className="ct-btn ct-btn-ghost" onClick={onClose}>Cancel</button>
          <button type="submit" className="ct-btn ct-btn-primary" disabled={busy || !selectedCount || closedBlocked || manualPingNeedsConfirmation || (kind === "custom" && (customBlocked || !text.trim())) || (kind === "set-tags" && !tagValues.length)}>
            {busy ? "Applying..." : `Apply to ${selectedCount}`}
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
    kind: "campaign",
    enabled: true,
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
    video_check_text: "conseguiste ver el video?",
    calendly_intro_text: "Para avanzar, el siguiente paso es elegir un horario en el calendario:",
    calendly_base_url: "https://calendly.com/facundogoiriz/crecimiento",
    alert_emails: [],
    whatsapp_referral_source_ids: [],
    initial_reply_quiet_seconds: 30,
    post_loom_min_seconds: 600,
    post_loom_quiet_seconds: 30,
    strategies: [
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
    "offer-solo-page-promo": "Solo pagina web profesional. Precio ponderado hacia 99/49 USD.",
    "send-opener": funnel.opener_text,
    "send-loom": funnel.loom_intro_text,
    "send-accountant-page-example-video": "Esta es una pagina de un cliente contador nuestro, asi podria verse tu pagina",
    "send-lawyer-page-example-video": "Esta es una pagina de un cliente abogado nuestro, asi podria verse tu pagina",
    "send-video-check": funnel.video_check_text,
    "send-calendly": `${funnel.calendly_intro_text}\n${funnel.calendly_base_url}`,
    "send-calendly-link": funnel.calendly_base_url,
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

function formatBytes(value: number): string {
  if (!Number.isFinite(value) || value <= 0) {
    return "0 B";
  }
  if (value < 1024) {
    return `${value} B`;
  }
  if (value < 1024 * 1024) {
    return `${Math.round(value / 1024)} KB`;
  }
  return `${(value / (1024 * 1024)).toFixed(1)} MB`;
}

function formatWorkstationOffer(client: WorkstationClientSummary | null | undefined): string {
  if (!client?.offer_price_usd || client.offer_price_usd <= 0) {
    return "";
  }
  return `${client.offer_price_usd} ${client.offer_currency || "USD"}`;
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

function buildLeadContextText({
  lead,
  funnel,
  messages,
  inboxMode,
}: {
  lead: LeadSummary;
  funnel: FunnelDefinition | null;
  messages: MessageItem[];
  inboxMode: boolean;
}): string {
  const lastActivity = lastInteractionAt(lead);
  const whatsappWindow = customMessageBlockReason(lead) || "Custom WhatsApp window is open.";
  const latestMessages = messages.slice(-5).map(formatLeadContextMessage);
  const funnelLabel = funnel ? `${funnel.label} (${funnel.id})` : lead.funnel_id;
  const status = inboxMode ? "Inbox" : formatStageLabel(lead.stage);

  const lines = [
    `Lead: ${lead.full_name || lead.phone || lead.external_lead_id || lead.id}`,
    `Funnel: ${funnelLabel}`,
    `Status: ${status}`,
    `Manual reply: ${humanize(lead.manual_reply_status || "")}`,
    `WhatsApp window: ${whatsappWindow}`,
    `Phone: ${lead.phone || "-"}`,
    `Normalized phone: ${lead.normalized_phone || "-"}`,
    `Email: ${lead.email || "-"}`,
    `Platform: ${lead.platform || "-"}`,
    `External lead ID: ${lead.external_lead_id || "-"}`,
    `Tags: ${lead.tags.length ? lead.tags.join(", ") : "-"}`,
    `Calendly: ${lead.calendly_url || "-"}`,
    `Last activity: ${relativeTime(lastActivity)} (${shortDate(lastActivity)})`,
    `Automation: ${lead.automation_paused ? `Paused (${humanize(lead.automation_paused_reason || "")})` : "Active"}`,
    `Workstation: ${lead.workstation_client_id || "-"}`,
  ];

  if (lead.latest_outbound_error) {
    lines.push(`Latest delivery error: ${lead.latest_outbound_error}`);
  }

  lines.push("", "Recent messages:");
  if (latestMessages.length) {
    lines.push(...latestMessages);
  } else {
    lines.push("- No messages loaded yet.");
  }

  return lines.join("\n");
}

function formatLeadContextMessage(message: MessageItem): string {
  const sender = message.from_me ? "Operator" : "Lead";
  const status = humanize(message.delivery_status);
  const text = message.text?.trim() || message.media_caption?.trim() || `[${humanize(message.media_type || "media")}]`;
  return `- ${shortDate(message.created_at)} ${sender} (${status}): ${truncate(text, 220)}`;
}

function PhoneCountryFlag({ phone }: { phone: string | null | undefined }) {
  const country = phoneCountry(phone);
  if (!country) {
    return null;
  }

  return (
    <span className="ct-phone-flag" aria-label={country.name} title={country.name}>
      {countryFlag(country.iso2)}
    </span>
  );
}

const PHONE_COUNTRIES = [
  { code: "1939", iso2: "PR", name: "Puerto Rico" },
  { code: "1849", iso2: "DO", name: "Dominican Republic" },
  { code: "1829", iso2: "DO", name: "Dominican Republic" },
  { code: "1809", iso2: "DO", name: "Dominican Republic" },
  { code: "1787", iso2: "PR", name: "Puerto Rico" },
  { code: "598", iso2: "UY", name: "Uruguay" },
  { code: "595", iso2: "PY", name: "Paraguay" },
  { code: "593", iso2: "EC", name: "Ecuador" },
  { code: "591", iso2: "BO", name: "Bolivia" },
  { code: "507", iso2: "PA", name: "Panama" },
  { code: "506", iso2: "CR", name: "Costa Rica" },
  { code: "505", iso2: "NI", name: "Nicaragua" },
  { code: "504", iso2: "HN", name: "Honduras" },
  { code: "503", iso2: "SV", name: "El Salvador" },
  { code: "502", iso2: "GT", name: "Guatemala" },
  { code: "351", iso2: "PT", name: "Portugal" },
  { code: "58", iso2: "VE", name: "Venezuela" },
  { code: "57", iso2: "CO", name: "Colombia" },
  { code: "56", iso2: "CL", name: "Chile" },
  { code: "55", iso2: "BR", name: "Brazil" },
  { code: "54", iso2: "AR", name: "Argentina" },
  { code: "53", iso2: "CU", name: "Cuba" },
  { code: "52", iso2: "MX", name: "Mexico" },
  { code: "51", iso2: "PE", name: "Peru" },
  { code: "49", iso2: "DE", name: "Germany" },
  { code: "44", iso2: "GB", name: "United Kingdom" },
  { code: "39", iso2: "IT", name: "Italy" },
  { code: "34", iso2: "ES", name: "Spain" },
  { code: "33", iso2: "FR", name: "France" },
  { code: "1", iso2: "US", name: "United States" },
] as const;

function phoneCountry(phone: string | null | undefined): (typeof PHONE_COUNTRIES)[number] | null {
  const digits = (phone || "").replace(/\D/g, "");
  if (!digits) {
    return null;
  }
  return PHONE_COUNTRIES.find((country) => digits.startsWith(country.code)) ?? null;
}

function countryFlag(iso2: string): string {
  return iso2
    .toUpperCase()
    .replace(/[A-Z]/g, (letter) => String.fromCodePoint(0x1f1e6 + letter.charCodeAt(0) - 65));
}

function customMessageBlockReason(lead: LeadSummary | null): string | null {
  if (!lead) {
    return null;
  }
  if (lead.stage === "closed") {
    return "This lead is closed. Reopen it before sending WhatsApp messages.";
  }
  if (!lead.last_inbound_at) {
    return "Custom WhatsApp is blocked until the lead sends a message. Use an approved template such as Manual ping.";
  }
  const lastInboundAt = new Date(lead.last_inbound_at).getTime();
  if (Number.isNaN(lastInboundAt)) {
    return "Custom WhatsApp is blocked because the last inbound time is unavailable. Use an approved template such as Manual ping.";
  }
  if (Date.now() - lastInboundAt >= WHATSAPP_CUSTOM_WINDOW_MS) {
    return "The 24-hour WhatsApp window is closed. Use an approved template such as Manual ping.";
  }
  return null;
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
