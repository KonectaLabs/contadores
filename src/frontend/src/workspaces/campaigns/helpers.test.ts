import { describe, expect, it } from "vitest";
import { campaignStatusConfirmText, shouldApplyGeoSearchResult } from "./helpers";

describe("campaign helpers", () => {
  it("ignores stale geo search results", () => {
    expect(shouldApplyGeoSearchResult(3, 4)).toBe(false);
    expect(shouldApplyGeoSearchResult(4, 4)).toBe(true);
  });

  it("keeps campaign status changes behind explicit confirmation copy", () => {
    const text = campaignStatusConfirmText("June Leads", "paused", "active");

    expect(text.title).toBe("Active campaign?");
    expect(text.message).toContain("June Leads is currently Paused");
    expect(text.message).toContain("Confirm changing it to Active");
    expect(text.confirmLabel).toBe("Active");
  });
});
