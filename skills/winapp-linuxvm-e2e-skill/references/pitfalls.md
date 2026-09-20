# Pitfalls (all seen while building and verifying this skill)

## Wine / wine-mono
- **wine-mono must be exactly the version Wine asks for**, otherwise "Wine Mono Installer" pops up and `wineboot` hangs forever in Xvfb.
  `setup.sh` reads it from `appwiz.cpl` (`strings -a -e l …` — the string is UTF-16) and unpacks it into `wine/share/wine/mono/`. Wine 11.0 → 10.4.1, 11.17 → 11.3.0.
- **Never set `WINEDLLOVERRIDES=mscoree=`** (or `mscoree,mshtml=`): IL-only assemblies then fail with "mscoree.dll not found, IL-only binary cannot be loaded". Only `mshtml=` is disabled (avoids the Gecko prompt).
- **WPF dies with `Environment.FailFast` in `FontFamily.FirstFontFamily`** unless `HKCU\Software\Wine\Fonts\Replacements` maps Segoe UI/Meiryo/… to installed fonts. `assets/fonts.reg` does this; setup converts it to UTF-16LE+BOM (needed for full-width names such as ＭＳ Ｐゴシック; import checked by exporting the key).
- Harmless noise in logs: `winemenubuilder`, `winebth` driver errors, `libEGL DRI3` warnings.
- No window manager: windows sit where the app puts them, Wine draws a ~30 px caption and 4 px border (client origin ≈ (4,30)).
- The Kron4ek wow64 tarball needs the shared libraries that `apt install libwine` pulls in (setup does this; the Ubuntu wine itself is not used).
- UIA is unusable (see fidelity.md). Do not spend time on FlaUI/UIA3/UIA2.

## Downloads
- Wine and wine-mono tarballs are checked by `scripts/verify_download.py` against **every** available source, which must agree: the SHA-256 pinned in `setup.sh`, the digest GitHub recorded when the asset was uploaded (read from the release page HTML — the REST API is rate-limited on shared egress IPs), and the maintainer's own `sha256sums.txt` (Kron4ek publishes one). wine-mono is fetched from WineHQ's own server (independent of GitHub) and cross-checked against GitHub's digest. No upstream *signature* exists for these builds, so this is agreement between independent records, not a signature check.
- Other Wine versions usually still verify through GitHub's digest or `sha256sums.txt`. Setup fails closed: with no source at all the download is discarded and setup stops, unless `E2E_ALLOW_UNVERIFIED=1` is set. Exit code 3 of the verifier = no source, 1 = mismatch/disagreement.
- The .NET SDK is installed from the tarball named in Microsoft's release metadata and checked against its SHA-512 (`scripts/dotnet_sdk_url.py`), not through `dotnet-install.sh` — that script would be an unverified root-executed download.
- Windows .NET runtime zips are checked against the SHA-512 in Microsoft's release metadata; a mismatch discards the file. Truncated downloads (Content-Length) are rejected.
- `dotnet-install.sh` and apt handle their own verification.

## .NET runtimes
- Ubuntu's apt `dotnet-sdk-8.0` lacks the WindowsDesktop SDK → use the official `dotnet-install.sh` (setup does).
- Framework-dependent apps: the driver downloads `dotnet-runtime-*-win-x64.zip` + `windowsdesktop-runtime-*-win-x64.zip` from the release metadata and sets `DOTNET_ROOT=Z:\…` (Windows path).
  The Linux `DOTNET_ROOT` must not leak into Wine (the driver strips it). For newer channels the metadata lists apphost-pack/targeting-pack zips first — match by file name.
