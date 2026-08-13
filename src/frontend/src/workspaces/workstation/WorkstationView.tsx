import { useEffect, useState } from "react";
import type { ClipboardEvent, DragEvent, FormEvent } from "react";
import {
  ArrowSquareOut,
  Camera,
  CaretDown,
  Check,
  CheckCircle,
  ChatCircleText,
  ClockCountdown,
  Copy,
  DownloadSimple,
  FolderOpen,
  NotePencil,
  PaperPlaneTilt,
  Robot,
  SpinnerGap,
  Trash,
  UploadSimple,
  WarningCircle,
  X,
} from "@phosphor-icons/react";
import { compactNumber, humanize, shortDate } from "../../format";
import type { FunnelDefinition, LeadSummary, MessageItem, WorkstationClientDetailResponse, WorkstationClientSummary, WorkstationCopyAllResponse, WorkstationMediaAsset, WorkstationProfessionalPhotoJobResponse } from "../../types";
import {
  CtEmptyState,
  formatBytes,
  formatWorkstationClientState,
  formatWorkstationOffer,
  MessageTimeline,
  monogram,
  ProfessionalPhotoModal,
  SoloPagePromptModal,
  SoloPageSteerModal,
} from "../../App";

export async function copyTextToClipboard(value: string): Promise<void> {
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

export function WorkstationView({
  clients,
  detail,
  funnel,
  selectedClientId,
  listLoading,
  loading,
  actionBusy,
  notesDraft,
  notesDirty,
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
  notesDirty: boolean;
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
                      {notesDirty ? <span className="workstation-dirty-pill">Unsaved</span> : null}
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
          clientName={activeClient?.display_name || "this client"}
          prompt={soloPageOperatorPrompt}
          busy={actionBusy === "solo-page-work"}
          onPromptChange={setSoloPageOperatorPrompt}
          onClose={closeSoloPagePromptModal}
          onSubmit={submitSoloPagePromptModal}
        />
      ) : null}
      {soloPageSteerModalOpen ? (
        <SoloPageSteerModal
          clientName={activeClient?.display_name || "this client"}
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
