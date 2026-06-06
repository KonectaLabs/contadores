import { useCallback, useEffect, useLayoutEffect, useMemo, useRef, useState } from "react";
import type { CSSProperties, ClipboardEvent, DragEvent, FormEvent, KeyboardEvent, PointerEvent as ReactPointerEvent, ReactNode } from "react";
import {
  ArrowsClockwise,
  ArrowSquareOut,
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
  GearSix,
  ListChecks,
  Megaphone,
  NotePencil,
  PaperPlaneTilt,
  PauseCircle,
  Plus,
  Pulse,
  Robot,
  SpinnerGap,
  Trash,
  UploadSimple,
  WarningCircle,
  X,
} from "@phosphor-icons/react";
import { apiFetch } from "./api";
import { compactNumber, humanize, lastInteractionAt, relativeTime, shortDate } from "./format";
import type {
  BulkActionResponse,
  ClientLead,
  ClientLeadCopyAllResponse,
  ClientLeadListResponse,
  ClientLeadRecipientChatResponse,
  ClientLeadRecipientCrmLead,
  ClientLeadRecipientChatMessage,
  ClientLeadSource,
  ClientLeadSourceListResponse,
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
const DELIVERY_AUTO_SYNC_MS = 10000;
const WHATSAPP_CUSTOM_WINDOW_MS = 24 * 60 * 60 * 1000;
const DASHBOARD_FUNNEL_STORAGE_KEY = "contadores.dashboard.selectedFunnelId";
const DASHBOARD_LEAD_VIEW_FILTER_STORAGE_KEY = "contadores.dashboard.leadViewFilter";
const LEGACY_DASHBOARD_STAGE_FILTER_STORAGE_KEY = "contadores.dashboard.stageFilter";
const DASHBOARD_SECTION_STORAGE_KEY = "contadores.dashboard.activeSection";
const DASHBOARD_CRM_LEADS_WIDTH_STORAGE_KEY = "contadores.dashboard.crmLeadsWidth";
const CRM_LEADS_DEFAULT_WIDTH = 360;
const CRM_LEADS_MIN_WIDTH = 280;
const CRM_LEADS_MAX_WIDTH = 620;
const CRM_DETAIL_MIN_WIDTH = 440;
const CRM_STACKED_LAYOUT_WIDTH = 1180;

type LeadViewFilterValue =
  | LeadStage
  | "all"
  | "manual_attention";
type LeadViewFilterOption = {
  value: LeadViewFilterValue;
  label: string;
  metric?: keyof ContadoresMetrics;
  tone: "all" | "neutral" | "accent" | "success" | "warn" | "muted";
};
type ActiveSection = "crm" | "campaigns" | "workstation" | "delivery";
type LoadWorkstationDetailOptions = {
  syncNotes?: boolean;
  showLoading?: boolean;
};
type DeliveryEditorMode = "edit" | "create";
type ConfirmDialogTone = "danger" | "warn";
type ConfirmDialogState = {
  id: string;
  tone: ConfirmDialogTone;
  title: string;
  message: string;
  confirmLabel: string;
  busyLabel: string;
  busyKey: string;
  onConfirm: () => void | Promise<void>;
};
const CONFIRM_FOCUSABLE_SELECTOR = [
  "button:not([disabled])",
  "input:not([disabled])",
  "select:not([disabled])",
  "textarea:not([disabled])",
  "a[href]",
  "[tabindex]:not([tabindex='-1'])",
].join(",");
type ClientLeadSourceDraft = {
  id: string;
  label: string;
  enabled: boolean;
  sheet_url: string;
  sheet_gid: string;
  sheet_tab_name: string;
  sheet_poll_seconds: number;
  recipient_name: string;
  recipient_phone: string;
  template_name: string;
  template_language: string;
  column_mapping_text: string;
  context_field_mapping_text: string;
};
type ClientLeadSourceDraftField = keyof ClientLeadSourceDraft;
type ClientLeadSourceDraftValidation = {
  canSave: boolean;
  fields: Partial<Record<ClientLeadSourceDraftField, string>>;
  messages: string[];
  summary: string;
};
type ClientLeadSourceMutationPayload = {
  id: string;
  label: string;
  enabled: boolean;
  sheet_url: string | null;
  sheet_gid: string | null;
  sheet_tab_name: string | null;
  sheet_poll_seconds: number;
  recipient_name: string | null;
  recipient_phone: string | null;
  template_name: string | null;
  template_language: string | null;
  column_mapping: Record<string, string>;
  context_field_mapping: Record<string, string>;
};

const leadViewFilters: LeadViewFilterOption[] = [
  { value: "all", label: "All", metric: "total", tone: "all" },
  { value: "awaiting_initial_reply", label: "Opener sent", metric: "awaiting_initial_reply", tone: "neutral" },
  { value: "awaiting_video_reply", label: "Offer sent", metric: "awaiting_video_reply", tone: "neutral" },
  { value: "calendly_sent", label: "Meeting sent", metric: "calendly_sent", tone: "accent" },
  { value: "booked", label: "Booked", metric: "booked", tone: "success" },
  { value: "needs_human", label: "Manual", metric: "needs_human", tone: "warn" },
  { value: "manual_attention", label: "Needs answer", metric: "attention_needs_reply", tone: "warn" },
  { value: "closed", label: "Closed", metric: "closed", tone: "muted" },
];

const validLeadViewFilterValues = new Set<LeadViewFilterValue>(leadViewFilters.map((filter) => filter.value));
// Compat-only aliases for localStorage values written by the grouped filter.
const legacyLeadViewFilterAliases: Record<string, LeadViewFilterValue> = {
  "pipeline:new": "awaiting_initial_reply",
  "pipeline:contacted": "awaiting_initial_reply",
  "pipeline:offer_sent": "awaiting_video_reply",
  "pipeline:meeting_sent": "calendly_sent",
  "pipeline:converted": "booked",
  "attention:needs_reply": "manual_attention",
  "queue:operator": "needs_human",
  "queue:paused": "all",
  "terminal:closed": "closed",
};

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

function readStoredLeadViewFilter(): LeadViewFilterValue {
  const value = readStoredValue(DASHBOARD_LEAD_VIEW_FILTER_STORAGE_KEY)
    ?? readStoredValue(LEGACY_DASHBOARD_STAGE_FILTER_STORAGE_KEY);
  if (validLeadViewFilterValues.has(value as LeadViewFilterValue)) {
    return value as LeadViewFilterValue;
  }
  return legacyLeadViewFilterAliases[value || ""] ?? "all";
}

function clampNumber(value: number, min: number, max: number): number {
  return Math.min(Math.max(value, min), max);
}

function readStoredCrmLeadsWidth(): number {
  const storedWidth = Number(readStoredValue(DASHBOARD_CRM_LEADS_WIDTH_STORAGE_KEY));

  if (!Number.isFinite(storedWidth)) {
    return CRM_LEADS_DEFAULT_WIDTH;
  }

  return clampNumber(storedWidth, CRM_LEADS_MIN_WIDTH, CRM_LEADS_MAX_WIDTH);
}

function CtEmptyState({
  title,
  message,
  action,
  compact = false,
  loading = false,
}: {
  title: string;
  message: string;
  action?: ReactNode;
  compact?: boolean;
  loading?: boolean;
}) {
  return (
    <div className={`ct-empty-state ${compact ? "compact" : ""}`} role="status" aria-live="polite">
      {loading ? <SpinnerGap className="ct-empty-state-icon" size={18} weight="bold" aria-hidden="true" /> : null}
      <strong>{title}</strong>
      <span>{message}</span>
      {action}
    </div>
  );
}

function applyLeadViewFilter(params: URLSearchParams, filter: LeadViewFilterValue) {
  if (filter === "all") {
    return;
  }

  if (filter === "manual_attention") {
    params.set("stage", "needs_human");
    params.set("manual_reply_status", "needs_reply");
    params.set("needs_human", "true");
    return;
  }

  params.set("stage", filter);
}

function readStoredActiveSection(): ActiveSection {
  const value = readStoredValue(DASHBOARD_SECTION_STORAGE_KEY);
  if (value === "runner") {
    return "crm";
  }
  if (value === "campaigns" || value === "workstation" || value === "delivery") {
    return value;
  }
  return "crm";
}

const operations: Array<{
  section: ActiveSection;
  label: string;
  icon: ReactNode;
}> = [
  {
    section: "crm",
    label: "CRM",
    icon: <ListChecks size={16} weight="bold" />,
  },
  {
    section: "campaigns",
    label: "Ads",
    icon: <Megaphone size={16} weight="bold" />,
  },
  {
    section: "workstation",
    label: "Build",
    icon: <Robot size={16} weight="bold" />,
  },
  {
    section: "delivery",
    label: "Deliver",
    icon: <PaperPlaneTilt size={16} weight="bold" />,
  },
];

const campaignRouteOptions: Array<{ value: LeadStage; label: string }> = [
  { value: "needs_human", label: "Operator follow-up" },
  { value: "awaiting_initial_reply", label: "Start sequence" },
  { value: "awaiting_video_reply", label: "Offer follow-up" },
  { value: "calendly_sent", label: "Meeting follow-up" },
];

const sendOptions = [
  { value: "custom", title: "Custom message", help: "Write your own WhatsApp reply." },
  { value: "send-manual-ping", title: "Follow-up ping", help: "Send the approved follow-up template to reopen WhatsApp." },
  { value: "offer-solo-page-promo", title: "Promo solo pagina", help: "Offer the page-only promo and let automation handle the reply." },
  { value: "send-opener", title: "Opener", help: "Queue the default opener template." },
  { value: "send-loom", title: "Send offer", help: "Queue the configured offer message." },
  { value: "send-accountant-page-example-video", title: "Pagina contador", help: "Send the accountant page example video." },
  { value: "send-lawyer-page-example-video", title: "Pagina abogado", help: "Send the lawyer page example video." },
  { value: "send-video-check", title: "Offer check", help: "Ask if they want to review the offer on a short call." },
  { value: "send-calendly", title: "Meeting with intro", help: "Send the meeting details and meeting link." },
  { value: "send-calendly-link", title: "Meeting link only", help: "Send only the meeting link and mark meeting sent." },
] as const;

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
  | "pause-automation"
  | "mark-answered"
  | "mark-converted"
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

function useScrollChatToLatestMessage(messages: MessageItem[], hasLead: boolean) {
  const timelineRef = useRef<HTMLDivElement | null>(null);
  const messageIds = messages.map((message) => message.id).join(",");

  useLayoutEffect(() => {
    if (!hasLead || !timelineRef.current || !messages.length) {
      return;
    }

    const scrollContainer = findScrollContainer(timelineRef.current);
    scrollContainer.scrollTop = scrollContainer.scrollHeight;
  }, [hasLead, messages.length, messageIds]);

  return timelineRef;
}

function findScrollContainer(element: HTMLElement): HTMLElement {
  let current: HTMLElement | null = element;

  while (current) {
    const style = window.getComputedStyle(current);
    const canScroll = /(auto|scroll)/.test(`${style.overflowY} ${style.overflow}`);

    if (canScroll) {
      return current;
    }

    current = current.parentElement;
  }

  return document.documentElement;
}

export function App() {
  const [activeSection, setActiveSection] = useState<ActiveSection>(readStoredActiveSection);
  const [runtime, setRuntime] = useState<RuntimeSettings | null>(null);
  const [funnels, setFunnels] = useState<FunnelDefinition[]>([]);
  const [funnelConfigPath, setFunnelConfigPath] = useState("");
  const [funnelConfigErrors, setFunnelConfigErrors] = useState<string[]>([]);
  const [selectedFunnelId, setSelectedFunnelId] = useState(readStoredFunnelId);
  const [leadList, setLeadList] = useState<LeadListResponse | null>(null);
  const [manualAttentionCounts, setManualAttentionCounts] = useState<Record<string, number>>({});
  const [strategyStats, setStrategyStats] = useState<StrategyStatsItem[]>([]);
  const [detail, setDetail] = useState<LeadDetailResponse | null>(null);
  const [selectedLeadId, setSelectedLeadId] = useState<string | null>(null);
  const [leadViewFilter, setLeadViewFilter] = useState<LeadViewFilterValue>(readStoredLeadViewFilter);
  const [crmLeadsWidth, setCrmLeadsWidth] = useState(readStoredCrmLeadsWidth);
  const [tagFilter, setTagFilter] = useState("");
  const [strategyFilter, setStrategyFilter] = useState<{ step: string; strategyId: string }>({ step: "", strategyId: "" });
  const [query, setQuery] = useState("");
  const [loading, setLoading] = useState(true);
  const [detailLoading, setDetailLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [actionBusy, setActionBusy] = useState<string | null>(null);
  const [confirmDialog, setConfirmDialog] = useState<ConfirmDialogState | null>(null);
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
  const [workstationListLoading, setWorkstationListLoading] = useState(false);
  const [workstationLoading, setWorkstationLoading] = useState(false);
  const [deliverySources, setDeliverySources] = useState<ClientLeadSource[]>([]);
  const [deliveryLeads, setDeliveryLeads] = useState<ClientLead[]>([]);
  const [selectedDeliverySourceId, setSelectedDeliverySourceId] = useState<string | null>(null);
  const [deliveryEditorMode, setDeliveryEditorMode] = useState<DeliveryEditorMode>("edit");
  const [deliverySourceDraft, setDeliverySourceDraft] = useState<ClientLeadSourceDraft>(buildBlankClientLeadSourceDraft);
  const [deliverySourceEditorError, setDeliverySourceEditorError] = useState("");
  const [deliveryLoading, setDeliveryLoading] = useState(false);
  const [deliveryLeadsLoading, setDeliveryLeadsLoading] = useState(false);
  const [deliveryRecipientChat, setDeliveryRecipientChat] = useState<ClientLeadRecipientChatResponse | null>(null);
  const [deliveryRecipientChatLoading, setDeliveryRecipientChatLoading] = useState(false);
  const [deliveryCopyStatus, setDeliveryCopyStatus] = useState("");
  const [campaignRefreshSignal, setCampaignRefreshSignal] = useState(0);
  const [acknowledgingDeliveryErrorIds, setAcknowledgingDeliveryErrorIds] = useState<number[]>([]);
  const [leadContextCopyStatus, setLeadContextCopyStatus] = useState("");
  const detailRequestId = useRef(0);
  const dashboardRequestId = useRef(0);
  const workstationDetailRequestId = useRef(0);
  const workstationLoadingRequestId = useRef(0);
  const deliveryDraftSourceId = useRef<string | null>(null);
  const deliverySourcesRef = useRef<ClientLeadSource[]>([]);
  const previousFunnelIdRef = useRef(selectedFunnelId);
  const crmWorkspaceRef = useRef<HTMLDivElement | null>(null);
  const debouncedQuery = useDebouncedValue(query, 250);
  const debouncedWorkstationQuery = useDebouncedValue(workstationQuery, 250);

  const metrics = leadList?.metrics;
  const tagOptions = leadList?.tag_options ?? [];
  const config = leadList?.config ?? detail?.config ?? null;
  const selectedFunnel = funnels.find((funnel) => funnel.id === selectedFunnelId) ?? funnels[0] ?? null;
  const selectedFunnelSetupIssues = buildFunnelSetupIssues(selectedFunnel);
  const isCrmWorkspace = activeSection === "crm";
  const crmModeLabel = "CRM";
  const crmLeadListTitle = "Leads";
  const crmLeadListSummary = "Reply, unblock, or route";
  const isContadoresFunnel = true;
  const isInboxFunnel = selectedFunnel?.kind === "inbox";
  const canEditLegacyRuntimeConfig = selectedFunnel?.id === "contadores";

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
  const visibleLeadIdSet = useMemo(() => new Set(visibleLeadIds), [visibleLeadIds]);
  const selectedLeadIdSet = useMemo(() => new Set(selectedLeadIds), [selectedLeadIds]);
  const selectedVisibleLeads = useMemo(
    () => (leadList?.leads ?? []).filter((lead) => selectedLeadIdSet.has(lead.id)),
    [leadList, selectedLeadIdSet],
  );
  const selectedVisibleLeadIds = useMemo(() => selectedVisibleLeads.map((lead) => lead.id), [selectedVisibleLeads]);
  const selectedLeadCustomBlockReason = customMessageBlockReason(selectedLead);
  const bulkCustomBlockedCount = selectedVisibleLeads.filter((lead) => customMessageBlockReason(lead)).length;
  const bulkClosedCount = selectedVisibleLeads.filter(isLeadClosed).length;
  const bulkConvertedCount = selectedVisibleLeads.filter(isLeadConverted).length;
  const bulkArchivedCount = selectedVisibleLeads.filter(isLeadArchived).length;
  const bulkOutboundBlockedCount = bulkSendKind === "set-tags"
    ? 0
    : bulkClosedCount + bulkConvertedCount + bulkArchivedCount;
  const workstationClients = workstationList?.clients ?? [];
  const selectedDeliverySource = deliveryEditorMode === "edit"
    ? deliverySources.find((source) => source.id === selectedDeliverySourceId) ?? null
    : null;
  const deliveryContactGroups = useMemo(() => buildDeliveryContactGroups(deliverySources), [deliverySources]);
  const deliveryLeadTotal = deliverySources.reduce((total, source) => total + deliverySourceCount(source, "total"), 0);
  const deliverySourceIssueCount = deliveryContactGroups.reduce((total, group) => total + group.issues, 0);
  const selectedVisibleCount = selectedVisibleLeadIds.length;
  const selectedHiddenCount = Math.max(0, selectedLeadIds.length - selectedVisibleCount);
  const allVisibleSelected = visibleLeadIds.length > 0 && selectedVisibleCount === visibleLeadIds.length;

  const loadDashboard = useCallback(async () => {
    setError(null);
    const requestId = dashboardRequestId.current + 1;
    dashboardRequestId.current = requestId;

    const [runtimePayload, funnelPayload, attentionCountsPayload] = await Promise.all([
      apiFetch<RuntimeSettings>("/api/runtime"),
      apiFetch<FunnelListResponse>("/api/funnels"),
      apiFetch<ManualAttentionCountsResponse>("/api/contadores/manual-attention-counts"),
    ]);

    if (dashboardRequestId.current !== requestId) {
      return;
    }

    setRuntime(runtimePayload);
    setFunnels(funnelPayload.funnels ?? []);
    setFunnelConfigPath(funnelPayload.config_path || "");
    setFunnelConfigErrors(funnelPayload.config_errors ?? []);
    setManualAttentionCounts(attentionCountsPayload.counts ?? {});

    if (!selectedFunnelId || !funnelPayload.funnels.some((funnel) => funnel.id === selectedFunnelId)) {
      setSelectedFunnelId(funnelPayload.funnels[0]?.id ?? "contadores");
    }

    const activeFunnel = funnelPayload.funnels.find((funnel) => funnel.id === selectedFunnelId) ?? funnelPayload.funnels[0];
    const activeFunnelId = activeFunnel?.id ?? "contadores";
    const activeIsInbox = activeFunnel?.kind === "inbox";
    const params = new URLSearchParams({ limit: "500", archived: "false", funnel_id: activeFunnelId });
    if (!activeIsInbox) {
      applyLeadViewFilter(params, leadViewFilter);
    }
    if (!activeIsInbox && strategyFilter.step) {
      params.set("strategy_step", strategyFilter.step);
    }
    if (!activeIsInbox && strategyFilter.strategyId) {
      params.set("strategy_id", strategyFilter.strategyId);
    }
    if (!activeIsInbox && tagFilter) {
      params.set("tag", tagFilter);
    }
    if (debouncedQuery.trim()) {
      params.set("query", debouncedQuery.trim());
    }

    const [leadsPayload, strategyPayload] = await Promise.all([
      apiFetch<LeadListResponse>(`/api/contadores/leads?${params.toString()}`),
      apiFetch<StrategyStatsResponse>(`/api/contadores/strategy-stats?funnel_id=${encodeURIComponent(activeFunnelId)}`),
    ]);

    if (dashboardRequestId.current !== requestId) {
      return;
    }

    setLeadList(leadsPayload);
    setStrategyStats(strategyPayload.items ?? []);

    setSelectedLeadId((current) => {
      const currentLeadIsVisible = Boolean(current && leadsPayload.leads.some((lead) => lead.id === current));
      if (currentLeadIsVisible) {
        return current;
      }
      return leadsPayload.leads[0]?.id ?? null;
    });
  }, [debouncedQuery, selectedFunnelId, leadViewFilter, strategyFilter.step, strategyFilter.strategyId, tagFilter]);

  const loadWorkstation = useCallback(async () => {
    const params = new URLSearchParams({ limit: "500" });
    if (selectedFunnelId) {
      params.set("funnel_id", selectedFunnelId);
    }
    if (debouncedWorkstationQuery.trim()) {
      params.set("query", debouncedWorkstationQuery.trim());
    }

    setWorkstationListLoading(true);
    try {
      const payload = await apiFetch<WorkstationClientListResponse>(`/api/workstation/clients?${params.toString()}`);
      setWorkstationList(payload);
      setSelectedWorkstationClientId((current) => {
        if (current && payload.clients.some((client) => client.id === current)) {
          return current;
        }
        return payload.clients[0]?.id ?? null;
      });
    } finally {
      setWorkstationListLoading(false);
    }
  }, [debouncedWorkstationQuery, selectedFunnelId]);

  const loadDeliverySources = useCallback(async () => {
    const payload = await apiFetch<ClientLeadSourceListResponse | ClientLeadSource[]>("/api/client-lead-sources");
    const sources = unpackClientLeadSources(payload).slice().sort(compareDeliverySources);
    setDeliverySources(sources);
    setSelectedDeliverySourceId((current) => {
      if (deliveryEditorMode === "create") {
        return current;
      }
      if (current && sources.some((source) => source.id === current)) {
        return current;
      }
      return sources[0]?.id ?? null;
    });
    return sources;
  }, [deliveryEditorMode]);

  const fetchDeliveryLeads = useCallback(async (sourceId: string) => {
    const payload = await apiFetch<ClientLeadListResponse | ClientLead[]>(
      `/api/client-lead-sources/${encodeURIComponent(sourceId)}/leads`,
    );
    return unpackClientLeads(payload);
  }, []);

  const loadDeliveryLeadsForSources = useCallback(async (sourceIds: string[]) => {
    if (!sourceIds.length) {
      setDeliveryLeads([]);
      return;
    }
    const batches = await Promise.all(sourceIds.map((sourceId) => fetchDeliveryLeads(sourceId)));
    setDeliveryLeads(batches.flat().sort(compareClientLeads));
  }, [fetchDeliveryLeads]);

  const loadDeliveryRecipientChat = useCallback(async (sourceId: string) => {
    const payload = await apiFetch<ClientLeadRecipientChatResponse>(
      `/api/client-lead-sources/${encodeURIComponent(sourceId)}/recipient-chat`,
    );
    setDeliveryRecipientChat(payload);
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
    const requestId = workstationDetailRequestId.current + 1;
    workstationDetailRequestId.current = requestId;
    const syncNotes = options.syncNotes ?? true;
    const showLoading = options.showLoading ?? true;
    const loadingRequestId = workstationLoadingRequestId.current + (showLoading ? 1 : 0);
    if (showLoading) {
      workstationLoadingRequestId.current = loadingRequestId;
      setWorkstationLoading(true);
      setWorkstationDetail((current) => current?.client.id === clientId ? current : null);
    }
    try {
      const payload = await apiFetch<WorkstationClientDetailResponse>(`/api/workstation/clients/${clientId}`);
      if (workstationDetailRequestId.current === requestId) {
        setWorkstationDetail(payload);
        if (syncNotes) {
          setWorkstationNotesDraft(payload.notes ?? "");
        }
        return payload;
      }
      return null;
    } finally {
      if (showLoading && workstationLoadingRequestId.current === loadingRequestId) {
        setWorkstationLoading(false);
      }
    }
  }, []);

  useEffect(() => {
    writeStoredValue(DASHBOARD_FUNNEL_STORAGE_KEY, selectedFunnelId);
  }, [selectedFunnelId]);

  useEffect(() => {
    if (previousFunnelIdRef.current === selectedFunnelId) {
      return;
    }
    previousFunnelIdRef.current = selectedFunnelId;
    setStrategyFilter({ step: "", strategyId: "" });
    setTagFilter("");
    setSelectedLeadIds([]);
  }, [selectedFunnelId]);

  useEffect(() => {
    writeStoredValue(DASHBOARD_SECTION_STORAGE_KEY, activeSection);
  }, [activeSection]);

  useEffect(() => {
    deliverySourcesRef.current = deliverySources;
  }, [deliverySources]);

  useEffect(() => {
    writeStoredValue(DASHBOARD_LEAD_VIEW_FILTER_STORAGE_KEY, leadViewFilter);
  }, [leadViewFilter]);

  useEffect(() => {
    writeStoredValue(DASHBOARD_CRM_LEADS_WIDTH_STORAGE_KEY, String(Math.round(crmLeadsWidth)));
  }, [crmLeadsWidth]);

  useEffect(() => {
    setSelectedLeadIds((current) => {
      const next = current.filter((leadId) => visibleLeadIdSet.has(leadId));
      return next.length === current.length ? current : next;
    });
  }, [visibleLeadIdSet]);

  useEffect(() => {
    if (!isInboxFunnel) {
      return;
    }
    setLeadViewFilter("all");
    setStrategyFilter({ step: "", strategyId: "" });
    setTagFilter("");
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
        const loaders: Array<Promise<unknown>> = [loadDashboard()];
        if (activeSection === "delivery") {
          loaders.push(loadDeliverySources());
          if (selectedDeliverySourceId) {
            const sourceIds = deliveryContactSourceIdsFor(deliverySourcesRef.current, selectedDeliverySourceId);
            loaders.push(loadDeliveryLeadsForSources(sourceIds));
            loaders.push(loadDeliveryRecipientChat(selectedDeliverySourceId));
          }
        }
        Promise.all(loaders).catch((reason) => {
          setError(reason instanceof Error ? reason.message : "Automatic refresh failed.");
        });
      }
    }, REFRESH_MS);
    return () => window.clearInterval(timer);
  }, [activeSection, loadDashboard, loadDeliveryLeadsForSources, loadDeliveryRecipientChat, loadDeliverySources, selectedDeliverySourceId]);

  useEffect(() => {
    if (!selectedLeadId || !isContadoresFunnel) {
      setDetail(null);
      return;
    }
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
    if (activeSection !== "delivery") {
      return;
    }
    let cancelled = false;
    setDeliveryLoading(true);
    loadDeliverySources()
      .catch((reason) => {
        if (!cancelled) {
          setError(reason instanceof Error ? reason.message : "Could not load Delivery sources.");
        }
      })
      .finally(() => {
        if (!cancelled) {
          setDeliveryLoading(false);
        }
      });
    return () => {
      cancelled = true;
    };
  }, [activeSection, loadDeliverySources]);

  useEffect(() => {
    if (deliveryEditorMode === "create") {
      deliveryDraftSourceId.current = null;
      setDeliveryLeads([]);
      setDeliveryRecipientChat(null);
      return;
    }

    const source = deliverySources.find((item) => item.id === selectedDeliverySourceId) ?? null;
    if (!source) {
      deliveryDraftSourceId.current = null;
      setDeliverySourceDraft(buildBlankClientLeadSourceDraft());
      setDeliveryLeads([]);
      setDeliveryRecipientChat(null);
      return;
    }

    if (deliveryDraftSourceId.current !== source.id) {
      deliveryDraftSourceId.current = source.id;
      setDeliverySourceDraft(clientLeadSourceToDraft(source));
      setDeliveryCopyStatus("");
    }
    if (activeSection !== "delivery") {
      return;
    }

    let cancelled = false;
    setDeliveryLeadsLoading(true);
    setDeliveryRecipientChatLoading(true);
    const sourceIds = deliveryContactSourceIdsFor(deliverySources, source.id);
    Promise.all([
      loadDeliveryLeadsForSources(sourceIds),
      loadDeliveryRecipientChat(source.id),
    ])
      .catch((reason) => {
        if (!cancelled) {
          setError(reason instanceof Error ? reason.message : "Could not load Delivery leads.");
        }
      })
      .finally(() => {
        if (!cancelled) {
          setDeliveryLeadsLoading(false);
          setDeliveryRecipientChatLoading(false);
        }
      });
    return () => {
      cancelled = true;
    };
  }, [activeSection, deliveryEditorMode, deliverySources, loadDeliveryLeadsForSources, loadDeliveryRecipientChat, selectedDeliverySourceId]);

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
    if (activeSection !== "delivery" || deliveryEditorMode !== "edit" || !selectedDeliverySourceId) {
      return;
    }

    let cancelled = false;
    let inFlight = false;

    const autoSyncDelivery = async () => {
      if (document.visibilityState !== "visible" || inFlight) {
        return;
      }

      const sourceIds = deliveryContactSourceIdsFor(deliverySourcesRef.current, selectedDeliverySourceId);
      if (!sourceIds.length) {
        return;
      }
      inFlight = true;
      try {
        const syncResults = await Promise.allSettled(
          sourceIds.map((sourceId) => apiFetch(`/api/client-lead-sources/${encodeURIComponent(sourceId)}/sync`, { method: "POST" })),
        );
        if (cancelled) {
          return;
        }
        await Promise.all([
          loadDeliverySources(),
          loadDeliveryLeadsForSources(sourceIds),
          loadDeliveryRecipientChat(selectedDeliverySourceId),
        ]);
        if (syncResults.every((result) => result.status === "rejected")) {
          const reason = syncResults[0]?.reason;
          setError(reason instanceof Error ? reason.message : "Could not auto-refresh Delivery.");
        }
      } catch (reason) {
        if (!cancelled) {
          setError(reason instanceof Error ? reason.message : "Could not auto-refresh Delivery.");
        }
      } finally {
        inFlight = false;
      }
    };

    const timer = window.setInterval(() => {
      autoSyncDelivery();
    }, DELIVERY_AUTO_SYNC_MS);

    autoSyncDelivery();

    return () => {
      cancelled = true;
      window.clearInterval(timer);
    };
  }, [activeSection, deliveryEditorMode, loadDeliveryLeadsForSources, loadDeliveryRecipientChat, loadDeliverySources, selectedDeliverySourceId]);

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
      if (selectedLeadId && isContadoresFunnel) {
        await loadDetail(selectedLeadId);
      }
      if (selectedWorkstationClientId) {
        await loadWorkstationDetail(selectedWorkstationClientId);
      }
      if (activeSection === "delivery") {
        const updatedSources = await loadDeliverySources();
        if (selectedDeliverySourceId) {
          await loadDeliveryLeadsForSources(deliveryContactSourceIdsFor(updatedSources, selectedDeliverySourceId));
          await loadDeliveryRecipientChat(selectedDeliverySourceId);
        }
      }
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Could not refresh funnels.");
    } finally {
      setLoading(false);
    }
  }

  function refreshCampaigns() {
    setCampaignRefreshSignal((current) => current + 1);
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

  function startNewDeliverySource() {
    setDeliveryEditorMode("create");
    setSelectedDeliverySourceId(null);
    deliveryDraftSourceId.current = null;
    setDeliveryLeads([]);
    setDeliveryRecipientChat(null);
    setDeliveryCopyStatus("");
    setDeliverySourceEditorError("");
    setDeliverySourceDraft(buildBlankClientLeadSourceDraft());
  }

  async function saveDeliverySource(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const validation = validateClientLeadSourceDraft(deliverySourceDraft);
    if (!validation.canSave) {
      setDeliverySourceEditorError(validation.summary);
      return;
    }

    setDeliverySourceEditorError("");
    setActionBusy("delivery-save");
    try {
      const payload = clientLeadSourcePayloadFromDraft(deliverySourceDraft);
      const existingSource = deliverySources.find((source) => source.id === payload.id);
      const method = existingSource && deliveryEditorMode === "edit" ? "PUT" : "POST";
      const path = method === "PUT"
        ? `/api/client-lead-sources/${encodeURIComponent(existingSource?.id ?? payload.id)}`
        : "/api/client-lead-sources";
      const saved = await apiFetch<ClientLeadSource>(path, {
        method,
        body: JSON.stringify(payload),
      });
      setDeliveryEditorMode("edit");
      setSelectedDeliverySourceId(saved.id || payload.id);
      deliveryDraftSourceId.current = saved.id || payload.id;
      setDeliverySourceDraft(clientLeadSourceToDraft(saved));
      const updatedSources = await loadDeliverySources();
      const sourceIds = deliveryContactSourceIdsFor(updatedSources, saved.id || payload.id);
      await loadDeliveryLeadsForSources(sourceIds);
      await loadDeliveryRecipientChat(saved.id || payload.id);
    } catch (reason) {
      setDeliverySourceEditorError(reason instanceof Error ? reason.message : "Could not save Delivery source.");
    } finally {
      setActionBusy(null);
    }
  }

  function closeConfirmDialog() {
    if (!confirmDialog || actionBusy === confirmDialog.busyKey) {
      return;
    }
    setConfirmDialog(null);
  }

  async function submitConfirmDialog(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const currentDialog = confirmDialog;
    if (!currentDialog || actionBusy === currentDialog.busyKey) {
      return;
    }
    await currentDialog.onConfirm();
    setConfirmDialog((activeDialog) => activeDialog?.id === currentDialog.id ? null : activeDialog);
  }

  function deleteDeliverySource() {
    const sourceId = selectedDeliverySource?.id;
    const label = selectedDeliverySource?.label || sourceId;
    if (!sourceId) {
      return;
    }
    setConfirmDialog({
      id: `delivery-source:${sourceId}`,
      tone: "danger",
      title: "Delete Delivery source",
      message: `${label} will stop polling and remove this source from the delivery contact. Existing sent chat history stays in the audit trail.`,
      confirmLabel: "Delete source",
      busyLabel: "Deleting...",
      busyKey: "delivery-delete",
      onConfirm: async () => {
        setActionBusy("delivery-delete");
        try {
          await apiFetch(`/api/client-lead-sources/${encodeURIComponent(sourceId)}`, { method: "DELETE" });
          setSelectedDeliverySourceId(null);
          deliveryDraftSourceId.current = null;
          setDeliveryLeads([]);
          setDeliveryRecipientChat(null);
          setDeliveryCopyStatus("");
          await loadDeliverySources();
        } catch (reason) {
          setError(reason instanceof Error ? reason.message : "Could not delete Delivery source.");
        } finally {
          setActionBusy(null);
        }
      },
    });
  }

  async function copyClientLeadInfo(lead: ClientLead) {
    try {
      await copyTextToClipboard(buildClientLeadText(lead));
      setDeliveryCopyStatus(`Copied ${lead.full_name || lead.phone_number || `row ${lead.row_number}`}.`);
    } catch {
      setDeliveryCopyStatus("");
      setError("Could not copy lead info.");
    }
  }

  async function copyClientLeadAll(lead: ClientLead) {
    setActionBusy(`delivery-copy-${lead.id}`);
    try {
      const payload = await apiFetch<ClientLeadCopyAllResponse | string>(
        `/api/client-leads/${encodeURIComponent(lead.id)}/copy-all`,
      );
      const text = typeof payload === "string" ? payload : payload.text;
      await copyTextToClipboard(text || buildClientLeadText(lead));
      setDeliveryCopyStatus(`Copied all for ${lead.full_name || lead.phone_number || `row ${lead.row_number}`}.`);
    } catch (reason) {
      setDeliveryCopyStatus("");
      setError(reason instanceof Error ? reason.message : "Could not copy all lead info.");
    } finally {
      setActionBusy(null);
    }
  }

  async function retryClientLeadNotification(lead: ClientLead) {
    if (!isRetryableClientLead(lead)) {
      return;
    }
    setActionBusy(`delivery-retry-${lead.id}`);
    try {
      await apiFetch(`/api/client-leads/${encodeURIComponent(lead.id)}/retry`, { method: "POST" });
      const sourceId = lead.source_id || selectedDeliverySourceId || deliverySourceDraft.id;
      const updatedSources = await loadDeliverySources();
      await loadDeliveryLeadsForSources(deliveryContactSourceIdsFor(updatedSources, sourceId));
      await loadDeliveryRecipientChat(sourceId);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Could not retry this notification.");
    } finally {
      setActionBusy(null);
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
    setWorkstationDetail((current) => current?.client.id === clientId ? current : null);
    setWorkstationNotesDraft("");
    setActiveSection("workstation");
    setProfessionalPhotoMediaIds([]);
    setProfessionalPhotoContext("");
    setProfessionalPhotoEditPrompts({});
    try {
      const payload = await loadWorkstationDetail(clientId);
      if (!payload) {
        return;
      }
      setSelectedFunnelId(payload.client.funnel_id || "contadores");
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

  function openCrmLeadFromDelivery(lead: ClientLeadRecipientCrmLead | null | undefined) {
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

  function deleteWorkstationMedia(asset: WorkstationMediaAsset) {
    const clientId = workstationDetail?.client.id ?? selectedWorkstationClientId;
    if (!clientId) {
      return;
    }
    const assetTitle = asset.title || asset.original_filename || "this media file";
    const busyKey = `delete-media-${asset.id}`;
    setConfirmDialog({
      id: `workstation-media:${asset.id}`,
      tone: "danger",
      title: "Delete media",
      message: `${assetTitle} will be removed from this Workstation client. Generated artifacts that already reference it are not rewritten.`,
      confirmLabel: "Delete media",
      busyLabel: "Deleting...",
      busyKey,
      onConfirm: async () => {
        setActionBusy(busyKey);
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
      },
    });
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

  function closeWorkstationClient() {
    const clientId = workstationDetail?.client.id ?? selectedWorkstationClientId;
    const clientName = workstationDetail?.client.display_name || "this lead";
    if (!clientId) {
      return;
    }
    setConfirmDialog({
      id: `workstation-client:${clientId}`,
      tone: "warn",
      title: "Close Workstation client",
      message: `${clientName} will leave the active Build queue. This also stops Workstation and CRM automation for the lead.`,
      confirmLabel: "Close client",
      busyLabel: "Closing...",
      busyKey: "workstation-close",
      onConfirm: async () => {
        setActionBusy("workstation-close");
        try {
          const payload = await apiFetch<WorkstationClientDetailResponse>(
            `/api/workstation/clients/${clientId}/close`,
            { method: "POST" },
          );
          setWorkstationDetail(payload);
          setWorkstationNotesDraft(payload.notes ?? "");
          await Promise.all([loadWorkstation(), loadDashboard()]);
        } catch (reason) {
          setError(reason instanceof Error ? reason.message : "Could not close Workstation lead.");
        } finally {
          setActionBusy(null);
        }
      },
    });
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
      setError("Select a chat before sending a message.");
      return;
    }

    setActionBusy("send-modal");
    try {
      if (isLeadClosed(selectedLead)) {
        setError("This lead is closed. Reopen it before sending WhatsApp messages.");
        return;
      }
      if (sendKind === "custom") {
        const text = manualText.trim();
        if (!text) {
          setError("Write a message before sending.");
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
    const leadIds = selectedVisibleLeadIds;
    if (!leadIds.length) {
      setError("Select chats in the current list before applying a bulk action.");
      return;
    }

    setActionBusy("bulk-send-modal");
    try {
      if (bulkSendKind !== "set-tags" && bulkOutboundBlockedCount > 0) {
        const reasons: string[] = [];
        if (bulkClosedCount > 0) {
          reasons.push(`${bulkClosedCount} selected lead${bulkClosedCount === 1 ? " is" : "s are"} closed. Reopen before sending WhatsApp messages.`);
        }
        if (bulkConvertedCount > 0) {
          reasons.push(
            `${bulkConvertedCount} selected lead${bulkConvertedCount === 1 ? " is" : "s are"} converted. Use Workstation delivery instead of CRM follow-up messages.`,
          );
        }
        if (bulkArchivedCount > 0) {
          reasons.push(
            `${bulkArchivedCount} selected lead${bulkArchivedCount === 1 ? " is" : "s are"} archived. Unarchive before sending WhatsApp messages.`,
          );
        }
        setError(reasons.join(" "));
        return;
      }
      if (bulkSendKind === "custom" && bulkCustomBlockedCount > 0) {
          setError(`Custom WhatsApp is blocked for ${bulkCustomBlockedCount} selected chat${bulkCustomBlockedCount === 1 ? "" : "s"} because the 24-hour window is closed. Use the follow-up ping template instead.`);
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

  async function routeLeadToCampaign(targetCampaignId: string, handoffPoint: LeadStage) {
    const leadId = selectedLead?.id ?? selectedLeadId;
    if (!leadId) {
      return;
    }
    setActionBusy("route-lead");
    try {
      const moved = await apiFetch<LeadSummary>(`/api/contadores/leads/${leadId}/move`, {
        method: "POST",
        body: JSON.stringify({ funnel_id: targetCampaignId, stage: handoffPoint }),
      });
      setSelectedFunnelId(moved.funnel_id);
      setSelectedLeadId(moved.id);
      await loadDashboard();
      await loadDetail(moved.id);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Could not route this chat.");
    } finally {
      setActionBusy(null);
    }
  }

  function deleteLead() {
    const leadId = selectedLead?.id ?? selectedLeadId;
    const leadName = selectedLead?.full_name || selectedLead?.phone || "this chat";
    if (!leadId) {
      return;
    }
    setConfirmDialog({
      id: `lead:${leadId}`,
      tone: "danger",
      title: "Delete chat",
      message: `${leadName} and its local conversation history will be removed from this CRM. Use this only for duplicates or bad imports.`,
      confirmLabel: "Delete chat",
      busyLabel: "Deleting...",
      busyKey: "delete",
      onConfirm: async () => {
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
      },
    });
  }

  const startCrmLeadsResize = useCallback((event: ReactPointerEvent<HTMLButtonElement>) => {
    const workspace = crmWorkspaceRef.current;

    if (!workspace || window.innerWidth <= CRM_STACKED_LAYOUT_WIDTH) {
      return;
    }

    event.preventDefault();

    const startX = event.clientX;
    const startWidth = crmLeadsWidth;
    const workspaceWidth = workspace.getBoundingClientRect().width;
    const maxWidth = Math.max(
      CRM_LEADS_MIN_WIDTH,
      Math.min(CRM_LEADS_MAX_WIDTH, workspaceWidth - CRM_DETAIL_MIN_WIDTH),
    );

    document.body.classList.add("ct-resizing");

    const handlePointerMove = (moveEvent: PointerEvent) => {
      const nextWidth = clampNumber(startWidth + moveEvent.clientX - startX, CRM_LEADS_MIN_WIDTH, maxWidth);
      setCrmLeadsWidth(nextWidth);
    };

    const stopResize = () => {
      document.removeEventListener("pointermove", handlePointerMove);
      document.removeEventListener("pointerup", stopResize);
      document.removeEventListener("pointercancel", stopResize);
      document.body.classList.remove("ct-resizing");
    };

    document.addEventListener("pointermove", handlePointerMove);
    document.addEventListener("pointerup", stopResize);
    document.addEventListener("pointercancel", stopResize);
  }, [crmLeadsWidth]);

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

  function selectOperation(section: ActiveSection) {
    setActiveSection(section);
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
  const activeLeadView = leadViewFilters.find((filter) => filter.value === leadViewFilter) ?? leadViewFilters[0];
  const activeCrmFilterCount = [
    leadViewFilter !== "all",
    Boolean(strategyFilter.step || strategyFilter.strategyId),
    Boolean(tagFilter),
    Boolean(query.trim()),
  ].filter(Boolean).length;
  const crmHeroMetrics = [
    { label: "Needs answer", value: metrics?.attention_needs_reply ?? 0 },
    { label: "Manual", value: metrics?.needs_human ?? 0 },
    { label: "Opener", value: metrics?.awaiting_initial_reply ?? 0 },
  ];
  const crmHeroTitle = "Clear the queue";
  const crmHeroDetail = totalCount
    ? `${compactNumber(visibleCount)}/${compactNumber(totalCount)} visible · ${activeLeadView.label}`
    : "No leads in this view";
  const clearCrmFilters = useCallback(() => {
    setLeadViewFilter("all");
    setStrategyFilter({ step: "", strategyId: "" });
    setTagFilter("");
    setQuery("");
  }, []);
  const selectedFunnelNeedsSetup = Boolean(
    isCrmWorkspace
      && selectedFunnel
      && selectedFunnel.kind === "campaign"
      && selectedFunnelSetupIssues.length
      && totalCount === 0,
  );
  const totalManualAttentionCount = Object.values(manualAttentionCounts).reduce((total, count) => total + count, 0);
  const showGlobalCrmAttentionBadge = !isCrmWorkspace && totalManualAttentionCount > 0;
  const workstationTitle = selectedFunnel
    ? `Build · ${selectedFunnel.label}`
    : "Build";
  const activeTitle = activeSection === "workstation"
      ? workstationTitle
      : activeSection === "delivery"
        ? "Deliver"
        : activeSection === "campaigns"
          ? "Ads"
        : "CRM";
  const syncStatus = activeSection === "workstation"
    ? `${workstationClients.length} converted ${workstationClients.length === 1 ? "client" : "clients"}`
    : activeSection === "campaigns"
    ? "Owned forms"
    : activeSection === "delivery"
    ? `${deliveryContactGroups.length} ${deliveryContactGroups.length === 1 ? "contact" : "contacts"} · ${compactNumber(deliveryLeadTotal)} leads${deliverySourceIssueCount ? ` · ${deliverySourceIssueCount} issue${deliverySourceIssueCount === 1 ? "" : "s"}` : ""}`
    : config?.last_sheet_sync_status
    ? `${config.last_sheet_sync_status} · ${config.last_sheet_sync_at ? relativeTime(config.last_sheet_sync_at) : "never"}`
    : runtime
      ? (runtime.ready ? "Ready" : "Review config")
      : "Sync idle";
  const syncBadgeIsOk = activeSection === "delivery"
    ? deliverySourceIssueCount === 0
    : activeSection === "campaigns"
        ? true
        : config?.last_sheet_sync_status === "ok";

  return (
    <section id="contadoresView" className="contadores-view" data-app="contadores">
      <header className="ct-topbar">
        <div className="ct-topbar-brand">
          <span className="ct-brand-mark" aria-hidden="true">{monogram(activeTitle)}</span>
          <div className="ct-brand-copy">
            <p className="ct-brand-word">
              {activeTitle}
            </p>
            <span className={`ct-sync-badge ${syncBadgeIsOk ? "has-unread" : ""}`}>{syncStatus}</span>
          </div>
        </div>

        <nav className="ct-section-switch" aria-label="Primary operation">
          {operations.map((operation) => {
            const isActive = activeSection === operation.section;
            const badge = operation.section === "crm" && showGlobalCrmAttentionBadge
              ? totalManualAttentionCount
              : 0;

            return (
              <button
                type="button"
                className={isActive ? "active" : ""}
                aria-current={isActive ? "page" : undefined}
                aria-label={badge ? `${operation.label}, ${badge} needs attention` : operation.label}
                key={operation.section}
                onClick={() => selectOperation(operation.section)}
              >
                <span className="ct-operation-icon" aria-hidden="true">{operation.icon}</span>
                <span className="ct-operation-copy">
                  <strong>{operation.label}</strong>
                </span>
                {badge ? (
                  <span className="ct-section-badge">{compactNumber(badge)}</span>
                ) : null}
              </button>
            );
          })}
        </nav>

        {isCrmWorkspace || activeSection === "workstation" ? (
          <nav className="ct-topbar-nav" aria-label={activeSection === "workstation" ? "Build funnels" : "Funnel views"}>
            {funnels.map((funnel) => {
              const attentionCount = manualAttentionCounts[funnel.id] ?? 0;
              const isActiveFunnel = selectedFunnelId === funnel.id;

              return (
                <button
                  key={funnel.id}
                  type="button"
                  className={`ct-nav-btn ${isActiveFunnel ? "active" : ""}`}
                  aria-current={isActiveFunnel ? "page" : undefined}
                  onClick={() => setSelectedFunnelId(funnel.id)}
                >
                  <span>{funnel.label}</span>
                  {isCrmWorkspace && attentionCount > 0 ? (
                    <span className="ct-nav-badge" aria-label={`${attentionCount} needs answer`}>
                      {compactNumber(attentionCount)}
                    </span>
                  ) : null}
                </button>
              );
            })}
            {isCrmWorkspace ? (
              <button type="button" className="ct-nav-btn ct-nav-add" onClick={openCreateFunnel}>
                <Plus size={14} weight="bold" />
                <span>Funnel</span>
              </button>
            ) : null}
          </nav>
        ) : null}

        <div className="ct-topbar-tools">
          {isCrmWorkspace ? (
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
            {isCrmWorkspace || activeSection === "workstation" ? (
              <button type="button" className="ct-icon-btn" onClick={openEditFunnel} disabled={!selectedFunnel} title="Edit funnel" aria-label="Edit funnel">
                <NotePencil size={15} weight="bold" />
                <span className="ct-toolbar-label">Funnel</span>
              </button>
            ) : null}
            {isCrmWorkspace && canEditLegacyRuntimeConfig ? (
              <button type="button" className="ct-icon-btn" onClick={() => setShowConfig(true)} title="Runtime config" aria-label="Runtime config">
                <GearSix size={15} weight="bold" />
                <span className="ct-toolbar-label">Runtime</span>
              </button>
            ) : null}
          <button
            type="button"
            className="ct-icon-btn"
            title={activeSection === "campaigns" ? "Refresh Ads" : "Refresh"}
            aria-label={activeSection === "campaigns" ? "Refresh Ads" : "Refresh"}
            onClick={activeSection === "campaigns" ? refreshCampaigns : refreshAll}
            disabled={loading || deliveryLoading}
          >
            <ArrowsClockwise size={15} weight="bold" />
            <span className="ct-toolbar-label">Refresh</span>
          </button>
        </div>
      </header>

      <main className="ct-main-slot">
        {error ? (
          <div className="ct-error" role="alert">
            <span>{error}</span>
            <button type="button" className="ct-icon-btn" onClick={() => setError(null)}>Dismiss</button>
          </div>
        ) : null}
        {funnelConfigErrors.length ? (
          <div className="ct-error" role="alert">
            <span>{funnelConfigErrors.join(" ")}</span>
            <button type="button" className="ct-icon-btn" onClick={() => setFunnelConfigErrors([])}>Dismiss</button>
          </div>
        ) : null}

        {activeSection === "campaigns" ? (
        <CampaignsPanel refreshSignal={campaignRefreshSignal} onError={(message) => setError(message)} />
        ) : activeSection === "workstation" ? (
        <WorkstationView
          clients={workstationClients}
          detail={workstationDetail}
          funnel={selectedFunnel}
          selectedClientId={selectedWorkstationClientId}
          listLoading={workstationListLoading}
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
            const switchingClient = selectedWorkstationClientId !== clientId;
            setSelectedWorkstationClientId(clientId);
            if (switchingClient) {
              setWorkstationDetail(null);
              setWorkstationNotesDraft("");
            }
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
          onCloseWorkstationClient={closeWorkstationClient}
          onProfessionalPhotoEditPromptChange={updateProfessionalPhotoEditPrompt}
          onEditProfessionalPhoto={(version) => editProfessionalPhoto(version)}
        />
        ) : activeSection === "delivery" ? (
          <ClientLeadDeliveryView
            sources={deliverySources}
            contactGroups={deliveryContactGroups}
            leads={deliveryLeads}
            selectedSource={selectedDeliverySource}
            selectedSourceId={selectedDeliverySourceId}
            editorMode={deliveryEditorMode}
            draft={deliverySourceDraft}
            loading={deliveryLoading}
            leadsLoading={deliveryLeadsLoading}
            recipientChat={deliveryRecipientChat}
            recipientChatLoading={deliveryRecipientChatLoading}
            actionBusy={actionBusy}
            copyStatus={deliveryCopyStatus}
            sourceEditorError={deliverySourceEditorError}
            onSelectSource={(sourceId) => {
              setDeliverySourceEditorError("");
              setDeliveryEditorMode("edit");
              setSelectedDeliverySourceId(sourceId);
            }}
            onNewSource={startNewDeliverySource}
            onDraftChange={(nextDraft) => {
              setDeliverySourceEditorError("");
              setDeliverySourceDraft(nextDraft);
            }}
            onSaveSource={saveDeliverySource}
            onDeleteSource={deleteDeliverySource}
            onCopyLead={copyClientLeadInfo}
            onCopyLeadAll={copyClientLeadAll}
            onRetryLead={retryClientLeadNotification}
            onOpenCrmLead={openCrmLeadFromDelivery}
          />
        ) : selectedFunnelNeedsSetup ? (
        <FunnelSetupView
          funnel={selectedFunnel}
          configPath={funnelConfigPath}
          onEdit={openEditFunnel}
        />
        ) : (
        <div className="ct-surface" data-crm-mode="crm">
        {selectedFunnel && selectedFunnel.kind === "campaign" && selectedFunnelSetupIssues.length ? (
          <FunnelSetupBanner
            setupIssues={selectedFunnelSetupIssues}
            onEdit={openEditFunnel}
          />
        ) : null}
        {!isInboxFunnel ? (
          <section className="ct-simple-head ct-crm-hero" data-mode="crm">
            <div className="ct-simple-title">
              <span>CRM</span>
              <strong>{crmHeroTitle}</strong>
              <small>{crmHeroDetail}</small>
            </div>
            <div className="ct-simple-metrics" aria-label={`${crmModeLabel} metrics`}>
              {crmHeroMetrics.map((item) => (
                <span key={item.label}>
                  <strong>{compactNumber(item.value)}</strong>
                  {item.label}
                </span>
              ))}
            </div>
          </section>
        ) : null}
        {!isInboxFunnel ? (
          <div className="ct-queue-bar">
            <section className="ct-lead-filter-bar" aria-labelledby="ctLeadStateLabel">
              <div className="ct-lead-filter-head">
                <div>
                  <span id="ctLeadStateLabel">State</span>
                  <strong>{activeLeadView.label}</strong>
                </div>
                {activeCrmFilterCount ? (
                  <button
                    type="button"
                    className="ct-filter-clear"
                    onClick={clearCrmFilters}
                  >
                    Clear filters
                  </button>
                ) : null}
              </div>
              <div className="ct-lead-state-strip" role="group" aria-label="Lead state filters">
                {leadViewFilters.map((filter) => {
                  const count = Number(metrics?.[filter.metric ?? "total"] ?? 0);
                  const isActiveFilter = leadViewFilter === filter.value;

                  return (
                    <button
                      key={filter.value}
                      type="button"
                      className={`ct-lead-view ${isActiveFilter ? "active" : ""}`}
                      data-tone={filter.tone}
                      aria-pressed={isActiveFilter}
                      onClick={() => setLeadViewFilter(filter.value)}
                    >
                      <span className="ct-lead-view-count">{compactNumber(count)}</span>
                      <span className="ct-lead-view-label">{filter.label}</span>
                    </button>
                  );
                })}
              </div>
            </section>
            {(strategyStats.length || tagOptions.length) ? (
              <section className="ct-filter-board" aria-label="Lead filters">
                {strategyStats.length ? (
                  <div className="ct-filter-row">
                    <span className="ct-filter-row-label">Strategies</span>
                    <div className="ct-filter-strip" role="group" aria-label="Strategy filters">
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
                    </div>
                  </div>
                ) : null}

                {tagOptions.length ? (
                  <div className="ct-filter-row">
                    <span className="ct-filter-row-label">Tags</span>
                    <div className="ct-filter-strip" role="group" aria-label="Tag filters">
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
                    </div>
                  </div>
                ) : null}
              </section>
            ) : null}
          </div>
        ) : null}

        <div
          className="ct-workspace ct-workspace-resizable"
          ref={crmWorkspaceRef}
          style={{ "--crm-leads-width": `${crmLeadsWidth}px` } as CSSProperties}
        >
          <aside className="ct-leads">
            <div className="ct-leads-head">
              <h3>{crmLeadListTitle}</h3>
              <p className="ct-leads-summary">{visibleCount ? `${visibleCount}` : crmLeadListSummary}</p>
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
                disabled={!selectedVisibleCount || Boolean(actionBusy)}
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
              hasActiveFilters={Boolean(activeCrmFilterCount)}
              onClearFilters={clearCrmFilters}
              onSelect={setSelectedLeadId}
              onToggleSelected={toggleLeadSelection}
            />
          </aside>

          <button
            type="button"
            className="ct-workspace-resizer"
            aria-label="Resize lead list"
            onPointerDown={startCrmLeadsResize}
          />

          <section className="ct-detail">
            <LeadDetailHeader
              lead={selectedLead}
              actionBusy={actionBusy}
              onOpenSend={() => {
                setSendKind("custom");
                setShowSendModal(true);
              }}
              onMarkConverted={() => runAction("mark-converted")}
              onPauseAutomation={() => runAction("pause-automation")}
              onManualHandoff={() => runAction("manual-handoff")}
              onMarkAnswered={() => runAction("mark-answered")}
              onToggleClosed={() => runAction(isLeadClosed(selectedLead) ? "reopen" : "close")}
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
              <CampaignRoutingPanel
                lead={selectedLead}
                funnels={funnels}
                busy={actionBusy === "route-lead"}
                onRoute={routeLeadToCampaign}
              />
            ) : null}

            <section className="ct-message-pane">
              <MessageTimeline
                messages={selectedLeadDetail?.messages ?? []}
                loading={detailLoading}
                hasLead={Boolean(selectedLead)}
                acknowledgingIds={acknowledgingDeliveryErrorIds}
                onAcknowledgeDeliveryError={acknowledgeDeliveryError}
              />
            </section>

            <details className="ct-manual-disclosure" open={Boolean(manualText.trim() || manualFiles.length)}>
              <summary>Operator message</summary>
              <ManualDock
                disabled={!selectedLead || Boolean(actionBusy)}
                blockReason={selectedLeadCustomBlockReason}
                value={manualText}
                files={manualFiles}
                onChange={setManualText}
                onFilesChange={setManualFiles}
                onSubmit={submitManualDock}
              />
            </details>
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
          selectedCount={selectedVisibleCount}
          hiddenSelectedCount={selectedHiddenCount}
          customBlockedCount={bulkCustomBlockedCount}
          closedCount={bulkClosedCount}
          convertedCount={bulkConvertedCount}
          archivedCount={bulkArchivedCount}
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

      {confirmDialog ? (
        <ConfirmDialog
          dialog={confirmDialog}
          busy={actionBusy === confirmDialog.busyKey}
          onClose={closeConfirmDialog}
          onSubmit={submitConfirmDialog}
        />
      ) : null}
    </section>
  );
}

type CampaignClientItem = {
  id: string;
  display_name: string;
  lead?: {
    full_name?: string | null;
    phone?: string | null;
    email?: string | null;
  } | null;
};

type LeadCaptureCampaignItem = {
  id: string;
  name: string;
  status: string;
  public_url: string;
  public_slug: string;
  client_id: string;
  client?: CampaignClientItem | null;
  submission_count: number;
  daily_budget_usd: number | null;
  location: string;
  campaign_info: Record<string, unknown>;
  creative_brief: string;
  form_schema: { fields?: CampaignFormField[] };
  delivery_source?: ClientLeadSource | null;
  meta_pixel_id: string;
  meta_events_enabled: boolean;
  created_at: string | null;
  updated_at: string | null;
};

type LeadCaptureSubmissionItem = {
  id: string;
  full_name: string | null;
  phone: string;
  email: string | null;
  answers: Record<string, unknown>;
  delivery_status: string;
  meta_event_status: string;
  created_at: string | null;
};

type CampaignFormField = {
  id: string;
  label: string;
  type: string;
  required?: boolean;
  placeholder?: string;
  options?: string[];
};

type CampaignFieldDraft = CampaignFormField & {
  optionsText: string;
};

type CampaignClientMode = "existing" | "new";

type CampaignCreativeDraft = {
  primaryText: string;
  headline: string;
  description: string;
  assetBrief: string;
  destinationUrl: string;
  callToAction: string;
};

type CampaignGeoTargetingDraft = {
  locations: CampaignGeoLocation[];
};

type CampaignGeoArea = {
  name: string;
  key?: string;
  country_code?: string;
  type?: "region" | "city";
  source?: "meta" | "local";
};

type CampaignGeoLocation = {
  country_code: string;
  regions: CampaignGeoArea[];
  cities: CampaignGeoArea[];
};

type CampaignGeoSearchResponse = {
  country_code: string;
  kind: "region" | "city";
  query: string;
  source: "meta" | "local";
  meta_error?: string | null;
  suggestions: CampaignGeoArea[];
};

const campaignFieldTypes = [
  { value: "text", label: "Text" },
  { value: "textarea", label: "Long text" },
  { value: "email", label: "Email" },
  { value: "phone", label: "Phone" },
  { value: "yes_no", label: "Yes / No" },
  { value: "select", label: "Choice" },
  { value: "multi_select", label: "Multiple" },
];

const campaignCountryOptions = [
  { value: "AR", label: "Argentina" },
  { value: "UY", label: "Uruguay" },
  { value: "CL", label: "Chile" },
  { value: "PY", label: "Paraguay" },
  { value: "BO", label: "Bolivia" },
  { value: "PE", label: "Peru" },
  { value: "CO", label: "Colombia" },
  { value: "EC", label: "Ecuador" },
  { value: "MX", label: "Mexico" },
  { value: "US", label: "United States" },
  { value: "ES", label: "Spain" },
];
const campaignCountryLabels = Object.fromEntries(campaignCountryOptions.map((country) => [country.value, country.label]));
const campaignGeoNamePattern = /^[A-Za-zÀ-ÖØ-öø-ÿ0-9][A-Za-zÀ-ÖØ-öø-ÿ0-9 .,'()/-]{0,95}$/;

function defaultCampaignFields(): CampaignFieldDraft[] {
  return [
    { id: "full_name", label: "Cual es tu nombre?", type: "text", required: true, placeholder: "Nombre completo", optionsText: "" },
    { id: "phone", label: "Cual es tu numero de WhatsApp?", type: "phone", required: true, placeholder: "+54 9 ...", optionsText: "" },
    { id: "email", label: "Cual es tu email?", type: "email", required: false, placeholder: "nombre@email.com", optionsText: "" },
    { id: "necesidad", label: "Que servicio necesitas?", type: "textarea", required: true, placeholder: "Contanos brevemente", optionsText: "" },
  ];
}

function campaignFieldId(value: string, index: number): string {
  const normalized = value
    .normalize("NFD")
    .replace(/[\u0300-\u036f]/g, "")
    .replace(/[^a-zA-Z0-9]+/g, "_")
    .replace(/^_+|_+$/g, "")
    .toLowerCase();
  return normalized || `field_${index + 1}`;
}

function campaignFormSchema(fields: CampaignFieldDraft[]): { fields: CampaignFormField[]; layout: string } {
  return {
    layout: "multi_step",
    fields: fields.map((field, index) => {
      const options = field.optionsText
        .split(/[\n,]/)
        .map((option) => option.trim())
        .filter(Boolean);
      return {
        id: campaignFieldId(field.id || field.label, index),
        label: field.label.trim() || `Field ${index + 1}`,
        type: field.type,
        required: Boolean(field.required),
        placeholder: field.placeholder?.trim() || "",
        options,
      };
    }),
  };
}

function validateCampaignGeoAreas(areas: CampaignGeoArea[], label: string): string | null {
  if (areas.length > 20) {
    return `${label} supports up to 20 values.`;
  }
  const seen = new Set<string>();
  for (const area of areas) {
    const name = area.name.trim();
    if (!campaignGeoNamePattern.test(name)) {
      return `${label} has invalid characters: ${name}`;
    }
    const key = name.toLowerCase();
    if (seen.has(key)) {
      return `${label} has a duplicate value: ${name}`;
    }
    seen.add(key);
  }
  return null;
}

function campaignGeoLocationLabel(location: CampaignGeoLocation): string {
  const parts = [campaignCountryLabels[location.country_code] || location.country_code];
  if (location.regions.length) {
    parts.push(location.regions.map((area) => area.name).join(", "));
  }
  if (location.cities.length) {
    parts.push(location.cities.map((area) => area.name).join(", "));
  }
  return parts.join(" · ");
}

function validateCampaignGeoLocations(locations: CampaignGeoLocation[]): string | null {
  if (locations.length > 20) {
    return "Locations supports up to 20 values.";
  }
  const seen = new Set<string>();
  for (const location of locations) {
    const regionError = validateCampaignGeoAreas(location.regions, "Regions / provinces");
    const cityError = validateCampaignGeoAreas(location.cities, "Cities");
    if (regionError || cityError) {
      return regionError || cityError;
    }
    const duplicateKey = JSON.stringify({
      country_code: location.country_code,
      regions: location.regions.map((area) => area.key || area.name.toLowerCase()).sort(),
      cities: location.cities.map((area) => area.key || area.name.toLowerCase()).sort(),
    });
    if (seen.has(duplicateKey)) {
      return `Duplicate location: ${campaignGeoLocationLabel(location)}`;
    }
    seen.add(duplicateKey);
  }
  return null;
}

function campaignGeoTargeting(locations: CampaignGeoLocation[]): CampaignGeoTargetingDraft {
  const cleanAreas = (areas: CampaignGeoArea[], country: string) => areas.map((area) => ({
    name: area.name.trim(),
    ...(area.key ? { key: area.key } : {}),
    country_code: area.country_code || country,
  }));
  return {
    locations: locations.map((location) => {
      const country = location.country_code.trim().toUpperCase() || "AR";
      return {
        country_code: country,
        regions: cleanAreas(location.regions, country),
        cities: cleanAreas(location.cities, country),
      };
    }),
  };
}

function campaignClientLabel(client: CampaignClientItem): string {
  const lead = client.lead;
  return [
    client.display_name || lead?.full_name || client.id,
    lead?.phone,
    lead?.email,
  ].filter(Boolean).join(" · ");
}

function campaignLocationKindLabel(location: CampaignGeoLocation): string {
  if (location.regions.length || location.cities.length) {
    return "Specific";
  }
  return "Country";
}

function campaignLocationDetailLabel(location: CampaignGeoLocation): string {
  const details = [
    location.regions.length ? `${location.regions.length} regions` : "",
    location.cities.length ? `${location.cities.length} cities` : "",
  ].filter(Boolean);
  return details.length ? details.join(" · ") : "Whole country";
}

function campaignCreativeBriefSummary(creative: CampaignCreativeDraft): string {
  const creativeLines = [
    creative.primaryText.trim() ? `Primary text: ${creative.primaryText.trim()}` : "",
    creative.headline.trim() ? `Headline: ${creative.headline.trim()}` : "",
    creative.description.trim() ? `Description: ${creative.description.trim()}` : "",
    creative.assetBrief.trim() ? `Creative asset: ${creative.assetBrief.trim()}` : "",
    creative.destinationUrl.trim() ? `Destination URL: ${creative.destinationUrl.trim()}` : "",
  ].filter(Boolean);
  if (!creativeLines.length) {
    return "";
  }
  if (creative.callToAction.trim()) {
    creativeLines.push(`Call to action: ${creative.callToAction.trim()}`);
  }
  return creativeLines.join("\n");
}

function CampaignGeoSelector({
  countryCode,
  kind,
  label,
  value,
  onChange,
  onError,
}: {
  countryCode: string;
  kind: "region" | "city";
  label: string;
  value: CampaignGeoArea[];
  onChange: (next: CampaignGeoArea[]) => void;
  onError: (message: string) => void;
}) {
  const [query, setQuery] = useState("");
  const [suggestions, setSuggestions] = useState<CampaignGeoArea[]>([]);
  const [loading, setLoading] = useState(false);
  const selectedKeys = useMemo(() => new Set(value.map((item) => `${item.key || ""}:${item.name.toLowerCase()}`)), [value]);

  useEffect(() => {
    const cleanQuery = query.trim();
    if (!cleanQuery) {
      setSuggestions([]);
      setLoading(false);
      return;
    }
    setLoading(true);
    const timeout = window.setTimeout(async () => {
      try {
        const payload = await apiFetch<CampaignGeoSearchResponse>(
          `/api/campaigns/geo/search?country_code=${encodeURIComponent(countryCode)}&kind=${kind}&q=${encodeURIComponent(cleanQuery)}&limit=12`,
        );
        setSuggestions(payload.suggestions ?? []);
      } catch (reason) {
        setSuggestions([]);
        onError(reason instanceof Error ? reason.message : `Could not search ${label.toLowerCase()}.`);
      } finally {
        setLoading(false);
      }
    }, 220);
    return () => window.clearTimeout(timeout);
  }, [countryCode, kind, label, onError, query]);

  function addArea(area: CampaignGeoArea) {
    const cleanName = area.name.trim();
    if (!cleanName || value.length >= 20) {
      return;
    }
    const duplicate = value.some((item) => item.name.toLowerCase() === cleanName.toLowerCase() || (area.key && item.key === area.key));
    if (duplicate) {
      return;
    }
    onChange([...value, { ...area, name: cleanName, country_code: area.country_code || countryCode }]);
    setQuery("");
  }

  function removeArea(index: number) {
    onChange(value.filter((_, itemIndex) => itemIndex !== index));
  }

  function addFirstSuggestion(event: KeyboardEvent<HTMLInputElement>) {
    if (event.key !== "Enter") {
      return;
    }
    event.preventDefault();
    const first = suggestions.find((item) => !selectedKeys.has(`${item.key || ""}:${item.name.toLowerCase()}`));
    if (first) {
      addArea(first);
    }
  }

  return (
    <div className="campaign-geo-picker" data-kind={kind}>
      <label className="ct-field">
        <span>{label}</span>
        <div className="campaign-command-input">
          <input
            value={query}
            onChange={(event) => setQuery(event.target.value)}
            onKeyDown={addFirstSuggestion}
            placeholder={kind === "region" ? "Type to search provinces..." : "Type to search cities..."}
          />
          {loading ? <SpinnerGap size={14} weight="bold" className="workstation-spinner" /> : null}
        </div>
      </label>
      {value.length ? (
        <div className="campaign-geo-chips">
          {value.map((area, index) => (
            <button type="button" className="campaign-geo-chip" key={`${area.key || area.name}-${index}`} onClick={() => removeArea(index)}>
              <span>{area.name}</span>
              <small>{area.key ? "Meta" : "Local"}</small>
              <X size={12} weight="bold" />
            </button>
          ))}
        </div>
      ) : null}
      <div className="campaign-geo-results">
        {!loading && !query.trim() ? <span className="campaign-geo-empty">Start typing to search</span> : null}
        {!loading && query.trim() && suggestions.length === 0 ? <span className="campaign-geo-empty">No matches</span> : null}
        {!loading ? suggestions.map((area) => {
          const disabled = selectedKeys.has(`${area.key || ""}:${area.name.toLowerCase()}`);
          return (
            <button type="button" key={`${area.source || "local"}-${area.key || area.name}`} onClick={() => addArea(area)} disabled={disabled}>
              <span>
                <strong>{area.name}</strong>
                <em>{campaignCountryLabels[area.country_code || countryCode] || area.country_code || countryCode}</em>
              </span>
              <small>{area.key ? "Meta" : "Local"}</small>
            </button>
          );
        }) : null}
      </div>
    </div>
  );
}

function CampaignsPanel({ refreshSignal, onError }: { refreshSignal: number; onError: (message: string) => void }) {
  const [campaigns, setCampaigns] = useState<LeadCaptureCampaignItem[]>([]);
  const [clients, setClients] = useState<CampaignClientItem[]>([]);
  const [selectedCampaignId, setSelectedCampaignId] = useState<string | null>(null);
  const [submissions, setSubmissions] = useState<LeadCaptureSubmissionItem[]>([]);
  const [loading, setLoading] = useState(false);
  const [submissionsLoading, setSubmissionsLoading] = useState(false);
  const [saving, setSaving] = useState(false);
  const [createOpen, setCreateOpen] = useState(false);
  const [campaignName, setCampaignName] = useState("");
  const [campaignStatus, setCampaignStatus] = useState("draft");
  const [clientMode, setClientMode] = useState<CampaignClientMode>("new");
  const [existingClientId, setExistingClientId] = useState("");
  const [newClientName, setNewClientName] = useState("");
  const [newClientWhatsapp, setNewClientWhatsapp] = useState("");
  const [newClientEmail, setNewClientEmail] = useState("");
  const [newClientExtraInfo, setNewClientExtraInfo] = useState("");
  const [dailyBudget, setDailyBudget] = useState("");
  const [locationCountryCode, setLocationCountryCode] = useState("AR");
  const [selectedRegions, setSelectedRegions] = useState<CampaignGeoArea[]>([]);
  const [selectedCities, setSelectedCities] = useState<CampaignGeoArea[]>([]);
  const [campaignLocations, setCampaignLocations] = useState<CampaignGeoLocation[]>([]);
  const [creativeBrief, setCreativeBrief] = useState("");
  const [creativeHeadline, setCreativeHeadline] = useState("");
  const [creativeDescription, setCreativeDescription] = useState("");
  const [creativeAssetBrief, setCreativeAssetBrief] = useState("");
  const [destinationUrl, setDestinationUrl] = useState("");
  const [metaPixelId, setMetaPixelId] = useState("");
  const [metaEventName, setMetaEventName] = useState("Lead");
  const [metaEventsEnabled, setMetaEventsEnabled] = useState(false);
  const [fields, setFields] = useState<CampaignFieldDraft[]>(defaultCampaignFields);

  const selectedCampaign = campaigns.find((campaign) => campaign.id === selectedCampaignId) ?? campaigns[0] ?? null;
  const selectedClient = clients.find((client) => client.id === existingClientId) ?? null;
  const currentLocation = currentGeoLocation();
  const currentLocationLabel = campaignGeoLocationLabel(currentLocation);
  const creativeDraft: CampaignCreativeDraft = {
    primaryText: creativeBrief,
    headline: creativeHeadline,
    description: creativeDescription,
    assetBrief: creativeAssetBrief,
    destinationUrl,
    callToAction: "LEARN_MORE",
  };
  const creativeSummary = campaignCreativeBriefSummary(creativeDraft);

  async function loadCampaignSubmissions(campaignId: string) {
    setSubmissionsLoading(true);
    try {
      const payload = await apiFetch<{ submissions: LeadCaptureSubmissionItem[] }>(
        `/api/campaigns/${encodeURIComponent(campaignId)}/submissions?limit=20`,
      );
      setSubmissions(payload.submissions ?? []);
    } finally {
      setSubmissionsLoading(false);
    }
  }

  async function loadCampaigns() {
    setLoading(true);
    try {
      const [campaignPayload, clientPayload] = await Promise.all([
        apiFetch<{ campaigns: LeadCaptureCampaignItem[] }>("/api/campaigns?limit=120"),
        apiFetch<{ clients: CampaignClientItem[] }>("/api/campaigns/clients?limit=300"),
      ]);
      const nextCampaigns = campaignPayload.campaigns ?? [];
      setCampaigns(nextCampaigns);
      setClients(clientPayload.clients ?? []);
      const nextSelected = selectedCampaignId && nextCampaigns.some((campaign) => campaign.id === selectedCampaignId)
        ? selectedCampaignId
        : nextCampaigns[0]?.id ?? null;
      setSelectedCampaignId(nextSelected);
      if (nextSelected) {
        await loadCampaignSubmissions(nextSelected);
      } else {
        setSubmissions([]);
      }
    } catch (reason) {
      onError(reason instanceof Error ? reason.message : "Could not load campaigns.");
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    void loadCampaigns();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [refreshSignal]);

  async function selectCampaign(campaignId: string) {
    setSelectedCampaignId(campaignId);
    try {
      await loadCampaignSubmissions(campaignId);
    } catch (reason) {
      onError(reason instanceof Error ? reason.message : "Could not load campaign submissions.");
    }
  }

  function updateField(index: number, patch: Partial<CampaignFieldDraft>) {
    setFields((current) => current.map((field, fieldIndex) => fieldIndex === index ? { ...field, ...patch } : field));
  }

  function addField() {
    setFields((current) => [
      ...current,
      { id: `field_${current.length + 1}`, label: "Pregunta", type: "text", required: false, placeholder: "", optionsText: "" },
    ]);
  }

  function removeField(index: number) {
    setFields((current) => current.filter((_, fieldIndex) => fieldIndex !== index));
  }

  function currentGeoLocation(): CampaignGeoLocation {
    return {
      country_code: locationCountryCode,
      regions: selectedRegions,
      cities: selectedCities,
    };
  }

  function addCampaignLocation() {
    const location = currentGeoLocation();
    const validationError = validateCampaignGeoLocations([...campaignLocations, location]);
    if (validationError) {
      onError(validationError);
      return;
    }
    setCampaignLocations((current) => [...current, location]);
    setSelectedRegions([]);
    setSelectedCities([]);
  }

  function removeCampaignLocation(index: number) {
    setCampaignLocations((current) => current.filter((_, itemIndex) => itemIndex !== index));
  }

  async function createCampaign(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const cleanName = campaignName.trim();
    if (!cleanName) {
      onError("Campaign name is required.");
      return;
    }
    const usingExistingClient = clientMode === "existing";
    if (usingExistingClient && !existingClientId) {
      onError("Choose an existing client or switch to new client.");
      return;
    }
    const client = usingExistingClient ? null : {
      name: newClientName.trim(),
      whatsapp: newClientWhatsapp.trim(),
      email: newClientEmail.trim() || null,
      extra_info: newClientExtraInfo.trim() || null,
    };
    if (!usingExistingClient && (!client?.name || !client.whatsapp)) {
      onError("Client name and WhatsApp are required.");
      return;
    }
    const locations = campaignLocations.length ? campaignLocations : [currentGeoLocation()];
    const geoError = validateCampaignGeoLocations(locations);
    if (geoError) {
      onError(geoError);
      return;
    }
    setSaving(true);
    try {
      const body = {
        name: cleanName,
        client_id: usingExistingClient ? existingClientId : null,
        client,
        status: campaignStatus,
        daily_budget_usd: dailyBudget ? Number(dailyBudget) : null,
        geo_targeting: campaignGeoTargeting(locations),
        campaign_info: {
          creative: {
            primary_text: creativeBrief.trim(),
            headline: creativeHeadline.trim(),
            description: creativeDescription.trim(),
            asset_brief: creativeAssetBrief.trim(),
            call_to_action: creativeDraft.callToAction,
          },
        },
        creative_brief: creativeSummary || null,
        form_schema: campaignFormSchema(fields),
        destination_url: destinationUrl.trim() || null,
        meta_pixel_id: metaPixelId.trim() || null,
        meta_event_name: metaEventName.trim() || "Lead",
        meta_events_enabled: metaEventsEnabled,
      };
      const payload = await apiFetch<{ campaign: LeadCaptureCampaignItem }>("/api/campaigns", {
        method: "POST",
        body: JSON.stringify(body),
      });
      setCampaignName("");
      setDailyBudget("");
      setLocationCountryCode("AR");
      setSelectedRegions([]);
      setSelectedCities([]);
      setCampaignLocations([]);
      setCreativeBrief("");
      setCreativeHeadline("");
      setCreativeDescription("");
      setCreativeAssetBrief("");
      setDestinationUrl("");
      setMetaPixelId("");
      setMetaEventName("Lead");
      setMetaEventsEnabled(false);
      setClientMode("new");
      setExistingClientId("");
      setNewClientName("");
      setNewClientWhatsapp("");
      setNewClientEmail("");
      setNewClientExtraInfo("");
      setFields(defaultCampaignFields());
      setCreateOpen(false);
      await loadCampaigns();
      await selectCampaign(payload.campaign.id);
    } catch (reason) {
      onError(reason instanceof Error ? reason.message : "Could not create campaign.");
    } finally {
      setSaving(false);
    }
  }

  async function patchCampaignStatus(campaign: LeadCaptureCampaignItem, status: string) {
    setSaving(true);
    try {
      const payload = await apiFetch<{ campaign: LeadCaptureCampaignItem }>(
        `/api/campaigns/${encodeURIComponent(campaign.id)}`,
        { method: "PATCH", body: JSON.stringify({ status }) },
      );
      setCampaigns((current) => current.map((item) => item.id === campaign.id ? payload.campaign : item));
    } catch (reason) {
      onError(reason instanceof Error ? reason.message : "Could not update campaign.");
    } finally {
      setSaving(false);
    }
  }

  async function refreshDeliverySource(campaign: LeadCaptureCampaignItem) {
    setSaving(true);
    try {
      await apiFetch(`/api/campaigns/${encodeURIComponent(campaign.id)}/delivery-source`, { method: "POST" });
      await loadCampaigns();
    } catch (reason) {
      onError(reason instanceof Error ? reason.message : "Could not refresh campaign delivery.");
    } finally {
      setSaving(false);
    }
  }

  async function copyCampaignUrl(campaign: LeadCaptureCampaignItem) {
    await navigator.clipboard.writeText(campaign.public_url);
  }

  return (
    <section className="ct-surface campaign-manager-surface">
      <div className="ct-simple-head campaign-manager-head">
        <div className="ct-simple-title">
          <span>Campaigns</span>
          <strong>{campaigns.length ? `${compactNumber(campaigns.length)} forms` : "No forms yet"}</strong>
          <small>{selectedCampaign ? selectedCampaign.name : "Owned lead capture"}</small>
        </div>
        <div className="ct-simple-metrics campaign-manager-metrics">
          <span><strong>{compactNumber(campaigns.reduce((total, campaign) => total + (campaign.submission_count || 0), 0))}</strong>Leads</span>
          <span><strong>{compactNumber(campaigns.filter((campaign) => campaign.status === "active").length)}</strong>Active</span>
          <span><strong>{compactNumber(clients.length)}</strong>Clients</span>
        </div>
        <div className="campaign-manager-actions">
          <button type="button" className="ct-btn ct-btn-ghost" onClick={() => void loadCampaigns()} disabled={loading}>
            <ArrowsClockwise size={14} weight="bold" />
            Refresh
          </button>
          <button type="button" className="ct-btn" onClick={() => setCreateOpen((current) => !current)}>
            <Plus size={14} weight="bold" />
            Campaign
          </button>
        </div>
      </div>

      {createOpen ? (
        <form className="campaign-create-panel campaign-create-studio" onSubmit={createCampaign}>
          <div className="campaign-create-main">
            <section className="campaign-create-section campaign-section-basics">
              <div className="campaign-section-side">
                <span className="campaign-section-icon"><NotePencil size={16} weight="bold" /></span>
                <div>
                  <strong>1. Basics</strong>
                  <small>Name, status and budget</small>
                </div>
              </div>
              <div className="campaign-section-body campaign-basics-grid">
                <label className="ct-field">
                  <span>Campaign name</span>
                  <input value={campaignName} onChange={(event) => setCampaignName(event.target.value)} required placeholder="Campaña Facu Contadores" />
                </label>
                <div className="campaign-control-block">
                  <span>Status</span>
                  <div className="campaign-segmented" role="group" aria-label="Campaign status">
                    {["draft", "active", "paused"].map((status) => (
                      <button type="button" className={campaignStatus === status ? "is-active" : ""} key={status} onClick={() => setCampaignStatus(status)}>
                        {humanize(status)}
                      </button>
                    ))}
                  </div>
                </div>
                <label className="ct-field">
                  <span>Daily budget (USD)</span>
                  <input value={dailyBudget} onChange={(event) => setDailyBudget(event.target.value)} inputMode="numeric" placeholder="25" />
                </label>
              </div>
            </section>

            <section className="campaign-create-section campaign-section-targeting">
              <div className="campaign-section-side">
                <span className="campaign-section-icon"><Megaphone size={16} weight="bold" /></span>
                <div>
                  <strong>2. Targeting</strong>
                  <small>Country, regions, cities</small>
                </div>
              </div>
              <div className="campaign-section-body">
                <div className="campaign-targeting-top">
                  <label className="ct-field campaign-country-field">
                    <span>Country</span>
                    <select
                      value={locationCountryCode}
                      onChange={(event) => {
                        setLocationCountryCode(event.target.value);
                        setSelectedRegions([]);
                        setSelectedCities([]);
                      }}
                    >
                      {campaignCountryOptions.map((country) => (
                        <option key={country.value} value={country.value}>{country.label}</option>
                      ))}
                    </select>
                  </label>
                  <div className="campaign-location-current">
                    <span>Current selection</span>
                    <strong>{currentLocationLabel}</strong>
                    <small>{campaignLocationDetailLabel(currentLocation)}</small>
                  </div>
                  <button type="button" className="ct-btn campaign-add-location" onClick={addCampaignLocation}>
                    <Plus size={13} weight="bold" />
                    Add location
                  </button>
                </div>
                <div className="campaign-location-grid">
                  <CampaignGeoSelector
                    countryCode={locationCountryCode}
                    kind="region"
                    label="Regions / provinces"
                    value={selectedRegions}
                    onChange={setSelectedRegions}
                    onError={onError}
                  />
                  <CampaignGeoSelector
                    countryCode={locationCountryCode}
                    kind="city"
                    label="Cities"
                    value={selectedCities}
                    onChange={setSelectedCities}
                    onError={onError}
                  />
                </div>
                {campaignLocations.length ? (
                  <div className="campaign-location-list">
                    {campaignLocations.map((location, index) => (
                      <article className="campaign-location-item" key={`${location.country_code}-${index}`}>
                        <div>
                          <span>{campaignLocationKindLabel(location)}</span>
                          <strong>{campaignGeoLocationLabel(location)}</strong>
                          <small>{campaignLocationDetailLabel(location)}</small>
                        </div>
                        <button type="button" className="ct-icon-btn" onClick={() => removeCampaignLocation(index)} aria-label="Remove location">
                          <X size={13} weight="bold" />
                        </button>
                      </article>
                    ))}
                  </div>
                ) : (
                  <div className="campaign-location-empty">
                    <CheckCircle size={16} weight="bold" />
                    <span>No saved target yet. If you create now, {currentLocationLabel} will be used.</span>
                  </div>
                )}
              </div>
            </section>

            <section className="campaign-create-section campaign-section-client">
              <div className="campaign-section-side">
                <span className="campaign-section-icon"><ChatCircleText size={16} weight="bold" /></span>
                <div>
                  <strong>3. Client</strong>
                  <small>Existing or new</small>
                </div>
              </div>
              <div className="campaign-section-body">
                <div className="campaign-client-mode">
                  <div className="campaign-segmented" role="group" aria-label="Client source">
                    <button
                      type="button"
                      className={clientMode === "existing" ? "is-active" : ""}
                      disabled={!clients.length}
                      onClick={() => {
                        setClientMode("existing");
                        setExistingClientId((current) => current || clients[0]?.id || "");
                      }}
                    >
                      Existing client
                    </button>
                    <button
                      type="button"
                      className={clientMode === "new" ? "is-active" : ""}
                      onClick={() => {
                        setClientMode("new");
                        setExistingClientId("");
                      }}
                    >
                      New client
                    </button>
                  </div>
                  {clientMode === "existing" ? (
                    <label className="ct-field">
                      <span>Choose client</span>
                      <select value={existingClientId} onChange={(event) => setExistingClientId(event.target.value)}>
                        <option value="" disabled>Select one client</option>
                        {clients.map((client) => (
                          <option key={client.id} value={client.id}>{campaignClientLabel(client)}</option>
                        ))}
                      </select>
                    </label>
                  ) : null}
                </div>
                {clientMode === "new" ? (
                  <>
                    <div className="campaign-client-fields">
                      <label className="ct-field">
                        <span>Client name</span>
                        <input value={newClientName} onChange={(event) => setNewClientName(event.target.value)} placeholder="New converted client" />
                      </label>
                      <label className="ct-field">
                        <span>WhatsApp</span>
                        <input value={newClientWhatsapp} onChange={(event) => setNewClientWhatsapp(event.target.value)} inputMode="tel" placeholder="549..." />
                      </label>
                      <label className="ct-field">
                        <span>Email</span>
                        <input value={newClientEmail} onChange={(event) => setNewClientEmail(event.target.value)} type="email" placeholder="cliente@email.com" />
                      </label>
                    </div>
                    <label className="ct-field">
                      <span>Extra info</span>
                      <textarea value={newClientExtraInfo} onChange={(event) => setNewClientExtraInfo(event.target.value)} rows={2} placeholder="Notes for this client" />
                    </label>
                  </>
                ) : (
                  <div className="campaign-existing-client-summary">
                    <strong>{selectedClient?.display_name || "No client selected"}</strong>
                    <span>{selectedClient?.lead?.phone || "Choose a saved converted client"}{selectedClient?.lead?.email ? ` · ${selectedClient.lead.email}` : ""}</span>
                  </div>
                )}
              </div>
            </section>

            <section className="campaign-create-section campaign-section-creative">
              <div className="campaign-section-side">
                <span className="campaign-section-icon"><Camera size={16} weight="bold" /></span>
                <div>
                  <strong>4. Creative</strong>
                  <small>Copy and asset notes</small>
                </div>
              </div>
              <div className="campaign-section-body campaign-creative-grid">
                <label className="ct-field campaign-creative-primary">
                  <span>Primary text</span>
                  <textarea value={creativeBrief} onChange={(event) => setCreativeBrief(event.target.value)} rows={3} placeholder="Main ad text shown above the image/video" />
                </label>
                <label className="ct-field">
                  <span>Headline</span>
                  <input value={creativeHeadline} onChange={(event) => setCreativeHeadline(event.target.value)} placeholder="Short offer headline" />
                </label>
                <label className="ct-field">
                  <span>Description</span>
                  <input value={creativeDescription} onChange={(event) => setCreativeDescription(event.target.value)} placeholder="Optional supporting line" />
                </label>
                <label className="ct-field campaign-creative-primary">
                  <span>Image / video asset</span>
                  <textarea value={creativeAssetBrief} onChange={(event) => setCreativeAssetBrief(event.target.value)} rows={2} placeholder="Contador en oficina, testimonial corto, placa de beneficios..." />
                </label>
                <label className="ct-field campaign-creative-primary">
                  <span>Destination URL</span>
                  <input value={destinationUrl} onChange={(event) => setDestinationUrl(event.target.value)} placeholder="https://..." />
                </label>
              </div>
            </section>

            <section className="campaign-create-section campaign-section-form">
              <div className="campaign-section-side">
                <span className="campaign-section-icon"><ListChecks size={16} weight="bold" /></span>
                <div>
                  <strong>5. Form fields</strong>
                  <small>{fields.length} fields</small>
                </div>
              </div>
              <div className="campaign-section-body campaign-form-builder">
                <div className="campaign-form-builder-head">
                  <div>
                    <span>Lead form</span>
                    <strong>Questions people complete</strong>
                  </div>
                  <button type="button" className="ct-btn ct-btn-ghost" onClick={addField}>
                    <Plus size={13} weight="bold" />
                    Field
                  </button>
                </div>
                <div className="campaign-field-list">
                  {fields.map((field, index) => {
                    const locked = field.id === "full_name" || field.id === "phone";
                    const typeLabel = campaignFieldTypes.find((type) => type.value === field.type)?.label || field.type;
                    return (
                      <article className="campaign-field-card" key={`${field.id}-${index}`}>
                        <div className="campaign-field-card-head">
                          <div>
                            <span>Field {index + 1}</span>
                            <strong>{field.label.trim() || "Untitled field"}</strong>
                          </div>
                          <div className="campaign-field-badges">
                            <span>{typeLabel}</span>
                            <span className={field.required ? "is-required" : "is-optional"}>{field.required ? "Required" : "Optional"}</span>
                            {locked ? <span className="is-locked">Locked</span> : null}
                          </div>
                          <button type="button" className="ct-icon-btn" onClick={() => removeField(index)} disabled={locked || fields.length <= 2} aria-label="Remove field">
                            <Trash size={14} weight="bold" />
                          </button>
                        </div>
                        <div className="campaign-field-editor">
                          <label className="ct-field campaign-field-label">
                            <span>Label</span>
                            <input value={field.label} onChange={(event) => updateField(index, { label: event.target.value, id: locked ? field.id : campaignFieldId(event.target.value, index) })} />
                          </label>
                          <label className="ct-field">
                            <span>Type</span>
                            <select value={field.type} onChange={(event) => updateField(index, { type: event.target.value })} disabled={locked}>
                              {campaignFieldTypes.map((type) => <option key={type.value} value={type.value}>{type.label}</option>)}
                            </select>
                          </label>
                          <label className="ct-field">
                            <span>Placeholder</span>
                            <input value={field.placeholder || ""} onChange={(event) => updateField(index, { placeholder: event.target.value })} placeholder="Shown inside the form field" />
                          </label>
                          <label className="campaign-required-toggle">
                            <input type="checkbox" checked={Boolean(field.required)} onChange={(event) => updateField(index, { required: event.target.checked })} disabled={locked} />
                            <span>{field.required ? "Required" : "Optional"}</span>
                          </label>
                        </div>
                        {(field.type === "select" || field.type === "multi_select") ? (
                          <label className="ct-field campaign-field-options">
                            <span>Options</span>
                            <input value={field.optionsText} onChange={(event) => updateField(index, { optionsText: event.target.value })} placeholder="Opcion 1, Opcion 2" />
                          </label>
                        ) : null}
                      </article>
                    );
                  })}
                </div>
              </div>
            </section>

            <section className="campaign-create-section campaign-section-meta">
              <div className="campaign-section-side">
                <span className="campaign-section-icon"><Pulse size={16} weight="bold" /></span>
                <div>
                  <strong>6. Meta</strong>
                  <small>Pixel and events</small>
                </div>
              </div>
              <div className="campaign-section-body campaign-meta-grid">
                <label className="ct-field">
                  <span>Meta Pixel ID</span>
                  <input value={metaPixelId} onChange={(event) => setMetaPixelId(event.target.value)} placeholder="123456789012345" />
                </label>
                <label className="ct-field">
                  <span>Event name</span>
                  <input value={metaEventName} onChange={(event) => setMetaEventName(event.target.value)} placeholder="Lead" />
                </label>
                <label className="ct-field ct-field-toggle campaign-meta-toggle">
                  <input type="checkbox" checked={metaEventsEnabled} onChange={(event) => setMetaEventsEnabled(event.target.checked)} />
                  <span>Send Meta event on lead</span>
                </label>
              </div>
            </section>
          </div>

          <aside className="campaign-create-preview">
            <section className="campaign-form-preview" aria-label="Campaign form preview">
              <div className="campaign-preview-head">
                <span>Lead form preview</span>
                <strong>{campaignName.trim() || "New campaign"}</strong>
              </div>
              <div className="campaign-preview-pages">
                {fields.slice(0, 4).map((field, index) => {
                  const options = field.optionsText
                    .split(/[\n,]/)
                    .map((option) => option.trim())
                    .filter(Boolean);
                  const previewOptions = options.length ? options.slice(0, 4) : ["Si", "No"];
                  return (
                    <section className="campaign-preview-question" key={`${field.id}-preview-${index}`}>
                      <div className="campaign-preview-question-head">
                        <span>{index + 1}/{fields.length}</span>
                        {field.required ? <small>Required</small> : null}
                      </div>
                      <strong>{field.label.trim() || `Field ${index + 1}`}</strong>
                      {field.placeholder ? <em>{field.placeholder}</em> : null}
                      {(field.type === "select" || field.type === "multi_select" || field.type === "yes_no") ? (
                        <div className="campaign-preview-options">
                          {previewOptions.map((option) => <span key={`${field.id}-${option}`}>{option}</span>)}
                        </div>
                      ) : (
                        <div className={`campaign-preview-input ${field.type === "textarea" ? "is-long" : ""}`} />
                      )}
                    </section>
                  );
                })}
              </div>
              <div className="campaign-preview-foot">
                <button type="button" className="ct-btn" disabled>
                  <Check size={13} weight="bold" />
                  Next
                </button>
                <span>Draft preview</span>
              </div>
            </section>

            <section className="campaign-summary-card">
              <strong>Campaign summary</strong>
              <dl>
                <div><dt>Status</dt><dd>{humanize(campaignStatus)}</dd></div>
                <div><dt>Budget</dt><dd>{dailyBudget ? `USD ${dailyBudget}` : "-"}</dd></div>
                <div><dt>Country</dt><dd>{campaignCountryLabels[locationCountryCode]}</dd></div>
                <div><dt>Locations</dt><dd>{campaignLocations.length ? `${campaignLocations.length} saved` : currentLocationLabel}</dd></div>
                <div><dt>Client</dt><dd>{clientMode === "existing" ? (selectedClient?.display_name || "Existing") : (newClientName.trim() || "New client")}</dd></div>
                <div><dt>Form fields</dt><dd>{fields.length} fields</dd></div>
                <div><dt>Creative</dt><dd>{creativeSummary ? "Copy ready" : "Empty"}</dd></div>
                <div><dt>Meta event</dt><dd>{metaEventsEnabled ? metaEventName || "Lead" : "Off"}</dd></div>
              </dl>
            </section>

            <div className="campaign-create-actions">
              <button type="button" className="ct-btn ct-btn-ghost" onClick={() => setCreateOpen(false)}>Cancel</button>
              <button type="submit" className="ct-btn campaign-create-primary" disabled={saving}>{saving ? "Saving..." : "Create campaign"}</button>
            </div>
          </aside>
        </form>
      ) : null}

      <div className="campaign-manager-grid">
        <div className="campaign-list">
          {loading && !campaigns.length ? (
            <CtEmptyState compact loading title="Loading campaigns" message="Checking owned forms." />
          ) : campaigns.length ? campaigns.map((campaign) => (
            <button
              type="button"
              className={`campaign-card ${selectedCampaign?.id === campaign.id ? "active" : ""}`}
              key={campaign.id}
              onClick={() => void selectCampaign(campaign.id)}
            >
              <div>
                <strong>{campaign.name}</strong>
                <span>{campaign.client?.display_name || "No client"} · {campaign.location || "No location"}</span>
              </div>
              <span className="delivery-status-pill" data-tone={campaign.status === "active" ? "success" : campaign.status === "paused" ? "warn" : "muted"}>
                {humanize(campaign.status)}
              </span>
              <small>{compactNumber(campaign.submission_count)} leads</small>
            </button>
          )) : (
            <CtEmptyState compact title="No campaign forms yet" message="Create the first owned form." />
          )}
        </div>

        <div className="campaign-detail-panel">
          {selectedCampaign ? (
            <>
              <div className="campaign-detail-head">
                <div>
                  <span>Public form</span>
                  <strong>{selectedCampaign.name}</strong>
                  <a href={selectedCampaign.public_url} target="_blank" rel="noreferrer">{selectedCampaign.public_url}</a>
                </div>
                <div className="campaign-detail-actions">
                  <button type="button" className="ct-icon-btn" onClick={() => void copyCampaignUrl(selectedCampaign)} title="Copy public URL" aria-label="Copy public URL">
                    <Copy size={14} weight="bold" />
                  </button>
                  <button type="button" className="ct-icon-btn" onClick={() => window.open(selectedCampaign.public_url, "_blank", "noopener,noreferrer")} title="Open public form" aria-label="Open public form">
                    <ArrowSquareOut size={14} weight="bold" />
                  </button>
                </div>
              </div>

              <div className="campaign-detail-metrics">
                <span><strong>{compactNumber(selectedCampaign.submission_count)}</strong>Submissions</span>
                <span><strong>{selectedCampaign.daily_budget_usd ? `$${selectedCampaign.daily_budget_usd}` : "-"}</strong>Daily</span>
                <span><strong>{selectedCampaign.delivery_source ? "Ready" : "Missing"}</strong>Delivery</span>
                <span><strong>{selectedCampaign.meta_events_enabled ? "On" : "Off"}</strong>Meta</span>
              </div>

              <div className="campaign-detail-controls">
                <button type="button" className="ct-btn ct-btn-ghost" disabled={saving || selectedCampaign.status === "active"} onClick={() => void patchCampaignStatus(selectedCampaign, "active")}>Activate</button>
                <button type="button" className="ct-btn ct-btn-ghost" disabled={saving || selectedCampaign.status === "paused"} onClick={() => void patchCampaignStatus(selectedCampaign, "paused")}>Pause</button>
                <button type="button" className="ct-btn ct-btn-ghost" disabled={saving} onClick={() => void refreshDeliverySource(selectedCampaign)}>Delivery source</button>
              </div>

              <div className="campaign-submissions">
                <div className="campaign-submissions-head">
                  <strong>Submissions</strong>
                  <button type="button" className="ct-btn ct-btn-ghost" disabled={submissionsLoading} onClick={() => void loadCampaignSubmissions(selectedCampaign.id)}>
                    <ArrowsClockwise size={13} weight="bold" />
                    Refresh
                  </button>
                </div>
                {submissionsLoading && !submissions.length ? (
                  <CtEmptyState compact loading title="Loading submissions" message="Checking captured leads." />
                ) : submissions.length ? (
                  <div className="campaign-submission-list">
                    {submissions.map((submission) => (
                      <article className="campaign-submission-row" key={submission.id}>
                        <div>
                          <strong>{submission.full_name || submission.phone}</strong>
                          <span>{submission.phone}{submission.email ? ` · ${submission.email}` : ""}</span>
                        </div>
                        <span>{submission.created_at ? relativeTime(submission.created_at) : "-"}</span>
                        <span className="delivery-status-pill" data-tone={submission.delivery_status === "pending" ? "warn" : "muted"}>{humanize(submission.delivery_status || "queued")}</span>
                      </article>
                    ))}
                  </div>
                ) : (
                  <CtEmptyState compact title="No submissions yet" message="Captured leads will appear here." />
                )}
              </div>
            </>
          ) : (
            <CtEmptyState compact title="No selected campaign" message="Create or select a campaign form." />
          )}
        </div>
      </div>
    </section>
  );
}

function ClientLeadDeliveryView({
  sources,
  contactGroups,
  leads,
  selectedSource,
  selectedSourceId,
  editorMode,
  draft,
  loading,
  leadsLoading,
  recipientChat,
  recipientChatLoading,
  actionBusy,
  copyStatus,
  sourceEditorError,
  onSelectSource,
  onNewSource,
  onDraftChange,
  onSaveSource,
  onDeleteSource,
  onCopyLead,
  onCopyLeadAll,
  onRetryLead,
  onOpenCrmLead,
}: {
  sources: ClientLeadSource[];
  contactGroups: DeliveryContactGroup[];
  leads: ClientLead[];
  selectedSource: ClientLeadSource | null;
  selectedSourceId: string | null;
  editorMode: DeliveryEditorMode;
  draft: ClientLeadSourceDraft;
  loading: boolean;
  leadsLoading: boolean;
  recipientChat: ClientLeadRecipientChatResponse | null;
  recipientChatLoading: boolean;
  actionBusy: string | null;
  copyStatus: string;
  sourceEditorError: string;
  onSelectSource: (sourceId: string) => void;
  onNewSource: () => void;
  onDraftChange: (draft: ClientLeadSourceDraft) => void;
  onSaveSource: (event: FormEvent<HTMLFormElement>) => void | Promise<void>;
  onDeleteSource: () => void;
  onCopyLead: (lead: ClientLead) => void | Promise<void>;
  onCopyLeadAll: (lead: ClientLead) => void | Promise<void>;
  onRetryLead: (lead: ClientLead) => void | Promise<void>;
  onOpenCrmLead: (lead: ClientLeadRecipientCrmLead) => void;
}) {
  const [configOpen, setConfigOpen] = useState(editorMode === "create");
  const [sentChatOpen, setSentChatOpen] = useState(false);
  const [deliveryStage, setDeliveryStage] = useState<"contacts" | "client" | "sheet">("contacts");
  const [activeSheetId, setActiveSheetId] = useState<string | null>(null);
  const isExisting = editorMode === "edit" && Boolean(selectedSource);
  const selectedGroup = isExisting
    ? contactGroups.find((group) => group.sources.some((source) => source.id === selectedSourceId)) ?? null
    : null;
  const selectedSources = selectedGroup?.sources ?? (selectedSource ? [selectedSource] : []);
  const selectedGroupKey = selectedGroup?.key ?? selectedSourceId ?? "";
  const selectedGroupLabel = selectedGroup?.label || selectedSource?.label || "Select a contact";
  const selectedGroupTone = selectedGroup ? deliveryContactTone(selectedGroup) : selectedSource ? deliverySourceTone(selectedSource) : "muted";
  const selectedGroupStatus = selectedGroup ? deliveryContactStatusLabel(selectedGroup) : selectedSource?.enabled ? humanize(selectedSource.last_sync_status || "active") : "Paused";
  const activeSheet = selectedSources.find((source) => source.id === activeSheetId) ?? null;
  const activeSheetLeads = activeSheet ? leads.filter((lead) => lead.source_id === activeSheet.id) : [];
  const activeSheetSections = activeSheet ? buildDeliverySheetLeadSections([activeSheet], activeSheetLeads, activeSheet.id) : [];
  const totalLeads = sources.reduce((total, source) => total + deliverySourceCount(source, "total"), 0);
  const failedLeads = contactGroups.reduce((total, group) => total + group.issues, 0);
  const deliveredLeads = sources.reduce((total, source) => total + deliverySourceCount(source, "sent") + deliverySourceCount(source, "delivered"), 0);
  const selectedTotalLeads = selectedSources.reduce((total, source) => total + deliverySourceCount(source, "total"), 0);
  const selectedDeliveredLeads = selectedSources.reduce((total, source) => total + deliverySourceCount(source, "sent") + deliverySourceCount(source, "delivered"), 0);
  const selectedBlockedLeads = selectedSources.reduce((total, source) => total + deliverySourceCount(source, "blocked"), 0);
  const selectedFailedLeads = selectedSources.reduce((total, source) => total + deliverySourceCount(source, "failed"), 0);
  const activeSheetTotalLeads = activeSheet ? deliverySourceCount(activeSheet, "total") : 0;
  const activeSheetDeliveredLeads = activeSheet ? deliverySourceCount(activeSheet, "sent") + deliverySourceCount(activeSheet, "delivered") : 0;
  const activeSheetBlockedLeads = activeSheet ? deliverySourceCount(activeSheet, "blocked") : 0;
  const activeSheetFailedLeads = activeSheet ? deliverySourceCount(activeSheet, "failed") : 0;
  const selectedLabel = editorMode === "create" ? "New contact" : selectedGroupLabel;
  const selectedIssueSources = selectedSources.filter(deliverySourceHasIssue);
  const activeSheetIssueSources = activeSheet && deliverySourceHasIssue(activeSheet) ? [activeSheet] : [];
  const recipientMessages = recipientChat?.messages ?? [];
  const recipientDeliveredCount = recipientMessages.filter((message) => message.delivery_status === "delivered").length;
  const recipientCrmLead = recipientChat?.crm_leads?.[0] ?? null;

  useEffect(() => {
    if (editorMode === "create") {
      setConfigOpen(true);
      setDeliveryStage("client");
      setActiveSheetId(null);
    }
  }, [editorMode]);

  useEffect(() => {
    if (editorMode === "edit" && selectedGroupKey) {
      setConfigOpen(false);
      setSentChatOpen(false);
      setActiveSheetId(null);
    }
  }, [editorMode, selectedGroupKey]);

  function startNewDeliveryContact() {
    setDeliveryStage("client");
    setActiveSheetId(null);
    onNewSource();
  }

  function openDeliveryContact(group: DeliveryContactGroup) {
    setDeliveryStage("client");
    setActiveSheetId(null);
    onSelectSource(group.primarySource.id);
  }

  function openDeliverySheet(source: ClientLeadSource) {
    setDeliveryStage("sheet");
    setActiveSheetId(source.id);
    onSelectSource(source.id);
  }

  function backToDeliveryContacts() {
    setDeliveryStage("contacts");
    setActiveSheetId(null);
    setSentChatOpen(false);
  }

  function backToDeliveryClient() {
    setDeliveryStage("client");
    setActiveSheetId(null);
  }

  const canInspectClient = isExisting && selectedSources.length > 0;
  const showingSheet = deliveryStage === "sheet" && Boolean(activeSheet);

  return (
    <div className="ct-surface delivery-surface">
      <div className="ct-simple-head delivery-home-head">
        <div className="ct-simple-title delivery-home-title">
          <span>Delivery</span>
          <strong>{contactGroups.length ? `${compactNumber(contactGroups.length)} clients` : "No clients yet"}</strong>
          <small>{showingSheet && activeSheet ? deliverySheetLabel(activeSheet) : "Lead delivery"}</small>
        </div>
        <div className="ct-simple-metrics delivery-summary-metrics" aria-label="Delivery summary">
          <span>
            <strong>{compactNumber(totalLeads)}</strong>
            Leads
          </span>
          <span>
            <strong>{compactNumber(deliveredLeads)}</strong>
            Delivered
          </span>
          <span>
            <strong>{compactNumber(failedLeads)}</strong>
            Issues
          </span>
        </div>
        <button type="button" className="ct-btn ct-btn-ghost delivery-small-btn" onClick={startNewDeliveryContact}>
          <Plus size={13} weight="bold" />
          Contact
        </button>
      </div>
      {copyStatus ? <p className="delivery-copy-status" aria-live="polite">{copyStatus}</p> : null}

      {deliveryStage === "contacts" ? (
        <section className="delivery-home">
          {loading && !contactGroups.length ? (
            <CtEmptyState compact loading title="Loading clients" message="Checking Delivery sources." />
          ) : contactGroups.length ? (
            <div className="delivery-contact-grid">
              {contactGroups.map((group) => {
                const active = editorMode === "edit" && group.sources.some((source) => source.id === selectedSourceId);
                return (
                  <button
                    type="button"
                    className={`delivery-contact-card ${active ? "active" : ""} ${group.sources.some((source) => source.enabled) ? "" : "disabled"}`}
                    data-tone={deliveryContactTone(group)}
                    key={group.key}
                    onClick={() => openDeliveryContact(group)}
                  >
                    <div className="delivery-card-title">
                      <strong>{group.label || group.key}</strong>
                      <span className="delivery-status-pill" data-tone={deliveryContactTone(group)}>
                        {deliveryContactStatusLabel(group)}
                      </span>
                    </div>
                    <p>{group.recipientName || "No recipient"}{group.recipientPhone ? ` · ${group.recipientPhone}` : ""}</p>
                    <div className="delivery-card-counts">
                      <span><strong>{compactNumber(group.total)}</strong>Total</span>
                      <span><strong>{compactNumber(group.delivered)}</strong>Delivered</span>
                      <span><strong>{compactNumber(group.sources.length)}</strong>Sheets</span>
                      <span><strong>{compactNumber(group.issues)}</strong>Issues</span>
                    </div>
                    <div className="delivery-source-sheet-tags">
                      {group.sources.slice(0, 4).map((source) => (
                        <span key={source.id} data-tone={deliverySourceTone(source)}>
                          {deliverySheetLabel(source)}
                        </span>
                      ))}
                      {group.sources.length > 4 ? <span>+{group.sources.length - 4}</span> : null}
                    </div>
                  </button>
                );
              })}
            </div>
          ) : (
            <CtEmptyState compact title="No clients yet" message="Add a Delivery contact to pull sheet leads." />
          )}
        </section>
      ) : (
        <section className="delivery-client-page">
          <header className="delivery-client-head">
            <button type="button" className="ct-btn ct-btn-ghost delivery-back-btn" onClick={backToDeliveryContacts}>
              All clients
            </button>
            <div className="delivery-client-main">
              <div className="ct-detail-avatar">{monogram(selectedLabel)}</div>
              <div className="ct-detail-head-copy">
                <p className="ct-detail-kicker">{showingSheet ? "Delivery sheet" : "Delivery client"}</p>
                <h3>{showingSheet && activeSheet ? deliverySheetLabel(activeSheet) : selectedLabel}</h3>
                <p className="ct-detail-meta">
                  {isExisting
                    ? [selectedGroup?.recipientName || selectedSource?.recipient_name || "-", selectedGroup?.recipientPhone || selectedSource?.recipient_phone || "-", `${selectedSources.length} ${selectedSources.length === 1 ? "sheet" : "sheets"}`].join(" · ")
                    : "Create a sheet contact, recipient, and WhatsApp template mapping."}
                </p>
              </div>
            </div>
            <div className="delivery-client-actions">
              <span className="delivery-live-pill" data-tone={selectedGroupTone}>
                {isExisting ? selectedGroupStatus : "Draft"}
              </span>
              <button
                type="button"
                className="ct-btn ct-btn-ghost"
                disabled={!isExisting}
                onClick={() => setSentChatOpen((current) => !current)}
              >
                <ChatCircleText size={15} weight="bold" />
                Sent chat
              </button>
              <button
                type="button"
                className="ct-btn ct-btn-ghost"
                disabled={!isExisting && editorMode !== "create"}
                onClick={() => setConfigOpen(true)}
              >
                <GearSix size={15} weight="bold" />
                {editorMode === "create" ? "Source setup" : "Edit source"}
              </button>
            </div>
          </header>

          {!canInspectClient ? (
            <CtEmptyState compact title="New Delivery contact" message="Complete the source setup to start syncing leads." />
          ) : showingSheet && activeSheet ? (
            <div className="delivery-sheet-page">
              <div className="delivery-sheet-page-head">
                <button type="button" className="ct-btn ct-btn-ghost delivery-back-btn" onClick={backToDeliveryClient}>
                  Sheets
                </button>
                <div className="delivery-sheet-heading">
                  <span>{activeSheet.sheet_tab_name || activeSheet.sheet_gid || "Sheet"}</span>
                  <strong>{deliverySheetLabel(activeSheet)}</strong>
                </div>
                <div className="delivery-sheet-metrics">
                  <span>{compactNumber(activeSheetTotalLeads)} total</span>
                  <span>{compactNumber(activeSheetDeliveredLeads)} delivered</span>
                  <span>{compactNumber(activeSheetBlockedLeads)} blocked</span>
                  <span>{compactNumber(activeSheetFailedLeads)} failed</span>
                </div>
              </div>

              {activeSheetIssueSources.length ? (
                <div className="delivery-source-alert" data-tone="danger">
                  <WarningCircle size={18} weight="fill" />
                  <div>
                    <strong>Sheet needs access</strong>
                    <span>{deliverySourceIssueText(activeSheet)}</span>
                  </div>
                </div>
              ) : null}

              <DeliverySheetRows
                actionBusy={actionBusy}
                leadsLoading={leadsLoading}
                rowCount={activeSheetLeads.length}
                sections={activeSheetSections}
                onCopyLead={onCopyLead}
                onCopyLeadAll={onCopyLeadAll}
                onRetryLead={onRetryLead}
              />
            </div>
          ) : (
            <div className="delivery-client-overview">
              <div className="delivery-client-summary">
                <span><strong>{compactNumber(selectedTotalLeads)}</strong>Total</span>
                <span><strong>{compactNumber(selectedDeliveredLeads)}</strong>Delivered</span>
                <span><strong>{compactNumber(selectedBlockedLeads)}</strong>Blocked</span>
                <span><strong>{compactNumber(selectedFailedLeads)}</strong>Failed</span>
              </div>

              {selectedIssueSources.length ? (
                <div className="delivery-source-alert" data-tone="danger">
                  <WarningCircle size={18} weight="fill" />
                  <div>
                    <strong>{selectedIssueSources.length === 1 ? "Sheet needs access" : "Sheets need access"}</strong>
                    <span>{selectedIssueSources.map((source) => `${deliverySheetLabel(source)}: ${deliverySourceIssueText(source)}`).join(" · ")}</span>
                  </div>
                </div>
              ) : null}

              <section className="delivery-sheet-grid" aria-label="Delivery sheets">
                {selectedSources.map((source) => {
                  const sourceDelivered = deliverySourceCount(source, "sent") + deliverySourceCount(source, "delivered");
                  const sourceIssues = deliverySourceCount(source, "blocked") + deliverySourceCount(source, "failed");
                  return (
                    <button
                      type="button"
                      className="delivery-sheet-card"
                      data-tone={deliverySourceTone(source)}
                      key={source.id}
                      onClick={() => openDeliverySheet(source)}
                    >
                      <div className="delivery-card-title">
                        <strong>{deliverySheetLabel(source)}</strong>
                        <span className="delivery-status-pill" data-tone={deliverySourceTone(source)}>
                          {deliverySourceStatusIcon(source)}
                          {humanize(source.last_sync_status || "active")}
                        </span>
                      </div>
                      <p>{source.sheet_tab_name || source.sheet_gid || "Sheet"}</p>
                      <div className="delivery-card-counts">
                        <span><strong>{compactNumber(deliverySourceCount(source, "total"))}</strong>Rows</span>
                        <span><strong>{compactNumber(sourceDelivered)}</strong>Delivered</span>
                        <span><strong>{compactNumber(sourceIssues)}</strong>Issues</span>
                      </div>
                    </button>
                  );
                })}
              </section>

              {sentChatOpen ? (
                <section className="delivery-recipient-chat-panel">
                  <div className="workstation-panel-head">
                    <div>
                      <span>Sent chat</span>
                      <strong>
                        {(recipientChat?.recipient_name || selectedSource?.recipient_name || "Recipient")}
                        {" · "}
                        {recipientChat?.recipient_phone || selectedSource?.recipient_phone || "-"}
                      </strong>
                    </div>
                    <div className="delivery-recipient-actions">
                      <span>{recipientMessages.length} messages</span>
                      <span>{recipientDeliveredCount} delivered</span>
                      <button
                        type="button"
                        className="ct-btn ct-btn-ghost"
                        disabled={!recipientCrmLead}
                        onClick={() => {
                          if (recipientCrmLead) {
                            onOpenCrmLead(recipientCrmLead);
                          }
                        }}
                        title={recipientCrmLead ? "Open matching CRM chat" : "No CRM chat found for this recipient phone"}
                      >
                        <ChatCircleText size={14} weight="bold" />
                        CRM chat
                      </button>
                    </div>
                  </div>

                  {recipientChatLoading && !recipientMessages.length ? (
                    <CtEmptyState compact loading title="Loading sent chat" message="Fetching recipient messages." />
                  ) : recipientMessages.length ? (
                    <div className="delivery-recipient-messages">
                      {recipientMessages.map((message) => (
                        <article className="delivery-recipient-message" data-tone={recipientChatMessageTone(message)} key={message.delivery_id}>
                          <div className="delivery-recipient-message-head">
                            <div>
                              <strong>{message.lead_name || message.lead_phone || `Row ${message.row_number}`}</strong>
                              <span>Row {message.row_number}{message.lead_email ? ` · ${message.lead_email}` : ""}</span>
                            </div>
                            <span className="delivery-status-pill" data-tone={recipientChatMessageTone(message)}>
                              {humanize(message.delivery_status)}
                            </span>
                          </div>
                          <p>{message.text || "-"}</p>
                          <small>
                            {recipientChatMessageDetail(message)}
                            {message.external_id ? ` · Meta ${truncate(message.external_id, 24)}` : ""}
                          </small>
                          {message.last_delivery_error ? <em>{message.last_delivery_error}</em> : null}
                        </article>
                      ))}
                    </div>
                  ) : (
                    <CtEmptyState compact title="No sent chat yet" message="Delivery messages will appear here." />
                  )}
                </section>
              ) : null}
            </div>
          )}
        </section>
      )}

      {configOpen ? (
        <DeliverySourceEditorDrawer
          actionBusy={actionBusy}
          draft={draft}
          editorMode={editorMode}
          isExisting={isExisting}
          sourceEditorError={sourceEditorError}
          onClose={() => setConfigOpen(false)}
          onDeleteSource={onDeleteSource}
          onDraftChange={onDraftChange}
          onSaveSource={onSaveSource}
        />
      ) : null}
    </div>
  );
}

function DeliverySourceEditorDrawer({
  actionBusy,
  draft,
  editorMode,
  isExisting,
  sourceEditorError,
  onClose,
  onDeleteSource,
  onDraftChange,
  onSaveSource,
}: {
  actionBusy: string | null;
  draft: ClientLeadSourceDraft;
  editorMode: DeliveryEditorMode;
  isExisting: boolean;
  sourceEditorError: string;
  onClose: () => void;
  onDeleteSource: () => void;
  onDraftChange: (draft: ClientLeadSourceDraft) => void;
  onSaveSource: (event: FormEvent<HTMLFormElement>) => void | Promise<void>;
}) {
  const validation = validateClientLeadSourceDraft(draft);
  const drawerMessages = sourceEditorError
    ? [sourceEditorError]
    : validation.messages;

  function submitSource(event: FormEvent<HTMLFormElement>) {
    if (!validation.canSave) {
      event.preventDefault();
      return;
    }
    void onSaveSource(event);
  }

  function updateDraft<K extends keyof ClientLeadSourceDraft>(key: K, value: ClientLeadSourceDraft[K]) {
    onDraftChange({ ...draft, [key]: value });
  }

  return (
    <aside className="ct-drawer open delivery-source-drawer" aria-hidden="false" aria-label="Delivery source editor">
      <button className="ct-drawer-overlay" type="button" onClick={onClose} aria-label="Close Delivery source editor" />
      <form className="ct-drawer-panel wide delivery-source-drawer-panel" role="dialog" aria-modal="false" aria-labelledby="deliverySourceDrawerTitle" onSubmit={submitSource}>
        <header className="ct-drawer-head">
          <div>
            <p className="ct-drawer-kicker">Delivery source</p>
            <h3 id="deliverySourceDrawerTitle">{editorMode === "create" ? "New contact" : "Sheet and template"}</h3>
            <p className="ct-drawer-note">Keep polling, recipient, and mapping details out of the daily Delivery view.</p>
          </div>
          <button type="button" className="ct-icon-btn" onClick={onClose} aria-label="Close Delivery source editor">
            <X size={16} weight="bold" />
          </button>
        </header>

        <div className="ct-drawer-body delivery-source-form">
          {drawerMessages.length ? (
            <div className="delivery-drawer-feedback" role="alert">
              <strong>{sourceEditorError ? "Save blocked" : "Complete before saving"}</strong>
              <ul>
                {drawerMessages.map((message) => (
                  <li key={message}>{message}</li>
                ))}
              </ul>
            </div>
          ) : null}

          <section className="delivery-drawer-section">
            <div className="workstation-panel-head">
              <div>
                <span>Contact</span>
                <strong>Recipient and label</strong>
              </div>
            </div>
            <div className="ct-field-grid">
              <label className="ct-field" data-invalid={validation.fields.id ? "true" : undefined}>
                <span>Source ID</span>
                <input
                  value={draft.id}
                  disabled={isExisting}
                  onChange={(event) => updateDraft("id", slugifyClient(event.target.value))}
                  placeholder="client-name"
                />
                {validation.fields.id ? <p className="ct-field-error">{validation.fields.id}</p> : null}
              </label>
              <label className="ct-field" data-invalid={validation.fields.label ? "true" : undefined}>
                <span>Label</span>
                <input value={draft.label} onChange={(event) => updateDraft("label", event.target.value)} placeholder="Cliente · Sheet delivery" />
                {validation.fields.label ? <p className="ct-field-error">{validation.fields.label}</p> : null}
              </label>
              <label className="ct-field" data-invalid={validation.fields.recipient_name ? "true" : undefined}>
                <span>Recipient name</span>
                <input value={draft.recipient_name} onChange={(event) => updateDraft("recipient_name", event.target.value)} placeholder="Client operator" />
                {validation.fields.recipient_name ? <p className="ct-field-error">{validation.fields.recipient_name}</p> : null}
              </label>
              <label className="ct-field" data-invalid={validation.fields.recipient_phone ? "true" : undefined}>
                <span>Recipient phone</span>
                <input value={draft.recipient_phone} onChange={(event) => updateDraft("recipient_phone", event.target.value)} placeholder="+54..." />
                {validation.fields.recipient_phone ? <p className="ct-field-error">{validation.fields.recipient_phone}</p> : null}
              </label>
            </div>
            <label className="ct-field ct-field-toggle">
              <span>Enabled</span>
              <div className="ct-toggle-row">
                <input type="checkbox" checked={draft.enabled} onChange={(event) => updateDraft("enabled", event.target.checked)} />
                <p className="ct-field-hint">Disabled contacts stay visible but do not poll or notify recipients.</p>
              </div>
            </label>
          </section>

          <section className="delivery-drawer-section">
            <div className="workstation-panel-head">
              <div>
                <span>Sheet</span>
                <strong>Source and polling</strong>
              </div>
            </div>
            <label className="ct-field" data-invalid={validation.fields.sheet_url ? "true" : undefined}>
              <span>Sheet URL</span>
              <input value={draft.sheet_url} onChange={(event) => updateDraft("sheet_url", event.target.value)} placeholder="https://docs.google.com/spreadsheets/..." />
              {validation.fields.sheet_url ? <p className="ct-field-error">{validation.fields.sheet_url}</p> : null}
            </label>
            <div className="ct-field-grid">
              <label className="ct-field">
                <span>Sheet GID</span>
                <input value={draft.sheet_gid} onChange={(event) => updateDraft("sheet_gid", event.target.value)} placeholder="0" />
              </label>
              <label className="ct-field">
                <span>Tab name</span>
                <input value={draft.sheet_tab_name} onChange={(event) => updateDraft("sheet_tab_name", event.target.value)} placeholder="deuda" />
              </label>
              <label className="ct-field" data-invalid={validation.fields.sheet_poll_seconds ? "true" : undefined}>
                <span>Poll seconds</span>
                <input
                  type="number"
                  min="5"
                  value={draft.sheet_poll_seconds}
                  onChange={(event) => updateDraft("sheet_poll_seconds", Number(event.target.value) || 10)}
                />
                {validation.fields.sheet_poll_seconds ? <p className="ct-field-error">{validation.fields.sheet_poll_seconds}</p> : null}
              </label>
            </div>
          </section>

          <section className="delivery-drawer-section">
            <div className="workstation-panel-head">
              <div>
                <span>Template</span>
                <strong>Message mapping</strong>
              </div>
            </div>
            <div className="ct-field-grid">
              <label className="ct-field">
                <span>Template name</span>
                <input value={draft.template_name} onChange={(event) => updateDraft("template_name", event.target.value)} placeholder="client_lead_delivery_es" />
              </label>
              <label className="ct-field">
                <span>Template language</span>
                <input value={draft.template_language} onChange={(event) => updateDraft("template_language", event.target.value)} placeholder="es" />
              </label>
            </div>
            <label className="ct-field" data-invalid={validation.fields.context_field_mapping_text ? "true" : undefined}>
              <span>Context fields</span>
              <textarea
                value={draft.context_field_mapping_text}
                onChange={(event) => updateDraft("context_field_mapping_text", event.target.value)}
                rows={4}
                spellCheck={false}
                placeholder={'{\n  "Tipo de deuda": "¿qué_tipo_de_deuda_tiene_pendiente?",\n  "Caso": "breve_descripción_de_su_caso"\n}'}
              />
              {validation.fields.context_field_mapping_text ? <p className="ct-field-error">{validation.fields.context_field_mapping_text}</p> : null}
            </label>
            <label className="ct-field" data-invalid={validation.fields.column_mapping_text ? "true" : undefined}>
              <span>Column mapping</span>
              <textarea
                value={draft.column_mapping_text}
                onChange={(event) => updateDraft("column_mapping_text", event.target.value)}
                rows={5}
                spellCheck={false}
              />
              {validation.fields.column_mapping_text ? <p className="ct-field-error">{validation.fields.column_mapping_text}</p> : null}
            </label>
          </section>
        </div>

        <footer className="ct-drawer-foot">
          {isExisting ? (
            <button
              type="button"
              className="ct-btn ct-btn-ghost btn-destructive"
              disabled={actionBusy === "delivery-delete"}
              onClick={onDeleteSource}
            >
              <Trash size={15} weight="bold" />
              {actionBusy === "delivery-delete" ? "Deleting..." : "Delete"}
            </button>
          ) : null}
          <button type="submit" className="ct-btn ct-btn-primary" disabled={actionBusy === "delivery-save" || !validation.canSave}>
            <Check size={15} weight="bold" />
            {actionBusy === "delivery-save" ? "Saving..." : editorMode === "create" ? "Create contact" : "Save source"}
          </button>
        </footer>
      </form>
    </aside>
  );
}

function DeliverySheetRows({
  sections,
  leadsLoading,
  rowCount,
  actionBusy,
  onCopyLead,
  onCopyLeadAll,
  onRetryLead,
}: {
  sections: DeliverySheetLeadSection[];
  leadsLoading: boolean;
  rowCount: number;
  actionBusy: string | null;
  onCopyLead: (lead: ClientLead) => void | Promise<void>;
  onCopyLeadAll: (lead: ClientLead) => void | Promise<void>;
  onRetryLead: (lead: ClientLead) => void | Promise<void>;
}) {
  if (leadsLoading && !rowCount) {
    return <CtEmptyState compact loading title="Loading rows" message="Fetching sheet leads." />;
  }

  if (!sections.length) {
    return <CtEmptyState compact title="No rows loaded" message="Rows will appear after the next sync." />;
  }

  return (
    <section className="delivery-lead-panel delivery-sheet-rows-panel">
      <div className="delivery-sheet-sections">
        {sections.map((section) => (
          <section className="delivery-sheet-section" key={section.source.id}>
            <header className="delivery-sheet-section-head">
              <div>
                <span>{section.source.sheet_tab_name || section.source.sheet_gid || "Sheet"}</span>
                <strong>{deliverySheetLabel(section.source)}</strong>
              </div>
              <div className="delivery-sheet-section-meta">
                <span>{compactNumber(section.leads.length)} rows</span>
                <span className="delivery-status-pill" data-tone={deliverySourceTone(section.source)}>
                  {deliverySourceStatusIcon(section.source)}
                  {humanize(section.source.last_sync_status || "active")}
                </span>
              </div>
            </header>
            <div className="delivery-sheet-lead-list">
              {section.leads.map((lead) => {
                const waLink = lead.wa_link || buildWaLink(lead.phone_number);
                const retryable = isRetryableClientLead(lead);
                const copyBusy = actionBusy === `delivery-copy-${lead.id}`;
                const retryBusy = actionBusy === `delivery-retry-${lead.id}`;
                const rawFields = deliveryRawFields(lead);
                return (
                  <article className="delivery-sheet-lead-card" data-tone={clientLeadDeliveryTone(lead)} key={lead.id}>
                    <header className="delivery-sheet-lead-card-head">
                      <div className="delivery-lead-identity">
                        <span>Row {lead.row_number} · {clientLeadAgeText(lead)}</span>
                        <strong>{deliveryLeadTitle(lead)}</strong>
                        <small>{deliveryLeadSubtitle(lead)}</small>
                      </div>
                      <div className="delivery-status-cell">
                        <span className="delivery-status-pill" data-tone={clientLeadDeliveryTone(lead)}>
                          {humanize(lead.delivery_status || (lead.block_reason ? "blocked" : "pending"))}
                        </span>
                        <small>{deliveryStatusDetail(lead)}</small>
                      </div>
                    </header>

                    {lead.notification_text ? (
                      <p className="delivery-notification-preview">{truncate(lead.notification_text, 220)}</p>
                    ) : null}

                    {lead.last_delivery_error || lead.block_reason ? (
                      <p className="delivery-lead-issue">{lead.last_delivery_error || lead.block_reason}</p>
                    ) : null}

                    <div className="delivery-sheet-lead-card-foot">
                      <details className="delivery-raw-details">
                        <summary>
                          Source details
                          <span>{rawFields.length} fields</span>
                        </summary>
                        <dl>
                          {rawFields.map((field) => (
                            <div key={field.label}>
                              <dt>{field.label}</dt>
                              <dd>{field.value || "-"}</dd>
                            </div>
                          ))}
                        </dl>
                      </details>

                      <div className="delivery-row-actions">
                        {waLink ? (
                          <a className="ct-btn ct-btn-ghost delivery-action-link" href={waLink} target="_blank" rel="noreferrer">
                            <ArrowSquareOut size={14} weight="bold" />
                            Chat
                          </a>
                        ) : (
                          <button type="button" className="ct-btn ct-btn-ghost" onClick={() => onCopyLead(lead)}>
                            <Copy size={14} weight="bold" />
                            Copy
                          </button>
                        )}
                        <details className="ct-action-menu delivery-row-menu">
                          <summary className="ct-btn ct-btn-ghost">More</summary>
                          <div className="ct-action-menu-panel">
                            {waLink ? (
                              <button type="button" className="ct-btn ct-btn-ghost" onClick={() => onCopyLead(lead)}>
                                <Copy size={14} weight="bold" />
                                Copy
                              </button>
                            ) : null}
                            <button
                              type="button"
                              className="ct-btn ct-btn-ghost"
                              disabled={copyBusy}
                              onClick={() => onCopyLeadAll(lead)}
                            >
                              {copyBusy ? "Copying..." : "Copy all"}
                            </button>
                            {retryable ? (
                              <button
                                type="button"
                                className="ct-btn ct-btn-ghost"
                                disabled={retryBusy}
                                onClick={() => onRetryLead(lead)}
                              >
                                <ArrowsClockwise size={14} weight="bold" />
                                {retryBusy ? "Retrying..." : "Retry"}
                              </button>
                            ) : null}
                          </div>
                        </details>
                      </div>
                    </div>
                  </article>
                );
              })}
            </div>
          </section>
        ))}
      </div>
    </section>
  );
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

function WorkstationView({
  clients,
  detail,
  funnel,
  selectedClientId,
  listLoading,
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
  onCloseWorkstationClient,
  onProfessionalPhotoEditPromptChange,
  onEditProfessionalPhoto,
}: {
  clients: WorkstationClientSummary[];
  detail: WorkstationClientDetailResponse | null;
  funnel: FunnelDefinition | null;
  selectedClientId: string | null;
  listLoading: boolean;
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
  onCloseWorkstationClient: () => void | Promise<void>;
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
  const publicPage = detailClient ? detail?.public_page ?? null : null;
  const openRuntimeAlerts = runtimeAlerts.filter((alert) => !alert.resolved_at);
  const latestRuntimeAlert = openRuntimeAlerts[0] ?? null;
  const workstationFailed = activeClient?.automation_status === "failed";
  const workstationClosed = activeClient?.status === "closed";
  const detailMedia = detailClient ? detail?.media ?? [] : [];
  const imageAssets = detailMedia.filter((asset) => asset.content_type?.startsWith("image/"));
  const professionalPhotos = detailClient ? detail?.professional_photos ?? [] : [];
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
  const canStartSoloPageWork = activeClient?.work_type === "solo_pagina" && !soloPageBusy && !workstationClosed;
  const showStartCodexPrimary = canStartSoloPageWork;
  const showSteerCodexPrimary = !showStartCodexPrimary && canStopSoloPageWork;
  const showNotesPrimary = !showStartCodexPrimary && !showSteerCodexPrimary && !publicPage;
  const clientListLoading = listLoading && clients.length === 0;
  const clientDetailLoading = Boolean(selectedClientId && loading && detail?.client.id !== selectedClientId);
  const failedClientCount = clients.filter((client) => client.automation_status === "failed").length;
  const totalClientMedia = clients.reduce((total, client) => total + (client.media_count ?? 0), 0);
  const workstationStateIsReady = (automationState?.label ?? "").toLowerCase().includes("ready");
  const workstationHasMissingLiveProcess = automationState && (activeClient?.automation_status === "drafting" || activeClient?.automation_status === "revision_requested")
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
  const workstationClientStateLabel = formatWorkstationClientState(activeClient, automationState);
  const workstationContactLine = selectedLead
    ? [selectedLead.phone, selectedLead.email].filter(Boolean).join(" · ") || selectedLead.external_lead_id || "No contact info"
    : activeClient?.folder_name || "No contact info";
  const workstationMediaCount = detailClient ? detailMedia.length : activeClient?.media_count ?? 0;
  const workstationRunDetailsId = activeClient ? `workstation-run-details-${activeClient.id}` : "workstation-run-details";
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
  const workstationAttention = workstationFailed
    ? {
        title: "Automation failed",
        detail: latestRuntimeAlert?.error || "No runtime alert details were attached. Review this client manually.",
        note: latestRuntimeAlert?.notified_at ? `Email alert sent ${shortDate(latestRuntimeAlert.notified_at)}` : "Email alert pending",
      }
    : automationState?.is_stale
      ? {
          title: "Run is stale",
          detail: automationState.live_detail || automationState.detail || "The visible run has not reported recent progress.",
          note: automationState.progress_updated_at ? `Last update ${shortDate(automationState.progress_updated_at)}` : "No recent progress update",
        }
      : workstationHasMissingLiveProcess
        ? {
            title: "No live process",
            detail: automationState?.detail || "This client is marked as active, but no live Codex process is attached.",
            note: "Needs operator review",
          }
        : latestRuntimeAlert
          ? {
              title: humanize(latestRuntimeAlert.alert_type || "runtime alert"),
              detail: latestRuntimeAlert.error || "No runtime alert details were attached. Review this client manually.",
              note: latestRuntimeAlert.resolved_at
                ? `Resolved ${shortDate(latestRuntimeAlert.resolved_at)}`
                : latestRuntimeAlert.notified_at
                  ? `Email alert sent ${shortDate(latestRuntimeAlert.notified_at)}`
                  : "Email alert pending",
            }
          : null;

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
      <div className="ct-simple-head workstation-simple-head">
        <div className="ct-simple-title">
          <span>Build</span>
          <strong>{clients.length ? `${compactNumber(clients.length)} clients` : "No clients yet"}</strong>
          <small>{clientListLoading ? "Loading converted workspaces" : funnelLabel}</small>
        </div>
        <div className="ct-simple-metrics" aria-label="Build summary">
          <span>
            <strong>{compactNumber(clients.length)}</strong>
            Clients
          </span>
          <span>
            <strong>{compactNumber(failedClientCount)}</strong>
            Alerts
          </span>
          <span>
            <strong>{compactNumber(totalClientMedia)}</strong>
            Media
          </span>
        </div>
      </div>

      <div className="ct-workspace workstation-layout">
        <aside className="ct-leads">
          <div className="ct-leads-head">
            <h3>Clients</h3>
            <p className="ct-leads-summary">{clientListLoading ? "Loading" : clients.length ? `${clients.length} active` : "Empty"}</p>
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
                  <small>{formatWorkstationClientState(client)} · {client.media_count} media</small>
                </div>
              </button>
            )) : clientListLoading ? (
              <CtEmptyState compact loading title="Loading clients" message="Fetching converted workspaces." />
            ) : (
              <CtEmptyState compact title="No clients yet" message="Convert a paid lead to open Build." />
            )}
          </div>
        </aside>

        <section className="ct-detail workstation-detail">
          {clientDetailLoading ? (
            <CtEmptyState loading title="Loading workspace" message="Fetching client details." />
          ) : !activeClient && clientListLoading ? (
            <CtEmptyState loading title="Loading clients" message="Fetching converted workspaces." />
          ) : !activeClient ? (
            <CtEmptyState title="Select a client" message="Choose a converted client to build." />
          ) : (
            <>
              <header className="ct-detail-head workstation-head">
                <div className="ct-detail-head-main workstation-client-summary">
                  <div className="ct-detail-avatar">{monogram(activeClient.display_name || "CL")}</div>
                  <div className="ct-detail-head-copy">
                    <p className="ct-detail-kicker">Build client</p>
                    <h3>{activeClient.display_name}</h3>
                    <p className="ct-detail-meta">{workstationContactLine}</p>
                    <div className="workstation-client-facts" aria-label="Client status">
                      <span>
                        <CheckCircle size={14} weight="bold" />
                        {workstationClientStateLabel}
                      </span>
                      {activeOffer ? <span>{activeOffer}</span> : null}
                      <span>{workstationMediaCount} media</span>
                    </div>
                  </div>
                </div>
                <div className="ct-detail-head-actions workstation-primary-actions">
                  {showStartCodexPrimary ? (
                    <button type="button" className="ct-btn ct-btn-primary" onClick={openSoloPagePromptModal}>
                      <Robot size={15} weight="bold" />
                      Start Codex
                    </button>
                  ) : showSteerCodexPrimary ? (
                    <button
                      type="button"
                      className="ct-btn ct-btn-primary"
                      onClick={openSoloPageSteerModal}
                      disabled={actionBusy === "solo-page-steer"}
                    >
                      <PaperPlaneTilt size={15} weight="bold" />
                      Steer Codex
                    </button>
                  ) : publicPage ? (
                    <a className="ct-btn ct-btn-primary" href={publicPage.public_url} target="_blank" rel="noreferrer">
                      <ArrowSquareOut size={15} weight="bold" />
                      Open page
                    </a>
                  ) : (
                    <button
                      type="button"
                      className="ct-btn ct-btn-primary"
                      onClick={() => setNotesOpen(true)}
                      aria-controls="workstation-notes-panel"
                    >
                      <NotePencil size={15} weight="bold" />
                      Add notes
                    </button>
                  )}
                  <details
                    className="ct-action-menu workstation-action-menu"
                    open={actionsOpen}
                    onToggle={(event) => setActionsOpen(event.currentTarget.open)}
                  >
                    <summary className="ct-btn ct-btn-ghost">
                      More
                      <CaretDown size={14} weight="bold" />
                    </summary>
                    <div className="ct-action-menu-panel workstation-action-popover">
                      <div className="workstation-menu-group">
                        <span className="workstation-menu-label">Build controls</span>
                        {!showStartCodexPrimary ? (
                          <button
                            type="button"
                            onClick={openSoloPagePromptModal}
                            disabled={!canStartSoloPageWork}
                          >
                            <Robot size={16} weight="bold" />
                            <span>Start Codex</span>
                          </button>
                        ) : null}
                        <button
                          type="button"
                          onClick={() => {
                            setActionsOpen(false);
                            onStopSoloPageCodexWork();
                          }}
                          disabled={!canStopSoloPageWork || actionBusy === "solo-page-stop"}
                        >
                          <X size={16} weight="bold" />
                          <span>Stop Codex</span>
                        </button>
                        {!showSteerCodexPrimary ? (
                          <button
                            type="button"
                            onClick={openSoloPageSteerModal}
                            disabled={!canStopSoloPageWork || actionBusy === "solo-page-steer"}
                          >
                            <PaperPlaneTilt size={16} weight="bold" />
                            <span>Steer Codex</span>
                          </button>
                        ) : null}
                      </div>

                      <div className="workstation-menu-group">
                        <span className="workstation-menu-label">Workstation actions</span>
                        <button
                          type="button"
                          onClick={openProfessionalPhotoModal}
                          disabled={workstationClosed || !imageAssets.length || professionalPhotoJobBusy || actionBusy === "professional-photo-start"}
                        >
                          <Camera size={16} weight="bold" />
                          <span>Professional photo</span>
                        </button>
                        {!showNotesPrimary ? (
                          <button
                            type="button"
                            onClick={() => {
                              setNotesOpen((current) => !current);
                              setActionsOpen(false);
                            }}
                            aria-expanded={notesOpen}
                            aria-controls="workstation-notes-panel"
                          >
                            <NotePencil size={16} weight="bold" />
                            <span>Notes</span>
                          </button>
                        ) : null}
                      </div>

                      <div className="workstation-menu-group">
                        <span className="workstation-menu-label">Client utilities</span>
                        <button
                          type="button"
                          onClick={() => {
                            setActionsOpen(false);
                            onOpenCrmLead(selectedLead);
                          }}
                        >
                          <ArrowSquareOut size={16} weight="bold" />
                          <span>Open CRM chat</span>
                        </button>
                        <button
                          type="button"
                          onClick={() => {
                            setActionsOpen(false);
                            onCopyAll();
                          }}
                        >
                          <Copy size={16} weight="bold" />
                          <span>Copy all</span>
                        </button>
                        {publicPage ? (
                          <button
                            type="button"
                            onClick={() => {
                              setActionsOpen(false);
                              copyTextToClipboard(publicPage.public_url).catch(() => undefined);
                            }}
                          >
                            <Copy size={16} weight="bold" />
                            <span>Copy public URL</span>
                          </button>
                        ) : null}
                        <a
                          className="workstation-menu-link"
                          href={`/api/workstation/clients/${activeClient.id}/zip`}
                          onClick={() => setActionsOpen(false)}
                        >
                          <DownloadSimple size={16} weight="bold" />
                          <span>Download ZIP</span>
                        </a>
                        <button
                          type="button"
                          className="danger"
                          onClick={() => {
                            setActionsOpen(false);
                            onCloseWorkstationClient();
                          }}
                          disabled={workstationClosed || actionBusy === "workstation-close"}
                        >
                          <Trash size={16} weight="bold" />
                          <span>{actionBusy === "workstation-close" ? "Closing..." : "Close lead"}</span>
                        </button>
                      </div>
                      </div>
                  </details>
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

              {workstationAttention ? (
                <section className="workstation-failure-alert" role="alert">
                  <WarningCircle size={22} weight="bold" />
                  <div>
                    <span>Workstation alert</span>
                    <strong>{workstationAttention.title}</strong>
                    <p>{workstationAttention.detail}</p>
                    <small>{workstationAttention.note}</small>
                  </div>
                </section>
              ) : null}

              <details
                className={`workstation-panel workstation-automation-panel ${automationTone}`}
                id={workstationRunDetailsId}
              >
                <summary className="workstation-panel-head">
                  <div>
                    <span>Run details</span>
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
                </summary>
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
              </details>

              <details
                className={`workstation-panel workstation-media-panel ${mediaDropActive ? "drag-active" : ""}`}
                onDragOver={handleMediaDragOver}
                onDragLeave={handleMediaDragLeave}
                onDrop={handleMediaDrop}
                onPaste={handleMediaPaste}
                tabIndex={0}
                aria-label="Workstation media"
              >
                <summary className="workstation-panel-head">
                  <div>
                    <span>Media</span>
                    <strong>{detailMedia.length ? `${detailMedia.length} files` : "Files"}</strong>
                  </div>
                </summary>
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
                  {detailMedia.length ? detailMedia.map((asset) => (
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
                    <CtEmptyState compact title="No media yet" message="Upload logos, photos, or references." />
                  )}
                </div>
              </details>

              <details className="workstation-panel">
                <summary className="workstation-panel-head">
                  <div>
                    <span>Photo</span>
                    <strong>{professionalPhotos.length ? `${professionalPhotos.length} versions` : "Portrait"}</strong>
                  </div>
                </summary>
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
                    <CtEmptyState
                      compact
                      loading={professionalPhotoJobBusy}
                      title={professionalPhotoJobBusy ? "Waiting first result" : "No portrait yet"}
                      message={professionalPhotoJobBusy ? "The generated photo will appear here." : "Create a professional photo from client media."}
                    />
                  )}
                </div>
              </details>

              <details className="workstation-panel workstation-chat-panel">
                <summary className="workstation-panel-head">
                  <div>
                    <span>Conversation</span>
                    <strong>{workstationMessages.length ? `${workstationMessages.length} messages` : "WhatsApp"}</strong>
                  </div>
                </summary>
                <div className="workstation-chat-actions">
                  <button type="button" className="ct-btn ct-btn-ghost workstation-crm-link" onClick={() => onOpenCrmLead(selectedLead)}>
                    <ArrowSquareOut size={15} weight="bold" />
                    Open
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
              </details>
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

function ConfirmDialog({
  dialog,
  busy,
  onClose,
  onSubmit,
}: {
  dialog: ConfirmDialogState;
  busy: boolean;
  onClose: () => void;
  onSubmit: (event: FormEvent<HTMLFormElement>) => void;
}) {
  const dialogRef = useRef<HTMLFormElement | null>(null);
  const cancelButtonRef = useRef<HTMLButtonElement | null>(null);
  const titleId = `ctConfirmTitle-${dialog.id.replace(/[^a-zA-Z0-9_-]/g, "-")}`;
  const messageId = `ctConfirmMessage-${dialog.id.replace(/[^a-zA-Z0-9_-]/g, "-")}`;

  useEffect(() => {
    const previousFocus = document.activeElement instanceof HTMLElement ? document.activeElement : null;
    cancelButtonRef.current?.focus();

    return () => {
      if (previousFocus?.isConnected) {
        previousFocus.focus();
      }
    };
  }, [dialog.id]);

  const getFocusableControls = useCallback(() => {
    const panel = dialogRef.current;
    if (!panel) {
      return [];
    }
    return Array.from(panel.querySelectorAll<HTMLElement>(CONFIRM_FOCUSABLE_SELECTOR)).filter((element) => {
      const rect = element.getBoundingClientRect();
      const style = window.getComputedStyle(element);
      return rect.width > 0 && rect.height > 0 && style.display !== "none" && style.visibility !== "hidden";
    });
  }, []);

  function handleKeyDown(event: KeyboardEvent<HTMLFormElement>) {
    if (event.key === "Escape") {
      event.preventDefault();
      onClose();
      return;
    }
    if (event.key !== "Tab") {
      return;
    }

    const focusableControls = getFocusableControls();
    if (!focusableControls.length) {
      event.preventDefault();
      return;
    }

    const currentIndex = focusableControls.findIndex((control) => control === document.activeElement);
    const nextIndex = event.shiftKey
      ? (Math.max(currentIndex, 0) - 1 + focusableControls.length) % focusableControls.length
      : (Math.max(currentIndex, 0) + 1) % focusableControls.length;
    event.preventDefault();
    focusableControls[nextIndex].focus();
  }

  return (
    <div className="ct-modal open" aria-hidden="false">
      <button className="ct-modal-overlay" type="button" onClick={onClose} disabled={busy} aria-label="Close confirmation" />
      <form
        ref={dialogRef}
        className="ct-modal-panel ct-confirm-panel"
        data-tone={dialog.tone}
        role="dialog"
        aria-modal="true"
        aria-labelledby={titleId}
        aria-describedby={messageId}
        onSubmit={onSubmit}
        onKeyDown={handleKeyDown}
      >
        <header className="ct-modal-head ct-confirm-head">
          <div className="ct-confirm-icon" aria-hidden="true">
            <WarningCircle size={22} weight="fill" />
          </div>
          <div>
            <p className="ct-drawer-kicker">{dialog.tone === "danger" ? "Destructive action" : "Confirm action"}</p>
            <h3 id={titleId}>{dialog.title}</h3>
          </div>
        </header>
        <div className="ct-modal-body ct-confirm-body">
          <p id={messageId}>{dialog.message}</p>
        </div>
        <footer className="ct-modal-foot">
          <button ref={cancelButtonRef} type="button" className="ct-btn ct-btn-ghost" onClick={onClose} disabled={busy}>Cancel</button>
          <button type="submit" className={`ct-btn ${dialog.tone === "danger" ? "ct-btn-danger" : "ct-btn-warn"}`} disabled={busy}>
            {busy ? <SpinnerGap className="workstation-spinner" size={15} weight="bold" /> : <WarningCircle size={15} weight="bold" />}
            {busy ? dialog.busyLabel : dialog.confirmLabel}
          </button>
        </footer>
      </form>
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
                <CtEmptyState compact title="No images available" message="Upload image media before creating a photo." />
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
  const [showSetupDetails, setShowSetupDetails] = useState(false);

  if (!funnel) {
    return (
      <div className="ct-funnel-setup">
        <CtEmptyState compact title="No funnel selected" message="Pick a funnel to review setup." />
      </div>
    );
  }

  const textStrategy = funnel.strategies.find((strategy) => strategy.delivery === "text");
  const mp4Strategy = funnel.strategies.find((strategy) => strategy.delivery === "video");
  const readyItems = buildFunnelReadyItems(funnel);
  const blockedItems = readyItems.filter((item) => !item.ready);
  const readyCount = readyItems.length - blockedItems.length;
  const setupReady = blockedItems.length === 0;

  return (
    <section className="ct-funnel-setup" aria-label="Funnel setup">
      <header className="ct-funnel-hero">
        <div>
          <p className="ct-detail-kicker">Funnel setup</p>
          <h2>{funnel.label}</h2>
          <p>{setupReady ? "Ready to sync leads and run the CRM flow." : "Fix the missing fields before turning this funnel into a live campaign."}</p>
        </div>
        <button type="button" className="ct-btn ct-btn-primary" onClick={onEdit}>Edit funnel</button>
      </header>

      <div className="ct-setup-overview" data-ready={setupReady ? "true" : "false"}>
        <div>
          <span>{setupReady ? "Ready" : "Needs setup"}</span>
          <strong>{readyCount}/{readyItems.length}</strong>
        </div>
        <div className="ct-setup-next">
          {setupReady ? (
            <p>No blockers. Keep details closed unless you are changing the funnel.</p>
          ) : (
            blockedItems.slice(0, 4).map((item) => (
              <span key={item.label}>
                <WarningCircle size={14} weight="bold" />
                {item.label}
              </span>
            ))
          )}
        </div>
      </div>

      <section
        className="ct-setup-details"
        data-open={showSetupDetails ? "true" : "false"}
        onClick={(event) => {
          const target = event.target as Element;
          if (target === event.currentTarget || target.closest(".ct-setup-details-summary")) {
            setShowSetupDetails((open) => !open);
          }
        }}
      >
        <button
          type="button"
          className="ct-setup-details-summary"
          aria-expanded={showSetupDetails}
        >
          Setup details
          <span>{blockedItems.length ? `${blockedItems.length} blocked` : "All checks ready"}</span>
        </button>

        <div className="ct-setup-checklist" aria-label="Setup checklist">
          {readyItems.map((item) => (
            <div className={`ct-setup-check ${item.ready ? "ready" : "blocked"}`} key={item.label}>
              {item.ready ? <Check size={16} weight="bold" /> : <WarningCircle size={16} weight="bold" />}
              <span>{item.label}</span>
            </div>
          ))}
        </div>

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
            <span>Offer</span>
            <strong>{textStrategy ? "Text offer" : mp4Strategy ? "Media offer" : "Not configured"}</strong>
            <p>{textStrategy?.message_text || mp4Strategy?.media_path || "-"}</p>
          </article>
          <article className="ct-funnel-card">
            <span>Meeting</span>
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
            <span>Operator ping template</span>
            {funnel.manual_ping_template_name ? <code>{funnel.manual_ping_template_name}</code> : null}
            <blockquote>{funnel.manual_ping_text}</blockquote>
          </div>
          <div className="ct-copy-row">
            <span>Offer message</span>
            <blockquote>{textStrategy?.message_text || funnel.loom_intro_text || "-"}</blockquote>
          </div>
          <div className="ct-copy-row">
            <span>Meeting handoff</span>
            <blockquote>{funnel.calendly_intro_text}</blockquote>
          </div>
        </section>

        <p className="ct-config-path">Config file: {configPath || "data/funnels.json"}</p>
      </section>
    </section>
  );
}

function FunnelSetupBanner({
  setupIssues,
  onEdit,
}: {
  setupIssues: string[];
  onEdit: () => void;
}) {
  return (
    <section className="ct-setup-callout" aria-label="Funnel setup warning">
      <WarningCircle size={18} weight="bold" />
      <div>
        <strong>Funnel setup incomplete</strong>
        <p>{setupIssues.slice(0, 3).join(" ")}</p>
      </div>
      <button type="button" className="ct-btn ct-btn-ghost" onClick={onEdit}>Edit funnel</button>
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
  const textStrategy = draft.strategies.find((strategy) => strategy.delivery === "text");
  const videoStrategy = draft.strategies.find((strategy) => strategy.delivery === "video");
  const primaryStrategy = textStrategy ?? videoStrategy ?? draft.strategies[0];
  const templateChoices = buildTemplateChoices(draft);
  const [showFunnelDetails, setShowFunnelDetails] = useState(false);

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

  function updateStrategyMessageText(strategyId: string | undefined, value: string) {
    if (!strategyId) {
      return;
    }
    setDraft((current) => ({
      ...current,
      strategies: current.strategies.map((strategy) => (
        strategy.id === strategyId ? { ...strategy, message_text: value } : strategy
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
      offer_version: draft.offer_version.trim() || "mission-2026-05-30",
      offer_summary: draft.offer_summary.trim(),
      default_daily_ad_budget_usd: draft.default_daily_ad_budget_usd ?? null,
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
            <span>Sheet URL</span>
            <input value={draft.sheet_url ?? ""} onChange={(event) => update("sheet_url", event.target.value || null)} />
          </label>

          <label className="ct-field">
            <span>Sheet GID</span>
            <input value={draft.sheet_gid ?? ""} onChange={(event) => update("sheet_gid", event.target.value || null)} />
          </label>

          <section
            className="ct-drawer-details"
            data-open={showFunnelDetails ? "true" : "false"}
            onClick={(event) => {
              const target = event.target as Element;
              if (target === event.currentTarget || target.closest(".ct-drawer-details-summary")) {
                setShowFunnelDetails((open) => !open);
              }
            }}
          >
            <button
              type="button"
              className="ct-drawer-details-summary"
              aria-expanded={showFunnelDetails}
            >
              Funnel details
              <span>Copy, pricing, routing</span>
            </button>
            <div className="ct-drawer-details-body">
              <div className="ct-field-grid">
                <label className="ct-field">
                  <span>Offer Price USD</span>
                  <input type="number" min="0" value={draft.offer_price_usd} onChange={(event) => update("offer_price_usd", Number(event.target.value) || 0)} />
                </label>
                <label className="ct-field">
                  <span>Payment Model</span>
                  <select value={draft.offer_payment_model} onChange={(event) => update("offer_payment_model", event.target.value as FunnelDefinition["offer_payment_model"])}>
                    <option value="monthly">Monthly</option>
                    <option value="one_time">One time</option>
                    <option value="custom">Custom</option>
                  </select>
                </label>
              </div>

              <label className="ct-field">
                <span>Offer Summary</span>
                <textarea value={draft.offer_summary} onChange={(event) => update("offer_summary", event.target.value)} rows={3} />
              </label>

              <div className="ct-field-grid">
                <label className="ct-field">
                  <span>Offer Version</span>
                  <input value={draft.offer_version} onChange={(event) => update("offer_version", event.target.value)} />
                </label>
                <label className="ct-field">
                  <span>Campaign Count</span>
                  <input type="number" min="0" value={draft.default_campaign_count} onChange={(event) => update("default_campaign_count", Number(event.target.value) || 0)} />
                </label>
              </div>

              <div className="ct-field-grid">
                <label className="ct-field">
                  <span>Daily Ad Budget USD</span>
                  <input
                    type="number"
                    min="0"
                    value={draft.default_daily_ad_budget_usd ?? ""}
                    onChange={(event) => update("default_daily_ad_budget_usd", event.target.value ? Number(event.target.value) : null)}
                  />
                </label>
                <label className="ct-field ct-field-toggle">
                  <span>Website Included</span>
                  <div className="ct-toggle-row">
                    <input type="checkbox" checked={draft.offer_includes_website} onChange={(event) => update("offer_includes_website", event.target.checked)} />
                    <p className="ct-field-hint">Used by the bot and future campaign briefs.</p>
                  </div>
                </label>
              </div>

              <div className="ct-field-grid">
                <label className="ct-field">
                  <span>Sheet Poll Seconds</span>
                  <input type="number" min="30" value={draft.sheet_poll_seconds} onChange={(event) => update("sheet_poll_seconds", Number(event.target.value) || 30)} />
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
                label="Operator Ping Template"
                value={draft.manual_ping_template_name ?? ""}
                text={draft.manual_ping_text}
                choices={templateChoices}
                onChange={(value) => updateTemplateChoice("manual_ping_template_name", "manual_ping_text", value)}
              />
              <label className="ct-field">
                <span>Operator Ping Text</span>
                <textarea value={draft.manual_ping_text} onChange={(event) => update("manual_ping_text", event.target.value)} rows={3} />
              </label>

              <label className="ct-field">
                <span>Pre-offer Text</span>
                <textarea value={draft.loom_intro_text} onChange={(event) => update("loom_intro_text", event.target.value)} rows={4} />
              </label>

              {videoStrategy ? (
                <label className="ct-field">
                  <span>MP4 Path</span>
                  <input value={videoStrategy.media_path ?? ""} onChange={(event) => updateStrategyMediaPath(event.target.value)} />
                </label>
              ) : null}

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
                <span>Offer Check Text</span>
                <input value={draft.video_check_text} onChange={(event) => update("video_check_text", event.target.value)} />
              </label>

              <label className="ct-field">
                <span>Meeting URL</span>
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
          </section>

          <label className="ct-field">
            <span>Primary Offer Text</span>
            <textarea value={primaryStrategy?.message_text ?? ""} onChange={(event) => updateStrategyMessageText(primaryStrategy?.id, event.target.value)} rows={4} />
          </label>

          <label className="ct-field">
            <span>Meeting Text</span>
            <textarea value={draft.calendly_intro_text} onChange={(event) => update("calendly_intro_text", event.target.value)} rows={4} />
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
  hasActiveFilters,
  onClearFilters,
  onSelect,
  onToggleSelected,
}: {
  leads: LeadSummary[];
  selectedLeadId: string | null;
  selectedLeadIds: string[];
  inboxMode: boolean;
  loading: boolean;
  hasActiveFilters: boolean;
  onClearFilters: () => void;
  onSelect: (leadId: string) => void;
  onToggleSelected: (leadId: string) => void;
}) {
  const selectedLeadIdSet = useMemo(() => new Set(selectedLeadIds), [selectedLeadIds]);

  if (loading && !leads.length) {
    return (
      <div className="ct-leads-list">
        <CtEmptyState loading title="Loading leads" message="Fetching the current queue." />
      </div>
    );
  }

  if (!leads.length) {
    return (
      <div className="ct-leads-list">
        <CtEmptyState
          title={hasActiveFilters ? "No visible leads" : "No leads loaded"}
          message={hasActiveFilters ? "Clear filters to return to the full queue." : "Refresh after the next sheet sync."}
          action={hasActiveFilters ? (
            <button type="button" className="ct-btn ct-btn-ghost" onClick={onClearFilters}>
              Clear filters
            </button>
          ) : null}
        />
      </div>
    );
  }

  return (
    <div className="ct-leads-list">
      {leads.map((lead) => {
        const tone = leadTone(lead);
        const turn = manualTurn(lead);
        const checked = selectedLeadIdSet.has(lead.id);
        const hasOutboundError = (lead.outbound_error_count || 0) > 0;
        return (
          <div
            className={`ct-lead-row ${lead.id === selectedLeadId ? "active" : ""} ${checked ? "selected" : ""} ${hasOutboundError ? "has-error" : ""}`}
            data-tone={tone}
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
                  <span className="ct-lead-time">{relativeTime(lastInteractionAt(lead))}</span>
                </div>
                {turn || hasOutboundError ? (
                  <div className="ct-lead-status-line">
                    {turn ? <span className={`ct-lead-turn ${turn}`}>{turn === "needs_reply" ? "Needs reply" : "Answered"}</span> : null}
                    {hasOutboundError ? (
                      <span className="ct-lead-delivery-error" title={lead.latest_outbound_error || "WhatsApp delivery failed"}>
                        <WarningCircle size={13} weight="fill" />
                        Send failed
                      </span>
                    ) : null}
                  </div>
                ) : null}
                <div className="ct-lead-meta">
                  <LeadCountryLabel phone={lead.phone || lead.normalized_phone} />
                </div>
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
  onMarkConverted,
  onPauseAutomation,
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
  onMarkConverted: () => void;
  onPauseAutomation: () => void;
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
  const closed = isLeadClosed(lead);
  const archived = isLeadArchived(lead);
  const convertedMilestone = isLeadConverted(lead);
  const crmOutboundBlocked = closed || archived || convertedMilestone;
  const paused = Boolean(lead?.automation_paused);
  const canMarkAnswered = lead?.manual_reply_status === "needs_reply" && !closed;
  const hasWorkstationClient = Boolean(lead?.workstation_client_id);
  const detailContactParts = lead
    ? [lead.phone || lead.normalized_phone, lead.email].filter(Boolean)
    : [];
  const showBuildPrimary = Boolean(lead && (hasWorkstationClient || convertedMilestone));

  return (
    <header className="ct-detail-head">
      <div className="ct-detail-head-main">
        <div className="ct-detail-avatar">{lead ? monogram(lead.full_name || lead.phone || "CT") : "CT"}</div>
        <div className="ct-detail-head-copy">
          <p className="ct-detail-kicker">{lead ? (inboxMode ? "Inbox" : formatLeadStatusLabel(lead)) : "Select a lead"}</p>
          <h3>{lead?.full_name || lead?.phone || "No lead selected"}</h3>
          <p className="ct-detail-meta">
            {lead ? (
              <>
                <PhoneCountryFlag phone={lead.phone || lead.normalized_phone} />
                <span>{detailContactParts.length ? detailContactParts.join(" · ") : "No contact info"}</span>
              </>
            ) : "Pick a lead."}
          </p>
        </div>
      </div>
      <div className="ct-detail-head-actions">
        {showBuildPrimary && hasWorkstationClient && lead?.workstation_client_id ? (
          <button
            type="button"
            className="ct-btn ct-btn-primary"
            disabled={Boolean(actionBusy)}
            onClick={() => onOpenWorkstation(lead.workstation_client_id || "")}
          >
            <FolderOpen size={15} weight="bold" />
            Open workspace
          </button>
        ) : showBuildPrimary ? (
          <button
            type="button"
            className="ct-btn ct-btn-primary"
            disabled={!lead || closed || archived || Boolean(actionBusy)}
            onClick={onConvert}
          >
            <Robot size={15} weight="bold" />
            Create workspace
          </button>
        ) : (
          <button type="button" className="ct-btn ct-btn-primary" disabled={!lead || crmOutboundBlocked || Boolean(actionBusy)} onClick={onOpenSend}>
            <PaperPlaneTilt size={15} weight="bold" />
            Send
          </button>
        )}
        <details className="ct-action-menu">
          <summary className="ct-btn ct-btn-ghost">More</summary>
          <div className="ct-action-menu-panel">
            <div className="ct-action-menu-group">
              <span className="ct-action-menu-label">Client</span>
              {!showBuildPrimary ? (
                <button
                  type="button"
                  className="ct-btn ct-btn-ghost"
                  disabled={!lead || closed || archived || Boolean(actionBusy)}
                  onClick={onConvert}
                >
                  <CurrencyDollar size={15} weight="bold" />
                  Start build
                </button>
              ) : null}
              {!hasWorkstationClient ? (
                <button
                  type="button"
                  className="ct-btn ct-btn-ghost"
                  disabled={!lead || Boolean(actionBusy)}
                  onClick={onStartSoloPage}
                >
                  <Robot size={15} weight="bold" />
                  Start solo page
                </button>
              ) : null}
              {!inboxMode && !convertedMilestone ? (
                <button type="button" className="ct-btn ct-btn-ghost" disabled={!lead || closed || Boolean(actionBusy)} onClick={onMarkConverted}>
                  <CheckCircle size={15} weight="bold" />
                  Mark as converted
                </button>
              ) : null}
            </div>

            <div className="ct-action-menu-group">
              <span className="ct-action-menu-label">Automation</span>
              {!inboxMode ? (
                <button type="button" className="ct-btn ct-btn-ghost" disabled={!lead || closed || paused || Boolean(actionBusy)} onClick={onPauseAutomation}>
                  <PauseCircle size={15} weight="bold" />
                  Pause automation
                </button>
              ) : null}
              {!inboxMode ? (
                <button type="button" className="ct-btn ct-btn-ghost" disabled={!lead || closed || paused || Boolean(actionBusy)} onClick={onManualHandoff}>
                  <NotePencil size={15} weight="bold" />
                  Operator review
                </button>
              ) : null}
              {canMarkAnswered && !inboxMode ? (
                <button type="button" className="ct-btn ct-btn-ghost" disabled={Boolean(actionBusy)} onClick={onMarkAnswered}>
                  <Check size={15} weight="bold" />
                  Mark answered
                </button>
              ) : null}
            </div>

            <div className="ct-action-menu-group">
              <span className="ct-action-menu-label">Utilities</span>
              <button type="button" className="ct-btn ct-btn-ghost" disabled={!lead} onClick={onCopyContext} title="Copy context">
                <Copy size={15} weight="bold" />
                Copy context
              </button>
            </div>

            <div className="ct-action-menu-group">
              <span className="ct-action-menu-label">Danger</span>
              <button type="button" className={`ct-btn ct-btn-ghost ${closed ? "" : "btn-destructive"}`} disabled={!lead || Boolean(actionBusy)} onClick={onToggleClosed}>
                {closed ? "Reopen lead" : "Close lead"}
              </button>
              <button type="button" className="ct-btn ct-btn-ghost btn-destructive" disabled={!lead || Boolean(actionBusy)} onClick={onDelete}>Delete lead</button>
            </div>
          </div>
        </details>
        {copyStatus ? <span className="ct-lead-copy-status" aria-live="polite">{copyStatus}</span> : null}
      </div>
    </header>
  );
}

function leadPauseDetail(lead: LeadSummary): string {
  const reason = (lead.automation_paused_reason || "").trim();
  if (!reason) {
    return "The bot won't send anything while automation is paused.";
  }
  if (reason === "booking_details_collected") {
    return "Meeting details collected. Operator should confirm the invite.";
  }
  if (reason === "meeting_scheduled") {
    return "Meeting scheduled. CRM follow-up is paused.";
  }
  if (reason.startsWith("manual_")) {
    return `Paused by operator (${humanize(reason)}).`;
  }
  return `Waiting for operator (${humanize(reason)}).`;
}

function PausedBanner({ lead }: {
  lead: LeadSummary | null;
}) {
  const closed = isLeadClosed(lead);
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
            : leadPauseDetail(lead)}
        </span>
      </div>
    </div>
  );
}

function CampaignRoutingPanel({
  lead,
  funnels,
  busy,
  onRoute,
}: {
  lead: LeadSummary | null;
  funnels: FunnelDefinition[];
  busy: boolean;
  onRoute: (campaignId: string, handoffPoint: LeadStage) => Promise<void>;
}) {
  const campaignFunnels = funnels.filter((funnel) => funnel.kind !== "inbox");
  const [targetCampaignId, setTargetCampaignId] = useState(campaignFunnels[0]?.id ?? "contadores");
  const [handoffPoint, setHandoffPoint] = useState<LeadStage>("needs_human");

  useEffect(() => {
    setTargetCampaignId((current) => (
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
    await onRoute(targetCampaignId, handoffPoint);
  }

  return (
    <form className="ct-route-panel" onSubmit={submit}>
      <div>
        <strong>Route to campaign</strong>
        <span>Choose the destination and where the operator should pick up.</span>
      </div>
      <label className="ct-field">
        <span>Campaign</span>
        <select value={targetCampaignId} onChange={(event) => setTargetCampaignId(event.target.value)}>
          {campaignFunnels.map((funnel) => (
            <option value={funnel.id} key={funnel.id}>{funnel.label}</option>
          ))}
        </select>
      </label>
      <label className="ct-field">
        <span>Handoff point</span>
        <select value={handoffPoint} onChange={(event) => setHandoffPoint(event.target.value as LeadStage)}>
          {campaignRouteOptions.map((option) => (
            <option value={option.value} key={option.value}>{option.label}</option>
          ))}
        </select>
      </label>
      <button type="submit" className="ct-btn ct-btn-primary" disabled={busy || !campaignFunnels.length}>
        {busy ? "Routing..." : "Route chat"}
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
  const timelineRef = useScrollChatToLatestMessage(messages, hasLead);

  if (!hasLead) {
    return <CtEmptyState compact title="Select a lead" message="Pick a lead to see the conversation." />;
  }
  if (loading && !messages.length) {
    return <CtEmptyState compact loading title="Loading messages" message="Fetching WhatsApp history." />;
  }
  if (!messages.length) {
    return <CtEmptyState compact title="No messages yet" message="Conversation history will appear here." />;
  }

  return (
    <div className="ct-timeline" ref={timelineRef}>
      {messages.map((message, index) => {
        const previousMessage = messages[index - 1] ?? null;
        const nextMessage = messages[index + 1] ?? null;
        const direction = message.from_me ? "outbound" : "inbound";
        const deliveryStatus = String(message.delivery_status || "").toLowerCase();
        const hasDeliveryError = message.from_me && deliveryStatus === "failed";
        const errorAcknowledged = Boolean(message.delivery_error_acknowledged_at);
        const needsDeliveryErrorAck = hasDeliveryError && !errorAcknowledged;
        const acknowledging = acknowledgingIds.includes(message.id);
        const showDateDivider = chatDayKey(previousMessage?.created_at) !== chatDayKey(message.created_at);
        const groupedWithPrevious = Boolean(
          previousMessage
            && previousMessage.from_me === message.from_me
            && !showDateDivider
            && chatMinutesBetween(previousMessage.created_at, message.created_at) <= 8,
        );
        const groupedWithNext = Boolean(
          nextMessage
            && nextMessage.from_me === message.from_me
            && chatDayKey(nextMessage.created_at) === chatDayKey(message.created_at)
            && chatMinutesBetween(message.created_at, nextMessage.created_at) <= 8,
        );
        const meta = [
          chatTimeLabel(message.created_at),
          chatDeliveryLabel(message),
        ].filter(Boolean);
        return (
          <div className="crm-message-group" key={message.id}>
            {showDateDivider ? (
              <div className="crm-message-date">{chatDayLabel(message.created_at)}</div>
            ) : null}
            <div className={`crm-message-shell ${direction} ${groupedWithPrevious ? "grouped-prev" : ""} ${groupedWithNext ? "grouped-next" : ""}`}>
              <article
                className={`crm-message-card ${direction} ${deliveryStatus === "undelivered" ? "pending" : ""} ${needsDeliveryErrorAck ? "failed" : ""} ${errorAcknowledged ? "acknowledged" : ""}`}
              >
                <MessageMedia message={message} />
                {message.text ? <p className="crm-message-body">{message.text}</p> : null}
                <footer className="crm-message-meta">
                  <span className="crm-message-meta-line">{meta.join(" · ")}</span>
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
                </footer>
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
          </div>
        );
      })}
    </div>
  );
}

function chatDayKey(value: string | null | undefined): string {
  if (!value) {
    return "";
  }
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) {
    return value;
  }
  return `${date.getFullYear()}-${date.getMonth() + 1}-${date.getDate()}`;
}

function chatDayLabel(value: string | null | undefined): string {
  if (!value) {
    return "";
  }
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) {
    return value;
  }
  return new Intl.DateTimeFormat("en", { month: "short", day: "2-digit" }).format(date);
}

function chatTimeLabel(value: string | null | undefined): string {
  if (!value) {
    return "";
  }
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) {
    return shortDate(value);
  }
  return new Intl.DateTimeFormat("en", { hour: "numeric", minute: "2-digit" }).format(date);
}

function chatMinutesBetween(first: string | null | undefined, second: string | null | undefined): number {
  const firstDate = first ? new Date(first) : null;
  const secondDate = second ? new Date(second) : null;
  if (!firstDate || !secondDate || Number.isNaN(firstDate.getTime()) || Number.isNaN(secondDate.getTime())) {
    return Number.POSITIVE_INFINITY;
  }
  return Math.abs(secondDate.getTime() - firstDate.getTime()) / 60000;
}

function chatDeliveryLabel(message: MessageItem): string {
  if (!message.from_me || !message.delivery_status) {
    return "";
  }
  return humanize(message.delivery_status);
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
        <span className="ct-manual-lock">Operator outbound</span>
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
  const [showAdvancedControls, setShowAdvancedControls] = useState(false);

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
            <p className="ct-drawer-kicker">Runtime</p>
            <h3 id="ctDrawerTitle">Automation controls</h3>
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
          <section
            className="ct-drawer-details"
            data-open={showAdvancedControls ? "true" : "false"}
            onClick={(event) => {
              const target = event.target as Element;
              if (target === event.currentTarget || target.closest(".ct-drawer-details-summary")) {
                setShowAdvancedControls((open) => !open);
              }
            }}
          >
            <button
              type="button"
              className="ct-drawer-details-summary"
              aria-expanded={showAdvancedControls}
            >
              Advanced controls
              <span>Meeting, alerts, weights</span>
            </button>
            <div className="ct-drawer-details-body">
              <label className="ct-field">
                <span>Meeting URL</span>
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
          </section>
        </div>
        <footer className="ct-drawer-foot">
          <button type="submit" className="ct-btn ct-btn-primary" disabled={saving || !config}>{saving ? "Saving..." : "Save controls"}</button>
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
              <span>{formatRate(item.meeting_rate ?? item.calendly_rate)} meeting</span>
              <span>{formatRate(item.conversion_rate ?? item.booked_rate)} converted</span>
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
      <form className="ct-modal-panel ct-send-panel" role="dialog" aria-modal="true" aria-labelledby="ctSendModalTitle" onSubmit={onSubmit}>
        <header className="ct-modal-head">
          <h3 id="ctSendModalTitle">Send message</h3>
          <button type="button" className="ct-icon-btn" onClick={onClose}>Close</button>
        </header>
        <div className="ct-modal-body">
          <p className="ct-modal-warning">
	            <strong>Heads up:</strong> {pausesAutomation ? "sending this pauses the bot for this lead. You can resume automation after." : "sending a meeting link marks the lead as meeting sent and keeps it in operator review."}
          </p>

          <fieldset className="ct-send-options">
            <legend className="ct-sr-only">Message type</legend>
            {availableOptions.map((option) => {
              const isDisabled = option.value === "custom" && customBlocked;

              return (
                <label className="ct-send-option" data-selected={kind === option.value} data-disabled={isDisabled} key={option.value}>
                  <input
                    type="radio"
                    name="ctSendKind"
                    value={option.value}
                    disabled={isDisabled}
                    checked={kind === option.value}
                    onChange={() => onKindChange(option.value)}
                  />
                  <div>
                    <strong>{option.title}</strong>
                    <span>{option.value === "custom" && customBlockReason ? customBlockReason : sendOptionPreview(option.value, funnel) || option.help}</span>
                  </div>
                </label>
              );
            })}
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
            {busy ? "Sending..." : pausesAutomation ? "Send and pause automation" : "Send and mark meeting sent"}
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
  hiddenSelectedCount,
  customBlockedCount,
  closedCount,
  convertedCount,
  archivedCount,
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
  hiddenSelectedCount: number;
  customBlockedCount: number;
  closedCount: number;
  convertedCount: number;
  archivedCount: number;
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
  const convertedBlocked = convertedCount > 0 && kind !== "set-tags";
  const archivedBlocked = archivedCount > 0 && kind !== "set-tags";
  const bulkOutboundBlocked = closedBlocked || convertedBlocked || archivedBlocked;
  const bulkOutboundReasons = [
    ...(closedCount > 0
      ? [`${closedCount} selected lead${closedCount === 1 ? " is" : "s are"} closed. Reopen before sending WhatsApp messages.`]
      : []),
    ...(convertedCount > 0
      ? [
          `${convertedCount} selected lead${convertedCount === 1 ? " is" : "s are"} converted. Use Workstation delivery instead of CRM follow-up messages.`,
        ]
      : []),
    ...(archivedCount > 0
      ? [`${archivedCount} selected lead${archivedCount === 1 ? " is" : "s are"} archived. Unarchive before sending WhatsApp messages.`]
      : []),
  ];
  const manualPingNeedsConfirmation = kind === "send-manual-ping" && !manualPingConfirmed;

  return (
    <div className="ct-modal open" aria-hidden="false">
      <button className="ct-modal-overlay" type="button" onClick={onClose} aria-label="Close bulk action" />
      <form className="ct-modal-panel ct-send-panel" role="dialog" aria-modal="true" aria-labelledby="ctBulkSendModalTitle" onSubmit={onSubmit}>
        <header className="ct-modal-head">
          <div>
            <h3 id="ctBulkSendModalTitle">Bulk action</h3>
            <p className="ct-modal-subtitle">
              {selectedCount} selected in this list
              {hiddenSelectedCount ? ` · ${hiddenSelectedCount} outside this view ignored` : ""}
            </p>
          </div>
          <button type="button" className="ct-icon-btn" onClick={onClose}>Close</button>
        </header>
        <div className="ct-modal-body">
          <p className="ct-modal-warning">
            <strong>Heads up:</strong> this will apply to every selected chat in the current list.
            {bulkOutboundBlocked
              ? ` ${bulkOutboundReasons.join(" ")}`
              : kind === "set-tags"
              ? " Tags will be replaced for those leads."
              : pausesAutomation
                ? " Sending this pauses automation for those leads."
	                : " Sending a meeting link marks them as meeting sent and keeps them in operator review."}
          </p>

          <fieldset className="ct-send-options">
            <legend className="ct-sr-only">Bulk action type</legend>
            {availableOptions.map((option) => {
              const isDisabled = (option.value !== "set-tags" && bulkOutboundBlocked) || (option.value === "custom" && customBlocked);

              return (
                <label className="ct-send-option" data-selected={kind === option.value} data-disabled={isDisabled} key={option.value}>
                  <input
                    type="radio"
                    name="ctBulkSendKind"
                    value={option.value}
                    disabled={isDisabled}
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
              );
            })}
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
	            <span>I explicitly want to send the follow-up ping to every selected chat.</span>
          </label>
        </div>
        <footer className="ct-modal-foot">
          <button type="button" className="ct-btn ct-btn-ghost" onClick={onClose}>Cancel</button>
          <button
            type="submit"
            className="ct-btn ct-btn-primary"
            disabled={busy || !selectedCount || bulkOutboundBlocked || manualPingNeedsConfirmation || (kind === "custom" && (customBlocked || !text.trim())) || (kind === "set-tags" && !tagValues.length)}
          >
            {busy ? "Applying..." : `Apply to ${selectedCount}`}
          </button>
        </footer>
      </form>
    </div>
  );
}

function buildBlankClientLeadSourceDraft(): ClientLeadSourceDraft {
  return {
    id: "nuevo-cliente",
    label: "Nuevo cliente",
    enabled: false,
    sheet_url: "",
    sheet_gid: "",
    sheet_tab_name: "",
    sheet_poll_seconds: 10,
    recipient_name: "",
    recipient_phone: "",
    template_name: "konecta_client_lead_alert_es_v2",
    template_language: "es",
    column_mapping_text: JSON.stringify({
      source_id: "id",
      created_time: "created_time",
      full_name: "full_name",
      phone_number: "phone_number",
      email: "email",
    }, null, 2),
    context_field_mapping_text: "{}",
  };
}

function clientLeadSourceToDraft(source: ClientLeadSource): ClientLeadSourceDraft {
  return {
    id: source.id,
    label: source.label,
    enabled: source.enabled,
    sheet_url: source.sheet_url ?? "",
    sheet_gid: source.sheet_gid ?? "",
    sheet_tab_name: source.sheet_tab_name ?? "",
    sheet_poll_seconds: source.sheet_poll_seconds || 10,
    recipient_name: source.recipient_name ?? "",
    recipient_phone: source.recipient_phone ?? "",
    template_name: source.template_name ?? "",
    template_language: source.template_language ?? "es",
    column_mapping_text: JSON.stringify(source.column_mapping ?? {}, null, 2),
    context_field_mapping_text: JSON.stringify(source.context_field_mapping ?? {}, null, 2),
  };
}

function clientLeadSourcePayloadFromDraft(draft: ClientLeadSourceDraft): ClientLeadSourceMutationPayload {
  const id = slugifyClient(draft.id || draft.label);
  const label = draft.label.trim() || id;
  return {
    id,
    label,
    enabled: draft.enabled,
    sheet_url: draft.sheet_url.trim() || null,
    sheet_gid: draft.sheet_gid.trim() || null,
    sheet_tab_name: draft.sheet_tab_name.trim() || null,
    sheet_poll_seconds: Math.max(5, Number(draft.sheet_poll_seconds) || 10),
    recipient_name: draft.recipient_name.trim() || null,
    recipient_phone: draft.recipient_phone.trim() || null,
    template_name: draft.template_name.trim() || null,
    template_language: draft.template_language.trim() || null,
    column_mapping: parseClientLeadColumnMapping(draft.column_mapping_text),
    context_field_mapping: parseClientLeadColumnMapping(draft.context_field_mapping_text),
  };
}

function validateClientLeadSourceDraft(draft: ClientLeadSourceDraft): ClientLeadSourceDraftValidation {
  const fields: Partial<Record<ClientLeadSourceDraftField, string>> = {};
  const messages: string[] = [];

  function add(field: ClientLeadSourceDraftField, message: string) {
    fields[field] = message;
    messages.push(message);
  }

  const id = slugifyClient(draft.id || draft.label);
  if (!id) {
    add("id", "Source ID is required.");
  }
  if (!draft.label.trim()) {
    add("label", "Label is required.");
  }
  if (!draft.recipient_name.trim()) {
    add("recipient_name", "Recipient name is required.");
  }

  const recipientDigits = draft.recipient_phone.replace(/\D/g, "");
  if (!recipientDigits || recipientDigits.length < 6) {
    add("recipient_phone", "Recipient phone needs at least 6 digits.");
  }

  const sheetUrl = draft.sheet_url.trim();
  if (!sheetUrl) {
    add("sheet_url", "Paste the Google Sheet URL.");
  } else if (!/^https?:\/\//i.test(sheetUrl)) {
    add("sheet_url", "Use a valid http(s) sheet URL.");
  }

  if ((Number(draft.sheet_poll_seconds) || 0) < 5) {
    add("sheet_poll_seconds", "Poll interval must be 5 seconds or more.");
  }

  const contextFieldsError = validateJsonObjectText(draft.context_field_mapping_text, "Context fields");
  if (contextFieldsError) {
    add("context_field_mapping_text", contextFieldsError);
  }

  const columnMappingError = validateJsonObjectText(draft.column_mapping_text, "Column mapping");
  if (columnMappingError) {
    add("column_mapping_text", columnMappingError);
  }

  return {
    canSave: messages.length === 0,
    fields,
    messages,
    summary: messages[0] ?? "Ready to save.",
  };
}

function validateJsonObjectText(value: string, label: string): string | null {
  if (!value.trim()) {
    return null;
  }
  try {
    const parsed = JSON.parse(value) as unknown;
    if (!parsed || typeof parsed !== "object" || Array.isArray(parsed)) {
      return `${label} must be a JSON object.`;
    }
    return null;
  } catch {
    return `${label} must be valid JSON.`;
  }
}

function parseClientLeadColumnMapping(value: string): Record<string, string> {
  if (!value.trim()) {
    return {};
  }
  const parsed = JSON.parse(value) as unknown;
  if (!parsed || typeof parsed !== "object" || Array.isArray(parsed)) {
    throw new Error("Column mapping must be a JSON object.");
  }
  return Object.fromEntries(
    Object.entries(parsed).map(([key, rawValue]) => [key, String(rawValue ?? "").trim()]).filter(([, rawValue]) => rawValue),
  );
}

function unpackClientLeadSources(payload: ClientLeadSourceListResponse | ClientLeadSource[]): ClientLeadSource[] {
  return Array.isArray(payload) ? payload : payload.sources ?? [];
}

function unpackClientLeads(payload: ClientLeadListResponse | ClientLead[]): ClientLead[] {
  return Array.isArray(payload) ? payload : payload.leads ?? [];
}

type DeliveryTone = "success" | "warn" | "danger" | "muted" | "accent";

type DeliveryContactGroup = {
  key: string;
  label: string;
  recipientName: string;
  recipientPhone: string;
  sources: ClientLeadSource[];
  primarySource: ClientLeadSource;
  total: number;
  delivered: number;
  blocked: number;
  failed: number;
  issues: number;
};

type DeliverySheetLeadSection = {
  source: ClientLeadSource;
  leads: ClientLead[];
};

function buildDeliveryContactGroups(sources: ClientLeadSource[]): DeliveryContactGroup[] {
  const groups = new Map<string, ClientLeadSource[]>();
  for (const source of sources.slice().sort(compareDeliverySources)) {
    const key = deliveryContactKey(source);
    groups.set(key, [...(groups.get(key) ?? []), source]);
  }

  return Array.from(groups.entries())
    .map(([key, groupSources]) => {
      const sortedSources = groupSources.slice().sort(compareDeliverySources);
      const primarySource = pickPrimaryDeliverySource(sortedSources);
      const total = sortedSources.reduce((count, source) => count + deliverySourceCount(source, "total"), 0);
      const delivered = sortedSources.reduce((count, source) => count + deliverySourceCount(source, "sent") + deliverySourceCount(source, "delivered"), 0);
      const blocked = sortedSources.reduce((count, source) => count + deliverySourceCount(source, "blocked"), 0);
      const failed = sortedSources.reduce((count, source) => count + deliverySourceCount(source, "failed"), 0);
      const sourceFailures = sortedSources.filter((source) => String(source.last_sync_status || "").toLowerCase() === "failed").length;
      return {
        key,
        label: deliveryContactLabel(sortedSources),
        recipientName: primarySource.recipient_name ?? "",
        recipientPhone: primarySource.recipient_phone ?? "",
        sources: sortedSources,
        primarySource,
        total,
        delivered,
        blocked,
        failed,
        issues: sourceFailures + blocked + failed,
      };
    })
    .sort((left, right) => left.label.localeCompare(right.label) || left.key.localeCompare(right.key));
}

function buildDeliverySheetLeadSections(
  sources: ClientLeadSource[],
  visibleLeads: ClientLead[],
  selectedSheetId: string,
): DeliverySheetLeadSection[] {
  const leadsBySource = new Map<string, ClientLead[]>();
  for (const lead of visibleLeads) {
    leadsBySource.set(lead.source_id, [...(leadsBySource.get(lead.source_id) ?? []), lead]);
  }

  return sources
    .filter((source) => selectedSheetId === "all" || source.id === selectedSheetId)
    .map((source) => {
      const sourceLeads = (leadsBySource.get(source.id) ?? []).slice().sort(compareClientLeads);
      return {
        source,
        leads: sourceLeads,
      };
    })
    .filter((section) => section.leads.length > 0);
}

type DeliveryRawField = {
  label: string;
  value: string;
};

function deliveryRawFields(lead: ClientLead): DeliveryRawField[] {
  const fields: DeliveryRawField[] = [];
  const seen = new Set<string>();
  for (const [rawKey, rawValue] of Object.entries(lead.raw_row ?? {})) {
    const label = String(rawKey || "").trim();
    if (!label || seen.has(label)) {
      continue;
    }
    seen.add(label);
    fields.push({ label, value: formatRawValue(rawValue).trim() });
  }
  return fields;
}

function deliveryContactSourceIdsFor(sources: ClientLeadSource[], selectedSourceId: string | null): string[] {
  if (!selectedSourceId) {
    return [];
  }
  const selected = sources.find((source) => source.id === selectedSourceId);
  if (!selected) {
    return [];
  }
  const key = deliveryContactKey(selected);
  return sources
    .filter((source) => deliveryContactKey(source) === key)
    .sort(compareDeliverySources)
    .map((source) => source.id);
}

function deliveryContactKey(source: ClientLeadSource): string {
  return source.normalized_recipient_phone || source.recipient_phone?.replace(/\D/g, "") || source.recipient_phone || source.id;
}

function deliveryContactLabel(sources: ClientLeadSource[]): string {
  const labels = sources.map((source) => deliverySourceBaseLabel(source)).filter(Boolean);
  return labels[0] || sources[0]?.recipient_name || sources[0]?.label || sources[0]?.id || "Delivery contact";
}

function deliverySourceBaseLabel(source: ClientLeadSource): string {
  return (source.label || source.recipient_name || source.id).split(" · ")[0]?.trim() || source.label || source.id;
}

function deliverySheetLabel(source: ClientLeadSource): string {
  const parts = (source.label || "").split(" · ").map((part) => part.trim()).filter(Boolean);
  return parts.length > 1 ? parts.slice(1).join(" · ") : source.sheet_tab_name || source.sheet_gid || "Main sheet";
}

function compareDeliverySources(left: ClientLeadSource, right: ClientLeadSource): number {
  return (
    deliverySourceBaseLabel(left).localeCompare(deliverySourceBaseLabel(right))
    || deliverySheetLabel(left).localeCompare(deliverySheetLabel(right))
    || left.id.localeCompare(right.id)
  );
}

function pickPrimaryDeliverySource(sources: ClientLeadSource[]): ClientLeadSource {
  return sources.find((source) => deliverySourceTone(source) !== "danger")
    ?? sources.find((source) => source.enabled)
    ?? sources[0];
}

function deliveryContactTone(group: DeliveryContactGroup): DeliveryTone {
  if (!group.sources.some((source) => source.enabled)) {
    return "muted";
  }
  if (group.sources.some((source) => deliverySourceTone(source) === "danger") || group.failed > 0) {
    return "danger";
  }
  if (group.blocked > 0 || group.sources.some((source) => deliverySourceTone(source) === "warn")) {
    return "warn";
  }
  if (group.sources.every((source) => deliverySourceTone(source) === "success")) {
    return "success";
  }
  return "accent";
}

function deliveryContactStatusLabel(group: DeliveryContactGroup): string {
  const tone = deliveryContactTone(group);
  if (tone === "danger") {
    return "Needs access";
  }
  if (tone === "warn") {
    return "Review";
  }
  if (tone === "success") {
    return "OK";
  }
  if (tone === "muted") {
    return "Paused";
  }
  return "Active";
}

function deliverySourceHasIssue(source: ClientLeadSource): boolean {
  const status = String(source.last_sync_status || "").toLowerCase();
  return status === "failed" || status === "error" || deliverySourceCount(source, "failed") > 0;
}

function deliverySourceIssueText(source: ClientLeadSource): string {
  const status = String(source.last_sync_status || "").toLowerCase();
  if (status === "failed" || status === "error") {
    return source.last_sync_note || "Sync failed";
  }
  if (deliverySourceCount(source, "failed") > 0) {
    return "Notification failed";
  }
  if (deliverySourceCount(source, "blocked") > 0) {
    return "Some leads are blocked";
  }
  return "Needs review";
}

function deliverySourceStatusIcon(source: ClientLeadSource): ReactNode {
  const tone = deliverySourceTone(source);
  if (tone === "success") {
    return <CheckCircle size={14} weight="fill" />;
  }
  if (tone === "danger") {
    return <WarningCircle size={14} weight="fill" />;
  }
  if (tone === "warn") {
    return <ClockCountdown size={14} weight="fill" />;
  }
  if (tone === "muted") {
    return <PauseCircle size={14} weight="fill" />;
  }
  return <Pulse size={14} weight="fill" />;
}

function compareClientLeads(left: ClientLead, right: ClientLead): number {
  const leftTime = left.created_time ? Date.parse(left.created_time) : 0;
  const rightTime = right.created_time ? Date.parse(right.created_time) : 0;
  if (leftTime !== rightTime) {
    return rightTime - leftTime;
  }
  return (right.row_number ?? 0) - (left.row_number ?? 0);
}

function deliverySourceCount(source: ClientLeadSource, key: keyof ClientLeadSource["counts"]): number {
  const value = source.counts?.[key] ?? 0;
  return Number.isFinite(value) ? Number(value) : 0;
}

function deliverySourceTone(source: ClientLeadSource): DeliveryTone {
  if (!source.enabled) {
    return "muted";
  }
  const status = String(source.last_sync_status || "").toLowerCase();
  if (status === "ok" || status === "success") {
    return "success";
  }
  if (status === "failed" || status === "error") {
    return "danger";
  }
  if (status === "running" || status === "syncing") {
    return "warn";
  }
  return "accent";
}

function buildClientLeadText(lead: ClientLead): string {
  const lines = [
    `Lead: ${lead.full_name || "-"}`,
    `Phone: ${displayLeadPhone(lead.phone_number)}`,
    `Email: ${lead.email || "-"}`,
    `WhatsApp: ${lead.wa_link || buildWaLink(lead.phone_number) || "-"}`,
    `Row: ${lead.row_number}`,
    `Status: ${humanize(lead.delivery_status || (lead.block_reason ? "blocked" : "pending"))}`,
  ];

  if (lead.last_delivery_error) {
    lines.push(`Error: ${lead.last_delivery_error}`);
  }
  if (lead.block_reason) {
    lines.push(`Blocked: ${lead.block_reason}`);
  }

  lines.push("", "Notification:", lead.notification_text || "-");
  return lines.join("\n");
}

function buildWaLink(phone: string | null | undefined): string {
  const digits = (phone || "").replace(/\D/g, "");
  return digits ? `https://wa.me/${digits}` : "";
}

function displayLeadPhone(phone: string | null | undefined): string {
  const value = (phone || "").trim().replace(/^p:/i, "");
  return value || "-";
}

function clientLeadAgeText(lead: ClientLead): string {
  return lead.created_time ? relativeTime(lead.created_time) : `Row ${lead.row_number}`;
}

function firstRawValue(lead: ClientLead, keys: string[]): string {
  for (const key of keys) {
    const value = lead.raw_row?.[key];
    const formatted = formatRawValue(value).trim();
    if (formatted) {
      return formatted;
    }
  }
  return "";
}

function deliveryLeadTitle(lead: ClientLead): string {
  return lead.full_name
    || firstRawValue(lead, ["Nombre", "Name", "nombre", "full_name", "Full name"])
    || displayLeadPhone(lead.phone_number)
    || `Row ${lead.row_number}`;
}

function deliveryLeadSubtitle(lead: ClientLead): string {
  const parts = [
    displayLeadPhone(lead.phone_number),
    lead.email || "",
  ].filter((part) => part && part !== "-");
  return parts.length ? parts.join(" · ") : "No mapped contact fields";
}

function deliveryStatusDetail(lead: ClientLead): string {
  if (lead.delivered_at) {
    return `Delivered ${relativeTime(lead.delivered_at)}`;
  }
  if (lead.sent_at) {
    return `Sent ${relativeTime(lead.sent_at)}`;
  }
  if (lead.block_reason) {
    return "Not sent";
  }
  if (lead.delivery_attempts > 0) {
    return `${lead.delivery_attempts} ${lead.delivery_attempts === 1 ? "attempt" : "attempts"}`;
  }
  return "Queued";
}

function recipientChatMessageDetail(message: ClientLeadRecipientChatMessage): string {
  if (message.delivered_at) {
    return `Delivered ${relativeTime(message.delivered_at)}`;
  }
  if (message.sent_at) {
    return `Sent ${relativeTime(message.sent_at)}`;
  }
  if (message.last_delivery_error) {
    return "Failed";
  }
  return message.updated_at ? `Updated ${relativeTime(message.updated_at)}` : "Queued";
}

function recipientChatMessageTone(message: ClientLeadRecipientChatMessage): "success" | "warn" | "danger" | "muted" | "accent" {
  const status = String(message.delivery_status || "").toLowerCase();
  if (status === "delivered" || status === "sent") {
    return "success";
  }
  if (status === "failed" || status === "error") {
    return "danger";
  }
  if (status === "blocked") {
    return "warn";
  }
  if (status === "skipped" || status === "cancelled") {
    return "muted";
  }
  return "accent";
}

function formatRawValue(value: unknown): string {
  if (typeof value === "string") {
    return value;
  }
  if (typeof value === "number" || typeof value === "boolean") {
    return String(value);
  }
  if (value === null || value === undefined) {
    return "";
  }
  try {
    return JSON.stringify(value);
  } catch {
    return String(value);
  }
}

function clientLeadDeliveryTone(lead: ClientLead): "success" | "warn" | "danger" | "muted" | "accent" {
  if (lead.block_reason) {
    return "warn";
  }
  const status = String(lead.delivery_status || "").toLowerCase();
  if (status === "delivered" || status === "sent") {
    return "success";
  }
  if (status === "failed" || status === "error") {
    return "danger";
  }
  if (status === "blocked") {
    return "warn";
  }
  if (status === "skipped" || status === "cancelled") {
    return "muted";
  }
  return "accent";
}

function isRetryableClientLead(lead: ClientLead): boolean {
  const status = String(lead.delivery_status || "").toLowerCase();
  return status === "failed" || status === "blocked" || Boolean(lead.last_delivery_error);
}

function buildBlankFunnel(): FunnelDefinition {
  return {
    id: "nuevo-funnel",
    label: "Nuevo Funnel",
    kind: "campaign",
    enabled: false,
    offer_version: "mission-2026-05-30",
    offer_price_usd: 599,
    offer_payment_model: "monthly",
    offer_summary: "Marketing y anuncios para recibir interesados directo al WhatsApp; sitio incluido si hace falta.",
    offer_includes_website: true,
    default_campaign_count: 3,
    default_daily_ad_budget_usd: null,
    sheet_url: null,
    sheet_gid: null,
    sheet_source_filter: null,
    sheet_poll_seconds: 30,
    template_language: "es",
    opener_text: "Hola, completaste el formulario sobre como podemos ayudarte. Es correcto?",
    opener_template_name: null,
    opener_followup_text: "Queria compartirte informacion sobre la propuesta que viste en el anuncio.",
    opener_followup_template_name: null,
    manual_ping_text: "Hola, queria saber en que situacion quedamos y si queres que retomemos la conversacion",
    manual_ping_template_name: null,
    loom_intro_text: "",
    loom_url: "",
    video_check_text: "te interesa que lo veamos en una llamada corta?",
    calendly_intro_text: "Para avanzar, el siguiente paso es elegir un horario en el calendario:",
    calendly_base_url: "",
    alert_emails: [],
    whatsapp_referral_source_ids: [],
    initial_reply_quiet_seconds: 30,
    post_loom_min_seconds: 600,
    post_loom_quiet_seconds: 30,
    strategies: [
      {
        step: "loom",
        id: "text_offer_599",
        label: "Text offer 599",
        weight: 100,
        delivery: "text",
        sequence_step: "text_offer",
        message_text: "Son 599 USD mensuales. A cambio recibis oportunidades de clientes potenciales directo a tu WhatsApp. Eso lo logramos con una pagina profesional y campanas enfocadas. Si te interesa, lo vemos en una llamada corta y revisamos si tiene sentido para tu caso.",
        media_type: null,
        media_path: null,
        media_caption: null,
      },
    ],
  };
}

function buildFunnelSetupIssues(funnel: FunnelDefinition | null): string[] {
  if (!funnel) {
    return ["Create or select one campaign funnel."];
  }
  if (funnel.kind === "inbox") {
    return [];
  }

  const checks = buildFunnelReadyItems(funnel);
  return checks.filter((item) => !item.ready).map((item) => `${item.label}.`);
}

function buildFunnelReadyItems(
  funnel: FunnelDefinition,
): Array<{ label: string; ready: boolean }> {
  const textStrategy = funnel.strategies.find((strategy) => strategy.delivery === "text");
  const videoStrategy = funnel.strategies.find((strategy) => strategy.delivery === "video");
  const hasTextOffer = Boolean(textStrategy?.message_text.trim());
  const hasMediaOffer = Boolean(funnel.loom_intro_text.trim() && videoStrategy?.media_path?.trim());
  return [
    { label: "Funnel enabled", ready: funnel.enabled },
    { label: "Offer price", ready: funnel.offer_price_usd > 0 || funnel.offer_payment_model === "custom" },
    { label: "Offer summary", ready: Boolean(funnel.offer_summary.trim()) },
    { label: "Sheet URL", ready: Boolean(funnel.sheet_url?.trim()) },
    { label: "Sheet GID", ready: Boolean(funnel.sheet_gid?.trim()) },
    { label: "Opener template", ready: Boolean(funnel.opener_template_name?.trim()) },
    { label: "Opener text", ready: Boolean(funnel.opener_text.trim()) },
    { label: "Follow-up template", ready: Boolean(funnel.opener_followup_template_name?.trim()) },
    { label: "Follow-up text", ready: Boolean(funnel.opener_followup_text.trim()) },
    { label: "Operator ping template", ready: Boolean(funnel.manual_ping_template_name?.trim()) },
    { label: "Operator ping text", ready: Boolean(funnel.manual_ping_text.trim()) },
    { label: "Text or media offer", ready: hasTextOffer || hasMediaOffer },
    { label: "Offer check text", ready: Boolean(funnel.video_check_text.trim()) },
    { label: "Meeting text", ready: Boolean(funnel.calendly_intro_text.trim()) },
    { label: "Meeting URL", ready: Boolean(funnel.calendly_base_url.trim()) },
    { label: "Alert emails", ready: funnel.alert_emails.length > 0 },
  ];
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
      label: "Operator ping",
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
  const primaryOfferText = (
    funnel.strategies.find((strategy) => strategy.delivery === "text")?.message_text
    || funnel.loom_intro_text
  );
  const previews: Partial<Record<SendKind, string>> = {
    "send-manual-ping": funnel.manual_ping_text,
    "offer-solo-page-promo": "Solo pagina web profesional. Precio ponderado hacia 99/49 USD.",
    "send-opener": funnel.opener_text,
    "send-loom": primaryOfferText,
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

function formatPipelineStageLabel(stage: string | null | undefined): string {
  const labels: Record<string, string> = {
    new: "New",
    contacted: "Contacted",
    offer_sent: "Offer",
    meeting_sent: "Meeting",
    converted: "Converted",
    closed: "Closed",
    archived: "Archived",
  };
  return labels[String(stage || "")] ?? humanize(stage || "Lead");
}

function formatLeadStatusLabel(lead: LeadSummary): string {
  if (isLeadClosed(lead)) {
    return "Closed";
  }
  if (isLeadArchived(lead)) {
    return "Archived";
  }
  return formatPipelineStageLabel(lead.pipeline_stage);
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

function formatWorkstationClientState(
  client: WorkstationClientSummary | null | undefined,
  automationState?: WorkstationClientDetailResponse["automation_state"] | null,
): string {
  if (!client) {
    return "No client selected";
  }
  if (client.status === "closed") {
    return "Closed";
  }
  if (client.automation_status === "failed") {
    return "Needs review";
  }
  if (automationState?.is_live_working) {
    return "Codex working";
  }
  if (automationState?.is_stale) {
    return "Stale run";
  }
  if (automationState?.is_waiting_backoff) {
    return "Waiting";
  }
  const labels: Record<string, string> = {
    intake: "Collecting inputs",
    needs_human: "Needs direction",
    drafting: "Building",
    awaiting_review: "Ready to review",
    revision_requested: "Revising",
    approved: "Approved",
    handoff_sent: "Delivered",
  };
  return labels[client.automation_status] ?? humanize(client.automation_status || client.status);
}

function formatRate(value: number): string {
  if (!Number.isFinite(value) || value <= 0) {
    return "0%";
  }
  return `${Math.round(value * 100)}%`;
}

function leadTone(lead: LeadSummary): "accent" | "warn" | "success" | "muted" {
  if (isLeadClosed(lead) || isLeadArchived(lead)) {
    return "muted";
  }
  if (lead.attention_state === "needs_reply" || lead.queue_state === "operator") {
    return "warn";
  }
  if (isLeadConverted(lead)) {
    return "success";
  }
  if (lead.pipeline_stage === "meeting_sent") {
    return "success";
  }
  return "accent";
}

function manualTurn(lead: LeadSummary): "" | "needs_reply" | "answered" {
  if (lead.queue_state !== "operator") {
    return "";
  }
  if (lead.manual_reply_status === "needs_reply" || lead.manual_reply_status === "answered") {
    return lead.manual_reply_status;
  }
  return "";
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
  const status = inboxMode ? "Inbox" : formatLeadStatusLabel(lead);

  const lines = [
    `Lead: ${lead.full_name || lead.phone || lead.external_lead_id || lead.id}`,
    `Funnel: ${funnelLabel}`,
    `Status: ${status}`,
    `Operator reply: ${humanize(lead.manual_reply_status || "")}`,
    `WhatsApp window: ${whatsappWindow}`,
    `Phone: ${lead.phone || "-"}`,
    `Normalized phone: ${lead.normalized_phone || "-"}`,
    `Email: ${lead.email || "-"}`,
    `Platform: ${lead.platform || "-"}`,
    `External lead ID: ${lead.external_lead_id || "-"}`,
    `Tags: ${lead.tags.length ? lead.tags.join(", ") : "-"}`,
    `Meeting URL: ${lead.meeting_url || lead.calendly_url || "-"}`,
    `Meeting scheduled: ${lead.meeting_scheduled_at ? `${relativeTime(lead.meeting_scheduled_at)} (${shortDate(lead.meeting_scheduled_at)})` : "-"}`,
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

function LeadCountryLabel({ phone }: { phone: string | null | undefined }) {
  const country = phoneCountry(phone);
  if (!country) {
    return null;
  }

  return (
    <span className="ct-lead-country" title={country.name}>
      <span className="ct-phone-flag" aria-hidden="true">{countryFlag(country.iso2)}</span>
      <span>{country.name}</span>
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
  if (isLeadClosed(lead)) {
    return "This lead is closed. Reopen it before sending WhatsApp messages.";
  }
  if (!lead.last_inbound_at) {
    return "Custom WhatsApp is blocked until the lead sends a message. Use an approved template such as follow-up ping.";
  }
  const lastInboundAt = new Date(lead.last_inbound_at).getTime();
  if (Number.isNaN(lastInboundAt)) {
    return "Custom WhatsApp is blocked because the last inbound time is unavailable. Use an approved template such as follow-up ping.";
  }
  if (Date.now() - lastInboundAt >= WHATSAPP_CUSTOM_WINDOW_MS) {
    return "The 24-hour WhatsApp window is closed. Use an approved template such as follow-up ping.";
  }
  return null;
}

// `stage` is kept only as a legacy payload fallback. Current UI state decisions
// should come from the split lifecycle fields or durable conversion evidence.
function isLeadClosed(lead: LeadSummary | null | undefined): boolean {
  return lead?.terminal_state === "closed" || lead?.stage === "closed";
}

function isLeadArchived(lead: LeadSummary | null | undefined): boolean {
  return lead?.terminal_state === "archived" || lead?.stage === "archived";
}

function isLeadConverted(lead: LeadSummary | null | undefined): boolean {
  if (!lead) {
    return false;
  }
  if (lead.pipeline_stage === "converted" || lead.converted_at) {
    return true;
  }
  return false;
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
