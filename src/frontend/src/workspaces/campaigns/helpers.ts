export function shouldApplyGeoSearchResult(requestId: number, latestRequestId: number): boolean {
  return requestId === latestRequestId;
}

export function campaignStatusConfirmText(
  campaignName: string,
  currentStatus: string,
  nextStatus: string,
): { title: string; message: string; confirmLabel: string } {
  const cleanNextStatus = nextStatus.trim() || "draft";
  const statusNote = cleanNextStatus === "active"
    ? "Activating can make the public form and Delivery routing live."
    : cleanNextStatus === "paused"
      ? "Pausing keeps the public form available but stops active promotion."
      : "This changes the operator-facing campaign state.";

  return {
    title: `${humanizeStatus(cleanNextStatus)} campaign?`,
    message: `${campaignName} is currently ${humanizeStatus(currentStatus)}. Confirm changing it to ${humanizeStatus(cleanNextStatus)}. ${statusNote}`,
    confirmLabel: humanizeStatus(cleanNextStatus),
  };
}

function humanizeStatus(value: string): string {
  return value.replace(/[_-]+/g, " ").replace(/\b\w/g, (letter) => letter.toUpperCase());
}
