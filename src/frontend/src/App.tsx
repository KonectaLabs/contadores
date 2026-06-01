import { useCallback, useEffect, useLayoutEffect, useMemo, useRef, useState } from "react";
import type { ClipboardEvent, DragEvent, FormEvent, KeyboardEvent, ReactNode } from "react";
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
  GearSix,
  ListChecks,
  NotePencil,
  PaperPlaneTilt,
  PauseCircle,
  Plus,
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
  PlatformAdCampaignItem,
  PlatformCreativeAssetItem,
  PlatformAgentRunItem,
  PlatformAgentToolCallItem,
  PlatformEventItem,
  PlatformHumanQuestionItem,
  PlatformMetaInventorySnapshotItem,
  PlatformMetaPublishAttemptItem,
  PlatformOverviewResponse,
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
const DELIVERY_AUTO_SYNC_MS = 10000;
const WHATSAPP_CUSTOM_WINDOW_MS = 24 * 60 * 60 * 1000;
const DASHBOARD_FUNNEL_STORAGE_KEY = "contadores.dashboard.selectedFunnelId";
const DASHBOARD_LEAD_VIEW_FILTER_STORAGE_KEY = "contadores.dashboard.leadViewFilter";
const LEGACY_DASHBOARD_STAGE_FILTER_STORAGE_KEY = "contadores.dashboard.stageFilter";
const DASHBOARD_SECTION_STORAGE_KEY = "contadores.dashboard.activeSection";

type LeadViewFilterValue =
  | "all"
  | "pipeline:new"
  | "pipeline:contacted"
  | "pipeline:offer_sent"
  | "pipeline:meeting_sent"
  | "pipeline:converted"
  | "attention:needs_reply"
  | "queue:operator"
  | "queue:paused"
  | "terminal:closed";
type LeadViewGroupId = "overview" | "pipeline" | "action" | "system";
type LeadViewFilterOption = {
  value: LeadViewFilterValue;
  label: string;
  metric?: keyof ContadoresMetrics;
  tone: "all" | "neutral" | "accent" | "success" | "warn" | "muted";
  group: LeadViewGroupId;
};
type ActiveSection = "crm" | "sell" | "workstation" | "delivery" | "ops";
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
  { value: "all", label: "All", metric: "total", tone: "all", group: "overview" },
  { value: "pipeline:new", label: "New", metric: "pipeline_new", tone: "neutral", group: "pipeline" },
  { value: "pipeline:contacted", label: "Contacted", metric: "pipeline_contacted", tone: "neutral", group: "pipeline" },
  { value: "pipeline:offer_sent", label: "Offer", metric: "pipeline_offer_sent", tone: "neutral", group: "pipeline" },
  { value: "pipeline:meeting_sent", label: "Meeting", metric: "pipeline_meeting_sent", tone: "accent", group: "pipeline" },
  { value: "pipeline:converted", label: "Converted", metric: "pipeline_converted", tone: "success", group: "pipeline" },
  { value: "queue:operator", label: "Operator", metric: "queue_operator", tone: "warn", group: "action" },
  { value: "attention:needs_reply", label: "Needs reply", metric: "attention_needs_reply", tone: "warn", group: "action" },
  { value: "queue:paused", label: "Paused", metric: "queue_paused", tone: "warn", group: "system" },
  { value: "terminal:closed", label: "Closed", metric: "terminal_closed", tone: "muted", group: "system" },
];

const validLeadViewFilterValues = new Set<LeadViewFilterValue>(leadViewFilters.map((filter) => filter.value));
const legacyLeadViewFilterValues: Record<string, LeadViewFilterValue> = {
  awaiting_initial_reply: "pipeline:new",
  awaiting_video_reply: "pipeline:offer_sent",
  calendly_sent: "pipeline:meeting_sent",
  booked: "pipeline:converted",
  needs_human: "queue:operator",
  manual_attention: "attention:needs_reply",
  closed: "terminal:closed",
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
  return legacyLeadViewFilterValues[value || ""] ?? "all";
}

function applyLeadViewFilter(params: URLSearchParams, filter: LeadViewFilterValue) {
  if (filter === "all") {
    return;
  }
  const [scope, value] = filter.split(":");
  if (!scope || !value) {
    return;
  }
  if (scope === "pipeline") {
    params.set("pipeline_stage", value);
  } else if (scope === "queue") {
    params.set("queue_state", value);
  } else if (scope === "terminal") {
    params.set("terminal_state", value);
  } else if (scope === "attention") {
    params.set("attention_state", value);
  }
}

