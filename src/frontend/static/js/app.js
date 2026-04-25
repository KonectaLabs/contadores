const state = {
  baseUrl: window.location.origin,
  currentSection: "audits",
  currentView: "home",
  projects: [],
  currentProjectId: null,
  currentProject: null,
  currentThreadId: null,
  threadMessages: [],
  crmThreads: [],
  crmUnreadThreadCount: 0,
  crmUnreadMessageCount: 0,
  currentCrmThreadId: null,
  currentCrmThread: null,
  crmMessages: [],
  crmMobilePane: "list",
  crmQuery: "",
  pendingCrmReplyThreadId: null,
  latestReport: null,
  toastTimer: null,
  loadingNode: null,
  createScanMode: "single",
  projectQuery: "",
  projectLanguageFilter: "all",
  projectIndustryFilter: "",
  projectTagFilter: "",
  projectCeoEmailFilter: "all",
  projectReplyFilter: "all",
  projectCompanySizeFilter: "all",
  threadQuery: "",
  lastRenderedThreadId: null,
  lastRenderedMessageCount: 0,
  pendingInboundTasks: {},
  pendingCompanyTasks: {},
  pendingAiAutomationCompanyId: null,
  pendingCeoDeliveryCompanyId: null,
  pendingCeoEmailCompanyId: null,
  editingMessageId: null,
  editingMessageText: "",
  editingProjectCeoEmail: false,
  editingProjectCeoEmailValue: "",
  editingProjectReportSchedule: false,
  editingProjectReportWindowHoursValue: "",
  editingProjectReportWindowMinutesValue: "",
  editingProjectScheduledSendValue: "",
  showArchivedThreads: false,
  dismissedEmailThreadLinkPanels: {},
  pendingProjectScheduleCompanyId: null,
  processingRefreshTimer: null,
  processingRefreshInFlight: false,
  crmRefreshTimer: null,
  authRedirectInProgress: false,
  sidebarAssistantMessages: [],
  pendingSidebarAssistantReply: false,
  contadoresConfig: null,
  contadoresMetrics: null,
  contadoresStrategyStats: [],
  contadoresLeads: [],
  currentContadoresLeadId: null,
  currentContadoresLead: null,
  contadoresMessages: [],
  contadoresEvents: [],
  contadoresQuery: "",
  contadoresStageFilter: "",
  contadoresPlatformFilter: "",
  contadoresManualReplyFilter: "",
  contadoresBookedFilter: "",
  contadoresNeedsHumanFilter: "",
  contadoresArchivedFilter: "",
  contadoresStrategyStepFilter: "",
  contadoresStrategyIdFilter: "",
};

const dom = {
  sectionAuditsBtn: document.getElementById("sectionAuditsBtn"),
  sectionContadoresBtn: document.getElementById("sectionContadoresBtn"),
  sectionCrmBtn: document.getElementById("sectionCrmBtn"),
  sectionCrmBadge: document.getElementById("sectionCrmBadge"),
  sidebarFocusTitle: document.getElementById("sidebarFocusTitle"),
  sidebarFocusMeta: document.getElementById("sidebarFocusMeta"),
  sidebarFocusCard: document.getElementById("sidebarFocusCard"),
  sidebarFocusSelect: document.getElementById("sidebarFocusSelect"),
  sidebarFocusSelectHint: document.getElementById("sidebarFocusSelectHint"),
  sidebarCompanyCard: document.getElementById("sidebarCompanyCard"),
  sidebarCompanyTitle: document.getElementById("sidebarCompanyTitle"),
  sidebarCompanyMeta: document.getElementById("sidebarCompanyMeta"),
  sidebarCompanyStats: document.getElementById("sidebarCompanyStats"),
  sidebarCompanyInfo: document.getElementById("sidebarCompanyInfo"),
  sidebarAssistantCard: document.getElementById("sidebarAssistantCard"),
  sidebarAssistantMeta: document.getElementById("sidebarAssistantMeta"),
  sidebarAssistantMessages: document.getElementById("sidebarAssistantMessages"),
  sidebarAssistantForm: document.getElementById("sidebarAssistantForm"),
  sidebarAssistantInput: document.getElementById("sidebarAssistantInput"),
  sidebarAssistantSendBtn: document.getElementById("sidebarAssistantSendBtn"),
  sidebarAssistantStatus: document.getElementById("sidebarAssistantStatus"),
  sidebarAssistantClearBtn: document.getElementById("sidebarAssistantClearBtn"),
  homeMetrics: document.getElementById("homeMetrics"),
  homeProjects: document.getElementById("homeProjects"),
  homeView: document.getElementById("homeView"),
  projectSearchInput: document.getElementById("projectSearchInput"),
  homeLanguageFilters: document.getElementById("homeLanguageFilters"),
  homeIndustryFilterSelect: document.getElementById("homeIndustryFilterSelect"),
  homeTagFilterSelect: document.getElementById("homeTagFilterSelect"),
  homeCeoEmailFilters: document.getElementById("homeCeoEmailFilters"),
  homeReplyFilters: document.getElementById("homeReplyFilters"),
  homeCompanySizeFilters: document.getElementById("homeCompanySizeFilters"),
  projectView: document.getElementById("projectView"),
  crmView: document.getElementById("crmView"),
  contadoresView: document.getElementById("contadoresView"),
  projectKicker: document.getElementById("projectKicker"),
  projectSourceUrlLink: document.getElementById("projectSourceUrlLink"),
  projectTitle: document.getElementById("projectTitle"),
  projectMeta: document.getElementById("projectMeta"),
  projectProcessingBanner: document.getElementById("projectProcessingBanner"),
  projectCeoEmailPanel: document.getElementById("projectCeoEmailPanel"),
  projectCeoEmailEditBtn: document.getElementById("projectCeoEmailEditBtn"),
  projectCeoEmailReadRow: document.getElementById("projectCeoEmailReadRow"),
  projectCeoEmailCopyBtn: document.getElementById("projectCeoEmailCopyBtn"),
  projectCeoEmailEditor: document.getElementById("projectCeoEmailEditor"),
  projectCeoEmailInput: document.getElementById("projectCeoEmailInput"),
  projectCeoEmailSaveBtn: document.getElementById("projectCeoEmailSaveBtn"),
  projectCeoEmailCancelBtn: document.getElementById("projectCeoEmailCancelBtn"),
  projectCeoEmailHint: document.getElementById("projectCeoEmailHint"),
  projectReportSchedulePanel: document.getElementById("projectReportSchedulePanel"),
  projectReportScheduleEditBtn: document.getElementById("projectReportScheduleEditBtn"),
  projectDeadlineSummary: document.getElementById("projectDeadlineSummary"),
  projectReportScheduleEditor: document.getElementById("projectReportScheduleEditor"),
  projectReportWindowHoursInput: document.getElementById("projectReportWindowHoursInput"),
  projectReportWindowMinutesInput: document.getElementById("projectReportWindowMinutesInput"),
  projectScheduledSendInput: document.getElementById("projectScheduledSendInput"),
  projectReportScheduleSaveBtn: document.getElementById("projectReportScheduleSaveBtn"),
  projectReportScheduleCancelBtn: document.getElementById("projectReportScheduleCancelBtn"),
  projectReportScheduleHint: document.getElementById("projectReportScheduleHint"),
  projectAiAutomationToggle: document.getElementById("projectAiAutomationToggle"),
  projectAiAutomationHint: document.getElementById("projectAiAutomationHint"),
  projectCeoDeliveryToggle: document.getElementById("projectCeoDeliveryToggle"),
  projectCeoDeliveryHint: document.getElementById("projectCeoDeliveryHint"),
  rescanCompanyBtn: document.getElementById("rescanCompanyBtn"),
  threadList: document.getElementById("threadList"),
  threadsSummary: document.getElementById("threadsSummary"),
  threadSearchInput: document.getElementById("threadSearchInput"),
  toggleArchivedThreadsBtn: document.getElementById("toggleArchivedThreadsBtn"),
  openManualContactModalBtn: document.getElementById("openManualContactModalBtn"),
  chatThreadTitle: document.getElementById("chatThreadTitle"),
  chatThreadMeta: document.getElementById("chatThreadMeta"),
  chatThreadObjective: document.getElementById("chatThreadObjective"),
  transcriptSummary: document.getElementById("transcriptSummary"),
  emailThreadLinkPanel: document.getElementById("emailThreadLinkPanel"),
  emailThreadLinkInput: document.getElementById("emailThreadLinkInput"),
  saveEmailThreadLinkBtn: document.getElementById("saveEmailThreadLinkBtn"),
  dismissEmailThreadLinkPanelBtn: document.getElementById("dismissEmailThreadLinkPanelBtn"),
  emailThreadLinkHint: document.getElementById("emailThreadLinkHint"),
  transcript: document.getElementById("transcript"),
  inboundForm: document.getElementById("inboundForm"),
  inboundInput: document.getElementById("inboundInput"),
  sendInboundBtn: document.getElementById("sendInboundBtn"),
  emailQuickLink: document.getElementById("emailQuickLink"),
  waQuickLink: document.getElementById("waQuickLink"),
  archiveThreadBtn: document.getElementById("archiveThreadBtn"),
  copyLatestDraftBtn: document.getElementById("copyLatestDraftBtn"),
  backHomeBtn: document.getElementById("backHomeBtn"),
  refreshProjectBtn: document.getElementById("refreshProjectBtn"),
  generateFullReportBtn:
    document.getElementById("generateFullReportBtn") || document.getElementById("generateAuditBtn"),
  viewAuditBtn: document.getElementById("viewAuditBtn") || document.getElementById("openAuditHtmlBtn"),
  createProjectModal: document.getElementById("createProjectModal"),
  createProjectForm: document.getElementById("createProjectForm"),
  createScanModeSingleBtn: document.getElementById("createScanModeSingleBtn"),
  createScanModeBatchBtn: document.getElementById("createScanModeBatchBtn"),
  createSingleScanFields: document.getElementById("createSingleScanFields"),
  createBatchScanFields: document.getElementById("createBatchScanFields"),
  createUrlInput: document.getElementById("createUrlInput"),
  createDevScanDetails: document.getElementById("createDevScanDetails"),
  createDevScanTextInput: document.getElementById("createDevScanTextInput"),
  createBatchTextInput: document.getElementById("createBatchTextInput"),
  createBatchFilesInput: document.getElementById("createBatchFilesInput"),
  createBatchFilesSummary: document.getElementById("createBatchFilesSummary"),
  createTagsInput: document.getElementById("createTagsInput"),
  createCeoEmailInput: document.getElementById("createCeoEmailInput"),
  createReportWindowHoursInput: document.getElementById("createReportWindowHoursInput"),
  createReportWindowMinutesInput: document.getElementById("createReportWindowMinutesInput"),
  createObjectiveInput: document.getElementById("createObjectiveInput"),
  createConversationAutomationToggle: document.getElementById("createConversationAutomationToggle"),
  createCeoDeliveryToggle: document.getElementById("createCeoDeliveryToggle"),
  openCreateProjectBtn: document.getElementById("openCreateProjectBtn"),
  homeCreateProjectBtn: document.getElementById("homeCreateProjectBtn"),
  closeCreateProjectBtn: document.getElementById("closeCreateProjectBtn"),
  submitCreateProjectBtn: document.getElementById("submitCreateProjectBtn"),
  manualContactModal: document.getElementById("manualContactModal"),
  manualContactForm: document.getElementById("manualContactForm"),
  manualContactTypeInput: document.getElementById("manualContactTypeInput"),
  manualContactValueInput: document.getElementById("manualContactValueInput"),
  manualContactObjectiveInput: document.getElementById("manualContactObjectiveInput"),
  manualContactNotesInput: document.getElementById("manualContactNotesInput"),
  manualContactAdditionalInfoInput: document.getElementById("manualContactAdditionalInfoInput"),
  closeManualContactModalBtn: document.getElementById("closeManualContactModalBtn"),
  submitManualContactBtn: document.getElementById("submitManualContactBtn"),
  toast: document.getElementById("toast"),
  contactsGridContainer: document.getElementById("contactsGridContainer"),
  threadsSidebar: document.getElementById("threadsSidebar"),
  threadSidebarList: document.getElementById("threadSidebarList"),
  chatPanel: document.getElementById("chatPanel"),
  closeThreadViewBtn: document.getElementById("closeThreadViewBtn"),
  crmMeta: document.getElementById("crmMeta"),
  crmHeadlineBadge: document.getElementById("crmHeadlineBadge"),
  crmOverviewStats: document.getElementById("crmOverviewStats"),
  crmSearchInput: document.getElementById("crmSearchInput"),
  refreshCrmBtn: document.getElementById("refreshCrmBtn"),
  crmThreadsSummary: document.getElementById("crmThreadsSummary"),
  crmThreadList: document.getElementById("crmThreadList"),
  crmThreadAvatar: document.getElementById("crmThreadAvatar"),
  crmThreadKicker: document.getElementById("crmThreadKicker"),
  crmThreadTitle: document.getElementById("crmThreadTitle"),
  crmThreadMeta: document.getElementById("crmThreadMeta"),
  crmThreadBadges: document.getElementById("crmThreadBadges"),
  crmTimeline: document.getElementById("crmTimeline"),
  crmReplyForm: document.getElementById("crmReplyForm"),
  crmReplySubject: document.getElementById("crmReplySubject"),
  crmReplyInput: document.getElementById("crmReplyInput"),
  crmMobileBackBtn: document.getElementById("crmMobileBackBtn"),
  sendCrmReplyBtn: document.getElementById("sendCrmReplyBtn"),
  contadoresMetrics: document.getElementById("contadoresMetrics"),
  contadoresSheetStatus: document.getElementById("contadoresSheetStatus"),
  contadoresSearchInput: document.getElementById("contadoresSearchInput"),
  contadoresStageFilter: document.getElementById("contadoresStageFilter"),
  contadoresPlatformFilter: document.getElementById("contadoresPlatformFilter"),
  contadoresManualReplyFilters: document.getElementById("contadoresManualReplyFilters"),
  contadoresBookedFilter: document.getElementById("contadoresBookedFilter"),
  contadoresNeedsHumanFilter: document.getElementById("contadoresNeedsHumanFilter"),
  contadoresArchivedFilter: document.getElementById("contadoresArchivedFilter"),
  refreshContadoresBtn: document.getElementById("refreshContadoresBtn"),
  contadoresEnabledToggle: document.getElementById("contadoresEnabledToggle"),
  contadoresConfigStatusNote: document.getElementById("contadoresConfigStatusNote"),
  contadoresStrategyStats: document.getElementById("contadoresStrategyStats"),
  contadoresStrategyFilters: document.getElementById("contadoresStrategyFilters"),
  contadoresLoomUrlInput: document.getElementById("contadoresLoomUrlInput"),
  contadoresCalendlyUrlInput: document.getElementById("contadoresCalendlyUrlInput"),
  contadoresAlertEmailsInput: document.getElementById("contadoresAlertEmailsInput"),
  saveContadoresConfigBtn: document.getElementById("saveContadoresConfigBtn"),
  contadoresLeadList: document.getElementById("contadoresLeadList"),
  contadoresListSummary: document.getElementById("contadoresListSummary"),
  contadoresLeadStage: document.getElementById("contadoresLeadStage"),
  contadoresLeadTitle: document.getElementById("contadoresLeadTitle"),
  contadoresLeadMeta: document.getElementById("contadoresLeadMeta"),
  contadoresLeadTimeline: document.getElementById("contadoresLeadTimeline"),
  contadoresEventTimeline: document.getElementById("contadoresEventTimeline"),
  contadoresLeadStrategies: document.getElementById("contadoresLeadStrategies"),
  contadoresMarkAnsweredBtn: document.getElementById("ctMarkAnsweredBtn"),
  contadoresDeleteLeadBtn: document.getElementById("ctDeleteLeadBtn"),
  contadoresToggleClosedBtn: document.getElementById("ctToggleClosedBtn"),
  contadoresManualForm: document.getElementById("contadoresManualForm"),
  contadoresManualInput: document.getElementById("contadoresManualInput"),
  sendContadoresManualBtn: document.getElementById("sendContadoresManualBtn"),
  contadoresActionOpenerBtn: document.getElementById("contadoresActionOpenerBtn"),
  contadoresActionLoomBtn: document.getElementById("contadoresActionLoomBtn"),
  contadoresActionVideoCheckBtn: document.getElementById("contadoresActionVideoCheckBtn"),
  contadoresActionCalendlyBtn: document.getElementById("contadoresActionCalendlyBtn"),
  contadoresActionBookedBtn: document.getElementById("contadoresActionBookedBtn"),
  contadoresActionArchiveBtn: document.getElementById("contadoresActionArchiveBtn"),
  contadoresActionUnarchiveBtn: document.getElementById("contadoresActionUnarchiveBtn"),
};

const prefersReducedMotionQuery = window.matchMedia
  ? window.matchMedia("(prefers-reduced-motion: reduce)")
  : null;

const pointerLightingState = {
  rafId: null,
  clientX: 0,
  clientY: 0,
  card: null,
};

const REPORT_TASK_TIMEOUT_MS = 240_000;
const REPORT_PDF_MODEL_TASK_TIMEOUT_MS = Math.max(10 * 60_000, REPORT_TASK_TIMEOUT_MS * 3);
const COMPANY_SCAN_TASK_TIMEOUT_MS = 3_000_000;
const CRM_REFRESH_INTERVAL_MS = 5_000;
const GMT_MINUS_THREE_OFFSET_HOURS = -3;
const GMT_MINUS_THREE_LABEL = "Florianopolis / GMT-3";
const MINUTE_MS = 60_000;
const HOUR_MS = 60 * MINUTE_MS;
const NAIVE_ISO_TIMESTAMP_RE = /^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}(?::\d{2}(?:\.\d+)?)?$/;
const AUTH_REQUIRED_ERROR_MESSAGE = "Authentication required.";
const SIDEBAR_ASSISTANT_SESSION_KEY = "konecta-sidebar-assistant-v1";
const SIDEBAR_ASSISTANT_MAX_MESSAGES = 24;

function normalizeBaseUrl(rawValue) {
  const value = String(rawValue || "").trim();
  if (!value) {
    return window.location.origin;
  }
  return value.replace(/\/+$/, "");
}

function parseUiStateFromUrl() {
  const params = new URLSearchParams(window.location.search);
  const rawSection = normalizeText(params.get("section"));
  const section = rawSection === "crm" ? "crm" : rawSection === "contadores" ? "contadores" : "audits";
  const companyId = String(params.get("company") || "").trim() || null;
  const contactId = String(params.get("contact") || "").trim() || null;
  const crmThreadId = String(params.get("crm_thread") || "").trim() || null;
  const contadoresLeadId = String(params.get("contadores_lead") || "").trim() || null;
  const archived = normalizeText(params.get("archived")) === "true";
  return { section, companyId, contactId, crmThreadId, contadoresLeadId, archived };
}

function syncUrlWithUiState() {
  const params = new URLSearchParams(window.location.search);
  params.delete("audit");
  const previousQuery = params.toString();
  params.set(
    "section",
    state.currentSection === "crm"
      ? "crm"
      : state.currentSection === "contadores"
        ? "contadores"
        : "audits",
  );

  if (state.currentSection === "crm") {
    params.delete("company");
    params.delete("contact");
    params.delete("archived");
    params.delete("contadores_lead");
    if (state.currentCrmThreadId) {
      params.set("crm_thread", state.currentCrmThreadId);
    } else {
      params.delete("crm_thread");
    }
    const nextQuery = params.toString();
    if (nextQuery === previousQuery) {
      return;
    }
    const nextUrl = `${window.location.pathname}${nextQuery ? `?${nextQuery}` : ""}${window.location.hash}`;
    window.history.replaceState(null, "", nextUrl);
    return;
  }

  if (state.currentSection === "contadores") {
    params.delete("company");
    params.delete("contact");
    params.delete("archived");
    params.delete("crm_thread");
    if (state.currentContadoresLeadId) {
      params.set("contadores_lead", state.currentContadoresLeadId);
    } else {
      params.delete("contadores_lead");
    }
    const nextQuery = params.toString();
    if (nextQuery === previousQuery) {
      return;
    }
    const nextUrl = `${window.location.pathname}${nextQuery ? `?${nextQuery}` : ""}${window.location.hash}`;
    window.history.replaceState(null, "", nextUrl);
    return;
  }

  params.delete("crm_thread");
  params.delete("contadores_lead");

  if (state.currentProjectId) {
    params.set("company", state.currentProjectId);
  } else {
    params.delete("company");
  }

  if (!state.currentProjectId) {
    params.delete("contact");
    params.delete("archived");
  } else if (state.showArchivedThreads) {
    params.set("archived", "true");
    params.delete("contact");
  } else {
    params.delete("archived");
    if (state.currentThreadId) {
      params.set("contact", state.currentThreadId);
    } else {
      params.delete("contact");
    }
  }

  const nextQuery = params.toString();
  if (nextQuery === previousQuery) {
    return;
  }

  const nextUrl = `${window.location.pathname}${nextQuery ? `?${nextQuery}` : ""}${window.location.hash}`;
  window.history.replaceState(null, "", nextUrl);
}

function escapeHtml(text) {
  const node = document.createElement("div");
  node.textContent = String(text ?? "");
  return node.innerHTML;
}

function normalizeText(value) {
  return String(value || "").trim().toLowerCase();
}

function currentSectionIsCrm() {
  return state.currentSection === "crm";
}

function currentSectionIsContadores() {
  return state.currentSection === "contadores";
}

function normalizeProjectLanguage(value) {
  const normalized = normalizeText(value).replace("-", "_");
  if (normalized.startsWith("en")) {
    return "en";
  }
  if (normalized.startsWith("es")) {
    return "es";
  }
  return "unknown";
}

function normalizeProjectCompanySize(value) {
  const normalized = normalizeText(value);
  if (["small", "medium", "large"].includes(normalized)) {
    return normalized;
  }
  return "unknown";
}

function normalizeProjectIndustry(value) {
  const normalized = normalizeText(value).replace(/[\s-]+/g, "_");
  const compact = normalized
    .split("_")
    .filter((part) => part)
    .join("_");
  return compact || "unknown";
}

function normalizeTagLabel(value) {
  return String(value || "").replace(/\s+/g, " ").trim();
}

function normalizeTagKey(value) {
  return normalizeTagLabel(value).toLowerCase();
}

function normalizeProjectTags(value) {
  if (!Array.isArray(value)) {
    return [];
  }
  const tags = [];
  const seen = new Set();
  value.forEach((item) => {
    const normalized = normalizeTagLabel(item);
    if (!normalized) {
      return;
    }
    const key = normalizeTagKey(normalized);
    if (seen.has(key)) {
      return;
    }
    seen.add(key);
    tags.push(normalized);
  });
  return tags;
}

function parseProjectTagsInput(value) {
  return normalizeProjectTags(String(value || "").split(/[\n,]+/));
}

function formatIndustryLabel(industrySlug) {
  const value = normalizeProjectIndustry(industrySlug);
  if (value === "unknown") {
    return "Unknown";
  }
  return value
    .split("_")
    .map((part) => (part ? `${part[0].toUpperCase()}${part.slice(1)}` : ""))
    .join(" ");
}

