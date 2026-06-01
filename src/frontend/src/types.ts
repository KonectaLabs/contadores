export type LeadStage =
  | "awaiting_initial_reply"
  | "awaiting_video_reply"
  | "needs_human"
  | "calendly_sent"
  | "booked"
  | "converted"
  | "closed"
  | "archived";

export type LeadPipelineStage =
  | "new"
  | "contacted"
  | "offer_sent"
  | "meeting_sent"
  | "converted"
  | "closed"
  | "archived";

export type LeadQueueState = "automation" | "operator" | "workstation" | "paused" | "none";
export type LeadTerminalState = "open" | "closed" | "archived";
export type LeadAttentionState = "clear" | "needs_reply" | "answered" | "paused" | "converted" | "closed" | "archived";
export type LeadConversionType = "meeting" | "workstation" | "manual" | null;

export type FunnelKind = "campaign" | "inbox";
export type OfferPaymentModel = "monthly" | "one_time" | "custom";
export type FunnelStrategyDelivery = "link" | "video" | "text";

export interface RuntimeFunnelSettings {
  id: string;
  label: string;
  kind: FunnelKind;
  enabled: boolean;
  sheet_configured: boolean;
  sheet_url_configured: boolean;
  sheet_gid: string;
  sheet_poll_seconds: number;
}

export interface RuntimeSettings {
  enabled: boolean;
  ready: boolean;
  readiness_issues: string[];
  sheet_configured: boolean;
  sheet_gid: string | null;
  sheet_poll_seconds: number;
  loom_url_configured: boolean;
  calendly_base_url: string;
  alert_emails: string[];
  funnel_config_path: string;
  enabled_campaign_funnels: string[];
  ready_campaign_funnels: string[];
  funnels: RuntimeFunnelSettings[];
}

export interface FunnelStrategyDefinition {
  step: string;
  id: string;
  label: string;
  weight: number;
  delivery: FunnelStrategyDelivery;
  sequence_step: string;
  message_text: string;
  media_type: string | null;
  media_path: string | null;
  media_caption: string | null;
}

export interface FunnelDefinition {
  id: string;
  label: string;
  kind: FunnelKind;
  enabled: boolean;
  offer_version: string;
  offer_price_usd: number;
  offer_payment_model: OfferPaymentModel;
  offer_summary: string;
  offer_includes_website: boolean;
  default_campaign_count: number;
  default_daily_ad_budget_usd: number | null;
  sheet_url: string | null;
  sheet_gid: string | null;
  sheet_source_filter: string | null;
  sheet_poll_seconds: number;
  template_language: string;
  opener_text: string;
  opener_template_name: string | null;
  opener_followup_text: string;
  opener_followup_template_name: string | null;
  manual_ping_text: string;
  manual_ping_template_name: string | null;
  loom_intro_text: string;
  loom_url: string;
  video_check_text: string;
  calendly_intro_text: string;
  calendly_base_url: string;
  alert_emails: string[];
  whatsapp_referral_source_ids: string[];
  initial_reply_quiet_seconds: number;
  post_loom_min_seconds: number;
  post_loom_quiet_seconds: number;
  strategies: FunnelStrategyDefinition[];
}

export interface FunnelListResponse {
  seed_config_path: string;
  config_path: string;
  config_errors: string[];
  funnels: FunnelDefinition[];
}

export interface ContadoresConfig {
  enabled: boolean;
  sheet_url: string | null;
  sheet_gid: string | null;
  sheet_poll_seconds: number;
  loom_url: string;
  calendly_base_url: string;
  alert_emails: string[];
  initial_reply_quiet_seconds: number;
  post_loom_min_seconds: number;
  post_loom_quiet_seconds: number;
  strategy_weights: Record<string, Record<string, number>>;
  last_sheet_sync_at: string | null;
  last_sheet_sync_status: string | null;
  last_sheet_sync_note: string | null;
  last_alert_at: string | null;
}

export interface RunnerLogItem {
  name: string;
  path: string;
  size_bytes: number;
  modified_at: string | null;
}

export interface RunnerMetricDelta {
  key: string;
  previous: number;
  current: number;
  delta: number;
}

export interface RunnerDeltaEvent {
  lead_id: string;
  funnel_id: string;
  full_name: string | null;
  phone: string | null;
  kind: string;
  severity: "critical" | "high" | "medium" | "low" | "info" | string;
  title: string;
  detail: string;
  suggested_action: string;
  occurred_at: string | null;
  stage: string | null;
  manual_reply_status: string | null;
  latest_text: string;
  excluded: boolean;
  exclusion_reasons: string[];
}

