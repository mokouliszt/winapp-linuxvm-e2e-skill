# API reference

Everything lives in `scripts/e2e.py` (library + CLI). State: `$E2E_HOME` (default `/opt/winapp-linuxvm-e2e-skill`), logs in `$E2E_HOME/logs/` (`app.log`, `agent.log`).

## CLI (`python3 scripts/e2e.py <cmd>`)

Exit codes: `0` ok · `1` check failed / other error · `3` no session or app unreachable · `4` element not found · `5` application not responding.

| Command | Purpose |
|---|---|
| `doctor` | check installation (exit 1 on any FAIL) |
| `start EXE [ARGS…] [--port 47800] [--lane core\|framework] [--keep-on-failure] [--no-wait-window] [--window-timeout 30]` | launch an existing EXE under Wine with the agent; waits until a window is visible (and fails if none appears). Refuses to start if the agent port is taken; on failure the half-started app and `session.json` are removed (log tails are in the error) |
| `stop` | kill everything in the Wine prefix (`wineserver -k`) and drop the session |
| `tree [--flat] [--sel SEL]` | dump the control tree (JSON, or one line per node with `--flat`) |
| `windows` / `dialogs` | native top-level windows / native dialogs (`#32770`) with child texts and button rects |
| `responsive` | is the UI thread answering? (exit 5 if not) |
| `click\|dblclick\|rclick SEL [--item N] [--cell R,C]` | real mouse click at the element (or list item / tab / grid cell) centre. `--cell`: WinForms DataGridView and WPF DataGrid; `--item`: lists, tabs, grid rows. Scrolled-out targets are scrolled into view first (`--no-scroll` disables it) |
| `scroll SEL [--item N]` | scroll the element (or list/grid item) into view: WinForms `ScrollControlIntoView`/`EnsureVisible`, WPF `BringIntoView`/`ScrollIntoView` |
| `hover SEL [--wait 1.5]` / `tooltip` | move the mouse over an element; print the WPF tooltip currently shown (exit 4 if none) |
| `--visual` (global, before the command) | WPF: walk the visual tree, i.e. control-template internals, for `tree`, selectors and clicks |
| `type TEXT [--sel SEL] [--clear] [--mode auto\|wmchar\|keys\|paste]` | keyboard text entry (see below) |
| `paste TEXT [--sel SEL]` | put TEXT on the X clipboard and press Ctrl+V |
| `key KEY…` | xdotool key names: `Return`, `Tab`, `Escape`, `BackSpace`, `Down`, `ctrl+a`, `alt+f`, `F5`, … |
| `menu "Top>Sub>Item"` | click through menus; `&` and `_` mnemonics are ignored |
| `get SEL [PROP]` | read text (default) or any node property (`Checked`, `IsChecked`, `SelectedItem`, `rows`, …) |
| `wait SEL [--gone] [--timeout 10]` | wait until an element appears / disappears |
| `press BUTTON [--title T]` | click a button of a native dialog |
| `shot PATH [--window] [--region x,y,w,h]` | screenshot of the virtual screen, the main window (error if there is none), or a region. `--window` picks the first visible top-level window with a caption — with several windows open, pass `--region` instead |
| `compare ACTUAL BASELINE [--fuzz 1%] [--mask x,y,w,h]… [--diff out.png]` | pixel diff (exit 1 if any pixel differs or the sizes differ) |

## Python

```python
import sys; sys.path.insert(0, "<skill>/scripts")
import e2e
from e2e import Session, NotFound, AppNotResponding, SessionError, AgentError

s = Session.start(exe, args=(), port=47800, env=None, lane=None, connect_timeout=90, keep_on_failure=False,
                  require_window=True, window_timeout=30)   # require_window=False: apps that start hidden   # or Session.attach()
s.stop()                       # also usable as a context manager
s.alive()                      # process still answers on the agent socket
s.responsive(timeout=2.0)      # UI thread answers?   s.wait_responsive(timeout=30) raises AppNotResponding
s.tree(); s.windows(); s.dialogs(); s.press_dialog("OK", title=None)
s.find_all(sel); s.find(sel, timeout=None)        # find() auto-waits s.timeout (5 s) for a visible, on-screen element
s.get(sel, prop="text"); s.wait(sel, timeout=10, gone=False); s.wait_prop(sel, prop, expected, timeout=10)
s.click(sel, button=1, count=1, item=None, cell=None, scroll=True); s.dblclick(sel); s.rclick(sel)
s.scroll_into_view(sel, item=None, timeout=3.0)   # returns the element once it is on screen
s.hover(sel, wait=1.5); s.tooltip(timeout=3.0)     # WPF tooltip text or None
s.visual = True; s.tree(visual=None)                # WPF visual tree (template internals) for tree()/find()/click()
s.menu("ファイル(&F)>終了(&X)")
s.type_text(text, sel=None, clear=False, mode="auto"); s.chars(text); s.paste(text, sel=None); s.key("ctrl+a", "BackSpace")
s.shot(path, region=None, window=False); s.record_start(path, fps=10); s.record_stop()   # record grabs the whole 1280x800 screen
e2e.compare(actual, baseline, fuzz="1%", masks=[(x, y, w, h)], diff_out=None)
# -> {"pixels", "total", "ratio"}; different image sizes -> {"ratio": 1.0, "size_mismatch": True, "actual_size", "baseline_size"}
```

Exceptions: `NotFound` (no visible match, item/cell unsupported or out of range), `AppNotResponding` (UI thread did not answer within `E2E_UI_TIMEOUT_MS`),
`SessionError` (no session / port in use / start failed), `AgentError` (agent-side error), `TimeoutError` (`wait`, `connect`).