function renderMarkdown(markdown) {
  if (!markdown) {
    return "";
  }

  const codeBlocks = [];
  let codeBlockIndex = 0;

  let html = markdown.replace(/```([\s\S]*?)```/gim, (match, code) => {
    const placeholder = `__CODE_BLOCK_${codeBlockIndex}__`;
    codeBlocks[codeBlockIndex] = `<pre><code>${escapeHtml(code.trim())}</code></pre>`;
    codeBlockIndex += 1;
    return placeholder;
  });

  const lines = html.split("\n");
  const result = [];
  let inList = false;
  let listType = null;

  for (let i = 0; i < lines.length; i += 1) {
    const trimmed = lines[i].trim();

    if (trimmed.includes("__CODE_BLOCK_")) {
      const match = trimmed.match(/__CODE_BLOCK_(\d+)__/);
      if (match) {
        if (inList) {
          result.push(`</${listType}>`);
          inList = false;
          listType = null;
        }
        result.push(codeBlocks[parseInt(match[1], 10)]);
        continue;
      }
    }

    if (!trimmed) {
      if (inList) {
        result.push(`</${listType}>`);
        inList = false;
        listType = null;
      }
      continue;
    }

    if (trimmed.startsWith("### ")) {
      if (inList) {
        result.push(`</${listType}>`);
        inList = false;
        listType = null;
      }
      result.push(`<h3>${escapeHtml(trimmed.substring(4))}</h3>`);
    } else if (trimmed.startsWith("## ")) {
      if (inList) {
        result.push(`</${listType}>`);
        inList = false;
        listType = null;
      }
      result.push(`<h2>${escapeHtml(trimmed.substring(3))}</h2>`);
    } else if (trimmed.startsWith("# ")) {
      if (inList) {
        result.push(`</${listType}>`);
        inList = false;
        listType = null;
      }
      result.push(`<h1>${escapeHtml(trimmed.substring(2))}</h1>`);
    } else if (/^[-*] /.test(trimmed)) {
      if (!inList || listType !== "ul") {
        if (inList) {
          result.push(`</${listType}>`);
        }
        result.push("<ul>");
        inList = true;
        listType = "ul";
      }
      let content = escapeHtml(trimmed.substring(2));
      content = content.replace(/`([^`]+)`/g, "<code>$1</code>");
      result.push(`<li>${content}</li>`);
    } else if (/^\d+\. /.test(trimmed)) {
      if (!inList || listType !== "ol") {
        if (inList) {
          result.push(`</${listType}>`);
        }
        result.push("<ol>");
        inList = true;
        listType = "ol";
      }
      const match = trimmed.match(/^\d+\. (.*)$/);
      let content = escapeHtml(match[1]);
      content = content.replace(/`([^`]+)`/g, "<code>$1</code>");
      result.push(`<li>${content}</li>`);
    } else {
      if (inList) {
        result.push(`</${listType}>`);
        inList = false;
        listType = null;
      }
      let processed = escapeHtml(trimmed);
      processed = processed.replace(/`([^`]+)`/g, "<code>$1</code>");
      processed = processed.replace(/\*\*(.*?)\*\*/g, "<strong>$1</strong>");
      processed = processed.replace(/\*(.*?)\*/g, "<em>$1</em>");
      processed = processed.replace(/\[([^\]]+)\]\(([^)]+)\)/g, '<a href="$2" target="_blank" rel="noopener noreferrer">$1</a>');
      result.push(`<p>${processed}</p>`);
    }
  }

  if (inList) {
    result.push(`</${listType}>`);
  }

  return result.join("");
}

function createSidebarAssistantMessage(role, content) {
  return {
    id: `sidebar-assistant-${Date.now()}-${Math.random().toString(36).slice(2, 10)}`,
    role,
    content: String(content || "").trim(),
  };
}

function normalizeSidebarAssistantMessage(value) {
  if (!value || typeof value !== "object") {
    return null;
  }
  const role = value.role === "assistant" ? "assistant" : value.role === "user" ? "user" : "";
  const content = String(value.content || "").trim();
  if (!role || !content) {
    return null;
  }
  return {
    id: String(value.id || `sidebar-assistant-${Date.now()}-${Math.random().toString(36).slice(2, 10)}`),
    role,
    content,
  };
}

function trimSidebarAssistantMessages(messages) {
  if (!Array.isArray(messages)) {
    return [];
  }
  return messages.slice(-SIDEBAR_ASSISTANT_MAX_MESSAGES);
}

function persistSidebarAssistantSession() {
  if (!window.sessionStorage) {
    return;
  }
  try {
    window.sessionStorage.setItem(
      SIDEBAR_ASSISTANT_SESSION_KEY,
      JSON.stringify(trimSidebarAssistantMessages(state.sidebarAssistantMessages)),
    );
  } catch (error) {
    console.warn("Failed persisting sidebar assistant session", error);
  }
}

function hydrateSidebarAssistantSession() {
  if (!window.sessionStorage) {
    return;
  }
  try {
    const raw = window.sessionStorage.getItem(SIDEBAR_ASSISTANT_SESSION_KEY);
    if (!raw) {
      return;
    }
    const parsed = JSON.parse(raw);
    if (!Array.isArray(parsed)) {
      return;
    }
    state.sidebarAssistantMessages = trimSidebarAssistantMessages(
      parsed
        .map(normalizeSidebarAssistantMessage)
        .filter(Boolean),
    );
  } catch (error) {
    console.warn("Failed hydrating sidebar assistant session", error);
  }
}

function clearSidebarAssistantSession() {
  state.sidebarAssistantMessages = [];
  persistSidebarAssistantSession();
  renderSidebarAssistant();
}

function buildSidebarAssistantFocusLabel() {
  if (currentSectionIsCrm()) {
    return "Focus: CRM inbox. Ask global questions about CEO threads, companies, contacts, or messages.";
  }
  if (!state.currentProject) {
    return "Focus: no company selected. Ask global questions across the whole database.";
  }
  const companyName = String(state.currentProject.company_name || "Selected company").trim();
  const thread = getCurrentThread();
  if (!thread) {
    return `Focus: ${companyName}. The selected company will be sent as context for follow-up questions.`;
  }
  return `Focus: ${companyName} · ${thread.contact_type} · ${thread.contact_value}.`;
}

function renderSidebarAssistantMessage(message) {
  const isAssistant = message.role === "assistant";
  const label = isAssistant ? "DB Copilot" : "You";
  const bodyHtml = isAssistant
    ? renderMarkdown(message.content)
    : `<p>${escapeHtml(message.content).replace(/\n/g, "<br>")}</p>`;
  return `
    <article class="sidebar-assistant-bubble ${isAssistant ? "is-assistant" : "is-user"}">
      <p class="sidebar-assistant-bubble-label">${label}</p>
      <div class="sidebar-assistant-bubble-body">
        ${bodyHtml}
      </div>
    </article>
  `;
}

function scrollSidebarAssistantToLatest() {
  if (!dom.sidebarAssistantMessages) {
    return;
  }
  window.requestAnimationFrame(() => {
    dom.sidebarAssistantMessages.scrollTop = dom.sidebarAssistantMessages.scrollHeight;
  });
}

function syncSidebarAssistantComposer() {
  if (!dom.sidebarAssistantInput || !dom.sidebarAssistantSendBtn || !dom.sidebarAssistantStatus) {
    return;
  }
  const busy = state.pendingSidebarAssistantReply;
  dom.sidebarAssistantInput.disabled = busy;
  dom.sidebarAssistantSendBtn.disabled = busy;
  dom.sidebarAssistantSendBtn.textContent = busy ? "Thinking..." : "Ask";
  dom.sidebarAssistantStatus.textContent = busy
    ? "Consultando la DB local..."
    : "Stateless backend. Historial solo en esta pestaña.";
}

function renderSidebarAssistant() {
  if (!dom.sidebarAssistantCard || !dom.sidebarAssistantMeta || !dom.sidebarAssistantMessages) {
    return;
  }

  dom.sidebarAssistantMeta.textContent = buildSidebarAssistantFocusLabel();
  syncSidebarAssistantComposer();

  if (!state.sidebarAssistantMessages.length) {
    dom.sidebarAssistantMessages.innerHTML = "";
    return;
  }

  dom.sidebarAssistantMessages.innerHTML = trimSidebarAssistantMessages(state.sidebarAssistantMessages)
    .map(renderSidebarAssistantMessage)
    .join("");
  scrollSidebarAssistantToLatest();
}

async function handleSidebarAssistantSubmit(event) {
  event.preventDefault();
  if (!dom.sidebarAssistantInput || state.pendingSidebarAssistantReply) {
    return;
  }

  const inputText = String(dom.sidebarAssistantInput.value || "").trim();
  if (!inputText) {
    dom.sidebarAssistantInput.focus();
    return;
  }

  const userMessage = createSidebarAssistantMessage("user", inputText);
  state.sidebarAssistantMessages = trimSidebarAssistantMessages([
    ...state.sidebarAssistantMessages,
    userMessage,
  ]);
  state.pendingSidebarAssistantReply = true;
  dom.sidebarAssistantInput.value = "";
  persistSidebarAssistantSession();
  renderSidebarAssistant();

  try {
    const payload = await apiFetch("/api/sidebar-assistant/reply", {
      method: "POST",
      body: {
        conversation: state.sidebarAssistantMessages.map((message) => ({
          role: message.role,
          content: message.content,
        })),
        company_id: state.currentProjectId,
        contact_id: state.currentThreadId,
      },
    });
    const replyText = String(payload?.reply || "").trim();
    if (!replyText) {
      throw new Error("Sidebar assistant returned an empty reply.");
    }
    state.sidebarAssistantMessages = trimSidebarAssistantMessages([
      ...state.sidebarAssistantMessages,
      createSidebarAssistantMessage("assistant", replyText),
    ]);
    persistSidebarAssistantSession();
  } catch (error) {
    state.sidebarAssistantMessages = state.sidebarAssistantMessages.filter((message) => message.id !== userMessage.id);
    dom.sidebarAssistantInput.value = inputText;
    showToast(error.message || "Failed querying the sidebar assistant", true);
  } finally {
    state.pendingSidebarAssistantReply = false;
    renderSidebarAssistant();
  }
}

function debounce(fn, ms) {
  let timeout = null;
  return function debounced(...args) {
    if (timeout) {
      window.clearTimeout(timeout);
    }
    timeout = window.setTimeout(() => {
      timeout = null;
      fn.apply(this, args);
    }, ms);
  };
}

function prefersReducedMotion() {
  return Boolean(prefersReducedMotionQuery && prefersReducedMotionQuery.matches);
}

function applyPointerLightingFrame() {
  pointerLightingState.rafId = null;
  document.documentElement.style.setProperty("--mouse-x", `${pointerLightingState.clientX}px`);
  document.documentElement.style.setProperty("--mouse-y", `${pointerLightingState.clientY}px`);

  const card = pointerLightingState.card;
  if (!card) {
    return;
  }
  const rect = card.getBoundingClientRect();
  card.style.setProperty("--card-mouse-x", `${pointerLightingState.clientX - rect.left}px`);
  card.style.setProperty("--card-mouse-y", `${pointerLightingState.clientY - rect.top}px`);
}

function schedulePointerLighting(event) {
  pointerLightingState.clientX = event.clientX;
  pointerLightingState.clientY = event.clientY;
  pointerLightingState.card = event.target.closest(".project-card, .thread-item, .btn-primary");

  if (pointerLightingState.rafId) {
    return;
  }
  pointerLightingState.rafId = window.requestAnimationFrame(applyPointerLightingFrame);
}

function wait(ms) {
  return new Promise((resolve) => {
    window.setTimeout(resolve, ms);
  });
}

function redirectToLogin() {
  if (state.authRedirectInProgress) {
    return;
  }
  state.authRedirectInProgress = true;
  window.location.replace("/login");
}

async function fetchWithAuth(url, options = {}) {
  const response = await fetch(url, {
    credentials: "same-origin",
    ...options,
  });
  if (response.status === 401) {
    redirectToLogin();
    throw new Error(AUTH_REQUIRED_ERROR_MESSAGE);
  }
  return response;
}

function parseApiDateValue(value) {
  if (!value) {
    return null;
  }
  if (value instanceof Date) {
    return Number.isNaN(value.getTime()) ? null : new Date(value.getTime());
  }
  const rawValue = typeof value === "string" ? value.trim() : value;
  const normalizedValue =
    typeof rawValue === "string" && NAIVE_ISO_TIMESTAMP_RE.test(rawValue) ? `${rawValue}Z` : rawValue;
  const date = new Date(normalizedValue);
  if (Number.isNaN(date.getTime())) {
    return null;
  }
  return date;
}

function toTimestamp(value) {
  const date = parseApiDateValue(value);
  if (!date) {
    return 0;
  }
  return date.getTime();
}

function padTwoDigits(value) {
  return String(value).padStart(2, "0");
}

function truncateTimestampToMinute(timestamp) {
  if (!Number.isFinite(timestamp) || timestamp <= 0) {
    return 0;
  }
  return Math.floor(timestamp / MINUTE_MS) * MINUTE_MS;
}

function toGmtMinusThreeDate(value) {
  const timestamp = value instanceof Date ? value.getTime() : toTimestamp(value);
  if (!timestamp) {
    return null;
  }
  return new Date(timestamp + GMT_MINUS_THREE_OFFSET_HOURS * HOUR_MS);
}

function formatGmtMinusThreeDate(value) {
  const date = toGmtMinusThreeDate(value);
  if (!date) {
    return "-";
  }
  const month = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"][
    date.getUTCMonth()
  ];
  const day = date.getUTCDate();
  const rawHours = date.getUTCHours();
  const minutes = padTwoDigits(date.getUTCMinutes());
  const suffix = rawHours >= 12 ? "PM" : "AM";
  const displayHours = rawHours % 12 || 12;
  return `${month} ${day} at ${padTwoDigits(displayHours)}:${minutes} ${suffix}`;
}

function formatGmtMinusThreeDateTimeLocalValue(value) {
  const date = toGmtMinusThreeDate(value);
  if (!date) {
    return "";
  }
  return `${date.getUTCFullYear()}-${padTwoDigits(date.getUTCMonth() + 1)}-${padTwoDigits(date.getUTCDate())}T${padTwoDigits(date.getUTCHours())}:${padTwoDigits(date.getUTCMinutes())}`;
}

function parseGmtMinusThreeDateTimeLocalValue(value) {
  const trimmed = String(value || "").trim();
  const match = trimmed.match(/^(\d{4})-(\d{2})-(\d{2})T(\d{2}):(\d{2})$/);
  if (!match) {
    return null;
  }
  const [, yearText, monthText, dayText, hoursText, minutesText] = match;
  const year = Number(yearText);
  const month = Number(monthText);
  const day = Number(dayText);
  const hours = Number(hoursText);
  const minutes = Number(minutesText);
  const date = new Date(Date.UTC(year, month - 1, day, hours - GMT_MINUS_THREE_OFFSET_HOURS, minutes));
  return Number.isNaN(date.getTime()) ? null : date;
}

function formatDate(isoString) {
  const date = parseApiDateValue(isoString);
  if (!date) {
    if (!isoString) {
      return "-";
    }
    return isoString;
  }
  return new Intl.DateTimeFormat("en-US", {
    month: "short",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  }).format(date);
}

function formatTime(isoString) {
  const date = parseApiDateValue(isoString);
  if (!date) {
    return "--:--";
  }
  return new Intl.DateTimeFormat("en-US", {
    hour: "2-digit",
    minute: "2-digit",
  }).format(date);
}

function formatRelativeDate(isoString) {
  const timestamp = toTimestamp(isoString);
  if (!timestamp) {
    return "unknown";
  }
  const deltaMs = Date.now() - timestamp;
  if (deltaMs < 60_000) {
    return "just now";
  }
  const minutes = Math.floor(deltaMs / 60_000);
  if (minutes < 60) {
    return `${minutes}m ago`;
  }
  const hours = Math.floor(minutes / 60);
  if (hours < 24) {
    return `${hours}h ago`;
  }
  const days = Math.floor(hours / 24);
  if (days < 7) {
    return `${days}d ago`;
  }
  return formatDate(isoString);
}

function normalizeReportWindowMinutesValue(rawMinutes, rawHours = null) {
  const parsedMinutes = Number.parseInt(String(rawMinutes ?? "").trim(), 10);
  if (Number.isFinite(parsedMinutes) && parsedMinutes >= 1) {
    return parsedMinutes;
  }
  const parsedHours = Number.parseInt(String(rawHours ?? "").trim(), 10);
  if (Number.isFinite(parsedHours) && parsedHours >= 1) {
    return parsedHours * 60;
  }
  return 24 * 60;
}

function splitReportWindowMinutes(totalMinutes) {
  const normalizedMinutes = Math.max(1, Number(totalMinutes || 0));
  return {
    hours: Math.floor(normalizedMinutes / 60),
    minutes: normalizedMinutes % 60,
  };
}

function legacyReportWindowHoursFromMinutes(totalMinutes) {
  const normalizedMinutes = normalizeReportWindowMinutesValue(totalMinutes);
  if (normalizedMinutes % 60 !== 0) {
    return null;
  }
  return Math.max(1, normalizedMinutes / 60);
}

function formatReportWindowDuration(totalMinutes) {
  const { hours, minutes } = splitReportWindowMinutes(totalMinutes);
  const parts = [];
  if (hours) {
    parts.push(`${hours}h`);
  }
  if (minutes) {
    parts.push(`${minutes}m`);
  }
  return parts.join(" ") || "1m";
}

function computeProjectReportDeadline(project, overrideReportWindowMinutes = null) {
  const explicitScheduledAt = parseApiDateValue(project?.scheduled_send_at);
  if (overrideReportWindowMinutes == null && explicitScheduledAt) {
    return explicitScheduledAt;
  }
  const createdTimestamp = truncateTimestampToMinute(toTimestamp(project?.created_at));
  if (!createdTimestamp) {
    return null;
  }
  const reportWindowMinutes = normalizeReportWindowMinutesValue(
    overrideReportWindowMinutes ?? project?.report_window_minutes,
    project?.report_window_hours,
  );
  const deadline = new Date(createdTimestamp + reportWindowMinutes * MINUTE_MS);
  if (Number.isNaN(deadline.getTime())) {
    return null;
  }
  return deadline;
}

function buildProjectDeadlineSummary(project) {
  const reportWindowMinutes = normalizeReportWindowMinutesValue(
    project?.report_window_minutes,
    project?.report_window_hours,
  );
  const scheduledAt = computeProjectReportDeadline(project);
  const sentAt = project?.ceo_delivery_sent_at ? formatGmtMinusThreeDate(project.ceo_delivery_sent_at) : null;
  const deadlineAt = scheduledAt ? formatGmtMinusThreeDate(scheduledAt) : "Unknown";

  if (sentAt) {
    return {
      windowLabel: "Report window",
      windowValue: formatReportWindowDuration(reportWindowMinutes),
      scheduleLabel: `Report sent (${GMT_MINUS_THREE_LABEL})`,
      scheduleValue: sentAt,
      note: `Actual CEO delivery time in ${GMT_MINUS_THREE_LABEL}`,
    };
  }

  return {
    windowLabel: "Report window",
    windowValue: formatReportWindowDuration(reportWindowMinutes),
    scheduleLabel: projectCeoDeliveryEnabled(project)
      ? `Scheduled send (${GMT_MINUS_THREE_LABEL})`
      : `Report deadline (${GMT_MINUS_THREE_LABEL})`,
    scheduleValue: deadlineAt,
    note: projectCeoDeliveryEnabled(project)
      ? `Computed from scan start or exact override in ${GMT_MINUS_THREE_LABEL}`
      : `CEO delivery is off; showing the configured deadline in ${GMT_MINUS_THREE_LABEL}`,
  };
}

function pluralize(count, singular, plural) {
  return `${count} ${count === 1 ? singular : plural}`;
}

function statusClassName(status) {
  const normalized = normalizeText(status).replace(/[^a-z0-9_-]+/g, "-");
  return normalized || "unknown";
}

function statusChip(status) {
  const safeText = escapeHtml(status || "unknown");
  const safeClass = escapeHtml(statusClassName(status));
  return `<span class="status-chip ${safeClass}">${safeText}</span>`;
}

function managementChip(enabled) {
  const ai = Boolean(enabled);
  const label = ai ? "Automation" : "Manual";
  const safeClass = ai ? "management-ai" : "management-human";
  return `<span class="status-chip ${safeClass}">${escapeHtml(label)}</span>`;
}

function sortProjects(projects) {
  return [...projects].sort((left, right) => {
    const rightTs = toTimestamp(right.updated_at || right.created_at);
    const leftTs = toTimestamp(left.updated_at || left.created_at);
    return rightTs - leftTs;
  });
}

function getLocalDayKey(value) {
  const date = parseApiDateValue(value);
  if (!date) {
    return "";
  }
  const year = date.getFullYear();
  const month = padTwoDigits(date.getMonth() + 1);
  const day = padTwoDigits(date.getDate());
  return `${year}-${month}-${day}`;
}

function getLocalDayStartTimestamp(value) {
  const date = parseApiDateValue(value);
  if (!date) {
    return 0;
  }
  return new Date(date.getFullYear(), date.getMonth(), date.getDate()).getTime();
}

function formatProjectCreatedDayLabel(value) {
  const date = parseApiDateValue(value);
  if (!date) {
    return "Unknown day";
  }
  const formatterOptions = {
    weekday: "long",
    month: "short",
    day: "numeric",
  };
  if (date.getFullYear() !== new Date().getFullYear()) {
    formatterOptions.year = "numeric";
  }
  return new Intl.DateTimeFormat("en-US", formatterOptions).format(date);
}

function sortHomeProjects(projects) {
  return [...projects].sort((left, right) => {
    const rightDayTs = getLocalDayStartTimestamp(right.created_at);
    const leftDayTs = getLocalDayStartTimestamp(left.created_at);
    if (rightDayTs !== leftDayTs) {
      return rightDayTs - leftDayTs;
    }

    const rightUpdatedTs = toTimestamp(right.updated_at || right.created_at);
    const leftUpdatedTs = toTimestamp(left.updated_at || left.created_at);
    if (rightUpdatedTs !== leftUpdatedTs) {
      return rightUpdatedTs - leftUpdatedTs;
    }

    return toTimestamp(right.created_at) - toTimestamp(left.created_at);
  });
}

function groupProjectsByCreatedDay(projects) {
  const dayGroups = [];
  const groupsByKey = new Map();

  sortHomeProjects(projects).forEach((project) => {
    const dayKey = getLocalDayKey(project.created_at) || "unknown";
    let group = groupsByKey.get(dayKey);
    if (!group) {
      group = {
        dayKey,
        label: formatProjectCreatedDayLabel(project.created_at),
        projects: [],
      };
      groupsByKey.set(dayKey, group);
      dayGroups.push(group);
    }
    group.projects.push(project);
  });

  return dayGroups;
}

function normalizeCompanySummary(raw) {
  const normalizedCeoEmail = String(raw.ceo_email || "").trim();
  const reportWindowMinutes = normalizeReportWindowMinutesValue(
    raw.report_window_minutes,
    raw.report_window_hours,
  );
  return {
    ...raw,
    total_threads: raw.total_contacts ?? 0,
    pending_delivery_contacts: Number(raw.pending_delivery_contacts || 0),
    tags: normalizeProjectTags(raw.tags),
    report_window_hours: legacyReportWindowHoursFromMinutes(reportWindowMinutes),
    report_window_minutes: reportWindowMinutes,
    scheduled_send_at: raw.scheduled_send_at || computeProjectReportDeadline({
      created_at: raw.created_at,
      report_window_minutes: reportWindowMinutes,
    })?.toISOString() || null,
    can_rescan: Boolean(raw.can_rescan),
    conversation_automation_enabled: Boolean(raw.conversation_automation_enabled),
    ceo_delivery_enabled: Boolean(raw.ceo_delivery_enabled),
    has_ceo_email: Boolean(raw.has_ceo_email || normalizedCeoEmail),
    processing: Boolean(raw.processing),
    has_contact_reply: Boolean(raw.has_contact_reply),
  };
}

function hasPendingCompanyTask(companyId) {
  return Boolean(companyId && state.pendingCompanyTasks[companyId]);
}

function projectIsProcessing(project) {
  if (!project) {
    return false;
  }
  if (hasPendingCompanyTask(project.id)) {
    return true;
  }
  if (typeof project.processing === "boolean") {
    return project.processing;
  }
  return normalizeText(project.status) === "initializing";
}

function projectCanRescan(project) {
  if (!project) {
    return false;
  }
  if (projectIsProcessing(project)) {
    return false;
  }
  return Boolean(project.can_rescan) && Number(project.total_threads || 0) === 0;
}

function shouldRefreshProcessingProjects() {
  return state.projects.some((project) => projectIsProcessing(project)) || projectIsProcessing(state.currentProject);
}

function stopProcessingRefreshLoop() {
  if (state.processingRefreshTimer) {
    window.clearTimeout(state.processingRefreshTimer);
    state.processingRefreshTimer = null;
  }
}

function syncProcessingRefreshLoop() {
  if (!shouldRefreshProcessingProjects()) {
    stopProcessingRefreshLoop();
    return;
  }
  if (state.processingRefreshTimer || state.processingRefreshInFlight) {
    return;
  }
  state.processingRefreshTimer = window.setTimeout(() => {
    state.processingRefreshTimer = null;
    void refreshProcessingProjects();
  }, 2000);
}

async function refreshProcessingProjects() {
  if (state.processingRefreshInFlight) {
    return;
  }
  if (!shouldRefreshProcessingProjects()) {
    stopProcessingRefreshLoop();
    return;
  }
  state.processingRefreshInFlight = true;
  try {
    if (state.currentProjectId) {
      await refreshCurrentProject(true);
    } else {
      await loadProjects();
    }
  } catch {
    // Processing polling is best-effort; the next loop will retry.
  } finally {
    state.processingRefreshInFlight = false;
    syncProcessingRefreshLoop();
  }
}

function toProjectViewModel(project) {
  const summary = normalizeCompanySummary(project);
  if (projectIsProcessing(summary)) {
    return {
      ...summary,
      processing: true,
      status: "initializing",
    };
  }
  return summary;
}

function normalizeCompanyDetail(raw) {
  const contacts = Array.isArray(raw.contacts) ? raw.contacts : [];
  const threads = contacts.map((contact) => ({
    ...contact,
    contact_type: contact.type,
    contact_value: contact.value,
    contact_notes: contact.notes || null,
    contact_name: contact.value,
    conversation_id: contact.id,
  }));
  return {
    ...normalizeCompanySummary(raw),
    threads,
  };
}

function normalizeCrmThread(raw) {
  return {
    ...raw,
    company_name: String(raw?.company_name || "").trim() || "Unknown company",
    participant_email: String(raw?.participant_email || "").trim().toLowerCase(),
    subject: String(raw?.subject || "").trim() || "No subject",
    unread_message_count: Math.max(0, Number(raw?.unread_message_count || 0)),
    last_message_preview: String(raw?.last_message_preview || "").trim(),
    last_message_direction: raw?.last_message_direction ? normalizeText(raw.last_message_direction) : null,
    last_message_status: raw?.last_message_status ? normalizeText(raw.last_message_status) : null,
  };
}

function normalizeCrmMessage(raw) {
  return {
    ...raw,
    direction: normalizeText(raw?.direction) === "inbound" ? "inbound" : "outbound",
    kind: normalizeText(raw?.kind) || "manual_reply",
    status: normalizeText(raw?.status) || "pending",
    body: String(raw?.body || ""),
    subject: String(raw?.subject || "").trim(),
    from_email: raw?.from_email ? String(raw.from_email).trim().toLowerCase() : null,
    to_email: raw?.to_email ? String(raw.to_email).trim().toLowerCase() : null,
  };
}

function sortCrmThreads(threads) {
  return [...threads].sort((left, right) => {
    const timeDelta =
      toTimestamp(right?.last_message_at || right?.updated_at || right?.created_at) -
      toTimestamp(left?.last_message_at || left?.updated_at || left?.created_at);
    if (timeDelta !== 0) {
      return timeDelta;
    }
    const leftTitle = normalizeText(`${left.company_name} ${left.participant_email}`);
    const rightTitle = normalizeText(`${right.company_name} ${right.participant_email}`);
    return leftTitle.localeCompare(rightTitle);
  });
}

function getCurrentCrmThread() {
  if (!state.currentCrmThreadId) {
    return null;
  }
  return state.crmThreads.find((thread) => thread.id === state.currentCrmThreadId) || state.currentCrmThread || null;
}

function isCompactCrmViewport() {
  if (window.matchMedia) {
    return window.matchMedia("(max-width: 760px)").matches;
  }
  return window.innerWidth <= 760;
}

function setCrmMobilePane(pane) {
  state.crmMobilePane = pane === "detail" ? "detail" : "list";
}

function syncCrmMobilePane() {
  if (!getCurrentCrmThread()) {
    setCrmMobilePane("list");
  }
}

function buildCrmMessagePreview(body, maxChars = 160) {
  const compact = String(body || "").replace(/\s+/g, " ").trim();
  return truncateWithEllipsis(compact, maxChars);
}

function buildCrmMonogram(value) {
  const parts = String(value || "")
    .trim()
    .split(/[\s@._-]+/)
    .filter((part) => part);
  if (!parts.length) {
    return "--";
  }
  if (parts.length === 1) {
    return parts[0].slice(0, 2).toUpperCase();
  }
  return `${parts[0][0] || ""}${parts[1][0] || ""}`.toUpperCase();
}

function crmThreadDirectionLabel(direction) {
  return normalizeText(direction) === "inbound" ? "CEO replied" : "You replied";
}

function crmThreadStateLabel(thread) {
  const unread = Math.max(0, Number(thread?.unread_message_count || 0));
  if (unread > 0) {
    return unread === 1 ? "Needs reply" : `${unread} unread`;
  }
  const status = normalizeText(thread?.last_message_status);
  if (status === "pending") {
    return "Pending send";
  }
  if (normalizeText(thread?.last_message_direction) === "inbound") {
    return "CEO waiting";
  }
  return "Waiting on CEO";
}

function crmThreadStateTone(thread) {
  const unread = Math.max(0, Number(thread?.unread_message_count || 0));
  if (unread > 0) {
    return "received";
  }
  const status = normalizeText(thread?.last_message_status);
  if (status === "pending") {
    return "pending";
  }
  return normalizeText(thread?.last_message_direction) === "inbound" ? "received" : "sent";
}

function renderCrmOverviewStats() {
  if (!dom.crmOverviewStats) {
    return;
  }
  const selectedThread = getCurrentCrmThread();
  const totalThreads = state.crmThreads.length;
  const latestThread = state.crmThreads[0] || null;
  const pendingThreadCount = state.crmThreads.filter(
    (thread) => normalizeText(thread.last_message_status) === "pending",
  ).length;
  if (!totalThreads) {
    dom.crmOverviewStats.innerHTML = "";
    return;
  }
  const focusThread = selectedThread || latestThread;
  const attentionNote = state.crmUnreadThreadCount > 0
    ? `${pluralize(state.crmUnreadMessageCount, "unread reply", "unread replies")} across ${pluralize(
        state.crmUnreadThreadCount,
        "thread",
        "threads",
      )}`
    : pendingThreadCount > 0
      ? `${pluralize(pendingThreadCount, "thread still pending send", "threads still pending send")}`
      : "Inbox is caught up";
  const focusNote = focusThread
    ? `${focusThread.participant_email || "-"} · ${formatRelativeDate(crmThreadTimestamp(focusThread))}`
    : "Waiting for the first report delivery";

  dom.crmOverviewStats.innerHTML = `
    <article class="crm-overview-card">
      <span class="crm-overview-label">Needs Review</span>
      <strong class="crm-overview-value">${escapeHtml(String(state.crmUnreadThreadCount))}</strong>
      <p class="crm-overview-note">${escapeHtml(attentionNote)}</p>
    </article>
    <article class="crm-overview-card">
      <span class="crm-overview-label">${escapeHtml(selectedThread ? "Focused Thread" : "Latest Thread")}</span>
      <strong class="crm-overview-value crm-overview-value-title">${escapeHtml(
        focusThread ? focusThread.company_name : "Inbox quiet",
      )}</strong>
      <p class="crm-overview-note">${escapeHtml(focusNote)}</p>
    </article>
  `;
}

function recalculateCrmUnreadCounts() {
  state.crmUnreadThreadCount = state.crmThreads.filter((thread) => thread.unread_message_count > 0).length;
  state.crmUnreadMessageCount = state.crmThreads.reduce(
    (total, thread) => total + Math.max(0, Number(thread.unread_message_count || 0)),
    0,
  );
}

function renderCrmBadge() {
  if (!dom.sectionCrmBadge) {
    return;
  }
  const unread = Math.max(0, Number(state.crmUnreadMessageCount || 0));
  if (dom.crmHeadlineBadge) {
    dom.crmHeadlineBadge.textContent = unread > 0
      ? `${unread > 99 ? "99+" : unread} unread`
      : "All caught up";
    dom.crmHeadlineBadge.classList.toggle("has-unread", unread > 0);
  }
  if (unread <= 0) {
    dom.sectionCrmBadge.classList.add("hidden");
    dom.sectionCrmBadge.textContent = "0";
    return;
  }
  dom.sectionCrmBadge.classList.remove("hidden");
  dom.sectionCrmBadge.textContent = unread > 99 ? "99+" : String(unread);
}

function upsertCrmThreadSummary(rawThread) {
  const summary = normalizeCrmThread(rawThread);
  let found = false;
  state.crmThreads = sortCrmThreads(
    state.crmThreads.map((thread) => {
      if (thread.id !== summary.id) {
        return thread;
      }
      found = true;
      return {
        ...thread,
        ...summary,
      };
    }),
  );
  if (!found) {
    state.crmThreads = sortCrmThreads([summary, ...state.crmThreads]);
  }
  if (state.currentCrmThreadId === summary.id) {
    state.currentCrmThread = {
      ...(state.currentCrmThread || {}),
      ...summary,
    };
  }
  recalculateCrmUnreadCounts();
  renderCrmBadge();
}

function applyCrmThreadsPayload(payload, { preserveSelection = true, selectFirstIfNeeded = false } = {}) {
  const threads = sortCrmThreads(
    (Array.isArray(payload?.threads) ? payload.threads : []).map(normalizeCrmThread),
  );
  state.crmThreads = threads;
  state.crmUnreadThreadCount = Math.max(0, Number(payload?.unread_thread_count || 0));
  state.crmUnreadMessageCount = Math.max(0, Number(payload?.unread_message_count || 0));

  const selectionExists = Boolean(
    state.currentCrmThreadId && threads.some((thread) => thread.id === state.currentCrmThreadId),
  );
  if (!preserveSelection || !selectionExists) {
    const nextThreadId = selectFirstIfNeeded && threads.length ? threads[0].id : null;
    state.currentCrmThreadId = nextThreadId;
    if (!nextThreadId) {
      state.currentCrmThread = null;
      state.crmMessages = [];
    }
  }

  if (state.currentCrmThreadId) {
    state.currentCrmThread =
      threads.find((thread) => thread.id === state.currentCrmThreadId) || state.currentCrmThread;
  }

  renderCrmBadge();
}

function getFilteredCrmThreads() {
  return state.crmThreads.filter((thread) => {
    if (!state.crmQuery) {
      return true;
    }
    const haystack = normalizeText(
      `${thread.company_name} ${thread.participant_email} ${thread.subject} ${thread.last_message_preview}`,
    );
    return haystack.includes(state.crmQuery);
  });
}

function crmThreadTimestamp(thread) {
  return thread?.last_message_at || thread?.updated_at || thread?.created_at || null;
}

function crmMessageTimestamp(message) {
  return message?.sent_at || message?.received_at || message?.created_at || null;
}

function crmMessageKindLabel(kind) {
  const normalized = normalizeText(kind);
  if (normalized === "report_delivery") {
    return "Report sent";
  }
  if (normalized === "ceo_reply") {
    return "CEO replied";
  }
  return "Manual reply";
}

function crmMessageDirectionLabel(direction) {
  return normalizeText(direction) === "inbound" ? "CEO" : "You";
}

function crmMessageStatusLabel(status) {
  const normalized = normalizeText(status);
  if (normalized === "received") {
    return "Received";
  }
  if (normalized === "sent") {
    return "Sent";
  }
  return "Pending send";
}

function shouldShowCrmMessageStatus(message) {
  return normalizeText(message?.direction) === "outbound" && normalizeText(message?.status) !== "sent";
}

function syncCrmComposerState() {
  const currentThread = getCurrentCrmThread();
  const isBusy = Boolean(currentThread && state.pendingCrmReplyThreadId === currentThread.id);
  setBusy(dom.sendCrmReplyBtn, isBusy, "Sending...", "Send Reply");
  if (dom.crmReplySubject) {
    dom.crmReplySubject.textContent = currentThread
      ? currentThread.subject
      : "Select a thread to preserve subject continuity.";
  }
  if (dom.crmReplyInput) {
    dom.crmReplyInput.disabled = !currentThread || isBusy;
    dom.crmReplyInput.placeholder = currentThread
      ? `Reply to ${currentThread.participant_email}...`
      : "Select a CRM thread to reply.";
  }
}

function renderCrmThreadList() {
  if (!dom.crmThreadList || !dom.crmThreadsSummary || !dom.crmMeta) {
    return;
  }

  const filteredThreads = getFilteredCrmThreads();
  const totalThreads = state.crmThreads.length;
  const selectedThread = getCurrentCrmThread();
  dom.crmMeta.textContent =
    totalThreads > 0
      ? `${pluralize(totalThreads, "thread", "threads")} · ${pluralize(
          state.crmUnreadThreadCount,
          "thread needs review",
          "threads need review",
        )}${selectedThread ? ` · focused on ${selectedThread.company_name}` : ""}`
      : "Review unread CEO replies and keep audit delivery threads moving.";
  dom.crmThreadsSummary.textContent =
    totalThreads > 0
      ? `${filteredThreads.length}/${totalThreads} visible · ${pluralize(
          state.crmUnreadMessageCount,
          "unread message",
          "unread messages",
        )}`
      : "No CRM threads yet.";
  renderCrmOverviewStats();

  if (!totalThreads) {
    dom.crmThreadList.innerHTML = `
      <div class="crm-empty-state">
        <div>
          <h3>No CRM threads yet</h3>
          <p>Threads appear here only after the first audit report email is actually sent and registered.</p>
        </div>
      </div>
    `;
    return;
  }

  if (!filteredThreads.length) {
    dom.crmThreadList.innerHTML = `<p class="empty-note">No CRM threads match the current search.</p>`;
    return;
  }

  dom.crmThreadList.innerHTML = filteredThreads
    .map((thread) => {
      const isActive = thread.id === state.currentCrmThreadId;
      const unread = Math.max(0, Number(thread.unread_message_count || 0));
      const preview = thread.last_message_preview || "Audit report delivery thread.";
      const stateLabel = crmThreadStateLabel(thread);
      const stateTone = crmThreadStateTone(thread);
      return `
        <button
          type="button"
          class="crm-thread-item ${isActive ? "active" : ""} ${unread > 0 ? "unread" : ""}"
          data-crm-thread-id="${escapeHtml(thread.id)}"
        >
          <div class="crm-thread-top">
            <div class="crm-thread-identity">
              <span class="crm-thread-avatar">${escapeHtml(buildCrmMonogram(thread.company_name))}</span>
              <div>
                <p class="crm-thread-company">${escapeHtml(thread.company_name)}</p>
                <p class="crm-thread-email">${escapeHtml(thread.participant_email || "-")}</p>
              </div>
            </div>
            <div class="crm-thread-meta-stack">
              <span class="crm-thread-time">${escapeHtml(formatRelativeDate(crmThreadTimestamp(thread)))}</span>
              ${unread > 0 ? `<span class="crm-thread-unread">${escapeHtml(String(unread))}</span>` : ""}
            </div>
          </div>
          <div class="crm-thread-chip-row">
            <span class="crm-thread-chip ${escapeHtml(stateTone)}">${escapeHtml(stateLabel)}</span>
            ${thread.last_message_direction ? `<span class="crm-thread-chip subtle">${escapeHtml(
              crmThreadDirectionLabel(thread.last_message_direction),
            )}</span>` : ""}
          </div>
          <div class="crm-thread-body">
            <p class="crm-thread-subject">${escapeHtml(thread.subject)}</p>
            <p class="crm-thread-preview">${escapeHtml(preview)}</p>
          </div>
        </button>
      `;
    })
    .join("");

  dom.crmThreadList.querySelectorAll("[data-crm-thread-id]").forEach((node) => {
    node.addEventListener("click", async () => {
      const threadId = String(node.getAttribute("data-crm-thread-id") || "").trim();
      if (!threadId) {
        return;
      }
      await openCrmThread(threadId);
    });
  });
}

function renderCrmThreadBadges(thread) {
  if (!dom.crmThreadBadges) {
    return;
  }
  if (!thread) {
    dom.crmThreadBadges.innerHTML = "";
    return;
  }
  const chips = [
    `<span class="crm-thread-badge">${escapeHtml(thread.participant_email || "-")}</span>`,
    `<span class="crm-thread-badge ${escapeHtml(crmThreadStateTone(thread))}">${escapeHtml(crmThreadStateLabel(thread))}</span>`,
  ];
  if (thread.subject) {
    chips.push(`<span class="crm-thread-badge subtle">${escapeHtml(truncateWithEllipsis(thread.subject, 64))}</span>`);
  }
  dom.crmThreadBadges.innerHTML = chips.join("");
}

function renderCrmThreadDetail() {
  if (
    !dom.crmThreadKicker ||
    !dom.crmThreadTitle ||
    !dom.crmThreadMeta ||
    !dom.crmThreadAvatar ||
    !dom.crmTimeline ||
    !dom.crmReplyForm ||
    !dom.crmReplySubject
  ) {
    return;
  }

  const thread = getCurrentCrmThread();
  if (dom.crmMobileBackBtn) {
    dom.crmMobileBackBtn.classList.toggle("hidden", !thread);
  }
  if (!thread) {
    dom.crmThreadAvatar.textContent = "--";
    dom.crmThreadKicker.textContent = "Select a thread";
    dom.crmThreadTitle.textContent = "No CRM thread selected";
    dom.crmThreadMeta.textContent = "Open a report email thread to review the conversation.";
    dom.crmReplySubject.textContent = "Select a thread to preserve subject continuity.";
    if (dom.crmThreadBadges) {
      dom.crmThreadBadges.innerHTML = "";
    }
    dom.crmTimeline.innerHTML = `
      <div class="crm-empty-state">
        <div>
          <h3>No thread selected</h3>
          <p>Choose a CRM conversation from the inbox to inspect the timeline and reply.</p>
        </div>
      </div>
    `;
    dom.crmReplyForm.classList.add("hidden");
    syncCrmComposerState();
    return;
  }

  dom.crmThreadAvatar.textContent = buildCrmMonogram(thread.company_name);
  dom.crmThreadKicker.textContent = "CEO thread";
  dom.crmThreadTitle.textContent = thread.company_name;
  dom.crmThreadMeta.textContent = `${thread.participant_email} · last activity ${formatRelativeDate(crmThreadTimestamp(thread))}`;
  dom.crmReplySubject.textContent = thread.subject;
  renderCrmThreadBadges(thread);
  dom.crmReplyForm.classList.remove("hidden");

  if (!state.crmMessages.length) {
    dom.crmTimeline.innerHTML = `
      <div class="crm-empty-state">
        <div>
          <h3>No messages persisted</h3>
          <p>This CRM thread exists, but no message history was returned yet.</p>
        </div>
      </div>
    `;
    syncCrmComposerState();
    return;
  }

  dom.crmTimeline.innerHTML = state.crmMessages
    .map((message) => {
      const timestamp = crmMessageTimestamp(message);
      const kindTone = normalizeText(message.kind);
      const isReportDelivery = kindTone === "report_delivery";
      const showStatus = shouldShowCrmMessageStatus(message);
      return `
        <div class="crm-message-shell ${escapeHtml(message.direction)}">
          <div class="crm-message-rail">
            <span class="crm-message-dot ${escapeHtml(message.direction)}"></span>
          </div>
          <article class="crm-message-card ${escapeHtml(message.direction)} ${message.status === "pending" ? "pending" : ""} ${isReportDelivery ? "report-delivery" : ""}">
            <div class="crm-message-meta">
              <div class="crm-message-eyebrow">
                <span class="crm-message-author ${escapeHtml(message.direction)}">${escapeHtml(
                  crmMessageDirectionLabel(message.direction),
                )}</span>
                <span class="crm-message-kind-chip ${escapeHtml(kindTone)}">${escapeHtml(crmMessageKindLabel(message.kind))}</span>
                <span>${escapeHtml(formatDate(timestamp))}</span>
              </div>
              ${showStatus ? `<span class="crm-message-status ${escapeHtml(message.status)}">${escapeHtml(
                crmMessageStatusLabel(message.status),
              )}</span>` : ""}
            </div>
            ${isReportDelivery ? '<p class="crm-message-callout">First audit delivery email that opened this CRM thread.</p>' : ""}
            <p class="crm-message-body">${escapeHtml(message.body)}</p>
          </article>
        </div>
      `;
    })
    .join("");
  syncCrmComposerState();
}

function renderCrmView() {
  syncCrmMobilePane();
  if (dom.crmView) {
    const detailActive = state.crmMobilePane === "detail" && Boolean(getCurrentCrmThread());
    dom.crmView.classList.toggle("crm-detail-active", detailActive);
    dom.crmView.classList.toggle("crm-list-active", !detailActive);
  }
  renderCrmBadge();
  renderCrmOverviewStats();
  renderCrmThreadList();
  renderCrmThreadDetail();
}

function getCurrentContadoresLead() {
  if (!state.currentContadoresLeadId) {
    return null;
  }
  return state.contadoresLeads.find((lead) => lead.id === state.currentContadoresLeadId) || state.currentContadoresLead || null;
}

function normalizeContadoresStage(stage) {
  return normalizeText(stage);
}

function isContadoresLeadClosed(lead) {
  return normalizeContadoresStage(lead?.stage) === "closed";
}

function formatContadoresStageLabel(stage) {
  const value = normalizeContadoresStage(stage);
  if (value === "awaiting_initial_reply") {
    return "Opener sent";
  }
  if (value === "awaiting_video_reply") {
    return "Loom sent";
  }
  if (value === "calendly_sent") {
    return "Calendly sent";
  }
  if (value === "needs_human") {
    return "Manual";
  }
  if (value === "booked") {
    return "Booked";
  }
  if (value === "closed") {
    return "Closed";
  }
  if (value === "archived") {
    return "Archived";
  }
  return String(stage || "Lead").replace(/_/g, " ").trim() || "Lead";
}

function formatContadoresStrategyLabel(value) {
  return String(value || "").replace(/_/g, " ").trim() || "Strategy";
}

function formatContadoresRate(value) {
  const rate = Number(value || 0);
  if (!Number.isFinite(rate) || rate <= 0) {
    return "0%";
  }
  return `${Math.round(rate * 100)}%`;
}

function contadoresQuickActionSuccessMessage(action) {
  if (action === "close") {
    return "Lead closed.";
  }
  if (action === "reopen") {
    return "Lead reopened.";
  }
  if (action === "mark-booked") {
    return "Lead marked as booked.";
  }
  if (action === "mark-answered") {
    return "Lead marked as answered.";
  }
  if (action === "archive") {
    return "Lead archived.";
  }
  if (action === "unarchive") {
    return "Lead unarchived.";
  }
  return `Action ${action} queued.`;
}

function renderContadoresOverviewStats() {
  const metrics = state.contadoresMetrics || {};
  document.querySelectorAll("[data-pipeline-count]").forEach((node) => {
    const key = String(node.getAttribute("data-pipeline-count") || "");
    const value = Number(metrics[key] || 0);
    node.textContent = String(value);
  });
  const activeStage = String(state.contadoresStageFilter || "");
  document.querySelectorAll("[data-stage-pill]").forEach((pill) => {
    const stage = String(pill.getAttribute("data-stage-pill") || "");
    const active = stage === activeStage;
    pill.classList.toggle("active", active);
    pill.setAttribute("aria-pressed", active ? "true" : "false");
  });
  const manualFilters = dom.contadoresManualReplyFilters;
  if (manualFilters) {
    const manualStageActive = activeStage === "needs_human";
    manualFilters.hidden = !manualStageActive;
    if (!manualStageActive && state.contadoresManualReplyFilter) {
      state.contadoresManualReplyFilter = "";
    }
  }
  const activeManualReplyStatus = String(state.contadoresManualReplyFilter || "");
  document.querySelectorAll("[data-manual-reply-pill]").forEach((pill) => {
    const status = String(pill.getAttribute("data-manual-reply-pill") || "");
    const active = status === activeManualReplyStatus;
    pill.classList.toggle("active", active);
    pill.setAttribute("aria-pressed", active ? "true" : "false");
  });
  const inlineSummary = document.getElementById("contadoresListInlineSummary");
  if (inlineSummary) {
    const total = Number(metrics.total || 0);
    const visible = Array.isArray(state.contadoresLeads) ? state.contadoresLeads.length : 0;
    inlineSummary.textContent = total
      ? `${visible} of ${total} ${total === 1 ? "lead" : "leads"}`
      : "No leads yet";
  }
}

function renderContadoresStrategyFilters() {
  if (!dom.contadoresStrategyFilters) {
    return;
  }
  const items = Array.isArray(state.contadoresStrategyStats) ? state.contadoresStrategyStats : [];
  if (!items.length) {
    dom.contadoresStrategyFilters.innerHTML = "";
    return;
  }
  const activeStep = String(state.contadoresStrategyStepFilter || "");
  const activeStrategyId = String(state.contadoresStrategyIdFilter || "");
  const buttons = [
    `<button type="button" class="ct-strategy-filter-btn${!activeStep && !activeStrategyId ? " active" : ""}" data-strategy-step="" data-strategy-id="" aria-pressed="${!activeStep && !activeStrategyId ? "true" : "false"}">All strategies</button>`,
    ...items.map((item) => {
      const step = String(item.step || "");
      const strategyId = String(item.strategy_id || "");
      const active = step === activeStep && strategyId === activeStrategyId;
      const label = `${formatContadoresStrategyLabel(step)}: ${item.strategy_label || formatContadoresStrategyLabel(strategyId)}`;
      return `<button type="button" class="ct-strategy-filter-btn${active ? " active" : ""}" data-strategy-step="${escapeHtml(step)}" data-strategy-id="${escapeHtml(strategyId)}" aria-pressed="${active ? "true" : "false"}">${escapeHtml(label)}</button>`;
    }),
  ];
  dom.contadoresStrategyFilters.innerHTML = buttons.join("");
}

function renderContadoresPlatformFilterOptions() {
  if (!dom.contadoresPlatformFilter) {
    return;
  }
  const currentValue = String(state.contadoresPlatformFilter || "");
  const platforms = [...new Set(state.contadoresLeads.map((lead) => String(lead.platform || "").trim()).filter(Boolean))].sort(
    (left, right) => left.localeCompare(right),
  );
  dom.contadoresPlatformFilter.innerHTML = `
    <option value="">All platforms</option>
    ${platforms.map((platform) => `<option value="${escapeHtml(platform)}">${escapeHtml(platform)}</option>`).join("")}
  `;
  dom.contadoresPlatformFilter.value = currentValue;
}

function renderContadoresConfigForm() {
  const config = state.contadoresConfig;
  if (!config) {
    return;
  }
  if (dom.contadoresEnabledToggle) {
    dom.contadoresEnabledToggle.checked = Boolean(config.enabled);
  }
  if (dom.contadoresLoomUrlInput) {
    dom.contadoresLoomUrlInput.value = config.loom_url || "";
  }
  if (dom.contadoresCalendlyUrlInput) {
    dom.contadoresCalendlyUrlInput.value = config.calendly_base_url || "";
  }
  if (dom.contadoresAlertEmailsInput) {
    dom.contadoresAlertEmailsInput.value = Array.isArray(config.alert_emails) ? config.alert_emails.join(", ") : "";
  }
  if (dom.contadoresSheetStatus) {
    const syncLabel = config.last_sheet_sync_status
      ? `${config.last_sheet_sync_status} · ${config.last_sheet_sync_at ? formatRelativeDate(config.last_sheet_sync_at) : "never"}`
      : "Sync idle";
    dom.contadoresSheetStatus.textContent = syncLabel;
    dom.contadoresSheetStatus.classList.toggle("has-unread", normalizeText(config.last_sheet_sync_status) === "ok");
  }
  if (dom.contadoresConfigStatusNote) {
    const parts = [
      `Sheet: ${config.last_sheet_sync_status || "idle"}`,
      `Last alert: ${config.last_alert_at ? formatRelativeDate(config.last_alert_at) : "never"}`,
      `Calendly: manual booked`,
    ];
    dom.contadoresConfigStatusNote.textContent = parts.join(" · ");
  }
}

function renderContadoresStrategyStats() {
  if (!dom.contadoresStrategyStats) {
    return;
  }
  const items = Array.isArray(state.contadoresStrategyStats) ? state.contadoresStrategyStats : [];
  if (!items.length) {
    dom.contadoresStrategyStats.innerHTML = `
      <div class="ct-strategy-head">
        <span>Strategies</span>
        <strong>No data</strong>
      </div>
    `;
    return;
  }
  dom.contadoresStrategyStats.innerHTML = `
    <div class="ct-strategy-head">
      <span>Strategies</span>
      <strong>${escapeHtml(items.length)} active</strong>
    </div>
    <div class="ct-strategy-list">
      ${items
        .map((item) => {
          const assigned = Number(item.assigned || 0);
          return `
            <article class="ct-strategy-row">
              <div>
                <strong>${escapeHtml(item.strategy_label || formatContadoresStrategyLabel(item.strategy_id))}</strong>
                <span>${escapeHtml(formatContadoresStrategyLabel(item.step))} · ${escapeHtml(String(item.weight || 0))}% weight</span>
              </div>
              <div class="ct-strategy-metrics">
                <span>${escapeHtml(String(assigned))} assigned</span>
                <span>${escapeHtml(formatContadoresRate(item.calendly_rate))} Calendly</span>
                <span>${escapeHtml(formatContadoresRate(item.booked_rate))} booked</span>
              </div>
            </article>
          `;
        })
        .join("")}
    </div>
  `;
}

function contadoresLeadStateTone(lead) {
  const stage = normalizeContadoresStage(lead?.stage);
  if (stage === "needs_human") {
    return "received";
  }
  if (stage === "booked") {
    return "sent";
  }
  if (stage === "closed") {
    return "pending";
  }
  if (stage === "archived") {
    return "pending";
  }
  return stage === "calendly_sent" ? "sent" : "pending";
}

function contadoresLeadPreviewText(lead) {
  if (isContadoresLeadClosed(lead)) {
    const previousStageLabel = formatContadoresStageLabel(lead?.stage_before_closed);
    return previousStageLabel
      ? `Closed from ${previousStageLabel.toLowerCase()}.`
      : "Lead marked as closed.";
  }
  const reason = String(lead?.last_classification_reason || "").trim();
  if (reason) {
    return truncateWithEllipsis(reason, 120);
  }
  if (lead?.booked_at) {
    return "Booked through Calendly or manually marked.";
  }
  return truncateWithEllipsis(`${lead?.platform || "-"} · ${lead?.email || lead?.phone || "-"}`, 120);
}

function syncContadoresQuickActionState(lead) {
  const hasLead = Boolean(lead);
  const closed = Boolean(hasLead && isContadoresLeadClosed(lead));
  const sendBtn = document.getElementById("ctSendMessageBtn");
  const markAnsweredBtn = document.getElementById("ctMarkAnsweredBtn");
  const deleteBtn = document.getElementById("ctDeleteLeadBtn");
  const toggleClosedBtn = document.getElementById("ctToggleClosedBtn");
  const manualReplyStatus = normalizeText(lead?.manual_reply_status);
  if (sendBtn) {
    sendBtn.disabled = !hasLead || closed;
  }
  if (markAnsweredBtn) {
    const canMarkAnswered = hasLead && !closed && manualReplyStatus === "needs_reply";
    markAnsweredBtn.hidden = !canMarkAnswered;
    markAnsweredBtn.disabled = !canMarkAnswered;
  }
  if (deleteBtn) {
    deleteBtn.disabled = !hasLead;
  }
  if (toggleClosedBtn) {
    toggleClosedBtn.disabled = !hasLead;
    toggleClosedBtn.textContent = closed ? "Reopen lead" : "Close lead";
    toggleClosedBtn.dataset.label = toggleClosedBtn.textContent;
    toggleClosedBtn.dataset.action = closed ? "reopen" : "close";
    toggleClosedBtn.classList.toggle("btn-destructive", !closed);
  }
  const pausedBanner = document.getElementById("ctPausedBanner");
  const statusBannerTitle = document.getElementById("ctStatusBannerTitle");
  const pausedReason = document.getElementById("ctPausedReason");
  const resumeBtn = document.getElementById("ctResumeBtn");
  const paused = Boolean(hasLead && lead && lead.automation_paused);
  const showStatusBanner = Boolean(closed || paused);
  if (pausedBanner) {
    pausedBanner.hidden = !showStatusBanner;
  }
  if (resumeBtn) {
    resumeBtn.hidden = closed;
    resumeBtn.disabled = !paused || closed;
  }
  if (statusBannerTitle && closed) {
    statusBannerTitle.textContent = "Lead closed";
  } else if (statusBannerTitle) {
    statusBannerTitle.textContent = "Automation paused";
  }
  if (pausedReason && hasLead && lead && closed) {
    const previousStageLabel = formatContadoresStageLabel(lead.stage_before_closed);
    const closedLabel = lead.closed_at ? formatRelativeDate(lead.closed_at) : "just now";
    pausedReason.textContent = previousStageLabel
      ? `Closed ${closedLabel}. Reopen to return to ${previousStageLabel.toLowerCase()}.`
      : `Closed ${closedLabel}. Reopen to continue with this lead.`;
  } else if (pausedReason && hasLead && lead) {
    const reason = String(lead.automation_paused_reason || "").trim();
    pausedReason.textContent = reason
      ? `Paused by operator (${reason.replace(/_/g, " ")}). Resume to let the bot continue.`
      : "The bot won't send anything until you resume.";
  }
}

function contadoresLeadTone(lead) {
  const stage = normalizeContadoresStage(lead?.stage);
  if (stage === "needs_human") {
    return "warn";
  }
  if (stage === "booked" || stage === "calendly_sent") {
    return "success";
  }
  if (stage === "closed") {
    return "muted";
  }
  if (stage === "archived") {
    return "muted";
  }
  return "accent";
}

function formatContadoresLeadStrategyTag(lead) {
  const assignments = Array.isArray(lead?.strategy_assignments) ? lead.strategy_assignments : [];
  const loomAssignment = assignments.find((assignment) => normalizeText(assignment.step) === "loom") || assignments[0];
  if (!loomAssignment) {
    return "";
  }
  return loomAssignment.strategy_label || formatContadoresStrategyLabel(loomAssignment.strategy_id);
}

function parseContadoresLeadTime(value) {
  const parsed = parseApiDateValue(value);
  return parsed instanceof Date && !Number.isNaN(parsed.getTime()) ? parsed : null;
}

function getContadoresLeadLastInteraction(lead) {
  const interactions = [
    parseContadoresLeadTime(lead?.last_inbound_at),
    parseContadoresLeadTime(lead?.last_outbound_at),
  ].filter(Boolean);
  if (interactions.length) {
    return interactions.sort((left, right) => right.getTime() - left.getTime())[0];
  }
  return parseContadoresLeadTime(lead?.created_at);
}

function getContadoresManualTurn(lead) {
  if (normalizeContadoresStage(lead?.stage) !== "needs_human") {
    return "";
  }
  const status = normalizeText(lead?.manual_reply_status);
  if (status === "needs_reply" || status === "answered") {
    return status;
  }
  const lastInboundAt = parseContadoresLeadTime(lead?.last_inbound_at);
  const lastOutboundAt = parseContadoresLeadTime(lead?.last_outbound_at);
  const handledAt = parseContadoresLeadTime(lead?.manual_reply_handled_at);
  const latestAnswerAt = [lastOutboundAt, handledAt]
    .filter(Boolean)
    .sort((left, right) => right.getTime() - left.getTime())[0] || null;
  if (lastInboundAt && (!latestAnswerAt || lastInboundAt > latestAnswerAt)) {
    return "needs_reply";
  }
  if (lastInboundAt || latestAnswerAt) {
    return "answered";
  }
  return "";
}

function formatContadoresManualTurnLabel(turn) {
  if (turn === "needs_reply") {
    return "Needs reply";
  }
  if (turn === "answered") {
    return "Answered";
  }
  return "";
}

function renderContadoresLeadList() {
  if (!dom.contadoresLeadList || !dom.contadoresListSummary) {
    return;
  }
  const leads = Array.isArray(state.contadoresLeads) ? state.contadoresLeads : [];
  dom.contadoresListSummary.textContent = leads.length
    ? `${leads.length} ${leads.length === 1 ? "lead" : "leads"}`
    : "No matches";
  if (!leads.length) {
    dom.contadoresLeadList.innerHTML = `<p class="ct-empty">No leads match the current filters.</p>`;
    return;
  }
  dom.contadoresLeadList.innerHTML = leads
    .map((lead) => {
      const active = lead.id === state.currentContadoresLeadId;
      const tone = contadoresLeadTone(lead);
      const manualTurn = getContadoresManualTurn(lead);
      const manualTurnLabel = formatContadoresManualTurnLabel(manualTurn);
      const strategyTag = formatContadoresLeadStrategyTag(lead);
      const lastInteraction = getContadoresLeadLastInteraction(lead);
      const timeLabel = lastInteraction ? formatRelativeDate(lastInteraction) : "";
      const stageLabel = formatContadoresStageLabel(lead.stage);
      const name = lead.full_name || lead.phone || "Lead";
      const phone = lead.phone || "-";
      return `
        <button
          type="button"
          class="ct-lead${active ? " active" : ""}"
          data-contadores-lead-id="${escapeHtml(lead.id)}"
        >
          <div class="ct-lead-avatar" data-tone="${escapeHtml(tone)}">${escapeHtml(buildCrmMonogram(name))}</div>
          <div class="ct-lead-body">
            <div class="ct-lead-top">
              <h4 class="ct-lead-name">${escapeHtml(name)}</h4>
              <div class="ct-lead-tags">
                <span class="ct-lead-stage" data-tone="${escapeHtml(tone)}">${escapeHtml(stageLabel)}</span>
                ${strategyTag ? `<span class="ct-lead-strategy-tag">${escapeHtml(strategyTag)}</span>` : ""}
                ${manualTurnLabel ? `<span class="ct-lead-turn ${escapeHtml(manualTurn)}">${escapeHtml(manualTurnLabel)}</span>` : ""}
              </div>
            </div>
            <div class="ct-lead-meta">
              <span class="ct-lead-meta-main">${escapeHtml(phone)}</span>
              ${timeLabel ? `<span class="ct-lead-time">${escapeHtml(timeLabel)}</span>` : ""}
            </div>
            <p class="ct-lead-preview">${escapeHtml(contadoresLeadPreviewText(lead))}</p>
          </div>
        </button>
      `;
    })
    .join("");
}

function renderContadoresMessages() {
  if (!dom.contadoresLeadTimeline) {
    return;
  }
  const messages = Array.isArray(state.contadoresMessages) ? state.contadoresMessages : [];
  if (!messages.length) {
    dom.contadoresLeadTimeline.innerHTML = `<p class="empty-note">No messages for this lead yet.</p>`;
    return;
  }
  dom.contadoresLeadTimeline.innerHTML = messages
    .map((message) => {
      const direction = message.from_me ? "outbound" : "inbound";
      const status = normalizeText(message.delivery_status);
      const metaBits = [formatDate(message.created_at)];
      if (message.sequence_step) {
        metaBits.push(message.sequence_step);
      }
      if (message.strategy_label || message.strategy_id) {
        metaBits.push(message.strategy_label || formatContadoresStrategyLabel(message.strategy_id));
      }
      if (message.media_type) {
        metaBits.push(message.media_type);
      }
      if (message.from_me && status) {
        metaBits.push(status);
      }
      return `
        <div class="crm-message-shell ${escapeHtml(direction)}">
          <div class="crm-message-rail">
            <span class="crm-message-dot ${escapeHtml(direction)}"></span>
          </div>
          <article class="crm-message-card ${escapeHtml(direction)} ${status === "undelivered" ? "pending" : ""}">
            <div class="crm-message-meta">
              <div class="crm-message-eyebrow">
                <span class="crm-message-author ${escapeHtml(direction)}">${escapeHtml(message.from_me ? "Bot / Operator" : "Lead")}</span>
                <span>${escapeHtml(metaBits.join(" · "))}</span>
              </div>
            </div>
            <p class="crm-message-body">${escapeHtml(message.text || "")}</p>
          </article>
        </div>
      `;
    })
    .join("");
}

function renderContadoresEvents() {
  if (!dom.contadoresEventTimeline) {
    return;
  }
  const events = Array.isArray(state.contadoresEvents) ? state.contadoresEvents : [];
  if (!events.length) {
    dom.contadoresEventTimeline.innerHTML = `<p class="empty-note">No automation events yet.</p>`;
    return;
  }
  dom.contadoresEventTimeline.innerHTML = events
    .map((event) => `
      <article class="ct-event-card">
        <div class="ct-event-head">
          <strong>${escapeHtml(event.event_type || "event")}</strong>
          <time>${escapeHtml(formatDate(event.created_at))}</time>
        </div>
        <p>${escapeHtml(event.summary || "")}</p>
      </article>
    `)
    .join("");
}

function renderContadoresLeadStrategies() {
  if (!dom.contadoresLeadStrategies) {
    return;
  }
  const messages = Array.isArray(state.contadoresMessages) ? state.contadoresMessages : [];
  const strategyMessages = messages.filter((message) => message.from_me && message.strategy_id);
  if (!strategyMessages.length) {
    dom.contadoresLeadStrategies.innerHTML = `<p class="empty-note">No strategy assignment for this lead yet.</p>`;
    return;
  }

  const groups = new Map();
  strategyMessages.forEach((message) => {
    const key = String(message.strategy_assignment_id || `${message.strategy_step}:${message.strategy_id}`);
    const current = groups.get(key) || {
      step: message.strategy_step || "",
      strategyId: message.strategy_id || "",
      strategyLabel: message.strategy_label || formatContadoresStrategyLabel(message.strategy_id),
      messages: [],
    };
    current.messages.push(message);
    groups.set(key, current);
  });

  dom.contadoresLeadStrategies.innerHTML = [...groups.values()]
    .map((group) => {
      const delivered = group.messages.filter((message) => normalizeText(message.delivery_status) === "delivered").length;
      const sent = group.messages.filter((message) => ["sent", "delivered"].includes(normalizeText(message.delivery_status))).length;
      const mediaTypes = [...new Set(group.messages.map((message) => normalizeText(message.media_type)).filter(Boolean))];
      return `
        <article class="ct-lead-strategy-card">
          <div class="ct-lead-strategy-head">
            <div>
              <strong>${escapeHtml(group.strategyLabel)}</strong>
              <span>${escapeHtml(formatContadoresStrategyLabel(group.step))}</span>
            </div>
            <span class="ct-strategy-chip">${escapeHtml(sent)}/${escapeHtml(group.messages.length)} sent</span>
          </div>
          <div class="ct-lead-strategy-meta">
            <span>${escapeHtml(delivered)} delivered</span>
            ${mediaTypes.map((mediaType) => `<span>${escapeHtml(mediaType)}</span>`).join("")}
          </div>
          <ul>
            ${group.messages
              .map((message) => `
                <li>
                  <span>${escapeHtml(message.sequence_step || "message")}</span>
                  <strong>${escapeHtml(normalizeText(message.delivery_status) || "pending")}</strong>
                </li>
              `)
              .join("")}
          </ul>
        </article>
      `;
    })
    .join("");
}

function renderContadoresDetail() {
  const lead = getCurrentContadoresLead();
  if (!lead) {
    if (dom.contadoresLeadStage) {
      dom.contadoresLeadStage.textContent = "Select a lead";
    }
    if (dom.contadoresLeadTitle) {
      dom.contadoresLeadTitle.textContent = "No lead selected";
    }
    if (dom.contadoresLeadMeta) {
      dom.contadoresLeadMeta.textContent = "Open a lead to inspect messages, automation events, and manual controls.";
    }
    if (dom.contadoresLeadTimeline) {
      dom.contadoresLeadTimeline.innerHTML = `<p class="empty-note">Select a lead from the list.</p>`;
    }
    if (dom.contadoresEventTimeline) {
      dom.contadoresEventTimeline.innerHTML = `<p class="empty-note">Events will appear when you select a lead.</p>`;
    }
    if (dom.contadoresLeadStrategies) {
      dom.contadoresLeadStrategies.innerHTML = `<p class="empty-note">Strategies will appear when you select a lead.</p>`;
    }
    syncContadoresQuickActionState(null);
    return;
  }
  if (dom.contadoresLeadStage) {
    dom.contadoresLeadStage.textContent = formatContadoresStageLabel(lead.stage);
  }
  if (dom.contadoresLeadTitle) {
    dom.contadoresLeadTitle.textContent = lead.full_name || lead.phone || "Lead";
  }
  if (dom.contadoresLeadMeta) {
    dom.contadoresLeadMeta.textContent = [
      lead.phone || "-",
      lead.email || "-",
      lead.platform || "-",
      lead.external_lead_id || "-",
    ].join(" · ");
  }
  syncContadoresQuickActionState(lead);
  renderContadoresMessages();
  renderContadoresEvents();
  renderContadoresLeadStrategies();
}

function renderContadoresView() {
  renderContadoresConfigForm();
  renderContadoresStrategyStats();
  renderContadoresOverviewStats();
  renderContadoresStrategyFilters();
  renderContadoresPlatformFilterOptions();
  renderContadoresLeadList();
  renderContadoresDetail();
}

function threadTimestamp(thread) {
  return toTimestamp(
    thread?.latest_message?.timestamp || thread?.latest_message?.created_at || thread?.updated_at || thread?.created_at,
  );
}

function sortThreads(threads) {
  return [...threads].sort((left, right) => {
    const timeDelta = threadTimestamp(right) - threadTimestamp(left);
    if (timeDelta !== 0) {
      return timeDelta;
    }
    const leftTitle = normalizeText(left.contact_name || left.contact_value);
    const rightTitle = normalizeText(right.contact_name || right.contact_value);
    return leftTitle.localeCompare(rightTitle);
  });
}

function showToast(message, isError = false) {
  if (!dom.toast) {
    return;
  }
  if (state.toastTimer) {
    window.clearTimeout(state.toastTimer);
  }
  dom.toast.className = `toast${isError ? " error" : ""}`;
  dom.toast.textContent = message;
  dom.toast.classList.remove("hidden");
  state.toastTimer = window.setTimeout(() => {
    dom.toast.classList.add("hidden");
  }, 3500);
}

function showLoading(message) {
  hideLoading();
  const overlay = document.createElement("div");
  overlay.className = "loading-overlay";
  overlay.innerHTML = `
    <div class="loading-card">
      <div class="loading-spinner"></div>
      <p>${escapeHtml(message || "Working...")}</p>
    </div>
  `;
  document.body.appendChild(overlay);
  state.loadingNode = overlay;
}

function hideLoading() {
  if (state.loadingNode) {
    state.loadingNode.remove();
    state.loadingNode = null;
  }
}

function setView(view) {
  state.currentView = view === "project" ? "project" : "home";
  const showCrm = currentSectionIsCrm();
  const showContadores = currentSectionIsContadores();
  const showProject = !showCrm && !showContadores && state.currentView === "project";
  const showHome = !showCrm && !showContadores && state.currentView === "home";
  dom.homeView.classList.toggle("hidden", !showHome);
  dom.projectView.classList.toggle("hidden", !showProject);
  dom.crmView.classList.toggle("hidden", !showCrm);
  dom.contadoresView.classList.toggle("hidden", !showContadores);
  const appShell = document.querySelector(".app-shell");
  if (appShell) {
    appShell.classList.toggle("contadores-active", showContadores);
  }
  if (!showContadores) {
    closeContadoresDrawer();
    closeContadoresSendModal();
  }
  syncWorkspaceNav();
  renderSidebarFocus();
}

function closeContadoresDrawer() {
  const drawer = document.getElementById("contadoresDrawer");
  if (drawer) {
    drawer.classList.remove("open");
  }
  document.body.classList.remove("contadores-drawer-open");
}

function openContadoresDrawer() {
  const drawer = document.getElementById("contadoresDrawer");
  if (!drawer) {
    return;
  }
  drawer.classList.add("open");
  document.body.classList.add("contadores-drawer-open");
}

function syncWorkspaceNav() {
  const auditsActive = !currentSectionIsCrm() && !currentSectionIsContadores();
  const contadoresActive = currentSectionIsContadores();
  const crmActive = currentSectionIsCrm();
  dom.sectionAuditsBtn?.classList.toggle("active", auditsActive);
  dom.sectionAuditsBtn?.setAttribute("aria-pressed", auditsActive ? "true" : "false");
  dom.sectionContadoresBtn?.classList.toggle("active", contadoresActive);
  dom.sectionContadoresBtn?.setAttribute("aria-pressed", contadoresActive ? "true" : "false");
  dom.sectionCrmBtn?.classList.toggle("active", crmActive);
  dom.sectionCrmBtn?.setAttribute("aria-pressed", crmActive ? "true" : "false");
}

function getCurrentThread() {
  if (!state.currentProject || !state.currentThreadId) {
    return null;
  }
  return state.currentProject.threads.find((thread) => thread.id === state.currentThreadId) || null;
}

function isWhatsAppThread(thread) {
  if (!thread) {
    return false;
  }
  const contactType = normalizeText(thread.contact_type || thread.type);
  return contactType === "whatsapp" || Boolean(thread.wa_link);
}

function isEmailThread(thread) {
  if (!thread) {
    return false;
  }
  const contactType = normalizeText(thread.contact_type || thread.type);
  return contactType === "email";
}

function emailThreadLinkPanelDismissKey(thread) {
  if (!thread || !thread.id || !state.currentProjectId) {
    return null;
  }
  return `${state.currentProjectId}:${thread.id}`;
}

function isEmailThreadLinkPanelDismissed(thread) {
  const key = emailThreadLinkPanelDismissKey(thread);
  if (!key) {
    return false;
  }
  return Boolean(state.dismissedEmailThreadLinkPanels[key]);
}

function dismissEmailThreadLinkPanel(thread) {
  const key = emailThreadLinkPanelDismissKey(thread);
  if (!key) {
    return;
  }
  state.dismissedEmailThreadLinkPanels[key] = true;
}

function isArchivedThread(thread) {
  if (!thread) {
    return false;
  }
  if (typeof thread.archived === "boolean") {
    return thread.archived;
  }
  return normalizeText(thread.status) === "archived";
}

function normalizeDeliveryStatus(value) {
  const normalized = normalizeText(value);
  if (normalized === "sent") {
    return "sent";
  }
  if (normalized === "delivered") {
    return "delivered";
  }
  if (normalized === "failed") {
    return "failed";
  }
  return "undelivered";
}

function isUndeliveredOutboundMessage(message) {
  if (!message || !message.from_me) {
    return false;
  }
  return normalizeDeliveryStatus(message.delivery_status) === "undelivered";
}

function countUndeliveredOutboundMessages(messages) {
  if (!Array.isArray(messages) || !messages.length) {
    return 0;
  }
  return messages.filter((message) => isUndeliveredOutboundMessage(message)).length;
}

function threadNeedsDelivery(thread) {
  if (!thread) {
    return false;
  }
  if (typeof thread.pending_delivery === "boolean") {
    return thread.pending_delivery;
  }
  return Number(thread.pending_delivery_count || 0) > 0;
}

function projectPendingDeliveryCount(project) {
  return Number(project?.pending_delivery_contacts || 0);
}

function projectConversationAutomationEnabled(project) {
  return Boolean(project?.conversation_automation_enabled);
}

function projectCeoDeliveryEnabled(project) {
  return Boolean(project?.ceo_delivery_enabled);
}

function clearProjectCeoEmailEditing() {
  state.editingProjectCeoEmail = false;
  state.editingProjectCeoEmailValue = "";
}

function clearProjectReportScheduleEditing() {
  state.editingProjectReportSchedule = false;
  state.editingProjectReportWindowHoursValue = "";
  state.editingProjectReportWindowMinutesValue = "";
  state.editingProjectScheduledSendValue = "";
}

function setProjectConversationAutomationState(projectId, enabled, updatedAt = null) {
  const nextEnabled = Boolean(enabled);
  state.projects = sortProjects(
    state.projects.map((project) => {
      if (project.id !== projectId) {
        return project;
      }
      return {
        ...project,
        conversation_automation_enabled: nextEnabled,
        updated_at: updatedAt || project.updated_at,
      };
    }),
  );

  if (state.currentProject && state.currentProject.id === projectId) {
    state.currentProject.conversation_automation_enabled = nextEnabled;
    if (updatedAt) {
      state.currentProject.updated_at = updatedAt;
    }
  }
}

function setProjectCeoDeliveryState(projectId, enabled, updatedAt = null) {
  const nextEnabled = Boolean(enabled);
  state.projects = sortProjects(
    state.projects.map((project) => {
      if (project.id !== projectId) {
        return project;
      }
      return {
        ...project,
        ceo_delivery_enabled: nextEnabled,
        updated_at: updatedAt || project.updated_at,
      };
    }),
  );

  if (state.currentProject && state.currentProject.id === projectId) {
    state.currentProject.ceo_delivery_enabled = nextEnabled;
    if (updatedAt) {
      state.currentProject.updated_at = updatedAt;
    }
  }
}

function setProjectCeoEmailState(projectId, ceoEmail, updatedAt = null) {
  const nextEmail = String(ceoEmail || "").trim() || null;
  state.projects = sortProjects(
    state.projects.map((project) => {
      if (project.id !== projectId) {
        return project;
      }
      return {
        ...project,
        ceo_email: nextEmail,
        has_ceo_email: Boolean(nextEmail),
        updated_at: updatedAt || project.updated_at,
      };
    }),
  );

  if (state.currentProject && state.currentProject.id === projectId) {
    state.currentProject.ceo_email = nextEmail;
    state.currentProject.has_ceo_email = Boolean(nextEmail);
    if (updatedAt) {
      state.currentProject.updated_at = updatedAt;
    }
  }
}

function setProjectReportScheduleState(projectId, reportWindowMinutes, scheduledSendAt = null, updatedAt = null) {
  const nextMinutes = normalizeReportWindowMinutesValue(reportWindowMinutes);
  const nextHours = legacyReportWindowHoursFromMinutes(nextMinutes);
  state.projects = sortProjects(
    state.projects.map((project) => {
      if (project.id !== projectId) {
        return project;
      }
      const nextScheduledSendAt =
        scheduledSendAt
        || computeProjectReportDeadline({
          created_at: project.created_at,
          report_window_minutes: nextMinutes,
        })?.toISOString()
        || project.scheduled_send_at
        || null;
      return {
        ...project,
        report_window_hours: nextHours,
        report_window_minutes: nextMinutes,
        scheduled_send_at: nextScheduledSendAt,
        updated_at: updatedAt || project.updated_at,
      };
    }),
  );

  if (state.currentProject && state.currentProject.id === projectId) {
    state.currentProject.report_window_hours = nextHours;
    state.currentProject.report_window_minutes = nextMinutes;
    state.currentProject.scheduled_send_at =
      scheduledSendAt
      || computeProjectReportDeadline({
        created_at: state.currentProject.created_at,
        report_window_minutes: nextMinutes,
      })?.toISOString()
      || state.currentProject.scheduled_send_at
      || null;
    if (updatedAt) {
      state.currentProject.updated_at = updatedAt;
    }
  }
}

function markProjectScanStarted(projectId, taskId, updatedAt = null) {
  if (!projectId || !taskId) {
    return;
  }
  const nextUpdatedAt = updatedAt || new Date().toISOString();
  state.pendingCompanyTasks[projectId] = taskId;
  state.projects = sortProjects(
    state.projects.map((project) => {
      if (project.id !== projectId) {
        return project;
      }
      return {
        ...project,
        processing: true,
        status: "initializing",
        can_rescan: false,
        updated_at: nextUpdatedAt,
      };
    }),
  );

  if (state.currentProject && state.currentProject.id === projectId) {
    state.currentProject.processing = true;
    state.currentProject.status = "initializing";
    state.currentProject.can_rescan = false;
    state.currentProject.updated_at = nextUpdatedAt;
  }
}

function syncProjectAutomationControls() {
  if (!dom.projectAiAutomationToggle || !dom.projectAiAutomationHint) {
    return;
  }
  if (!dom.projectCeoDeliveryToggle || !dom.projectCeoDeliveryHint) {
    return;
  }
  if (!state.currentProject) {
    dom.projectAiAutomationToggle.checked = false;
    dom.projectAiAutomationToggle.disabled = true;
    dom.projectAiAutomationHint.textContent = "Open a company to configure.";
    dom.projectCeoDeliveryToggle.checked = false;
    dom.projectCeoDeliveryToggle.disabled = true;
    dom.projectCeoDeliveryHint.textContent = "Open a company to configure.";
    return;
  }
  const conversationEnabled = projectConversationAutomationEnabled(state.currentProject);
  const ceoDeliveryEnabled = projectCeoDeliveryEnabled(state.currentProject);
  const isSaving = state.pendingAiAutomationCompanyId === state.currentProject.id;
  const isSavingCeo = state.pendingCeoDeliveryCompanyId === state.currentProject.id;
  dom.projectAiAutomationToggle.checked = conversationEnabled;
  dom.projectAiAutomationToggle.disabled = isSaving;
  dom.projectAiAutomationHint.textContent = isSaving
    ? "Saving..."
    : conversationEnabled
      ? "Authorized for bot."
      : "Blocked for bot.";
  dom.projectCeoDeliveryToggle.checked = ceoDeliveryEnabled;
  dom.projectCeoDeliveryToggle.disabled = isSavingCeo;
  dom.projectCeoDeliveryHint.textContent = isSavingCeo
    ? "Saving..."
    : ceoDeliveryEnabled
      ? "Audit PDF delivery enabled."
      : "Audit PDF delivery blocked.";
}

function computePendingDeliveryCountFromThreads(threads) {
  if (!Array.isArray(threads) || !threads.length) {
    return 0;
  }
  return threads.reduce((count, thread) => count + (threadNeedsDelivery(thread) ? 1 : 0), 0);
}

function syncCurrentProjectPendingDeliveryState() {
  if (!state.currentProject || !state.currentProjectId) {
    return;
  }
  const pendingCount = computePendingDeliveryCountFromThreads(state.currentProject.threads);
  state.currentProject.pending_delivery_contacts = pendingCount;
  state.projects = state.projects.map((project) => {
    if (project.id !== state.currentProjectId) {
      return project;
    }
    return {
      ...project,
      pending_delivery_contacts: pendingCount,
    };
  });
}

function getLatestOutboundMessage() {
  for (let index = state.threadMessages.length - 1; index >= 0; index -= 1) {
    const message = state.threadMessages[index];
    if (message.from_me) {
      return message;
    }
  }
  return null;
}

function extractWhatsAppDigits(contactValue) {
  return String(contactValue || "").replace(/\D/g, "");
}

function latestThreadMessageText(thread) {
  for (let index = state.threadMessages.length - 1; index >= 0; index -= 1) {
    const text = String(state.threadMessages[index]?.text || "").trim();
    if (text) {
      return text;
    }
  }
  const fallback = String(thread?.latest_message?.text || "").trim();
  return fallback || null;
}

function buildWhatsAppLinkWithLatestMessage(thread) {
  if (!thread) {
    return null;
  }
  const baseLink = String(thread.wa_link || "").trim();
  let waUrl = null;
  try {
    if (baseLink) {
      waUrl = new URL(baseLink);
    } else {
      const digits = extractWhatsAppDigits(thread.contact_value);
      if (!digits) {
        return null;
      }
      waUrl = new URL(`https://wa.me/${digits}`);
    }
  } catch {
    const digits = extractWhatsAppDigits(thread.contact_value);
    if (!digits) {
      return null;
    }
    waUrl = new URL(`https://wa.me/${digits}`);
  }
  const latestText = latestThreadMessageText(thread);
  if (latestText) {
    waUrl.searchParams.set("text", latestText);
  }
  return waUrl.toString();
}