function readStoredActiveSection(): ActiveSection {
  const value = readStoredValue(DASHBOARD_SECTION_STORAGE_KEY);
  if (value === "runner") {
    return "ops";
  }
  if (value === "sell" || value === "workstation" || value === "delivery" || value === "ops") {
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
    label: "Triage",
    icon: <ListChecks size={16} weight="bold" />,
  },
  {
    section: "sell",
    label: "Sell",
    icon: <ChatCircleText size={16} weight="bold" />,
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
  {
    section: "ops",
    label: "Observe",
    icon: <Pulse size={16} weight="bold" />,
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
  | "pause-automation"
  | "enable-codex"
  | "disable-codex"
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
  let current = element.parentElement;

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
  const [tagFilter, setTagFilter] = useState("");
  const [strategyFilter, setStrategyFilter] = useState<{ step: string; strategyId: string }>({ step: "", strategyId: "" });
  const [activeTab, setActiveTab] = useState<DetailTab>("messages");
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
  const [runnerStatus, setRunnerStatus] = useState<RunnerStatusResponse | null>(null);
  const [runnerLoading, setRunnerLoading] = useState(false);
  const [platformOverview, setPlatformOverview] = useState<PlatformOverviewResponse | null>(null);
  const [platformLoading, setPlatformLoading] = useState(false);
  const [acknowledgingDeliveryErrorIds, setAcknowledgingDeliveryErrorIds] = useState<number[]>([]);
  const [leadContextCopyStatus, setLeadContextCopyStatus] = useState("");
  const detailRequestId = useRef(0);
  const deliveryDraftSourceId = useRef<string | null>(null);
  const deliverySourcesRef = useRef<ClientLeadSource[]>([]);
  const previousFunnelIdRef = useRef(selectedFunnelId);
  const debouncedQuery = useDebouncedValue(query, 250);
  const debouncedWorkstationQuery = useDebouncedValue(workstationQuery, 250);

  const metrics = leadList?.metrics;
  const tagOptions = leadList?.tag_options ?? [];
  const config = leadList?.config ?? detail?.config ?? null;
  const selectedFunnel = funnels.find((funnel) => funnel.id === selectedFunnelId) ?? funnels[0] ?? null;
  const selectedFunnelSetupIssues = buildFunnelSetupIssues(selectedFunnel);
  const isCrmWorkspace = activeSection === "crm" || activeSection === "sell";
  const crmModeLabel = activeSection === "sell" ? "Sell" : "Triage";
  const crmLeadListTitle = activeSection === "sell" ? "Selling conversations" : "Needs attention";
  const crmLeadListSummary = activeSection === "sell"
    ? "Move the active conversation forward"
    : "Reply, unblock, or route";
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
  const selectedVisibleLeads = useMemo(
    () => (leadList?.leads ?? []).filter((lead) => selectedLeadIds.includes(lead.id)),
    [leadList, selectedLeadIds],
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
    const [runtimePayload, funnelPayload, attentionCountsPayload] = await Promise.all([
      apiFetch<RuntimeSettings>("/api/runtime"),
      apiFetch<FunnelListResponse>("/api/funnels"),
      apiFetch<ManualAttentionCountsResponse>("/api/contadores/manual-attention-counts"),
    ]);

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

    setLeadList(leadsPayload);
    setStrategyStats(strategyPayload.items ?? []);

    setSelectedLeadId((current) => {
      const currentLeadIsVisible = Boolean(current && leadsPayload.leads.some((lead) => lead.id === current));
      const currentLeadIsOpen = Boolean(current && detail?.lead.id === current);
      if (currentLeadIsVisible || currentLeadIsOpen) {
        return current;
      }
      return leadsPayload.leads[0]?.id ?? null;
    });
  }, [debouncedQuery, detail?.lead.id, selectedFunnelId, leadViewFilter, strategyFilter.step, strategyFilter.strategyId, tagFilter]);

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

  const loadRunnerStatus = useCallback(async () => {
    const payload = await apiFetch<RunnerStatusResponse>(
      "/api/contadores/followup/runner/status?log_tail_lines=160&log_limit=12",
    );
    setRunnerStatus(payload);
  }, []);

  const loadPlatformOverview = useCallback(async () => {
    const payload = await apiFetch<PlatformOverviewResponse>("/api/platform/overview?limit=120");
    setPlatformOverview(payload);
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
    if (previousFunnelIdRef.current === selectedFunnelId) {
      return;
    }
    previousFunnelIdRef.current = selectedFunnelId;
    setStrategyFilter({ step: "", strategyId: "" });
    setTagFilter("");
    setSelectedLeadIds([]);
    setActiveTab("messages");
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
    setSelectedLeadIds((current) => current.filter((leadId) => visibleLeadIds.includes(leadId)));
  }, [visibleLeadIds]);

  useEffect(() => {
    if (!isInboxFunnel) {
      return;
    }
    setLeadViewFilter("all");
    setStrategyFilter({ step: "", strategyId: "" });
    setTagFilter("");
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
        const loaders: Array<Promise<unknown>> = [loadDashboard()];
        if (activeSection === "delivery") {
          loaders.push(loadDeliverySources());
          if (selectedDeliverySourceId) {
            const sourceIds = deliveryContactSourceIdsFor(deliverySourcesRef.current, selectedDeliverySourceId);
            loaders.push(loadDeliveryLeadsForSources(sourceIds));
            loaders.push(loadDeliveryRecipientChat(selectedDeliverySourceId));
          }
        }
        if (activeSection === "ops") {
          loaders.push(loadPlatformOverview());
          loaders.push(loadRunnerStatus());
        }
        Promise.all(loaders).catch((reason) => {
          setError(reason instanceof Error ? reason.message : "Automatic refresh failed.");
        });
      }
    }, REFRESH_MS);
    return () => window.clearInterval(timer);
  }, [activeSection, loadDashboard, loadDeliveryLeadsForSources, loadDeliveryRecipientChat, loadDeliverySources, loadPlatformOverview, loadRunnerStatus, selectedDeliverySourceId]);

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
    if (activeSection !== "ops") {
      return;
    }
    let cancelled = false;
    setPlatformLoading(true);
    setRunnerLoading(true);
    Promise.all([loadPlatformOverview(), loadRunnerStatus()])
      .catch((reason) => {
        if (!cancelled) {
          setError(reason instanceof Error ? reason.message : "Could not load observability.");
        }
      })
      .finally(() => {
        if (!cancelled) {
          setPlatformLoading(false);
          setRunnerLoading(false);
        }
      });
    return () => {
      cancelled = true;
    };
  }, [activeSection, loadPlatformOverview, loadRunnerStatus]);

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
      await loadRunnerStatus();
      await loadPlatformOverview();
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

  async function toggleLeadCodex(lead: LeadSummary | null | undefined, enabled: boolean) {
    if (!lead?.id) {
      return;
    }
    const action: QuickActionName = enabled ? "enable-codex" : "disable-codex";
    setActionBusy(action);
    try {
      await apiFetch<QuickActionResponse>(`/api/contadores/leads/${lead.id}/actions/${action}`, {
        method: "POST",
      });
      await loadDashboard();
      await loadDetail(lead.id);
      if (selectedWorkstationClientId) {
        await loadWorkstationDetail(selectedWorkstationClientId);
      }
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Could not update Codex switch.");
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

    if (section === "crm") {
      setLeadViewFilter("attention:needs_reply");
      setSelectedLeadId(null);
      setSelectedLeadIds([]);
      setActiveTab("messages");
      return;
    }

    if (section === "sell") {
      setLeadViewFilter((current) => current === "attention:needs_reply" ? "all" : current);
      setSelectedLeadId(null);
      setSelectedLeadIds([]);
      setActiveTab("messages");
    }
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
  const activeTitle = activeSection === "ops"
    ? "Observe"
    : activeSection === "workstation"
      ? workstationTitle
      : activeSection === "delivery"
        ? "Deliver"
        : activeSection === "sell"
          ? "Sell"
          : "Triage";
  const syncStatus = activeSection === "ops"
    ? platformOverview
      ? `${compactNumber(platformOverview.counts.active_blockers)} blockers · ${relativeTime(platformOverview.generated_at)}`
      : runnerStatus?.running
        ? "Runner running"
        : "Observe loading"
    : activeSection === "workstation"
    ? `${workstationClients.length} converted ${workstationClients.length === 1 ? "client" : "clients"}`
    : activeSection === "delivery"
    ? `${deliveryContactGroups.length} ${deliveryContactGroups.length === 1 ? "contact" : "contacts"} · ${compactNumber(deliveryLeadTotal)} leads${deliverySourceIssueCount ? ` · ${deliverySourceIssueCount} issue${deliverySourceIssueCount === 1 ? "" : "s"}` : ""}`
    : config?.last_sheet_sync_status
    ? `${config.last_sheet_sync_status} · ${config.last_sheet_sync_at ? relativeTime(config.last_sheet_sync_at) : "never"}`
    : runtime
      ? (runtime.ready ? "Ready" : "Review config")
      : "Sync idle";
  const syncBadgeIsOk = activeSection === "delivery"
    ? deliverySourceIssueCount === 0
    : activeSection === "ops"
      ? (platformOverview?.counts.active_blockers ?? 0) === 0
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
              : operation.section === "ops" && platformOverview && platformOverview.counts.active_blockers > 0
                ? platformOverview.counts.active_blockers
                : 0;

            return (
              <button
                type="button"
                className={isActive ? "active" : ""}
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

              return (
                <button
                  key={funnel.id}
                  type="button"
                  className={`ct-nav-btn ${selectedFunnelId === funnel.id ? "active" : ""}`}
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
              <button type="button" className="ct-nav-btn ct-nav-add" onClick={openCreateFunnel}>+ Funnel</button>
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
            <button type="button" className="ct-icon-btn" onClick={openEditFunnel} disabled={!selectedFunnel}>Funnel</button>
          ) : null}
          {isCrmWorkspace && canEditLegacyRuntimeConfig ? (
            <button type="button" className="ct-icon-btn" onClick={() => setShowConfig(true)}>Runtime</button>
          ) : null}
          <button type="button" className="ct-icon-btn" onClick={refreshAll} disabled={loading || deliveryLoading || platformLoading}>Refresh</button>
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

        {activeSection === "ops" ? (
        <PlatformOpsView
          overview={platformOverview}
          loading={platformLoading}
          runnerStatus={runnerStatus}
          runnerLoading={runnerLoading}
          onRefresh={() => {
            setPlatformLoading(true);
            setRunnerLoading(true);
            Promise.all([loadPlatformOverview(), loadRunnerStatus()])
              .catch((reason) => setError(reason instanceof Error ? reason.message : "Could not refresh platform ops."))
              .finally(() => {
                setPlatformLoading(false);
                setRunnerLoading(false);
              });
          }}
        />
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
          onToggleLeadCodex={toggleLeadCodex}
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
        <div className="ct-surface" data-crm-mode={activeSection === "sell" ? "sell" : "triage"}>
        {selectedFunnel && selectedFunnel.kind === "campaign" && selectedFunnelSetupIssues.length ? (
          <FunnelSetupBanner
            setupIssues={selectedFunnelSetupIssues}
            onEdit={openEditFunnel}
          />
        ) : null}
        {!isInboxFunnel ? (
          <div className="ct-queue-bar">
            <div className="ct-queue-summary">
              <strong>{crmModeLabel}</strong>
              <span>{totalCount ? `${visibleCount}/${totalCount}` : "0"}</span>
            </div>
            <section className="ct-lead-filter-bar" aria-labelledby="ctLeadStateLabel">
              <div className="ct-lead-filter-head">
                <span id="ctLeadStateLabel">State</span>
                <strong>{leadViewFilters.find((filter) => filter.value === leadViewFilter)?.label ?? "All"}</strong>
              </div>
              <div className="ct-lead-filter-set" role="group" aria-label="Lead state filters">
                {leadViewFilters.map((filter) => {
                  const count = Number(metrics?.[filter.metric ?? "total"] ?? 0);

                  return (
                    <button
                      key={filter.value}
                      type="button"
                      className={`ct-lead-view ${leadViewFilter === filter.value ? "active" : ""}`}
                      data-group={filter.group}
                      data-tone={filter.tone}
                      aria-pressed={leadViewFilter === filter.value}
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

        <div className="ct-workspace">
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
              onMarkConverted={() => runAction("mark-converted")}
              onPauseAutomation={() => runAction("pause-automation")}
              onManualHandoff={() => runAction("manual-handoff")}
              onMarkAnswered={() => runAction("mark-answered")}
              onToggleClosed={() => runAction(isLeadClosed(selectedLead) ? "reopen" : "close")}
              onDelete={deleteLead}
              onConvert={convertLeadToWorkstation}
              onStartSoloPage={startSoloPageWorkstation}
              onToggleCodex={(enabled) => toggleLeadCodex(selectedLead, enabled)}
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
  const [activeSheetFilter, setActiveSheetFilter] = useState("all");
  const isExisting = editorMode === "edit" && Boolean(selectedSource);
  const selectedGroup = isExisting
    ? contactGroups.find((group) => group.sources.some((source) => source.id === selectedSourceId)) ?? null
    : null;
  const selectedSources = selectedGroup?.sources ?? (selectedSource ? [selectedSource] : []);
  const selectedGroupKey = selectedGroup?.key ?? selectedSourceId ?? "";
  const selectedGroupLabel = selectedGroup?.label || selectedSource?.label || "Select a contact";
  const selectedGroupTone = selectedGroup ? deliveryContactTone(selectedGroup) : selectedSource ? deliverySourceTone(selectedSource) : "muted";
  const selectedGroupStatus = selectedGroup ? deliveryContactStatusLabel(selectedGroup) : selectedSource?.enabled ? humanize(selectedSource.last_sync_status || "active") : "Paused";
  const visibleLeads = activeSheetFilter === "all" ? leads : leads.filter((lead) => lead.source_id === activeSheetFilter);
  const nextActionLeads = visibleLeads.filter(isRetryableClientLead);
  const visibleSheetSections = buildDeliverySheetLeadSections(selectedSources, visibleLeads, activeSheetFilter);
  const totalLeads = sources.reduce((total, source) => total + deliverySourceCount(source, "total"), 0);
  const failedLeads = contactGroups.reduce((total, group) => total + group.issues, 0);
  const deliveredLeads = sources.reduce((total, source) => total + deliverySourceCount(source, "sent") + deliverySourceCount(source, "delivered"), 0);
  const selectedTotalLeads = selectedSources.reduce((total, source) => total + deliverySourceCount(source, "total"), 0);
  const selectedDeliveredLeads = selectedSources.reduce((total, source) => total + deliverySourceCount(source, "sent") + deliverySourceCount(source, "delivered"), 0);
  const selectedBlockedLeads = selectedSources.reduce((total, source) => total + deliverySourceCount(source, "blocked"), 0);
  const selectedFailedLeads = selectedSources.reduce((total, source) => total + deliverySourceCount(source, "failed"), 0);
  const selectedLabel = editorMode === "create" ? "New contact" : selectedGroupLabel;
  const selectedIssueSources = selectedSources.filter(deliverySourceHasIssue);
  const recipientMessages = recipientChat?.messages ?? [];
  const recipientDeliveredCount = recipientMessages.filter((message) => message.delivery_status === "delivered").length;
  const recipientCrmLead = recipientChat?.crm_leads?.[0] ?? null;

  useEffect(() => {
    if (editorMode === "create") {
      setConfigOpen(true);
    }
  }, [editorMode]);

  useEffect(() => {
    if (editorMode === "edit" && selectedGroupKey) {
      setConfigOpen(false);
      setSentChatOpen(false);
      setActiveSheetFilter("all");
    }
  }, [editorMode, selectedGroupKey]);

  return (
    <div className="ct-surface delivery-surface">
      <div className="ct-secondary delivery-summary">
        <p className="ct-secondary-note">
          {contactGroups.length
            ? `${contactGroups.length} ${contactGroups.length === 1 ? "contact" : "contacts"} · ${compactNumber(totalLeads)} leads · ${compactNumber(deliveredLeads)} delivered · ${compactNumber(failedLeads)} issues`
            : "No delivery contacts configured yet"}
        </p>
        {copyStatus ? <p className="delivery-copy-status" aria-live="polite">{copyStatus}</p> : null}
      </div>

      <div className="ct-workspace delivery-workspace">
        <aside className="ct-leads delivery-sources">
          <div className="ct-leads-head">
            <h3>Delivery contacts</h3>
            <button type="button" className="ct-btn ct-btn-ghost delivery-small-btn" onClick={onNewSource}>
              <Plus size={13} weight="bold" />
              Contact
            </button>
          </div>
          <div className="ct-leads-list delivery-source-list">
            {loading && !contactGroups.length ? (
              <p className="ct-empty">Loading delivery contacts...</p>
            ) : contactGroups.length ? contactGroups.map((group) => {
              const active = editorMode === "edit" && group.sources.some((source) => source.id === selectedSourceId);
              return (
                <button
                  type="button"
                  className={`delivery-source-row ${active ? "active" : ""} ${group.sources.some((source) => source.enabled) ? "" : "disabled"}`}
                  data-tone={deliveryContactTone(group)}
                  key={group.key}
                  onClick={() => onSelectSource(group.primarySource.id)}
                >
                  <div className="delivery-source-row-top">
                    <strong>{group.label || group.key}</strong>
                    <span className="delivery-status-pill" data-tone={deliveryContactTone(group)}>
                      {deliveryContactStatusLabel(group)}
                    </span>
                  </div>
                  <div className="delivery-source-counts">
                    <span>Total <strong>{compactNumber(group.total)}</strong></span>
                    <span>Delivered <strong>{compactNumber(group.delivered)}</strong></span>
                    <span>Sheets <strong>{compactNumber(group.sources.length)}</strong></span>
                    <span>Issues <strong>{compactNumber(group.issues)}</strong></span>
                  </div>
                  <p>{group.recipientName || "No recipient"}{group.recipientPhone ? ` · ${group.recipientPhone}` : ""}</p>
                  <div className="delivery-source-sheet-tags">
                    {group.sources.map((source) => (
                      <span key={source.id} data-tone={deliverySourceTone(source)}>
                        {deliverySheetLabel(source)}
                      </span>
                    ))}
                  </div>
                </button>
              );
            }) : (
              <p className="ct-empty">Create a contact to pull sheet leads and deliver notifications.</p>
            )}
          </div>
        </aside>

        <section className="ct-detail delivery-detail">
          <header className="ct-detail-head delivery-detail-head">
            <div className="ct-detail-head-main">
              <div className="ct-detail-avatar">{monogram(selectedLabel)}</div>
              <div className="ct-detail-head-copy">
                <p className="ct-detail-kicker">Client Lead Delivery</p>
                <h3>{selectedLabel}</h3>
                <p className="ct-detail-meta">
                  {isExisting
                    ? [selectedGroup?.recipientName || selectedSource?.recipient_name || "-", selectedGroup?.recipientPhone || selectedSource?.recipient_phone || "-", `${selectedSources.length} ${selectedSources.length === 1 ? "sheet" : "sheets"}`].join(" · ")
                    : "Create a sheet contact, recipient, and WhatsApp template mapping."}
                </p>
              </div>
            </div>
            <div className="ct-detail-head-actions">
              <span className="delivery-live-pill" data-tone={selectedGroupTone}>
                {isExisting ? selectedGroupStatus : "Draft"}
              </span>
              <button type="button" className="ct-btn ct-btn-ghost" onClick={onNewSource}>New contact</button>
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

          <div className="delivery-detail-body">
            {isExisting && selectedSources.length ? (
              <div className="delivery-source-strip">
                <button
                  type="button"
                  className={activeSheetFilter === "all" ? "active" : ""}
                  onClick={() => setActiveSheetFilter("all")}
                >
                  <ListChecks size={14} weight="bold" />
                  All sheets
                  <strong>{compactNumber(selectedTotalLeads)}</strong>
                </button>
                {selectedSources.map((source) => (
                  <button
                    type="button"
                    className={activeSheetFilter === source.id ? "active" : ""}
                    data-tone={deliverySourceTone(source)}
                    key={source.id}
                    onClick={() => setActiveSheetFilter(source.id)}
                  >
                    {deliverySourceStatusIcon(source)}
                    {deliverySheetLabel(source)}
                    <strong>{compactNumber(deliverySourceCount(source, "total"))}</strong>
                  </button>
                ))}
              </div>
            ) : null}

            {selectedIssueSources.length ? (
              <div className="delivery-source-alert" data-tone="danger">
                <WarningCircle size={18} weight="fill" />
                <div>
                  <strong>{selectedIssueSources.length === 1 ? "Sheet needs access" : "Sheets need access"}</strong>
                  <span>{selectedIssueSources.map((source) => `${deliverySheetLabel(source)}: ${deliverySourceIssueText(source)}`).join(" · ")}</span>
                </div>
              </div>
            ) : null}

            {isExisting && nextActionLeads.length ? (
              <DeliveryNextActions
                leads={nextActionLeads}
                actionBusy={actionBusy}
                onCopyLead={onCopyLead}
                onCopyLeadAll={onCopyLeadAll}
                onRetryLead={onRetryLead}
              />
            ) : null}

            {isExisting && sentChatOpen ? (
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
                  <p className="ct-empty">Loading sent messages...</p>
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
                  <p className="ct-empty">No sent Delivery messages to this recipient yet.</p>
                )}
              </section>
            ) : null}

            <details className="delivery-lead-panel delivery-rows-disclosure">
              <summary className="workstation-panel-head">
                <div>
                  <span>Rows</span>
                  <strong>{isExisting ? compactNumber(visibleLeads.length) : "-"}</strong>
                </div>
                <div className="delivery-sheet-metrics">
                  <span>{compactNumber(selectedTotalLeads)} total</span>
                  <span>{compactNumber(selectedDeliveredLeads)} delivered</span>
                  <span>{compactNumber(selectedBlockedLeads)} blocked</span>
                  <span>{compactNumber(selectedFailedLeads)} failed</span>
                </div>
              </summary>

              {!isExisting ? (
                <p className="ct-empty">Pick a Delivery contact to inspect the sheet leads.</p>
              ) : leadsLoading && !visibleLeads.length ? (
                <p className="ct-empty">Loading contact leads...</p>
              ) : visibleLeads.length ? (
                <div className="delivery-sheet-sections">
                  {visibleSheetSections.map((section) => (
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
                                  ) : null}
                                  <button type="button" className="ct-btn ct-btn-ghost" onClick={() => onCopyLead(lead)}>
                                    <Copy size={14} weight="bold" />
                                    Copy
                                  </button>
                                  <button
                                    type="button"
                                    className="ct-btn ct-btn-ghost"
                                    disabled={actionBusy === `delivery-copy-${lead.id}`}
                                    onClick={() => onCopyLeadAll(lead)}
                                  >
                                    {actionBusy === `delivery-copy-${lead.id}` ? "Copying..." : "Copy all"}
                                  </button>
                                  {retryable ? (
                                    <button
                                      type="button"
                                      className="ct-btn ct-btn-ghost"
                                      disabled={actionBusy === `delivery-retry-${lead.id}`}
                                      onClick={() => onRetryLead(lead)}
                                    >
                                      <ArrowsClockwise size={14} weight="bold" />
                                      {actionBusy === `delivery-retry-${lead.id}` ? "Retrying..." : "Retry"}
                                    </button>
                                  ) : null}
                                </div>
                              </div>
                            </article>
                          );
                        })}
                      </div>
                    </section>
                  ))}
                </div>
              ) : (
                <p className="ct-empty">No leads loaded for this contact yet.</p>
              )}
            </details>
          </div>
        </section>
      </div>

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

function DeliveryNextActions({
  leads,
  actionBusy,
  onCopyLead,
  onCopyLeadAll,
  onRetryLead,
}: {
  leads: ClientLead[];
  actionBusy: string | null;
  onCopyLead: (lead: ClientLead) => void | Promise<void>;
  onCopyLeadAll: (lead: ClientLead) => void | Promise<void>;
  onRetryLead: (lead: ClientLead) => void | Promise<void>;
}) {
  return (
    <section className="delivery-next-actions" aria-label="Delivery next actions">
      <header className="delivery-next-head">
        <div>
          <span>Next actions</span>
          <strong>{leads.length === 1 ? "1 lead needs delivery" : `${leads.length} leads need delivery`}</strong>
        </div>
      </header>
      <div className="delivery-next-list">
        {leads.map((lead) => {
          const busy = actionBusy === `delivery-retry-${lead.id}`;
          const copyBusy = actionBusy === `delivery-copy-${lead.id}`;
          const waLink = lead.wa_link || buildWaLink(lead.phone_number);
          return (
            <article className="delivery-next-card" data-tone={clientLeadDeliveryTone(lead)} key={lead.id}>
              <div className="delivery-next-copy">
                <span>Row {lead.row_number} · {humanize(lead.delivery_status || "blocked")}</span>
                <strong>{deliveryLeadTitle(lead)}</strong>
                <small>{lead.last_delivery_error || lead.block_reason || deliveryLeadSubtitle(lead)}</small>
              </div>
              <div className="delivery-next-actions-row">
                <button
                  type="button"
                  className="ct-btn ct-btn-primary"
                  disabled={busy}
                  onClick={() => onRetryLead(lead)}
                >
                  <ArrowsClockwise size={14} weight="bold" />
                  {busy ? "Retrying..." : "Retry"}
                </button>
                <details className="ct-action-menu">
                  <summary className="ct-btn ct-btn-ghost">More</summary>
                  <div className="ct-action-menu-panel">
                    {waLink ? (
                      <a className="ct-btn ct-btn-ghost delivery-action-link" href={waLink} target="_blank" rel="noreferrer">
                        <ArrowSquareOut size={14} weight="bold" />
                        Chat
                      </a>
                    ) : null}
                    <button type="button" className="ct-btn ct-btn-ghost" onClick={() => onCopyLead(lead)}>
                      <Copy size={14} weight="bold" />
                      Copy
                    </button>
                    <button type="button" className="ct-btn ct-btn-ghost" disabled={copyBusy} onClick={() => onCopyLeadAll(lead)}>
                      {copyBusy ? "Copying..." : "Copy all"}
                    </button>
                  </div>
                </details>
              </div>
            </article>
          );
        })}
      </div>
    </section>
  );
}

type OpsActionTone = "danger" | "warn";
type OpsActionItem = {
  id: string;
  tone: OpsActionTone;
  area: string;
  title: string;
  detail: string;
  action: string;
  status: string;
  updatedAt: string | null;
};
type OpsReadinessStatus = "ready" | "partial" | "blocked" | "missing" | string;
type OpsReadinessItem = {
  label: string;
  status: OpsReadinessStatus;
  detail: string;
};
type OpsMode = "loading" | "missing" | "blocked" | "review" | "clean";

function PlatformOpsView({
  overview,
  loading,
  runnerStatus,
  runnerLoading,
  onRefresh,
}: {
  overview: PlatformOverviewResponse | null;
  loading: boolean;
  runnerStatus: RunnerStatusResponse | null;
  runnerLoading: boolean;
  onRefresh: () => void;
}) {
  const defaultCounts = {
    active_blockers: 0,
    open_human_questions: 0,
    blocked_meta_attempts: 0,
    blocked_meta_inventory: 0,
    pending_campaigns: 0,
    meetings: 0,
    campaigns: 0,
    creative_assets: 0,
    meta_inventory_snapshots: 0,
    client_updates: 0,
    agent_runs: 0,
    failed_agent_runs: 0,
    agent_tool_calls: 0,
    failed_agent_tool_calls: 0,
    recent_events: 0,
  };
  const counts = { ...defaultCounts, ...(overview?.counts ?? {}) };
  const questions = overview?.human_questions ?? [];
  const metaAttempts = overview?.meta_publish_attempts ?? [];
  const campaigns = overview?.ad_campaigns ?? [];
  const updates = overview?.client_updates ?? [];
  const meetings = overview?.meetings ?? [];
  const events = overview?.events ?? [];
  const profiles = overview?.client_profiles ?? [];
  const creatives = overview?.creative_assets ?? [];
  const inventorySnapshots = overview?.meta_inventory_snapshots ?? [];
  const agentRuns = overview?.agent_runs ?? [];
  const agentToolCalls = overview?.agent_tool_calls ?? [];
  const openQuestions = questions.filter(isOpenPlatformQuestion);
  const blockedAttempts = metaAttempts.filter(isBlockedPlatformAttempt);
  const updatesWithBlockers = updates.filter((update) => update.blockers.length > 0);
  const metaReadyCreatives = creatives.filter(isMetaReadyCreative);
  const uploadBlockedCreatives = creatives.filter((creative) => ["upload_blocked", "upload_failed"].includes(creative.status));
  const failedAgentRuns = agentRuns.filter((run) => ["failed", "error", "blocked"].includes(run.status));
  const failedAgentToolCalls = agentToolCalls.filter((call) => call.status === "failed");
  const latestInventory = inventorySnapshots[0] ?? null;
  const latestInventoryBlocked = latestInventory
    ? latestInventory.status === "missing_credentials" || latestInventory.status === "partial" || latestInventory.errors.length > 0
    : false;
  const inventoryBlockers = latestInventory && latestInventoryBlocked ? [latestInventory] : [];
  const metaCredentialsPendingAction: OpsActionItem[] = !latestInventory ? [{
    id: "setup:meta-credentials",
    tone: "warn",
    area: "Setup",
    title: "Meta credentials not connected",
    detail: "Meta access is missing.",
    action: "Add token, ad account, and live-write approval.",
    status: "missing",
    updatedAt: overview?.generated_at ?? null,
  }] : [];
  const rawOperatorActions: OpsActionItem[] = [
    ...openQuestions.map((question) => ({
      id: `question:${question.id}`,
      tone: "warn" as const,
      area: "Question",
      title: question.question,
      detail: question.trying_to_do || question.context_summary || question.workflow || "Operator answer needed.",
      action: question.default_action || "Answer or choose the safe default.",
      status: question.status,
      updatedAt: question.updated_at,
    })),
    ...blockedAttempts.map((attempt) => ({
      id: `meta:${attempt.id}`,
      tone: "danger" as const,
      area: "Meta",
      title: platformCampaignNameFromAttempt(attempt) || "Meta publish blocked",
      detail: attempt.error || formatMissingMetaFields(attempt),
      action: "Complete missing fields, credentials, or approval before live publish.",
      status: metaPublishStatusValue(attempt),
      updatedAt: attempt.updated_at,
    })),
    ...inventoryBlockers.map((snapshot) => ({
      id: `inventory:${snapshot.id}`,
      tone: "danger" as const,
      area: "Inventory",
      title: "Meta inventory needs access",
      detail: snapshot.errors.length ? formatUnknownList(snapshot.errors) : metaInventoryCounts(snapshot),
      action: "Add Meta credentials or ask Alan for the missing access.",
      status: snapshot.status,
      updatedAt: snapshot.created_at,
    })),
    ...metaCredentialsPendingAction,
    ...updatesWithBlockers.map((update) => ({
      id: `update:${update.id}`,
      tone: "warn" as const,
      area: "Client update",
      title: update.summary_text || formatPlatformRef("client", update.client_id),
      detail: formatUnknownList(update.blockers),
      action: update.next_action || "Resolve blockers before sending update.",
      status: update.status,
      updatedAt: update.updated_at,
    })),
    ...uploadBlockedCreatives.map((creative) => ({
      id: `creative:${creative.id}`,
      tone: "warn" as const,
      area: "Creative",
      title: creative.file_path ? truncate(creative.file_path, 54) : formatPlatformRef("creative", creative.id),
      detail: creative.failure_reason || metaCreativeDetail(creative),
      action: "Upload to Meta after credentials and file readiness are confirmed.",
      status: creative.status,
      updatedAt: creative.updated_at,
    })),
    ...failedAgentRuns.map((run) => ({
      id: `run:${run.id}`,
      tone: "danger" as const,
      area: "Agent",
      title: run.agent_kind || "Agent run failed",
      detail: run.error_preview || run.final_response_preview || formatPlatformRef(run.target_type, run.target_id),
      action: "Inspect the run context before retrying.",
      status: run.status,
      updatedAt: run.finished_at || run.started_at,
    })),
    ...failedAgentToolCalls.map((call) => ({
      id: `tool:${call.id}`,
      tone: "danger" as const,
      area: "Tool",
      title: call.tool_name,
      detail: call.error_preview || call.arguments_preview || formatPlatformRef(call.target_type, call.target_id),
      action: "Fix the input or provider blocker, then rerun the tool.",
      status: call.status,
      updatedAt: call.created_at,
    })),
  ];
  const overviewLoading = loading && !overview;
  const overviewMissing = !loading && !overview;
  const operatorActions = [...rawOperatorActions].sort(compareOpsActions);
  const primaryAction = operatorActions[0] ?? null;
  const hasDangerAction = operatorActions.some((item) => item.tone === "danger");
  let opsMode: OpsMode = "clean";
  if (overviewLoading) {
    opsMode = "loading";
  } else if (overviewMissing) {
    opsMode = "missing";
  } else if (counts.active_blockers > 0 || hasDangerAction) {
    opsMode = "blocked";
  } else if (operatorActions.length > 0) {
    opsMode = "review";
  }

  let opsHero = {
    label: "State",
    title: "Clean",
    detail: "No active platform blockers.",
  };
  if (opsMode === "loading") {
    opsHero = {
      label: "State",
      title: "Loading",
      detail: "Reading platform status before showing blockers.",
    };
  } else if (opsMode === "missing") {
    opsHero = {
      label: "State",
      title: "No data",
      detail: "Refresh platform status before trusting this view.",
    };
  } else if (opsMode === "blocked") {
    opsHero = {
      label: "Next",
      title: primaryAction ? truncate(primaryAction.title, 64) : "Resolve blockers first",
      detail: primaryAction ? truncate(primaryAction.action, 72) : "Clear the blocked queue.",
    };
  } else if (opsMode === "review") {
    opsHero = {
      label: "Next",
      title: primaryAction ? truncate(primaryAction.title, 64) : "Review pending work",
      detail: primaryAction ? truncate(primaryAction.action, 72) : "Clear the open queue.",
    };
  }
  const metaReadiness: OpsReadinessItem[] = [
    {
      label: "Credentials",
      status: inventoryBlockers.length ? "blocked" : latestInventory ? latestInventory.status : "missing",
      detail: inventoryBlockers.length ? "Meta access missing or partial" : latestInventory ? metaInventoryCounts(latestInventory) : "No inventory sync yet",
    },
    {
      label: "Campaign brief",
      status: campaigns.length ? "ready" : "missing",
      detail: campaigns.length ? `${campaigns.length} staged` : "Stage campaign after client profile",
    },
    {
      label: "Creative batch",
      status: metaReadyCreatives.length ? "ready" : creatives.length ? "partial" : "missing",
      detail: `${creatives.length} assets · ${metaReadyCreatives.length} Meta-ready`,
    },
    {
      label: "Publish plan",
      status: metaAttempts.length ? (blockedAttempts.length ? "blocked" : "ready") : "missing",
      detail: metaAttempts.length ? `${metaAttempts.length} attempts · ${blockedAttempts.length} blocked` : "No Meta plan staged",
    },
    {
      label: "Approval gate",
      status: metaAttempts.some((attempt) => attempt.approval_status === "approved" || attempt.response_payload.schema_version === "konecta.meta_publish_execution.v1") ? "ready" : "missing",
      detail: "Needs explicit approval before live writes",
    },
  ];
  const runnerNeedsAction = runnerStatus?.delta?.metrics.needs_action ?? 0;
  const runnerReplies = runnerStatus?.delta?.metrics.new_replies ?? 0;
  const runnerTone = runnerStatus?.running
    ? "blue"
    : runnerNeedsAction > 0
      ? "danger"
      : "ok";

  return (
    <div className="ct-surface ops-surface">
      <section className="ops-toolbar" data-mode={opsMode} aria-label="Platform lifecycle status">
        <div className="ops-toolbar-main">
          <span>{opsHero.label}</span>
          <strong>{opsHero.title}</strong>
          <small>{opsHero.detail}</small>
        </div>
        <div className="ops-toolbar-side">
          <button type="button" className="ct-btn ct-btn-ghost" onClick={onRefresh} disabled={loading}>
            {loading ? <SpinnerGap size={16} weight="bold" /> : <ArrowsClockwise size={16} weight="bold" />}
            Refresh
          </button>
        </div>
      </section>

      <section className="runner-command-center ops-signal-grid" aria-label="Platform signals">
        <RunnerSignal icon={<WarningCircle size={30} weight="fill" />} label="Blockers" value={counts.active_blockers} tone={counts.active_blockers > 0 ? "danger" : "ok"} />
        <RunnerSignal icon={<ChatCircleText size={30} weight="fill" />} label="Questions" value={counts.open_human_questions} tone={counts.open_human_questions > 0 ? "warn" : "neutral"} />
        <RunnerSignal icon={<Pulse size={30} weight="fill" />} label="Runner" value={runnerNeedsAction} tone={runnerTone} />
        <RunnerSignal icon={<PaperPlaneTilt size={30} weight="fill" />} label="Meta" value={counts.blocked_meta_attempts + counts.blocked_meta_inventory} tone={counts.blocked_meta_attempts + counts.blocked_meta_inventory > 0 ? "danger" : "neutral"} />
      </section>

      <section className="ops-layout">
        <div className="ops-main-column">
          <OpsPanel eyebrow={<ListChecks size={18} weight="fill" />} title="Action queue" meta={`${operatorActions.length}`}>
            {overviewLoading ? (
              <OpsEmpty title="Loading platform state" value="..." />
            ) : overviewMissing ? (
              <OpsEmpty title="No platform data" value="-" />
            ) : operatorActions.length ? (
              <div className="ops-action-queue">
                {operatorActions.slice(0, 5).map((item) => (
                  <OpsActionCard item={item} key={item.id} />
                ))}
              </div>
            ) : (
              <OpsEmpty title="No open actions" value="0" />
            )}
          </OpsPanel>
        </div>

        <aside className="ops-side-column">
          <ObserveRunnerPanel
            status={runnerStatus}
            loading={runnerLoading}
            needsAction={runnerNeedsAction}
            replies={runnerReplies}
          />
        </aside>
      </section>

      <details className="ops-deep-details">
        <summary>
          <span>Details</span>
          <em>{compactNumber(counts.recent_events)} events</em>
        </summary>
        <div className="ops-deep-grid">
          <OpsPanel eyebrow={<PaperPlaneTilt size={18} weight="fill" />} title="Meta readiness" meta={`${metaReadyCreatives.length} ready creatives`}>
            <div className="ops-readiness-lane">
              {metaReadiness.map((step) => (
                <OpsReadinessStep step={step} key={step.label} />
              ))}
            </div>
          </OpsPanel>

          <OpsPanel eyebrow={<ListChecks size={18} weight="fill" />} title="Blockers" meta={`${openQuestions.length + blockedAttempts.length + updatesWithBlockers.length}`}>
            <div className="ops-list">
              {openQuestions.map((question) => (
                <article className="ops-item" data-tone="warn" key={question.id}>
                  <div className="ops-item-topline">
                    <OpsStatus value={question.status} />
                    <time>{relativeTime(question.updated_at)}</time>
                  </div>
                  <strong>{question.question}</strong>
                  <p>{question.trying_to_do || question.context_summary || question.workflow}</p>
                  <div className="ops-item-meta">
                    <span>{formatPlatformRef(question.target_type, question.target_id)}</span>
                    {question.default_action ? <span>{question.default_action}</span> : null}
                  </div>
                </article>
              ))}
              {blockedAttempts.map((attempt) => (
                <article className="ops-item" data-tone="danger" key={attempt.id}>
                  <div className="ops-item-topline">
                    <OpsStatus value={attempt.approval_status || attempt.status} />
                    <time>{relativeTime(attempt.updated_at)}</time>
                  </div>
                  <strong>{platformCampaignNameFromAttempt(attempt) || "Meta publish"}</strong>
                  <p>{attempt.error || formatPlatformRef("campaign", attempt.campaign_id)}</p>
                  <div className="ops-item-meta">
                    <span>{formatPlatformRef("attempt", attempt.id)}</span>
                    <span>{formatMissingMetaFields(attempt)}</span>
                  </div>
                </article>
              ))}
              {updatesWithBlockers.map((update) => (
                <article className="ops-item" data-tone="warn" key={update.id}>
                  <div className="ops-item-topline">
                    <OpsStatus value={update.status} />
                    <time>{relativeTime(update.updated_at)}</time>
                  </div>
                  <strong>{update.summary_text || formatPlatformRef("client", update.client_id)}</strong>
                  <p>{formatUnknownList(update.blockers)}</p>
                  <div className="ops-item-meta">
                    <span>{formatPlatformRef("campaign", update.campaign_id)}</span>
                    <span>{update.next_action || "-"}</span>
                  </div>
                </article>
              ))}
              {!openQuestions.length && !blockedAttempts.length && !updatesWithBlockers.length ? (
                <OpsEmpty title="Clean" value="0" />
              ) : null}
            </div>
          </OpsPanel>

          <OpsPanel eyebrow={<TrendUp size={18} weight="fill" />} title="Campaigns" meta={`${campaigns.length}`}>
            <div className="ops-table-list">
              {campaigns.slice(0, 8).map((campaign) => (
                <div className="ops-table-row" key={campaign.id}>
                  <div>
                    <strong>{campaign.objective || formatPlatformRef("campaign", campaign.id)}</strong>
                    <span>{formatPlatformRef("client", campaign.client_id)} · {campaignBudgetLabel(campaign)}</span>
                  </div>
                  <OpsStatus value={campaign.approval_status || campaign.status} />
                  <time>{relativeTime(campaign.updated_at)}</time>
                </div>
              ))}
              {!campaigns.length ? <OpsEmpty title="No campaigns" value="0" /> : null}
            </div>
          </OpsPanel>

          <OpsPanel eyebrow={<PaperPlaneTilt size={18} weight="fill" />} title="Meta publish" meta={`${metaAttempts.length}`}>
            <div className="ops-table-list">
              {metaAttempts.slice(0, 8).map((attempt) => (
                <div className="ops-table-row" key={attempt.id}>
                  <div>
                    <strong>{platformCampaignNameFromAttempt(attempt) || humanize(attempt.status)}</strong>
                    <span>{formatPlatformRef("campaign", attempt.campaign_id)} · {formatMetaPublishDetail(attempt)}</span>
                  </div>
                  <OpsStatus value={metaPublishStatusValue(attempt)} />
                  <time>{relativeTime(attempt.updated_at)}</time>
                </div>
              ))}
              {!metaAttempts.length ? <OpsEmpty title="No attempts" value="0" /> : null}
            </div>
          </OpsPanel>

          <OpsPanel eyebrow={<ListChecks size={18} weight="fill" />} title="Meta inventory" meta={`${inventorySnapshots.length}`}>
            <div className="ops-table-list">
              {inventorySnapshots.slice(0, 5).map((snapshot) => {
                const technicalFields = metaInventoryTechnicalFields(snapshot);
                return (
                  <div className="ops-table-row" key={snapshot.id}>
                    <div>
                      <strong>{metaInventoryLabel(snapshot)}</strong>
                      <span>{metaInventoryCounts(snapshot)}</span>
                      {technicalFields.length ? (
                        <details className="ops-debug-details">
                          <summary>Technical details</summary>
                          {technicalFields.map((field) => (
                            <code key={field}>{field}</code>
                          ))}
                        </details>
                      ) : null}
                    </div>
                    <OpsStatus value={snapshot.status} />
                    <time>{relativeTime(snapshot.created_at)}</time>
                  </div>
                );
              })}
              {!inventorySnapshots.length ? <OpsEmpty title="No inventory" value="0" /> : null}
            </div>
          </OpsPanel>

          <OpsPanel eyebrow={<GearSix size={18} weight="fill" />} title="Agent activity" meta={`${agentRuns.length} runs · ${agentToolCalls.length} calls`}>
            <div className="ops-table-list">
              {agentRuns.slice(0, 6).map((run) => {
                const runDetail = run.error_preview || run.final_response_preview;
                return (
                  <div className="ops-table-row" key={run.id}>
                    <div>
                      <strong>{formatAgentRunTitle(run)}</strong>
                      <span>{formatAgentRunContext(run)}</span>
                      {runDetail || run.prompt_version || run.context_path ? (
                        <details className="ops-debug-details">
                          <summary>Technical details</summary>
                          <span>{runDetail ? truncate(runDetail, 180) : "No preview"}</span>
                          <code>{formatPlatformRef(run.target_type, run.target_id)}</code>
                          {run.prompt_version ? <code>Prompt {run.prompt_version}</code> : null}
                          {run.context_path ? <code>{truncate(run.context_path, 90)}</code> : null}
                        </details>
                      ) : null}
                    </div>
                    <OpsStatus value={run.status} />
                    <time>{relativeTime(run.finished_at || run.started_at)}</time>
                  </div>
                );
              })}
              {!agentRuns.length ? <OpsEmpty title="No runs" value="0" /> : null}
            </div>
            {failedAgentRuns.length ? (
              <p className="ops-panel-note">{compactNumber(failedAgentRuns.length)} failed agent run{failedAgentRuns.length === 1 ? "" : "s"}.</p>
            ) : null}
            <div className="ops-table-list">
              {agentToolCalls.slice(0, 6).map((call) => {
                const callDetail = call.error_preview || call.result_preview || call.arguments_preview;
                return (
                  <div className="ops-table-row" key={call.id}>
                    <div>
                      <strong>{humanize(call.tool_name || "tool call")}</strong>
                      <span>{formatAgentToolContext(call)}</span>
                      {callDetail || call.idempotency_key ? (
                        <details className="ops-debug-details">
                          <summary>Technical details</summary>
                          <span>{callDetail ? truncate(callDetail, 180) : "No preview"}</span>
                          <code>{formatPlatformRef(call.target_type, call.target_id)}</code>
                          <code>Run {truncate(call.run_id, 28)}</code>
                          {call.idempotency_key ? <code>{truncate(call.idempotency_key, 80)}</code> : null}
                        </details>
                      ) : null}
                    </div>
                    <OpsStatus value={call.status} />
                    <time>{relativeTime(call.created_at)}</time>
                  </div>
                );
              })}
            </div>
            {failedAgentToolCalls.length ? (
              <p className="ops-panel-note">{compactNumber(failedAgentToolCalls.length)} failed tool call{failedAgentToolCalls.length === 1 ? "" : "s"}.</p>
            ) : null}
          </OpsPanel>

          <OpsPanel eyebrow={<ClockCountdown size={18} weight="fill" />} title="Meetings" meta={`${meetings.length}`}>
            <div className="ops-list compact">
              {meetings.slice(0, 6).map((meeting) => (
                <article className="ops-item" key={meeting.id}>
                  <div className="ops-item-topline">
                    <OpsStatus value={meeting.status} />
                    <time>{relativeTime(meeting.updated_at)}</time>
                  </div>
                  <strong>{meeting.lead_email || formatPlatformRef("lead", meeting.lead_id)}</strong>
                  <p>{[meeting.requested_day, meeting.requested_time, meeting.timezone].filter(Boolean).join(" · ") || meeting.context_summary || "-"}</p>
                  {meeting.calendar_event_link ? (
                    <a href={meeting.calendar_event_link} target="_blank" rel="noreferrer">
                      Calendar event
                    </a>
                  ) : meeting.calendar_error ? (
                    <p>{meeting.calendar_error}</p>
                  ) : null}
                </article>
              ))}
              {!meetings.length ? <OpsEmpty title="No meetings" value="0" /> : null}
            </div>
          </OpsPanel>

          <OpsPanel eyebrow={<ChatCircleText size={18} weight="fill" />} title="Client updates" meta={`${updates.length}`}>
            <div className="ops-list compact">
              {updates.slice(0, 6).map((update) => (
                <article className="ops-item" key={update.id}>
                  <div className="ops-item-topline">
                    <OpsStatus value={update.status} />
                    <time>{relativeTime(update.updated_at)}</time>
                  </div>
                  <strong>{update.summary_text || formatPlatformRef("client", update.client_id)}</strong>
                  <p>{`${compactNumber(update.leads_count)} leads · ${update.next_action || "-"}`}</p>
                </article>
              ))}
              {!updates.length ? <OpsEmpty title="No updates" value="0" /> : null}
            </div>
          </OpsPanel>

          <OpsPanel eyebrow={<Robot size={18} weight="fill" />} title="Assets" meta={`${profiles.length + creatives.length}`}>
            <div className="ops-asset-grid">
              <div>
                <strong>{compactNumber(profiles.length)}</strong>
                <span>Profiles</span>
              </div>
              <div>
                <strong>{compactNumber(creatives.length)}</strong>
                <span>Creatives</span>
              </div>
              <div>
                <strong>{compactNumber(metaReadyCreatives.length)}</strong>
                <span>Meta-ready</span>
              </div>
            </div>
            <div className="ops-table-list">
              {creatives.slice(0, 5).map((creative) => (
                <div className="ops-table-row" key={creative.id}>
                  <div>
                    <strong>{creative.file_path ? truncate(creative.file_path, 42) : formatPlatformRef("creative", creative.id)}</strong>
                    <span>{metaCreativeDetail(creative)}</span>
                  </div>
                  <OpsStatus value={creative.status} />
                  <time>{relativeTime(creative.updated_at)}</time>
                </div>
              ))}
              {!creatives.length ? <OpsEmpty title="No creatives" value="0" /> : null}
            </div>
            {uploadBlockedCreatives.length ? (
              <p className="ops-panel-note">{compactNumber(uploadBlockedCreatives.length)} creative upload blocker{uploadBlockedCreatives.length === 1 ? "" : "s"}.</p>
            ) : null}
          </OpsPanel>

          <OpsPanel eyebrow={<Pulse size={18} weight="fill" />} title="Event stream" meta={`${events.length}`}>
            <div className="ops-event-stream">
              {events.slice(0, 14).map((event) => (
                <article className="ops-item ops-event-card" data-tone={opsEventTone(event)} key={event.id}>
                  <div className="ops-item-topline">
                    <span>{formatOpsEventStage(event)}</span>
                    <time>{relativeTime(event.created_at)}</time>
                  </div>
                  <strong>{formatOpsEventTitle(event)}</strong>
                  <p>{formatOpsEventDetail(event)}</p>
                  <details className="ops-debug-details">
                    <summary>Technical details</summary>
                    <code>{formatPlatformRef(event.target_type, event.target_id)}</code>
                    <code>{event.event_type}</code>
                    {event.source ? <code>Source {humanize(event.source)}</code> : null}
                    {event.actor ? <code>Actor {humanize(event.actor)}</code> : null}
                    {event.correlation_id ? <code>{truncate(event.correlation_id, 80)}</code> : null}
                  </details>
                </article>
              ))}
              {!events.length ? <OpsEmpty title="No events" value="0" /> : null}
            </div>
          </OpsPanel>
        </div>
      </details>
    </div>
  );
}

function ObserveRunnerPanel({
  status,
  loading,
  needsAction,
  replies,
}: {
  status: RunnerStatusResponse | null;
  loading: boolean;
  needsAction: number;
  replies: number;
}) {
  const delta = status?.delta ?? null;
  const attentionEvents = delta?.attention_events ?? [];
  const mode = loading
    ? "loading"
    : status?.running
      ? "running"
      : needsAction > 0
        ? "review"
        : "clean";
  const title = mode === "loading" ? "Loading" : mode === "running" ? "Running" : mode === "review" ? "Review" : "Clean";
  const updated = status?.latest_summary_updated_at ? relativeTime(status.latest_summary_updated_at) : "No run";

  return (
    <OpsPanel eyebrow={<Pulse size={18} weight="fill" />} title="Runner" meta={updated}>
      <div className="observe-runner" data-mode={mode}>
        <div className="observe-runner-main">
          <div className="observe-runner-icon" aria-hidden="true">
            {mode === "running" || mode === "loading" ? (
              <Pulse size={24} weight="fill" />
            ) : mode === "review" ? (
              <WarningCircle size={24} weight="fill" />
            ) : (
              <CheckCircle size={24} weight="fill" />
            )}
          </div>
          <div>
            <strong>{title}</strong>
            <span>{compactNumber(needsAction)} action · {compactNumber(replies)} replies</span>
          </div>
        </div>

        {attentionEvents.length ? (
          <div className="observe-runner-list">
            {attentionEvents.slice(0, 3).map((event) => (
              <RunnerCompactEvent event={event} key={`${event.kind}:${event.lead_id}:${event.occurred_at || ""}`} />
            ))}
          </div>
        ) : (
          <OpsEmpty title="No runner actions" value="0" />
        )}

        <details className="runner-history-details">
          <summary>Runner details</summary>
          <div className="runner-disclosure-row">
            <details className="runner-history-details">
              <summary>Last run</summary>
              <MarkdownBlock markdown={status?.latest_summary || "No run summary has been written yet."} className="runner-last-markdown" />
            </details>
            <details className="runner-history-details">
              <summary>Counts</summary>
              <RunnerDeltaTable
                bucketDeltas={delta?.bucket_deltas ?? []}
                failureDeltas={delta?.failure_deltas ?? []}
                exclusionDeltas={delta?.exclusion_deltas ?? []}
              />
            </details>
            <details className="runner-technical">
              <summary>Technical logs</summary>
              <p className="runner-technical-note">Use these only when the human status above is not enough to debug the runner or LaunchAgent.</p>
              <div className="runner-technical-meta" aria-label="Runner process details">
                <code>{status?.running ? "Process running" : "Process stopped"}</code>
                {typeof status?.pid === "number" ? <code>pid {status.pid}</code> : null}
                {status?.started_at ? <code>Started {relativeTime(status.started_at)}</code> : null}
                {typeof status?.lock_age_seconds === "number" ? <code>Lock {compactNumber(Math.round(status.lock_age_seconds))}s</code> : null}
              </div>
              <div className="runner-tail-grid" aria-label="Runner log tails">
                <RunnerTail title="Latest run tail" text={status?.latest_log_tail || ""} />
                <RunnerTail title="LaunchAgent stdout" text={status?.launchd_out_tail || ""} />
                <RunnerTail title="LaunchAgent stderr" text={status?.launchd_err_tail || ""} />
              </div>
            </details>
          </div>
        </details>
      </div>
    </OpsPanel>
  );
}

function OpsPanel({
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
    <section className="ops-panel">
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

function OpsActionCard({ item }: { item: OpsActionItem }) {
  return (
    <article className="ops-action-card" data-tone={item.tone}>
      <div className="ops-action-marker">
        {item.tone === "danger" ? <WarningCircle size={18} weight="fill" /> : <ClockCountdown size={18} weight="fill" />}
      </div>
      <div className="ops-action-copy">
        <div className="ops-action-topline">
          <span>{item.area}</span>
          <time>{relativeTime(item.updatedAt)}</time>
        </div>
        <strong>{truncate(item.title, 72)}</strong>
        <p>{truncate(item.detail, 90)}</p>
        <em>{truncate(item.action, 90)}</em>
      </div>
      <OpsStatus value={item.status} />
    </article>
  );
}

function OpsReadinessStep({ step }: { step: OpsReadinessItem }) {
  const tone = opsReadinessTone(step.status);
  return (
    <article className="ops-readiness-step" data-tone={tone}>
      <span className="ops-readiness-dot" aria-hidden="true" />
      <div>
        <strong>{step.label}</strong>
        <p>{step.detail}</p>
      </div>
      <OpsStatus value={step.status} />
    </article>
  );
}

function OpsStatus({ value }: { value: string }) {
  const tone = opsStatusTone(value);
  return <span className="ops-status" data-tone={tone}>{humanize(value)}</span>;
}

function OpsEmpty({ title, value }: { title: string; value: string }) {
  return (
    <div className="ops-empty">
      <CheckCircle size={30} weight="fill" />
      <strong>{title}</strong>
      <span>{value}</span>
    </div>
  );
}

function isOpenPlatformQuestion(question: PlatformHumanQuestionItem): boolean {
  return !["answered", "closed", "resolved", "cancelled"].includes(question.status);
}

function isBlockedPlatformAttempt(attempt: PlatformMetaPublishAttemptItem): boolean {
  return (
    ["blocked", "failed", "error", "partial_failed"].includes(attempt.status)
    || ["needs_preflight", "rejected"].includes(attempt.approval_status)
  );
}

function campaignBudgetLabel(campaign: PlatformAdCampaignItem): string {
  if (campaign.budget_daily_usd !== null) {
    return `${campaign.budget_currency} ${campaign.budget_daily_usd}/day`;
  }
  if (campaign.budget_total_usd !== null) {
    return `${campaign.budget_currency} ${campaign.budget_total_usd} total`;
  }
  return "No budget";
}

function isMetaReadyCreative(creative: PlatformCreativeAssetItem): boolean {
  return Boolean(creative.meta_creative_id || creative.image_hash || creative.video_id);
}

function metaCreativeDetail(creative: PlatformCreativeAssetItem): string {
  if (creative.meta_creative_id) {
    return `Meta creative ${truncate(creative.meta_creative_id, 24)}`;
  }
  if (creative.image_hash) {
    return `Image hash ${truncate(creative.image_hash, 24)}`;
  }
  if (creative.video_id) {
    return `Video ${truncate(creative.video_id, 24)}`;
  }
  if (creative.failure_reason) {
    return truncate(creative.failure_reason, 72);
  }
  return [humanize(creative.asset_type), creative.dimensions || "No dimensions"].filter(Boolean).join(" · ");
}

function opsStatusTone(value: string): "danger" | "warn" | "ok" | "neutral" {
  const normalized = value.toLowerCase();
  if (["failed", "error", "blocked", "rejected", "partial_failed", "upload_failed"].includes(normalized)) {
    return "danger";
  }
  if (["missing_credentials", "partial", "upload_blocked"].includes(normalized)) {
    return "danger";
  }
  if (["pending", "needs_preflight", "not_requested", "draft", "staged"].includes(normalized)) {
    return "warn";
  }
  if (["answered", "approved", "published", "submitted", "already_submitted", "sent", "delivered", "completed", "ready", "uploaded", "uploaded_to_meta"].includes(normalized)) {
    return "ok";
  }
  return "neutral";
}

function opsReadinessTone(value: string): "danger" | "warn" | "ok" | "neutral" {
  const normalized = value.toLowerCase();
  if (["blocked", "failed", "error", "missing_credentials"].includes(normalized)) {
    return "danger";
  }
  if (["missing", "partial", "pending", "staged", "not_requested"].includes(normalized)) {
    return "warn";
  }
  if (["ready", "approved", "uploaded", "published", "completed"].includes(normalized)) {
    return "ok";
  }
  return "neutral";
}

function compareOpsActions(a: OpsActionItem, b: OpsActionItem): number {
  const toneDifference = opsActionToneRank(a.tone) - opsActionToneRank(b.tone);
  if (toneDifference !== 0) {
    return toneDifference;
  }
  return timestampValue(b.updatedAt) - timestampValue(a.updatedAt);
}

function opsActionToneRank(tone: OpsActionTone): number {
  return tone === "danger" ? 0 : 1;
}

function timestampValue(value: string | null): number {
  const parsed = Date.parse(value ?? "");
  return Number.isNaN(parsed) ? 0 : parsed;
}

function formatPlatformRef(type: string, id: string): string {
  if (!id) {
    return humanize(type || "item");
  }
  return `${humanize(type)} · ${truncate(id, 18)}`;
}

function formatPlatformTargetLabel(type: string, id: string): string {
  const label = platformTargetLabel(type);
  return id ? `${label} record` : label;
}

function platformTargetLabel(type: string): string {
  const normalized = type.toLowerCase();
  const labels: Record<string, string> = {
    ad_campaign: "Campaign",
    agent_run: "Agent run",
    client: "Client",
    client_lead_source: "Delivery source",
    creative: "Creative",
    creative_asset: "Creative",
    funnel: "Funnel",
    human_question: "Operator question",
    lead: "Lead",
    meeting: "Meeting",
    meta_inventory: "Meta inventory",
    meta_publish_attempt: "Meta publish",
    recipient: "Recipient",
    workstation_client: "Workstation client",
  };
  return labels[normalized] || humanize(type || "Item");
}

function formatAgentRunTitle(run: PlatformAgentRunItem): string {
  return `${humanize(run.agent_kind || "agent")} run`;
}

function formatAgentRunContext(run: PlatformAgentRunItem): string {
  return `${formatPlatformTargetLabel(run.target_type, run.target_id)} · ${agentOutcomeLabel(run.status)}`;
}

function formatAgentToolContext(call: PlatformAgentToolCallItem): string {
  return `${formatPlatformTargetLabel(call.target_type, call.target_id)} · ${agentOutcomeLabel(call.status)}`;
}

function agentOutcomeLabel(status: string): string {
  const normalized = status.toLowerCase();
  if (["failed", "error", "blocked"].includes(normalized)) {
    return "Needs review";
  }
  if (["running", "queued", "pending"].includes(normalized)) {
    return "In progress";
  }
  if (["completed", "complete", "success", "succeeded"].includes(normalized)) {
    return "Completed";
  }
  return humanize(status || "status pending");
}

function formatOpsEventStage(event: PlatformEventItem): string {
  return humanize(event.lifecycle_stage || event.severity || "event");
}

function formatOpsEventTitle(event: PlatformEventItem): string {
  return event.summary || `${humanize(event.event_type || event.lifecycle_stage || "platform event")} update`;
}

function formatOpsEventDetail(event: PlatformEventItem): string {
  const parts = [formatPlatformTargetLabel(event.target_type, event.target_id)];
  if (event.actor && event.actor !== event.source) {
    parts.push(`by ${humanize(event.actor)}`);
  }
  if (event.source) {
    parts.push(`from ${humanize(event.source)}`);
  }
  return parts.join(" · ");
}

function opsEventTone(event: PlatformEventItem): "danger" | "warn" | undefined {
  const signal = `${event.severity} ${event.lifecycle_stage} ${event.event_type}`.toLowerCase();
  if (/(failed|failure|error|blocked|critical|danger)/.test(signal)) {
    return "danger";
  }
  if (/(warn|warning|missing|pending|partial)/.test(signal)) {
    return "warn";
  }
  return undefined;
}

function formatUnknownList(items: unknown[]): string {
  if (!items.length) {
    return "-";
  }
  return items.map((item) => typeof item === "string" ? item : JSON.stringify(item)).join(" · ");
}

function platformCampaignNameFromAttempt(attempt: PlatformMetaPublishAttemptItem): string {
  const campaign = attempt.request_payload.campaign;
  if (campaign && typeof campaign === "object" && "name" in campaign) {
    const name = (campaign as { name?: unknown }).name;
    return typeof name === "string" ? name : "";
  }
  const campaignName = attempt.request_payload.campaign_name;
  return typeof campaignName === "string" ? campaignName : "";
}

function formatMissingMetaFields(attempt: PlatformMetaPublishAttemptItem): string {
  const missing = attempt.request_payload.required_before_live_publish;
  if (Array.isArray(missing) && missing.length) {
    return `${missing.length} missing`;
  }
  return attempt.idempotency_key ? truncate(attempt.idempotency_key, 28) : "Ready";
}

function formatMetaPublishDetail(attempt: PlatformMetaPublishAttemptItem): string {
  const execution = attempt.response_payload;
  if (execution.schema_version === "konecta.meta_publish_execution.v1") {
    const results = Array.isArray(execution.operation_results) ? execution.operation_results : [];
    const executed = results.filter((item) => {
      return typeof item === "object" && item !== null && (item as { status?: unknown }).status === "executed";
    }).length;
    const failed = results.filter((item) => {
      return typeof item === "object" && item !== null && (item as { status?: unknown }).status === "failed";
    }).length;
    if (failed > 0) {
      return `${failed} failed · ${executed} executed`;
    }
    if (results.length > 0) {
      return `${results.length} Meta ops`;
    }
  }
  return formatMissingMetaFields(attempt);
}

function metaPublishStatusValue(attempt: PlatformMetaPublishAttemptItem): string {
  if (attempt.response_payload.schema_version === "konecta.meta_publish_execution.v1") {
    return attempt.status;
  }
  return attempt.approval_status || attempt.status;
}

function metaInventoryLabel(snapshot: PlatformMetaInventorySnapshotItem): string {
  return snapshot.status === "missing_credentials" ? "Meta inventory needs access" : "Meta inventory";
}

function metaInventoryTechnicalFields(snapshot: PlatformMetaInventorySnapshotItem): string[] {
  return [
    snapshot.ad_account_id ? `Ad account ${truncate(snapshot.ad_account_id, 32)}` : "",
    snapshot.business_id ? `Business ${truncate(snapshot.business_id, 32)}` : "",
    snapshot.api_version ? `API ${snapshot.api_version}` : "",
  ].filter(Boolean);
}

function metaInventoryArrayCount(snapshot: PlatformMetaInventorySnapshotItem, key: string): number {
  const value = snapshot.inventory[key];
  return Array.isArray(value) ? value.length : 0;
}

function metaInventoryCounts(snapshot: PlatformMetaInventorySnapshotItem): string {
  if (snapshot.errors.length > 0) {
    return `${snapshot.errors.length} blocker${snapshot.errors.length === 1 ? "" : "s"}`;
  }
  const parts = [
    `${metaInventoryArrayCount(snapshot, "ad_accounts")} accounts`,
    `${metaInventoryArrayCount(snapshot, "pages")} pages`,
    `${metaInventoryArrayCount(snapshot, "lead_forms")} forms`,
    `${metaInventoryArrayCount(snapshot, "whatsapp_phone_numbers")} WA numbers`,
  ];
  return parts.join(" · ");
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
    booking_time_provided: "Meeting intent",
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

function RunnerTail({ title, text }: { title: string; text: string }) {
  return (
    <section className="workstation-panel runner-tail-panel">
      <div className="workstation-panel-head">
        <div>
          <span>Technical tail</span>
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
  onToggleLeadCodex,
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
  onToggleLeadCodex: (lead: LeadSummary | null | undefined, enabled: boolean) => void | Promise<void>;
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
  const codexEnabled = Boolean(selectedLead?.codex_enabled);
  const canStartSoloPageWork = activeClient?.work_type === "solo_pagina" && codexEnabled && !soloPageBusy && !workstationClosed;
  const showStartCodexPrimary = canStartSoloPageWork;
  const showSteerCodexPrimary = !showStartCodexPrimary && canStopSoloPageWork;
  const showNotesPrimary = !showStartCodexPrimary && !showSteerCodexPrimary && !publicPage;
  const clientListLoading = listLoading && clients.length === 0;
  const clientSummaryText = clientListLoading
    ? `Loading converted clients in ${funnelLabel}`
    : clients.length
      ? `${clients.length} ${clients.length === 1 ? "client" : "clients"} in ${funnelLabel}${listLoading ? " · refreshing" : ""}`
      : `No converted clients in ${funnelLabel} yet`;
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
      <div className="ct-secondary">
        <p className="ct-secondary-note">{clientSummaryText}</p>
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
              <p className="ct-empty">Loading converted clients...</p>
            ) : (
              <p className="ct-empty">Convert a paid lead from CRM to open a client workspace.</p>
            )}
          </div>
        </aside>

        <section className="ct-detail workstation-detail">
          {!activeClient && clientListLoading ? (
            <p className="empty-note">Loading client workspace.</p>
          ) : !activeClient ? (
            <p className="empty-note">Select a converted client.</p>
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
                      disabled={!codexEnabled || actionBusy === "solo-page-steer"}
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
                  <div className="workstation-action-menu">
                    <button
                      type="button"
                      className={`ct-btn ct-btn-ghost ${actionsOpen ? "active" : ""}`}
                      onClick={() => setActionsOpen((current) => !current)}
                      aria-expanded={actionsOpen}
                      aria-haspopup="menu"
                    >
                      More
                      <CaretDown size={14} weight="bold" />
                    </button>
                    {actionsOpen ? (
                      <div className="workstation-action-popover" role="menu">
                        <div className="workstation-menu-group" role="presentation">
                          <span className="workstation-menu-label">Build controls</span>
                          <label
                            className="ct-codex-switch workstation-menu-switch"
                            role="menuitemcheckbox"
                            aria-checked={codexEnabled}
                            title={codexEnabled ? "Codex enabled for this lead" : "Codex disabled for this lead"}
                          >
                            <input
                              type="checkbox"
                              checked={codexEnabled}
                              disabled={!selectedLead || Boolean(actionBusy)}
                              onChange={(event) => onToggleLeadCodex(selectedLead, event.target.checked)}
                            />
                            <span>Codex</span>
                          </label>
                          {!showStartCodexPrimary ? (
                            <button
                              type="button"
                              role="menuitem"
                              onClick={openSoloPagePromptModal}
                              disabled={!canStartSoloPageWork}
                            >
                              <Robot size={16} weight="bold" />
                              <span>Start Codex</span>
                            </button>
                          ) : null}
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
                          {!showSteerCodexPrimary ? (
                            <button
                              type="button"
                              role="menuitem"
                              onClick={openSoloPageSteerModal}
                              disabled={!codexEnabled || !canStopSoloPageWork || actionBusy === "solo-page-steer"}
                            >
                              <PaperPlaneTilt size={16} weight="bold" />
                              <span>Steer Codex</span>
                            </button>
                          ) : null}
                        </div>

                        <div className="workstation-menu-group" role="presentation">
                          <span className="workstation-menu-label">Workstation actions</span>
                          <button
                            type="button"
                            role="menuitem"
                            onClick={openProfessionalPhotoModal}
                            disabled={!codexEnabled || workstationClosed || !imageAssets.length || professionalPhotoJobBusy || actionBusy === "professional-photo-start"}
                          >
                            <Camera size={16} weight="bold" />
                            <span>Professional photo</span>
                          </button>
                          {!showNotesPrimary ? (
                            <button
                              type="button"
                              role="menuitem"
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

                        <div className="workstation-menu-group" role="presentation">
                          <span className="workstation-menu-label">Client utilities</span>
                          <button
                            type="button"
                            role="menuitem"
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
                            role="menuitem"
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
                              role="menuitem"
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
                            role="menuitem"
                            className="workstation-menu-link"
                            href={`/api/workstation/clients/${activeClient.id}/zip`}
                            onClick={() => setActionsOpen(false)}
                          >
                            <DownloadSimple size={16} weight="bold" />
                            <span>Download ZIP</span>
                          </a>
                          <button
                            type="button"
                            role="menuitem"
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
                    ) : null}
                  </div>
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
                    <p className="empty-note">No media uploaded for this client yet.</p>
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
                    <p className="empty-note">
                      {professionalPhotoJobBusy ? "Waiting for the first result." : "No professional photo yet."}
                    </p>
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
  const [showSetupDetails, setShowSetupDetails] = useState(false);

  if (!funnel) {
    return (
      <div className="ct-funnel-setup">
        <p className="ct-empty">No funnel selected.</p>
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
        const hasSecondaryTags = (lead.tags ?? []).length > 0;
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
                  <span className="ct-lead-time">{relativeTime(lastInteractionAt(lead))}</span>
                </div>
                <div className="ct-lead-status-line">
                  <span className="ct-lead-stage" data-tone={tone}>{inboxMode ? "Inbox" : formatLeadStatusLabel(lead)}</span>
                  {turn ? <span className={`ct-lead-turn ${turn}`}>{turn === "needs_reply" ? "Needs reply" : "Answered"}</span> : null}
                  {hasOutboundError ? (
                    <span className="ct-lead-delivery-error" title={lead.latest_outbound_error || "WhatsApp delivery failed"}>
                      <WarningCircle size={13} weight="fill" />
                      Send failed
                    </span>
                  ) : null}
                </div>
                <p className="ct-lead-preview">{leadPreview(lead)}</p>
                <div className="ct-lead-meta">
                  <span className="ct-lead-meta-main">
                    <PhoneCountryFlag phone={lead.phone || lead.normalized_phone} />
                    <span>{lead.phone || "-"}</span>
                  </span>
                  {strategyTag ? <span className="ct-lead-context">{strategyTag}</span> : null}
                  {hasSecondaryTags ? <span className="ct-lead-context">{lead.tags.length} tag{lead.tags.length === 1 ? "" : "s"}</span> : null}
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
  onToggleCodex,
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
  onToggleCodex: (enabled: boolean) => void | Promise<void>;
  onCopyContext: () => void | Promise<void>;
  onOpenWorkstation: (clientId: string) => void | Promise<void>;
  copyStatus: string;
}) {
  const closed = isLeadClosed(lead);
  const archived = isLeadArchived(lead);
  const convertedMilestone = isLeadConverted(lead);
  const crmOutboundBlocked = closed || archived || convertedMilestone;
  const paused = Boolean(lead?.automation_paused);
  const codexEnabled = Boolean(lead?.codex_enabled);
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
            Build
          </button>
        ) : showBuildPrimary ? (
          <button
            type="button"
            className="ct-btn ct-btn-primary"
            disabled={!lead || closed || archived || Boolean(actionBusy)}
            onClick={onConvert}
          >
            <Robot size={15} weight="bold" />
            Build
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
            {!showBuildPrimary ? (
              <button
                type="button"
                className="ct-btn ct-btn-ghost"
                disabled={!lead || closed || archived || Boolean(actionBusy)}
                onClick={onConvert}
              >
                <CurrencyDollar size={15} weight="bold" />
                Convert
              </button>
            ) : null}
            <label className="ct-codex-switch" title={codexEnabled ? "Codex enabled for this lead" : "Codex disabled for this lead"}>
              <input
                type="checkbox"
                checked={codexEnabled}
                disabled={!lead || Boolean(actionBusy)}
                onChange={(event) => onToggleCodex(event.target.checked)}
              />
              <span>Codex</span>
            </label>
            <button type="button" className="ct-btn ct-btn-ghost" disabled={!lead} onClick={onCopyContext} title="Copy context">
              <Copy size={15} weight="bold" />
              Copy
            </button>
            {!hasWorkstationClient ? (
              <button
                type="button"
                className="ct-btn ct-btn-ghost"
                disabled={!lead || Boolean(actionBusy)}
                onClick={onStartSoloPage}
              >
                <Robot size={15} weight="bold" />
                Solo page
              </button>
            ) : null}
            {!inboxMode ? (
              <button type="button" className="ct-btn ct-btn-ghost" disabled={!lead || closed || convertedMilestone || Boolean(actionBusy)} onClick={onMarkConverted}>
                <CheckCircle size={15} weight="bold" />
                Mark converted
              </button>
            ) : null}
            {!inboxMode ? (
              <button type="button" className="ct-btn ct-btn-ghost" disabled={!lead || closed || paused || Boolean(actionBusy)} onClick={onPauseAutomation}>
                <PauseCircle size={15} weight="bold" />
                Pause
              </button>
            ) : null}
            {!inboxMode ? (
	              <button type="button" className="ct-btn ct-btn-ghost" disabled={!lead || closed || paused || Boolean(actionBusy)} onClick={onManualHandoff}>
	                <NotePencil size={15} weight="bold" />
	                Operator
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
    return <p className="empty-note">Select a lead from the list.</p>;
  }
  if (loading && !messages.length) {
    return <p className="empty-note">Loading messages...</p>;
  }
  if (!messages.length) {
    return <p className="empty-note">No messages for this lead yet.</p>;
  }

  return (
    <div className="ct-timeline" ref={timelineRef}>
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
                  <span className={`crm-message-author ${direction}`}>{message.from_me ? "Operator" : "Lead"}</span>
                  <span className="crm-message-meta-chips">
                    {meta.map((item, index) => (
                      <span key={`${item}:${index}`}>{item}</span>
                    ))}
                  </span>
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
      <form className="ct-modal-panel" role="dialog" aria-modal="true" aria-labelledby="ctSendModalTitle" onSubmit={onSubmit}>
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
      <form className="ct-modal-panel" role="dialog" aria-modal="true" aria-labelledby="ctBulkSendModalTitle" onSubmit={onSubmit}>
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
            {availableOptions.map((option) => (
              <label className="ct-send-option" key={option.value}>
                <input
                  type="radio"
                  name="ctBulkSendKind"
                  value={option.value}
                  disabled={(option.value !== "set-tags" && bulkOutboundBlocked) || (option.value === "custom" && customBlocked)}
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
  activeSheetFilter: string,
): DeliverySheetLeadSection[] {
  const leadsBySource = new Map<string, ClientLead[]>();
  for (const lead of visibleLeads) {
    leadsBySource.set(lead.source_id, [...(leadsBySource.get(lead.source_id) ?? []), lead]);
  }

  return sources
    .filter((source) => activeSheetFilter === "all" || source.id === activeSheetFilter)
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
    return [selectedSourceId];
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

function formatConversionType(type: LeadSummary["conversion_type"]): string {
  const labels: Record<string, string> = {
    manual: "operator mark",
    meeting: "meeting link",
    workstation: "Workstation",
  };
  return type ? labels[type] ?? humanize(type) : "conversion";
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

function strategyTagForLead(lead: LeadSummary): string {
  const assignments = lead.strategy_assignments ?? [];
  const loomAssignment = assignments.find((assignment) => assignment.step === "loom") ?? assignments[0];
  return loomAssignment?.strategy_label || "";
}

function leadPreview(lead: LeadSummary): string {
  if (isLeadClosed(lead)) {
    return "Lead marked as closed.";
  }
  if (isLeadConverted(lead)) {
    return `Converted by ${formatConversionType(lead.conversion_type)}.`;
  }
  if (lead.meeting_scheduled_at) {
    return `Meeting scheduled ${relativeTime(lead.meeting_scheduled_at)}.`;
  }
  if (lead.last_classification_reason) {
    return truncate(lead.last_classification_reason, 120);
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
  return Boolean(lead.booked_at);
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
