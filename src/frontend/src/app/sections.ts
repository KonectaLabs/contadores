import type { ReactNode } from "react";

export type ActiveSection = "ops" | "crm" | "campaigns" | "workstation" | "delivery";

export type OperationNavItem = {
  section: ActiveSection;
  label: string;
  icon: ReactNode;
};

const activeSections = new Set<ActiveSection>(["ops", "crm", "campaigns", "workstation", "delivery"]);

export function parseActiveSection(value: string | null): ActiveSection {
  if (value === "runner") {
    return "crm";
  }
  return activeSections.has(value as ActiveSection) ? value as ActiveSection : "crm";
}
