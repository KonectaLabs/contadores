import { useCallback, useEffect, useMemo, useState } from "react";
import type { ClipboardEvent, DragEvent, FormEvent } from "react";
import {
  ArrowSquareOut,
  Copy,
  CurrencyDollar,
  DownloadSimple,
  FolderOpen,
  Trash,
  UploadSimple,
} from "@phosphor-icons/react";
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
  RuntimeSettings,
  StrategyStatsItem,
  StrategyStatsResponse,
  WorkstationClientDetailResponse,
  WorkstationClientListResponse,
  WorkstationClientSummary,
  WorkstationCopyAllResponse,
  WorkstationMediaAsset,
  WorkstationProfessionalPhotoVersion,
} from "./types";

const REFRESH_MS = 12000;
const DASHBOARD_FUNNEL_STORAGE_KEY = "contadores.dashboard.selectedFunnelId";
const DASHBOARD_STAGE_STORAGE_KEY = "contadores.dashboard.stageFilter";
const DASHBOARD_SECTION_STORAGE_KEY = "contadores.dashboard.activeSection";

type StageFilterValue = LeadStage | "all" | "manual_attention";
type ActiveSection = "crm" | "workstation";

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
  return readStoredValue(DASHBOARD_SECTION_STORAGE_KEY) === "workstation" ? "workstation" : "crm";
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
  { value: "send-opener", title: "Opener", help: "Queue the default opener template." },
  { value: "send-loom", title: "Loom sequence", help: "Queue the Loom video introduction messages." },
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
  | "send-loom"
  | "send-video-check"
  | "send-calendly"
  | "send-calendly-link"
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
  const [bulkSendKind, setBulkSendKind] = useState<BulkSendKind>("send-manual-ping");
  const [manualText, setManualText] = useState("");
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
  const [workstationLoading, setWorkstationLoading] = useState(false);
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
  const visibleLeadIds = useMemo(() => (leadList?.leads ?? []).map((lead) => lead.id), [leadList]);
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
      if (current && leadsPayload.leads.some((lead) => lead.id === current)) {
        return current;
      }
      return leadsPayload.leads[0]?.id ?? null;
    });
  }, [debouncedQuery, selectedFunnelId, stageFilter, strategyFilter.step, strategyFilter.strategyId, tagFilter]);

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

  const loadDetail = useCallback(async (leadId: string) => {
    setDetailLoading(true);
    try {
      const payload = await apiFetch<LeadDetailResponse>(`/api/contadores/leads/${leadId}`);
      setDetail(payload);
    } finally {
      setDetailLoading(false);
    }
  }, []);

  const loadWorkstationDetail = useCallback(async (clientId: string) => {
    setWorkstationLoading(true);
    try {
      const payload = await apiFetch<WorkstationClientDetailResponse>(`/api/workstation/clients/${clientId}`);
      setWorkstationDetail(payload);
      setWorkstationNotesDraft(payload.notes ?? "");
    } finally {
      setWorkstationLoading(false);
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

  useEffect(() => {
    loadWorkstation().catch((reason) => {
      setError(reason instanceof Error ? reason.message : "Could not load Workstation.");
    });
  }, [loadWorkstation]);

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
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Could not refresh funnels.");
    } finally {
      setLoading(false);
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

  function toggleProfessionalPhotoMedia(assetId: string) {
    setProfessionalPhotoMediaIds((current) => (
      current.includes(assetId)
        ? current.filter((id) => id !== assetId)
        : [...current, assetId]
    ));
  }

  async function createProfessionalPhoto() {
    const clientId = workstationDetail?.client.id ?? selectedWorkstationClientId;
    if (!clientId || professionalPhotoMediaIds.length === 0) {
      setError("Select at least one image from client media.");
      return;
    }
    setActionBusy("professional-photo-create");
    try {
      await apiFetch<WorkstationProfessionalPhotoVersion>(
        `/api/workstation/clients/${clientId}/professional-photo`,
        {
          method: "POST",
          body: JSON.stringify({
            media_asset_ids: professionalPhotoMediaIds,
            context: professionalPhotoContext,
          }),
        },
      );
      setProfessionalPhotoContext("");
      await loadWorkstationDetail(clientId);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Could not create professional photo.");
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
  const workstationTitle = selectedFunnel
    ? `Workstation · ${selectedFunnel.label}`
    : "Workstation";
  const syncStatus = activeSection === "workstation"
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
            <p className="ct-brand-word">{activeSection === "workstation" ? workstationTitle : selectedFunnel?.label || "Funnels"}</p>
            <span className={`ct-sync-badge ${config?.last_sheet_sync_status === "ok" ? "has-unread" : ""}`}>{syncStatus}</span>
          </div>
        </div>

        <nav className="ct-section-switch" aria-label="Primary workspace">
          <button
            type="button"
            className={activeSection === "crm" ? "active" : ""}
            aria-label={totalManualAttentionCount > 0 ? `CRM, ${totalManualAttentionCount} needs answer` : "CRM"}
            onClick={() => setActiveSection("crm")}
          >
            CRM
            {totalManualAttentionCount > 0 ? (
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
          ) : (
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
          )}
          <button type="button" className="ct-icon-btn" onClick={openEditFunnel} disabled={!selectedFunnel}>Funnel</button>
          {activeSection === "crm" && isContadoresFunnel ? (
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

      {activeSection === "workstation" ? (
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
          onFileTitleChange={setWorkstationFileTitle}
          onFileChange={setWorkstationFile}
          onUploadMedia={uploadWorkstationMedia}
          onUploadMediaFile={(fileToUpload) => {
            uploadWorkstationMediaFromFile(fileToUpload).catch((reason) => {
              setError(reason instanceof Error ? reason.message : "Could not upload media.");
            });
          }}
          onDeleteMedia={deleteWorkstationMedia}
          onToggleProfessionalPhotoMedia={toggleProfessionalPhotoMedia}
          onProfessionalPhotoContextChange={setProfessionalPhotoContext}
          onCreateProfessionalPhoto={() => createProfessionalPhoto()}
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
              onMarkAnswered={() => runAction("mark-answered")}
              onToggleClosed={() => runAction(selectedLead?.stage === "closed" ? "reopen" : "close")}
              onDelete={deleteLead}
              onConvert={convertLeadToWorkstation}
              onOpenWorkstation={openWorkstationClient}
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
                <MessageTimeline messages={detail?.messages ?? []} loading={detailLoading} hasLead={Boolean(selectedLead)} />
              </section>

              {!isInboxFunnel ? (
                <section className={`ct-pane ${activeTab === "strategies" ? "active" : ""}`}>
                  <LeadStrategies messages={detail?.messages ?? []} loading={detailLoading} hasLead={Boolean(selectedLead)} />
                </section>
              ) : null}
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
          tagsText={bulkTagsDraft}
          funnel={selectedFunnel}
          selectedCount={selectedLeadIds.length}
          busy={actionBusy === "bulk-send-modal"}
          onKindChange={setBulkSendKind}
          onTextChange={setManualText}
          onTagsTextChange={setBulkTagsDraft}
          onClose={() => setShowBulkSendModal(false)}
          onSubmit={submitBulkSendModal}
        />
      ) : null}
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
  onFileTitleChange,
  onFileChange,
  onUploadMedia,
  onUploadMediaFile,
  onDeleteMedia,
  selectedProfessionalPhotoMediaIds,
  professionalPhotoContext,
  professionalPhotoEditPrompts,
  onToggleProfessionalPhotoMedia,
  onProfessionalPhotoContextChange,
  onCreateProfessionalPhoto,
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
  onSelectClient: (clientId: string) => void;
  onNotesChange: (notes: string) => void;
  onSaveNotes: () => void;
  onCopyNotes: () => void;
  onCopyAll: () => void;
  onOpenCrmLead: (lead: LeadSummary | null | undefined) => void;
  onFileTitleChange: (value: string) => void;
  onFileChange: (file: File | null) => void;
  onUploadMedia: (event: FormEvent<HTMLFormElement>) => void;
  onUploadMediaFile: (file: File) => void;
  onDeleteMedia: (asset: WorkstationMediaAsset) => void;
  onToggleProfessionalPhotoMedia: (assetId: string) => void;
  onProfessionalPhotoContextChange: (value: string) => void;
  onCreateProfessionalPhoto: () => void;
  onProfessionalPhotoEditPromptChange: (version: string, prompt: string) => void;
  onEditProfessionalPhoto: (version: string) => void;
}) {
  const detailClient = detail?.client.id === selectedClientId ? detail.client : null;
  const selectedLead = detailClient?.lead ?? null;
  const activeClient = detailClient ?? clients.find((client) => client.id === selectedClientId) ?? null;
  const funnelLabel = funnel?.label ?? activeClient?.funnel_id ?? "selected funnel";
  const imageAssets = (detail?.media ?? []).filter((asset) => asset.content_type?.startsWith("image/"));
  const professionalPhotos = detail?.professional_photos ?? [];
  const [mediaDropActive, setMediaDropActive] = useState(false);
  const canUploadMedia = Boolean(activeClient) && actionBusy !== "workstation-upload";

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
                className={`workstation-client-row ${client.id === selectedClientId ? "active" : ""}`}
                key={client.id}
                onClick={() => onSelectClient(client.id)}
              >
                <div className="ct-lead-avatar" data-tone="success">
                  {monogram(client.display_name || client.lead?.full_name || "CL")}
                </div>
                <div>
                  <div className="workstation-client-row-top">
                    <strong>{client.display_name || client.lead?.full_name || "Client"}</strong>
                  </div>
                  <p>{client.lead?.phone || client.folder_name}</p>
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
                  </div>
                </div>
                <div className="ct-detail-head-actions">
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

              <section className="workstation-panel notes-panel">
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
                      {asset.content_type?.startsWith("image/") ? (
                        <img src={asset.media_url} alt={asset.title || asset.original_filename} loading="lazy" />
                      ) : (
                        <div className="workstation-file-icon"><FolderOpen size={28} weight="bold" /></div>
                      )}
                      <div>
                        <strong>{asset.title || asset.original_filename}</strong>
                        <span>{asset.original_filename} · {formatBytes(asset.size_bytes)}</span>
                        <code>{asset.stored_path}</code>
                      </div>
                      <div className="workstation-media-actions">
                        {asset.content_type?.startsWith("image/") ? (
                          <label className="workstation-media-check">
                            <input
                              type="checkbox"
                              checked={selectedProfessionalPhotoMediaIds.includes(asset.id)}
                              onChange={() => onToggleProfessionalPhotoMedia(asset.id)}
                            />
                            Source
                          </label>
                        ) : null}
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
                  <button
                    type="button"
                    className="ct-btn ct-btn-primary"
                    disabled={
                      !imageAssets.length
                      || selectedProfessionalPhotoMediaIds.length === 0
                      || actionBusy === "professional-photo-create"
                    }
                    onClick={onCreateProfessionalPhoto}
                  >
                    {actionBusy === "professional-photo-create" ? "Creating..." : "Create professional photo"}
                  </button>
                </div>
                <label className="ct-field">
                  <span>Optional direction</span>
                  <input
                    value={professionalPhotoContext}
                    onChange={(event) => onProfessionalPhotoContextChange(event.target.value)}
                    placeholder="Abogado penalista, contador premium, más formal, ciudad..."
                  />
                </label>
                <p className="workstation-helper">
                  Select image media as sources, then generate a deterministic version under professional-photo.
                </p>
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
                      {imageAssets.length
                        ? "Select source images from Media and create the first professional photo."
                        : "Upload client photos to create a professional portrait."}
                    </p>
                  )}
                </div>
              </section>

              <section className="workstation-panel">
                <div className="workstation-panel-head">
                  <div>
                    <span>Conversation</span>
                    <strong>CRM chat snapshot</strong>
                  </div>
                </div>
                <MessageTimeline messages={detail?.messages ?? []} loading={loading} hasLead={Boolean(activeClient)} />
              </section>
            </>
          )}
        </section>
      </div>
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
                    <span className="ct-lead-stage" data-tone={tone}>{inboxMode ? "Inbox" : formatStageLabel(lead.stage)}</span>
                    {lead.workstation_client_id ? (
                      <span className="ct-lead-converted">
                        Converted
                      </span>
                    ) : null}
                    {strategyTag ? <span className="ct-lead-strategy-tag">{strategyTag}</span> : null}
                    {(lead.tags ?? []).slice(0, 3).map((tag) => <span className="ct-lead-tag" key={tag}>#{tag}</span>)}
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
  inboxMode,
  onOpenSend,
  onManualBooked,
  onMarkAnswered,
  onToggleClosed,
  onDelete,
  onConvert,
  onOpenWorkstation,
}: {
  lead: LeadSummary | null;
  actionBusy: string | null;
  inboxMode: boolean;
  onOpenSend: () => void;
  onManualBooked: () => void;
  onMarkAnswered: () => void;
  onToggleClosed: () => void;
  onDelete: () => void;
  onConvert: () => void;
  onOpenWorkstation: (clientId: string) => void | Promise<void>;
}) {
  const closed = lead?.stage === "closed";
  const booked = lead?.stage === "booked";
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
            {lead ? [lead.phone || "-", lead.email || "-", lead.platform || "-", lead.external_lead_id || "-"].join(" · ") : "Open a lead to inspect messages, strategy history, and manual controls."}
          </p>
        </div>
      </div>
      <div className="ct-detail-head-actions">
        <button type="button" className="ct-btn ct-btn-primary" disabled={!lead || closed || Boolean(actionBusy)} onClick={onOpenSend}>Send message...</button>
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
          <button
            type="button"
            className="ct-btn ct-btn-ghost"
            disabled={!lead || Boolean(actionBusy)}
            onClick={onConvert}
          >
            <CurrencyDollar size={15} weight="bold" />
            Convert
          </button>
        )}
        {!inboxMode ? (
          <button type="button" className="ct-btn ct-btn-ghost" disabled={!lead || closed || booked || Boolean(actionBusy)} onClick={onManualBooked}>Mark booked</button>
        ) : null}
        {canMarkAnswered && !inboxMode ? (
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
  const marksCalendlySent = kind === "send-calendly" || kind === "send-calendly-link";
  const pausesAutomation = !marksCalendlySent;
  const availableOptions = funnel?.kind === "inbox"
    ? sendOptions.filter((option) => ["custom", "send-opener", "send-manual-ping"].includes(option.value))
    : sendOptions;

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
  tagsText,
  funnel,
  selectedCount,
  busy,
  onKindChange,
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
  busy: boolean;
  onKindChange: (kind: BulkSendKind) => void;
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
            {kind === "set-tags"
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
                  checked={kind === option.value}
                  onChange={() => onKindChange(option.value)}
                />
                <div>
                  <strong>{option.title}</strong>
                  <span>{option.value === "set-tags" ? option.help : sendOptionPreview(option.value, funnel) || option.help}</span>
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

          <label className="ct-modal-field" hidden={kind !== "set-tags"}>
            <span>Tags</span>
            <input
              value={tagsText}
              onChange={(event) => onTagsTextChange(event.target.value)}
              placeholder="prioridad, whatsapp_funnel"
            />
          </label>
        </div>
        <footer className="ct-modal-foot">
          <button type="button" className="ct-btn ct-btn-ghost" onClick={onClose}>Cancel</button>
          <button type="submit" className="ct-btn ct-btn-primary" disabled={busy || !selectedCount || (kind === "custom" && !text.trim()) || (kind === "set-tags" && !tagValues.length)}>
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
    calendly_base_url: "https://calendly.com",
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
    "send-opener": funnel.opener_text,
    "send-loom": funnel.loom_intro_text,
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