function getMessageId(message) {
  const id = Number(message?.id);
  if (!Number.isInteger(id) || id <= 0) {
    return null;
  }
  return id;
}

function getMessageById(messageId) {
  return state.threadMessages.find((message) => getMessageId(message) === messageId) || null;
}

function clearMessageEditing() {
  state.editingMessageId = null;
  state.editingMessageText = "";
}

async function copyTextToClipboard(text) {
  await navigator.clipboard.writeText(String(text || ""));
}

function setTranscriptSummaryCopyState(copyText) {
  if (!dom.transcriptSummary) {
    return;
  }
  const subjectText = String(copyText || "").trim();
  if (subjectText) {
    dom.transcriptSummary.dataset.copyText = subjectText;
    dom.transcriptSummary.dataset.copyLabel = "Copy subject";
    dom.transcriptSummary.classList.add("chat-summary-copyable");
    dom.transcriptSummary.classList.remove("copied");
    dom.transcriptSummary.setAttribute("role", "button");
    dom.transcriptSummary.setAttribute("tabindex", "0");
    dom.transcriptSummary.setAttribute("title", "Click to copy subject");
    dom.transcriptSummary.setAttribute("aria-label", "Copy email subject");
    return;
  }
  delete dom.transcriptSummary.dataset.copyText;
  delete dom.transcriptSummary.dataset.copyLabel;
  dom.transcriptSummary.classList.remove("chat-summary-copyable");
  dom.transcriptSummary.classList.remove("copied");
  dom.transcriptSummary.removeAttribute("role");
  dom.transcriptSummary.removeAttribute("tabindex");
  dom.transcriptSummary.removeAttribute("title");
  dom.transcriptSummary.removeAttribute("aria-label");
}