export interface RunnerDelta {
  schema_version: number;
  status: string;
  source: string;
  created_at: string;
  baseline_available: boolean;
  previous_generated_at: string | null;
  current_generated_at: string | null;
  summary_excerpt: string;
  metrics: {
    total_leads: number;
    new_replies: number;
    needs_action: number;
    new_outbound: number;
    delivery_changes: number;
    state_changes: number;
    due_next_steps: number;
    new_exclusions: number;
  };
  bucket_deltas: RunnerMetricDelta[];
  exclusion_deltas: RunnerMetricDelta[];
  failure_deltas: RunnerMetricDelta[];
  events: RunnerDeltaEvent[];
  attention_events: RunnerDeltaEvent[];
  sent_events: RunnerDeltaEvent[];
  markdown: string;
}

export interface RunnerStatusResponse {
  generated_at: string;
  running: boolean;
  pid: number | null;
  started_at: string | null;
  lock_age_seconds: number | null;
  latest_summary: string;
  latest_summary_updated_at: string | null;
  history_markdown: string;
  history_updated_at: string | null;
  delta: RunnerDelta | null;
  latest_log_path: string | null;
  latest_log_tail: string;
  launchd_out_tail: string;
  launchd_err_tail: string;
  logs: RunnerLogItem[];
}

export interface PlatformEventItem {
  id: number;
  event_type: string;
  lifecycle_stage: string;
  target_type: string;
  target_id: string;
  funnel_id: string;
  severity: string;
  source: string;
  actor: string;
  summary: string;
  payload: Record<string, unknown>;
  idempotency_key: string | null;
  correlation_id: string | null;
  created_at: string;
}

export interface PlatformMeetingItem {
  id: string;
  lead_id: string;
  client_id: string;
  funnel_id: string;
  status: string;
  lead_email: string;
  timezone: string;
  requested_day: string;
  requested_time: string;
  calendar_id: string;
  calendar_event_id: string;
  calendar_event_link: string;
  calendar_event_payload: Record<string, unknown>;
  calendar_result: Record<string, unknown>;
  calendar_error: string;
  context_summary: string;
  transcript_text: string;
  transcript_path: string;
  extracted_profile: Record<string, unknown>;
  idempotency_key: string | null;
  scheduled_at: string | null;
  created_at: string;
  updated_at: string;
}

export interface PlatformClientProfileItem {
  id: string;
  client_id: string;
  lead_id: string;
  funnel_id: string;
  status: string;
  source_meeting_id: string;
  business_summary: string;
  offer_summary: string;
  market_summary: string;
  objections: unknown[];
  segments: unknown[];
  knowledge: Record<string, unknown>;
  created_at: string;
  updated_at: string;
}

export interface PlatformAdCampaignItem {
  id: string;
  client_id: string;
  funnel_id: string;
  status: string;
  objective: string;
  budget_daily_usd: number | null;
  budget_total_usd: number | null;
  budget_currency: string;
  target_segments: unknown[];
  angles: unknown[];
  creative_benchmark: Record<string, unknown>;
  creative_testing: Record<string, unknown>;
  meta_campaign_id: string;
  approval_status: string;
  idempotency_key: string | null;
  created_at: string;
  updated_at: string;
}

export interface PlatformCreativeAssetItem {
  id: string;
  campaign_id: string;
  client_id: string;
  status: string;
  asset_type: string;
  prompt: string;
  file_path: string;
  dimensions: string;
  source_refs: unknown[];
  meta_creative_id: string;
  image_hash: string;
  video_id: string;
  meta_upload_response: Record<string, unknown>;
  failure_reason: string;
  created_at: string;
  updated_at: string;
}

export interface PlatformMetaPublishAttemptItem {
  id: string;
  campaign_id: string;
  status: string;
  approval_status: string;
  request_payload: Record<string, unknown>;
  response_payload: Record<string, unknown>;
  error: string;
  idempotency_key: string | null;
  created_at: string;
  updated_at: string;
}

export interface PlatformMetaInventorySnapshotItem {
  id: string;
  status: string;
  source: string;
  actor: string;
  ad_account_id: string;
  business_id: string;
  api_version: string;
  inventory: Record<string, unknown>;
  errors: unknown[];
  created_at: string;
}

