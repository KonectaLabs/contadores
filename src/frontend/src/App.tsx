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
import { apiFetch as baseApiFetch } from "./api";
import { parseActiveSection } from "./app/sections";
import type { ActiveSection, OperationNavItem } from "./app/sections";
import { compactNumber, humanize, lastInteractionAt, relativeTime, shortDate } from "./format";
import { ClientLeadDeliveryView } from "./workspaces/delivery/ClientLeadDeliveryView";
import { CampaignsPanel } from "./workspaces/campaigns/CampaignsPanel";
import { campaignStatusConfirmText, shouldApplyGeoSearchResult } from "./workspaces/campaigns/helpers";
import { CrmWorkspace } from "./workspaces/crm/CrmWorkspace";
import { shouldApplyLatestRequest } from "./workspaces/delivery/helpers";
import { OpsView } from "./workspaces/ops/OpsView";
import { copyTextToClipboard, WorkstationView } from "./workspaces/workstation/WorkstationView";
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
  PlatformOverviewResponse,
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
const WHATSAPP_CUSTOM_WINDOW_MS = 24 * 60 * 60 * 1000;
const CSRF_COOKIE_NAME = "contadores_csrf";
const CSRF_HEADER_NAME = "X-CSRF-Token";
const UNSAFE_API_METHODS = new Set(["POST", "PUT", "PATCH", "DELETE"]);
const CRM_MANUAL_MEDIA_MAX_FILES = 5;
const CRM_MANUAL_MEDIA_MAX_FILE_BYTES = 25 * 1024 * 1024;
const CRM_MANUAL_MEDIA_MAX_TOTAL_BYTES = 50 * 1024 * 1024;
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
type LoadWorkstationDetailOptions = {
  syncNotes?: boolean;
  showLoading?: boolean;
};
export type DeliveryEditorMode = "edit" | "create";
type ConfirmDialogTone = "danger" | "warn";
export type ConfirmDialogState = {
  id: string;
  tone: ConfirmDialogTone;
  title: string;
  message: string;
  confirmLabel: string;
  busyLabel: string;
  busyKey: string;
  onConfirm: () => void | Promise<void>;
};
type ManualDraft = {
  text: string;
  files: File[];
};
const emptyManualDraft: ManualDraft = { text: "", files: [] };
const CONFIRM_FOCUSABLE_SELECTOR = [
  "button:not([disabled])",
  "input:not([disabled])",
  "select:not([disabled])",
  "textarea:not([disabled])",
  "a[href]",
  "[tabindex]:not([tabindex='-1'])",
].join(",");
export type ClientLeadSourceDraft = {
  id: string;
  label: string;
  enabled: boolean;
  sheet_url: string;
  sheet_gid: string;
  sheet_tab_name: string;
  sheet_poll_seconds: number;
  meta_page_id: string;
  meta_lead_form_id: string;
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
  meta_page_id: string | null;
  meta_lead_form_id: string | null;
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

function readCookieValue(name: string): string {
  const prefix = `${name}=`;
  const match = document.cookie
    .split(";")
    .map((item) => item.trim())
    .find((item) => item.startsWith(prefix));
  return match ? decodeURIComponent(match.slice(prefix.length)) : "";
}

function apiFetch<T>(path: string, options: RequestInit & { timeoutMs?: number } = {}): Promise<T> {
  const method = String(options.method || "GET").toUpperCase();
  if (!UNSAFE_API_METHODS.has(method)) {
    return baseApiFetch<T>(path, options);
  }

  const headers = new Headers(options.headers);
  const csrfToken = readCookieValue(CSRF_COOKIE_NAME);
  if (csrfToken && !headers.has(CSRF_HEADER_NAME)) {
    headers.set(CSRF_HEADER_NAME, csrfToken);
  }
  return baseApiFetch<T>(path, { ...options, headers });
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

export function CtEmptyState({
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
  return parseActiveSection(readStoredValue(DASHBOARD_SECTION_STORAGE_KEY));
}

const operations: OperationNavItem[] = [
  {
    section: "ops",
    label: "Ops",
    icon: <Pulse size={15} weight="bold" />,
  },
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
  const [opsOverview, setOpsOverview] = useState<PlatformOverviewResponse | null>(null);
  const [opsLoading, setOpsLoading] = useState(false);
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
  const [manualDraftsByLeadId, setManualDraftsByLeadId] = useState<Record<string, ManualDraft>>({});
  const [sendModalLeadId, setSendModalLeadId] = useState<string | null>(null);
  const [sendModalText, setSendModalText] = useState("");
  const [bulkManualText, setBulkManualText] = useState("");
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
  const [deliverySyncStatus, setDeliverySyncStatus] = useState("");
  const [campaignRefreshSignal, setCampaignRefreshSignal] = useState(0);
  const [acknowledgingDeliveryErrorIds, setAcknowledgingDeliveryErrorIds] = useState<number[]>([]);
  const [leadContextCopyStatus, setLeadContextCopyStatus] = useState("");
  const detailRequestId = useRef(0);
  const dashboardRequestId = useRef(0);
  const workstationDetailRequestId = useRef(0);
  const workstationListRequestId = useRef(0);
  const workstationLoadingRequestId = useRef(0);
  const selectedWorkstationClientIdRef = useRef<string | null>(null);
  const workstationNotesDraftByClientId = useRef<Record<string, string>>({});
  const workstationNotesSavedByClientId = useRef<Record<string, string>>({});
  const deliveryDraftSourceId = useRef<string | null>(null);
  const deliverySourcesRef = useRef<ClientLeadSource[]>([]);
  const selectedDeliverySourceIdRef = useRef<string | null>(null);
  const deliveryLeadsRequestId = useRef(0);
  const deliveryRecipientChatRequestId = useRef(0);
  const previousFunnelIdRef = useRef(selectedFunnelId);
  const crmWorkspaceRef = useRef<HTMLDivElement | null>(null);
  const debouncedQuery = useDebouncedValue(query, 250);
  const debouncedWorkstationQuery = useDebouncedValue(workstationQuery, 250);

  const workstationNotesDirty = Boolean(
    selectedWorkstationClientId
    && workstationNotesDraft !== (workstationNotesSavedByClientId.current[selectedWorkstationClientId] ?? ""),
  );

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
  const opsBlockerCount = opsOverview?.counts.active_blockers ?? 0;

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
  const selectedManualDraft = selectedLeadId ? manualDraftsByLeadId[selectedLeadId] ?? emptyManualDraft : emptyManualDraft;
  const sendModalLead = sendModalLeadId
    ? (sendModalLeadId === selectedLead?.id ? selectedLead : leadList?.leads.find((lead) => lead.id === sendModalLeadId) ?? null)
    : selectedLead;
  const sendModalCustomBlockReason = sendModalLeadId === selectedLeadId
    ? selectedLeadCustomBlockReason
    : customMessageBlockReason(sendModalLead);
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
  const deliverySourceDraftDirty = isDeliverySourceDraftDirty(deliverySourceDraft, selectedDeliverySource, deliveryEditorMode);
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

  const loadOpsOverview = useCallback(async () => {
    setOpsLoading(true);
    try {
      const payload = await apiFetch<PlatformOverviewResponse>("/api/platform/overview");
      setOpsOverview(payload);
    } finally {
      setOpsLoading(false);
    }
  }, []);

  const syncWorkstationNotesFromServer = useCallback((clientId: string, notes: string, forceDraft = false) => {
    const previousSaved = workstationNotesSavedByClientId.current[clientId] ?? "";
    const previousDraft = workstationNotesDraftByClientId.current[clientId] ?? previousSaved;
    const dirty = previousDraft !== previousSaved;
    const nextDraft = forceDraft || !dirty ? notes : previousDraft;
    workstationNotesSavedByClientId.current = { ...workstationNotesSavedByClientId.current, [clientId]: notes };
    workstationNotesDraftByClientId.current = { ...workstationNotesDraftByClientId.current, [clientId]: nextDraft };
    if (selectedWorkstationClientIdRef.current === clientId) {
      setWorkstationNotesDraft(nextDraft);
    }
  }, []);

  const updateSelectedWorkstationNotesDraft = useCallback((notes: string) => {
    const clientId = selectedWorkstationClientIdRef.current;
    if (clientId) {
      workstationNotesDraftByClientId.current = { ...workstationNotesDraftByClientId.current, [clientId]: notes };
    }
    setWorkstationNotesDraft(notes);
  }, []);

  function cachedWorkstationNotesDraft(clientId: string): string {
    return workstationNotesDraftByClientId.current[clientId] ?? workstationNotesSavedByClientId.current[clientId] ?? "";
  }

  const loadWorkstation = useCallback(async () => {
    const requestId = workstationListRequestId.current + 1;
    workstationListRequestId.current = requestId;
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
      if (workstationListRequestId.current !== requestId) {
        return;
      }
      setWorkstationList(payload);
      setSelectedWorkstationClientId((current) => {
        if (current && payload.clients.some((client) => client.id === current)) {
          return current;
        }
        return payload.clients[0]?.id ?? null;
      });
    } finally {
      if (workstationListRequestId.current === requestId) {
        setWorkstationListLoading(false);
      }
    }
  }, [debouncedWorkstationQuery, selectedFunnelId]);

  const loadDeliverySources = useCallback(async () => {
    const payload = await apiFetch<ClientLeadSourceListResponse | ClientLeadSource[]>("/api/client-lead-sources");
    const sources = unpackClientLeadSources(payload).slice().sort(compareDeliverySources);
    deliverySourcesRef.current = sources;
    setDeliverySources(sources);
    setSelectedDeliverySourceId((current) => {
      let nextSelected: string | null;
      if (deliveryEditorMode === "create") {
        nextSelected = current;
      } else if (current && sources.some((source) => source.id === current)) {
        nextSelected = current;
      } else {
        nextSelected = sources[0]?.id ?? null;
      }
      selectedDeliverySourceIdRef.current = nextSelected;
      return nextSelected;
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
    const requestId = deliveryLeadsRequestId.current + 1;
    deliveryLeadsRequestId.current = requestId;
    const sourceKey = sourceIds.join("|");
    if (!sourceIds.length) {
      if (shouldApplyLatestRequest(requestId, deliveryLeadsRequestId.current)) {
        setDeliveryLeads([]);
      }
      return;
    }
    const batches = await Promise.all(sourceIds.map((sourceId) => fetchDeliveryLeads(sourceId)));
    const currentSourceId = selectedDeliverySourceIdRef.current;
    const currentSourceKey = currentSourceId
      ? deliveryContactSourceIdsFor(deliverySourcesRef.current, currentSourceId).join("|")
      : "";
    if (shouldApplyLatestRequest(requestId, deliveryLeadsRequestId.current) && currentSourceKey === sourceKey) {
      setDeliveryLeads(batches.flat().sort(compareClientLeads));
    }
  }, [fetchDeliveryLeads]);

  const loadDeliveryRecipientChat = useCallback(async (sourceId: string) => {
    const requestId = deliveryRecipientChatRequestId.current + 1;
    deliveryRecipientChatRequestId.current = requestId;
    const payload = await apiFetch<ClientLeadRecipientChatResponse>(
      `/api/client-lead-sources/${encodeURIComponent(sourceId)}/recipient-chat`,
    );
    if (deliveryRecipientChatRequestId.current === requestId && selectedDeliverySourceIdRef.current === sourceId) {
      setDeliveryRecipientChat(payload);
    }
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
          syncWorkstationNotesFromServer(clientId, payload.notes ?? "");
        }
        return payload;
      }
      return null;
    } finally {
      if (showLoading && workstationLoadingRequestId.current === loadingRequestId) {
        setWorkstationLoading(false);
      }
    }
  }, [syncWorkstationNotesFromServer]);

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
    selectedDeliverySourceIdRef.current = selectedDeliverySourceId;
  }, [selectedDeliverySourceId]);

  useEffect(() => {
    selectedWorkstationClientIdRef.current = selectedWorkstationClientId;
  }, [selectedWorkstationClientId]);

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
        if (activeSection === "ops") {
          loaders.push(loadOpsOverview());
        }
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
  }, [activeSection, loadDashboard, loadDeliveryLeadsForSources, loadDeliveryRecipientChat, loadDeliverySources, loadOpsOverview, selectedDeliverySourceId]);

  useEffect(() => {
    if (activeSection !== "ops") {
      return;
    }
    loadOpsOverview().catch((reason) => {
      setError(reason instanceof Error ? reason.message : "Could not load Ops overview.");
    });
  }, [activeSection, loadOpsOverview]);

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
      deliveryLeadsRequestId.current += 1;
      deliveryRecipientChatRequestId.current += 1;
      setDeliveryLeads([]);
      setDeliveryRecipientChat(null);
      return;
    }

    const source = deliverySources.find((item) => item.id === selectedDeliverySourceId) ?? null;
    if (!source) {
      deliveryDraftSourceId.current = null;
      deliveryLeadsRequestId.current += 1;
      deliveryRecipientChatRequestId.current += 1;
      setDeliverySourceDraft(buildBlankClientLeadSourceDraft());
      setDeliveryLeads([]);
      setDeliveryRecipientChat(null);
      return;
    }

    if (deliveryDraftSourceId.current !== source.id) {
      deliveryDraftSourceId.current = source.id;
      setDeliverySourceDraft(clientLeadSourceToDraft(source));
      setDeliveryCopyStatus("");
      setDeliveryLeads([]);
      setDeliveryRecipientChat(null);
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
    selectedWorkstationClientIdRef.current = selectedWorkstationClientId;
    setWorkstationNotesDraft(cachedWorkstationNotesDraft(selectedWorkstationClientId));
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
          if (selectedWorkstationClientIdRef.current === payload.client_id) {
            await loadWorkstationDetail(payload.client_id);
          }
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
      if (activeSection === "ops") {
        await loadOpsOverview();
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

  function updateManualDraft(leadId: string, patch: Partial<ManualDraft>) {
    setManualDraftsByLeadId((current) => {
      const currentDraft = current[leadId] ?? emptyManualDraft;
      const nextDraft = {
        text: patch.text ?? currentDraft.text,
        files: patch.files ?? currentDraft.files,
      };
      const nextDraftHasContent = Boolean(nextDraft.text.trim() || nextDraft.files.length);
      if (!nextDraftHasContent) {
        const remaining = { ...current };
        delete remaining[leadId];
        return remaining;
      }
      return { ...current, [leadId]: nextDraft };
    });
  }

  function clearManualDraft(leadId: string) {
    setManualDraftsByLeadId((current) => {
      const remaining = { ...current };
      delete remaining[leadId];
      return remaining;
    });
  }

  function setSelectedManualText(text: string) {
    if (selectedLeadId) {
      updateManualDraft(selectedLeadId, { text });
    }
  }

  function setSelectedManualFiles(files: File[]) {
    if (selectedLeadId) {
      updateManualDraft(selectedLeadId, { files });
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

  function guardDeliverySourceDraft(action: () => void) {
    if (!deliverySourceDraftDirty) {
      action();
      return;
    }
    const label = selectedDeliverySource?.label || deliverySourceDraft.label || "this Delivery source";
    setConfirmDialog({
      id: `delivery-source-discard:${Date.now()}`,
      tone: "warn",
      title: "Discard Delivery edits?",
      message: `Discard unsaved changes to ${label}? Sheet URL, recipient, template, and mapping edits will be lost.`,
      confirmLabel: "Discard edits",
      busyLabel: "Discarding...",
      busyKey: "delivery-discard",
      onConfirm: action,
    });
  }

  function selectDeliverySource(sourceId: string) {
    selectedDeliverySourceIdRef.current = sourceId;
    setDeliverySourceEditorError("");
    setDeliverySyncStatus("");
    setDeliveryEditorMode("edit");
    setSelectedDeliverySourceId(sourceId);
  }

  function startNewDeliverySource() {
    selectedDeliverySourceIdRef.current = null;
    setDeliveryEditorMode("create");
    setSelectedDeliverySourceId(null);
    deliveryDraftSourceId.current = null;
    setDeliveryLeads([]);
    setDeliveryRecipientChat(null);
    setDeliveryCopyStatus("");
    setDeliverySyncStatus("");
    setDeliverySourceEditorError("");
    setDeliverySourceDraft(buildBlankClientLeadSourceDraft());
  }

  async function syncSelectedDeliverySources() {
    if (!selectedDeliverySourceId || actionBusy) {
      return;
    }
    const sourceIds = deliveryContactSourceIdsFor(deliverySourcesRef.current, selectedDeliverySourceId);
    if (!sourceIds.length) {
      return;
    }

    setActionBusy("delivery-sync");
    setDeliverySyncStatus(`Syncing ${sourceIds.length} ${sourceIds.length === 1 ? "sheet" : "sheets"}...`);
    try {
      const results = await Promise.allSettled(
        sourceIds.map((sourceId) => apiFetch<{ imported?: number; updated?: number; queued?: number }>(
          `/api/client-lead-sources/${encodeURIComponent(sourceId)}/sync`,
          { method: "POST" },
        )),
      );
      const updatedSources = await loadDeliverySources();
      const updatedSourceIds = deliveryContactSourceIdsFor(updatedSources, selectedDeliverySourceId);
      await Promise.all([
        loadDeliveryLeadsForSources(updatedSourceIds),
        loadDeliveryRecipientChat(selectedDeliverySourceId),
      ]);
      const failures = results.filter((result) => result.status === "rejected");
      const imported = results.reduce((total, result) => total + (result.status === "fulfilled" ? result.value.imported ?? 0 : 0), 0);
      const updated = results.reduce((total, result) => total + (result.status === "fulfilled" ? result.value.updated ?? 0 : 0), 0);
      const queued = results.reduce((total, result) => total + (result.status === "fulfilled" ? result.value.queued ?? 0 : 0), 0);
      if (failures.length) {
        const reason = failures[0].reason;
        const message = reason instanceof Error ? reason.message : "Could not sync Delivery.";
        setDeliverySyncStatus(`${results.length - failures.length}/${results.length} synced. ${message}`);
        setError(message);
      } else {
        setDeliverySyncStatus(`Synced ${sourceIds.length} ${sourceIds.length === 1 ? "sheet" : "sheets"} · ${imported} new · ${updated} updated · ${queued} queued`);
      }
    } catch (reason) {
      const message = reason instanceof Error ? reason.message : "Could not sync Delivery.";
      setDeliverySyncStatus(message);
      setError(message);
    } finally {
      setActionBusy(null);
    }
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
      const editSourceId = deliveryEditorMode === "edit"
        ? deliveryDraftSourceId.current ?? selectedDeliverySourceId ?? selectedDeliverySource?.id ?? null
        : null;
      const saveSourceId = editSourceId ?? payload.id;
      const method = editSourceId ? "PUT" : "POST";
      const path = method === "PUT"
        ? `/api/client-lead-sources/${encodeURIComponent(saveSourceId)}`
        : "/api/client-lead-sources";
      const saved = await apiFetch<ClientLeadSource>(path, {
        method,
        body: JSON.stringify(editSourceId ? { ...payload, id: saveSourceId } : payload),
      });
      setDeliveryEditorMode("edit");
      const savedSourceId = saved.id || editSourceId || payload.id;
      selectedDeliverySourceIdRef.current = savedSourceId;
      setSelectedDeliverySourceId(savedSourceId);
      deliveryDraftSourceId.current = savedSourceId;
      setDeliverySourceDraft(clientLeadSourceToDraft(saved));
      const updatedSources = await loadDeliverySources();
      const sourceIds = deliveryContactSourceIdsFor(updatedSources, savedSourceId);
      await loadDeliveryLeadsForSources(sourceIds);
      await loadDeliveryRecipientChat(savedSourceId);
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
          selectedDeliverySourceIdRef.current = null;
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
      selectedWorkstationClientIdRef.current = payload.client.id;
      syncWorkstationNotesFromServer(payload.client.id, payload.notes ?? "", true);
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
      selectedWorkstationClientIdRef.current = payload.client.id;
      syncWorkstationNotesFromServer(payload.client.id, payload.notes ?? "", true);
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
    selectedWorkstationClientIdRef.current = clientId;
    setSelectedWorkstationClientId(clientId);
    setWorkstationDetail((current) => current?.client.id === clientId ? current : null);
    setWorkstationNotesDraft(cachedWorkstationNotesDraft(clientId));
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
      syncWorkstationNotesFromServer(clientId, payload.notes ?? "", true);
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

  function stopSoloPageCodexWork() {
    const clientId = workstationDetail?.client.id ?? selectedWorkstationClientId;
    const clientName = workstationDetail?.client.display_name || "this client";
    if (!clientId) {
      return;
    }
    setConfirmDialog({
      id: `solo-page-stop-${clientId}`,
      tone: "warn",
      title: "Stop live Codex run?",
      message: `${clientName}: stop the active live Codex run for this Workstation client.`,
      confirmLabel: "Stop Codex",
      busyLabel: "Stopping...",
      busyKey: "solo-page-stop",
      onConfirm: async () => {
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
      },
    });
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
          syncWorkstationNotesFromServer(clientId, payload.notes ?? "", true);
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

  function requestQuickAction(action: QuickActionName) {
    const leadName = selectedLead?.full_name || selectedLead?.phone || "this chat";
    const confirmations: Partial<Record<QuickActionName, { title: string; message: string; label: string; tone?: ConfirmDialogTone }>> = {
      "mark-converted": {
        title: "Mark lead converted?",
        message: `${leadName} will move into a converted state and CRM follow-up will stop.`,
        label: "Mark converted",
      },
      "pause-automation": {
        title: "Pause automation?",
        message: `${leadName} will stop receiving automatic CRM follow-up until an operator resumes or routes it.`,
        label: "Pause automation",
      },
      "manual-handoff": {
        title: "Send to operator review?",
        message: `${leadName} will be held for manual review instead of continuing the automatic sequence.`,
        label: "Send to review",
      },
      close: {
        title: "Close lead?",
        message: `${leadName} will leave the active CRM queue and automation will stop for this lead.`,
        label: "Close lead",
        tone: "danger",
      },
      reopen: {
        title: "Reopen lead?",
        message: `${leadName} will return to the active CRM queue. Review automation before sending anything new.`,
        label: "Reopen lead",
      },
    };
    const confirmation = confirmations[action];
    if (!confirmation) {
      void runAction(action);
      return;
    }
    setConfirmDialog({
      id: `quick-action-${action}-${selectedLead?.id ?? selectedLeadId ?? Date.now()}`,
      tone: confirmation.tone ?? "warn",
      title: confirmation.title,
      message: confirmation.message,
      confirmLabel: confirmation.label,
      busyLabel: "Saving...",
      busyKey: action,
      onConfirm: () => runAction(action),
    });
  }

  async function submitSendModal(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const leadId = sendModalLeadId ?? selectedLead?.id ?? selectedLeadId;
    if (!leadId) {
      setError("Select a chat before sending a message.");
      return;
    }

    setActionBusy("send-modal");
    try {
      if (isLeadClosed(sendModalLead)) {
        setError("This lead is closed. Reopen it before sending WhatsApp messages.");
        return;
      }
      if (sendKind === "custom") {
        const text = sendModalText.trim();
        if (!text) {
          setError("Write a message before sending.");
          return;
        }
        if (sendModalCustomBlockReason) {
          setError(sendModalCustomBlockReason);
          return;
        }
        await queueCustomManualMessage(leadId, text);
      } else {
        await apiFetch<QuickActionResponse>(`/api/contadores/leads/${leadId}/actions/${sendKind}`, {
          method: "POST",
        });
      }
      setShowSendModal(false);
      setSendModalLeadId(null);
      if (sendKind === "custom") {
        setSendModalText("");
      }
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
          text: bulkSendKind === "custom" ? bulkManualText.trim() : null,
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
        setBulkManualText("");
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
    const draft = leadId ? manualDraftsByLeadId[leadId] ?? emptyManualDraft : emptyManualDraft;
    const text = draft.text.trim();
    if (!leadId || (!text && !draft.files.length)) {
      return;
    }
    if (selectedLeadCustomBlockReason) {
      setError(selectedLeadCustomBlockReason);
      return;
    }

    setActionBusy("manual-dock");
    try {
      await queueCustomManualMessage(leadId, text, draft.files);
      clearManualDraft(leadId);
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
        : activeSection === "ops"
          ? "Ops"
          : "CRM";
  const syncStatus = activeSection === "workstation"
    ? `${workstationClients.length} converted ${workstationClients.length === 1 ? "client" : "clients"}`
    : activeSection === "ops"
    ? `${compactNumber(opsBlockerCount)} active ${opsBlockerCount === 1 ? "blocker" : "blockers"}`
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
    : activeSection === "ops"
      ? opsBlockerCount === 0
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
              : operation.section === "ops" && opsBlockerCount
                ? opsBlockerCount
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
            disabled={loading || deliveryLoading || opsLoading}
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

        {activeSection === "ops" ? (
          <OpsView
            overview={opsOverview}
            loading={opsLoading}
            onRefresh={() => {
              loadOpsOverview().catch((reason) => {
                setError(reason instanceof Error ? reason.message : "Could not load Ops overview.");
              });
            }}
            onOpenCrmLead={(leadId) => {
              setSelectedLeadId(leadId);
              setActiveSection("crm");
            }}
            onOpenCampaigns={() => setActiveSection("campaigns")}
            onOpenWorkstation={(clientId) => {
              selectedWorkstationClientIdRef.current = clientId;
              setSelectedWorkstationClientId(clientId);
              setActiveSection("workstation");
            }}
          />
        ) : activeSection === "campaigns" ? (
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
          notesDirty={workstationNotesDirty}
          fileTitle={workstationFileTitle}
          file={workstationFile}
          selectedProfessionalPhotoMediaIds={professionalPhotoMediaIds}
          professionalPhotoContext={professionalPhotoContext}
          professionalPhotoEditPrompts={professionalPhotoEditPrompts}
          professionalPhotoJob={professionalPhotoJob}
          onSelectClient={(clientId) => {
            const switchingClient = selectedWorkstationClientId !== clientId;
            selectedWorkstationClientIdRef.current = clientId;
            setSelectedWorkstationClientId(clientId);
            if (switchingClient) {
              setWorkstationDetail(null);
              setWorkstationNotesDraft(cachedWorkstationNotesDraft(clientId));
            }
            setProfessionalPhotoMediaIds([]);
            setProfessionalPhotoContext("");
            setProfessionalPhotoEditPrompts({});
          }}
          onNotesChange={updateSelectedWorkstationNotesDraft}
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
            syncStatus={deliverySyncStatus}
            sourceEditorError={deliverySourceEditorError}
            sourceDraftDirty={deliverySourceDraftDirty}
            onDiscardSourceDraft={guardDeliverySourceDraft}
            onSelectSource={selectDeliverySource}
            onNewSource={startNewDeliverySource}
            onDraftChange={(nextDraft) => {
              setDeliverySourceEditorError("");
              setDeliverySourceDraft(nextDraft);
            }}
            onSaveSource={saveDeliverySource}
            onDeleteSource={deleteDeliverySource}
            onSyncSources={syncSelectedDeliverySources}
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
        <CrmWorkspace
          setupBanner={selectedFunnel && selectedFunnel.kind === "campaign" && selectedFunnelSetupIssues.length ? (
            <FunnelSetupBanner
              setupIssues={selectedFunnelSetupIssues}
              onEdit={openEditFunnel}
            />
          ) : null}
          isInboxFunnel={isInboxFunnel}
          crmHeroTitle={crmHeroTitle}
          crmHeroDetail={crmHeroDetail}
          crmModeLabel={crmModeLabel}
          crmHeroMetrics={crmHeroMetrics}
          activeLeadViewLabel={activeLeadView.label}
          activeCrmFilterCount={activeCrmFilterCount}
          onClearCrmFilters={clearCrmFilters}
          leadViewFilters={leadViewFilters}
          leadViewFilter={leadViewFilter}
          onLeadViewFilterChange={setLeadViewFilter}
          metrics={metrics ?? null}
          strategyStats={strategyStats}
          strategyFilter={strategyFilter}
          onStrategyFilterChange={setStrategyFilter}
          tagOptions={tagOptions}
          tagFilter={tagFilter}
          onTagFilterChange={setTagFilter}
          formatStrategyLabel={formatStrategyLabel}
          workspaceRef={crmWorkspaceRef}
          crmLeadsWidth={crmLeadsWidth}
          crmLeadListTitle={crmLeadListTitle}
          visibleCount={visibleCount}
          crmLeadListSummary={crmLeadListSummary}
          allVisibleSelected={allVisibleSelected}
          hasVisibleLeads={Boolean(visibleLeadIds.length)}
          onToggleAllVisibleLeads={toggleAllVisibleLeads}
          selectedVisibleCount={selectedVisibleCount}
          actionBusy={actionBusy}
          onOpenBulkAction={() => {
            setBulkSendKind("custom");
            setBulkManualText("");
            setBulkManualPingConfirmed(false);
            setShowBulkSendModal(true);
          }}
          leadList={(
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
          )}
          onStartResize={startCrmLeadsResize}
          detailHeader={(
            <LeadDetailHeader
              lead={selectedLead}
              actionBusy={actionBusy}
              onOpenSend={() => {
                setSendKind("custom");
                setSendModalLeadId(selectedLead?.id ?? selectedLeadId);
                setSendModalText(selectedManualDraft.text);
                setShowSendModal(true);
              }}
              onMarkConverted={() => requestQuickAction("mark-converted")}
              onPauseAutomation={() => requestQuickAction("pause-automation")}
              onManualHandoff={() => requestQuickAction("manual-handoff")}
              onMarkAnswered={() => runAction("mark-answered")}
              onToggleClosed={() => requestQuickAction(isLeadClosed(selectedLead) ? "reopen" : "close")}
              onDelete={deleteLead}
              onConvert={convertLeadToWorkstation}
              onStartSoloPage={startSoloPageWorkstation}
              onCopyContext={copySelectedLeadContext}
              onOpenWorkstation={openWorkstationClient}
              copyStatus={leadContextCopyStatus}
              inboxMode={isInboxFunnel}
            />
          )}
          pausedBanner={!isInboxFunnel ? <PausedBanner lead={selectedLead} /> : null}
          campaignRoutingPanel={isInboxFunnel ? (
            <CampaignRoutingPanel
              lead={selectedLead}
              funnels={funnels}
              busy={actionBusy === "route-lead"}
              onRoute={routeLeadToCampaign}
            />
          ) : null}
          messageTimeline={(
            <MessageTimeline
              messages={selectedLeadDetail?.messages ?? []}
              loading={detailLoading}
              hasLead={Boolean(selectedLead)}
              acknowledgingIds={acknowledgingDeliveryErrorIds}
              onAcknowledgeDeliveryError={acknowledgeDeliveryError}
            />
          )}
          manualDockOpen={Boolean(selectedManualDraft.text.trim() || selectedManualDraft.files.length)}
          manualDock={(
            <ManualDock
              disabled={!selectedLead || Boolean(actionBusy)}
              blockReason={selectedLeadCustomBlockReason}
              value={selectedManualDraft.text}
              files={selectedManualDraft.files}
              onChange={setSelectedManualText}
              onFilesChange={setSelectedManualFiles}
              onSubmit={submitManualDock}
            />
          )}
        />
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
          text={sendModalText}
          funnel={selectedFunnel}
          customBlockReason={sendModalCustomBlockReason}
          busy={actionBusy === "send-modal"}
          onKindChange={setSendKind}
          onTextChange={setSendModalText}
          onClose={() => {
            setShowSendModal(false);
            setSendModalLeadId(null);
          }}
          onSubmit={submitSendModal}
        />
      ) : null}

      {showBulkSendModal ? (
        <BulkSendModal
          kind={bulkSendKind}
          text={bulkManualText}
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
          onTextChange={setBulkManualText}
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

export function ConfirmDialog({
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

export function SoloPageSteerModal({
  clientName,
  message,
  busy,
  onMessageChange,
  onClose,
  onSubmit,
}: {
  clientName: string;
  message: string;
  busy: boolean;
  onMessageChange: (value: string) => void;
  onClose: () => void;
  onSubmit: (event: FormEvent<HTMLFormElement>) => void;
}) {
  const [reviewing, setReviewing] = useState(false);
  const cleanMessage = message.trim();

  function handleSubmit(event: FormEvent<HTMLFormElement>) {
    if (!reviewing) {
      event.preventDefault();
      setReviewing(true);
      return;
    }
    onSubmit(event);
  }

  return (
    <div className="ct-modal open" aria-hidden="false">
      <button className="ct-modal-overlay" type="button" onClick={onClose} aria-label="Cerrar steer de Codex" />
      <form className="ct-modal-panel workstation-solo-page-modal" role="dialog" aria-modal="true" aria-labelledby="workstationSoloPageSteerModalTitle" onSubmit={handleSubmit}>
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
              onChange={(event) => {
                setReviewing(false);
                onMessageChange(event.target.value);
              }}
              placeholder="Segui, pero usá un tono más sobrio y no uses la foto del logo..."
              rows={6}
              autoFocus
            />
          </label>
          {reviewing ? (
            <section className="workstation-codex-review">
              <span>Review</span>
              <strong>{clientName}</strong>
              <pre>{cleanMessage}</pre>
            </section>
          ) : null}
        </div>
        <footer className="ct-modal-foot">
          <button type="button" className="ct-btn ct-btn-ghost" onClick={onClose}>Cancel</button>
          <button type="submit" className="ct-btn ct-btn-primary" disabled={!cleanMessage || busy}>
            {busy ? <SpinnerGap className="workstation-spinner" size={15} weight="bold" /> : <PaperPlaneTilt size={15} weight="bold" />}
            {busy ? "Enviando..." : reviewing ? "Confirmar envio" : "Review"}
          </button>
        </footer>
      </form>
    </div>
  );
}

export function SoloPagePromptModal({
  clientName,
  prompt,
  busy,
  onPromptChange,
  onClose,
  onSubmit,
}: {
  clientName: string;
  prompt: string;
  busy: boolean;
  onPromptChange: (value: string) => void;
  onClose: () => void;
  onSubmit: (event: FormEvent<HTMLFormElement>) => void;
}) {
  const [reviewing, setReviewing] = useState(false);
  const cleanPrompt = prompt.trim();

  function handleSubmit(event: FormEvent<HTMLFormElement>) {
    if (!reviewing) {
      event.preventDefault();
      setReviewing(true);
      return;
    }
    onSubmit(event);
  }

  return (
    <div className="ct-modal open" aria-hidden="false">
      <button className="ct-modal-overlay" type="button" onClick={onClose} aria-label="Cerrar prompt de Codex" />
      <form className="ct-modal-panel workstation-solo-page-modal" role="dialog" aria-modal="true" aria-labelledby="workstationSoloPageModalTitle" onSubmit={handleSubmit}>
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
              onChange={(event) => {
                setReviewing(false);
                onPromptChange(event.target.value);
              }}
              placeholder="Hey, ponete a trabajar y hacele la pagina. Usá lo que ya mandó, priorizá..."
              rows={7}
              autoFocus
            />
          </label>
          {reviewing ? (
            <section className="workstation-codex-review">
              <span>Review</span>
              <strong>{clientName}</strong>
              <pre>{cleanPrompt}</pre>
            </section>
          ) : null}
        </div>
        <footer className="ct-modal-foot">
          <button type="button" className="ct-btn ct-btn-ghost" onClick={onClose}>Cancel</button>
          <button type="submit" className="ct-btn ct-btn-primary" disabled={!cleanPrompt || busy}>
            {busy ? <SpinnerGap className="workstation-spinner" size={15} weight="bold" /> : <Robot size={15} weight="bold" />}
            {busy ? "Arrancando..." : reviewing ? "Confirmar arranque" : "Review"}
          </button>
        </footer>
      </form>
    </div>
  );
}

export function ProfessionalPhotoModal({
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
                      <span className="workstation-select-icon" aria-hidden="true">
                        <Check size={14} weight="bold" />
                      </span>
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
  const [reviewMode, setReviewMode] = useState<"save" | "discard" | null>(null);

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

  function normalizedFunnelDraft(): FunnelDefinition {
    return {
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
    };
  }

  function funnelChangeSummary() {
    const nextFunnel = normalizedFunnelDraft();
    if (mode === "create" || !funnel) {
      return [`Create funnel: ${nextFunnel.label || nextFunnel.id}`];
    }
    return [
      funnel.enabled !== nextFunnel.enabled ? `Enabled: ${funnel.enabled ? "on" : "off"} -> ${nextFunnel.enabled ? "on" : "off"}` : "",
      funnel.sheet_url !== nextFunnel.sheet_url || funnel.sheet_gid !== nextFunnel.sheet_gid ? "Sheet source changed" : "",
      funnel.sheet_poll_seconds !== nextFunnel.sheet_poll_seconds ? "Sheet polling changed" : "",
      funnel.opener_template_name !== nextFunnel.opener_template_name
        || funnel.opener_followup_template_name !== nextFunnel.opener_followup_template_name
        || funnel.manual_ping_template_name !== nextFunnel.manual_ping_template_name
        || funnel.opener_text !== nextFunnel.opener_text
        || funnel.opener_followup_text !== nextFunnel.opener_followup_text
        || funnel.manual_ping_text !== nextFunnel.manual_ping_text
        || funnel.calendly_intro_text !== nextFunnel.calendly_intro_text
        ? "Templates or funnel copy changed"
        : "",
      JSON.stringify(funnel.alert_emails) !== JSON.stringify(nextFunnel.alert_emails) ? "Alert emails changed" : "",
      JSON.stringify(funnel.strategies.map((item) => ({ id: item.id, weight: item.weight, delivery: item.delivery, media_path: item.media_path })))
        !== JSON.stringify(nextFunnel.strategies.map((item) => ({ id: item.id, weight: item.weight, delivery: item.delivery, media_path: item.media_path })))
        ? "Strategies changed"
        : "",
    ].filter(Boolean);
  }

  const changes = funnelChangeSummary();
  const dirty = changes.length > 0;

  function requestClose() {
    if (dirty) {
      setReviewMode("discard");
      return;
    }
    onClose();
  }

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!dirty) {
      onClose();
      return;
    }
    if (reviewMode !== "save") {
      setReviewMode("save");
      return;
    }
    await onSave(normalizedFunnelDraft());
  }

  return (
    <aside className="ct-drawer open" aria-hidden="false" aria-label="Funnel editor">
      <button className="ct-drawer-overlay" type="button" onClick={requestClose} aria-label="Close funnel editor" />
      <form className="ct-drawer-panel wide" role="dialog" aria-modal="false" aria-labelledby="ctFunnelDrawerTitle" onSubmit={submit}>
        <header className="ct-drawer-head">
          <div>
            <p className="ct-drawer-kicker">{mode === "create" ? "New funnel" : "Funnel config"}</p>
            <h3 id="ctFunnelDrawerTitle">{mode === "create" ? "Add Niche Funnel" : draft.label}</h3>
            <p className="ct-drawer-note">Saved to the shared funnel config file used by the UI and Codex.</p>
          </div>
          <button type="button" className="ct-icon-btn" onClick={requestClose}>Close</button>
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
          {reviewMode ? (
            <section className="ct-drawer-review" data-mode={reviewMode}>
              <strong>{reviewMode === "save" ? "Review funnel changes" : "Discard funnel edits?"}</strong>
              <ul>
                {(changes.length ? changes : ["No saved values changed."]).map((change) => (
                  <li key={change}>{change}</li>
                ))}
              </ul>
              {reviewMode === "discard" ? (
                <div className="ct-drawer-review-actions">
                  <button type="button" className="ct-btn ct-btn-ghost" onClick={() => setReviewMode(null)}>Keep editing</button>
                  <button type="button" className="ct-btn ct-btn-warn" onClick={onClose}>Discard edits</button>
                </div>
              ) : null}
            </section>
          ) : null}
        </div>

        <footer className="ct-drawer-foot">
          <button type="button" className="ct-btn ct-btn-ghost" onClick={requestClose}>Cancel</button>
          <button type="submit" className="ct-btn ct-btn-primary" disabled={saving}>{saving ? "Saving..." : reviewMode === "save" ? "Confirm save" : "Review changes"}</button>
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

export function MessageTimeline({
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
  const [fileError, setFileError] = useState("");
  const hasContent = Boolean(value.trim() || files.length);
  const blocked = Boolean(blockReason);

  useEffect(() => {
    setFileError("");
  }, [files]);

  function usableFiles(fileList: FileList | File[]): File[] {
    return Array.from(fileList).filter((item) => item.size > 0);
  }

  function mergeFiles(nextFiles: File[]) {
    if (!nextFiles.length) {
      return;
    }
    const seen = new Set(files.map((item) => `${item.name}:${item.size}:${item.lastModified}`));
    const uniqueFiles = nextFiles.filter((item) => {
      const key = `${item.name}:${item.size}:${item.lastModified}`;
      if (seen.has(key)) {
        return false;
      }
      seen.add(key);
      return true;
    });
    if (!uniqueFiles.length) {
      return;
    }
    const oversizedFile = uniqueFiles.find((item) => item.size > CRM_MANUAL_MEDIA_MAX_FILE_BYTES);
    if (oversizedFile) {
      setFileError(`${oversizedFile.name} is over ${formatBytes(CRM_MANUAL_MEDIA_MAX_FILE_BYTES)}.`);
      return;
    }
    if (files.length + uniqueFiles.length > CRM_MANUAL_MEDIA_MAX_FILES) {
      setFileError(`Attach up to ${CRM_MANUAL_MEDIA_MAX_FILES} files.`);
      return;
    }
    const currentBytes = files.reduce((total, item) => total + item.size, 0);
    const nextBytes = uniqueFiles.reduce((total, item) => total + item.size, 0);
    if (currentBytes + nextBytes > CRM_MANUAL_MEDIA_MAX_TOTAL_BYTES) {
      setFileError(`Attachments can total up to ${formatBytes(CRM_MANUAL_MEDIA_MAX_TOTAL_BYTES)}.`);
      return;
    }
    setFileError("");
    onFilesChange([...files, ...uniqueFiles]);
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
    setFileError("");
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
        ) : null}
        <p className={`ct-manual-hint ${fileError ? "blocked" : ""}`}>
          {fileError || `Up to ${CRM_MANUAL_MEDIA_MAX_FILES} files, ${formatBytes(CRM_MANUAL_MEDIA_MAX_FILE_BYTES)} each, ${formatBytes(CRM_MANUAL_MEDIA_MAX_TOTAL_BYTES)} total. Drop or paste files here.`}
        </p>
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
  const [reviewMode, setReviewMode] = useState<"save" | "discard" | null>(null);

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

  function nextConfigPayload(): Partial<ContadoresConfig> {
    return {
      enabled: draft.enabled,
      calendly_base_url: draft.calendly_base_url,
      alert_emails: draft.alert_emails.split(",").map((item) => item.trim()).filter(Boolean),
      strategy_weights: draft.strategy_weights,
    };
  }

  function configChangeSummary() {
    if (!config) {
      return [];
    }
    const nextConfig = nextConfigPayload();
    const currentEmails = config.alert_emails.join(", ");
    const nextEmails = nextConfig.alert_emails?.join(", ") ?? "";
    return [
      config.enabled !== nextConfig.enabled ? `Enabled: ${config.enabled ? "on" : "off"} -> ${nextConfig.enabled ? "on" : "off"}` : "",
      config.calendly_base_url !== nextConfig.calendly_base_url ? "Meeting URL changed" : "",
      currentEmails !== nextEmails ? "Alert emails changed" : "",
      JSON.stringify(config.strategy_weights ?? {}) !== JSON.stringify(nextConfig.strategy_weights ?? {}) ? "Strategy weights changed" : "",
    ].filter(Boolean);
  }

  const changes = configChangeSummary();
  const dirty = changes.length > 0;

  function requestClose() {
    if (dirty) {
      setReviewMode("discard");
      return;
    }
    onClose();
  }

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!dirty) {
      onClose();
      return;
    }
    if (reviewMode !== "save") {
      setReviewMode("save");
      return;
    }
    await onSave(nextConfigPayload());
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
      <button className="ct-drawer-overlay" type="button" onClick={requestClose} aria-label="Close rollout controls" />
      <form className="ct-drawer-panel" role="dialog" aria-modal="false" aria-labelledby="ctDrawerTitle" onSubmit={handleSubmit}>
        <header className="ct-drawer-head">
          <div>
            <p className="ct-drawer-kicker">Runtime</p>
            <h3 id="ctDrawerTitle">Automation controls</h3>
            <p className="ct-drawer-note">
              Sheet: {config?.last_sheet_sync_status || "idle"} · Ready: {runtime?.ready ? "yes" : "review"}
            </p>
          </div>
          <button type="button" className="ct-icon-btn" onClick={requestClose}>Close</button>
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
          {reviewMode ? (
            <section className="ct-drawer-review" data-mode={reviewMode}>
              <strong>{reviewMode === "save" ? "Review runtime changes" : "Discard runtime edits?"}</strong>
              <ul>
                {(changes.length ? changes : ["No saved values changed."]).map((change) => (
                  <li key={change}>{change}</li>
                ))}
              </ul>
              {reviewMode === "discard" ? (
                <div className="ct-drawer-review-actions">
                  <button type="button" className="ct-btn ct-btn-ghost" onClick={() => setReviewMode(null)}>Keep editing</button>
                  <button type="button" className="ct-btn ct-btn-warn" onClick={onClose}>Discard edits</button>
                </div>
              ) : null}
            </section>
          ) : null}
        </div>
        <footer className="ct-drawer-foot">
          <button type="button" className="ct-btn ct-btn-ghost" onClick={requestClose}>Cancel</button>
          <button type="submit" className="ct-btn ct-btn-primary" disabled={saving || !config}>{saving ? "Saving..." : reviewMode === "save" ? "Confirm save" : "Review changes"}</button>
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
    meta_page_id: "",
    meta_lead_form_id: "",
    recipient_name: "",
    recipient_phone: "",
    template_name: "konecta_delivery_lead_alert_es",
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
    meta_page_id: source.meta_page_id ?? "",
    meta_lead_form_id: source.meta_lead_form_id ?? "",
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
    meta_page_id: draft.meta_page_id.trim() || null,
    meta_lead_form_id: draft.meta_lead_form_id.trim() || null,
    recipient_name: draft.recipient_name.trim() || null,
    recipient_phone: draft.recipient_phone.trim() || null,
    template_name: draft.template_name.trim() || null,
    template_language: draft.template_language.trim() || null,
    column_mapping: parseClientLeadColumnMapping(draft.column_mapping_text),
    context_field_mapping: parseClientLeadColumnMapping(draft.context_field_mapping_text),
  };
}

function clientLeadSourceDraftFingerprint(draft: ClientLeadSourceDraft): string {
  try {
    return JSON.stringify(clientLeadSourcePayloadFromDraft(draft));
  } catch {
    return JSON.stringify({
      ...draft,
      id: slugifyClient(draft.id || draft.label),
      label: draft.label.trim(),
      sheet_url: draft.sheet_url.trim(),
      sheet_gid: draft.sheet_gid.trim(),
      sheet_tab_name: draft.sheet_tab_name.trim(),
      sheet_poll_seconds: Math.max(5, Number(draft.sheet_poll_seconds) || 10),
      meta_page_id: draft.meta_page_id.trim(),
      meta_lead_form_id: draft.meta_lead_form_id.trim(),
      recipient_name: draft.recipient_name.trim(),
      recipient_phone: draft.recipient_phone.trim(),
      template_name: draft.template_name.trim(),
      template_language: draft.template_language.trim(),
      column_mapping_text: draft.column_mapping_text.trim(),
      context_field_mapping_text: draft.context_field_mapping_text.trim(),
    });
  }
}

function isDeliverySourceDraftDirty(
  draft: ClientLeadSourceDraft,
  source: ClientLeadSource | null,
  editorMode: DeliveryEditorMode,
): boolean {
  const baselineDraft = editorMode === "edit" && source
    ? clientLeadSourceToDraft(source)
    : buildBlankClientLeadSourceDraft();
  return clientLeadSourceDraftFingerprint(draft) !== clientLeadSourceDraftFingerprint(baselineDraft);
}

export function validateClientLeadSourceDraft(draft: ClientLeadSourceDraft): ClientLeadSourceDraftValidation {
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

export type DeliveryContactGroup = {
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

export type DeliverySheetLeadSection = {
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

export function buildDeliverySheetLeadSections(
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

export function deliveryRawFields(lead: ClientLead): DeliveryRawField[] {
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

export function deliverySheetLabel(source: ClientLeadSource): string {
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

export function deliveryContactTone(group: DeliveryContactGroup): DeliveryTone {
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

export function deliveryContactStatusLabel(group: DeliveryContactGroup): string {
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

export function deliverySourceHasIssue(source: ClientLeadSource): boolean {
  const status = String(source.last_sync_status || "").toLowerCase();
  return status === "failed" || status === "error" || deliverySourceCount(source, "failed") > 0;
}

export function deliverySourceIssueText(source: ClientLeadSource): string {
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

export function deliverySourceStatusIcon(source: ClientLeadSource): ReactNode {
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

export function deliverySourceCount(source: ClientLeadSource, key: keyof ClientLeadSource["counts"]): number {
  const value = source.counts?.[key] ?? 0;
  return Number.isFinite(value) ? Number(value) : 0;
}

export function deliverySourceTone(source: ClientLeadSource): DeliveryTone {
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

export function buildWaLink(phone: string | null | undefined): string {
  const digits = (phone || "").replace(/\D/g, "");
  return digits ? `https://wa.me/${digits}` : "";
}

export function displayLeadPhone(phone: string | null | undefined): string {
  const value = (phone || "").trim().replace(/^p:/i, "");
  return value || "-";
}

export function clientLeadAgeText(lead: ClientLead): string {
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

export function deliveryLeadTitle(lead: ClientLead): string {
  return lead.full_name
    || firstRawValue(lead, ["Nombre", "Name", "nombre", "full_name", "Full name"])
    || displayLeadPhone(lead.phone_number)
    || `Row ${lead.row_number}`;
}

export function deliveryLeadSubtitle(lead: ClientLead): string {
  const parts = [
    displayLeadPhone(lead.phone_number),
    lead.email || "",
  ].filter((part) => part && part !== "-");
  return parts.length ? parts.join(" · ") : "No mapped contact fields";
}

export function deliveryStatusDetail(lead: ClientLead): string {
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

export function recipientChatMessageDetail(message: ClientLeadRecipientChatMessage): string {
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

export function recipientChatMessageTone(message: ClientLeadRecipientChatMessage): "success" | "warn" | "danger" | "muted" | "accent" {
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

export function clientLeadDeliveryTone(lead: ClientLead): "success" | "warn" | "danger" | "muted" | "accent" {
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

export function isRetryableClientLead(lead: ClientLead): boolean {
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

export function slugifyClient(value: string): string {
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

export function formatBytes(value: number): string {
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

export function formatWorkstationOffer(client: WorkstationClientSummary | null | undefined): string {
  if (!client?.offer_price_usd || client.offer_price_usd <= 0) {
    return "";
  }
  return `${client.offer_price_usd} ${client.offer_currency || "USD"}`;
}

export function formatWorkstationClientState(
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

export function monogram(value: string): string {
  return value
    .split(/\s+/)
    .filter(Boolean)
    .slice(0, 2)
    .map((part) => part[0]?.toUpperCase() ?? "")
    .join("") || "CT";
}

export function truncate(value: string, maxLength: number): string {
  if (value.length <= maxLength) {
    return value;
  }
  return `${value.slice(0, maxLength - 1)}...`;
}