async function handleTranscriptSummaryCopy(event) {
  if (!dom.transcriptSummary) {
    return;
  }
  if (event?.type === "keydown") {
    const isActivationKey = event.key === "Enter" || event.key === " ";
    if (!isActivationKey) {
      return;
    }
    event.preventDefault();
  }
  const text = String(dom.transcriptSummary.dataset.copyText || "").trim();
  if (!text) {
    return;
  }
  try {
    await copyTextToClipboard(text);
    showCopiedEffect(dom.transcriptSummary);
    showToast("Subject copied.");
  } catch {
    showToast("Clipboard copy failed.", true);
  }
}

function showCopiedEffect(node) {
  if (!node) {
    return;
  }
  node.classList.remove("copied");
  void node.offsetWidth;
  node.classList.add("copied");
  window.setTimeout(() => {
    node.classList.remove("copied");
  }, 900);
}

function syncThreadLatestFromMessages() {
  const thread = getCurrentThread();
  if (!thread || !state.threadMessages.length) {
    return;
  }
  const latest = state.threadMessages[state.threadMessages.length - 1];
  thread.latest_message = {
    ...(thread.latest_message || {}),
    ...latest,
  };
  if (latest.timestamp) {
    thread.updated_at = latest.timestamp;
  }
  const pendingDeliveryCount = countUndeliveredOutboundMessages(state.threadMessages);
  thread.pending_delivery_count = pendingDeliveryCount;
  thread.pending_delivery = pendingDeliveryCount > 0;
  syncCurrentProjectPendingDeliveryState();
}

function hasPendingInboundTask(threadId) {
  return Boolean(threadId && state.pendingInboundTasks[threadId]);
}

function appendLocalInboundMessage(threadId, text) {
  if (!threadId || !text) {
    return;
  }

  const nowIso = new Date().toISOString();
  if (state.currentProject) {
    const thread = state.currentProject.threads.find((item) => item.id === threadId);
    if (thread) {
      thread.latest_message = {
        text,
        timestamp: nowIso,
      };
      thread.updated_at = nowIso;
    }
  }

  if (state.currentThreadId === threadId) {
    state.threadMessages = [
      ...state.threadMessages,
      {
        from_me: false,
        text,
        timestamp: nowIso,
      },
    ];
  }
}

function syncInboundComposerState() {
  if (!dom.sendInboundBtn || !dom.inboundInput) {
    return;
  }
  if (projectIsProcessing(state.currentProject)) {
    setBusy(dom.sendInboundBtn, true, "Processing Scan", "Register Inbound + Generate Reply");
    dom.inboundInput.disabled = true;
    dom.inboundInput.placeholder = "Company scan still processing.";
    return;
  }
  const currentThreadId = state.currentThreadId;
  const currentThread = getCurrentThread();
  const isArchived = isArchivedThread(currentThread);
  const isBusy = hasPendingInboundTask(currentThreadId);
  const isDone = Boolean(currentThread?.conversation_done);
  if (isArchived) {
    setBusy(dom.sendInboundBtn, true, "Archived Contact", "Register Inbound + Generate Reply");
    dom.inboundInput.disabled = true;
    dom.inboundInput.placeholder = "Archived contacts can't receive new messages.";
    return;
  }
  if (isDone) {
    setBusy(dom.sendInboundBtn, isBusy, "Saving...", "Register Inbound Only");
    dom.inboundInput.disabled = isBusy;
    dom.inboundInput.placeholder = "Conversation closed. New inbound will be saved, but no auto-reply will be generated.";
    return;
  }
  setBusy(dom.sendInboundBtn, isBusy, "AI writing...", "Register Inbound + Generate Reply");
  dom.inboundInput.disabled = isBusy;
  dom.inboundInput.placeholder = "Paste the contact's latest message here...";
}

async function apiFetch(path, options = {}) {
  const method = options.method || "GET";
  const headers = {};
  const isFormData = options.body instanceof FormData;
  if (options.body !== undefined && !isFormData) {
    headers["Content-Type"] = "application/json";
  }

  const response = await fetchWithAuth(`${state.baseUrl}${path}`, {
    method,
    headers,
    body:
      options.body === undefined
        ? undefined
        : isFormData
          ? options.body
          : JSON.stringify(options.body),
  });

  const raw = await response.text();
  let parsed = null;
  if (raw) {
    try {
      parsed = JSON.parse(raw);
    } catch {
      parsed = raw;
    }
  }

  if (!response.ok) {
    let detail = `HTTP ${response.status}`;
    if (parsed && typeof parsed === "object" && parsed.detail) {
      detail = String(parsed.detail);
    } else if (typeof parsed === "string" && parsed.trim()) {
      detail = parsed.trim();
    }
    throw new Error(detail);
  }

  return parsed;
}

function setBusy(button, isBusy, busyLabel, idleLabel) {
  if (!button) {
    return;
  }
  button.disabled = isBusy;
  button.textContent = isBusy ? busyLabel : idleLabel;
}

function hasGeneratedAudit() {
  return Boolean(
    state.currentProjectId &&
      (Boolean(state.currentProject?.has_report_pdf_model) || Boolean(state.latestReport?.pdf_model)),
  );
}

function syncReportActions() {
  const processing = projectIsProcessing(state.currentProject);
  if (dom.generateFullReportBtn) {
    dom.generateFullReportBtn.disabled = processing || !state.currentProjectId;
  }
  if (dom.viewAuditBtn) {
    dom.viewAuditBtn.classList.remove("hidden");
    dom.viewAuditBtn.disabled = !hasGeneratedAudit();
  }
}

function syncArchivedContactsToggleButton() {
  if (!dom.toggleArchivedThreadsBtn) {
    return;
  }
  if (!state.currentProjectId) {
    dom.toggleArchivedThreadsBtn.classList.add("hidden");
    return;
  }
  dom.toggleArchivedThreadsBtn.classList.remove("hidden");
  dom.toggleArchivedThreadsBtn.disabled = projectIsProcessing(state.currentProject);
  dom.toggleArchivedThreadsBtn.textContent = state.showArchivedThreads ? "View Active" : "View Archived";
}

function extractHttpErrorMessage(response, rawPayload) {
  let detail = `HTTP ${response.status}`;
  if (rawPayload) {
    try {
      const parsed = JSON.parse(rawPayload);
      if (parsed && typeof parsed === "object" && parsed.detail) {
        detail = String(parsed.detail);
      } else if (typeof parsed === "string" && parsed.trim()) {
        detail = parsed.trim();
      }
    } catch {
      if (rawPayload.trim()) {
        detail = rawPayload.trim();
      }
    }
  }
  return detail;
}

function parseDownloadFilename(contentDisposition, fallbackName) {
  const header = String(contentDisposition || "");
  const utf8Match = header.match(/filename\*=UTF-8''([^;]+)/i);
  if (utf8Match && utf8Match[1]) {
    try {
      return decodeURIComponent(utf8Match[1].trim());
    } catch {
      return utf8Match[1].trim();
    }
  }
  const basicMatch = header.match(/filename="?([^\";]+)"?/i);
  if (basicMatch && basicMatch[1]) {
    return basicMatch[1].trim();
  }
  return fallbackName;
}

async function downloadAuditPdf(projectId) {
  const response = await fetchWithAuth(`${state.baseUrl}/api/companies/${projectId}/audit-delivery/pdf`);
  if (!response.ok) {
    const rawPayload = await response.text();
    throw new Error(extractHttpErrorMessage(response, rawPayload));
  }

  const blob = await response.blob();
  const filename = parseDownloadFilename(
    response.headers.get("Content-Disposition"),
    `audit-${projectId}.pdf`,
  );
  const blobUrl = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = blobUrl;
  link.download = filename;
  document.body.appendChild(link);
  link.click();
  link.remove();
  window.setTimeout(() => URL.revokeObjectURL(blobUrl), 60_000);
}

async function handleViewAudit() {
  const projectId = state.currentProjectId;
  if (!projectId) {
    return;
  }
  if (!hasGeneratedAudit()) {
    showToast("No generated audit found yet.", true);
    return;
  }

  setBusy(dom.viewAuditBtn, true, "Downloading...", "View Audit");
  try {
    await downloadAuditPdf(projectId);
    showToast("Audit download started.");
  } catch (error) {
    showToast(error.message || "Failed downloading audit", true);
  } finally {
    setBusy(dom.viewAuditBtn, false, "Downloading...", "View Audit");
    syncReportActions();
  }
}

function renderProjectCeoEmailPanel() {
  if (
    !dom.projectCeoEmailPanel ||
    !dom.projectCeoEmailEditBtn ||
    !dom.projectCeoEmailReadRow ||
    !dom.projectCeoEmailCopyBtn ||
    !dom.projectCeoEmailEditor ||
    !dom.projectCeoEmailInput ||
    !dom.projectCeoEmailSaveBtn ||
    !dom.projectCeoEmailCancelBtn ||
    !dom.projectCeoEmailHint
  ) {
    return;
  }

  const project = state.currentProject;
  if (!project) {
    dom.projectCeoEmailPanel.classList.add("hidden");
    dom.projectCeoEmailEditBtn.classList.remove("hidden");
    dom.projectCeoEmailEditBtn.disabled = true;
    dom.projectCeoEmailCopyBtn.disabled = true;
    dom.projectCeoEmailCopyBtn.textContent = "No CEO email configured";
    dom.projectCeoEmailCopyBtn.classList.add("is-empty");
    dom.projectCeoEmailReadRow.classList.remove("hidden");
    dom.projectCeoEmailEditor.classList.add("hidden");
    dom.projectCeoEmailHint.textContent =
      "Click the email to copy it or edit the recipient for the next CEO audit delivery.";
    return;
  }

  const ceoEmail = String(project.ceo_email || "").trim();
  const isEditing = state.editingProjectCeoEmail;
  const isSaving = state.pendingCeoEmailCompanyId === project.id;

  dom.projectCeoEmailPanel.classList.remove("hidden");
  dom.projectCeoEmailEditBtn.classList.toggle("hidden", isEditing);
  dom.projectCeoEmailEditBtn.disabled = isSaving || isEditing;
  dom.projectCeoEmailEditBtn.textContent = isSaving ? "Saving..." : "Edit";
  dom.projectCeoEmailCopyBtn.textContent = ceoEmail || "No CEO email configured";
  dom.projectCeoEmailCopyBtn.disabled = !ceoEmail || isSaving;
  dom.projectCeoEmailCopyBtn.classList.toggle("is-empty", !ceoEmail);
  dom.projectCeoEmailCopyBtn.setAttribute(
    "title",
    ceoEmail || "No CEO email configured",
  );

  if (isEditing) {
    dom.projectCeoEmailReadRow.classList.add("hidden");
    dom.projectCeoEmailEditor.classList.remove("hidden");
    if (dom.projectCeoEmailInput.value !== state.editingProjectCeoEmailValue) {
      dom.projectCeoEmailInput.value = state.editingProjectCeoEmailValue;
    }
    dom.projectCeoEmailInput.disabled = isSaving;
    dom.projectCeoEmailSaveBtn.disabled = isSaving;
    dom.projectCeoEmailCancelBtn.disabled = isSaving;
    dom.projectCeoEmailHint.textContent = isSaving
      ? "Saving CEO delivery email..."
      : "Change the email used when the audit PDF is delivered.";
    if (!isSaving && document.activeElement !== dom.projectCeoEmailInput) {
      window.requestAnimationFrame(() => {
        dom.projectCeoEmailInput?.focus();
        dom.projectCeoEmailInput?.select();
      });
    }
    return;
  }

  dom.projectCeoEmailReadRow.classList.remove("hidden");
  dom.projectCeoEmailEditor.classList.add("hidden");
  dom.projectCeoEmailInput.disabled = false;
  dom.projectCeoEmailSaveBtn.disabled = false;
  dom.projectCeoEmailCancelBtn.disabled = false;
  dom.projectCeoEmailHint.textContent = ceoEmail
    ? "Click the email to copy it. Edit changes the recipient for the next CEO audit delivery."
    : "No CEO email configured yet. Edit to set the recipient for the next CEO audit delivery.";
}

function getProjectReportScheduleMinimumDate(project) {
  const createdTimestamp = truncateTimestampToMinute(toTimestamp(project?.created_at));
  if (!createdTimestamp) {
    return null;
  }
  return new Date(createdTimestamp + MINUTE_MS);
}

function readProjectReportWindowMinutesInput() {
  const parsedHours = Number.parseInt(String(dom.projectReportWindowHoursInput?.value || "0").trim(), 10);
  const parsedMinutes = Number.parseInt(String(dom.projectReportWindowMinutesInput?.value || "0").trim(), 10);
  const hours = Number.isFinite(parsedHours) && parsedHours >= 0 ? parsedHours : NaN;
  const minutes = Number.isFinite(parsedMinutes) && parsedMinutes >= 0 ? parsedMinutes : NaN;
  if (!Number.isFinite(hours) || !Number.isFinite(minutes)) {
    return null;
  }
  return (hours * 60) + minutes;
}

function syncProjectReportScheduleEditorFromWindow() {
  if (
    !state.currentProject ||
    !dom.projectReportWindowHoursInput ||
    !dom.projectReportWindowMinutesInput ||
    !dom.projectScheduledSendInput
  ) {
    return;
  }
  const totalMinutes = readProjectReportWindowMinutesInput();
  if (!Number.isFinite(totalMinutes) || totalMinutes < 1) {
    return;
  }
  const normalizedMinutes = Math.max(1, totalMinutes);
  const scheduledSendAt = computeProjectReportDeadline(state.currentProject, normalizedMinutes);
  if (!scheduledSendAt) {
    return;
  }
  const parts = splitReportWindowMinutes(normalizedMinutes);
  state.editingProjectReportWindowHoursValue = String(parts.hours);
  state.editingProjectReportWindowMinutesValue = String(parts.minutes);
  state.editingProjectScheduledSendValue = formatGmtMinusThreeDateTimeLocalValue(scheduledSendAt);
  dom.projectReportWindowHoursInput.value = state.editingProjectReportWindowHoursValue;
  dom.projectReportWindowMinutesInput.value = state.editingProjectReportWindowMinutesValue;
  dom.projectScheduledSendInput.value = state.editingProjectScheduledSendValue;
}

function syncProjectReportScheduleEditorFromScheduledSend() {
  if (
    !state.currentProject ||
    !dom.projectScheduledSendInput ||
    !dom.projectReportWindowHoursInput ||
    !dom.projectReportWindowMinutesInput
  ) {
    return;
  }
  const scheduledSendAt = parseGmtMinusThreeDateTimeLocalValue(dom.projectScheduledSendInput.value);
  const createdTimestamp = truncateTimestampToMinute(toTimestamp(state.currentProject.created_at));
  if (!scheduledSendAt || !createdTimestamp) {
    return;
  }
  const deltaMs = scheduledSendAt.getTime() - createdTimestamp;
  if (deltaMs < MINUTE_MS) {
    return;
  }
  const resolvedMinutes = Math.round(deltaMs / MINUTE_MS);
  if (Math.abs(deltaMs - resolvedMinutes * MINUTE_MS) > 1_000) {
    return;
  }
  const parts = splitReportWindowMinutes(Math.max(1, resolvedMinutes));
  state.editingProjectScheduledSendValue = dom.projectScheduledSendInput.value;
  state.editingProjectReportWindowHoursValue = String(parts.hours);
  state.editingProjectReportWindowMinutesValue = String(parts.minutes);
  dom.projectReportWindowHoursInput.value = state.editingProjectReportWindowHoursValue;
  dom.projectReportWindowMinutesInput.value = state.editingProjectReportWindowMinutesValue;
}

function renderProjectReportSchedulePanel() {
  if (
    !dom.projectReportSchedulePanel ||
    !dom.projectReportScheduleEditBtn ||
    !dom.projectDeadlineSummary ||
    !dom.projectReportScheduleEditor ||
    !dom.projectReportWindowHoursInput ||
    !dom.projectReportWindowMinutesInput ||
    !dom.projectScheduledSendInput ||
    !dom.projectReportScheduleSaveBtn ||
    !dom.projectReportScheduleCancelBtn ||
    !dom.projectReportScheduleHint
  ) {
    return;
  }

  const project = state.currentProject;
  if (!project) {
    dom.projectReportSchedulePanel.classList.add("hidden");
    dom.projectDeadlineSummary.classList.add("hidden");
    dom.projectReportScheduleEditor.classList.add("hidden");
    return;
  }

  const isEditing = state.editingProjectReportSchedule;
  const isSaving = state.pendingProjectScheduleCompanyId === project.id;
  const minimumDate = getProjectReportScheduleMinimumDate(project);

  dom.projectReportSchedulePanel.classList.remove("hidden");
  dom.projectReportScheduleEditBtn.classList.toggle("hidden", isEditing);
  dom.projectReportScheduleEditBtn.disabled = isSaving || isEditing;
  dom.projectReportScheduleEditBtn.textContent = isSaving ? "Saving..." : "Edit";

  const deadline = buildProjectDeadlineSummary(project);
  dom.projectDeadlineSummary.innerHTML = `
    <article class="project-deadline-card">
      <span class="project-deadline-label">${escapeHtml(deadline.windowLabel)}</span>
      <strong class="project-deadline-value">${escapeHtml(deadline.windowValue)}</strong>
    </article>
    <article class="project-deadline-card">
      <span class="project-deadline-label">${escapeHtml(deadline.scheduleLabel)}</span>
      <strong class="project-deadline-value">${escapeHtml(deadline.scheduleValue)}</strong>
      <span class="project-deadline-note">${escapeHtml(deadline.note)}</span>
    </article>
  `;
  dom.projectDeadlineSummary.classList.remove("hidden");

  if (!isEditing) {
    dom.projectReportScheduleEditor.classList.add("hidden");
    dom.projectReportWindowHoursInput.disabled = false;
    dom.projectReportWindowMinutesInput.disabled = false;
    dom.projectScheduledSendInput.disabled = false;
    dom.projectReportScheduleSaveBtn.disabled = false;
    dom.projectReportScheduleCancelBtn.disabled = false;
    dom.projectReportScheduleHint.textContent =
      `Edit the duration or exact date/time. Both stay aligned from the scan start and are shown in ${GMT_MINUS_THREE_LABEL}.`;
    return;
  }

  const fallbackScheduledValue = formatGmtMinusThreeDateTimeLocalValue(computeProjectReportDeadline(project));
  const fallbackWindowParts = splitReportWindowMinutes(project.report_window_minutes);
  if (!state.editingProjectReportWindowHoursValue) {
    state.editingProjectReportWindowHoursValue = String(fallbackWindowParts.hours);
  }
  if (state.editingProjectReportWindowMinutesValue === "") {
    state.editingProjectReportWindowMinutesValue = String(fallbackWindowParts.minutes);
  }
  if (!state.editingProjectScheduledSendValue) {
    state.editingProjectScheduledSendValue = fallbackScheduledValue;
  }

  dom.projectReportScheduleEditor.classList.remove("hidden");
  dom.projectReportWindowHoursInput.value = state.editingProjectReportWindowHoursValue;
  dom.projectReportWindowMinutesInput.value = state.editingProjectReportWindowMinutesValue;
  dom.projectScheduledSendInput.value = state.editingProjectScheduledSendValue;
  dom.projectScheduledSendInput.min = minimumDate
    ? formatGmtMinusThreeDateTimeLocalValue(minimumDate)
    : "";
  dom.projectScheduledSendInput.disabled = isSaving;
  dom.projectReportWindowHoursInput.disabled = isSaving;
  dom.projectReportWindowMinutesInput.disabled = isSaving;
  dom.projectReportScheduleSaveBtn.disabled = isSaving;
  dom.projectReportScheduleCancelBtn.disabled = isSaving;
  dom.projectReportScheduleHint.textContent = isSaving
    ? "Saving report schedule..."
    : `You can use exact minutes or an exact date/time. Times use ${GMT_MINUS_THREE_LABEL}.`;
  if (
    !isSaving &&
    document.activeElement !== dom.projectReportWindowHoursInput &&
    document.activeElement !== dom.projectReportWindowMinutesInput &&
    document.activeElement !== dom.projectScheduledSendInput
  ) {
    window.requestAnimationFrame(() => {
      dom.projectReportWindowHoursInput?.focus();
      dom.projectReportWindowHoursInput?.select();
    });
  }
}

function isTypingTarget(target) {
  if (!(target instanceof Element)) {
    return false;
  }
  const tagName = target.tagName.toLowerCase();
  if (["input", "textarea", "select", "button"].includes(tagName)) {
    return true;
  }
  return target.closest("[contenteditable='true']") !== null;
}

function collectIndustryFilterOptions() {
  const uniqueIndustries = new Set(
    state.projects
      .map((project) => normalizeProjectIndustry(project.industry))
      .filter((industry) => industry !== "unknown"),
  );
  return [...uniqueIndustries].sort((left, right) => left.localeCompare(right));
}

function collectTagFilterOptions() {
  const tagsByKey = new Map();
  state.projects.forEach((project) => {
    normalizeProjectTags(project.tags).forEach((tag) => {
      const key = normalizeTagKey(tag);
      if (!key || tagsByKey.has(key)) {
        return;
      }
      tagsByKey.set(key, tag);
    });
  });
  return [...tagsByKey.entries()]
    .sort((left, right) => left[1].localeCompare(right[1]))
    .map(([key, label]) => ({ key, label }));
}

function syncFilterChipGroup(container, attributeName, activeValue) {
  if (!container) {
    return;
  }
  container.querySelectorAll(`button[${attributeName}]`).forEach((button) => {
    const value = String(button.getAttribute(attributeName) || "");
    const isActive = value === activeValue;
    button.classList.toggle("active", isActive);
    button.setAttribute("aria-pressed", isActive ? "true" : "false");
  });
}

function renderHomeFilterControls() {
  const industries = collectIndustryFilterOptions();
  const tags = collectTagFilterOptions();
  if (dom.homeIndustryFilterSelect) {
    if (state.projectIndustryFilter && !industries.includes(state.projectIndustryFilter)) {
      state.projectIndustryFilter = "";
    }
    const options = [
      `<option value="">All industries</option>`,
      ...industries.map(
        (industry) => `<option value="${escapeHtml(industry)}">${escapeHtml(formatIndustryLabel(industry))}</option>`,
      ),
    ];
    dom.homeIndustryFilterSelect.innerHTML = options.join("");
    dom.homeIndustryFilterSelect.value = state.projectIndustryFilter;
  }
  if (dom.homeTagFilterSelect) {
    if (state.projectTagFilter && !tags.some((tag) => tag.key === state.projectTagFilter)) {
      state.projectTagFilter = "";
    }
    const options = [
      `<option value="">All tags</option>`,
      ...tags.map(
        (tag) => `<option value="${escapeHtml(tag.key)}">${escapeHtml(tag.label)}</option>`,
      ),
    ];
    dom.homeTagFilterSelect.innerHTML = options.join("");
    dom.homeTagFilterSelect.value = state.projectTagFilter;
  }

  syncFilterChipGroup(dom.homeLanguageFilters, "data-language-filter", state.projectLanguageFilter);
  syncFilterChipGroup(dom.homeCeoEmailFilters, "data-ceo-email-filter", state.projectCeoEmailFilter);
  syncFilterChipGroup(dom.homeReplyFilters, "data-response-filter", state.projectReplyFilter);
  syncFilterChipGroup(dom.homeCompanySizeFilters, "data-company-size-filter", state.projectCompanySizeFilter);
}

function getFilteredProjects() {
  return state.projects.filter((project) => {
    const languageMatches =
      state.projectLanguageFilter === "all" ||
      normalizeProjectLanguage(project.language) === state.projectLanguageFilter;
    if (!languageMatches) {
      return false;
    }

    const industryMatches =
      !state.projectIndustryFilter ||
      normalizeProjectIndustry(project.industry) === state.projectIndustryFilter;
    if (!industryMatches) {
      return false;
    }

    const tagMatches =
      !state.projectTagFilter ||
      normalizeProjectTags(project.tags).some((tag) => normalizeTagKey(tag) === state.projectTagFilter);
    if (!tagMatches) {
      return false;
    }

    const ceoEmailMatches =
      state.projectCeoEmailFilter === "all" ||
      (state.projectCeoEmailFilter === "configured" && Boolean(project.has_ceo_email));
    if (!ceoEmailMatches) {
      return false;
    }

    const replyMatches =
      state.projectReplyFilter === "all" ||
      (state.projectReplyFilter === "replied" && Boolean(project.has_contact_reply));
    if (!replyMatches) {
      return false;
    }

    const companySizeMatches =
      state.projectCompanySizeFilter === "all" ||
      normalizeProjectCompanySize(project.company_size) === state.projectCompanySizeFilter;
    if (!companySizeMatches) {
      return false;
    }

    if (!state.projectQuery) {
      return true;
    }

    const haystack = normalizeText(
      `${project.company_name || ""} ${project.source_url || ""} ${project.status || ""} ${(project.tags || []).join(" ")}`,
    );
    return haystack.includes(state.projectQuery);
  });
}

