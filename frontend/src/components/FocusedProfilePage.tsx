import { useCallback, useEffect, useState } from "react";
import { api, ApiError, type Profile } from "../lib/api";
import { ProfileViewer } from "./ProfileViewer";
import "./focused-profile.css";

const noAction = () => {};
export function FocusedProfilePage({ profileId }: { profileId: string }) {
  const [profile, setProfile] = useState<Profile | null>(null);
  const [problem, setProblem] = useState("");
  const [connection, setConnection] = useState("");
  const [retry, setRetry] = useState(0);
  const [restartUrl, setRestartUrl] = useState<string | null>(null);
  useEffect(() => {
    let cancelled = false;
    void api.getRemoteViewContext(profileId).then(result => { if (!cancelled) setRestartUrl(result.restart_url); }).catch(() => {});
    return () => { cancelled = true; };
  }, [profileId]);
  useEffect(() => {
    let cancelled = false;
    let timer: ReturnType<typeof setTimeout>;
    const controller = new AbortController();
    const refresh = async () => {
      try {
        const next = await api.getProfile(profileId, AbortSignal.any([controller.signal, AbortSignal.timeout(15_000)]));
        if (!cancelled) { setProfile(next); setProblem(""); }
      } catch (error) {
        if (!cancelled) setProblem(error instanceof ApiError && error.status === 404 ? "此 Profile 已不存在，请返回 BAM 核对账号。" : "无法连接浏览器环境，请检查网络后重试。");
      } finally {
        if (!cancelled) timer = setTimeout(refresh, 3000);
      }
    };
    void refresh();
    return () => { cancelled = true; controller.abort(); clearTimeout(timer); };
  }, [profileId]);
  useEffect(() => {
    document.title = profile?.name ?? `Profile ${profileId}`;
  }, [profile?.name, profileId]);
  const onConnectionChange = useCallback((state: "connected" | "disconnected", message?: string) => {
    setConnection(state === "connected" ? "" : message ?? "画面连接已断开。");
  }, []);
  const running = profile?.status === "running";
  const overlay = problem || (profile && !running ? "Profile 已停止" : connection);
  return <main className="focused-profile" aria-label="Profile 专注画面">
    <div className="focused-profile-screen">
      {running && !problem && <ProfileViewer key={`${profileId}:${retry}`} profileId={profileId} cdpUrl={profile.cdp_url} clipboardSync={profile.clipboard_sync} onClipboardSyncChange={async () => {}} onDisconnect={noAction} onConnectionChange={onConnectionChange} focused />}
      {overlay && <div className="focused-profile-overlay" role="status"><div><h1>{overlay}</h1><p>{!running && profile ? "通过 BAM 重新启动此账号，代理准备好后会自动回到画面。" : "此标签页始终连接当前账号，不会切换到其他 Profile。"}</p>{restartUrl && <a className="btn-secondary" href={restartUrl}>重新启动</a>}{running && !problem && connection && <button className="btn-secondary" onClick={() => { setConnection(""); setRetry(value => value + 1); }}>重新连接画面</button>}</div></div>}
    </div>
  </main>;
}
