import type { LeadStage } from "./types";

const stageLabels: Record<LeadStage, string> = {
  awaiting_initial_reply: "New",
  awaiting_video_reply: "Offer",
  needs_human: "Operator queue",
  calendly_sent: "Meeting",
  booked: "Converted",
  closed: "Closed",
  archived: "Archived",
};

const readableLabels: Record<string, string> = {
  answered: "Answered",
  automation_paused: "Automation paused",
  booked: "Converted",
  calendly: "Meeting",
  calendly_intro: "Meeting intro",
  calendly_link: "Meeting link",
  calendly_sent: "Meeting",
  calendly_url: "Meeting link",
  closed: "Closed",
  converted: "Converted",
  delivered: "Delivered",
  failed: "Failed",
  form: "Form",
  general_inbox: "General inbox",
  initial: "First message",
  loom: "Loom",
  loom_intro: "Loom intro",
  loom_mp4: "WhatsApp video",
  loom_video: "Loom video",
  manual_booked: "Marked converted manually",
  manual_converted: "Marked converted manually",
  manual_calendly_send: "Manual meeting send",
  manual_message: "Manual message",
  manual_pause: "Paused manually",
  meeting_scheduled: "Meeting scheduled",
  manual_ping_template: "Manual ping template",
  manual_review: "Manual review",
  manual_send_loom: "Manual offer send",
  manual_send_manual_ping: "Manual ping",
  manual_send_opener: "Manual opener send",
  manual_send_video_check: "Manual offer check",
  needs_human: "Manual",
  needs_human_alert_sent: "Manual alert sent",
  needs_human_handoff: "Manual handoff",
  needs_reply: "Needs reply",
  opener: "First message",
  opener_followup_24h: "24h opener follow-up",
  opener_followup_24h_template_retry_20260424: "24h opener follow-up retry",
  post_calendly_inbound: "Reply after meeting",
  queued: "Queued",
  read: "Read",
  sent: "Sent",
  text_offer: "Text offer",
  text_offer_599: "Text offer 599",
  video_check: "Offer check",
  whatsapp: "WhatsApp",
  whatsapp_ctwa: "Click-to-WhatsApp",
  whatsapp_funnel: "WhatsApp funnel",
  whatsapp_general: "General WhatsApp",
};

export function stageLabel(stage: LeadStage | string | null | undefined): string {
  if (!stage) {
    return "No status";
  }
  return stageLabels[stage as LeadStage] ?? humanize(stage);
}

export function humanize(value: string | null | undefined): string {
  if (!value) {
    return "-";
  }
  const normalized = value.trim().toLowerCase().replace(/-+/g, "_");
  if (readableLabels[normalized]) {
    return readableLabels[normalized];
  }
  return value
    .replace(/[_-]+/g, " ")
    .replace(/\s+/g, " ")
    .trim()
    .replace(/\b\w/g, (letter) => letter.toUpperCase());
}

export function shortDate(value: string | null | undefined): string {
  if (!value) {
    return "-";
  }
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) {
    return value;
  }
  const options: Intl.DateTimeFormatOptions = {
    month: "short",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
  };
  if (date.getFullYear() !== new Date().getFullYear()) {
    options.year = "numeric";
  }
  return new Intl.DateTimeFormat("en", {
    ...options,
  }).format(date);
}

export function relativeTime(value: string | null | undefined): string {
  if (!value) {
    return "No activity";
  }
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) {
    return "No data";
  }
  const seconds = Math.round((date.getTime() - Date.now()) / 1000);
  const absolute = Math.abs(seconds);
  const units: [Intl.RelativeTimeFormatUnit, number][] = [
    ["day", 86400],
    ["hour", 3600],
    ["minute", 60],
  ];
  const formatter = new Intl.RelativeTimeFormat("en", { numeric: "auto" });
  for (const [unit, size] of units) {
    if (absolute >= size) {
      return formatter.format(Math.round(seconds / size), unit);
    }
  }
  return formatter.format(seconds, "second");
}

export function compactNumber(value: number): string {
  return new Intl.NumberFormat("en", { maximumFractionDigits: 1 }).format(value);
}

export function lastInteractionAt(lead: { last_inbound_at: string | null; last_outbound_at: string | null; created_at: string }): string {
  const dates = [lead.last_inbound_at, lead.last_outbound_at, lead.created_at]
    .filter(Boolean)
    .map((item) => new Date(item as string))
    .filter((item) => !Number.isNaN(item.getTime()));
  if (!dates.length) {
    return lead.created_at;
  }
  return new Date(Math.max(...dates.map((item) => item.getTime()))).toISOString();
}