function renderProjectTags(tags) {
  const normalizedTags = normalizeProjectTags(tags);
  if (!normalizedTags.length) {
    return "";
  }
  return `
    <div class="bubble-meta">
      ${normalizedTags.map((tag) => `<span class="mini-chip">${escapeHtml(tag)}</span>`).join("")}
    </div>
  `;
}

function getFilteredThreads(project) {
  return project.threads.filter((thread) => {
    if (!state.threadQuery) {
      return true;
    }

    const latestText = thread.latest_message?.text || "";
    const haystack = normalizeText(
      `${thread.contact_name || ""} ${thread.contact_type || ""} ${thread.contact_value || ""} ${thread.objective || ""} ${latestText}`,
    );
    return haystack.includes(state.threadQuery);
  });
}

function renderContactPendingDot(thread) {
  if (!threadNeedsDelivery(thread)) {
    return "";
  }
  return `<span class="attention-dot" title="Pending delivery"></span>`;
}

function renderProjectPendingBadge(project) {
  const pendingCount = projectPendingDeliveryCount(project);
  if (pendingCount <= 0) {
    return "";
  }
  return `<span class="alert-badge" title="${pendingCount} contacts pending delivery">${pendingCount}</span>`;
}

function truncateWithEllipsis(value, maxChars = 56) {
  const text = String(value || "").trim();
  if (!text) {
    return "";
  }
  if (!Number.isFinite(maxChars) || maxChars < 4 || text.length <= maxChars) {
    return text;
  }
  return `${text.slice(0, maxChars - 1).trimEnd()}…`;
}

function compactUrlForDisplay(value) {
  const text = String(value || "").trim();
  if (!text) {
    return "";
  }
  try {
    const parsed = new URL(text);
    const compact = `${parsed.hostname}${parsed.pathname}`.replace(/\/$/, "");
    return compact || text;
  } catch {
    return text;
  }
}

function normalizeExternalUrl(value) {
  const rawValue = String(value || "").trim();
  if (!rawValue) {
    return "";
  }
  const withScheme = /^https?:\/\//i.test(rawValue) ? rawValue : `https://${rawValue}`;
  try {
    return new URL(withScheme).href;
  } catch {
    return "";
  }
}

function buildDevScanSourceLabel(text) {
  const normalized = String(text || "").replace(/\s+/g, " ").trim();
  if (!normalized) {
    return "Dev text input";
  }
  if (normalized.length <= 72) {
    return `Dev text: ${normalized}`;
  }
  return `Dev text: ${normalized.slice(0, 69).trimEnd()}...`;
}

function threadDisplayTitle(thread, maxChars = 56) {
  const preferred = String(thread?.contact_name || "").trim();
  const fallback = String(thread?.contact_value || "").trim();
  const candidate = preferred || compactUrlForDisplay(fallback);
  return truncateWithEllipsis(candidate, maxChars) || "Contact";
}

function threadObjectiveText(thread) {
  return String(thread?.objective || "").trim();
}

function threadObjectiveCaption(thread, fallback = "No objective defined.") {
  const objective = threadObjectiveText(thread);
  if (!objective) {
    return fallback;
  }
  return `Objective: ${objective}`;
}

function threadMetaLabel(thread) {
  const parts = [
    String(thread?.contact_type || "").trim(),
    String(thread?.contact_value || "").trim(),
  ].filter(Boolean);
  if (thread?.conversation_done) {
    parts.push("Closed");
  }
  return parts.join(" · ");
}

function renderThreadDoneBadge(thread) {
  if (!thread?.conversation_done) {
    return "";
  }
  return `<span class="status-chip completed thread-state-chip">Closed</span>`;
}

function renderProcessingState(title, note) {
  return `
    <div class="processing-state" aria-live="polite">
      <div class="loading-spinner"></div>
      <h3>${escapeHtml(title)}</h3>
      <p class="empty-note">${escapeHtml(note)}</p>
    </div>
  `;
}

function renderSidebarContactPicker(threads, selectedThreadId) {
  if (!dom.sidebarFocusSelect || !dom.sidebarFocusSelectHint) {
    return;
  }

  const hasThreads = Array.isArray(threads) && threads.length > 0;
  if (!hasThreads) {
    dom.sidebarFocusSelect.innerHTML = `<option value="">No contacts available</option>`;
    dom.sidebarFocusSelect.value = "";
    dom.sidebarFocusSelect.disabled = true;
    dom.sidebarFocusSelectHint.textContent = state.currentProject
      ? projectIsProcessing(state.currentProject)
        ? "Company scan still processing. Contacts will appear when it finishes."
        : "No contacts discovered for this company yet."
      : "Open a company to load contacts.";
    return;
  }

  const hasSelectedThread =
    Boolean(selectedThreadId) && threads.some((thread) => thread.id === selectedThreadId);
  const placeholder = hasSelectedThread ? "" : `<option value="">Select a contact...</option>`;
  const options = threads
    .map((thread) => {
      const title = threadDisplayTitle(thread);
      const type = thread.contact_type || thread.type || "contact";
      const value = thread.contact_value || thread.value || "";
      const label = `${title} · ${type} · ${value}`;
      return `<option value="${escapeHtml(thread.id)}">${escapeHtml(label)}</option>`;
    })
    .join("");
  dom.sidebarFocusSelect.innerHTML = `${placeholder}${options}`;
  dom.sidebarFocusSelect.value = hasSelectedThread ? selectedThreadId : "";

  if (state.showArchivedThreads) {
    dom.sidebarFocusSelect.disabled = true;
    dom.sidebarFocusSelectHint.textContent = "Switch to active contacts to pick a current focus.";
    return;
  }

  dom.sidebarFocusSelect.disabled = false;
  dom.sidebarFocusSelectHint.textContent = `${threads.length} contacts available.`;
}

function renderSidebarCompanyContext(project, visibleContacts) {
  if (dom.sidebarCompanyTitle) {
    dom.sidebarCompanyTitle.textContent = project?.company_name || "No company selected";
  }
  if (dom.sidebarCompanyMeta) {
    dom.sidebarCompanyMeta.textContent = project?.source_url || "Select a company to view extracted company information.";
  }
  if (dom.sidebarCompanyStats) {
    if (!project) {
      dom.sidebarCompanyStats.innerHTML = "";
    } else {
      const objectiveText = String(project.objective || "").trim() || "Not defined";
      const tagsText = normalizeProjectTags(project.tags).join(", ") || "None";
      dom.sidebarCompanyStats.innerHTML = `
        <p class="sidebar-company-stat"><strong>Status:</strong> ${escapeHtml(project.status || "unknown")}</p>
        <p class="sidebar-company-stat"><strong>Contacts:</strong> ${escapeHtml(String(visibleContacts))}</p>
        <p class="sidebar-company-stat"><strong>Tags:</strong> ${escapeHtml(tagsText)}</p>
        <p class="sidebar-company-stat"><strong>Objective:</strong> ${escapeHtml(objectiveText)}</p>
      `;
    }
  }
  if (dom.sidebarCompanyInfo) {
    const companyInfo = String(project?.company_info || "").trim();
    dom.sidebarCompanyInfo.innerHTML = companyInfo
      ? renderMarkdown(companyInfo)
      : project && projectIsProcessing(project)
        ? "<p>Company context is still being extracted.</p>"
        : "<p>No extracted company information yet.</p>";
  }
}

function renderSidebarFocus() {
  if (currentSectionIsCrm()) {
    if (dom.sidebarFocusCard) {
      dom.sidebarFocusCard.classList.add("hidden");
    }
    if (dom.sidebarCompanyCard) {
      dom.sidebarCompanyCard.classList.add("hidden");
    }
    dom.sidebarFocusTitle.textContent = "CEO CRM";
    dom.sidebarFocusMeta.textContent = "Global inbox for CEO report-delivery threads.";
    renderSidebarContactPicker([], null);
    renderSidebarCompanyContext(null, 0);
  } else if (currentSectionIsContadores()) {
    if (dom.sidebarFocusCard) {
      dom.sidebarFocusCard.classList.add("hidden");
    }
    if (dom.sidebarCompanyCard) {
      dom.sidebarCompanyCard.classList.add("hidden");
    }
    dom.sidebarFocusTitle.textContent = "Contadores";
    dom.sidebarFocusMeta.textContent = "Dedicated workspace for spreadsheet leads and WhatsApp automation.";
    renderSidebarContactPicker([], null);
    renderSidebarCompanyContext(null, 0);
  } else if (!state.currentProject) {
    if (dom.sidebarFocusCard) {
      dom.sidebarFocusCard.classList.add("hidden");
    }
    if (dom.sidebarCompanyCard) {
      dom.sidebarCompanyCard.classList.add("hidden");
    }
    dom.sidebarFocusTitle.textContent = "No company selected";
    dom.sidebarFocusMeta.textContent = "Open a company to continue message relay and report preparation.";
    renderSidebarContactPicker([], null);
    renderSidebarCompanyContext(null, 0);
  } else {
    if (dom.sidebarFocusCard) {
      dom.sidebarFocusCard.classList.remove("hidden");
    }
    if (dom.sidebarCompanyCard) {
      dom.sidebarCompanyCard.classList.remove("hidden");
    }

    const threads = Array.isArray(state.currentProject.threads) ? state.currentProject.threads : [];
    const thread = getCurrentThread();
    if (!thread) {
      const modeLabel = state.showArchivedThreads ? "archived contacts" : "active contacts";
      dom.sidebarFocusTitle.textContent = state.currentProject.company_name || "Selected company";
      dom.sidebarFocusMeta.textContent = threads.length
        ? `Select a contact from the dropdown (${threads.length} ${modeLabel}).`
        : projectIsProcessing(state.currentProject)
          ? "Scan still processing. Contacts will appear here when ready."
          : `No ${modeLabel} available.`;
      renderSidebarContactPicker(threads, null);
      renderSidebarCompanyContext(state.currentProject, threads.length);
    } else {
      const threadTitle = threadDisplayTitle(thread);
      dom.sidebarFocusTitle.textContent = `${state.currentProject.company_name} · ${threadTitle}`;
      dom.sidebarFocusMeta.textContent = `${thread.contact_type} · ${thread.contact_value}`;
      renderSidebarContactPicker(threads, thread.id);
      renderSidebarCompanyContext(state.currentProject, threads.length);
    }
  }

  renderSidebarAssistant();
}

function renderHomeMetrics() {
  if (!dom.homeMetrics) {
    return;
  }

  const visibleProjects = state.projects.length ? getFilteredProjects().length : 0;

  dom.homeMetrics.innerHTML = `
    <p class="home-company-counter" aria-live="polite">
      <span>Companies</span>
      <strong>${visibleProjects}</strong>
    </p>
  `;
}

function renderHomeProjectCard(project, index) {
  const processing = projectIsProcessing(project);
  const summaryLine = processing
    ? `Scan in progress · Created ${escapeHtml(formatRelativeDate(project.created_at))}`
    : `${escapeHtml(project.total_threads)} contacts · Updated ${escapeHtml(formatRelativeDate(project.updated_at))}`;
  const tagsMarkup = renderProjectTags(project.tags);

  return `
    <article class="project-card ${statusClassName(processing ? "initializing" : project.status)} ${processing ? "initializing" : ""} animate-stagger" data-home-project-id="${escapeHtml(project.id)}" style="--stagger-idx: ${index}">
      <button type="button" class="project-card-content" data-home-project-id="${escapeHtml(project.id)}">
        <div class="thread-line">
          <h3>${escapeHtml(project.company_name)}</h3>
          <div class="thread-line-right">
            ${statusChip(processing ? "processing" : project.status)}
            ${managementChip(project.conversation_automation_enabled)}
            ${renderProjectPendingBadge(project)}
          </div>
        </div>
        <p>${escapeHtml(project.source_url)}</p>
        ${tagsMarkup}
        ${processing ? `<p>Discovering contacts and preparing initial outbound messages <span class="loading-spinner-small" aria-hidden="true"></span></p>` : ""}
        <p>${summaryLine}</p>
      </button>
      <button type="button" class="project-delete-btn" data-delete-project-id="${escapeHtml(project.id)}" aria-label="Delete company" title="Delete company">×</button>
    </article>
  `;
}

function renderHomeProjects() {
  renderHomeFilterControls();
  renderHomeMetrics();

  if (!state.projects.length) {
    dom.homeProjects.innerHTML = `
      <button type="button" class="project-card empty-state-card" id="emptyStateCreateProject" aria-live="polite">
        <h3>No companies yet</h3>
        <p>Run your first company scan to discover contacts and start the conversation loop.</p>
        <span class="empty-state-cta">Scan Company</span>
      </button>
    `;
    dom.homeProjects.querySelector("#emptyStateCreateProject")?.addEventListener("click", openCreateProjectModal);
    return;
  }

  const filteredProjects = getFilteredProjects();
  if (!filteredProjects.length) {
    dom.homeProjects.innerHTML = `
      <article class="project-card empty-state-card" aria-live="polite">
        <h3>No matches</h3>
        <p>Try a broader search.</p>
      </article>
    `;
    return;
  }

  const projectGroups = groupProjectsByCreatedDay(filteredProjects);
  let staggerIndex = 0;

  dom.homeProjects.innerHTML = projectGroups
    .map((group) => {
      const cardsMarkup = group.projects
        .map((project) => {
          const markup = renderHomeProjectCard(project, staggerIndex);
          staggerIndex += 1;
          return markup;
        })
        .join("");

      return `
        <section class="project-day-group" data-created-day="${escapeHtml(group.dayKey)}">
          <header class="project-day-divider">
            <p class="project-day-kicker">Created</p>
            <div class="project-day-divider-main">
              <h3 class="project-day-title">${escapeHtml(group.label)}</h3>
              <span class="project-day-count">${escapeHtml(pluralize(group.projects.length, "company", "companies"))}</span>
            </div>
          </header>
          <div class="projects-grid">
            ${cardsMarkup}
          </div>
        </section>
      `;
    })
    .join("");

  dom.homeProjects.querySelectorAll(".project-card-content").forEach((node) => {
    node.addEventListener("click", (event) => {
      if (event.target.closest(".project-delete-btn")) {
        return;
      }
      const projectId = node.getAttribute("data-home-project-id");
      if (projectId) {
        openProject(projectId);
      }
    });
  });

  dom.homeProjects.querySelectorAll(".project-delete-btn").forEach((node) => {
    node.addEventListener("click", async (event) => {
      event.stopPropagation();
      const projectId = node.getAttribute("data-delete-project-id");
      if (!projectId) {
        return;
      }
      const project = state.projects.find((p) => p.id === projectId);
      const projectName = project?.company_name || "this company";
      if (!confirm(`Are you sure you want to delete \"${projectName}\"? This action cannot be undone.`)) {
        return;
      }
      await handleDeleteProject(projectId);
    });
  });
}

function renderProjectHeader() {
  if (!state.currentProject) {
    return;
  }

  const project = state.currentProject;
  const processing = projectIsProcessing(project);
  const modeLabel = state.showArchivedThreads ? "archived contacts" : "active contacts";
  const pendingCount = projectPendingDeliveryCount(project);
  const pendingLabel = pendingCount > 0 ? ` · ${pendingCount} pending delivery` : "";
  const processingLabel = processing ? " · Processing scan" : "";
  const sourceUrlText = String(project.source_url || "").trim();
  const normalizedSourceUrl = normalizeExternalUrl(sourceUrlText);
  if (dom.projectSourceUrlLink) {
    dom.projectSourceUrlLink.textContent = sourceUrlText || "-";
    if (normalizedSourceUrl) {
      dom.projectSourceUrlLink.href = normalizedSourceUrl;
      dom.projectSourceUrlLink.removeAttribute("aria-disabled");
      dom.projectSourceUrlLink.classList.remove("is-disabled");
    } else {
      dom.projectSourceUrlLink.removeAttribute("href");
      dom.projectSourceUrlLink.setAttribute("aria-disabled", "true");
      dom.projectSourceUrlLink.classList.add("is-disabled");
    }
  }
  dom.projectTitle.textContent = project.company_name;
  const managementLabel = projectConversationAutomationEnabled(project)
    ? "Conversation automation on"
    : "Conversation automation off";
  const deliveryLabel = projectCeoDeliveryEnabled(project) ? "CEO delivery on" : "CEO delivery off";
  const tagsLabel = normalizeProjectTags(project.tags).length
    ? ` · Tags: ${normalizeProjectTags(project.tags).join(", ")}`
    : "";
  dom.projectMeta.textContent =
    `${project.total_threads} ${modeLabel}${pendingLabel}${processingLabel} · ${managementLabel} · ${deliveryLabel} · Created ${formatDate(project.created_at)}${tagsLabel}`;

  if (dom.projectProcessingBanner) {
    if (processing) {
      dom.projectProcessingBanner.classList.remove("hidden");
      dom.projectProcessingBanner.innerHTML = `
        <span class="loading-spinner-small" aria-hidden="true"></span>
        <span>Scan still running. Company context and contacts stay blurred until the current task finishes.</span>
      `;
    } else {
      dom.projectProcessingBanner.classList.add("hidden");
      dom.projectProcessingBanner.innerHTML = "";
    }
  }

  [dom.contactsGridContainer, dom.threadsSidebar, dom.chatPanel, dom.sidebarCompanyCard, dom.sidebarFocusCard].forEach((node) => {
    node?.classList.toggle("is-processing", processing);
  });
  if (dom.openManualContactModalBtn) {
    dom.openManualContactModalBtn.disabled = processing;
  }
  if (dom.threadSearchInput) {
    dom.threadSearchInput.disabled = processing;
  }
  if (dom.rescanCompanyBtn) {
    dom.rescanCompanyBtn.classList.toggle("hidden", !projectCanRescan(project));
    dom.rescanCompanyBtn.disabled = processing;
  }

  const filteredCount = getFilteredThreads(project).length;
  dom.threadsSummary.textContent = `Showing ${filteredCount}/${project.threads.length} ${modeLabel}`;

  renderSidebarFocus();
  syncReportActions();
  syncProjectAutomationControls();
  renderProjectCeoEmailPanel();
  renderProjectReportSchedulePanel();
  syncArchivedContactsToggleButton();
}

function renderThreadList() {
  const project = state.currentProject;
  const modeLabel = state.showArchivedThreads ? "archived contacts" : "active contacts";
  if (!project) {
    dom.threadList.innerHTML = `<p class="empty-note">Loading...</p>`;
    dom.threadsSummary.textContent = "Loading...";
    return;
  }

  if (projectIsProcessing(project) && !project.threads.length) {
    dom.threadList.innerHTML = renderProcessingState(
      "Processing company scan",
      "Contacts will appear here after discovery and initial outbound seeding finish.",
    );
    dom.threadsSummary.textContent = "Processing contacts...";
    return;
  }

  if (!project.threads.length) {
    const emptyMessage = state.showArchivedThreads
      ? "No archived contacts."
      : "No active contacts discovered yet.";
    dom.threadList.innerHTML = `<p class="empty-note">${emptyMessage}</p>`;
    dom.threadsSummary.textContent = `No ${modeLabel} available.`;
    return;
  }

  const filteredThreads = getFilteredThreads(project);
  dom.threadsSummary.textContent = `Showing ${filteredThreads.length}/${project.threads.length} ${modeLabel}`;

  if (!filteredThreads.length) {
    dom.threadList.innerHTML = `<p class="empty-note">No ${modeLabel} match current search.</p>`;
    return;
  }

  if (state.showArchivedThreads) {
    dom.threadList.innerHTML = filteredThreads
      .map((thread, index) => {
        const fullTitle = thread.contact_name || thread.contact_value || "Contact";
        const title = threadDisplayTitle(thread, 56);
        const latest = thread.latest_message ? thread.latest_message.text : "No messages while archived.";
        const preview = String(latest).trim();
        const clipped = preview.length > 90 ? `${preview.slice(0, 90)}...` : preview;
        return `
          <article class="thread-card thread-card-archived animate-stagger" style="--stagger-idx: ${index}">
            <div class="thread-item thread-item-static">
              <div class="thread-line">
                <p class="thread-title" title="${escapeHtml(fullTitle)}">${escapeHtml(title)}</p>
                <div class="thread-line-badges">
                  ${renderThreadDoneBadge(thread)}
                  ${renderContactPendingDot(thread)}
                </div>
              </div>
              <p class="thread-caption">${escapeHtml(threadMetaLabel(thread))}</p>
              <p class="thread-caption thread-caption-objective">${escapeHtml(threadObjectiveCaption(thread))}</p>
              <p class="thread-caption">${escapeHtml(clipped || "No messages yet")}</p>
            </div>
            <div class="thread-item-actions">
              <button type="button" class="btn btn-secondary btn-sm thread-action-btn" data-unarchive-thread-id="${escapeHtml(thread.id)}">Unarchive</button>
              <button type="button" class="btn btn-secondary btn-sm btn-destructive thread-action-btn" data-delete-thread-id="${escapeHtml(thread.id)}">Delete</button>
            </div>
          </article>
        `;
      })
      .join("");

    dom.threadList.querySelectorAll("[data-unarchive-thread-id]").forEach((node) => {
      node.addEventListener("click", async () => {
        const threadId = node.getAttribute("data-unarchive-thread-id");
        if (!threadId) {
          return;
        }
        await handleSetThreadArchived(threadId, false);
      });
    });

    dom.threadList.querySelectorAll("[data-delete-thread-id]").forEach((node) => {
      node.addEventListener("click", async () => {
        const threadId = node.getAttribute("data-delete-thread-id");
        if (!threadId) {
          return;
        }
        const thread = state.currentProject?.threads?.find((item) => item.id === threadId);
        const threadName = thread?.contact_name || thread?.contact_value || "this contact";
        if (!confirm(`Are you sure you want to delete \"${threadName}\"? This action cannot be undone.`)) {
          return;
        }
        await handleDeleteThread(threadId);
      });
    });
    return;
  }

  dom.threadList.innerHTML = filteredThreads
    .map((thread, index) => {
      const isActive = thread.id === state.currentThreadId ? "active" : "";
      const fullTitle = thread.contact_name || thread.contact_value || "Contact";
      const title = threadDisplayTitle(thread, 56);
      const latest = thread.latest_message ? thread.latest_message.text : "No messages yet";
      const preview = String(latest).trim();
      const clipped = preview.length > 90 ? `${preview.slice(0, 90)}...` : preview;
      return `
        <article class="thread-card ${isActive} animate-stagger" style="--stagger-idx: ${index}">
          <button type="button" class="thread-item ${isActive}" data-thread-id="${escapeHtml(thread.id)}">
            <div class="thread-line">
              <p class="thread-title" title="${escapeHtml(fullTitle)}">${escapeHtml(title)}</p>
              <div class="thread-line-badges">
                ${renderThreadDoneBadge(thread)}
                ${renderContactPendingDot(thread)}
              </div>
            </div>
            <p class="thread-caption">${escapeHtml(threadMetaLabel(thread))}</p>
            <p class="thread-caption thread-caption-objective">${escapeHtml(threadObjectiveCaption(thread))}</p>
            <p class="thread-caption">${escapeHtml(clipped)}</p>
          </button>
          <div class="thread-item-actions">
            <button type="button" class="btn btn-secondary btn-sm thread-action-btn" data-archive-thread-id="${escapeHtml(thread.id)}">Archive</button>
            <button type="button" class="btn btn-secondary btn-sm btn-destructive thread-action-btn" data-delete-thread-id="${escapeHtml(thread.id)}">Delete</button>
          </div>
        </article>
      `;
    })
    .join("");

  dom.threadList.querySelectorAll("[data-thread-id]").forEach((node) => {
    node.addEventListener("click", () => {
      const threadId = node.getAttribute("data-thread-id");
      if (threadId) {
        selectThread(threadId);
      }
    });
  });

  dom.threadList.querySelectorAll("[data-archive-thread-id]").forEach((node) => {
    node.addEventListener("click", async (event) => {
      event.stopPropagation();
      const threadId = node.getAttribute("data-archive-thread-id");
      if (!threadId) {
        return;
      }
      await handleSetThreadArchived(threadId, true);
    });
  });

  dom.threadList.querySelectorAll("[data-delete-thread-id]").forEach((node) => {
    node.addEventListener("click", async (event) => {
      event.stopPropagation();
      const threadId = node.getAttribute("data-delete-thread-id");
      if (!threadId) {
        return;
      }
      const thread = state.currentProject?.threads?.find((item) => item.id === threadId);
      const threadName = thread?.contact_name || thread?.contact_value || "this contact";
      if (!confirm(`Are you sure you want to delete \"${threadName}\"? This action cannot be undone.`)) {
        return;
      }
      await handleDeleteThread(threadId);
    });
  });
}

function renderTranscript() {
  const thread = getCurrentThread();
  const whatsappTheme = isWhatsAppThread(thread);
  const showAiWriting = hasPendingInboundTask(state.currentThreadId);
  const showDraftIndicator = showAiWriting;
  const draftIndicatorText = "AI is writing...";
  dom.transcript.classList.toggle("transcript-whatsapp", whatsappTheme);

  if (!state.threadMessages.length && !showDraftIndicator) {
    dom.transcript.innerHTML = `<p class="empty-note">No messages yet.</p>`;
    state.lastRenderedThreadId = state.currentThreadId;
    state.lastRenderedMessageCount = 0;
    return;
  }

  const shouldSnapToBottom =
    state.lastRenderedThreadId !== state.currentThreadId ||
    state.threadMessages.length > state.lastRenderedMessageCount;

  const renderedMessages = state.threadMessages
    .map((message, index) => {
      const outgoing = Boolean(message.from_me);
      const directionClass = outgoing ? "from-me" : "from-contact";
      const label = outgoing ? "Draft (AI)" : "Contact";
      const messageId = getMessageId(message);
      const canEdit = Boolean(messageId);
      const isEditing = canEdit && state.editingMessageId === messageId;
      const editButton = canEdit
        ? `<button type="button" class="message-edit-btn" data-action="edit-message" data-message-id="${messageId}" aria-label="Edit message" title="Edit message">✎</button>`
        : "";
      const editor = isEditing
        ? `
          <div class="message-editor">
            <textarea class="message-editor-input" data-action="edit-input" data-message-id="${messageId}" rows="3">${escapeHtml(state.editingMessageText)}</textarea>
            <div class="message-editor-actions">
              <button type="button" class="btn btn-primary btn-sm" data-action="save-edit" data-message-id="${messageId}">Save</button>
              <button type="button" class="btn btn-secondary btn-sm" data-action="cancel-edit">Cancel</button>
            </div>
          </div>
        `
        : "";
      const deliveryStatus = normalizeDeliveryStatus(message.delivery_status);
      const deliveryLabel = deliveryStatus === "delivered"
        ? "Delivered"
        : deliveryStatus === "sent"
          ? "Sent"
          : deliveryStatus === "failed"
            ? "Failed"
            : "Pending";
      const deliveryChip = outgoing
        ? `<span class="message-delivery-chip ${deliveryStatus}">${deliveryLabel}</span>`
        : "";
      const deliveryButton =
        outgoing && canEdit && !whatsappTheme && deliveryStatus !== "delivered"
          ? `<button type="button" class="btn btn-secondary btn-xs message-delivery-btn" data-action="mark-delivered" data-message-id="${messageId}">Mark Delivered</button>`
          : "";
      const deliveryRow = outgoing
        ? `<div class="message-delivery-row">${deliveryChip}${deliveryButton}</div>`
        : "";
      if (whatsappTheme) {
        return `
          <div class="wa-row ${outgoing ? "outgoing" : "incoming"}">
            <article class="wa-msg ${outgoing ? "outgoing" : "incoming"} transcript-message copyable-message ${isEditing ? "editing" : ""}" data-message-index="${index}">
              ${editButton}
              <span class="wa-sender">${escapeHtml(label)}</span>
              <p class="wa-text">${escapeHtml(message.text)}</p>
              ${deliveryRow}
              <span class="wa-time">${escapeHtml(formatTime(message.timestamp))}</span>
              <span class="msg-copy-feedback">Copied</span>
              ${editor}
            </article>
          </div>
        `;
      }
      return `
        <div class="bubble-wrap ${directionClass}">
          <article class="bubble ${message.from_me ? "from-me" : "from-contact"} transcript-message copyable-message ${isEditing ? "editing" : ""}" data-message-index="${index}">
            ${editButton}
            <header class="bubble-header">
              <span>${escapeHtml(label)}</span>
              <span>${escapeHtml(formatTime(message.timestamp))}</span>
            </header>
            <p class="bubble-text">${escapeHtml(message.text)}</p>
            ${deliveryRow}
            <span class="msg-copy-feedback">Copied</span>
            ${editor}
          </article>
        </div>
      `;
    })
    .join("");

  const writingIndicator = showDraftIndicator
    ? whatsappTheme
      ? `
        <div class="wa-row outgoing">
          <article class="wa-msg outgoing ai-typing-indicator">
            <span class="wa-sender">Draft (AI)</span>
            <p class="wa-text">${escapeHtml(draftIndicatorText)}</p>
            <span class="wa-time">...</span>
          </article>
        </div>
      `
      : `
        <div class="bubble-wrap from-me">
          <article class="bubble from-me ai-typing-indicator">
            <header class="bubble-header">
              <span>Draft (AI)</span>
              <span>...</span>
            </header>
            <p class="bubble-text">${escapeHtml(draftIndicatorText)}</p>
          </article>
        </div>
      `
    : "";

  dom.transcript.innerHTML = renderedMessages + writingIndicator;
  bindTranscriptInteractions();

  state.lastRenderedThreadId = state.currentThreadId;
  state.lastRenderedMessageCount = state.threadMessages.length;

  if (shouldSnapToBottom) {
    window.requestAnimationFrame(() => {
      dom.transcript.scrollTop = dom.transcript.scrollHeight;
    });
  }
}

function bindTranscriptInteractions() {
  if (!dom.transcript) {
    return;
  }

  dom.transcript.querySelectorAll(".copyable-message").forEach((node) => {
    node.addEventListener("click", async (event) => {
      if (node.classList.contains("editing")) {
        return;
      }
      if (event.target.closest("[data-action]") || event.target.closest("textarea")) {
        return;
      }
      const index = Number(node.getAttribute("data-message-index"));
      const message = Number.isInteger(index) ? state.threadMessages[index] : null;
      if (!message || !message.text) {
        return;
      }
      try {
        await copyTextToClipboard(message.text);
        showCopiedEffect(node);
      } catch {
        showToast("Clipboard copy failed.", true);
      }
    });
  });

  dom.transcript.querySelectorAll("[data-action='edit-message']").forEach((node) => {
    node.addEventListener("click", (event) => {
      event.preventDefault();
      event.stopPropagation();
      const messageId = Number(node.getAttribute("data-message-id"));
      if (!Number.isInteger(messageId)) {
        return;
      }
      const message = getMessageById(messageId);
      if (!message) {
        return;
      }
      state.editingMessageId = messageId;
      state.editingMessageText = message.text || "";
      renderTranscript();
    });
  });

  dom.transcript.querySelectorAll("[data-action='cancel-edit']").forEach((node) => {
    node.addEventListener("click", (event) => {
      event.preventDefault();
      event.stopPropagation();
      clearMessageEditing();
      renderTranscript();
    });
  });

  dom.transcript.querySelectorAll("[data-action='edit-input']").forEach((node) => {
    node.addEventListener("click", (event) => {
      event.stopPropagation();
    });
    node.addEventListener("input", () => {
      state.editingMessageText = node.value;
    });
  });

  dom.transcript.querySelectorAll("[data-action='save-edit']").forEach((node) => {
    node.addEventListener("click", async (event) => {
      event.preventDefault();
      event.stopPropagation();
      const messageId = Number(node.getAttribute("data-message-id"));
      if (!Number.isInteger(messageId) || !state.currentProjectId || !state.currentThreadId) {
        return;
      }
      const text = String(state.editingMessageText || "").trim();
      if (!text) {
        showToast("Message text is required.", true);
        return;
      }
      const saveBtn = node;
      const cancelBtn = node.parentElement?.querySelector("[data-action='cancel-edit']");
      saveBtn.disabled = true;
      if (cancelBtn) {
        cancelBtn.disabled = true;
      }
      try {
        const updated = await apiFetch(
          `/api/companies/${state.currentProjectId}/contacts/${state.currentThreadId}/messages/${messageId}`,
          {
            method: "PUT",
            body: { text },
          },
        );
        state.threadMessages = state.threadMessages.map((message) => {
          if (getMessageId(message) !== messageId) {
            return message;
          }
          return {
            ...message,
            ...updated,
            text: updated.text,
          };
        });
        syncThreadLatestFromMessages();
        clearMessageEditing();
        renderThreadList();
        renderThreadSidebar();
        renderTranscript();
        showToast("Message updated.");
      } catch (error) {
        showToast(error.message || "Failed updating message", true);
      } finally {
        saveBtn.disabled = false;
        if (cancelBtn) {
          cancelBtn.disabled = false;
        }
      }
    });
  });

  dom.transcript.querySelectorAll("[data-action='mark-delivered']").forEach((node) => {
    node.addEventListener("click", async (event) => {
      event.preventDefault();
      event.stopPropagation();
      const messageId = Number(node.getAttribute("data-message-id"));
      if (!Number.isInteger(messageId) || !state.currentProjectId || !state.currentThreadId) {
        return;
      }
      node.disabled = true;
      try {
        const updated = await apiFetch(
          `/api/companies/${state.currentProjectId}/contacts/${state.currentThreadId}/messages/${messageId}/delivery`,
          {
            method: "PUT",
            body: { delivered: true },
          },
        );
        state.threadMessages = state.threadMessages.map((message) => {
          if (getMessageId(message) !== messageId) {
            return message;
          }
          return {
            ...message,
            ...updated,
            delivery_status: updated.delivery_status,
          };
        });
        syncThreadLatestFromMessages();
        renderProjectHeader();
        renderThreadList();
        renderThreadSidebar();
        renderHomeProjects();
        renderTranscript();
        showToast("Message marked as delivered.");
      } catch (error) {
        showToast(error.message || "Failed marking message as delivered", true);
      } finally {
        node.disabled = false;
      }
    });
  });
}

