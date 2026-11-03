<p align="center">
<img src="https://i.imgur.com/cqkp6fG.png" width="500" alt="CloakBrowser">
</p>

<h3 align="center">Browser Profile Manager for CloakBrowser</h3>

<p align="center">
A self-hosted browser for managing unlimited accounts and profiles,<br>
each one a genuinely separate machine: its own fingerprint, GPU, proxy, cookies, and history.<br>
Powered by CloakBrowser, the stealth engine that passes Cloudflare Turnstile, reCAPTCHA v3, FingerprintJS and BrowserScan.<br>
The identities don't just look different. They hold up.
</p>

<p align="center">
Self-hosted alternative to Multilogin, GoLogin, and AdsPower.<br>
Start free with one concurrent browser, scale to more on a paid plan.
</p>

<p align="center">
<a href="https://github.com/CloakHQ/CloakBrowser"><img src="https://img.shields.io/github/stars/cloakhq/cloakbrowser?label=CloakBrowser" alt="Stars"></a>
<a href="https://hub.docker.com/r/cloakhq/cloakbrowser-manager"><img src="https://img.shields.io/docker/pulls/cloakhq/cloakbrowser-manager?label=docker&logo=docker&logoColor=white" alt="Docker Pulls"></a>
<a href="LICENSE"><img src="https://img.shields.io/badge/license-MIT-blue" alt="License"></a>
</p>

---

<p align="center">
<img src="https://raw.githubusercontent.com/CloakHQ/CloakBrowser-Manager/main/assets/manager-macos.png" width="800" alt="CloakBrowser Manager on macOS">
</p>

Open a profile and you don't get a new tab, you get a different computer: its own browser fingerprint, GPU, screen, timezone, proxy, cookies, and history. Nothing bleeds between profiles, so your accounts never link back to each other, or to you. Close a profile and reopen it next day, it's the same person, warmed up and ready.

Windows and macOS launch browsers directly in native desktop windows; Linux keeps the Docker/KasmVNC server experience.

### Windows and macOS

