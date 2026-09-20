---
name: winapp-linuxvm-e2e-skill
description: >
  Run and end-to-end test Windows desktop apps (WinForms / WPF; .NET Framework 4.x and .NET 6+) inside this Linux sandbox
  with Xvfb + Wine + real X11 mouse/keyboard input + an in-process inspection agent, plus screenshots, video and pixel-diff regression.
  Use this whenever the user wants to run, drive, test, QA, screenshot or verify a WinForms/WPF app, .exe, .csproj or .sln without a Windows machine —
  e.g. "WinForms/WPFのE2Eテスト", "GUIテスト", "UIテスト", "画面を確認して", "ボタンを押して動作確認", "Windowsアプリを動かして", "スクショ回帰テスト",
  "test my WinForms app", "click through my WPF app" — even if Wine is never mentioned. Not for web, Android, Avalonia, MAUI or UWP/WinUI apps.
---

# winapp-linuxvm-e2e-skill

Drives real WinForms/WPF apps on Linux: **Xvfb** (virtual display) + **Wine 11** (+ wine-mono for .NET Framework) +
**xdotool** (real X11 input → Win32 messages) + an **in-process agent** (control tree, screen rects, values, popups, native dialogs, IME-style text delivery; no UI Automation)
+ ImageMagick/ffmpeg (screenshots, pixel diff, video). Everything here was exercised in this environment; see `references/verified-matrix.md`.

Fidelity in one line: **functional behaviour ≈ Windows; pixels/layout/theme ≠ Windows.** Read `references/fidelity.md` before you report results.

## 0. First use (idempotent, ~3–4 min, ~2 GB disk)

```bash
bash <skill>/scripts/setup.sh            # apt deps, Wine 11 wow64 + wine-mono + .NET SDK 8, all checksum-verified; prefix+fonts
#   a download with no checksum source at all is refused (override: E2E_ALLOW_UNVERIFIED=1)
python3 <skill>/scripts/e2e.py doctor    # must print no FAIL
python3 <skill>/scripts/selftest.py      # optional: builds samples, runs 157 checks on 13 lanes
#   --tfm net6.0-windows,net9.0-windows,net10.0-windows   same scenario on other .NET versions (needs SDK 10: DOTNET_CHANNEL=10.0 bash <skill>/scripts/setup.sh)
```
Needs network to: archive.ubuntu.com, github.com (+ release CDN), dl.winehq.org, builds.dotnet.microsoft.com, and api.nuget.org for source builds/selftest.
If a domain is blocked, tell the user which one to allow. Skip the SDK with `--no-sdk` when only prebuilt binaries are tested.
Long-running background processes must be started with `setsid nohup … &` (they die at the end of each tool call otherwise).
The shell that runs these commands is `/bin/sh` (dash), not bash: `source`, `[[ ]]`, `{a,b}` and `PIPESTATUS` all fail there.
Wrap anything that needs bash — above all sourcing `env.sh` — in `bash -c '…'`, and keep each command self-contained, because
environment variables do not survive from one tool call to the next.

## 1. Get the app into runnable form

| User gives | Do |
|---|---|
| Windows build output (exe + dlls), any .NET | use it as is |
| SDK-style `.csproj` / `.sln` (.NET 6+ or net48) | build on Linux (below) |
| Old-style csproj (net4x, packages.config) | cannot build here → ask for the built `bin/Release` folder |

```bash
bash -c '. /opt/winapp-linuxvm-e2e-skill/env.sh; export DOTNET_ROOT=$DOTNET_ROOT_SDK
         dotnet publish App.csproj -c Release -r win-x64 --self-contained false -p:EnableWindowsTargeting=true -o /tmp/app-out'
```
(`bash -c` is required: the tool shell is `/bin/sh`, where `source` does not exist — `. env.sh` alone would also leave `$PATH` unset for the next call.)
- `--self-contained false` is fine: the driver downloads the matching Windows runtime zips itself (SHA-512 verified, no installer). Use `true` if offline.
- SDK 8 builds ≤ net8. For net9/net10 targets install a newer SDK next to it: `DOTNET_CHANNEL=10.0 bash scripts/setup.sh` (same install dir; the newest SDK is used, and it also builds net6/net8).
- Change a target framework by editing the csproj, not with `-p:TargetFramework=…` (that breaks the implicit restore).
- Use the app's real files (config, DLLs, resources). Do not rewrite the app to make it testable.

## 2. Drive it (CLI, one short command per tool call)

