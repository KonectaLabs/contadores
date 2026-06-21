import type { CSSProperties, PointerEvent as ReactPointerEvent, ReactNode, RefObject } from "react";

import { compactNumber } from "../../format";
import type { ContadoresMetrics, LeadStage, StrategyStatsItem } from "../../types";

type LeadViewFilterValue = LeadStage | "all" | "manual_attention";
type LeadViewFilterOption = {
  value: LeadViewFilterValue;
  label: string;
  metric?: keyof ContadoresMetrics;
  tone: "all" | "neutral" | "accent" | "success" | "warn" | "muted";
};
type StrategyFilter = {
  step: string;
  strategyId: string;
};

export type CrmWorkspaceProps = {
  setupBanner: ReactNode;
  isInboxFunnel: boolean;
  crmHeroTitle: string;
  crmHeroDetail: string;
  crmModeLabel: string;
  crmHeroMetrics: Array<{ label: string; value: number }>;
  activeLeadViewLabel: string;
  activeCrmFilterCount: number;
  onClearCrmFilters: () => void;
  leadViewFilters: LeadViewFilterOption[];
  leadViewFilter: LeadViewFilterValue;
  onLeadViewFilterChange: (value: LeadViewFilterValue) => void;
  metrics: ContadoresMetrics | null;
  strategyStats: StrategyStatsItem[];
  strategyFilter: StrategyFilter;
  onStrategyFilterChange: (value: StrategyFilter) => void;
  tagOptions: string[];
  tagFilter: string;
  onTagFilterChange: (value: string) => void;
  formatStrategyLabel: (value: string | null | undefined) => string;
  workspaceRef: RefObject<HTMLDivElement | null>;
  crmLeadsWidth: number;
  crmLeadListTitle: string;
  visibleCount: number;
  crmLeadListSummary: string;
  allVisibleSelected: boolean;
  hasVisibleLeads: boolean;
  onToggleAllVisibleLeads: () => void;
  selectedVisibleCount: number;
  actionBusy: string | null;
  onOpenBulkAction: () => void;
  leadList: ReactNode;
  onStartResize: (event: ReactPointerEvent<HTMLButtonElement>) => void;
  detailHeader: ReactNode;
  pausedBanner: ReactNode;
  campaignRoutingPanel: ReactNode;
  messageTimeline: ReactNode;
  manualDockOpen: boolean;
  manualDock: ReactNode;
};

