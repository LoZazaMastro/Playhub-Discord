import { DialogButton, Focusable } from "@decky/ui";
import { call } from "@decky/api";
import { useEffect, useRef, useState } from "react";
import { FaMicrophoneAlt, FaMicrophoneAltSlash, FaHeadphonesAlt, FaPhoneSlash } from "react-icons/fa";
import { useSteamcordState } from "../hooks/useSteamcordState";
import { t } from "../i18n";
import { DANGER, ONLINE, focusHalo } from "./Styled";

const Button = DialogButton as any;

// Discord events remain the authority. No optimistic mute/deafen/leave state.
export function VoiceSession() {
  const state = useSteamcordState();
  const [pending, setPending] = useState<string | null>(null);
  const [error, setError] = useState(false);
  const [focus, setFocus] = useState<string | null>(null);
  const lock = useRef(false);
  const mounted = useRef(true);
  useEffect(() => { mounted.current = true; return () => { mounted.current = false; }; }, []);
  if (!state?.vc?.channel_id) return null;
  const act = async (method: string) => {
    if (lock.current) return;
    lock.current = true; setPending(method); setError(false);
    try {
      const result = await call<[], any>(method);
      if (result === false || result?.error) throw new Error("voice_action_failed");
    } catch { if (mounted.current) setError(true); }
    finally { lock.current = false; if (mounted.current) setPending(null); }
  };
  const actions = [
    { method: "toggle_mute", label: t(state.me?.is_muted ? "voice_unmute" : "voice_mute"),
      icon: state.me?.is_muted ? <FaMicrophoneAltSlash /> : <FaMicrophoneAlt />, active: !!state.me?.is_muted },
    { method: "toggle_deafen", label: t(state.me?.is_deafened ? "voice_listen" : "voice_deafen"),
      icon: <FaHeadphonesAlt />, active: !!state.me?.is_deafened },
    { method: "disconnect_vc", label: t("voice_leave"), icon: <FaPhoneSlash />, active: false },
  ];
  return <section aria-label={t("xv_call")} style={{ margin: "12px 0 16px", padding: "12px", borderRadius: 12,
    background: "rgba(255,255,255,.045)", border: "1px solid rgba(255,255,255,.09)", minWidth: 0 }}>
    <div style={{ display: "flex", gap: 7, alignItems: "center", color: ONLINE, fontSize: 11, fontWeight: 600, marginBottom: 4 }}>
      <span aria-hidden="true" style={{ width: 6, height: 6, background: ONLINE, borderRadius: "50%" }} />{t("voice_connected")}
    </div>
    <div style={{ fontWeight: 650, fontSize: 14, lineHeight: 1.4, overflowWrap: "anywhere" }}>{state.vc.channel_name || t("xv_call")}</div>
    {state.vc.guild_name && <div style={{ opacity: .6, fontSize: 11, marginTop: 2, overflowWrap: "anywhere" }}>{state.vc.guild_name}</div>}
    <Focusable flow-children="row" style={{ display: "flex", gap: 6, marginTop: 12 }}>
      {actions.map(action => <Button key={action.method} disabled={!!pending} aria-label={action.label}
        aria-pressed={action.method === "disconnect_vc" ? undefined : action.active} title={action.label}
        onClick={() => act(action.method)} noFocusRing
        onFocus={() => setFocus(action.method)} onBlur={() => setFocus(null)}
        onGamepadFocus={() => setFocus(action.method)} onGamepadBlur={() => setFocus(null)}
        style={{ flex: "1 1 0", minWidth: 0, minHeight: 50, padding: "8px 4px", margin: 0, borderRadius: 8,
          boxSizing: "border-box", display: "flex", flexDirection: "column", alignItems: "center", gap: 5,
          whiteSpace: "normal", overflowWrap: "anywhere", fontSize: 10, lineHeight: 1.25,
          background: action.active ? "rgba(237,66,69,.2)" : "rgba(255,255,255,.06)",
          color: action.active || action.method === "disconnect_vc" ? "#ff9698" : "#fff",
          ...focusHalo(DANGER, focus === action.method) }}>
          <span aria-hidden="true" style={{ fontSize: 17 }}>{action.icon}</span>{action.label}
        </Button>)}
    </Focusable>
    {error && <div role="alert" style={{ color: "#ff9698", fontSize: 12, marginTop: 9 }}>{t("voice_action_failed")}</div>}
  </section>;
}
