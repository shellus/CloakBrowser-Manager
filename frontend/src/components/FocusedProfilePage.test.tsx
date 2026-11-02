import { cleanup, render, screen, waitFor, fireEvent } from "@testing-library/react";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { FocusedProfilePage } from "./FocusedProfilePage";
import { api } from "../lib/api";

vi.mock("../lib/api", async (original) => ({ ...await original<typeof import("../lib/api")>(), api: { getProfile: vi.fn(), getRemoteViewContext: vi.fn() } }));
vi.mock("./ProfileViewer", () => ({ ProfileViewer: ({ profileId, onConnectionChange }: { profileId:string; onConnectionChange:(state:string)=>void }) => <div data-testid="viewer">{profileId}<button onClick={() => onConnectionChange("connected")}>connect</button><button onClick={() => onConnectionChange("disconnected")}>disconnect</button></div> }));
const profile = { id:"one", name:"person@example.test", status:"running", cdp_url:null, clipboard_sync:true };
beforeEach(() => { vi.mocked(api.getProfile).mockResolvedValue(profile as never); vi.mocked(api.getRemoteViewContext).mockResolvedValue({restart_url:"https://console.example.test/accounts/person%40example.test/remote-view"}); });
afterEach(() => { cleanup(); vi.restoreAllMocks(); });
it("pins the requested profile and title without management or switching controls", async () => {
 render(<FocusedProfilePage profileId="one" />);
 expect((await screen.findByTestId("viewer")).textContent).toContain("one");
 await waitFor(() => expect(document.title).toBe("person@example.test"));
 expect(screen.queryByLabelText("Profile sidebar")).toBeNull();
 expect(screen.queryByText("Launch")).toBeNull();
 expect(document.querySelector('header')).toBeNull();
 expect(screen.queryByRole('heading')).toBeNull();
 expect(screen.queryByLabelText('进入全屏')).toBeNull();
 fireEvent.click(screen.getByText("connect"));
 await waitFor(() => expect(screen.queryByText("正在连接画面…", {selector:"h1"})).toBeNull());
 fireEvent.click(screen.getByText("disconnect"));
 expect(screen.getByRole("heading").textContent).toBe("画面连接已断开。");
 expect(screen.getByText("重新连接画面")).toBeTruthy();
});
it("keeps a stopped target in place and sends the user back to BAM to launch", async () => {
 vi.mocked(api.getProfile).mockResolvedValue({...profile,status:"stopped"} as never);
 render(<FocusedProfilePage profileId="one" />);
 await waitFor(() => expect(screen.getByRole("heading").textContent).toBe("Profile 已停止"));
 expect(screen.queryByTestId("viewer")).toBeNull();
 expect(screen.getByRole("link", {name:"重新启动"}).getAttribute("href")).toBe("https://console.example.test/accounts/person%40example.test/remote-view");
 expect(screen.getByRole("link", {name:"重新启动"}).getAttribute("target")).toBeNull();
 expect(document.title).toBe("person@example.test");
});
