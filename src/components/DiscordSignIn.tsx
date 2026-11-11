import { DialogButton } from "@decky/ui";
import { t } from "../i18n";
import { IcCheckCircle, IcSmartphone, IcWarn } from "./Icons";
import { DiscordStartup } from "./DiscordStartup";
import { openCaptchaSolver } from "./CaptchaSolver";

const CaptchaBtn = DialogButton as any;

export const DiscordSignIn = ({ qr_login, qr_scanned, captcha_needed }: { qr_login?: string; qr_scanned?: boolean; captcha_needed?: boolean }) => {
  const qr = typeof qr_login === "string" && qr_login.length < 512 * 1024 && /^data:image\/(svg\+xml|png);base64,[A-Za-z0-9+/=]+$/.test(qr_login) ? qr_login : undefined;
  // Phone confirmation stays in Discord; the panel only presents its QR and
  // the existing controller-accessible verification surface when needed.
  return (
    <div style={{ display: "flex", flexDirection: "column", padding: "16px 4px", gap: 10 }}>
      <h2 style={{ margin: "0 0 4px", fontSize: 20, lineHeight: 1.3 }}>{t("not_connected")}</h2>
      {qr_scanned ? (
        // QR scanné → Discord attend la validation sur le téléphone.
        <div style={{ textAlign: "center", padding: "12px 0" }}>
          <div style={{ fontSize: 26, marginBottom: 8, display: "flex", gap: 8, justifyContent: "center" }}><IcSmartphone /><IcCheckCircle color="#23a55a" /></div>
          <p style={{ fontSize: 13, fontWeight: 600, margin: "0 0 4px" }}>{t("qr_scanned_title")}</p>
          <p style={{ fontSize: 11, opacity: 0.65, margin: 0, lineHeight: 1.4 }}>{t("qr_scanned_body")}</p>
        </div>
      ) : qr ? (
        <div style={{ textAlign: "center" }}>
          <p style={{ fontSize: 12, opacity: 0.8, margin: "4px 0 8px" }}>
            {t("qr_scan")}
          </p>
          <img src={qr} alt={t("qr_scan")} style={{ width: 160, height: 160, borderRadius: 8, background: "#fff", padding: 4 }} />
          <p style={{ fontSize: 11, opacity: 0.55, margin: "8px 0 0", lineHeight: 1.4 }}>
            {t("qr_explain")}
          </p>
        </div>
      ) : (
        <DiscordStartup compact />
      )}
      {captcha_needed && (
        // Discord a planté un CAPTCHA SUR sa page de login : tant qu'il n'est
        // pas résolu il n'émet aucun ticket, et le QR se régénère en boucle
        // sans le moindre indice (#37). On le dit, et on propose de le résoudre
        // ici même — le miroir de la page se pilote à la manette.
        <div style={{ marginTop: 10, padding: "8px 10px", borderRadius: 8, background: "rgba(255,204,68,0.10)", border: "1px solid rgba(255,204,68,0.35)" }}>
          <p style={{ fontSize: 12, color: "#ffcc44", margin: 0, lineHeight: 1.4 }}>
            <IcWarn /> {t("captcha_needed")}
          </p>
          <CaptchaBtn onClick={() => openCaptchaSolver()} style={{ marginTop: 8, width: "100%", minWidth: 0, whiteSpace: "normal", overflowWrap: "anywhere", minHeight: 40 }}>
            {t("captcha_open")}
          </CaptchaBtn>
        </div>
      )}
    </div>
  );
};

