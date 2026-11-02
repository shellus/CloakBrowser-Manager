import { useCallback, useEffect, useState } from "react";
import { Maximize2, Minimize2 } from "lucide-react";
import { api, ApiError, type Profile } from "../lib/api";
import { ProfileViewer } from "./ProfileViewer";
import "./focused-profile.css";

const noAction = () => {};
export function FocusedProfilePage({ profileId }: { profileId: string }) {
  const [profile, setProfile] = useState<Profile | null>(null);
  const [problem, setProblem] = useState("");
  const [connection, setConnection] = useState("正在连接画面…");
  const [connected, setConnected] = useState(false);
  const [retry, setRetry] = useState(0);
  const [fullscreen, setFullscreen] = useState(false);
  const [notice, setNotice] = useState("");
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
  useEffect(() => {
    const change = () => setFullscreen(Boolean(document.fullscreenElement));
    document.addEventListener("fullscreenchange", change);
    return () => document.removeEventListener("fullscreenchange", change);
  }, []);
  const onConnectionChange = useCallback((state: "connected" | "disconnected", message?: string) => {
    setConnected(state === "connected");
    setConnection(state === "connected" ? "已连接" : message ?? "画面连接已断开。");
  }, []);
  const toggleFullscreen = async () => {
    try {
      if (document.fullscreenElement) await document.exitFullscreen();
      else await document.documentElement.requestFullscreen();
      setNotice("");
    } catch { setNotice("浏览器未允许全屏，可使用浏览器的全屏快捷键。"); }
  };
  const running = profile?.status === "running";
  const status = problem ? "环境连接中断" : !profile ? "正在确认 Profile…" : !running ? "Profile 已停止" : connection;
  const overlay = problem || (!profile ? "正在确认目标 Profile…" : !running ? "Profile 已停止" : !connected ? connection : "");
  return <main className="focused-profile" aria-label="Profile 专注画面">
    <header className="focused-profile-bar">
      <strong title={profile?.name ?? profileId}>{profile?.name ?? profileId}</strong>
      <span className={connected && !problem && running ? "focused-connected" : ""} role="status">{status}</span>
      <button type="button" onClick={() => void toggleFullscreen()} aria-label={fullscreen ? "退出全屏" : "进入全屏"} title={fullscreen ? "退出全屏" : "进入全屏"}>{fullscreen ? <Minimize2 size={16} /> : <Maximize2 size={16} />}</button>
    </header>
    <div className="focused-profile-screen">
      {running && !problem && <ProfileViewer key={`${profileId}:${retry}`} profileId={profileId} cdpUrl={profile.cdp_url} clipboardSync={profile.clipboard_sync} onClipboardSyncChange={async () => {}} onDisconnect={noAction} onConnectionChange={onConnectionChange} focused />}
      {overlay && <div className="focused-profile-overlay" role="status"><div><h1>{overlay}</h1><p>{!profile && !problem ? "正在读取此 Profile 的运行状态。" : !running && profile ? "请回到 BAM，点击此账号的“启动并打开”。" : "此标签页始终连接当前账号，不会切换到其他 Profile。"}</p>{running && !problem && !connected && connection !== "正在连接画面…" && <button className="btn-secondary" onClick={() => { setConnection("正在连接画面…"); setRetry(value => value + 1); }}>重新连接画面</button>}</div></div>}
    </div>
    {notice && <div className="focused-profile-notice" role="alert">{notice}</div>}
  </main>;
}
