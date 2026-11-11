import { DialogButton } from "@decky/ui";
import { call } from "@decky/api";
import { useEffect, useRef, useState } from "react";
import { FaDiscord } from "react-icons/fa";
import { connectionFailed, connectionStarted, retryConnectionStarted, type BridgeStatus } from "../connectionDeadline";
import { t } from "../i18n";

const Button = DialogButton as any;
function bounded<T>(operation: Promise<T>, milliseconds: number): Promise<T> {
  return new Promise((resolve, reject) => {
    const timer = setTimeout(() => reject(new Error("Discord connection timed out")), milliseconds);
    operation.then(value => { clearTimeout(timer); resolve(value); }, error => { clearTimeout(timer); reject(error); });
  });
}

export function DiscordStartup({ compact = false }: { compact?: boolean }) {
  const [clock, setClock] = useState(Date.now);
  const [status, setStatus] = useState<BridgeStatus>();
  const [failures, setFailures] = useState(0);
  const [busy, setBusy] = useState(false);
  const alive = useRef(false);
  const inFlight = useRef(false);
  const retrying = useRef(false);
  const started = connectionStarted();
  useEffect(() => {
    alive.current = true;
    const poll = async () => {
      if (inFlight.current) return;
      inFlight.current = true;
      try {
        const result = await bounded(call<[], BridgeStatus>("get_bridge_status"), 2000);
        if (alive.current) { setStatus(result); setFailures(0); }
      } catch { if (alive.current) setFailures(value => value + 1); }
      finally { inFlight.current = false; if (alive.current) setClock(Date.now()); }
    };
    void poll();
    const timer = setInterval(() => { setClock(Date.now()); void poll(); }, 2000);
    return () => { alive.current = false; clearInterval(timer); };
  }, []);
  const failed = connectionFailed(clock - started, failures, status);
  const retry = async () => {
    if (retrying.current) return;
    retrying.current = true; setBusy(true);
    try {
      const result = await bounded(call<[], { ok: boolean }>("retry_connection"), 8000);
      if (alive.current) {
        if (result?.ok) { retryConnectionStarted(); setClock(Date.now()); setFailures(0); setStatus(undefined); }
        else setFailures(2);
      }
    } catch { if (alive.current) setFailures(2); }
    finally { retrying.current = false; if (alive.current) setBusy(false); }
  };
  return <div style={{ minWidth: 0, padding: compact ? "8px 0" : "24px 8px", display: "flex", flexDirection: "column", gap: 14, alignItems: "center", textAlign: "center" }}>
    {!compact && <FaDiscord size={32} aria-hidden="true" />}
    <p role={failed ? "alert" : "status"} style={{ margin: 0, fontSize: 14, lineHeight: 1.5 }}>
      {t(failed ? "connection_failed" : compact ? "qr_loading" : "initializing")}
    </p>
    {failed && <Button disabled={busy} onClick={() => void retry()} style={{ width: "100%", maxWidth: "100%", minWidth: 0, minHeight: 40, whiteSpace: "normal", overflowWrap: "anywhere" }}>
      {t(busy ? "connection_retrying" : "connection_retry")}
    </Button>}
  </div>;
}