```bash
E=<skill>/scripts/e2e.py
python3 $E start /tmp/app-out/App.exe            # lane (core / framework) auto-detected; waits until a window is visible (--no-wait-window for apps that start hidden)
python3 $E shot /tmp/s.png --window              # then LOOK at the image (view tool) before acting
python3 $E tree --flat                           # type, name/automationId, text, screen rect, values
python3 $E type "山田太郎" --sel "name=txtName"    # ASCII = real key events; Japanese = WM_CHAR per character from the agent
python3 $E click "name=btnSave"                  # real mouse click; scrolled-out targets are brought into view first (--no-scroll to disable)
python3 $E scroll "name=btnDeep" [--item 150]     # explicitly scroll an element or a list/grid item into view
python3 $E get "name=lblResult"                  # read text/property:  get "name=chk" Checked
python3 $E rclick "name=lblResult"; python3 $E click "text=リセット(&R)"   # context menu items appear in the tree while open
python3 $E hover "name=btnGreet"; python3 $E tooltip                      # WPF tooltip text (a popup root while shown)
python3 $E dialogs                               # native MessageBox/common dialogs, with button rects
python3 $E press OK                              # click a dialog button
python3 $E menu "ファイル(&F)>終了(&X)"            # & and _ mnemonics are ignored when matching
python3 $E responsive                            # UI thread answering? (exit 5 = hung/busy)
python3 $E stop
```
Selectors: `name=X` (WinForms Name / WPF x:Name), `id=X` (WPF AutomationId; WinForms falls back to Name), `text=X`, `contains=X`, `type=Button`; combine with `;`; `#N` picks the N-th match.
Elements auto-wait (5 s) and must be *visible and on screen*: controls scrolled out of their container are reported `onScreen=false`, and clicks scroll them into view automatically (`scroll_into_view` under the hood); clicks land on the visible part.
WPF `TreeViewItem` / `TabItem` / `Expander` are clicked on their header automatically (`headerRect`), and a WPF `PasswordBox` can crash the app under Wine unless its font is an installed family (`references/pitfalls.md`).
Some controls only react where their content is: a `CheckedListBox` toggles from the small check box (or select the row, then `key space`), and a
`LinkLabel` fires only on the link text — a click in the middle of the control's rectangle hits neither. See `references/pitfalls.md`.
Rows/tabs/cells: `click "name=grid" --cell 1,0` (WinForms DataGridView / WPF DataGrid; `get name=grid currentCell` reads it back), `click "name=lst" --item 2` (lists, grid rows), `click "name=tabs" --item 1`.
WPF: popups (context menus, drop-downs, tooltips) are extra roots in the tree; control-template internals need the visual tree: `python3 $E --visual tree --flat` (also for selectors/clicks).
CLI exit codes: 0 ok · 1 check failed · 3 no session / app unreachable · 4 element not found · 5 application not responding.
Full reference: `references/api.md`.

## 3. Write a repeatable test (Python)

```python
import sys; sys.path.insert(0, "<skill>/scripts")
import e2e
from e2e import Session

with Session.start("/tmp/app-out/App.exe") as s:      # start() cleans up after itself if the app cannot be reached
    s.type_text("山田太郎", sel="name=txtName")
    s.click("name=btnGreet")
    assert s.get("name=lblResult") == "こんにちは、山田太郎さん"
    s.click("name=txtName"); s.key("ctrl+a", "BackSpace"); s.click("name=btnGreet")
    d = s.dialogs(); assert d and d[0]["title"] == "入力エラー"; s.press_dialog("OK")
    s.shot("/tmp/after.png", window=True)
    r = e2e.compare("/tmp/after.png", "baselines/after.png", fuzz="1%", masks=[(24, 120, 300, 23)])  # blank volatile areas
    assert not r.get("size_mismatch") and r["ratio"] < 0.001, r     # different image sizes are reported as a mismatch (ratio 1.0)
    assert s.responsive()                                            # a busy/hung UI raises e2e.AppNotResponding from tree()/click()
```
Baselines are created by the same Wine setup (first run = review by eye, then commit). Video: `s.record_start(path)` / `s.record_stop()`.
Save screenshots/videos/logs the user should see to `/mnt/user-data/outputs/` and present them.

## 4. Reporting rules

- State what was exercised and observed (values read from the app, dialogs seen, screenshots looked at). Attach evidence.
- Say plainly that it ran on Wine, so a pass proves functional behaviour, **not** Windows pixel/theme/DPI/font fidelity.
- Never call a layout/visual result "same as Windows". Visual diffs are only meaningful against Wine-made baselines.
- Not testable here (say so, don't fake it): IME conversion UI, COM/ActiveX (e.g. vendor OCX), drivers/USB/serial hardware, GPU-specific rendering,
  Windows-only services. Suggest mocks/loopback (e.g. a TCP/SLMP simulator on 127.0.0.1) or a real Windows runner for those.
- If something looks wrong, check whether it is a Wine artefact (theme, font metrics) before calling it an app bug; re-run once to rule out flakiness.
- `AppNotResponding` is a finding about the app (UI thread blocked), not a tooling error: report it with the step that triggered it.

## 5. When things go wrong
`references/pitfalls.md` lists every failure seen while building this (wine-mono dialog hang, WPF FailFast without font replacements, WM_CHAR/ANSI truncation,
.NET 9/10 trimmed runtimes, UIA being unusable, port/state leftovers…). Quick checks:
`python3 $E doctor`; `cat /opt/winapp-linuxvm-e2e-skill/logs/app.log /opt/winapp-linuxvm-e2e-skill/logs/agent.log`; `python3 $E stop` (kills wineserver) then retry.