export interface PlatformClientUpdateItem {
  id: string;
  client_id: string;
  campaign_id: string;
  status: string;
  summary_text: string;
  leads_count: number;
  blockers: unknown[];
  next_action: string;
  whatsapp_message_id: number | null;
  window_started_at: string | null;
  window_ended_at: string | null;
  created_at: string;
  updated_at: string;
}

export interface PlatformHumanQuestionItem {
  id: string;
  workflow: string;
  target_type: string;
  target_id: string;
  funnel_id: string;
  status: string;
  context_summary: string;
  trying_to_do: string;
  question: string;
  options: unknown[];
  default_action: string;
  timeout_at: string | null;
  whatsapp_message_id: string;
  answer_text: string;
  answered_at: string | null;
  promoted_to_memory_at: string | null;
  created_at: string;
  updated_at: string;
}

export interface PlatformAgentRunItem {
  id: string;
  agent_kind: string;
  target_type: string;
  target_id: string;
  status: string;
  prompt_version: string;
  context_path: string;
  codex_thread_id: string | null;
  codex_turn_id: string | null;
  final_response_preview: string;
  error_preview: string;
  started_at: string;
  finished_at: string | null;
  created_at: string;
}

export interface PlatformAgentToolCallItem {
  id: number;
  run_id: string;
  tool_name: string;
  target_type: string;
  target_id: string;
  status: string;
  idempotency_key: string | null;
  arguments_preview: string;
  result_preview: string;
  error_preview: string;
  created_at: string;
}

export interface PlatformOverviewCounts {
  active_blockers: number;
  open_human_questions: number;
  blocked_meta_attempts: number;
  blocked_meta_inventory: number;
  pending_campaigns: number;
  meetings: number;
  campaigns: number;
  creative_assets: number;
  meta_inventory_snapshots: number;
  client_updates: number;
  agent_runs: number;
  failed_agent_runs: number;
  agent_tool_calls: number;
  failed_agent_tool_calls: number;
  recent_events: number;
}

export interface PlatformOverviewResponse {
  generated_at: string;
  counts: PlatformOverviewCounts;
  events: PlatformEventItem[];
  meetings: PlatformMeetingItem[];
  client_profiles: PlatformClientProfileItem[];
  ad_campaigns: PlatformAdCampaignItem[];
  creative_assets: PlatformCreativeAssetItem[];
  meta_inventory_snapshots: PlatformMetaInventorySnapshotItem[];
  meta_publish_attempts: PlatformMetaPublishAttemptItem[];
  client_updates: PlatformClientUpdateItem[];
  human_questions: PlatformHumanQuestionItem[];
  agent_runs: PlatformAgentRunItem[];
  agent_tool_calls: PlatformAgentToolCallItem[];
}

export interface ContadoresMetrics {
  total: number;
  awaiting_initial_reply: number;
  awaiting_video_reply: number;
  needs_human: number;
  calendly_sent: number;
  meeting_sent: number;
  /** Legacy alias. Prefer converted or pipeline_converted in new UI. */
  booked: number;
  converted: number;
  closed: number;
  archived: number;
  pipeline_new: number;
  pipeline_contacted: number;
  pipeline_offer_sent: number;
  pipeline_meeting_sent: number;
  pipeline_converted: number;
  queue_operator: number;
  queue_paused: number;
  attention_needs_reply: number;
  terminal_closed: number;
}

export interface StrategyAssignment {
  id: number;
  step: string;
  strategy_id: string;
  strategy_label: string;
  assigned_at: string;
}