- WPF trees: the default is the logical tree (compact) plus open popups. Template internals (`ContentPresenter`, `Border`, …) exist only in the visual tree (`--visual`), which is much larger and capped by `E2E_MAX_NODES`. A tooltip is a popup root only while it is shown: `hover` first, then `tooltip`.
- .NET 9/10 self-contained WinForms-only apps do not ship PresentationFramework (and WPF-only apps may lack WinForms): the agent keeps each UI stack in separate methods so neither is required.
- .NET Framework apps have no startup hooks: the driver stages a copy of the app folder, adds `E2ELauncher.exe` + `E2EAgent.dll`, and `E2ELauncher` runs the target with `AppDomain.ExecuteAssembly` in its own AppDomain
  (`ApplicationBase` = staged folder, `ConfigurationFile` = `<app>.exe.config`), starting the agent inside that domain. The app therefore sees itself as the entry assembly.
  An earlier `Assembly.LoadFrom(...).EntryPoint.Invoke` launcher made `GetEntryAssembly()`, `Application.ProductName` and `ExecutablePath` report `E2ELauncher` — do not go back to it.
  The original folder is not modified; files the app writes next to its exe land in `$E2E_HOME/stage/<name>`.
- Do not override the target framework with `dotnet publish -p:TargetFramework=…`: the implicit restore ignores it (NETSDK1005). Edit the csproj instead (`selftest.py --tfm` does).
- First start of an app on 1 vCPU can take 10–30 s (seen: 2–23 s). The default connect timeout is 90 s.

## Input
- **P/Invoke `SendMessageTimeout` with `CharSet.Unicode`**: the default ANSI entry point truncates `WM_CHAR`'s wParam to one byte (山田太郎 arrived as `q0*Î`). The self test's Japanese-typing checks exist to catch exactly this.
- `xdotool type` with several non-ASCII characters drops characters; even one-by-one, a cold first non-ASCII keystroke can be lost (X keymap remap race). That is why non-ASCII goes through the agent's `WM_CHAR` (default) or the clipboard.
- Clipboard paste waits until `xclip -o` really serves the text before Ctrl+V; `xclip -i` must be spawned with its stdout/stderr redirected, or it keeps the caller's pipes open.
- ListView (List/Icon views): only the label area is hit-testable — the agent reports label bounds as `itemRects`.
- Menu sub-items have no valid rect until the menu is opened; items of a closed drop-down are reported `visible=false`.
- Controls scrolled out of a container keep `Control.Visible == true`; the agent adds `onScreen`/`vrect` from the ancestors' clip rectangles and the driver only targets on-screen controls. `click()` scrolls them in automatically and `NotFound` says so; `scroll_into_view()` does it explicitly (virtualized WPF lists only realize containers after scrolling, so item rectangles appear then).
- Clipboard paste refuses to press Ctrl+V if the X selection does not serve the requested text within 3 s (it would paste whatever was there before).
- `shot(window=True)` takes the first visible captioned top-level window, and recording always grabs the whole 1280×800 screen: with several windows open, pass an explicit `--region`.
- A WPF DataGrid's `rows` are produced by calling every public property getter on each row item. That is fine for the usual DTO/record row, but an item whose getters are slow or have side effects will feel it (bound by `E2E_MAX_ROWS`).
- WinForms/WPF report as "present" before the first window is visible; the driver waits for a visible element (`start()` fails if none appears within `window_timeout`, 30 s; use `require_window=False` / `--no-wait-window` for apps that start hidden), and `find()` auto-waits 5 s.
- A WinForms form that has never been shown is not in `Application.OpenForms`, so tray-only apps (NotifyIcon + `ApplicationContext`, no form ever shown) are invisible to the agent: `start()` times out with "agent not ready". A form that was shown once and then hidden is listed (`visible=false`).

## The agent's loopback port is not a security boundary
- The agent listens on `127.0.0.1:$E2E_AGENT_PORT` **without authentication**: anything else running in the same sandbox can read the control tree, type into the app and scroll it. Run only trusted code beside a session, and do not treat the port as isolation.
- It is single-tenant with bounds, not hardened: at most `E2E_MAX_CLIENTS` (4) connections at a time, request lines up to `E2E_MAX_REQUEST_CHARS` (1 MiB), idle clients dropped after `E2E_CLIENT_IDLE_MS` (10 min). Extra connections are refused and over-long lines close that client only.

## Interrupted installs
- Wine, wine-mono and each Windows .NET runtime are extracted into a sibling `<dir>.partial` and renamed into place once a marker file is present, so a killed setup never leaves a directory that the next run mistakes for a finished install; a stale `.partial` is discarded. The .NET **SDK** is the exception: SDKs are added next to each other in one directory, so it is extracted in place after its SHA-512 is verified.

