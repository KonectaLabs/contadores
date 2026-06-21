import { ArrowsClockwise, WarningCircle } from "@phosphor-icons/react";
import type { ReactNode } from "react";
import { compactNumber, humanize, relativeTime } from "../../format";
import type { PlatformOverviewResponse } from "../../types";

type OpsViewProps = {
  overview: PlatformOverviewResponse | null;
  loading: boolean;
  onRefresh: () => void;
  onOpenCrmLead: (leadId: string) => void;
  onOpenCampaigns: () => void;
  onOpenWorkstation: (clientId: string) => void;
};

export function OpsView({
  overview,
  loading,
  onRefresh,
  onOpenCrmLead,
  onOpenCampaigns,
  onOpenWorkstation,
}: OpsViewProps) {
  const counts = overview?.counts;
  const failedRuns = (overview?.agent_runs ?? []).filter((run) => run.status === "failed" || run.error);
  const failedToolCalls = (overview?.agent_tool_calls ?? []).filter((call) => call.status === "failed" || call.error);
  const blockedMetaAttempts = (overview?.meta_publish_attempts ?? []).filter((attempt) => (
    ["blocked", "failed", "error"].includes(attempt.status) || ["needs_preflight", "rejected"].includes(attempt.approval_status)
  ));
  const blockedInventory = (overview?.meta_inventory_snapshots ?? []).filter((snapshot) => (
    ["missing_credentials", "partial", "error", "blocked"].includes(snapshot.status)
  ));
  const pendingCampaigns = (overview?.ad_campaigns ?? []).filter((campaign) => (
    !["published", "closed", "archived"].includes(campaign.status) || !["approved", "published"].includes(campaign.approval_status)
  ));

  return (
    <section className="ops-workspace" aria-label="Ops action queue">
      <header className="ops-head">
        <div>
          <span>Ops</span>
          <strong>Action queue</strong>
          <small>{overview ? `Updated ${relativeTime(overview.generated_at)}` : "Platform overview"}</small>
        </div>
        <button type="button" className="ct-btn ct-btn-ghost" onClick={onRefresh} disabled={loading}>
          <ArrowsClockwise size={14} weight="bold" />
          Refresh
        </button>
      </header>

      <div className="ops-metrics" aria-label="Ops totals">
        <OpsMetric label="Active blockers" value={counts?.active_blockers ?? 0} tone="danger" />
        <OpsMetric label="Questions" value={counts?.open_human_questions ?? 0} tone="warn" />
        <OpsMetric label="Meta blocked" value={(counts?.blocked_meta_attempts ?? 0) + (counts?.blocked_meta_inventory ?? 0)} tone="warn" />
        <OpsMetric label="Failed runs" value={(counts?.failed_agent_runs ?? 0) + (counts?.failed_agent_tool_calls ?? 0)} tone="danger" />
        <OpsMetric label="Pending campaigns" value={counts?.pending_campaigns ?? 0} tone="muted" />
      </div>

      {!overview && loading ? (
        <section className="ops-panel">
          <strong>Loading Ops</strong>
          <p>Reading platform overview.</p>
        </section>
      ) : null}

      <div className="ops-grid">
        <OpsPanel title="Runtime blockers" count={overview?.runtime_alerts.length ?? 0}>
          {(overview?.runtime_alerts ?? []).map((alert) => (
            <OpsItem
              key={alert.id}
              title={`${alert.funnel_label || "Runtime"} · ${humanize(alert.alert_type)}`}
              meta={alert.created_at ? relativeTime(alert.created_at) : ""}
              body={alert.error || alert.fallback_action}
              action={alert.lead_id ? { label: "Open CRM", onClick: () => onOpenCrmLead(alert.lead_id) } : undefined}
            />
          ))}
        </OpsPanel>

        <OpsPanel title="Human questions" count={overview?.human_questions.length ?? 0}>
          {(overview?.human_questions ?? []).map((question) => (
            <OpsItem
              key={question.id}
              title={question.question}
              meta={[humanize(question.workflow), humanize(question.status), question.timeout_at ? `timeout ${relativeTime(question.timeout_at)}` : ""].filter(Boolean).join(" · ")}
              body={question.context_summary || question.trying_to_do || question.default_action}
              action={question.target_type === "lead" && question.target_id
                ? { label: "Open CRM", onClick: () => onOpenCrmLead(question.target_id) }
                : question.target_type === "client" && question.target_id
                  ? { label: "Open Build", onClick: () => onOpenWorkstation(question.target_id) }
                  : undefined}
            />
          ))}
        </OpsPanel>

        <OpsPanel title="Meta blockers" count={blockedMetaAttempts.length + blockedInventory.length}>
          {blockedMetaAttempts.map((attempt) => (
            <OpsItem
              key={attempt.id}
              title={`Publish ${attempt.id}`}
              meta={[humanize(attempt.status), humanize(attempt.approval_status)].join(" · ")}
              body={attempt.error || `Campaign ${attempt.campaign_id}`}
              action={attempt.campaign_id ? { label: "Open Ads", onClick: onOpenCampaigns } : undefined}
            />
          ))}
          {blockedInventory.map((snapshot) => (
            <OpsItem
              key={snapshot.id}
              title={`Inventory ${humanize(snapshot.status)}`}
              meta={[snapshot.source, snapshot.ad_account_id || snapshot.business_id].filter(Boolean).join(" · ")}
              body={snapshot.errors.length ? `${snapshot.errors.length} inventory errors` : "Inventory is not ready."}
            />
          ))}
        </OpsPanel>

        <OpsPanel title="Failed automation" count={failedRuns.length + failedToolCalls.length}>
          {failedRuns.map((run) => (
            <OpsItem
              key={run.id}
              title={`${humanize(run.agent_kind)} run ${run.id}`}
              meta={[humanize(run.status), run.stale ? "stale" : "", run.started_at ? relativeTime(run.started_at) : ""].filter(Boolean).join(" · ")}
              body={run.error || `${run.target_type} ${run.target_id}`}
            />
          ))}
          {failedToolCalls.map((call) => (
            <OpsItem
              key={call.id}
              title={call.tool_name}
              meta={[humanize(call.status), call.run_id].filter(Boolean).join(" · ")}
              body={call.error}
            />
          ))}
        </OpsPanel>

        <OpsPanel title="Pending campaigns" count={pendingCampaigns.length}>
          {pendingCampaigns.map((campaign) => (
            <OpsItem
              key={campaign.id}
              title={campaign.objective || campaign.id}
              meta={[humanize(campaign.status), humanize(campaign.approval_status), campaign.budget_daily_usd ? `${campaign.budget_currency} ${campaign.budget_daily_usd}/day` : ""].filter(Boolean).join(" · ")}
              body={[campaign.client_id, campaign.funnel_id].filter(Boolean).join(" · ")}
              action={{ label: "Open Ads", onClick: onOpenCampaigns }}
            />
          ))}
        </OpsPanel>

        <OpsPanel title="Recent events" count={overview?.events.length ?? 0}>
          {(overview?.events ?? []).map((event) => (
            <OpsItem
              key={event.id}
              title={event.summary || humanize(event.event_type)}
              meta={[event.source, event.target_type, event.created_at ? relativeTime(event.created_at) : ""].filter(Boolean).join(" · ")}
              body={event.target_id}
            />
          ))}
        </OpsPanel>
      </div>
    </section>
  );
}

function OpsMetric({ label, value, tone }: { label: string; value: number; tone: "danger" | "warn" | "muted" }) {
  return (
    <span className="ops-metric" data-tone={tone}>
      <strong>{compactNumber(value)}</strong>
      {label}
    </span>
  );
}

function OpsPanel({ title, count, children }: { title: string; count: number; children: ReactNode }) {
  return (
    <section className="ops-panel">
      <header>
        <strong>{title}</strong>
        <span>{compactNumber(count)}</span>
      </header>
      <div className="ops-list">
        {count ? children : (
          <div className="ops-empty">
            <WarningCircle size={16} weight="bold" />
            Clear
          </div>
        )}
      </div>
    </section>
  );
}

function OpsItem({
  title,
  meta,
  body,
  action,
}: {
  title: string;
  meta: string;
  body: string;
  action?: { label: string; onClick: () => void };
}) {
  return (
    <article className="ops-item">
      <div>
        <strong>{title || "Untitled"}</strong>
        {meta ? <span>{meta}</span> : null}
        {body ? <p>{body}</p> : null}
      </div>
      {action ? (
        <button type="button" className="ct-btn ct-btn-ghost" onClick={action.onClick}>
          {action.label}
        </button>
      ) : null}
    </article>
  );
}