function showContactsView() {
  if (dom.contactsGridContainer) {
    dom.contactsGridContainer.classList.remove("hidden");
  }
  if (dom.threadsSidebar) {
    dom.threadsSidebar.classList.add("hidden");
  }
  if (dom.chatPanel) {
    dom.chatPanel.classList.add("hidden");
    dom.chatPanel.classList.remove("chat-panel-whatsapp");
  }
  if (dom.emailThreadLinkPanel) {
    dom.emailThreadLinkPanel.classList.add("hidden");
  }
  if (dom.archiveThreadBtn) {
    dom.archiveThreadBtn.classList.add("hidden");
    delete dom.archiveThreadBtn.dataset.archiveThreadId;
    delete dom.archiveThreadBtn.dataset.archiveNextState;
  }
  setTranscriptSummaryCopyState("");
}

function showThreadView() {
  if (state.showArchivedThreads) {
    showContactsView();
    return;
  }
  if (dom.contactsGridContainer) {
    dom.contactsGridContainer.classList.add("hidden");
  }
  if (dom.threadsSidebar) {
    dom.threadsSidebar.classList.remove("hidden");
  }
  if (dom.chatPanel) {
    dom.chatPanel.classList.remove("hidden");
  }

  const thread = getCurrentThread();
  if (!thread) {
    if (dom.chatPanel) {
      dom.chatPanel.classList.remove("chat-panel-whatsapp");
    }
    if (dom.archiveThreadBtn) {
      dom.archiveThreadBtn.classList.add("hidden");
    }
    if (dom.chatThreadObjective) {
      dom.chatThreadObjective.textContent = "";
      dom.chatThreadObjective.classList.add("hidden");
    }
    setTranscriptSummaryCopyState("");
    return;
  }
  const archived = isArchivedThread(thread);
  const whatsappTheme = isWhatsAppThread(thread);
  if (dom.chatPanel) {
    dom.chatPanel.classList.toggle("chat-panel-whatsapp", whatsappTheme);
  }

  const title = thread.contact_name || thread.contact_value;
  dom.chatThreadTitle.textContent = title;
  dom.chatThreadMeta.textContent = threadMetaLabel(thread);
  if (dom.chatThreadObjective) {
    const objectiveText = threadObjectiveText(thread);
    if (objectiveText) {
      dom.chatThreadObjective.textContent = `Objective: ${objectiveText}`;
      dom.chatThreadObjective.classList.remove("hidden");
    } else {
      dom.chatThreadObjective.textContent = "";
      dom.chatThreadObjective.classList.add("hidden");
    }
  }

  const emailThread = isEmailThread(thread);
  const needsEmailLink = emailThread && !thread.email_thread_link && thread.requires_email_thread_link;
  const emailThreadLinkPanelDismissed = isEmailThreadLinkPanelDismissed(thread);
  if (emailThread) {
    const emailSubject = String(thread.email_subject || "").trim();
    dom.transcriptSummary.textContent = emailSubject || "No subject";
    setTranscriptSummaryCopyState(emailSubject);
  } else {
    const inboundCount = state.threadMessages.filter((message) => !message.from_me).length;
    const outboundCount = state.threadMessages.filter((message) => message.from_me).length;
    const archivedHint = archived ? " · archived" : "";
    dom.transcriptSummary.textContent = `${pluralize(state.threadMessages.length, "message", "messages")} · ${inboundCount} inbound · ${outboundCount} drafts${archivedHint}`;
    setTranscriptSummaryCopyState("");
  }

  if (dom.emailQuickLink) {
    if (thread.email_link && !archived) {
      dom.emailQuickLink.href = thread.email_link;
      dom.emailQuickLink.classList.remove("hidden");
    } else {
      dom.emailQuickLink.classList.add("hidden");
    }
  }

  const waLink = buildWhatsAppLinkWithLatestMessage(thread);
  if (waLink && !archived) {
    dom.waQuickLink.href = waLink;
    dom.waQuickLink.classList.remove("hidden");
  } else {
    dom.waQuickLink.classList.add("hidden");
  }

  if (dom.emailThreadLinkPanel && dom.emailThreadLinkInput && dom.emailThreadLinkHint) {
    if (emailThread && !archived) {
      if (needsEmailLink && !emailThreadLinkPanelDismissed) {
        dom.emailThreadLinkPanel.classList.remove("hidden");
        dom.emailThreadLinkInput.value = thread.email_thread_link || "";
        dom.emailThreadLinkHint.textContent =
          "No thread link saved yet. Paste your inbox thread URL to keep Open Email available.";
      } else {
        dom.emailThreadLinkPanel.classList.add("hidden");
      }
    } else {
      dom.emailThreadLinkPanel.classList.add("hidden");
    }
  }

  if (dom.archiveThreadBtn) {
    dom.archiveThreadBtn.textContent = archived ? "Unarchive Contact" : "Archive Contact";
    dom.archiveThreadBtn.classList.remove("hidden");
    dom.archiveThreadBtn.dataset.archiveThreadId = thread.id;
    dom.archiveThreadBtn.dataset.archiveNextState = archived ? "false" : "true";
  }

  syncInboundComposerState();

  renderTranscript();
  renderSidebarFocus();
  renderThreadSidebar();
}

async function handleSetThreadArchived(threadId, archived) {
  if (!state.currentProjectId || !threadId) {
    return;
  }
  const label = archived ? "Archiving..." : "Unarchiving...";
  showLoading(label);
  try {
    await apiFetch(
      `/api/companies/${state.currentProjectId}/contacts/${threadId}/archive`,
      {
        method: "PUT",
        body: { archived: Boolean(archived) },
      },
    );
    await refreshCurrentProject(false);
    showToast(archived ? "Contact archived." : "Contact unarchived.");
  } catch (error) {
    showToast(error.message || "Failed updating contact archive status", true);
  } finally {
    hideLoading();
  }
}

async function handleDeleteThread(threadId) {
  if (!state.currentProjectId || !threadId) {
    return;
  }
  showLoading("Deleting contact...");
  try {
    await apiFetch(`/api/contacts/${threadId}`, {
      method: "DELETE",
    });
    await refreshCurrentProject(false);
    showToast("Contact deleted.");
  } catch (error) {
    showToast(error.message || "Failed deleting contact", true);
  } finally {
    hideLoading();
  }
}

async function handleSaveEmailThreadLink() {
  const thread = getCurrentThread();
  if (!thread || !state.currentProjectId || !isEmailThread(thread) || isArchivedThread(thread) || !dom.emailThreadLinkInput) {
    return;
  }
  const threadLink = dom.emailThreadLinkInput.value.trim();
  setBusy(dom.saveEmailThreadLinkBtn, true, "Saving...", "Save Link");
  try {
    const payload = await apiFetch(
      `/api/companies/${state.currentProjectId}/contacts/${thread.id}/email-thread-link`,
      {
        method: "PUT",
        body: { thread_link: threadLink || null },
      },
    );
    thread.email_thread_link = payload.thread_link || null;
    await refreshCurrentProject(true);
    showToast(payload.thread_link ? "Email thread link saved." : "Email thread link cleared.");
  } catch (error) {
    showToast(error.message || "Failed saving email thread link", true);
  } finally {
    setBusy(dom.saveEmailThreadLinkBtn, false, "Saving...", "Save Link");
  }
}

function handleDismissEmailThreadLinkPanel() {
  const thread = getCurrentThread();
  if (!thread || !isEmailThread(thread)) {
    return;
  }
  dismissEmailThreadLinkPanel(thread);
  if (dom.emailThreadLinkPanel) {
    dom.emailThreadLinkPanel.classList.add("hidden");
  }
}

function renderChat() {
  if (state.showArchivedThreads) {
    showContactsView();
    renderSidebarFocus();
    return;
  }
  const thread = getCurrentThread();
  if (!thread) {
    showContactsView();
    renderSidebarFocus();
    return;
  }

  showThreadView();
}

function renderThreadSidebar() {
  const project = state.currentProject;
  if (!project || !dom.threadSidebarList) {
    return;
  }

  if (projectIsProcessing(project) && !project.threads.length) {
    dom.threadSidebarList.innerHTML = renderProcessingState(
      "Processing contacts",
      "Wait until the scan finishes before opening a thread.",
    );
    return;
  }

  if (state.showArchivedThreads) {
    dom.threadSidebarList.innerHTML = `<p class="empty-note">Archived contacts are managed from the contacts panel.</p>`;
    return;
  }

  const filteredThreads = getFilteredThreads(project);

  dom.threadSidebarList.innerHTML = filteredThreads
    .map((thread) => {
      const isActive = thread.id === state.currentThreadId ? "active" : "";
      const fullTitle = thread.contact_name || thread.contact_value || "Contact";
      const title = threadDisplayTitle(thread, 56);
      return `
        <button type="button" class="thread-sidebar-item ${isActive}" data-thread-id="${escapeHtml(thread.id)}">
          <div class="thread-line">
            <p class="thread-title" title="${escapeHtml(fullTitle)}">${escapeHtml(title)}</p>
            <div class="thread-line-badges">
              ${renderThreadDoneBadge(thread)}
              ${renderContactPendingDot(thread)}
            </div>
          </div>
          <p class="thread-caption">${escapeHtml(threadMetaLabel(thread))}</p>
          <p class="thread-caption thread-caption-objective">${escapeHtml(threadObjectiveCaption(thread))}</p>
        </button>
      `;
    })
    .join("");

  dom.threadSidebarList.querySelectorAll("[data-thread-id]").forEach((node) => {
    node.addEventListener("click", () => {
      const threadId = node.getAttribute("data-thread-id");
      if (threadId) {
        selectThread(threadId);
      }
    });
  });
}

async function loadProjects() {
  const result = await apiFetch("/api/companies");
  const projects = (Array.isArray(result) ? result : []).map(toProjectViewModel);
  state.projects = sortProjects(projects);
  renderHomeMetrics();
  renderHomeProjects();
  syncProcessingRefreshLoop();
}

async function loadProjectDetail(projectId) {
  const rawDetail = await apiFetch(
    `/api/companies/${projectId}?archived=${state.showArchivedThreads ? "true" : "false"}`,
  );
  clearProjectCeoEmailEditing();
  clearProjectReportScheduleEditing();
  const detail = normalizeCompanyDetail(rawDetail);
  detail.threads = sortThreads(Array.isArray(detail.threads) ? detail.threads : []);
  state.currentProject = detail;
  state.currentProjectId = detail.id;
  setProjectConversationAutomationState(detail.id, detail.conversation_automation_enabled, detail.updated_at);
  setProjectCeoDeliveryState(detail.id, detail.ceo_delivery_enabled, detail.updated_at);
  renderProjectHeader();
  renderThreadList();
  syncProcessingRefreshLoop();
}

async function loadThreadMessages(threadId) {
  if (!state.currentProjectId) {
    return;
  }
  const payload = await apiFetch(`/api/companies/${state.currentProjectId}/contacts/${threadId}/messages`);
  state.currentThreadId = threadId;
  state.threadMessages = payload.messages || [];
  syncThreadLatestFromMessages();
  clearMessageEditing();
  renderThreadList();
  renderChat();
  syncUrlWithUiState();
}

async function loadExistingReport(projectId) {
  try {
    const [reportResponse, pdfModelResponse] = await Promise.all([
      fetchWithAuth(`${state.baseUrl}/api/companies/${projectId}/artifact-report`),
      fetchWithAuth(`${state.baseUrl}/api/companies/${projectId}/artifact-pdf-model`),
    ]);

    let reportPayload = null;
    let pdfModelPayload = null;
    if (reportResponse.status === 200) {
      reportPayload = await reportResponse.json();
    }
    if (pdfModelResponse.status === 200) {
      pdfModelPayload = await pdfModelResponse.json();
    }

    const report = reportPayload?.report || null;
    const pdfModel = pdfModelPayload?.pdf_model || null;
    if (!report && !pdfModel) {
      state.latestReport = null;
      if (state.currentProject) {
        state.currentProject = {
          ...state.currentProject,
          has_report_pdf_model: false,
        };
      }
      syncReportActions();
      return;
    }

    state.latestReport = {
      report,
      pdf_model: pdfModel,
      generated_at: pdfModelPayload?.generated_at || reportPayload?.generated_at || null,
      report_generated_at: reportPayload?.generated_at || null,
      pdf_model_generated_at: pdfModelPayload?.generated_at || null,
    };
    if (state.currentProject) {
      state.currentProject = {
        ...state.currentProject,
        has_report_pdf_model: Boolean(pdfModel),
      };
    }
    syncReportActions();
  } catch {
    state.latestReport = null;
    if (state.currentProject) {
      state.currentProject = {
        ...state.currentProject,
        has_report_pdf_model: false,
      };
    }
    syncReportActions();
  }
}

async function loadCrmThreads({ preserveSelection = true, selectFirstIfNeeded = false } = {}) {
  const payload = await apiFetch("/api/crm/threads");
  applyCrmThreadsPayload(payload, { preserveSelection, selectFirstIfNeeded });
  renderCrmView();
}

async function markCrmThreadRead(threadId) {
  const payload = await apiFetch(`/api/crm/threads/${threadId}/mark-read`, {
    method: "POST",
  });
  upsertCrmThreadSummary({
    ...payload,
    unread_message_count: 0,
  });
  renderCrmView();
}

async function loadCrmThreadDetail(threadId, { markRead = true, syncUrl = true } = {}) {
  const previousThreadId = state.currentCrmThreadId;
  const payload = await apiFetch(`/api/crm/threads/${threadId}`);
  state.currentCrmThreadId = threadId;
  state.currentCrmThread = normalizeCrmThread(payload.thread);
  state.crmMessages = (Array.isArray(payload.messages) ? payload.messages : []).map(normalizeCrmMessage);
  upsertCrmThreadSummary(payload.thread);
  if (previousThreadId !== threadId && dom.crmReplyInput) {
    dom.crmReplyInput.value = "";
  }
  renderCrmView();
  if (syncUrl) {
    syncUrlWithUiState();
  }
  if (markRead && state.currentCrmThread.unread_message_count > 0) {
    void markCrmThreadRead(threadId).catch(() => {
      // Read tracking is best-effort; the next refresh will reconcile counters.
    });
  }
}

function stopCrmRefreshLoop() {
  if (state.crmRefreshTimer) {
    window.clearTimeout(state.crmRefreshTimer);
    state.crmRefreshTimer = null;
  }
}

async function refreshCrmInbox({ includeThreadDetail = currentSectionIsCrm() } = {}) {
  await loadCrmThreads({
    preserveSelection: true,
    selectFirstIfNeeded: currentSectionIsCrm(),
  });
  if (includeThreadDetail && state.currentCrmThreadId) {
    await loadCrmThreadDetail(state.currentCrmThreadId, {
      markRead: false,
      syncUrl: false,
    });
  }
  renderCrmView();
  syncUrlWithUiState();
}

function syncCrmRefreshLoop() {
  if (state.crmRefreshTimer) {
    return;
  }
  state.crmRefreshTimer = window.setTimeout(async () => {
    state.crmRefreshTimer = null;
    try {
      await refreshCrmInbox({ includeThreadDetail: currentSectionIsCrm() });
    } catch {
      // CRM polling is best-effort; the next tick will retry.
    } finally {
      syncCrmRefreshLoop();
    }
  }, CRM_REFRESH_INTERVAL_MS);
}

async function handleToggleProjectConversationAutomation() {
  if (!state.currentProjectId || !state.currentProject || !dom.projectAiAutomationToggle) {
    return;
  }

  const companyId = state.currentProjectId;
  if (state.pendingAiAutomationCompanyId === companyId) {
    return;
  }

  const previousValue = projectConversationAutomationEnabled(state.currentProject);
  const nextValue = Boolean(dom.projectAiAutomationToggle.checked);
  if (nextValue === previousValue) {
    syncProjectAutomationControls();
    return;
  }

  const optimisticUpdatedAt = new Date().toISOString();
  state.pendingAiAutomationCompanyId = companyId;
  setProjectConversationAutomationState(companyId, nextValue, optimisticUpdatedAt);
  renderProjectHeader();
  renderHomeProjects();

  try {
    const response = await apiFetch(`/api/companies/${companyId}`, {
      method: "PUT",
      body: {
        conversation_automation_enabled: nextValue,
      },
    });
    setProjectConversationAutomationState(
      companyId,
      Boolean(response?.conversation_automation_enabled),
      response?.updated_at || optimisticUpdatedAt,
    );
    showToast(
      Boolean(response?.conversation_automation_enabled)
        ? "Conversation automation authorized for this company."
        : "Conversation automation blocked for this company.",
    );
  } catch (error) {
    setProjectConversationAutomationState(companyId, previousValue);
    showToast(error.message || "Failed updating conversation automation setting", true);
  } finally {
    state.pendingAiAutomationCompanyId = null;
    renderProjectHeader();
    renderHomeProjects();
  }
}


async function handleToggleProjectCeoDelivery() {
  if (!state.currentProjectId || !state.currentProject || !dom.projectCeoDeliveryToggle) {
    return;
  }

  const companyId = state.currentProjectId;
  if (state.pendingCeoDeliveryCompanyId === companyId) {
    return;
  }

  const previousValue = projectCeoDeliveryEnabled(state.currentProject);
  const nextValue = Boolean(dom.projectCeoDeliveryToggle.checked);
  if (nextValue === previousValue) {
    syncProjectAutomationControls();
    return;
  }

  const optimisticUpdatedAt = new Date().toISOString();
  state.pendingCeoDeliveryCompanyId = companyId;
  setProjectCeoDeliveryState(companyId, nextValue, optimisticUpdatedAt);
  renderProjectHeader();
  renderHomeProjects();

  try {
    const response = await apiFetch(`/api/companies/${companyId}`, {
      method: "PUT",
      body: {
        ceo_delivery_enabled: nextValue,
      },
    });
    setProjectCeoDeliveryState(
      companyId,
      Boolean(response?.ceo_delivery_enabled),
      response?.updated_at || optimisticUpdatedAt,
    );
    showToast(
      Boolean(response?.ceo_delivery_enabled)
        ? "CEO audit delivery enabled for this company."
        : "CEO audit delivery blocked for this company.",
    );
  } catch (error) {
    setProjectCeoDeliveryState(companyId, previousValue);
    showToast(error.message || "Failed updating CEO delivery setting", true);
  } finally {
    state.pendingCeoDeliveryCompanyId = null;
    renderProjectHeader();
    renderHomeProjects();
  }
}

function handleEditProjectCeoEmail() {
  if (!state.currentProject || state.pendingCeoEmailCompanyId === state.currentProject.id) {
    return;
  }
  state.editingProjectCeoEmail = true;
  state.editingProjectCeoEmailValue = String(state.currentProject.ceo_email || "").trim();
  renderProjectHeader();
}

async function handleCopyProjectCeoEmail() {
  if (!state.currentProject || !dom.projectCeoEmailCopyBtn) {
    return;
  }
  const ceoEmail = String(state.currentProject.ceo_email || "").trim();
  if (!ceoEmail) {
    return;
  }
  try {
    await copyTextToClipboard(ceoEmail);
    showCopiedEffect(dom.projectCeoEmailCopyBtn);
    showToast("CEO email copied.");
  } catch {
    showToast("Clipboard copy failed.", true);
  }
}

function handleCancelProjectCeoEmailEdit() {
  clearProjectCeoEmailEditing();
  renderProjectHeader();
}

async function handleSaveProjectCeoEmail() {
  if (!state.currentProject || !dom.projectCeoEmailInput) {
    return;
  }

  const companyId = state.currentProject.id;
  if (state.pendingCeoEmailCompanyId === companyId) {
    return;
  }

  const nextEmail = String(dom.projectCeoEmailInput.value || "").trim();
  if (nextEmail && !dom.projectCeoEmailInput.checkValidity()) {
    dom.projectCeoEmailInput.reportValidity();
    return;
  }

  const optimisticUpdatedAt = new Date().toISOString();
  state.pendingCeoEmailCompanyId = companyId;
  state.editingProjectCeoEmailValue = nextEmail;
  renderProjectHeader();
  renderHomeProjects();

  try {
    const response = await apiFetch(`/api/companies/${companyId}`, {
      method: "PUT",
      body: {
        ceo_email: nextEmail || null,
      },
    });
    setProjectCeoEmailState(companyId, response?.ceo_email || null, response?.updated_at || optimisticUpdatedAt);
    clearProjectCeoEmailEditing();
    showToast(response?.ceo_email ? "CEO email updated." : "CEO email cleared.");
  } catch (error) {
    showToast(error.message || "Failed updating CEO email", true);
  } finally {
    state.pendingCeoEmailCompanyId = null;
    renderProjectHeader();
    renderHomeProjects();
  }
}

function handleEditProjectReportSchedule() {
  if (!state.currentProject || state.pendingProjectScheduleCompanyId === state.currentProject.id) {
    return;
  }
  const parts = splitReportWindowMinutes(state.currentProject.report_window_minutes);
  state.editingProjectReportSchedule = true;
  state.editingProjectReportWindowHoursValue = String(parts.hours);
  state.editingProjectReportWindowMinutesValue = String(parts.minutes);
  state.editingProjectScheduledSendValue = formatGmtMinusThreeDateTimeLocalValue(
    computeProjectReportDeadline(state.currentProject),
  );
  renderProjectHeader();
}

function handleCancelProjectReportScheduleEdit() {
  clearProjectReportScheduleEditing();
  renderProjectHeader();
}

async function handleSaveProjectReportSchedule() {
  if (
    !state.currentProject ||
    !dom.projectReportWindowHoursInput ||
    !dom.projectReportWindowMinutesInput ||
    !dom.projectScheduledSendInput
  ) {
    return;
  }

  const companyId = state.currentProject.id;
  if (state.pendingProjectScheduleCompanyId === companyId) {
    return;
  }

  const reportWindowHours = Number.parseInt(String(dom.projectReportWindowHoursInput.value || "0").trim(), 10);
  if (!Number.isFinite(reportWindowHours) || reportWindowHours < 0 || !dom.projectReportWindowHoursInput.checkValidity()) {
    dom.projectReportWindowHoursInput.reportValidity();
    return;
  }
  const reportWindowMinutesRemainder = Number.parseInt(String(dom.projectReportWindowMinutesInput.value || "0").trim(), 10);
  if (
    !Number.isFinite(reportWindowMinutesRemainder) ||
    reportWindowMinutesRemainder < 0 ||
    !dom.projectReportWindowMinutesInput.checkValidity()
  ) {
    dom.projectReportWindowMinutesInput.reportValidity();
    return;
  }
  const reportWindowMinutes = (reportWindowHours * 60) + reportWindowMinutesRemainder;
  if (reportWindowMinutes < 1) {
    dom.projectReportWindowMinutesInput.setCustomValidity("Use at least 1 minute.");
    dom.projectReportWindowMinutesInput.reportValidity();
    dom.projectReportWindowMinutesInput.setCustomValidity("");
    return;
  }

  const scheduledSendValue = String(dom.projectScheduledSendInput.value || "").trim();
  const scheduledSendAt = parseGmtMinusThreeDateTimeLocalValue(scheduledSendValue);
  if (!scheduledSendAt || !dom.projectScheduledSendInput.checkValidity()) {
    dom.projectScheduledSendInput.reportValidity();
    return;
  }

  const optimisticUpdatedAt = new Date().toISOString();
  state.pendingProjectScheduleCompanyId = companyId;
  state.editingProjectReportWindowHoursValue = String(reportWindowHours);
  state.editingProjectReportWindowMinutesValue = String(reportWindowMinutesRemainder);
  state.editingProjectScheduledSendValue = scheduledSendValue;
  renderProjectHeader();
  renderHomeProjects();

  try {
    const response = await apiFetch(`/api/companies/${companyId}/report-schedule`, {
      method: "PUT",
      body: {
        report_window_minutes: reportWindowMinutes,
        scheduled_send_at: scheduledSendAt.toISOString(),
      },
    });
    setProjectReportScheduleState(
      companyId,
      response?.report_window_minutes,
      response?.scheduled_send_at,
      response?.updated_at || optimisticUpdatedAt,
    );
    clearProjectReportScheduleEditing();
    showToast("Report schedule updated.");
  } catch (error) {
    showToast(error.message || "Failed updating report schedule", true);
  } finally {
    state.pendingProjectScheduleCompanyId = null;
    renderProjectHeader();
    renderHomeProjects();
  }
}

async function handleRescanCompany() {
  if (!state.currentProjectId || !state.currentProject) {
    showToast("Open a company first.", true);
    return;
  }
  if (projectIsProcessing(state.currentProject)) {
    showToast("Wait for the current company scan to finish first.", true);
    return;
  }
  if (!projectCanRescan(state.currentProject)) {
    showToast("Re-scan is only available when the company has 0 contacts.", true);
    return;
  }

  const companyId = state.currentProjectId;
  const optimisticUpdatedAt = new Date().toISOString();
  setBusy(dom.rescanCompanyBtn, true, "Rescanning...", "Re-scan Company");

  try {
    const response = await apiFetch(`/api/companies/${companyId}/rescan`, {
      method: "POST",
    });
    if (!response?.task_id) {
      throw new Error("Failed queueing company re-scan.");
    }
    markProjectScanStarted(companyId, response.task_id, optimisticUpdatedAt);
    renderProjectHeader();
    renderHomeMetrics();
    renderHomeProjects();
    syncProcessingRefreshLoop();
    showToast("Company re-scan started. Running contact discovery again...");
    void finalizeRescannedCompany(companyId, response.task_id);
  } catch (error) {
    showToast(error.message || "Failed starting company re-scan", true);
  } finally {
    setBusy(dom.rescanCompanyBtn, false, "Rescanning...", "Re-scan Company");
  }
}

function parseOptionalBooleanFilter(value) {
  if (value === "true") {
    return true;
  }
  if (value === "false") {
    return false;
  }
  return null;
}

function buildContadoresQueryParams() {
  const params = new URLSearchParams();
  if (state.contadoresQuery) {
    params.set("query", state.contadoresQuery);
  }
  if (state.contadoresStageFilter) {
    params.set("stage", state.contadoresStageFilter);
  }
  if (state.contadoresPlatformFilter) {
    params.set("platform", state.contadoresPlatformFilter);
  }
  if (state.contadoresManualReplyFilter) {
    params.set("manual_reply_status", state.contadoresManualReplyFilter);
  }
  if (state.contadoresStrategyStepFilter) {
    params.set("strategy_step", state.contadoresStrategyStepFilter);
  }
  if (state.contadoresStrategyIdFilter) {
    params.set("strategy_id", state.contadoresStrategyIdFilter);
  }
  const booked = parseOptionalBooleanFilter(state.contadoresBookedFilter);
  const needsHuman = parseOptionalBooleanFilter(state.contadoresNeedsHumanFilter);
  const archived = parseOptionalBooleanFilter(state.contadoresArchivedFilter);
  if (booked !== null) {
    params.set("booked", booked ? "true" : "false");
  }
  if (needsHuman !== null) {
    params.set("needs_human", needsHuman ? "true" : "false");
  }
  if (archived !== null) {
    params.set("archived", archived ? "true" : "false");
  }
  return params;
}

async function loadContadoresOverview({ preserveSelection = true } = {}) {
  const params = buildContadoresQueryParams();
  const [response, strategyStats] = await Promise.all([
    apiFetch(`/api/contadores/leads${params.toString() ? `?${params.toString()}` : ""}`),
    apiFetch("/api/contadores/strategy-stats"),
  ]);
  state.contadoresConfig = response?.config || null;
  state.contadoresMetrics = response?.metrics || null;
  state.contadoresStrategyStats = Array.isArray(strategyStats?.items) ? strategyStats.items : [];
  state.contadoresLeads = Array.isArray(response?.leads) ? response.leads : [];
  if (preserveSelection && state.currentContadoresLeadId) {
    const stillExists = state.contadoresLeads.some((lead) => lead.id === state.currentContadoresLeadId);
    if (!stillExists) {
      state.currentContadoresLeadId = state.contadoresLeads[0]?.id || null;
    }
  } else {
    state.currentContadoresLeadId = state.contadoresLeads[0]?.id || null;
  }
  renderContadoresView();
}

async function refreshContadoresSelection() {
  await loadContadoresOverview({ preserveSelection: true });
  if (state.currentContadoresLeadId) {
    await loadContadoresLeadDetail(state.currentContadoresLeadId);
  }
}

async function loadContadoresLeadDetail(leadId) {
  if (!leadId) {
    state.currentContadoresLeadId = null;
    state.currentContadoresLead = null;
    state.contadoresMessages = [];
    state.contadoresEvents = [];
    renderContadoresView();
    syncUrlWithUiState();
    return;
  }
  const response = await apiFetch(`/api/contadores/leads/${leadId}`);
  state.currentContadoresLeadId = response?.lead?.id || leadId;
  state.currentContadoresLead = response?.lead || null;
  state.contadoresMessages = Array.isArray(response?.messages) ? response.messages : [];
  state.contadoresEvents = Array.isArray(response?.events) ? response.events : [];
  if (response?.config) {
    state.contadoresConfig = response.config;
  }
  if (state.currentContadoresLead) {
    state.contadoresLeads = state.contadoresLeads.map((lead) =>
      lead.id === state.currentContadoresLead.id ? { ...lead, ...state.currentContadoresLead } : lead,
    );
  }
  renderContadoresView();
  syncUrlWithUiState();
}

async function openContadoresSection({ leadId = null, showLoadingOverlay = true } = {}) {
  if (showLoadingOverlay) {
    showLoading("Loading Contadores...");
  }
  try {
    state.currentSection = "contadores";
    setView(state.currentView);
    await loadContadoresOverview({ preserveSelection: true });
    const resolvedLeadId =
      (leadId && state.contadoresLeads.some((lead) => lead.id === leadId) ? leadId : null) ||
      state.currentContadoresLeadId;
    if (resolvedLeadId) {
      await loadContadoresLeadDetail(resolvedLeadId);
    } else {
      renderContadoresView();
      syncUrlWithUiState();
    }
  } finally {
    if (showLoadingOverlay) {
      hideLoading();
    }
  }
}

async function openContadoresLead(leadId) {
  if (!leadId) {
    return;
  }
  showLoading("Loading lead...");
  try {
    state.currentSection = "contadores";
    setView(state.currentView);
    await loadContadoresLeadDetail(leadId);
  } catch (error) {
    showToast(error.message || "Failed loading lead", true);
  } finally {
    hideLoading();
  }
}

async function saveContadoresConfig() {
  if (!state.contadoresConfig) {
    return;
  }
  setBusy(dom.saveContadoresConfigBtn, true, "Saving...", "Save Config");
  try {
    const response = await apiFetch("/api/contadores/config", {
      method: "PUT",
      body: {
        enabled: Boolean(dom.contadoresEnabledToggle?.checked),
        loom_url: dom.contadoresLoomUrlInput?.value || "",
        calendly_base_url: dom.contadoresCalendlyUrlInput?.value || "",
        alert_emails: String(dom.contadoresAlertEmailsInput?.value || "")
          .split(",")
          .map((item) => item.trim())
          .filter((item) => item),
      },
    });
    state.contadoresConfig = response || null;
    renderContadoresView();
    showToast("Contadores config saved.");
    await loadContadoresOverview({ preserveSelection: true });
  } catch (error) {
    showToast(error.message || "Failed saving config", true);
  } finally {
    setBusy(dom.saveContadoresConfigBtn, false, "Saving...", "Save Config");
  }
}

async function runContadoresQuickAction(action, button) {
  const lead = getCurrentContadoresLead();
  if (!lead) {
    showToast("Select a Contadores lead first.", true);
    return;
  }
  setBusy(button, true, "Running...", button?.textContent || "Run");
  try {
    await apiFetch(`/api/contadores/leads/${lead.id}/actions/${action}`, {
      method: "POST",
    });
    await loadContadoresOverview({ preserveSelection: true });
    await loadContadoresLeadDetail(lead.id);
    showToast(contadoresQuickActionSuccessMessage(action));
  } catch (error) {
    showToast(error.message || `Failed running action ${action}`, true);
  } finally {
    setBusy(button, false, "Running...", button?.dataset?.label || button?.textContent || "Run");
  }
}

async function deleteContadoresLead(button) {
  const lead = getCurrentContadoresLead();
  if (!lead) {
    showToast("Select a Contadores lead first.", true);
    return;
  }
  const leadName = String(lead.full_name || lead.phone || lead.id || "this chat").trim();
  if (!confirm(`Are you sure you want to delete "${leadName}"? This action cannot be undone.`)) {
    return;
  }
  setBusy(button, true, "Deleting...", button?.textContent || "Delete chat");
  try {
    await apiFetch(`/api/contadores/leads/${lead.id}`, {
      method: "DELETE",
    });
    state.currentContadoresLeadId = null;
    await loadContadoresOverview({ preserveSelection: false });
    if (state.currentContadoresLeadId) {
      await loadContadoresLeadDetail(state.currentContadoresLeadId);
    } else {
      renderContadoresView();
    }
    showToast("Chat deleted.");
  } catch (error) {
    showToast(error.message || "Failed deleting chat", true);
  } finally {
    setBusy(button, false, "Deleting...", button?.dataset?.label || button?.textContent || "Delete chat");
  }
}