## WPF PasswordBox needs a font WPF can resolve itself
- A `PasswordBox` whose font comes only from Wine's font replacement (e.g. the inherited `Segoe UI`) kills the process the moment it takes focus:
  `FailFast` in `FontFamily.get_FirstFontFamily` via `TextSelection.CalculateCaretRectangle`. A `TextBox` with the same inherited font is fine —
  only the password caret path trips it. Registering a real font file under the name `Segoe UI` in the prefix did **not** help (tested).
- Workaround when you control the app: set `FontFamily` on the `PasswordBox` to a family that is really installed (`Noto Sans CJK JP` verified).
  For an app you cannot change, avoid focusing the `PasswordBox`: fill the form through other fields, or report that the login screen is not testable here.
  A crash of this kind shows up as `ConnectionError: agent closed the connection` plus the `FailFast` stack in `$E2E_HOME/logs/app.log`.

## Controls that ignore a click in the middle
- **CheckedListBox**: clicking the row centre only selects it — `ItemCheck` does not fire. Toggle with `click("name=lst", item=N)` followed by `key("space")` (verified), or aim at the check box glyph yourself; `itemRects` covers the whole row, and even the glyph area was unreliable under Wine in testing.
- **LinkLabel**: `LinkClicked` fires only over the link text, which is usually much narrower than the control. Click near the left edge of `rect` (e.g. `x + 15`) instead of its centre.
- **ToolStrip / StatusStrip** dock to the edge of the form, so a control placed at the same coordinates sits on top of them and swallows the click. If a toolbar button does nothing, take a screenshot and check what is actually at that point.
- **WPF headered items** (`TreeViewItem`, `TabItem`, `Expander`, `GroupBox`): the node's `rect` spans the whole item — for a `TreeViewItem` with children it even covers the subtree — while only the header strip reacts. The agent therefore reports `headerRect` (the template's `PART_Header` / `ContentSite` / `HeaderSite`), and `click()` aims there automatically. Note the header text is in `Header`; `Content`/`Header` hold strings only, and a non-string content type is reported as `ContentType`/`HeaderType`.
- General rule: when a click lands but nothing happens, the rectangle was right and the hit-testing was not. Look at a screenshot before assuming the control is unsupported.

## Hung or busy apps
- The agent marshals to the UI thread with a timeout (`E2E_UI_TIMEOUT_MS`, default 5000). A blocked UI thread surfaces as `AppNotResponding` (CLI exit 5); `responsive()` / `wait_responsive()` poll it. A timed-out operation that has not begun is cancelled; an operation already executing on the UI thread cannot be pre-empted.

## Rebuilding the agent
- `scripts/build_agent.sh` builds with `-p:DebugType=embedded -p:PathMap=<src>=/agent-src/ -p:Deterministic=true`, so the shipped assemblies keep file/line information in stack traces but contain no absolute build paths (and no separate `.pdb`). Keep those flags if you change the script, or the binaries start carrying your local directory names.

## Process / shell hygiene in the sandbox
- Background processes die when a tool call ends → start daemons with `setsid nohup … &`; commands over ~300 s are killed, so run long jobs in the background and poll.
- `pkill -f wine` / `pkill -f selftest.py` kill your own shell (its command line contains the pattern) → use `wineserver -k`, or write the pattern as `[s]elftest.py`.
- `/bin/sh` has no brace expansion or `${PIPESTATUS[0]}` (`mkdir -p a/{b,c}` creates a directory literally named `{b,c}`) → use `bash`.
- One session at a time (agent port 47800, state in `session.json`); `start` refuses if the port is taken. `stop` kills every Wine process of the prefix.
- Disk: Wine ≈ 0.9 GB, prefix ≈ 0.55 GB, SDK ≈ 0.6 GB, each Windows runtime ≈ 0.16 GB, and every self-contained publish ≈ 0.16 GB (`selftest.py` deletes each lane's build as it goes; `--keep-builds` does not). When disk runs out, `dotnet publish` hangs instead of failing — check `df -h` if a lane stops making progress. Sandboxes with ~10 GB free are fine; delete extra SDKs after use.
