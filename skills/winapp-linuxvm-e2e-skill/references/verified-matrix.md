# Verified matrix (September 2026)

Environment: Firecracker microVM, Ubuntu 24.04 x86_64, 1 vCPU / 4 GB, no KVM. Wine 11.0 (Kron4ek wow64 build) + wine-mono 10.4.1, .NET SDK 8.0.425 (SDK 10.0.401 for the net10 apps), runtimes 6.0.x / 8.0.31 / 10.0.12.

## `scripts/selftest.py` — 13 lanes, 157 checks, all passing

| Lane | App | Highlights |
|---|---|---|
| winforms | WinForms, .NET 8, self-contained | scenario (below) |
| wpf | WPF (XAML), .NET 8, self-contained | scenario |
| winforms-fd | WinForms, .NET 8, framework-dependent | scenario; runtime zips downloaded + SHA-512 verified |
| wpf-fd | WPF, .NET 8, framework-dependent | scenario |
| net48 | WinForms, .NET Framework 4.8 on wine-mono (AppDomain launcher) | scenario + entry assembly / ProductName / app.config seen by the app |
| wpf48 | WPF, .NET Framework 4.8 on wine-mono (AppDomain launcher) | scenario |
| controls | WinForms TabControl, ListBox, ListView, TreeView, NumericUpDown, RadioButton | real clicks + values read back; WM_CHAR → one KeyPress/TextChanged per character, ASCII/WM_CHAR mix, paste mode; UI-thread hang → `responsive()` false, `AppNotResponding`, recovery |
| nested | WinForms GroupBox / bordered scrolled Panel / Panel in GroupBox | clicks land; scrolled-out control is not findable and reports `onScreen=false` |
| hidden | WinForms app whose only window is registered but never visible | `start()` fails clearly (and cleans up) when no window becomes visible; `require_window=False` still gives a usable session |
| coverage | the other common WinForms controls: multiline / password / masked / rich text boxes, editable ComboBox, CheckedListBox, DateTimePicker, TrackBar, ProgressBar, LinkLabel, PictureBox, ToolStrip (button + drop-down), StatusStrip, SplitContainer, TableLayoutPanel, modal child Form | values read back, real clicks and keyboard; includes the hit-testing quirks (CheckedListBox needs select + Space, LinkLabel needs the link text) |
| wpf-coverage | the same for WPF: ToolBar (button + ToggleButton), TreeView, TabControl, PasswordBox, multiline TextBox, editable ComboBox, DatePicker, Slider, ProgressBar, Expander, ListView with GridView, RadioButton, modal child Window | values read back, real clicks and keyboard; headered items are clicked on their `headerRect` |
| scroll / wpf-scroll | WinForms / WPF long ListBox (200), 200-row grid, button deep inside a scroll container | `onScreen=false` reported, `NotFound` names `scroll_into_view`, explicit scroll + auto-scrolling clicks on element, list item 150 and grid cell row 120 |

Scenario per lane: click + type Japanese into a TextBox, button → label text and grid row, grid cell click (`cellRects` / `currentCell`; WinForms DataGridView and WPF DataGrid), checkbox, combo box by keyboard, context-menu item (WinForms ContextMenuStrip / WPF ContextMenu popup),
WPF lanes also: ToolTip visible as a popup while hovering, visual tree exposes control-template internals (`ContentPresenter` inside the button); validation MessageBox detected and dismissed by clicking its button, two window screenshots pixel-identical, menu → Exit closes the app.
Six driver checks cover malformed selectors, partial `WM_CHAR` failure, exact mask geometry, surfaced `xdotool` failures, fail-fast handling of a missing executable and runtime-cache path validation.

## `scripts/selftest.py --tfm net6.0-windows,net9.0-windows,net10.0-windows` — 151 checks, all passing
WinForms and WPF × self-contained and framework-dependent × .NET 6 / 9 / 10 (SDK 10.0.401 builds them; runtimes 6.0.x / 9.0.x / 10.0.12 downloaded, SHA-512 verified and staged atomically), same scenario as the default lanes (11 checks per WinForms lane, 13 per WPF lane).

## Checked manually
- WM_CHAR / clipboard / auto modes on `𠮷野家ｱｲｳ①㈱～ｶﾞ` (surrogate pair, half-width kana, circled digit, ㈱, fullwidth tilde) in a WinForms and a WPF TextBox: all identical.
- 39,262 `tree()` calls in 25 s while a WinForms app opened/closed forms every 4 ms: 0 errors.
- Grid row cap (`E2E_MAX_ROWS=1` → 1 row, `rowCount=2`, `truncated=true`) in WinForms and WPF; `id=` finds WinForms controls by name.
- `start()` failure cleanup (state file removed, port freed), second `start` refused with a clear error, CLI exit codes (3/4/5), `compare` on different-size images → mismatch, `shot(window=True)` without a window → error.
- `setup.sh` from scratch in an empty `E2E_HOME` (Wine accepted with pin + GitHub digest + upstream sha256sums.txt; wine-mono fetched from WineHQ and accepted with pin + GitHub digest), then a fresh-prefix app run.
- `verify_download.py`: tampered file → mismatch; wrong pin vs GitHub digest → "sources disagree"; unpinned Wine 10.0 → verified via upstream sha256sums.txt; unknown asset → exit 3 (unverified); the setup.sh wrapper for exit codes 0/1/3 with and without `E2E_ALLOW_UNVERIFIED=1` (fail closed by default).
- .NET SDK install from the SHA-512-verified tarball (`dotnet_sdk_url.py`), then a WinForms app built with that SDK.
- Peak disk: each lane's published app (~160 MB self-contained) is deleted right after that lane, so a full run needs one lane's worth, not a dozen (`--keep-builds` keeps them). A run without this filled a 2 GB-free sandbox and wedged a `dotnet publish`.
- Agent bounds: with a session running, 8 extra connections → only 4 answered (the rest refused), a 2 MiB request line drops that client alone, and the session keeps working. Atomic extraction helper: success, missing marker (nothing left behind) and recovery from a stale `.partial`.
- Fault tolerance: 5,946 `tree()` calls in 30 s against an app creating and disposing forms on every idle, and 432 mixed logical/visual `tree()` calls against the WPF sample: 0 errors. Clipboard guard raises instead of pasting stale text. Launcher with no argument / a missing target exits 2.
- Library features: ffmpeg x11grab recording (1280×800), window-cropped screenshots, masked comparison, clipboard paste, framework auto-detection, font substitution import (incl. full-width names).

## Known environment defect
A WPF `PasswordBox` whose font is only resolved through Wine's replacement list crashes the process on focus (`FailFast` in `FontFamily.get_FirstFontFamily`); an explicit installed `FontFamily` avoids it, and registering a substitute font file as `Segoe UI` did not. The `wpf-coverage` sample sets the font explicitly for this reason — see references/pitfalls.md.

## Not tested
32-bit/x86-only apps; COM/ActiveX; file/print dialogs; drag & drop; tray icons; multi-window apps beyond dialogs and popups; tray-only apps whose forms are never shown (invisible to the agent); WinForms tooltips (native windows, not read);
DPI ≠ 96; single-file/ClickOnce publish; long-running apps; SDK 10 building older targets; Windows visual parity (known to differ, see fidelity.md).