export interface LeadSummary {
  id: string;
  funnel_id: string;
  external_lead_id: string;
  phone: string;
  normalized_phone: string;
  full_name: string | null;
  email: string | null;
  platform: string | null;
  lead_status: string | null;
  tags: string[];
  sheet_created_time: string | null;
  stage: LeadStage;
  raw_stage: LeadStage;
  pipeline_stage: LeadPipelineStage;
  queue_state: LeadQueueState;
  terminal_state: LeadTerminalState;
  attention_state: LeadAttentionState;
  conversion_type: LeadConversionType;
  calendly_url: string;
  meeting_url: string;
  last_classification_label: string | null;
  last_classification_reason: string | null;
  opener_sent_at: string | null;
  first_reply_received_at: string | null;
  loom_sent_at: string | null;
  video_check_sent_at: string | null;
  classification_completed_at: string | null;
  calendly_sent_at: string | null;
  meeting_sent_at: string | null;
  meeting_scheduled_at: string | null;
  /** Legacy alias. Prefer converted_at in new UI. */
  booked_at: string | null;
  converted_at: string | null;
  closed_at: string | null;
  needs_human_notified_at: string | null;
  manual_reply_status: "needs_reply" | "answered" | null;
  manual_reply_handled_at: string | null;
  last_inbound_at: string | null;
  last_outbound_at: string | null;
  archived_at: string | null;
  codex_enabled: boolean;
  strategy_assignments: StrategyAssignment[];
  workstation_client_id: string | null;
  automation_paused: boolean;
  automation_paused_reason: string | null;
  outbound_error_count: number;
  latest_outbound_error: string | null;
  created_at: string;
  updated_at: string;
}

export interface MessageItem {
  id: number;
  lead_id: string;
  from_me: boolean;
  text: string;
  delivery_status: string;
  external_id: string | null;
  delivery_attempts: number;
  last_delivery_error: string | null;
  last_delivery_error_at: string | null;
  delivery_error_acknowledged_at: string | null;
  dispatch_after: string;
  sequence_step: string | null;
  strategy_step: string | null;
  strategy_id: string | null;
  strategy_label: string | null;
  media_type: string | null;
  media_path: string | null;
  media_caption: string | null;
  media_mime_type: string | null;
  media_filename: string | null;
  media_sha256: string | null;
  media_id: string | null;
  media_url: string | null;
  created_at: string;
}

export interface LeadListResponse {
  metrics: ContadoresMetrics;
  config: ContadoresConfig;
  leads: LeadSummary[];
  tag_options: string[];
}

export interface LeadDetailResponse {
  lead: LeadSummary;
  config: ContadoresConfig;
  messages: MessageItem[];
}

export interface QuickActionResponse {
  lead: LeadSummary;
  queued_message_ids: number[];
}

export interface BulkActionItem {
  lead_id: string;
  ok: boolean;
  lead: LeadSummary | null;
  queued_message_ids: number[];
  error: string | null;
}

export interface BulkActionResponse {
  action: string;
  total: number;
  succeeded: number;
  failed: number;
  queued_message_ids: number[];
  results: BulkActionItem[];
}

export interface StrategyStatsItem {
  step: string;
  strategy_id: string;
  strategy_label: string;
  weight: number;
  assigned: number;
  sent: number;
  delivered: number;
  reached_calendly: number;
  reached_meeting: number;
  /** Legacy alias. Prefer converted in new UI. */
  booked: number;
  converted: number;
  calendly_rate: number;
  meeting_rate: number;
  /** Legacy alias. Prefer conversion_rate in new UI. */
  booked_rate: number;
  conversion_rate: number;
}

export interface StrategyStatsResponse {
  items: StrategyStatsItem[];
}

export interface ManualAttentionCountsResponse {
  counts: Record<string, number>;
}

export interface WorkstationMediaAsset {
  id: string;
  client_id: string;
  title: string;
  original_filename: string;
  stored_filename: string;
  stored_path: string;
  content_type: string | null;
  size_bytes: number;
  media_url: string;
  created_at: string;
}

export interface WorkstationProfessionalPhotoVersion {
  version: string;
  image_path: string;
  image_url: string;
  metadata_path: string | null;
  operation: string | null;
  created_at: string | null;
  source_image_paths: string[];
  previous_version_path: string | null;
  user_edit_prompt: string | null;
}

export type WorkstationProfessionalPhotoJobStatus = "queued" | "running" | "completed" | "failed";

export interface WorkstationProfessionalPhotoJobResponse {
  job_id: string;
  client_id: string;
  status: WorkstationProfessionalPhotoJobStatus;
  created_at: string;
  started_at: string | null;
  completed_at: string | null;
  error: string | null;
  result: WorkstationProfessionalPhotoVersion | null;
}

export interface WorkstationClientSummary {
  id: string;
  lead_id: string;
  funnel_id: string;
  work_type: string;
  status: string;
  automation_status: string;
  offer_price_usd: number | null;
  offer_currency: string;
  display_name: string;
  folder_name: string;
  folder_path: string;
  media_count: number;
  lead: LeadSummary | null;
  last_automation_handled_at: string | null;
  last_preview_sent_at: string | null;
  approved_at: string | null;
  ping_1_sent_at: string | null;
  ping_2_sent_at: string | null;
  handoff_sent_at: string | null;
  created_at: string;
  updated_at: string;
}