function openContadoresSendModal() {
  const lead = getCurrentContadoresLead();
  if (!lead) {
    showToast("Select a Contadores lead first.", true);
    return;
  }
  const modal = document.getElementById("ctSendModal");
  if (!modal) {
    return;
  }
  modal.classList.add("open");
  modal.setAttribute("aria-hidden", "false");
  const textarea = document.getElementById("ctSendCustomText");
  if (textarea) {
    textarea.value = "";
  }
  const customRadio = modal.querySelector('input[name="ctSendKind"][value="custom"]');
  if (customRadio) {
    customRadio.checked = true;
  }
  syncContadoresSendModalField();
  window.requestAnimationFrame(() => textarea?.focus());
}

function closeContadoresSendModal() {
  const modal = document.getElementById("ctSendModal");
  if (!modal) {
    return;
  }
  modal.classList.remove("open");
  modal.setAttribute("aria-hidden", "true");
}

function contadoresSendKindPausesAutomation(kind) {
  return String(kind || "custom") !== "send-calendly";
}

function syncContadoresSendModalField() {
  const selected = document.querySelector('input[name="ctSendKind"]:checked');
  const kind = String(selected?.value || "custom");
  const wrap = document.getElementById("ctSendCustomWrap");
  const modal = document.getElementById("ctSendModal");
  const warning = modal?.querySelector(".ct-modal-warning");
  const confirmBtn = document.getElementById("ctSendConfirmBtn");
  if (!wrap) {
    return;
  }
  const isCustom = kind === "custom";
  const pausesAutomation = contadoresSendKindPausesAutomation(kind);
  wrap.hidden = !isCustom;
  if (warning) {
    warning.textContent = pausesAutomation
      ? "Heads up: sending this pauses the bot for this lead. You can resume automation after."
      : "Heads up: sending Calendly marks the lead as Calendly sent and clears the manual handoff.";
  }
  if (confirmBtn) {
    confirmBtn.textContent = pausesAutomation ? "Send and pause automation" : "Send and mark Calendly sent";
  }
}

async function submitContadoresSendModal() {
  const lead = getCurrentContadoresLead();
  if (!lead) {
    showToast("Select a Contadores lead first.", true);
    return;
  }
  const selected = document.querySelector('input[name="ctSendKind"]:checked');
  const kind = String(selected?.value || "custom");
  const confirmBtn = document.getElementById("ctSendConfirmBtn");
  const pausesAutomation = contadoresSendKindPausesAutomation(kind);
  const idleLabel = pausesAutomation ? "Send and pause automation" : "Send and mark Calendly sent";
  setBusy(confirmBtn, true, "Sending...", idleLabel);
  try {
    if (kind === "custom") {
      const textarea = document.getElementById("ctSendCustomText");
      const text = String(textarea?.value || "").trim();
      if (!text) {
        showToast("Write the manual message first.", true);
        return;
      }
      await apiFetch(`/api/contadores/leads/${lead.id}/messages/manual`, {
        method: "POST",
        body: { text },
      });
    } else {
      await apiFetch(`/api/contadores/leads/${lead.id}/actions/${kind}`, {
        method: "POST",
      });
    }
    closeContadoresSendModal();
    await loadContadoresOverview({ preserveSelection: true });
    await loadContadoresLeadDetail(lead.id);
    showToast(
      pausesAutomation
        ? "Message queued. Automation paused for this lead."
        : "Calendly sequence queued. Lead moved back to Calendly sent."
    );
  } catch (error) {
    showToast(error.message || "Failed sending message", true);
  } finally {
    setBusy(confirmBtn, false, "Sending...", idleLabel);
  }
}

async function resumeContadoresAutomation() {
  const lead = getCurrentContadoresLead();
  if (!lead) {
    return;
  }
  const resumeBtn = document.getElementById("ctResumeBtn");
  setBusy(resumeBtn, true, "Resuming...", "Resume automation");
  try {
    await apiFetch(`/api/contadores/leads/${lead.id}/resume-automation`, {
      method: "POST",
    });
    await loadContadoresOverview({ preserveSelection: true });
    await loadContadoresLeadDetail(lead.id);
    showToast("Automation resumed.");
  } catch (error) {
    showToast(error.message || "Failed resuming automation", true);
  } finally {
    setBusy(resumeBtn, false, "Resuming...", "Resume automation");
  }
}

function openAuditsSection() {
  state.currentSection = "audits";
  setView(state.currentProjectId ? "project" : "home");
  syncUrlWithUiState();
}

async function openCrmSection({ threadId = null, showLoadingOverlay = true } = {}) {
  if (showLoadingOverlay) {
    showLoading("Loading CRM...");
  }
  try {
    state.currentSection = "crm";
    setView(state.currentView);
    await loadCrmThreads({
      preserveSelection: true,
      selectFirstIfNeeded: !threadId && !isCompactCrmViewport(),
    });
    const resolvedThreadId =
      (threadId && state.crmThreads.some((thread) => thread.id === threadId) ? threadId : null) ||
      state.currentCrmThreadId;
    if (resolvedThreadId) {
      setCrmMobilePane("detail");
      await loadCrmThreadDetail(resolvedThreadId);
    } else {
      setCrmMobilePane("list");
      renderCrmView();
      syncUrlWithUiState();
    }
  } finally {
    if (showLoadingOverlay) {
      hideLoading();
    }
  }
}

async function openCrmThread(threadId) {
  if (!threadId) {
    return;
  }
  showLoading("Loading CRM thread...");
  try {
    state.currentSection = "crm";
    setCrmMobilePane("detail");
    setView(state.currentView);
    await loadCrmThreadDetail(threadId);
  } catch (error) {
    showToast(error.message || "Failed loading CRM thread", true);
  } finally {
    hideLoading();
  }
}

async function handleCrmReplySubmit(event) {
  event.preventDefault();
  const thread = getCurrentCrmThread();
  if (!thread || !dom.crmReplyInput) {
    showToast("Select a CRM thread first.", true);
    return;
  }

  const body = String(dom.crmReplyInput.value || "").trim();
  if (!body) {
    showToast("Reply body is required.", true);
    return;
  }
  if (state.pendingCrmReplyThreadId === thread.id) {
    return;
  }

  state.pendingCrmReplyThreadId = thread.id;
  syncCrmComposerState();
  try {
    const payload = await apiFetch(`/api/crm/threads/${thread.id}/reply`, {
      method: "POST",
      body: { body },
    });
    const message = normalizeCrmMessage(payload);
    state.crmMessages = [...state.crmMessages, message];
    upsertCrmThreadSummary({
      ...thread,
      last_message_preview: buildCrmMessagePreview(message.body),
      last_message_direction: message.direction,
      last_message_status: message.status,
      last_message_at: crmMessageTimestamp(message),
      updated_at: crmMessageTimestamp(message) || new Date().toISOString(),
    });
    dom.crmReplyInput.value = "";
    renderCrmView();
    syncUrlWithUiState();
    showToast("Reply queued. The bot will send it on the next tick.");
  } catch (error) {
    showToast(error.message || "Failed queueing CRM reply", true);
  } finally {
    state.pendingCrmReplyThreadId = null;
    syncCrmComposerState();
  }
}

async function openProject(projectId) {
  showLoading("Loading company...");
  try {
    state.currentSection = "audits";
    setView("project");
    state.showArchivedThreads = false;
    state.threadQuery = "";
    dom.threadSearchInput.value = "";
    syncArchivedContactsToggleButton();

    await loadProjectDetail(projectId);
    state.currentThreadId = null;
    state.threadMessages = [];
    state.lastRenderedThreadId = null;
    state.lastRenderedMessageCount = 0;
    state.latestReport = null;
    syncReportActions();

    renderChat();
    syncUrlWithUiState();
    await loadExistingReport(projectId);
  } catch (error) {
    showToast(error.message || "Failed loading company", true);
    setView("home");
  } finally {
    hideLoading();
  }
}

async function refreshCurrentProject(keepThread = true) {
  if (!state.currentProjectId) {
    return;
  }

  const preferredThread = keepThread && !state.showArchivedThreads ? state.currentThreadId : null;
  await loadProjectDetail(state.currentProjectId);

  const hasPreferredThread =
    Boolean(preferredThread) &&
    state.currentProject.threads.some((thread) => thread.id === preferredThread);

  state.currentThreadId = hasPreferredThread ? preferredThread : null;
  state.threadMessages = [];
  state.lastRenderedThreadId = null;
  state.lastRenderedMessageCount = 0;

  if (state.currentThreadId) {
    await loadThreadMessages(state.currentThreadId);
  } else {
    renderChat();
  }

  await loadExistingReport(state.currentProjectId);
  renderHomeMetrics();
  renderHomeProjects();
  syncUrlWithUiState();
  syncProcessingRefreshLoop();
}

async function selectThread(threadId) {
  if (!state.currentProjectId || state.showArchivedThreads) {
    return;
  }
  if (state.currentThreadId === threadId && state.threadMessages.length) {
    return;
  }

  showLoading("Loading contact...");
  try {
    await loadThreadMessages(threadId);
  } catch (error) {
    showToast(error.message || "Failed loading contact", true);
  } finally {
    hideLoading();
  }
}

async function restoreUiStateFromUrl() {
  const uiState = parseUiStateFromUrl();
  if (uiState.section === "crm") {
    try {
      await openCrmSection({
        threadId: uiState.crmThreadId,
        showLoadingOverlay: false,
      });
    } catch (error) {
      showToast(error.message || "Failed restoring CRM view", true);
      openAuditsSection();
    }
    syncUrlWithUiState();
    return;
  }

  if (uiState.section === "contadores") {
    try {
      await openContadoresSection({
        leadId: uiState.contadoresLeadId,
        showLoadingOverlay: false,
      });
    } catch (error) {
      showToast(error.message || "Failed restoring Contadores view", true);
      openAuditsSection();
    }
    syncUrlWithUiState();
    return;
  }

  if (!uiState.companyId) {
    openAuditsSection();
    syncUrlWithUiState();
    return;
  }

  const projectExists = state.projects.some((project) => project.id === uiState.companyId);
  if (!projectExists) {
    openAuditsSection();
    resetProjectSelection();
    syncUrlWithUiState();
    return;
  }

  await openProject(uiState.companyId);

  if (uiState.archived) {
    state.showArchivedThreads = true;
    state.currentThreadId = null;
    state.threadMessages = [];
    state.lastRenderedThreadId = null;
    state.lastRenderedMessageCount = 0;
    clearMessageEditing();
    try {
      await refreshCurrentProject(false);
    } catch (error) {
      showToast(error.message || "Failed restoring archived contacts view", true);
    }
    syncUrlWithUiState();
    return;
  }

  const contactId = uiState.contactId;
  if (!contactId) {
    syncUrlWithUiState();
    return;
  }

  const contactExists = state.currentProject?.threads?.some((thread) => thread.id === contactId);
  if (!contactExists) {
    state.currentThreadId = null;
    state.threadMessages = [];
    state.lastRenderedThreadId = null;
    state.lastRenderedMessageCount = 0;
    clearMessageEditing();
    renderChat();
    renderThreadList();
    renderThreadSidebar();
    renderSidebarFocus();
    syncUrlWithUiState();
    return;
  }

  await loadThreadMessages(contactId);
  syncUrlWithUiState();
}

let createModalTrigger = null;
let manualContactModalTrigger = null;

function createProjectSubmitIdleLabel() {
  return state.createScanMode === "batch" ? "Queue Batch Scan" : "Scan Company";
}

function syncCreateBatchFilesSummary() {
  if (!dom.createBatchFilesSummary || !dom.createBatchFilesInput) {
    return;
  }
  const files = Array.from(dom.createBatchFilesInput.files || []);
  if (!files.length) {
    dom.createBatchFilesSummary.textContent = "No files selected.";
    return;
  }
  if (files.length === 1) {
    dom.createBatchFilesSummary.textContent = files[0].name;
    return;
  }
  dom.createBatchFilesSummary.textContent = `${files.length} files selected`;
}

function setCreateScanMode(mode) {
  state.createScanMode = mode === "batch" ? "batch" : "single";
  const isBatch = state.createScanMode === "batch";
  dom.createScanModeSingleBtn?.classList.toggle("active", !isBatch);
  dom.createScanModeSingleBtn?.setAttribute("aria-pressed", String(!isBatch));
  dom.createScanModeBatchBtn?.classList.toggle("active", isBatch);
  dom.createScanModeBatchBtn?.setAttribute("aria-pressed", String(isBatch));
  dom.createSingleScanFields?.classList.toggle("hidden", isBatch);
  dom.createBatchScanFields?.classList.toggle("hidden", !isBatch);
  if (dom.createUrlInput) {
    dom.createUrlInput.disabled = isBatch;
  }
  if (dom.createCeoEmailInput) {
    dom.createCeoEmailInput.disabled = isBatch;
  }
  if (dom.submitCreateProjectBtn) {
    dom.submitCreateProjectBtn.textContent = createProjectSubmitIdleLabel();
  }
  syncCreateBatchFilesSummary();
}

function getCreateProjectSharedSettings() {
  const parsedReportWindowHours = Number.parseInt(String(dom.createReportWindowHoursInput?.value || "24").trim(), 10);
  const parsedReportWindowMinutes = Number.parseInt(String(dom.createReportWindowMinutesInput?.value || "0").trim(), 10);
  const reportWindowHours = Number.isFinite(parsedReportWindowHours) && parsedReportWindowHours >= 0
    ? parsedReportWindowHours
    : 24;
  const reportWindowMinutesRemainder = Number.isFinite(parsedReportWindowMinutes) && parsedReportWindowMinutes >= 0
    ? parsedReportWindowMinutes
    : 0;
  const reportWindowMinutes = Math.max(1, (reportWindowHours * 60) + reportWindowMinutesRemainder);
  return {
    objective: dom.createObjectiveInput.value.trim() || null,
    tags: parseProjectTagsInput(dom.createTagsInput?.value || ""),
    report_window_minutes: reportWindowMinutes,
    conversation_automation_enabled: Boolean(dom.createConversationAutomationToggle?.checked),
    ceo_delivery_enabled: Boolean(dom.createCeoDeliveryToggle?.checked),
  };
}

function openCreateProjectModal(event) {
  if (dom.createProjectModal.open) {
    return;
  }
  createModalTrigger = event?.currentTarget || document.activeElement;
  dom.createProjectModal.showModal();
  setCreateScanMode(state.createScanMode);
  window.setTimeout(() => {
    if (state.createScanMode === "batch") {
      dom.createBatchTextInput?.focus();
      return;
    }
    dom.createUrlInput?.focus();
  }, 0);
}

function closeCreateProjectModal() {
  if (!dom.createProjectModal.open) {
    return;
  }
  dom.createProjectModal.close();
  dom.createProjectForm.reset();
  if (dom.createDevScanDetails) {
    dom.createDevScanDetails.open = false;
  }
  setCreateScanMode("single");
  if (createModalTrigger instanceof HTMLElement) {
    createModalTrigger.focus();
    createModalTrigger = null;
  }
}

function syncManualContactValuePlaceholder() {
  if (!dom.manualContactTypeInput || !dom.manualContactValueInput) {
    return;
  }
  const type = String(dom.manualContactTypeInput.value || "").trim().toLowerCase();
  dom.manualContactValueInput.placeholder =
    type === "whatsapp" ? "+5491155557777" : "name@company.com";
}

function openManualContactModal(event) {
  if (!state.currentProjectId || !dom.manualContactModal || !dom.manualContactForm) {
    showToast("Open a company first.", true);
    return;
  }
  if (projectIsProcessing(state.currentProject)) {
    showToast("Wait for the company scan to finish before adding contacts.", true);
    return;
  }
  if (dom.manualContactModal.open) {
    return;
  }
  manualContactModalTrigger = event?.currentTarget || document.activeElement;
  dom.manualContactForm.reset();
  syncManualContactValuePlaceholder();
  dom.manualContactModal.showModal();
  window.setTimeout(() => dom.manualContactTypeInput?.focus(), 0);
}

function closeManualContactModal() {
  if (!dom.manualContactModal || !dom.manualContactForm || !dom.manualContactModal.open) {
    return;
  }
  dom.manualContactModal.close();
  dom.manualContactForm.reset();
  if (manualContactModalTrigger instanceof HTMLElement) {
    manualContactModalTrigger.focus();
  }
  manualContactModalTrigger = null;
}

async function handleCreateManualContact(event) {
  event.preventDefault();
  if (!state.currentProjectId) {
    showToast("Open a company first.", true);
    return;
  }
  if (projectIsProcessing(state.currentProject)) {
    showToast("Wait for the company scan to finish before adding contacts.", true);
    return;
  }
  if (
    !dom.manualContactTypeInput ||
    !dom.manualContactValueInput ||
    !dom.manualContactObjectiveInput ||
    !dom.manualContactNotesInput ||
    !dom.manualContactAdditionalInfoInput ||
    !dom.submitManualContactBtn
  ) {
    return;
  }

  const contactType = String(dom.manualContactTypeInput.value || "").trim().toLowerCase();
  const contactValue = dom.manualContactValueInput.value.trim();
  const contactObjective = dom.manualContactObjectiveInput.value.trim();
  if (!contactValue) {
    showToast("Contact value is required.", true);
    return;
  }
  if (!contactObjective) {
    showToast("Contact objective is required.", true);
    return;
  }

  const createPayload = {
    type: contactType,
    value: contactValue,
    objective: contactObjective,
    notes: dom.manualContactNotesInput.value.trim() || null,
    additional_info: dom.manualContactAdditionalInfoInput.value.trim() || null,
  };
  const companyId = state.currentProjectId;

  setBusy(dom.submitManualContactBtn, true, "Creating...", "Create Contact");
  try {
    const created = await apiFetch(`/api/companies/${companyId}/contacts`, {
      method: "POST",
      body: createPayload,
    });

    closeManualContactModal();
    if (state.currentProjectId === companyId) {
      try {
        await refreshCurrentProject(false);
      } catch (refreshError) {
        showToast(refreshError.message || "Contact saved, but company refresh failed.", true);
      }
    }

    showToast(created.created ? "Contact created." : "Contact already exists.");
  } catch (error) {
    showToast(error.message || "Failed creating manual contact", true);
  } finally {
    setBusy(dom.submitManualContactBtn, false, "Creating...", "Create Contact");
  }
}

async function handleCreateProject(event) {
  event.preventDefault();
  if (dom.createReportWindowHoursInput && !dom.createReportWindowHoursInput.checkValidity()) {
    dom.createReportWindowHoursInput.reportValidity();
    return;
  }
  if (dom.createReportWindowMinutesInput && !dom.createReportWindowMinutesInput.checkValidity()) {
    dom.createReportWindowMinutesInput.reportValidity();
    return;
  }
  const requestedHours = Number.parseInt(String(dom.createReportWindowHoursInput?.value || "0").trim(), 10);
  const requestedRemainderMinutes = Number.parseInt(String(dom.createReportWindowMinutesInput?.value || "0").trim(), 10);
  const requestedMinutes = (
    (Number.isFinite(requestedHours) ? requestedHours : 0) * 60
  ) + (Number.isFinite(requestedRemainderMinutes) ? requestedRemainderMinutes : 0);
  if (requestedMinutes < 1) {
    dom.createReportWindowMinutesInput?.setCustomValidity("Use at least 1 minute.");
    dom.createReportWindowMinutesInput?.reportValidity();
    dom.createReportWindowMinutesInput?.setCustomValidity("");
    return;
  }

  if (state.createScanMode === "batch") {
    await handleCreateBatchProject();
    return;
  }
  await handleCreateSingleProject();
}

async function handleCreateSingleProject() {
  const url = dom.createUrlInput.value.trim();
  const devScanText = String(dom.createDevScanTextInput?.value || "").trim();
  const isDevTextScan = Boolean(devScanText);
  if (!url && !isDevTextScan) {
    showToast("Company URL is required unless you provide dev scan text.", true);
    return;
  }
  const sharedPayload = getCreateProjectSharedSettings();
  const ceoEmail = String(dom.createCeoEmailInput?.value || "").trim();
  const payload = {
    ...sharedPayload,
    ceo_email: ceoEmail || null,
  };
  const endpoint = isDevTextScan ? "/api/dev/companies/scan" : "/api/companies/scan";
  const sourceLabel = isDevTextScan ? buildDevScanSourceLabel(devScanText) : url;
  const requestBody = isDevTextScan
    ? {
        ...payload,
        text: devScanText,
        source_label: sourceLabel,
      }
    : {
        ...payload,
        url,
      };
  const nowIso = new Date().toISOString();
  const optimisticCompanyId = `temp-${Date.now()}`;

  setBusy(dom.submitCreateProjectBtn, true, "Scanning...", createProjectSubmitIdleLabel());
  setView("home");
  closeCreateProjectModal();
  state.projects = sortProjects([
    toProjectViewModel({
      id: optimisticCompanyId,
      source_url: sourceLabel,
      company_name: sourceLabel,
      objective: payload.objective,
      tags: payload.tags,
      report_window_minutes: payload.report_window_minutes,
      scheduled_send_at: computeProjectReportDeadline({
        created_at: nowIso,
        report_window_minutes: payload.report_window_minutes,
      })?.toISOString() || null,
      ceo_email: payload.ceo_email,
      has_ceo_email: Boolean(payload.ceo_email),
      conversation_automation_enabled: payload.conversation_automation_enabled,
      ceo_delivery_enabled: payload.ceo_delivery_enabled,
      status: "initializing",
      processing: true,
      total_contacts: 0,
      created_at: nowIso,
      updated_at: nowIso,
    }),
    ...state.projects.filter((project) => project.id !== optimisticCompanyId),
  ]);
  renderHomeMetrics();
  renderHomeProjects();
  showToast("Company scan started. Discovering contacts and preparing initial outbound messages...");

  try {
    const response = await apiFetch(endpoint, {
      method: "POST",
      body: requestBody,
    });
    if (response.duplicate_ignored || response.status === "duplicate" || !response.task_id) {
      state.projects = state.projects.filter((project) => project.id !== optimisticCompanyId);
      renderHomeMetrics();
      renderHomeProjects();
      try {
        await loadProjects();
      } catch {
        // Leave the current view as-is if refresh fails transiently.
      }
      showToast("Company URL already exists. Duplicate scan skipped.");
      return;
    }
    state.pendingCompanyTasks[response.company_id] = response.task_id;
    state.projects = sortProjects([
      toProjectViewModel({
        id: response.company_id,
        source_url: sourceLabel,
        company_name: sourceLabel,
        objective: payload.objective,
        tags: payload.tags,
        report_window_minutes: payload.report_window_minutes,
        scheduled_send_at: computeProjectReportDeadline({
          created_at: nowIso,
          report_window_minutes: payload.report_window_minutes,
        })?.toISOString() || null,
        ceo_email: payload.ceo_email,
        has_ceo_email: Boolean(payload.ceo_email),
        conversation_automation_enabled: payload.conversation_automation_enabled,
        ceo_delivery_enabled: payload.ceo_delivery_enabled,
        status: "initializing",
        processing: true,
        total_contacts: 0,
        created_at: nowIso,
        updated_at: nowIso,
      }),
      ...state.projects.filter((project) => project.id !== response.company_id && project.id !== optimisticCompanyId),
    ]);
    renderHomeMetrics();
    renderHomeProjects();
    syncProcessingRefreshLoop();
    finalizeCreatedCompany(response.company_id, response.task_id);
  } catch (error) {
    state.projects = state.projects.filter((project) => project.id !== optimisticCompanyId);
    renderHomeMetrics();
    renderHomeProjects();
    showToast(error.message || "Failed starting company scan", true);
  } finally {
    setBusy(dom.submitCreateProjectBtn, false, "Scanning...", createProjectSubmitIdleLabel());
  }
}

async function handleCreateBatchProject() {
  const freeformText = String(dom.createBatchTextInput?.value || "").trim();
  const files = Array.from(dom.createBatchFilesInput?.files || []);
  if (!freeformText && !files.length) {
    showToast("Paste text and/or upload at least one file for the batch scan.", true);
    return;
  }

  const payload = getCreateProjectSharedSettings();
  const formData = new FormData();
  formData.append("freeform_text", freeformText);
  formData.append("objective", payload.objective || "");
  formData.append("report_window_minutes", String(payload.report_window_minutes));
  formData.append("conversation_automation_enabled", String(payload.conversation_automation_enabled));
  formData.append("ceo_delivery_enabled", String(payload.ceo_delivery_enabled));
  payload.tags.forEach((tag) => {
    formData.append("tags", tag);
  });
  files.forEach((file) => {
    formData.append("files", file, file.name);
  });

  setBusy(dom.submitCreateProjectBtn, true, "Queuing...", createProjectSubmitIdleLabel());
  showLoading("Extracting company URLs from the batch input...");
  try {
    const response = await apiFetch("/api/companies/scan-batch", {
      method: "POST",
      body: formData,
    });
    setView("home");
    closeCreateProjectModal();
    await loadProjects();
    if (response.task_id && response.company_count > 0) {
      syncProcessingRefreshLoop();
    }
    const queuedCount = Number(response.company_count) || 0;
    const duplicateCount = Number(response.duplicate_count) || 0;
    const toastParts = [];
    if (queuedCount === 1) {
      toastParts.push("1 company scan queued.");
    } else if (queuedCount > 1) {
      toastParts.push(`${queuedCount} company scans queued.`);
    }
    if (duplicateCount === 1) {
      toastParts.push("1 duplicate skipped.");
    } else if (duplicateCount > 1) {
      toastParts.push(`${duplicateCount} duplicates skipped.`);
    }
    if (!toastParts.length) {
      toastParts.push("No company scans were queued.");
    }
    showToast(toastParts.join(" "));
  } catch (error) {
    showToast(error.message || "Failed starting batch company scan", true);
  } finally {
    setBusy(dom.submitCreateProjectBtn, false, "Queuing...", createProjectSubmitIdleLabel());
    hideLoading();
  }
}

async function finalizeCreatedCompany(companyId, taskId) {
  try {
    await waitForTask(taskId, COMPANY_SCAN_TASK_TIMEOUT_MS, "Failed to complete company scan.");

    delete state.pendingCompanyTasks[companyId];
    try {
      await loadProjects();
    } catch {
      // Keep UI responsive even if refresh fails transiently.
    }
    syncProcessingRefreshLoop();
    showToast("Company scan completed. Initial outbound messages were prepared.");
  } catch (error) {
    delete state.pendingCompanyTasks[companyId];
    try {
      await loadProjects();
    } catch {
      // Keep UI responsive even if refresh fails transiently.
    }
    syncProcessingRefreshLoop();
    showToast(error.message || "Company scan failed", true);
  }
}

async function finalizeRescannedCompany(companyId, taskId) {
  let taskError = null;
  try {
    await waitForTask(taskId, COMPANY_SCAN_TASK_TIMEOUT_MS, "Failed to complete company re-scan.");
  } catch (error) {
    taskError = error;
  }

  delete state.pendingCompanyTasks[companyId];
  try {
    await loadProjects();
    if (state.currentProjectId === companyId) {
      await refreshCurrentProject(false);
    }
  } catch {
    // Keep UI responsive even if refresh fails transiently.
  }
  syncProcessingRefreshLoop();

  if (taskError) {
    showToast(taskError.message || "Company re-scan failed", true);
    return;
  }
  showToast("Company re-scan completed. Contacts were refreshed.");
}

async function handleInboundSubmit(event) {
  event.preventDefault();

  if (projectIsProcessing(state.currentProject)) {
    showToast("Wait for the company scan to finish before registering inbound messages.", true);
    return;
  }
  const thread = getCurrentThread();
  if (!thread || !state.currentProjectId) {
    return;
  }
  if (isArchivedThread(thread)) {
    showToast("This contact is archived. Unarchive to continue messaging.", true);
    return;
  }

  const text = dom.inboundInput.value.trim();
  if (!text) {
    showToast("Paste an inbound message first.", true);
    return;
  }
  if (hasPendingInboundTask(thread.id)) {
    showToast("This contact already has a reply being generated.", true);
    return;
  }
  try {
    const task = await apiFetch(`/api/companies/${state.currentProjectId}/contacts/${thread.id}/messages/inbound`, {
      method: "POST",
      body: { message: text },
    });

    appendLocalInboundMessage(thread.id, text);
    dom.inboundInput.value = "";
    autoResizeInbound();
    state.pendingInboundTasks[thread.id] = task.task_id;
    renderThreadList();
    renderThreadSidebar();
    renderChat();
    void monitorInboundTask({
      taskId: task.task_id,
      threadId: thread.id,
      companyId: state.currentProjectId,
      successMessage: "Inbound registered and new reply generated.",
      failureMessage: "AI failed to generate reply.",
    });
  } catch (error) {
    showToast(error.message || "Failed registering inbound message", true);
  }
}

async function monitorInboundTask({ taskId, threadId, companyId, successMessage, failureMessage }) {
  try {
    await waitForInboundTask(taskId);
    if (state.currentProjectId === companyId) {
      await refreshCurrentProject(true);
    }
    showToast(successMessage);
  } catch (error) {
    showToast(error.message || failureMessage, true);
  } finally {
    if (state.pendingInboundTasks[threadId] === taskId) {
      delete state.pendingInboundTasks[threadId];
    }
    renderThreadList();
    renderThreadSidebar();
    renderChat();
  }
}

async function waitForTask(taskId, timeoutMs = 120_000, errorMessage = "Task failed") {
  const intervalMs = 1_000;
  const startedAt = Date.now();

  while (true) {
    const task = await apiFetch(`/api/tasks/${taskId}`);
    if (task.status === "completed") {
      return task;
    }
    if (task.status === "failed") {
      throw new Error(task.error || errorMessage);
    }
    if (Date.now() - startedAt > timeoutMs) {
      throw new Error("Timed out waiting for task completion.");
    }
    await wait(intervalMs);
  }
}

async function waitForInboundTask(taskId) {
  return waitForTask(taskId, 120_000, "AI failed to generate reply.");
}

async function handleCopyLatestDraft() {
  const latest = getLatestOutboundMessage();
  if (!latest) {
    showToast("No draft found for this contact.", true);
    return;
  }
  try {
    await copyTextToClipboard(latest.text || "");
    showToast("Latest draft copied.");
  } catch {
    showToast("Clipboard copy failed.", true);
  }
}

async function handleDeleteProject(projectId) {
  if (!projectId) {
    return;
  }

  const project = state.projects.find((p) => p.id === projectId);
  const projectName = project?.company_name || "Company";

  showLoading("Deleting company...");
  try {
    await apiFetch(`/api/companies/${projectId}`, {
      method: "DELETE",
    });
    delete state.pendingCompanyTasks[projectId];

    if (state.currentProjectId === projectId) {
      setView("home");
      resetProjectSelection();
    }

    await loadProjects();
    showToast(`Company \"${projectName}\" deleted successfully.`);
  } catch (error) {
    showToast(error.message || "Failed deleting company", true);
  } finally {
    hideLoading();
  }
}

async function runPrepareReportTask(projectId) {
  const reportTask = await apiFetch(`/api/companies/${projectId}/prepare-report`, {
    method: "POST",
    body: {
      language: "en",
    },
  });
  const reportTaskId = String(reportTask?.task_id || "").trim();
  if (!reportTaskId) {
    throw new Error("prepare-report did not return task_id.");
  }
  const task = await waitForTask(reportTaskId, REPORT_TASK_TIMEOUT_MS, "Report generation failed.");
  return { taskId: reportTaskId, task };
}

async function runBuildReportPdfModelTask(projectId) {
  const taskResponse = await apiFetch(`/api/companies/${projectId}/build-report-pdf-model`, {
    method: "POST",
  });
  const taskId = String(taskResponse?.task_id || "").trim();
  if (!taskId) {
    throw new Error("build-report-pdf-model did not return task_id.");
  }
  const task = await waitForTask(taskId, REPORT_PDF_MODEL_TASK_TIMEOUT_MS, "Audit generation failed.");
  return { taskId, task };
}

function shouldConfirmAuditRegeneration() {
  if (!hasGeneratedAudit()) {
    return true;
  }
  return window.confirm(
    [
      "This company already has an audit.",
      "",
      "If you confirm, this will generate the audit again and replace the current version.",
      "If you only want to download the existing audit, use 'View Audit'.",
      "",
      "Do you want to regenerate the audit?",
    ].join("\n"),
  );
}

async function handleGenerateAudit() {
  const projectId = state.currentProjectId;
  if (!projectId) {
    return;
  }
  if (projectIsProcessing(state.currentProject)) {
    showToast("Wait for the company scan to finish before generating the audit.", true);
    return;
  }
  if (!shouldConfirmAuditRegeneration()) {
    return;
  }

  setBusy(dom.generateFullReportBtn, true, "Generating...", "Generate Audit");
  showLoading("Generating audit...");
  try {
    await runPrepareReportTask(projectId);
    const auditResult = await runBuildReportPdfModelTask(projectId);

    await refreshCurrentProject(true);
    if (hasGeneratedAudit()) {
      const finishedAt = formatTime(auditResult.task?.updated_at || state.latestReport?.pdf_model_generated_at);
      showToast(finishedAt !== "--:--" ? `Audit generated at ${finishedAt}.` : "Audit generated.");
    } else {
      showToast("Audit generated, but no PDF artifact is available yet.", true);
    }
  } catch (error) {
    showToast(error.message || "Failed generating audit", true);
  } finally {
    setBusy(dom.generateFullReportBtn, false, "Generating...", "Generate Audit");
    hideLoading();
    syncReportActions();
  }
}