export function CrmWorkspace({
  setupBanner,
  isInboxFunnel,
  crmHeroTitle,
  crmHeroDetail,
  crmModeLabel,
  crmHeroMetrics,
  activeLeadViewLabel,
  activeCrmFilterCount,
  onClearCrmFilters,
  leadViewFilters,
  leadViewFilter,
  onLeadViewFilterChange,
  metrics,
  strategyStats,
  strategyFilter,
  onStrategyFilterChange,
  tagOptions,
  tagFilter,
  onTagFilterChange,
  formatStrategyLabel,
  workspaceRef,
  crmLeadsWidth,
  crmLeadListTitle,
  visibleCount,
  crmLeadListSummary,
  allVisibleSelected,
  hasVisibleLeads,
  onToggleAllVisibleLeads,
  selectedVisibleCount,
  actionBusy,
  onOpenBulkAction,
  leadList,
  onStartResize,
  detailHeader,
  pausedBanner,
  campaignRoutingPanel,
  messageTimeline,
  manualDockOpen,
  manualDock,
}: CrmWorkspaceProps) {
  return (
    <div className="ct-surface" data-crm-mode="crm">
      {setupBanner}
      {!isInboxFunnel ? (
        <section className="ct-simple-head ct-crm-hero" data-mode="crm">
          <div className="ct-simple-title">
            <span>CRM</span>
            <strong>{crmHeroTitle}</strong>
            <small>{crmHeroDetail}</small>
          </div>
          <div className="ct-simple-metrics" aria-label={`${crmModeLabel} metrics`}>
            {crmHeroMetrics.map((item) => (
              <span key={item.label}>
                <strong>{compactNumber(item.value)}</strong>
                {item.label}
              </span>
            ))}
          </div>
        </section>
      ) : null}

      {!isInboxFunnel ? (
        <div className="ct-queue-bar">
          <section className="ct-lead-filter-bar" aria-labelledby="ctLeadStateLabel">
            <div className="ct-lead-filter-head">
              <div>
                <span id="ctLeadStateLabel">State</span>
                <strong>{activeLeadViewLabel}</strong>
              </div>
              {activeCrmFilterCount ? (
                <button type="button" className="ct-filter-clear" onClick={onClearCrmFilters}>
                  Clear filters
                </button>
              ) : null}
            </div>
            <div className="ct-lead-state-strip" role="group" aria-label="Lead state filters">
              {leadViewFilters.map((filter) => {
                const count = Number(metrics?.[filter.metric ?? "total"] ?? 0);
                const isActiveFilter = leadViewFilter === filter.value;

                return (
                  <button
                    key={filter.value}
                    type="button"
                    className={`ct-lead-view ${isActiveFilter ? "active" : ""}`}
                    data-tone={filter.tone}
                    aria-pressed={isActiveFilter}
                    onClick={() => onLeadViewFilterChange(filter.value)}
                  >
                    <span className="ct-lead-view-count">{compactNumber(count)}</span>
                    <span className="ct-lead-view-label">{filter.label}</span>
                  </button>
                );
              })}
            </div>
          </section>

          {strategyStats.length || tagOptions.length ? (
            <section className="ct-filter-board" aria-label="Lead filters">
              {strategyStats.length ? (
                <div className="ct-filter-row">
                  <span className="ct-filter-row-label">Strategies</span>
                  <div className="ct-filter-strip" role="group" aria-label="Strategy filters">
                    <button
                      type="button"
                      className={`ct-strategy-filter-btn ${!strategyFilter.step && !strategyFilter.strategyId ? "active" : ""}`}
                      onClick={() => onStrategyFilterChange({ step: "", strategyId: "" })}
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
                          onClick={() => onStrategyFilterChange({ step: item.step, strategyId: item.strategy_id })}
                        >
                          {formatStrategyLabel(item.step)}: {item.strategy_label || formatStrategyLabel(item.strategy_id)}
                        </button>
                      );
                    })}
                  </div>
                </div>
              ) : null}

              {tagOptions.length ? (
                <div className="ct-filter-row">
                  <span className="ct-filter-row-label">Tags</span>
                  <div className="ct-filter-strip" role="group" aria-label="Tag filters">
                    <button
                      type="button"
                      className={`ct-strategy-filter-btn ${!tagFilter ? "active" : ""}`}
                      onClick={() => onTagFilterChange("")}
                    >
                      All tags
                    </button>
                    {tagOptions.map((tag) => (
                      <button
                        type="button"
                        className={`ct-strategy-filter-btn ${tagFilter === tag ? "active" : ""}`}
                        key={tag}
                        onClick={() => onTagFilterChange(tag)}
                      >
                        #{tag}
                      </button>
                    ))}
                  </div>
                </div>
              ) : null}
            </section>
          ) : null}
        </div>
      ) : null}

      <div
        className="ct-workspace ct-workspace-resizable"
        ref={workspaceRef}
        style={{ "--crm-leads-width": `${crmLeadsWidth}px` } as CSSProperties}
      >
        <aside className="ct-leads">
          <div className="ct-leads-head">
            <h3>{crmLeadListTitle}</h3>
            <p className="ct-leads-summary">{visibleCount ? `${visibleCount}` : crmLeadListSummary}</p>
          </div>
          <div className="ct-bulk-toolbar">
            <label className="ct-bulk-check">
              <input
                type="checkbox"
                checked={allVisibleSelected}
                disabled={!hasVisibleLeads}
                onChange={onToggleAllVisibleLeads}
              />
              <span>{allVisibleSelected ? "All visible selected" : "Select visible"}</span>
            </label>
            <button
              type="button"
              className="ct-btn ct-btn-ghost"
              disabled={!selectedVisibleCount || Boolean(actionBusy)}
              onClick={onOpenBulkAction}
            >
              Bulk action
            </button>
          </div>
          {leadList}
        </aside>

        <button
          type="button"
          className="ct-workspace-resizer"
          aria-label="Resize lead list"
          onPointerDown={onStartResize}
        />

        <section className="ct-detail">
          {detailHeader}
          {pausedBanner}
          {campaignRoutingPanel}
          <section className="ct-message-pane">{messageTimeline}</section>
          <details className="ct-manual-disclosure" open={manualDockOpen}>
            <summary>Operator message</summary>
            {manualDock}
          </details>
        </section>
      </div>
    </div>
  );
}
