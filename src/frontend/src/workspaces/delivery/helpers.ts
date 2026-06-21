export function shouldApplyLatestRequest(requestId: number, latestRequestId: number): boolean {
  return requestId === latestRequestId;
}
