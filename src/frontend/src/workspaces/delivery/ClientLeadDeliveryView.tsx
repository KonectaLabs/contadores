import { useEffect, useState } from "react";
import type { FormEvent } from "react";
import { ArrowsClockwise, ArrowSquareOut, ChatCircleText, Check, Copy, GearSix, Plus, Trash, WarningCircle, X } from "@phosphor-icons/react";
import { compactNumber, humanize } from "../../format";
import type { ClientLead, ClientLeadRecipientChatMessage, ClientLeadRecipientChatResponse, ClientLeadRecipientCrmLead, ClientLeadSource } from "../../types";
import { CtEmptyState, buildDeliverySheetLeadSections, buildWaLink, clientLeadAgeText, clientLeadDeliveryTone, deliveryContactStatusLabel, deliveryContactTone, deliveryLeadSubtitle, deliveryLeadTitle, deliveryRawFields, deliverySheetLabel, deliverySourceCount, deliverySourceHasIssue, deliverySourceIssueText, deliverySourceStatusIcon, deliverySourceTone, deliveryStatusDetail, displayLeadPhone, isRetryableClientLead, monogram, recipientChatMessageDetail, recipientChatMessageTone, slugifyClient, truncate, validateClientLeadSourceDraft } from "../../App";
import type { ClientLeadSourceDraft, DeliveryContactGroup, DeliveryEditorMode, DeliverySheetLeadSection } from "../../App";

export function ClientLeadDeliveryView({
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
  syncStatus,
  sourceEditorError,
  sourceDraftDirty,
  onDiscardSourceDraft,
  onSelectSource,
  onNewSource,
  onDraftChange,
  onSaveSource,
  onDeleteSource,
  onSyncSources,
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
  syncStatus: string;
  sourceEditorError: string;
  sourceDraftDirty: boolean;
  onDiscardSourceDraft: (action: () => void) => void;
  onSelectSource: (sourceId: string) => void;
  onNewSource: () => void;
  onDraftChange: (draft: ClientLeadSourceDraft) => void;
  onSaveSource: (event: FormEvent<HTMLFormElement>) => void | Promise<void>;
  onDeleteSource: () => void;
  onSyncSources: () => void | Promise<void>;
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
    if (editorMode === "edit" && selectedGroupKey && !sourceDraftDirty) {
      setConfigOpen(false);
      setSentChatOpen(false);
      setActiveSheetId(null);
    }
  }, [editorMode, selectedGroupKey, sourceDraftDirty]);

  function closeSourceEditor() {
    onDiscardSourceDraft(() => setConfigOpen(false));
  }

  function startNewDeliveryContact() {
    onDiscardSourceDraft(() => {
      setDeliveryStage("client");
      setActiveSheetId(null);
      onNewSource();
    });
  }

  function openDeliveryContact(group: DeliveryContactGroup) {
    onDiscardSourceDraft(() => {
      setDeliveryStage("client");
      setActiveSheetId(null);
      onSelectSource(group.primarySource.id);
    });
  }

  function openDeliverySheet(source: ClientLeadSource) {
    onDiscardSourceDraft(() => {
      setDeliveryStage("sheet");
      setActiveSheetId(source.id);
      onSelectSource(source.id);
    });
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
      {syncStatus ? <p className="delivery-copy-status" aria-live="polite">{syncStatus}</p> : null}

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
                className="ct-btn ct-btn-primary"
                disabled={!isExisting || actionBusy === "delivery-sync"}
                onClick={() => {
                  void onSyncSources();
                }}
              >
                <ArrowsClockwise size={15} weight="bold" />
                {actionBusy === "delivery-sync" ? "Syncing..." : selectedSources.length > 1 ? `Sync ${selectedSources.length} sheets` : "Sync sheet"}
              </button>
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
          onClose={closeSourceEditor}
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
                {isExisting ? <p className="ct-field-hint">Source ID is locked after create.</p> : null}
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
            <div className="ct-field-grid">
              <label className="ct-field">
                <span>Meta Page ID</span>
                <input value={draft.meta_page_id} onChange={(event) => updateDraft("meta_page_id", event.target.value)} placeholder="page id" />
              </label>
              <label className="ct-field">
                <span>Meta Lead Form ID</span>
                <input value={draft.meta_lead_form_id} onChange={(event) => updateDraft("meta_lead_form_id", event.target.value)} placeholder="lead form id" />
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