export interface WorkstationClientListResponse {
  clients: WorkstationClientSummary[];
}

export interface WorkstationRuntimeAlert {
  id: number;
  alert_type: string;
  error: string;
  fallback_action: string;
  latest_inbound_text: string;
  notified_at: string | null;
  resolved_at: string | null;
  email_thread_id: string | null;
  email_message_id: string | null;
  created_at: string;
}

export interface WorkstationPublicPage {
  client_id: string;
  public_token: string;
  public_path: string;
  public_url: string;
  current_version: string;
  version_path: string;
  status: string;
  first_published_at: string | null;
  updated_at: string | null;
  last_sent_at: string | null;
}

export interface WorkstationAutomationState {
  status: string;
  label: string;
  detail: string;
  is_working: boolean;
  is_live_working: boolean;
  is_waiting_backoff: boolean;
  is_stale: boolean;
  live_status: string;
  live_detail: string;
  live_started_at: string | null;
  has_active_background_task: boolean;
  has_active_codex_turn: boolean;
  backoff_until: string | null;
  latest_inbound_at: string | null;
  progress_path: string | null;
  progress_markdown: string;
  progress_updated_at: string | null;
}

export interface WorkstationClientDetailResponse {
  client: WorkstationClientSummary;
  notes: string;
  messages: MessageItem[];
  media: WorkstationMediaAsset[];
  runtime_alerts: WorkstationRuntimeAlert[];
  automation_state: WorkstationAutomationState;
  professional_photos: WorkstationProfessionalPhotoVersion[];
  public_page: WorkstationPublicPage | null;
}

export interface WorkstationCopyAllResponse {
  text: string;
}

export interface ClientLeadSourceCounts {
  total?: number;
  pending?: number;
  queued?: number;
  sent?: number;
  delivered?: number;
  failed?: number;
  blocked?: number;
  [key: string]: number | undefined;
}

export interface ClientLeadSource {
  id: string;
  label: string;
  enabled: boolean;
  sheet_url: string | null;
  sheet_gid: string | null;
  sheet_tab_name: string | null;
  sheet_poll_seconds: number;
  recipient_name: string | null;
  recipient_phone: string | null;
  normalized_recipient_phone: string | null;
  template_name: string | null;
  template_language: string | null;
  column_mapping: Record<string, string>;
  context_field_mapping: Record<string, string>;
  last_sync_at: string | null;
  last_sync_status: string | null;
  last_sync_note: string | null;
  counts: ClientLeadSourceCounts;
}

export interface ClientLeadSourceListResponse {
  sources: ClientLeadSource[];
}

export interface ClientLead {
  id: string;
  source_id: string;
  row_number: number;
  raw_row: Record<string, unknown>;
  created_time: string | null;
  full_name: string | null;
  phone_number: string | null;
  email: string | null;
  wa_link: string | null;
  notification_text: string | null;
  sent_text: string | null;
  delivery_status: string | null;
  delivery_attempts: number;
  last_delivery_error: string | null;
  block_reason: string | null;
  sent_at: string | null;
  delivered_at: string | null;
}

export interface ClientLeadListResponse {
  leads: ClientLead[];
  source?: ClientLeadSource;
}

export interface ClientLeadRecipientCrmLead {
  id: string;
  funnel_id: string;
  full_name: string | null;
  phone: string;
  normalized_phone: string;
  stage: string;
  updated_at: string;
}

export interface ClientLeadRecipientChatMessage {
  delivery_id: string;
  row_number: number;
  lead_name: string | null;
  lead_phone: string;
  lead_email: string | null;
  text: string;
  delivery_status: string;
  external_id: string | null;
  sent_at: string | null;
  delivered_at: string | null;
  last_delivery_error: string | null;
  created_at: string;
  updated_at: string;
}

export interface ClientLeadRecipientChatResponse {
  source: ClientLeadSource;
  recipient_name: string | null;
  recipient_phone: string;
  normalized_recipient_phone: string;
  crm_leads: ClientLeadRecipientCrmLead[];
  messages: ClientLeadRecipientChatMessage[];
}

export interface ClientLeadCopyAllResponse {
  text: string;
}