function autoResizeInbound() {
  if (!dom.inboundInput) {
    return;
  }
  dom.inboundInput.style.height = "auto";
  dom.inboundInput.style.height = `${Math.min(dom.inboundInput.scrollHeight, 220)}px`;
}

function resetProjectSelection() {
  state.currentProjectId = null;
  state.currentProject = null;
  state.currentThreadId = null;
  state.threadMessages = [];
  state.showArchivedThreads = false;
  state.pendingAiAutomationCompanyId = null;
  state.pendingCeoDeliveryCompanyId = null;
  state.pendingCeoEmailCompanyId = null;
  state.pendingProjectScheduleCompanyId = null;
  state.lastRenderedThreadId = null;
  state.lastRenderedMessageCount = 0;
  state.latestReport = null;
  clearMessageEditing();
  clearProjectCeoEmailEditing();
  clearProjectReportScheduleEditing();
  syncReportActions();
  syncProjectAutomationControls();
  renderProjectCeoEmailPanel();
  renderProjectReportSchedulePanel();
  syncArchivedContactsToggleButton();
  syncInboundComposerState();
  renderSidebarFocus();
  syncUrlWithUiState();
  syncProcessingRefreshLoop();
}

async function handleRefreshProject() {
  if (!state.currentProjectId) {
    return;
  }
  setBusy(dom.refreshProjectBtn, true, "Refreshing...", "Refresh");
  showLoading("Refreshing company...");
  try {
    await refreshCurrentProject(true);
    showToast("Company refreshed.");
  } catch (error) {
    showToast(error.message || "Failed refreshing company", true);
  } finally {
    setBusy(dom.refreshProjectBtn, false, "Refreshing...", "Refresh");
    hideLoading();
  }
}

function handleGlobalKeydown(event) {
  if (event.key === "Escape" && dom.manualContactModal?.open) {
    event.preventDefault();
    closeManualContactModal();
    return;
  }
  if (event.key === "Escape" && dom.createProjectModal.open) {
    event.preventDefault();
    closeCreateProjectModal();
    return;
  }

  if (event.repeat || event.metaKey || event.ctrlKey || event.altKey) {
    return;
  }

  if (isTypingTarget(event.target)) {
    return;
  }

  if (event.key === "n" || event.key === "N") {
    event.preventDefault();
    openCreateProjectModal();
    return;
  }

  if (event.key === "r" || event.key === "R") {
    event.preventDefault();
    const isProjectView = !dom.projectView.classList.contains("hidden");
    if (isProjectView && state.currentProjectId) {
      handleRefreshProject();
    } else {
      loadProjects()
        .then(() => showToast("Company list refreshed."))
        .catch((err) => showToast(err.message || "Failed refreshing", true));
    }
  }
}

function bindEvents() {
  if (!prefersReducedMotion()) {
    document.body.addEventListener("mousemove", schedulePointerLighting, { passive: true });
  }

  if (dom.sectionAuditsBtn) {
    dom.sectionAuditsBtn.addEventListener("click", () => {
      openAuditsSection();
    });
  }
  if (dom.sectionCrmBtn) {
    dom.sectionCrmBtn.addEventListener("click", async () => {
      try {
        await openCrmSection({
          threadId: state.currentCrmThreadId,
        });
      } catch (error) {
        showToast(error.message || "Failed loading CRM", true);
        openAuditsSection();
      }
    });
  }
  if (dom.sectionContadoresBtn) {
    dom.sectionContadoresBtn.addEventListener("click", async () => {
      try {
        await openContadoresSection({
          leadId: state.currentContadoresLeadId,
        });
      } catch (error) {
        showToast(error.message || "Failed loading Contadores", true);
        openAuditsSection();
      }
    });
  }

  const debouncedProjectSearch = debounce(() => {
    state.projectQuery = normalizeText(dom.projectSearchInput.value);
    renderHomeProjects();
  }, 220);

  dom.projectSearchInput.addEventListener("input", debouncedProjectSearch);
  if (dom.homeLanguageFilters) {
    dom.homeLanguageFilters.addEventListener("click", (event) => {
      const button = event.target.closest("button[data-language-filter]");
      if (!button) {
        return;
      }
      const filterValue = normalizeText(button.getAttribute("data-language-filter"));
      if (!filterValue || filterValue === state.projectLanguageFilter) {
        return;
      }
      state.projectLanguageFilter = filterValue;
      renderHomeProjects();
    });
  }
  if (dom.homeIndustryFilterSelect) {
    dom.homeIndustryFilterSelect.addEventListener("change", () => {
      state.projectIndustryFilter = normalizeProjectIndustry(dom.homeIndustryFilterSelect.value);
      if (state.projectIndustryFilter === "unknown") {
        state.projectIndustryFilter = "";
      }
      renderHomeProjects();
    });
  }
  if (dom.homeTagFilterSelect) {
    dom.homeTagFilterSelect.addEventListener("change", () => {
      state.projectTagFilter = normalizeTagKey(dom.homeTagFilterSelect.value);
      renderHomeProjects();
    });
  }
  if (dom.homeCeoEmailFilters) {
    dom.homeCeoEmailFilters.addEventListener("click", (event) => {
      const button = event.target.closest("button[data-ceo-email-filter]");
      if (!button) {
        return;
      }
      const filterValue = normalizeText(button.getAttribute("data-ceo-email-filter"));
      if (!filterValue || filterValue === state.projectCeoEmailFilter) {
        return;
      }
      state.projectCeoEmailFilter = filterValue;
      renderHomeProjects();
    });
  }
  if (dom.homeReplyFilters) {
    dom.homeReplyFilters.addEventListener("click", (event) => {
      const button = event.target.closest("button[data-response-filter]");
      if (!button) {
        return;
      }
      const filterValue = normalizeText(button.getAttribute("data-response-filter"));
      if (!filterValue || filterValue === state.projectReplyFilter) {
        return;
      }
      state.projectReplyFilter = filterValue;
      renderHomeProjects();
    });
  }
  if (dom.homeCompanySizeFilters) {
    dom.homeCompanySizeFilters.addEventListener("click", (event) => {
      const button = event.target.closest("button[data-company-size-filter]");
      if (!button) {
        return;
      }
      const filterValue = normalizeText(button.getAttribute("data-company-size-filter"));
      if (!filterValue || filterValue === state.projectCompanySizeFilter) {
        return;
      }
      state.projectCompanySizeFilter = filterValue;
      renderHomeProjects();
    });
  }

  const debouncedThreadSearch = debounce(() => {
    state.threadQuery = normalizeText(dom.threadSearchInput.value);
    renderProjectHeader();
    renderThreadList();
    renderThreadSidebar();
  }, 220);

  dom.threadSearchInput.addEventListener("input", debouncedThreadSearch);
  if (dom.crmSearchInput) {
    const debouncedCrmSearch = debounce(() => {
      state.crmQuery = normalizeText(dom.crmSearchInput.value);
      renderCrmView();
    }, 220);
    dom.crmSearchInput.addEventListener("input", debouncedCrmSearch);
  }
  if (dom.contadoresSearchInput) {
    const debouncedContadoresSearch = debounce(async () => {
      state.contadoresQuery = normalizeText(dom.contadoresSearchInput.value);
      try {
        await refreshContadoresSelection();
      } catch (error) {
        showToast(error.message || "Failed filtering Contadores", true);
      }
    }, 220);
    dom.contadoresSearchInput.addEventListener("input", debouncedContadoresSearch);
  }
  const bindContadoresFilterChange = (element, stateKey) => {
    if (!element) {
      return;
    }
    element.addEventListener("change", async () => {
      state[stateKey] = String(element.value || "").trim();
      try {
        await refreshContadoresSelection();
      } catch (error) {
        showToast(error.message || "Failed refreshing Contadores filters", true);
      }
    });
  };
  bindContadoresFilterChange(dom.contadoresStageFilter, "contadoresStageFilter");
  bindContadoresFilterChange(dom.contadoresPlatformFilter, "contadoresPlatformFilter");
  bindContadoresFilterChange(dom.contadoresBookedFilter, "contadoresBookedFilter");
  bindContadoresFilterChange(dom.contadoresNeedsHumanFilter, "contadoresNeedsHumanFilter");
  bindContadoresFilterChange(dom.contadoresArchivedFilter, "contadoresArchivedFilter");
  if (dom.refreshContadoresBtn) {
    dom.refreshContadoresBtn.addEventListener("click", async () => {
      setBusy(dom.refreshContadoresBtn, true, "Refreshing...", "Refresh");
      try {
        await openContadoresSection({
          leadId: state.currentContadoresLeadId,
          showLoadingOverlay: false,
        });
        showToast("Contadores refreshed.");
      } catch (error) {
        showToast(error.message || "Failed refreshing Contadores", true);
      } finally {
        setBusy(dom.refreshContadoresBtn, false, "Refreshing...", "Refresh");
      }
    });
  }
  if (dom.saveContadoresConfigBtn) {
    dom.saveContadoresConfigBtn.addEventListener("click", saveContadoresConfig);
  }
  if (dom.contadoresLeadList) {
    dom.contadoresLeadList.addEventListener("click", async (event) => {
      const button = event.target.closest("[data-contadores-lead-id]");
      if (!button) {
        return;
      }
      const leadId = String(button.getAttribute("data-contadores-lead-id") || "").trim();
      if (!leadId) {
        return;
      }
      await openContadoresLead(leadId);
    });
  }
  const ctSendMessageBtn = document.getElementById("ctSendMessageBtn");
  if (ctSendMessageBtn) {
    ctSendMessageBtn.addEventListener("click", () => {
      openContadoresSendModal();
    });
  }
  const ctResumeBtn = document.getElementById("ctResumeBtn");
  if (ctResumeBtn) {
    ctResumeBtn.addEventListener("click", () => {
      resumeContadoresAutomation();
    });
  }
  if (dom.contadoresMarkAnsweredBtn) {
    dom.contadoresMarkAnsweredBtn.dataset.label = dom.contadoresMarkAnsweredBtn.textContent || "Mark answered";
    dom.contadoresMarkAnsweredBtn.addEventListener("click", async () => {
      await runContadoresQuickAction("mark-answered", dom.contadoresMarkAnsweredBtn);
    });
  }
  document.querySelectorAll("[data-ct-send-close]").forEach((node) => {
    node.addEventListener("click", (event) => {
      event.preventDefault();
      closeContadoresSendModal();
    });
  });
  document.querySelectorAll('input[name="ctSendKind"]').forEach((input) => {
    input.addEventListener("change", syncContadoresSendModalField);
  });
  const ctSendConfirmBtn = document.getElementById("ctSendConfirmBtn");
  if (ctSendConfirmBtn) {
    ctSendConfirmBtn.addEventListener("click", () => {
      submitContadoresSendModal();
    });
  }
  const ctSendCustomText = document.getElementById("ctSendCustomText");
  if (ctSendCustomText) {
    ctSendCustomText.addEventListener("keydown", (event) => {
      if ((event.metaKey || event.ctrlKey) && event.key === "Enter") {
        event.preventDefault();
        submitContadoresSendModal();
      }
    });
  }
  const refreshContadoresAfterFilter = async () => {
    try {
      await refreshContadoresSelection();
    } catch (error) {
      showToast(error.message || "Failed refreshing Contadores filters", true);
    }
  };
  document.querySelectorAll("[data-stage-pill]").forEach((pill) => {
    pill.addEventListener("click", () => {
      const stage = String(pill.getAttribute("data-stage-pill") || "");
      if (state.contadoresStageFilter === stage) {
        return;
      }
      state.contadoresStageFilter = stage;
      state.contadoresBookedFilter = "";
      state.contadoresNeedsHumanFilter = "";
      state.contadoresArchivedFilter = "";
      if (stage !== "needs_human") {
        state.contadoresManualReplyFilter = "";
      }
      renderContadoresOverviewStats();
      refreshContadoresAfterFilter();
    });
  });
  document.querySelectorAll("[data-manual-reply-pill]").forEach((pill) => {
    pill.addEventListener("click", () => {
      const status = String(pill.getAttribute("data-manual-reply-pill") || "");
      if (state.contadoresManualReplyFilter === status) {
        return;
      }
      state.contadoresStageFilter = "needs_human";
      state.contadoresManualReplyFilter = status;
      renderContadoresOverviewStats();
      refreshContadoresAfterFilter();
    });
  });
  if (dom.contadoresStrategyFilters) {
    dom.contadoresStrategyFilters.addEventListener("click", (event) => {
      const button = event.target.closest("[data-strategy-step]");
      if (!button) {
        return;
      }
      const step = String(button.getAttribute("data-strategy-step") || "");
      const strategyId = String(button.getAttribute("data-strategy-id") || "");
      if (state.contadoresStrategyStepFilter === step && state.contadoresStrategyIdFilter === strategyId) {
        return;
      }
      state.contadoresStrategyStepFilter = step;
      state.contadoresStrategyIdFilter = strategyId;
      renderContadoresOverviewStats();
      renderContadoresStrategyFilters();
      refreshContadoresAfterFilter();
    });
  }
  const ctNavAuditsBtn = document.getElementById("ctNavAuditsBtn");
  if (ctNavAuditsBtn) {
    ctNavAuditsBtn.addEventListener("click", () => {
      openAuditsSection();
    });
  }
  const ctNavCrmBtn = document.getElementById("ctNavCrmBtn");
  if (ctNavCrmBtn) {
    ctNavCrmBtn.addEventListener("click", async () => {
      try {
        await openCrmSection({ threadId: state.currentCrmThreadId });
      } catch (error) {
        showToast(error.message || "Failed loading CRM", true);
        openAuditsSection();
      }
    });
  }
  const ctSettingsBtn = document.getElementById("ctSettingsBtn");
  if (ctSettingsBtn) {
    ctSettingsBtn.addEventListener("click", () => {
      openContadoresDrawer();
    });
  }
  document.querySelectorAll("[data-ct-drawer-close]").forEach((node) => {
    node.addEventListener("click", (event) => {
      event.preventDefault();
      closeContadoresDrawer();
    });
  });
  document.addEventListener("keydown", (event) => {
    if (event.key === "Escape") {
      const sendModal = document.getElementById("ctSendModal");
      if (sendModal && sendModal.classList.contains("open")) {
        closeContadoresSendModal();
        return;
      }
      const drawer = document.getElementById("contadoresDrawer");
      if (drawer && drawer.classList.contains("open")) {
        closeContadoresDrawer();
      }
    }
  });
  const setContadoresTab = (target) => {
    document.querySelectorAll("[data-contadores-tab]").forEach((t) => {
      const active = String(t.getAttribute("data-contadores-tab") || "") === target;
      t.classList.toggle("active", active);
      t.setAttribute("aria-selected", active ? "true" : "false");
    });
    document.querySelectorAll("[data-contadores-pane]").forEach((pane) => {
      const active = String(pane.getAttribute("data-contadores-pane") || "") === target;
      pane.classList.toggle("active", active);
    });
  };
  setContadoresTab("messages");
  document.querySelectorAll("[data-contadores-tab]").forEach((tab) => {
    tab.addEventListener("click", () => {
      const target = String(tab.getAttribute("data-contadores-tab") || "messages");
      setContadoresTab(target);
    });
  });
  if (dom.contadoresManualInput) {
    dom.contadoresManualInput.addEventListener("keydown", (event) => {
      if ((event.metaKey || event.ctrlKey) && event.key === "Enter") {
        event.preventDefault();
        dom.contadoresManualForm?.requestSubmit();
      }
    });
  }
  [
    [dom.contadoresActionOpenerBtn, "send-opener"],
    [dom.contadoresActionLoomBtn, "send-loom"],
    [dom.contadoresActionVideoCheckBtn, "send-video-check"],
    [dom.contadoresActionCalendlyBtn, "send-calendly"],
    [dom.contadoresActionBookedBtn, "mark-booked"],
    [dom.contadoresActionArchiveBtn, "archive"],
    [dom.contadoresActionUnarchiveBtn, "unarchive"],
  ].forEach(([button, action]) => {
    if (!button) {
      return;
    }
    button.dataset.label = button.textContent || "Run";
    button.addEventListener("click", async () => {
      await runContadoresQuickAction(action, button);
    });
  });
  if (dom.contadoresDeleteLeadBtn) {
    dom.contadoresDeleteLeadBtn.dataset.label = dom.contadoresDeleteLeadBtn.textContent || "Delete chat";
    dom.contadoresDeleteLeadBtn.addEventListener("click", async () => {
      await deleteContadoresLead(dom.contadoresDeleteLeadBtn);
    });
  }
  if (dom.contadoresToggleClosedBtn) {
    dom.contadoresToggleClosedBtn.dataset.label = dom.contadoresToggleClosedBtn.textContent || "Close lead";
    dom.contadoresToggleClosedBtn.addEventListener("click", async () => {
      const action = String(dom.contadoresToggleClosedBtn.dataset.action || "close");
      await runContadoresQuickAction(action, dom.contadoresToggleClosedBtn);
    });
  }
  if (dom.refreshCrmBtn) {
    dom.refreshCrmBtn.addEventListener("click", async () => {
      setBusy(dom.refreshCrmBtn, true, "Refreshing...", "Refresh CRM");
      try {
        await refreshCrmInbox({ includeThreadDetail: currentSectionIsCrm() });
        showToast("CRM refreshed.");
      } catch (error) {
        showToast(error.message || "Failed refreshing CRM", true);
      } finally {
        setBusy(dom.refreshCrmBtn, false, "Refreshing...", "Refresh CRM");
      }
    });
  }
  if (dom.crmReplyForm) {
    dom.crmReplyForm.addEventListener("submit", handleCrmReplySubmit);
  }
  if (dom.crmReplyInput) {
    dom.crmReplyInput.addEventListener("keydown", (event) => {
      if ((event.metaKey || event.ctrlKey) && event.key === "Enter") {
        event.preventDefault();
        dom.crmReplyForm?.requestSubmit();
      }
    });
  }
  if (dom.crmMobileBackBtn) {
    dom.crmMobileBackBtn.addEventListener("click", () => {
      setCrmMobilePane("list");
      renderCrmView();
    });
  }
  if (dom.sidebarFocusSelect) {
    dom.sidebarFocusSelect.addEventListener("change", async () => {
      if (state.showArchivedThreads) {
        return;
      }
      const threadId = String(dom.sidebarFocusSelect.value || "").trim();
      if (!threadId) {
        state.currentThreadId = null;
        state.threadMessages = [];
        state.lastRenderedThreadId = null;
        state.lastRenderedMessageCount = 0;
        clearMessageEditing();
        renderChat();
        renderThreadList();
        renderThreadSidebar();
        renderSidebarFocus();
        syncUrlWithUiState();
        return;
      }
      await selectThread(threadId);
    });
  }
  if (dom.sidebarAssistantForm) {
    dom.sidebarAssistantForm.addEventListener("submit", handleSidebarAssistantSubmit);
  }
  if (dom.sidebarAssistantInput) {
    dom.sidebarAssistantInput.addEventListener("keydown", (event) => {
      if (event.key === "Enter" && !event.shiftKey && !event.isComposing) {
        event.preventDefault();
        dom.sidebarAssistantForm?.requestSubmit();
      }
    });
  }
  if (dom.sidebarAssistantClearBtn) {
    dom.sidebarAssistantClearBtn.addEventListener("click", () => {
      clearSidebarAssistantSession();
    });
  }
  if (dom.transcriptSummary) {
    dom.transcriptSummary.addEventListener("click", handleTranscriptSummaryCopy);
    dom.transcriptSummary.addEventListener("keydown", handleTranscriptSummaryCopy);
  }
  if (dom.toggleArchivedThreadsBtn) {
    dom.toggleArchivedThreadsBtn.addEventListener("click", async () => {
      if (!state.currentProjectId) {
        return;
      }
      state.showArchivedThreads = !state.showArchivedThreads;
      state.currentThreadId = null;
      state.threadMessages = [];
      state.lastRenderedThreadId = null;
      state.lastRenderedMessageCount = 0;
      clearMessageEditing();
      try {
        await refreshCurrentProject(false);
      } catch (error) {
        showToast(error.message || "Failed switching contact view", true);
      }
    });
  }
  if (dom.projectAiAutomationToggle) {
    dom.projectAiAutomationToggle.addEventListener("change", async () => {
      await handleToggleProjectConversationAutomation();
    });
  }
  if (dom.projectCeoDeliveryToggle) {
    dom.projectCeoDeliveryToggle.addEventListener("change", async () => {
      await handleToggleProjectCeoDelivery();
    });
  }
  if (dom.projectCeoEmailEditBtn) {
    dom.projectCeoEmailEditBtn.addEventListener("click", handleEditProjectCeoEmail);
  }
  if (dom.projectCeoEmailCopyBtn) {
    dom.projectCeoEmailCopyBtn.addEventListener("click", handleCopyProjectCeoEmail);
  }
  if (dom.projectCeoEmailCancelBtn) {
    dom.projectCeoEmailCancelBtn.addEventListener("click", handleCancelProjectCeoEmailEdit);
  }
  if (dom.projectCeoEmailSaveBtn) {
    dom.projectCeoEmailSaveBtn.addEventListener("click", handleSaveProjectCeoEmail);
  }
  if (dom.projectCeoEmailInput) {
    dom.projectCeoEmailInput.addEventListener("input", () => {
      state.editingProjectCeoEmailValue = dom.projectCeoEmailInput.value;
    });
    dom.projectCeoEmailInput.addEventListener("keydown", (event) => {
      if (event.key === "Escape") {
        event.preventDefault();
        handleCancelProjectCeoEmailEdit();
        return;
      }
      if (event.key === "Enter" && !event.shiftKey) {
        event.preventDefault();
        handleSaveProjectCeoEmail();
      }
    });
  }
  if (dom.projectReportScheduleEditBtn) {
    dom.projectReportScheduleEditBtn.addEventListener("click", handleEditProjectReportSchedule);
  }
  if (dom.projectReportScheduleCancelBtn) {
    dom.projectReportScheduleCancelBtn.addEventListener("click", handleCancelProjectReportScheduleEdit);
  }
  if (dom.projectReportScheduleSaveBtn) {
    dom.projectReportScheduleSaveBtn.addEventListener("click", handleSaveProjectReportSchedule);
  }
  if (dom.projectReportWindowHoursInput) {
    dom.projectReportWindowHoursInput.addEventListener("input", () => {
      state.editingProjectReportWindowHoursValue = dom.projectReportWindowHoursInput.value;
      syncProjectReportScheduleEditorFromWindow();
    });
    dom.projectReportWindowHoursInput.addEventListener("keydown", (event) => {
      if (event.key === "Escape") {
        event.preventDefault();
        handleCancelProjectReportScheduleEdit();
        return;
      }
      if (event.key === "Enter" && !event.shiftKey) {
        event.preventDefault();
        handleSaveProjectReportSchedule();
      }
    });
  }
  if (dom.projectReportWindowMinutesInput) {
    dom.projectReportWindowMinutesInput.addEventListener("input", () => {
      state.editingProjectReportWindowMinutesValue = dom.projectReportWindowMinutesInput.value;
      syncProjectReportScheduleEditorFromWindow();
    });
    dom.projectReportWindowMinutesInput.addEventListener("keydown", (event) => {
      if (event.key === "Escape") {
        event.preventDefault();
        handleCancelProjectReportScheduleEdit();
        return;
      }
      if (event.key === "Enter" && !event.shiftKey) {
        event.preventDefault();
        handleSaveProjectReportSchedule();
      }
    });
  }
  if (dom.projectScheduledSendInput) {
    dom.projectScheduledSendInput.addEventListener("input", () => {
      state.editingProjectScheduledSendValue = dom.projectScheduledSendInput.value;
      syncProjectReportScheduleEditorFromScheduledSend();
    });
    dom.projectScheduledSendInput.addEventListener("keydown", (event) => {
      if (event.key === "Escape") {
        event.preventDefault();
        handleCancelProjectReportScheduleEdit();
        return;
      }
      if (event.key === "Enter" && !event.shiftKey) {
        event.preventDefault();
        handleSaveProjectReportSchedule();
      }
    });
  }

  dom.inboundInput.addEventListener("input", autoResizeInbound);
  dom.inboundInput.addEventListener("keydown", (event) => {
    if ((event.metaKey || event.ctrlKey) && event.key === "Enter") {
      event.preventDefault();
      dom.inboundForm.requestSubmit();
    }
  });

  if (dom.emailThreadLinkInput) {
    dom.emailThreadLinkInput.addEventListener("keydown", (event) => {
      if ((event.metaKey || event.ctrlKey) && event.key === "Enter") {
        event.preventDefault();
        handleSaveEmailThreadLink();
      }
    });
  }

  dom.openCreateProjectBtn.addEventListener("click", openCreateProjectModal);
  dom.homeCreateProjectBtn.addEventListener("click", openCreateProjectModal);
  dom.closeCreateProjectBtn.addEventListener("click", closeCreateProjectModal);
  if (dom.createScanModeSingleBtn) {
    dom.createScanModeSingleBtn.addEventListener("click", () => setCreateScanMode("single"));
  }
  if (dom.createScanModeBatchBtn) {
    dom.createScanModeBatchBtn.addEventListener("click", () => setCreateScanMode("batch"));
  }
  if (dom.createBatchFilesInput) {
    dom.createBatchFilesInput.addEventListener("change", syncCreateBatchFilesSummary);
  }
  dom.createProjectForm.addEventListener("submit", handleCreateProject);
  if (dom.openManualContactModalBtn) {
    dom.openManualContactModalBtn.addEventListener("click", openManualContactModal);
  }
  if (dom.closeManualContactModalBtn) {
    dom.closeManualContactModalBtn.addEventListener("click", closeManualContactModal);
  }
  if (dom.manualContactForm) {
    dom.manualContactForm.addEventListener("submit", handleCreateManualContact);
  }
  if (dom.manualContactTypeInput) {
    dom.manualContactTypeInput.addEventListener("change", syncManualContactValuePlaceholder);
  }

  dom.backHomeBtn.addEventListener("click", () => {
    setView("home");
    resetProjectSelection();
  });

  if (dom.refreshProjectBtn) {
    dom.refreshProjectBtn.addEventListener("click", handleRefreshProject);
  }
  if (dom.rescanCompanyBtn) {
    dom.rescanCompanyBtn.addEventListener("click", handleRescanCompany);
  }

  dom.inboundForm.addEventListener("submit", handleInboundSubmit);
  if (dom.saveEmailThreadLinkBtn) {
    dom.saveEmailThreadLinkBtn.addEventListener("click", handleSaveEmailThreadLink);
  }
  if (dom.dismissEmailThreadLinkPanelBtn) {
    dom.dismissEmailThreadLinkPanelBtn.addEventListener("click", handleDismissEmailThreadLinkPanel);
  }
  dom.copyLatestDraftBtn.addEventListener("click", handleCopyLatestDraft);
  if (dom.generateFullReportBtn) {
    dom.generateFullReportBtn.addEventListener("click", handleGenerateAudit);
  }
  if (dom.viewAuditBtn) {
    dom.viewAuditBtn.addEventListener("click", handleViewAudit);
  }
  if (dom.archiveThreadBtn) {
    dom.archiveThreadBtn.addEventListener("click", async () => {
      const threadId = dom.archiveThreadBtn.dataset.archiveThreadId;
      const nextRaw = dom.archiveThreadBtn.dataset.archiveNextState;
      if (!threadId || typeof nextRaw !== "string") {
        return;
      }
      await handleSetThreadArchived(threadId, nextRaw === "true");
    });
  }

  if (dom.closeThreadViewBtn) {
    dom.closeThreadViewBtn.addEventListener("click", () => {
      state.currentThreadId = null;
      state.threadMessages = [];
      state.lastRenderedThreadId = null;
      state.lastRenderedMessageCount = 0;
      clearMessageEditing();
      showContactsView();
      renderThreadList();
      renderSidebarFocus();
      syncUrlWithUiState();
    });
  }

  dom.createProjectModal.addEventListener("click", (event) => {
    const rect = dom.createProjectModal.getBoundingClientRect();
    const isOutside =
      event.clientX < rect.left ||
      event.clientX > rect.right ||
      event.clientY < rect.top ||
      event.clientY > rect.bottom;
    if (isOutside) {
      closeCreateProjectModal();
    }
  });

  dom.createProjectModal.addEventListener("cancel", (event) => {
    event.preventDefault();
    closeCreateProjectModal();
  });
  if (dom.manualContactModal) {
    dom.manualContactModal.addEventListener("click", (event) => {
      const rect = dom.manualContactModal.getBoundingClientRect();
      const isOutside =
        event.clientX < rect.left ||
        event.clientX > rect.right ||
        event.clientY < rect.top ||
        event.clientY > rect.bottom;
      if (isOutside) {
        closeManualContactModal();
      }
    });
    dom.manualContactModal.addEventListener("cancel", (event) => {
      event.preventDefault();
      closeManualContactModal();
    });
  }

  document.addEventListener("keydown", handleGlobalKeydown);
}

function initAmbientCanvas() {
  const canvas = document.getElementById("ambientCanvas");
  if (!canvas) {
    return;
  }
  const ctx = canvas.getContext("2d");
  if (!ctx) {
    return;
  }

  let width = window.innerWidth;
  let height = window.innerHeight;
  let dpr = Math.min(window.devicePixelRatio || 1, 1.6);
  let rafId = null;
  let running = false;
  const particles = [];
  let particleCount = 0;
  const linkDistance = 118;
  const linkDistanceSq = linkDistance * linkDistance;

  function createParticle() {
    return {
      x: Math.random() * width,
      y: Math.random() * height,
      vx: (Math.random() - 0.5) * 0.28,
      vy: (Math.random() - 0.5) * 0.28,
      size: Math.random() * 1.8 + 0.45,
      alpha: Math.random() * 0.38 + 0.08,
    };
  }

  function syncParticleCount() {
    const targetCount = Math.max(24, Math.min(Math.floor((width * height) / 26000), 72));
    while (particles.length < targetCount) {
      particles.push(createParticle());
    }
    particles.length = targetCount;
    particleCount = particles.length;
  }

  function resizeCanvas() {
    width = window.innerWidth;
    height = window.innerHeight;
    dpr = Math.min(window.devicePixelRatio || 1, 1.6);
    canvas.width = Math.floor(width * dpr);
    canvas.height = Math.floor(height * dpr);
    canvas.style.width = `${width}px`;
    canvas.style.height = `${height}px`;
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    syncParticleCount();
  }

  function start() {
    if (running || prefersReducedMotion() || document.hidden) {
      return;
    }
    running = true;
    rafId = window.requestAnimationFrame(render);
  }

  function stop() {
    running = false;
    if (rafId) {
      window.cancelAnimationFrame(rafId);
      rafId = null;
    }
  }

  function handlePrefersReducedMotionChange() {
    if (prefersReducedMotion()) {
      canvas.style.opacity = "0";
      stop();
      return;
    }
    canvas.style.opacity = "0.64";
    resizeCanvas();
    start();
  }

  function render() {
    if (!running) {
      return;
    }
    ctx.clearRect(0, 0, width, height);

    for (let i = 0; i < particleCount; i++) {
      const p = particles[i];
      p.x += p.vx;
      p.y += p.vy;

      if (p.x < -4) p.x = width + 4;
      if (p.x > width + 4) p.x = -4;
      if (p.y < -4) p.y = height + 4;
      if (p.y > height + 4) p.y = -4;

      ctx.beginPath();
      ctx.arc(p.x, p.y, p.size, 0, Math.PI * 2);
      ctx.fillStyle = `rgba(28, 160, 133, ${p.alpha})`;
      ctx.fill();

      for (let j = i + 1; j < particleCount; j++) {
        const p2 = particles[j];
        const dx = p.x - p2.x;
        const dy = p.y - p2.y;
        const distanceSq = dx * dx + dy * dy;

        if (distanceSq < linkDistanceSq) {
          const strength = (linkDistanceSq - distanceSq) / linkDistanceSq;
          ctx.beginPath();
          ctx.moveTo(p.x, p.y);
          ctx.lineTo(p2.x, p2.y);
          ctx.strokeStyle = `rgba(28, 160, 133, ${strength * 0.14})`;
          ctx.stroke();
        }
      }
    }

    rafId = window.requestAnimationFrame(render);
  }

  resizeCanvas();
  canvas.style.opacity = prefersReducedMotion() ? "0" : "0.64";
  start();

  window.addEventListener("resize", debounce(resizeCanvas, 150));
  document.addEventListener("visibilitychange", () => {
    if (document.hidden) {
      stop();
      return;
    }
    start();
  });

  if (prefersReducedMotionQuery) {
    if (typeof prefersReducedMotionQuery.addEventListener === "function") {
      prefersReducedMotionQuery.addEventListener("change", handlePrefersReducedMotionChange);
    } else if (typeof prefersReducedMotionQuery.addListener === "function") {
      prefersReducedMotionQuery.addListener(handlePrefersReducedMotionChange);
    }
  }
}

async function initialize() {
  state.baseUrl = normalizeBaseUrl(state.baseUrl);
  hydrateSidebarAssistantSession();
  initAmbientCanvas();
  bindEvents();
  setCreateScanMode("single");
  setView("home");
  renderSidebarFocus();
  syncProjectAutomationControls();
  syncArchivedContactsToggleButton();
  syncReportActions();
  renderCrmView();
  renderContadoresView();
  autoResizeInbound();
  try {
    await Promise.all([
      loadProjects(),
      loadCrmThreads({ preserveSelection: false }),
    ]);
    await restoreUiStateFromUrl();
    syncCrmRefreshLoop();
  } catch (error) {
    showToast(error.message || "Failed loading companies", true);
  }
}

document.addEventListener("DOMContentLoaded", () => {
  initialize();
});
