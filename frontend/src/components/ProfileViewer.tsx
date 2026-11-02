import { useEffect, useRef, useState } from "react";
import { ClipboardCopy, Maximize2, Minimize2 } from "lucide-react";
import { api } from "../lib/api";
import { CdpEndpointButton } from "./CdpEndpointButton";

interface ProfileViewerProps {
  profileId: string;
  cdpUrl: string | null;
  clipboardSync: boolean;
  onClipboardSyncChange: (enabled: boolean) => Promise<void>;
  onDisconnect: () => void;
  focused?: boolean;
  onConnectionChange?: (state: "connected" | "disconnected", message?: string) => void;
}

// X11 keysym for V key (Ctrl is already held in VNC by the time we intercept)
const XK_v = 0x0076;

export function ProfileViewer({
  profileId,
  cdpUrl,
  clipboardSync: initialClipboardSync,
  onClipboardSyncChange,
  onDisconnect,
  focused = false,
  onConnectionChange,
}: ProfileViewerProps) {
  const containerRef = useRef<HTMLDivElement>(null);
  const rfbRef = useRef<any>(null);
  const windowSizedRef = useRef(false);
  const [connected, setConnected] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [fullscreen, setFullscreen] = useState(false);
  const [clipboardSync, setClipboardSync] = useState(initialClipboardSync);

  useEffect(() => setClipboardSync(initialClipboardSync), [initialClipboardSync]);

  useEffect(() => {
    const container = containerRef.current;
    if (!focused || !connected || !container) return;
    let timer: ReturnType<typeof setTimeout>;
    let cancelled = false;
    let generation = 0;
    let pending = Promise.resolve();
    const observer = new ResizeObserver(() => {
      clearTimeout(timer);
      const current = ++generation;
      timer = setTimeout(() => {
        const width = Math.round(container.clientWidth), height = Math.round(container.clientHeight);
        if (width < 320 || height < 240) return;
        pending = pending.then(async () => {
          if (cancelled || current !== generation) return;
          try {
            await api.resizeViewer(profileId, width, height);
            if (!cancelled && current === generation) windowSizedRef.current = true;
          }
          catch { if (!cancelled) onConnectionChange?.("disconnected", "调整远端窗口失败，请重新连接画面。"); }
        });
      }, 600);
    });
    observer.observe(container);
    return () => { cancelled = true; clearTimeout(timer); observer.disconnect(); };
  }, [focused, connected, profileId, onConnectionChange]);

  useEffect(() => {
    let rfb: any = null;
    let cancelled = false;
    let frameTimer: ReturnType<typeof setTimeout>;
    windowSizedRef.current = false;
    if (focused) onConnectionChange?.("disconnected", "正在连接画面…");
    const connectTimeout = window.setTimeout(() => {
      if (!cancelled) {
        onConnectionChange?.("disconnected", "连接画面超时，请检查网络后重新连接。");
        rfb?.disconnect();
      }
    }, 30_000);

    async function connect() {
      try {
        // Import noVNC dynamically
        const { default: RFB } = await import("@novnc/novnc/core/rfb.js");

        if (cancelled) return;

        const protocol = window.location.protocol === "https:" ? "wss:" : "ws:";
        const wsUrl = `${protocol}//${window.location.host}/api/profiles/${profileId}/vnc`;

        rfb = new RFB(containerRef.current!, wsUrl, {
          wsProtocols: ["binary"],
        });
        rfbRef.current = rfb;

        rfb.scaleViewport = true;
        rfb.resizeSession = focused;
        rfb.showDotCursor = true;

        rfb.addEventListener("connect", () => {
          if (cancelled) return;
          setConnected(true);
          if (!focused) { clearTimeout(connectTimeout); onConnectionChange?.("connected"); return; }
          // The RFB handshake precedes the first framebuffer, and resizing clears
          // the canvas. Keep the loading cover until an actual pixel is painted
          // at the negotiated size; a transparent canvas is not a usable screen.
          const awaitFrame = () => {
            if (cancelled) return;
            const container = containerRef.current;
            const canvas = container?.querySelector("canvas");
            const sizeMatches = canvas && container && canvas.width === Math.round(container.clientWidth) && canvas.height === Math.round(container.clientHeight);
            const painted = windowSizedRef.current && sizeMatches && canvas.getContext("2d")?.getImageData(Math.floor(canvas.width / 2), Math.floor(canvas.height / 2), 1, 1).data[3];
            if (painted) { clearTimeout(connectTimeout); onConnectionChange?.("connected"); }
            else frameTimer = setTimeout(awaitFrame, 100);
          };
          frameTimer = setTimeout(awaitFrame, 100);
        });

        rfb.addEventListener("disconnect", () => {
          if (!cancelled) {
            setConnected(false);
            clearTimeout(frameTimer);
            clearTimeout(connectTimeout);
            onConnectionChange?.("disconnected", "画面连接已断开。");
            onDisconnect();
          }
        });

        rfb.addEventListener("securityfailure", (e: any) => {
          setError(`Security failure: ${e.detail.reason}`);
          onConnectionChange?.("disconnected", `画面认证失败：${e.detail.reason}`);
        });
      } catch (err) {
        if (!cancelled) {
          setError(err instanceof Error ? err.message : "Failed to connect");
          onConnectionChange?.("disconnected", err instanceof Error ? err.message : "连接画面失败。");
        }
      }
    }

    connect();

    return () => {
      cancelled = true;
      clearTimeout(frameTimer);
      clearTimeout(connectTimeout);
      if (rfb) {
        try {
          rfb.disconnect();
        } catch (err) {
          console.debug("[vnc] disconnect cleanup failed:", err);
        }
      }
      rfbRef.current = null;
    };
  }, [profileId, onDisconnect, onConnectionChange]);

  // Host→VNC: intercept Ctrl+V/Cmd+V at keydown (capture phase)
  // Must fire BEFORE noVNC's canvas listener to prevent the race condition
  useEffect(() => {
    const container = containerRef.current;
    if (!container || !clipboardSync || !connected) return;

    const handleKeyDown = async (e: KeyboardEvent) => {
      console.log("[clipboard] keydown:", e.key, "ctrl:", e.ctrlKey, "meta:", e.metaKey, "clipboardSync:", true);

      const isPaste =
        e.key === "v" && (e.ctrlKey || e.metaKey) && !e.altKey && !e.shiftKey;
      if (!isPaste) return;

      console.log("[clipboard] intercepted Ctrl+V");

      // Block noVNC from sending the keystroke before clipboard is updated
      e.stopPropagation();
      e.preventDefault();

      const rfb = rfbRef.current;
      if (!rfb) {
        console.log("[clipboard] no rfb ref, aborting");
        return;
      }

      try {
        const text = await navigator.clipboard.readText();
        console.log("[clipboard] host clipboard text:", text?.substring(0, 50), "len:", text?.length);
        if (text) {
          console.log("[clipboard] calling setClipboard API...");
          await api.setClipboard(profileId, text);
          console.log("[clipboard] setClipboard API success");
        }
      } catch (err) {
        console.warn("[clipboard] error:", err);
        setClipboardSync(false);
        return;
      }

      // Send full Ctrl+V sequence to VNC. We can't rely on Ctrl still being
      // held because the user may have released it during the async API call.
      console.log("[clipboard] sending Ctrl+V to VNC");
      rfb.sendKey(0xffe3, "ControlLeft", true);   // Ctrl press
      rfb.sendKey(XK_v, "KeyV", true);             // V press
      rfb.sendKey(XK_v, "KeyV", false);            // V release
      rfb.sendKey(0xffe3, "ControlLeft", false);   // Ctrl release
    };

    // capture: true ensures we fire before noVNC's canvas listener
    container.addEventListener("keydown", handleKeyDown, true);
    return () => container.removeEventListener("keydown", handleKeyDown, true);
  }, [profileId, clipboardSync, connected]);

  // VNC→Host: listen for noVNC "clipboard" event (fired when proxy converts
  // KasmVNC BinaryClipboard type 180 → standard ServerCutText type 3)
  useEffect(() => {
    const rfb = rfbRef.current;
    console.log("[clipboard] VNC→Host effect: rfb=", !!rfb, "sync=", clipboardSync, "connected=", connected);
    if (!rfb || !clipboardSync || !connected) return;

    const handleClipboard = (e: any) => {
      const text = e.detail?.text;
      console.log("[clipboard] VNC→Host event fired, text:", text?.substring(0, 50), "len:", text?.length);
      if (text) {
        navigator.clipboard.writeText(text).then(() => {
          console.log("[clipboard] writeText success");
        }).catch((err) => {
          console.warn("[clipboard] writeText failed:", err);
        });
      }
    };

    console.log("[clipboard] registering clipboard event listener on rfb");
    rfb.addEventListener("clipboard", handleClipboard);
    return () => {
      console.log("[clipboard] removing clipboard event listener");
      rfb.removeEventListener("clipboard", handleClipboard);
    };
  }, [clipboardSync, connected]);

  // VNC→Host polling: Chrome doesn't write to X11 clipboard under KasmVNC,
  // so type 180 events won't fire for Chrome copies. Poll via Playwright CDP.
  useEffect(() => {
    if (!clipboardSync || !connected) return;

    let cancelled = false;
    let lastText = "";

    const poll = async () => {
      if (cancelled) return;
      try {
        const { text } = await api.getClipboard(profileId);
        if (text && text !== lastText) {
          lastText = text;
          console.log("[clipboard] poll: new VNC clipboard:", text.substring(0, 50), "len:", text.length);
          await navigator.clipboard.writeText(text).catch((err) =>
            console.warn("[clipboard] poll writeText failed:", err)
          );
        }
      } catch (err) {
        console.warn("[clipboard] poll error, stopping:", err);
        cancelled = true;
        return;
      }
      if (!cancelled) {
        setTimeout(poll, 2000);
      }
    };

    // Start polling after a short delay
    const timer = setTimeout(poll, 2000);
    return () => {
      cancelled = true;
      clearTimeout(timer);
    };
  }, [profileId, clipboardSync, connected]);

  const toggleClipboardSync = async () => {
    const previous = clipboardSync;
    const next = !previous;
    setClipboardSync(next);
    try {
      await onClipboardSyncChange(next);
    } catch (err) {
      console.warn("[clipboard] failed to persist preference:", err);
      setClipboardSync(previous);
    }
  };

  const toggleFullscreen = () => {
    if (!containerRef.current) return;
    if (!document.fullscreenElement) {
      containerRef.current.requestFullscreen();
      setFullscreen(true);
    } else {
      document.exitFullscreen();
      setFullscreen(false);
    }
  };

  useEffect(() => {
    const handleFsChange = () => {
      setFullscreen(!!document.fullscreenElement);
    };
    document.addEventListener("fullscreenchange", handleFsChange);
    return () => document.removeEventListener("fullscreenchange", handleFsChange);
  }, []);

  useEffect(() => {
    const container = containerRef.current;
    if (!container) return;

    const handleWheel = (e: WheelEvent) => {
      e.preventDefault();
    };

    container.addEventListener("wheel", handleWheel, { passive: false });
    return () => container.removeEventListener("wheel", handleWheel);
  }, []);

  if (error && !focused) {
    return (
      <div className="flex items-center justify-center h-full">
        <div className="text-center">
          <p className="text-red-400 text-sm mb-2">Connection failed</p>
          <p className="text-gray-500 text-xs">{error}</p>
        </div>
      </div>
    );
  }

  return (
    <div className="relative h-full flex flex-col">
      {/* Toolbar */}
      {!focused && <div className="flex items-center justify-between px-3 py-1.5 bg-surface-1 border-b border-border">
        <div className="flex items-center gap-2">
          <span className={`h-2 w-2 rounded-full ${connected ? "bg-emerald-400" : "bg-yellow-400 animate-pulse"}`} />
          <span className="text-xs text-gray-400">
            {connected ? "Connected" : "Connecting..."}
          </span>
        </div>
        <div className="flex items-center gap-1">
          <CdpEndpointButton cdpUrl={cdpUrl} />
          <button
            onClick={toggleClipboardSync}
            className={`p-1 ${clipboardSync ? "text-accent" : "text-gray-500 hover:text-gray-300"}`}
            title={clipboardSync ? "Disable clipboard sync" : "Enable clipboard sync"}
          >
            <ClipboardCopy className="h-3.5 w-3.5" />
          </button>
          <button
            onClick={toggleFullscreen}
            className="text-gray-500 hover:text-gray-300 p-1"
            title={fullscreen ? "Exit fullscreen" : "Fullscreen"}
          >
            {fullscreen ? <Minimize2 className="h-3.5 w-3.5" /> : <Maximize2 className="h-3.5 w-3.5" />}
          </button>
        </div>
      </div>}

      {/* VNC canvas container */}
      <div
        ref={containerRef}
        className="flex-1 bg-black overflow-hidden"
        style={{ minHeight: 0 }}
      />
    </div>
  );
}
