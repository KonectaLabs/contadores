export type LeadStage =
  | "awaiting_initial_reply"
  | "awaiting_video_reply"
  | "needs_human"
  | "calendly_sent"
  | "booked"
  | "closed"
  | "archived";

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
}

export type FunnelKind = "campaign" | "inbox";
export type FunnelStrategyDelivery = "link" | "video";

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
  config_path: string;
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

export interface ContadoresMetrics {
  total: number;
  awaiting_initial_reply: number;
  awaiting_video_reply: number;
  needs_human: number;
  calendly_sent: number;
  booked: number;
  closed: number;
  archived: number;
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
  calendly_url: string;
  last_classification_label: string | null;
  last_classification_reason: string | null;
  opener_sent_at: string | null;
  first_reply_received_at: string | null;
  loom_sent_at: string | null;
  video_check_sent_at: string | null;
  classification_completed_at: string | null;
  calendly_sent_at: string | null;
  booked_at: string | null;
  closed_at: string | null;
  needs_human_notified_at: string | null;
  manual_reply_status: "needs_reply" | "answered" | null;
  manual_reply_handled_at: string | null;
  last_inbound_at: string | null;
  last_outbound_at: string | null;
  archived_at: string | null;
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
  booked: number;
  calendly_rate: number;
  booked_rate: number;
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
  display_name: string;
  folder_name: string;
  folder_path: string;
  media_count: number;
  lead: LeadSummary | null;
  created_at: string;
  updated_at: string;
}

export interface WorkstationClientListResponse {
  clients: WorkstationClientSummary[];
}

export interface WorkstationClientDetailResponse {
  client: WorkstationClientSummary;
  notes: string;
  messages: MessageItem[];
  media: WorkstationMediaAsset[];
  professional_photos: WorkstationProfessionalPhotoVersion[];
}

export interface WorkstationCopyAllResponse {
  text: string;
}