### Text entry (`type_text` modes)
- `auto` (default): ASCII is typed as real X11 key events; runs of non-ASCII are delivered by the agent as one `WM_CHAR` per UTF-16 unit to the focused window — what an IME's result string produces (KeyPress/TextChanged fire per character; surrogate pairs such as 𠮷 work). Falls back to clipboard paste only if the agent finds no focused window before sending anything; a partial/timeout error is reported without replaying text.
- `wmchar`: everything via `WM_CHAR`. `keys`: everything as X11 key events (non-ASCII drops characters — avoid). `paste`: whole string via Ctrl+V.
- No IME composition UI and no KeyDown/KeyUp for non-ASCII characters.

## Self test

`python3 scripts/selftest.py [--lanes …] [--tfm …] [--work DIR] [--keep-builds]` builds the sample apps and runs every lane.
Each lane's publish output is deleted as soon as that lane finishes; `--keep-builds` keeps them (faster re-runs, ~160 MB per lane).

## Selectors

`key=value` pairs joined by `;`, optional `#N` suffix for the N-th match (0-based).
An empty selector or a string with no `=` is rejected rather than matching every element.
Keys: `name` (WinForms `Name` / WPF `x:Name`), `id` (WPF AutomationId; falls back to `name` for nodes that have none, i.e. WinForms), `text` (exact, mnemonics `&`/`_` ignored),
`contains` (substring), `type` (CLR type name, e.g. `Button`, `DataGridView`), or any other node key (`Checked=True`).
Examples: `name=btnOK`, `type=Button;text=保存`, `type=TextBox#1`. Python callers may also pass a dict, e.g. `{"text": "子2"}` (TreeView nodes).
Only elements that are visible **and on screen** match (see `onScreen` below).

## Node schema (from the agent; screen coordinates are X11 pixels)

Common: `type`, `name`, `enabled`, `visible`, `focused`, `rect=[x,y,w,h]`, `onScreen` (false when scrolled/clipped out of its containers), `vrect` (the visible part of `rect`; clicks aim here), `children`,
plus `Text`/`Content`/`Header`/`Title`, `Checked`/`IsChecked`, `Value`, `SelectedIndex`, `IsSelected`, `IsExpanded` when present.

- WinForms: `ComboBox`/`ListBox` → `Items`, `SelectedItem`; `ListBox`/`ListView` → `itemRects`; `TabControl` → `tabs`, `tabRects`;
  `DataGridView` → `columns`, `rows` (first `E2E_MAX_ROWS`, default 200), `rowCount`, `truncated`, `cellRects[row][col]`, `currentCell`; `TreeView` → `nodes` (nested `text`, `rect`, `expanded`, `selected`);
  `MenuStrip`/`ToolStrip` → `items` (nested, each with `text`, `rect`, `enabled`, `visible` — items of a closed drop-down are `visible=false`). An open `ContextMenuStrip` appears as a child of its owner.
- WPF (logical tree by default): `automationId`; `Selector` → `SelectedItem`; `DataGrid` → `columns`, `rows` (read by calling every public property getter of each row item, so row objects are assumed to be plain data with cheap, side-effect-free getters; cap the work with `E2E_MAX_ROWS`), `rowCount`, `truncated`, `cellRects[row][col]` (realized, on-screen cells), `currentCell`; `ItemsControl` → `itemRects` (realized, on-screen containers only).
  Headered items (`TreeViewItem`, `TabItem`, `Expander`, `GroupBox`) also carry `headerRect` — the clickable header strip, which `click()` prefers over `rect`. `Content`/`Header` are only set when they are strings; a non-string content's type name goes to `ContentType`/`HeaderType`.
  Popups (ContextMenu, open sub-menus, drop-downs, ToolTip) are extra top-level roots (`PopupRoot`, visual-tree nodes) while they are open. Control-template internals (ContentPresenter, Border, scroll bars …) appear only in visual mode (`--visual` / `s.visual = True`); the node count is capped by `E2E_MAX_NODES`. WinForms tooltips are native windows and are not read.

## Agent protocol (for debugging)

Line-delimited JSON on `127.0.0.1:$E2E_AGENT_PORT`: `{"cmd":"ping"|"tree"|"windows"|"diag"|"uiping"|"chars","text":"…","timeout":ms}` → one JSON line.
Every UI-thread access has a timeout; a busy UI yields `{"ok":false,"code":"ui-timeout"}`. `diag` reports runtime, detected UI framework, entry assembly, AppDomain and loaded UI assemblies. Set `E2E_AGENT_LOG=<file>` to trace agent start-up.

## Environment variables

`E2E_HOME` (install root), `E2E_DISPLAY` (default `:99`), `E2E_WINEDEBUG` (default `-all`; e.g. `err+all` to debug Wine),
`E2E_UI_TIMEOUT_MS` (agent UI-thread timeout, default 5000; pass through `Session.start(env={...})`), `E2E_MAX_ROWS` (grid rows per tree, default 200), `E2E_MAX_NODES` (WPF nodes per tree, default 20000),
`E2E_MAX_CLIENTS` (concurrent agent connections, default 4), `E2E_MAX_REQUEST_CHARS` (longest request line, default 1048576), `E2E_CLIENT_IDLE_MS` (drop an idle client, default 600000),
`WINE_VERSION` (setup, default `11.0`; use an empty `E2E_HOME` to change an existing installation), `DOTNET_CHANNEL` (setup, default `8.0`; `10.0` adds SDK 10 next to an existing SDK, needed to build net9/net10 apps),
`E2E_ALLOW_UNVERIFIED=1` (setup / runtime download: install a download for which no checksum source exists; the default is to refuse it).
