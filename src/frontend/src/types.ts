export type LeadStage =
  | "awaiting_initial_reply"
  | "awaiting_video_reply"
  | "needs_human"
  | "calendly_sent"
  | "booked"
  | "closed"
  | "archived";

export type SourceMode = "testing" | "live";

export interface RuntimeSettings {
  enabled: boolean;
  source_mode: SourceMode;
  ready: boolean;
  readiness_issues: string[];
  testing_phone_configured: boolean;
  testing_name: string;
  sheet_configured: boolean;
  sheet_gid: string | null;
  sheet_poll_seconds: number;
  loom_url_configured: boolean;
  calendly_base_url: string;
  alert_emails: string[];
}

export type FunnelSourceMode = "testing" | "live";
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
  enabled: boolean;
  source_mode: FunnelSourceMode;
  test_phone: string;
  test_name: string;
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
  external_lead_id: string;
  phone: string;
  normalized_phone: string;
  full_name: string | null;
  email: string | null;
  platform: string | null;
  lead_status: string | null;
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
  automation_paused: boolean;
  automation_paused_reason: string | null;
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
  dispatch_after: string;
  sequence_step: string | null;
  strategy_step: string | null;
  strategy_id: string | null;
  strategy_label: string | null;
  media_type: string | null;
  media_path: string | null;
  media_caption: string | null;
  created_at: string;
}

export interface EventItem {
  id: number;
  lead_id: string | null;
  event_type: string;
  actor: string | null;
  summary: string;
  payload: Record<string, unknown>;
  created_at: string;
}

export interface LeadListResponse {
  metrics: ContadoresMetrics;
  config: ContadoresConfig;
  leads: LeadSummary[];
}

export interface LeadDetailResponse {
  lead: LeadSummary;
  config: ContadoresConfig;
  messages: MessageItem[];
  events: EventItem[];
}

export interface QuickActionResponse {
  lead: LeadSummary;
  queued_message_ids: number[];
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
