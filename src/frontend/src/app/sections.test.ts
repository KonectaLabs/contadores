import { describe, expect, it } from "vitest";
import { parseActiveSection } from "./sections";

describe("parseActiveSection", () => {
  it("keeps the ops workspace as a first-class stored section", () => {
    expect(parseActiveSection("ops")).toBe("ops");
  });

  it("maps old runner storage to CRM and ignores unknown values", () => {
    expect(parseActiveSection("runner")).toBe("crm");
    expect(parseActiveSection("missing")).toBe("crm");
  });
});
