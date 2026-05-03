import type { LeadStage } from "./types";

const stageLabels: Record<LeadStage, string> = {
  awaiting_initial_reply: "First message",
  awaiting_video_reply: "Video sent",
  needs_human: "Manual",
  calendly_sent: "Calendly sent",
  booked: "Booked",
  closed: "Closed",
  archived: "Archived",
};

const readableLabels: Record<string, string> = {
  answered: "Answered",
  automation_paused: "Automation paused",
  booked: "Booked",
  calendly: "Calendly",
  calendly_sent: "Calendly sent",
  closed: "Closed",
  delivered: "Delivered",
  failed: "Failed",
  initial: "First message",
  loom: "Loom",
  manual_review: "Manual review",
  needs_human: "Manual",
  needs_human_alert_sent: "Manual alert sent",
  needs_human_handoff: "Manual handoff",
  needs_reply: "Needs reply",
  opener: "First message",
  post_loom_service_recap: "Service recap",
  queued: "Queued",
  read: "Read",
  sent: "Sent",
  video_check: "Video check",
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
  const normalized = value.trim().toLowerCase();
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
  return new Intl.DateTimeFormat("en", {
    month: "short",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
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
