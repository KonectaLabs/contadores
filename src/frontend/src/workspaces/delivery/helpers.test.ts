import { describe, expect, it } from "vitest";
import { shouldApplyLatestRequest } from "./helpers";

describe("shouldApplyLatestRequest", () => {
  it("blocks stale Delivery responses from replacing newer state", () => {
    expect(shouldApplyLatestRequest(1, 2)).toBe(false);
    expect(shouldApplyLatestRequest(2, 2)).toBe(true);
  });
});