Download the installer from the [latest release](https://github.com/CloakHQ/CloakBrowser-Manager/releases) and run it:

- **macOS** — open the `.dmg` and drag **CloakBrowser Manager** into Applications. (Unsigned during early access — on first launch, run `xattr -rc "/Applications/CloakBrowser Manager.app"` in Terminal, or approve it under **System Settings → Privacy & Security → Open Anyway**.)
- **Windows** — run the setup `.exe`. (Unsigned during early access — if SmartScreen warns, click **More info → Run anyway**.)

No Python, Node, or git required. The Manager starts on `127.0.0.1:8080` and opens in your default browser. On first launch it downloads the CloakBrowser engine. Profiles are stored in `%LOCALAPPDATA%\CloakBrowser Manager` on Windows and `~/Library/Application Support/CloakBrowser Manager` on macOS; a `logs/manager.log` in that folder records what happened if you need it.

Open **Settings** (gear icon, top right) to add your license key and pick the Stable or Preview channel.

#### Run from source (developers)

```bash
git clone https://github.com/CloakHQ/CloakBrowser-Manager.git
cd CloakBrowser-Manager
./run-macos.sh      # macOS  (or run-windows.bat on Windows)
```

This path requires Python 3.10+ and Node 18+; the first run creates a local Python environment, installs dependencies, and builds the React UI before starting the Manager.

### Import existing BAM Windows profiles

The opt-in `bam-windows` launch mode preserves BAM's native Chromium arguments
and uses a copied, pinned Runtime Store package. It skips the CloakBrowser Python
launch wrapper, first-run bookmarks/search setup, viewport/GPU overrides and
automatic engine updates. Standard Manager profiles keep their existing behavior.

Run under the **same Windows user** that owns BAM's encrypted browser data. Stop
the source profile first; the importer only copies and never repairs or modifies
the source. Keep source and imported identities from running at the same time.

```powershell
.venv\Scripts\python -m backend.import_bam --runtime-root <bam-runtime-root> --profile-id <id> --data-dir <manager-data-dir> --proxy <account-loopback-proxy>
.\scripts\windows-host.ps1 -Install -DataDirectory <manager-data-dir> -Port <manager-port>
```

The import copies complete user data (including Local State and encrypted
cookies), the active browser package, unpacked extensions and original metadata
(including latitude/longitude and environment locks). It derives the seed using
BAM's original Profile ID, verifies file hashes, rejects running/duplicate imports
and stores the mapping in the copied profile's `bam-import.json`. The Manager UUID
does not replace that original fingerprint identity. Runtime packages are shared
between imports of the same version; each import pins its own extension copy.

Profiles that have never created a user-data directory import their metadata and
initialize browser data on first launch. Existing data must have a normal exit
(`Normal` or Windows `SessionEnded`); crash markers are rejected. Session exit
markers are copied verbatim, without repairing or changing the source.

Set `AUTH_TOKEN` in the ignored `.env`. The scheduled task runs at user logon with
an interactive token, serves only loopback and restarts a failed Manager process.
It does not run in Windows service session 0. A logged-in desktop is required.
Reinstalling the task updates its data directory and port. Use
`Get-ScheduledTask -TaskName CloakBrowser-Manager-Windows` to inspect it.

Imported profiles honor seed, name, locale, timezone and proxy (including the
shared `proxy_chain` implementation when enabled). Manager GPU/screen emulation,
advanced launch arguments and extension overrides do not apply in this mode;
the pinned BAM runtime and extension copies define those settings. Launch checks
that the original profile is stopped and that the pinned executable is unchanged.
Keep this mode on Windows with local storage. Moving it to another OS/user or
using registry storage is outside the import contract.

### Linux server

```bash
docker run -p 127.0.0.1:8080:8080 -v cloakprofiles:/data cloakhq/cloakbrowser-manager
```

Or build from source:

```bash
git clone https://github.com/CloakHQ/CloakBrowser-Manager.git
cd CloakBrowser-Manager
docker compose up --build
```

Open [http://localhost:8080](http://localhost:8080), create a profile, and click Launch.

> **Early alpha** — this project is under active development. Expect bugs. If you find one, please [open an issue](https://github.com/CloakHQ/CloakBrowser-Manager/issues) and attach the log so we can help. On Windows/macOS it's `logs/manager.log` in the data folder (`%LOCALAPPDATA%\CloakBrowser Manager` / `~/Library/Application Support/CloakBrowser Manager`); on Linux/Docker use `docker logs <container>`.

## CloakBrowser license key

The Manager runs on the CloakBrowser engine, so it needs a key.<br>
[Get a free one with GitHub](https://cloakbrowser.dev/free) to run one profile at a time on the current build.<br>
[Paid plans](https://cloakbrowser.dev) raise how many profiles run at the same time, from a handful to thousands.

Add your key once and every profile uses it.

**Native app (Windows/macOS):** open **Settings** (gear icon, top right), paste your key, choose the Stable or Preview channel, and Save. It applies immediately, no restart. The badge in the top bar shows which tier and binary version are active.

**Docker:** open **Settings** (gear icon, top right) the same way, paste your key, and Save. It applies immediately and is stored in the mounted `/data` volume, so it persists across restarts and image updates. For automated or headless setups, pass it at `docker run` instead:

```bash
docker run -p 127.0.0.1:8080:8080 -v cloakprofiles:/data \
  -e CLOAKBROWSER_LICENSE_KEY=cb_your_key_here \
  -e CLOAKBROWSER_RELEASE_CHANNEL=preview \
  cloakhq/cloakbrowser-manager
```

**Run from source (or `docker compose`):** set it in a manager-root `.env`:

```bash
cp .env.example .env
```

```bash
# .env
CLOAKBROWSER_LICENSE_KEY=cb_your_key_here
CLOAKBROWSER_RELEASE_CHANNEL=stable   # or: preview
```

The file is loaded automatically at startup (`docker compose` reads it too); restart the Manager after changing it. An environment variable overrides the in-app setting.

## Why Not a Cloud Anti-Detect Browser?

The popular anti-detect browsers solve the fingerprint, then hand you a new problem: every account you own, every cookie, every session, sits on someone else's servers. And the disguise increasingly doesn't survive real detection, shortcuts in how fingerprints are faked, GPU and WebGL values that don't add up, identities that pass a test page and fail the real site.

CloakBrowser Manager runs on your own machine, and every profile inherits the CloakBrowser engine, so the identities actually hold up.

| | Typical cloud anti-detect browser | **CloakBrowser Manager** |
|---|---|---|
| Pricing model | Per profile + per seat, forced up-tiering | **Flat by concurrency, unlimited profiles** |
| Where profiles live | Their cloud | **Your machine** |
| Fingerprinting | JS-injected into a stock browser | **Source-level C++ patched engine** |
| The app | Closed box | **Open-source GUI (MIT)** |
| Native desktop windows | Rare | **Windows + macOS** |
| Automation API | Add-on / higher tier | **CDP built in, every profile** |
| Cost of idle accounts | Counts against your limit | **Free** |

## Features

- **Unlimited profiles, no per-profile tax** — create as many identities as you want. You pay only for how many run at the same time, not how many you keep. Dormant accounts cost nothing.
- **Each profile is a different machine** — its own fingerprint seed, GPU family, screen, cookies, localStorage, cache, and history, persistent across restarts
- **Per-profile network and locale** — proxy, GeoIP, timezone, locale, and screen, per profile; timezone and language follow the proxy exit IP automatically
- **Platform-aware hardware profiles** — automatic Apple Silicon selection and configurable Windows GPU families, coherent within each profile
- **Profile organization** — create, search, tag, edit, auto-launch, and delete profiles
- **Platform-native browsing** — Windows and macOS profiles open in normal desktop windows
- **Linux server viewing** — interact with Docker-launched browsers through KasmVNC in the web GUI
- **Playwright/Puppeteer API** — connect to any running profile through CDP while watching the same session live
- **Humanized interaction** — optional human-like mouse, keyboard, and scrolling behavior
- **Compatibility controls** — unpacked extensions, third-party-cookie support, and advanced Chromium arguments
- **Clipboard sync** — copy and paste between the Manager and Linux VNC browser profiles
- **License and system status** — see the active tier, binary version, and Windows font health in the top bar
- **Optional authentication** — protect the web UI and API with a single token, or run locally without authentication
- **Powered by CloakBrowser** — the identities don't just look different, they hold up: a source-level C++ patched Chromium engine tested against Cloudflare Turnstile, reCAPTCHA v3, FingerprintJS, and BrowserScan

## Stack

- **Backend**: FastAPI (Python)
- **Frontend**: React + Tailwind CSS
- **Browser viewer**: native windows on Windows/macOS; noVNC/KasmVNC on Linux Docker
- **Database**: SQLite
- **Browser engine**: [CloakBrowser](https://github.com/CloakHQ/CloakBrowser) (stealth Chromium binary)

## Development

### Native backend

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r backend/requirements.txt
uvicorn backend.main:app --reload --host 127.0.0.1 --port 8080
```

### Frontend

```bash
cd frontend
npm install
npm run dev
```

### Docker

```bash
docker compose up --build
```

## Requirements

- Windows or macOS native: Python 3.10+, Node.js 18+
- Linux server: Docker 20.10+
- ~2 GB disk (application + browser binary)
- ~512 MB RAM per running profile

## Updating

### Windows and macOS

Pull the latest source and run the platform launcher again. It installs changed dependencies and rebuilds the interface automatically.

```bash
git pull
```

```text
Windows: run-windows.bat
macOS:   ./run-macos.sh
```

### Linux server

Pull the latest image and recreate the container:

```bash
docker pull cloakhq/cloakbrowser-manager
docker stop <container-id>
docker rm <container-id>
docker run -p 127.0.0.1:8080:8080 -v cloakprofiles:/data cloakhq/cloakbrowser-manager
```

Profiles and session data remain in the native application-data directory or the `cloakprofiles` Docker volume across updates.

## Automation API

Every running profile exposes a CDP (Chrome DevTools Protocol) endpoint. Connect Playwright or Puppeteer to automate a profile while watching it live in the browser.

```python
from playwright.async_api import async_playwright

async with async_playwright() as pw:
    browser = await pw.chromium.connect_over_cdp(
        "http://localhost:8080/api/profiles/<profile-id>/cdp"
    )
    page = browser.contexts[0].pages[0]
    await page.goto("https://example.com")
```

```javascript
const { chromium } = require("playwright");

const browser = await chromium.connectOverCDP(
  "http://localhost:8080/api/profiles/<profile-id>/cdp"
);
const page = browser.contexts()[0].pages()[0];
await page.goto("https://example.com");
```

The CDP URL is available from the running-profile view. The same browser session is accessible through its native window on Windows/macOS or through VNC on Linux Docker, and programmatically through the API on every platform.

## Remote Access

### Remote environments

Set `REMOTE_ENVIRONMENT_ENABLED=true` to enable the independent environment
contract. `PROFILE_STORAGE=registry` persists each profile as
`PROFILE_REGISTRY_PREFIX:<profile-id>` in `PROFILE_REGISTRY`; `CRANE_PATH` and
`MIHOMO_PATH` select the platform binaries. `PROFILE_IDLE_STOP_SECONDS` closes
profiles after the last CDP and VNC client has disconnected for that duration,
then pushes their data. An open client prevents idle stopping even without API
traffic. `GET /api/environment` reports the active
host, storage mode, idle timeout and viewer capability. Profiles accept
`proxy_chain`, an ordered mihomo `proxies` array. These options are disabled by
default and do not change local deployments. Remote mode requires `AUTH_TOKEN`
and refuses to start without it.

Running remote profiles accept `PUT /api/profiles/{id}/proxy-chain` with a
nonempty `proxy_chain` array. The Manager validates the candidate before stopping
the old Mihomo, then starts a replacement on the same loopback port. The browser
and its tabs remain open; existing network connections are interrupted. This
requires a profile launched with an independent proxy chain. Switching to or from
direct access still requires a cold start. A failed replacement keeps the desired
configuration and original port for retry, without falling back to direct access.
`GET /api/profiles/{id}/proxy-chain` reports readiness, desired/applied configuration
hashes and replacement support. Identical applied chains do not restart Mihomo;
after an uncertain HTTP response, read this status before retrying. These endpoints
use the existing authentication and require remote mode.

`POST /api/profiles/{id}/proxy-probe` diagnoses a supplied `proxy_chain` through
that Profile's Mihomo on the browser host. Supply an HTTP(S) `url`,
`connect_timeout_seconds` (up to 60) and `timeout_seconds` (up to 90). Running
profiles reuse their existing listener only when the applied chain hash matches;
otherwise the request fails with `PROXY_PROBE_CHAIN_CHANGED`. Stopped profiles
use a temporary Mihomo, including `MATCH,DIRECT` for an empty chain, without
launching a browser or saving the supplied chain. Cleanup completes before
lifecycle operations can continue, even when the caller disconnects.
The response contains `httpStatus`, the raw response `body`, and `source`
(`profileId`, Mihomo `pid`, loopback `port`, `temporary`, `chainVersion`). Logs
record the process, listener and HTTP status. The endpoint requires remote mode
and existing authentication; there is no host-network fallback. It requires
`curl` (`curl.exe` on Windows) on the browser host. Request failures return
`PROXY_VERIFY_REQUEST_FAILED`; unavailable runtimes return `PROXY_PROBE_UNAVAILABLE`.

Registry snapshots include profile metadata, tags, and browser session data.
Startup rebuilds the disposable profile index from registry tags; legacy tags
without Manager metadata are skipped. Cache directories are excluded. Browser
data is published only after a normal close (`exit_type=Normal`). Profile and
status responses expose `sync_status` (`not_synced`, `syncing`, `synced`, or
`failed`) and `sync_error` (null or the persistence error). Wait for `synced`
before deleting an environment. Each profile uses one replaceable tag;
deleting a profile deletes its published tag.

`deploy/cnb/` is a ready-to-copy CNB environment template. Copy its
`.cnb.yml` and `.ide/` into the root of your own private CNB repository; the
startup stage builds this branch, then serves Manager on port 8080 with
registry storage under `docker.cnb.cool/<your-repo-slug>` and a 300 second idle
stop. Rebuilds use the CNB image cache, so bump `CACHE_BUST` in
`.ide/Dockerfile` to pick up new Manager commits.

`AUTH_TOKEN` stays outside Git in the private registry artifact
`docker.cnb.cool/<your-repo-slug>/manager-secret:latest`, containing one file
`manager.env` with `AUTH_TOKEN=<token>`. The startup script pulls it with the
container's `CNB_TOKEN` and refuses to start if it is unavailable or lacks
`AUTH_TOKEN`. Publish it before the first start from any machine with `crane`
and a CNB access token that can push to the repository:

```bash
secret_dir=$(mktemp -d)
install -m 600 /path/to/private/manager.env "$secret_dir/manager.env"
tar -czf "$secret_dir/layer.tar.gz" -C "$secret_dir" manager.env
printf '%s' "$CNB_ACCESS_TOKEN" | crane auth login docker.cnb.cool -u cnb --password-stdin
crane append -f "$secret_dir/layer.tar.gz"   -t docker.cnb.cool/<your-repo-slug>/manager-secret:latest
rm -rf "$secret_dir"
```

Rotate the token by publishing a replacement the same way, then cold-start the
environment; running environments keep their current token until restarted.
Start the environment with `POST /<your-repo-slug>/-/workspace/start` and JSON
`{"branch":"main"}`, then read `business_id` from `GET /workspace/list`. The
Manager URL is `https://<business_id>-8080.cnb.run`; it is public and protected
only by `AUTH_TOKEN`. Wait for `sync_status` `synced` before stopping or
deleting an environment.

The container binds to localhost only. To access from a remote server:

```bash
ssh -L 8080:localhost:8080 your-server
```

Then open `http://localhost:8080`.

## Authentication

By default, there is no authentication (ideal for local use). To protect the web UI and API when hosting on a network, set the `AUTH_TOKEN` environment variable:

```bash
docker run -p 127.0.0.1:8080:8080 -v cloakprofiles:/data -e AUTH_TOKEN=your-secret-token cloakhq/cloakbrowser-manager
```

Or in `docker-compose.yml`:

```yaml
environment:
  - AUTH_TOKEN=your-secret-token
```

When `AUTH_TOKEN` is set:

- The web UI shows a login page. Enter the token to unlock.
- API consumers pass the token via `Authorization: Bearer <token>` header.
- VNC WebSocket connections are authenticated via the login cookie.
- Authenticated backends can `POST /api/profiles/{id}/remote-view-ticket` to obtain a single-use, 60-second login ticket. Open `/api/auth/remote-view?ticket=...` in the browser to consume it, set the existing HttpOnly auth cookie, and enter that profile's focused viewer (`/?focus={id}`). This view fills the entire window with a fixed profile and keeps its name as the tab title. It has no header or connecting cover; only stopped or disconnected states show an overlay. Use the browser fullscreen shortcut. Frame pixels and exact window dimensions do not gate visibility. It has no profile list, switching, or launch controls; stopped and disconnected states remain on the same target. Launch through BAM so its proxy chain is prepared. The normal Manager homepage remains the full management UI. The target is generated by Manager; external redirects are not accepted. Expired, unknown, or reused tickets return 401, including when the browser already has a valid cookie. Tickets are held in process memory and expire on restart; run a single Manager worker. Keep the long-lived `AUTH_TOKEN` in backend Bearer headers, never in browser URLs or response bodies.

The ticket request may bind a `return_url` pointing to BAM's `/accounts/{email}/remote-view` transition page. Manager signs this binding in an HttpOnly cookie and shows a same-tab restart link when stopped or the environment disconnects. Query parameters cannot supply or override this link. Restart always goes through BAM. In focused mode KasmVNC follows the viewer size (500 ms debounce), and Manager fits existing browser windows (600 ms debounce) without viewport emulation. Saved fingerprint screen settings remain unchanged. Multiple viewers of one Profile share its physical display; the most recent resize applies to all of them. Persistent launches omit Playwright's extra startup blank tab, and search setup closes only its own temporary settings tab before saving the session.
- The `/api/health` endpoint remains unauthenticated (for Docker healthcheck); it exposes no system details. The `/api/status` endpoint (running counts, version) now requires authentication.

> **Note**: The auth token is transmitted in cleartext over HTTP. If you expose the Manager to the internet, put it behind a reverse proxy with HTTPS (Caddy, nginx, Traefik).

## Runtime UI configuration

The profile sidebar defaults to `16rem`. To use a wider or narrower sidebar without changing the frontend build, set `SIDEBAR_WIDTH` to a CSS length:

```bash
docker run -p 127.0.0.1:8080:8080 -v cloakprofiles:/data -e SIDEBAR_WIDTH=20rem cloakhq/cloakbrowser-manager
```

Or in `docker-compose.yml`:

```yaml
environment:
  - SIDEBAR_WIDTH=20rem
```

Supported units are `px`, `rem`, `em`, and `vw`. Invalid values fall back to `16rem`.

## License

- **This application** (GUI source code) — MIT. See [LICENSE](LICENSE).
- **CloakBrowser binary** (compiled Chromium) — governed by version-specific subscription terms and may not be redistributed. See [BINARY-LICENSE.md](BINARY-LICENSE.md).

The GUI application requires the CloakBrowser Chromium binary to function. The binary is automatically downloaded on first launch and is governed by its own license terms. If you fork or redistribute this application, your users must comply with the [CloakBrowser Binary License](BINARY-LICENSE.md).

## Contributing

Contributions are welcome. Please [open an issue](https://github.com/CloakHQ/CloakBrowser-Manager/issues) first to discuss what you'd like to change.

### Contributors

- [lhq1363511234-arch](https://github.com/lhq1363511234-arch) — native Windows support foundation
- [quorentindupres-dev](https://github.com/quorentindupres-dev) — native macOS workflow and Manager integration concepts
- [shellus](https://github.com/shellus) — auth-gated status endpoint and unauthenticated health probe
- [hayka-pacha](https://github.com/hayka-pacha) — profile reset endpoint

## Links

- **CloakBrowser** — [github.com/CloakHQ/CloakBrowser](https://github.com/CloakHQ/CloakBrowser)
- **Website** — [cloakbrowser.dev](https://cloakbrowser.dev)
- **Bug reports** — [GitHub Issues](https://github.com/CloakHQ/CloakBrowser-Manager/issues)
- **Contact** — cloakhq@pm.me
