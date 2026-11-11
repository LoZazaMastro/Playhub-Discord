export type BridgeStatus = { ready: boolean; clientReady?: boolean; enabled?: boolean };
export function connectionFailed(elapsed: number, failures: number, status?: BridgeStatus) {
  return elapsed >= 20_000 || failures >= 2 || status?.ready === false && elapsed >= 6_000;
}
let started = 0;
export function connectionStarted(now = Date.now()) { if (!started) started = now; return started; }
export function retryConnectionStarted(now = Date.now()) { started = now; return started; }
export function connectionCompleted() { started = 0; }
export function connectionProgress(state?: { loaded?: boolean; logged_in?: boolean; qr_login?: unknown; qr_scanned?: boolean; captcha_needed?: boolean } | null) {
  if (state?.loaded && (state.logged_in || state.qr_login || state.qr_scanned || state.captcha_needed)) connectionCompleted();
}
