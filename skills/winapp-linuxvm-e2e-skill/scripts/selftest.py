#!/usr/bin/env python3
"""End-to-end self test of the environment. Builds the sample apps (needs the .NET SDK) and runs scenarios on every lane.

  python3 selftest.py [--lanes winforms,wpf,winforms-fd,wpf-fd,net48,wpf48,controls,nested,scroll,wpf-scroll,coverage,wpf-coverage,hidden] [--work /tmp/e2e-selftest]
  python3 selftest.py --tfm net6.0-windows,net9.0-windows,net10.0-windows      # same scenario on other .NET versions (winforms/wpf, self-contained + framework-dependent)
                                                                                # needs an SDK that can target them: DOTNET_CHANNEL=10.0 bash setup.sh

Lanes: winforms / wpf = .NET 8 self-contained; *-fd = framework-dependent (runtime zips are downloaded and SHA-512 verified);
       net48 / wpf48 = .NET Framework 4.8 WinForms / WPF on wine-mono (AppDomain launcher lane; net48 also checks entry assembly / ProductName / app.config);
       controls = WinForms Tab/List/Tree/NumericUpDown/Radio, per-character WM_CHAR input (KeyPress), UI-thread hang detection;
       nested = GroupBox / bordered scrolled Panel / nested Panel coordinates and clipping;
       hidden = an app whose main window never becomes visible: start() fails clearly, require_window=False still works;
       coverage = the other common WinForms controls (multiline/password/masked/rich text, editable ComboBox, CheckedListBox, DateTimePicker,
                  TrackBar, ProgressBar, LinkLabel, PictureBox, ToolStrip, StatusStrip, SplitContainer, TableLayoutPanel, modal child form);
       wpf-coverage = the same for WPF (ToolBar, ToggleButton, TreeView, TabControl, PasswordBox, DatePicker, Slider, ProgressBar, Expander,
                      ListView/GridView, RadioButton, modal child Window);
       scroll / wpf-scroll = long ListBox, 200-row grid and a deep button inside a scroll container: scroll_into_view and auto-scrolling clicks.
"""
import argparse, json, os, shutil, subprocess, sys, time
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import e2e
from e2e import Session

SAMPLES = os.path.join(e2e.SKILL_DIR, "assets", "samples")
GREETING = "こんにちは、山田太郎さん"
results = []

def check(name, cond, detail=""):
    results.append((name, bool(cond)))
    print(("PASS " if cond else "FAIL ") + name + (f"  [{detail}]" if detail and not cond else ""), flush=True)

def build(work, proj, name, self_contained, tfm=None):
    out = os.path.join(work, name + ("-sc" if self_contained else "-fd") + (f"-{tfm}" if tfm else ""))
    shutil.rmtree(out, ignore_errors=True)   # never let an interrupted/older run satisfy this regression run
    env = dict(os.environ, DOTNET_ROOT=os.path.join(e2e.HOME, "dotnet"), DOTNET_CLI_TELEMETRY_OPTOUT="1", DOTNET_NOLOGO="1")
    env["PATH"] = os.path.join(e2e.HOME, "dotnet") + ":" + env["PATH"]
    src = os.path.join(work, "src", proj); shutil.rmtree(src, ignore_errors=True); shutil.copytree(os.path.join(SAMPLES, proj), src)
    csproj = os.path.join(src, proj + ".csproj")
    if tfm and not proj.endswith("48Sample"):   # edit the copy: a -p:TargetFramework override breaks the implicit restore
        text = open(csproj, encoding="utf-8").read(); open(csproj, "w", encoding="utf-8").write(text.replace("net8.0-windows", tfm))
    args = ["dotnet", "publish", csproj, "-c", "Release", "-o", out, "-v", "q", "-nologo"]
    if not proj.endswith("48Sample"): args.append(f"-p:SelfContained={'true' if self_contained else 'false'}")

    r = subprocess.run(args, env=env, capture_output=True, text=True)
    exe = os.path.join(out, proj + ".exe")
    if not os.path.exists(exe): raise RuntimeError(r.stdout[-2000:] + r.stderr[-2000:])
    return exe

def driver_regressions(work):
    """Fast checks for driver-only regressions that do not need a sample app."""
    try: e2e.parse_sel("typo-without-equals"); rejected = False
    except e2e.NotFound: rejected = True
    check("[driver] malformed selector is rejected", rejected)

    class PartialChars(Session):
        def __init__(self): super().__init__(); self.pasted = []
        def _raw(self, cmd, **params): return {"ok": False, "code": "ui-timeout", "sent": 1, "error": "timeout"}
        def _paste_now(self, text): self.pasted.append(text)
    p = PartialChars()
    try: p.type_text("表裏"); raised = False
    except e2e.AppNotResponding: raised = True
    check("[driver] partial WM_CHAR failure is not retried as a whole paste", raised and not p.pasted, p.pasted)

    baseline = os.path.join(work, "mask-baseline.png"); actual = os.path.join(work, "mask-actual.png")
    r1 = e2e.sh(["convert", "-size", "3x3", "xc:black", baseline])
    r2 = e2e.sh(["convert", "-size", "3x3", "xc:black", "-fill", "white", "-draw", "point 1,1", actual])
    masked = e2e.compare(actual, baseline, fuzz="0%", masks=[(0, 0, 1, 1)]) if r1.returncode == 0 and r2.returncode == 0 else None
    check("[driver] 1x1 comparison mask covers exactly one pixel", masked is not None and masked["pixels"] == 1, masked)

    try: Session()._xdo("definitely-not-an-xdotool-command"); xdo_raised = False
    except RuntimeError: xdo_raised = True
    check("[driver] xdotool failures are reported", xdo_raised)

    missing = os.path.join(work, f"missing-e2e-target-{os.getpid()}.exe")
    try: Session.start(missing); missing_rejected = False
    except e2e.SessionError as ex: missing_rejected = "executable not found" in str(ex)
    check("[driver] missing executable fails before launch", missing_rejected)

    # RO1 bounds: the agent refuses more than E2E_MAX_CLIENTS connections and drops an over-long request line
    badrc = os.path.join(work, "invalid.runtimeconfig.json")
    with open(badrc, "w", encoding="utf-8") as f:
        json.dump({"runtimeOptions": {"framework": {"name": "Microsoft.WindowsDesktop.App", "version": "/tmp/outside.0"}}}, f)
    try: e2e.ensure_windows_dotnet(badrc); bad_version_rejected = False
    except RuntimeError as ex: bad_version_rejected = "invalid .NET framework version" in str(ex)
    check("[driver] runtimeconfig version cannot escape the runtime cache", bad_version_rejected)

    partial = os.path.join(work, "runtime-partial-probe")
    os.makedirs(partial, exist_ok=True)
    with open(os.path.join(partial, "app.runtimeconfig.json"), "w", encoding="utf-8") as f:
        json.dump({"runtimeOptions": {"frameworks": [{"name": "Microsoft.NETCore.App", "version": "8.0.0"},
                                                     {"name": "Microsoft.WindowsDesktop.App", "version": "9.0.0"}]}}, f)
    try: e2e.ensure_windows_dotnet(os.path.join(partial, "app.runtimeconfig.json")); mixed_rejected = False
    except RuntimeError as ex: mixed_rejected = "mixed .NET framework channels" in str(ex)
    check("[driver] mixed runtime channels are rejected", mixed_rejected)

def scenario_hidden(work):
    """Apps whose main window never becomes visible: start() must say so, and require_window=False must still give a session."""
    exe = build(work, "WinFormsHiddenSample", "WinFormsHiddenSample", True)
    try: Session.start(exe, window_timeout=3); rejected = False
    except e2e.SessionError as ex: rejected = "no visible application window" in str(ex)
    check("[hidden] start() fails clearly when no window becomes visible (and cleans up)", rejected and not Session._port_open(47800))
    s = Session.start(exe, require_window=False)
    try:
        forms = [n for r in s.tree() for n in e2e.walk(r) if n.get("name") == "hiddenForm"]
        check("[hidden] require_window=False returns a usable session; the hidden form is in the tree", s.alive() and forms and forms[0].get("visible") is False, forms)
    finally: s.stop()

def scenario(s, tag, shots):
    is_wpf = tag.startswith("wpf")
    pfx = f"[{tag}] "
    # 1. Japanese typing (agent WM_CHAR) + button click -> label + grid
    s.type_text("山田太郎", sel="name=txtName")
    check(pfx + "type Japanese into TextBox", s.get("name=txtName", "Text") == "山田太郎", s.get("name=txtName", "Text"))
    s.click("name=btnGreet")
    lbl = s.get("name=lblResult")
    check(pfx + "label updated after click", lbl == GREETING, lbl)
    rows = s.get("name=grid", "rows")
    check(pfx + "grid row appended", rows and rows[-1][0] == "山田太郎", rows)
    s.click("name=grid", cell=(0, 1)); time.sleep(0.4)
    check(pfx + "grid cell click selects the cell (cellRects)", s.get("name=grid", "currentCell") == [0, 1], s.get("name=grid", "currentCell"))
    if is_wpf:
        # tooltip = popup root while shown; visual tree = control-template internals
        s.hover("name=btnGreet", wait=2.0); tip = s.tooltip(3)
        check(pfx + "WPF ToolTip is listed as a popup while shown", tip == "挨拶を実行", tip)
        s._xdo("mousemove", 900, 700); time.sleep(0.5)
        logical = sum(1 for r in s.tree() for _ in e2e.walk(r)); vt = [n for r in s.tree(visual=True) for n in e2e.walk(r)]
        btn = next(n for n in vt if n.get("name") == "btnGreet"); inner = sorted({n.get("type") for n in e2e.walk(btn) if n is not btn})
        check(pfx + "visual tree lists control-template internals", len(vt) > logical and "ContentPresenter" in inner, (logical, len(vt), inner))
    # 2. checkbox + combobox (real clicks / keys)
    s.click("name=chkUpper")
    check(pfx + "checkbox toggled", s.get("name=chkUpper", "IsChecked" if is_wpf else "Checked") is True)
    s.click("name=cmbMode"); s.key("Down", "Return")
    check(pfx + "combobox selection via keyboard", s.get("name=cmbMode", "SelectedItem") == "丁寧", s.get("name=cmbMode", "SelectedItem"))
    # 3. context menu (popup outside the window's own tree)
    s.rclick("name=lblResult"); time.sleep(0.5); s.click({"text": "リセット(&R)"}); time.sleep(0.5)
    check(pfx + "context menu item clicked", s.get("name=lblResult") == "(未実行)", s.get("name=lblResult"))
    # 4. validation dialog (native MessageBox)
    s.click("name=txtName"); s.key("ctrl+a", "BackSpace"); s.click("name=btnGreet"); time.sleep(0.8)
    d = s.dialogs()
    check(pfx + "MessageBox detected", len(d) == 1 and d[0]["title"] == "入力エラー" and "名前を入力してください" in d[0]["texts"], d)
    s.shot(os.path.join(shots, tag + "_dialog.png"))
    if d: s.press_dialog("OK")
    time.sleep(0.5)
    check(pfx + "MessageBox dismissed via button click", not s.dialogs())
    # 5. screenshot stability (needed for visual regression baselines)
    a = s.shot(os.path.join(shots, tag + "_a.png"), window=True); time.sleep(1); b = s.shot(os.path.join(shots, tag + "_b.png"), window=True)
    check(pfx + "screenshots are pixel-stable", e2e.compare(a, b, fuzz="0%")["pixels"] == 0)
    # 6. .NET Framework lane: the target must see itself as the entry assembly, with its own product name and config
    if tag == "net48":
        info = s.get("name=lblInfo")
        check(pfx + "entry assembly / ProductName / app.config seen by the app", info == "entry=WinForms48Sample|product=E2E Sample Product|cfg=from-config", info)
    # 7. menu -> Exit closes the app
    s.menu("ファイル(&F)>終了(&X)"); time.sleep(1.5)
    check(pfx + "menu Exit closed the app", not s.alive())

def scenario_controls(s, tag, shots):
    pfx = f"[{tag}] "; st = lambda: s.get("name=lblStatus")
    tabs = s.find("name=tabs")
    check(pfx + "TabControl tabs/tabRects exposed", tabs.get("tabs") == ["一覧", "設定"] and len(tabs["tabRects"]) == 2)
    s.click("name=lstItems", item=1); time.sleep(0.4); check(pfx + "ListBox item click", st() == "lb:みかん", st())
    s.click("name=lvItems", item=1); time.sleep(0.4); check(pfx + "ListView item click", st() == "lv:X2", st())
    s.click({"text": "子2"}); time.sleep(0.4); check(pfx + "TreeView node click", st() == "tv:子2", st())
    s.click("name=tabs", item=1); time.sleep(0.6); check(pfx + "TabControl tab switch", st() == "tab:1", st())
    check(pfx + "NumericUpDown value read", s.get("name=numQty", "Value") == 5)
    s.click("name=numQty"); s.key("ctrl+a"); s.type_text("12"); s.key("Tab"); time.sleep(0.4); check(pfx + "NumericUpDown typing", st() == "nud:12", st())
    s.click("name=rbB"); time.sleep(0.4); check(pfx + "RadioButton click/state", st() == "rb:B" and s.get("name=rbB", "Checked") is True)
    # WM_CHAR delivery: one KeyPress + one TextChanged per character (a clipboard paste would give 0 KeyPress / 1 TextChanged)
    s.type_text("あいう", sel="name=txtKeys")
    check(pfx + "WM_CHAR: text arrives", s.get("name=txtKeys", "Text") == "あいう", s.get("name=txtKeys", "Text"))
    check(pfx + "WM_CHAR: one KeyPress and TextChanged per character", s.get("name=lblKeys") == "keys:3 chg:3", s.get("name=lblKeys"))
    s.type_text("ab"); time.sleep(0.3)
    check(pfx + "ASCII keys + WM_CHAR mix keeps order", s.get("name=txtKeys", "Text") == "あいうab" and s.get("name=lblKeys") == "keys:5 chg:5", (s.get("name=txtKeys", "Text"), s.get("name=lblKeys")))
    s.type_text("表", sel="name=txtKeys", mode="paste")
    check(pfx + "paste mode still works", s.get("name=txtKeys", "Text").endswith("表"))
    # RO1 resource bounds of the loopback listener (no auth by design; these only stop a runaway client)
    import socket as _socket
    extra = []
    try:
        for _ in range(8):
            try:
                c = _socket.create_connection(("127.0.0.1", s.port), timeout=2); c.settimeout(2)
                c.sendall(b'{"cmd":"ping"}\n')
                extra.append((c, c.recv(64)))
            except OSError:
                extra.append((None, b""))
        answered = sum(1 for _, data in extra if data)
        check(pfx + f"agent caps concurrent clients ({answered} of 8 extra connections answered)", 0 < answered <= 4, answered)
    finally:
        for c, _ in extra:
            if c:
                try: c.close()
                except OSError: pass
    c = _socket.create_connection(("127.0.0.1", s.port), timeout=5); c.settimeout(10)
    try:
        c.sendall(b'{"cmd":"ping","pad":"' + b"x" * (1 << 21) + b'"}\n')
        dropped = c.recv(64) == b""
    except OSError:
        dropped = True
    finally:
        c.close()
    check(pfx + "agent drops an over-long request line", dropped)
    check(pfx + "session still usable after the bound checks", s.get("name=lblStatus") is not None)

    # UI thread hang detection
    s.click("name=btnFreeze"); time.sleep(1.0)
    check(pfx + "responsive() is False while the UI thread is blocked", s.responsive(1.0) is False)
    try: s.tree(); raised = False
    except e2e.AppNotResponding: raised = True
    check(pfx + "tree() raises AppNotResponding while blocked", raised)
    try: s.wait_responsive(25); rec = True
    except e2e.AppNotResponding: rec = False
    check(pfx + "recovers after the UI thread is free", rec and st() == "unfrozen", st())

def scenario_coverage(s, tag, shots):
    """Common WinForms controls beyond the core set, including the ones whose hit-testing is not the rectangle centre."""
    pfx = f"[{tag}] "; st = lambda: s.get("name=st")
    types = {n.get("name"): n.get("type") for r in s.tree() for n in e2e.walk(r) if n.get("name")}
    check(pfx + "all controls appear in the tree", types.get("dtp") == "DateTimePicker" and types.get("clb") == "CheckedListBox" and types.get("rtb") == "RichTextBox", types)
    check(pfx + "ProgressBar and TrackBar values readable", s.get("name=pbar", "Value") == 40 and s.get("name=trk", "Value") == 3)
    check(pfx + "StatusStrip label readable", any(i.get("text") == "ready" for r in s.tree() for n in e2e.walk(r) if n.get("type") == "StatusStrip" for i in n.get("items", [])))
    s.type_text("あいう", sel="name=tbMulti"); check(pfx + "multiline TextBox typing", s.get("name=tbMulti", "Text") == "あいう", s.get("name=tbMulti", "Text"))
    s.type_text("secret", sel="name=tbPass"); check(pfx + "password TextBox typing (value still readable)", s.get("name=tbPass", "Text") == "secret", s.get("name=tbPass", "Text"))
    s.type_text("1234567", sel="name=mtb"); time.sleep(0.3); check(pfx + "MaskedTextBox typing", st().startswith("mtb:"), st())
    s.type_text("abc", sel="name=cbEdit"); check(pfx + "editable ComboBox typing", s.get("name=cbEdit", "Text") == "abc", s.get("name=cbEdit", "Text"))
    s.type_text("XY", sel="name=rtb"); check(pfx + "RichTextBox typing", "XY" in (s.get("name=rtb", "Text") or ""), s.get("name=rtb", "Text"))
    s.click("name=pic"); time.sleep(0.4); check(pfx + "PictureBox click", st() == "pic clicked", st())
    s.click({"text": "Save"}); time.sleep(0.4); check(pfx + "ToolStrip button click", st() == "toolstrip Save", st())
    s.menu("More>Item1"); time.sleep(0.5); check(pfx + "ToolStrip drop-down item", st() == "toolstrip Item1", st())
    s.click("name=btnLeft"); time.sleep(0.4); check(pfx + "SplitContainer child click", st() == "split left", st())
    s.click("name=btnCell"); time.sleep(0.4); check(pfx + "TableLayoutPanel child click", st() == "tlp cell", st())
    s.click("name=btnPB"); time.sleep(0.4); check(pfx + "ProgressBar updates", s.get("name=pbar", "Value") == 50, s.get("name=pbar", "Value"))
    s.click("name=trk"); s.key("Right"); time.sleep(0.4); check(pfx + "TrackBar keyboard", st().startswith("trk:"), st())
    s.click("name=dtp"); s.key("Up"); time.sleep(0.5); check(pfx + "DateTimePicker keyboard", st().startswith("dtp:"), st())
    # hit-testing quirks documented in references/pitfalls.md
    s.click("name=clb", item=1); s.key("space"); time.sleep(0.4)
    check(pfx + "CheckedListBox toggles with select + Space (a centre click only selects)", st().startswith("clb:1"), st())
    lr = s.find("name=link")["rect"]; s._click_xy(lr[0] + 15, lr[1] + lr[3] // 2); time.sleep(0.4)
    check(pfx + "LinkLabel fires on the link text, not the rectangle centre", st() == "link clicked", st())
    # a modal child Form (not a MessageBox)
    s.click("name=btnModal"); time.sleep(1.2)
    check(pfx + "modal child Form is in the tree", "childModal" in [n.get("name") for r in s.tree() for n in e2e.walk(r)])
    s.click("name=btnChildOk"); time.sleep(1.0)
    check(pfx + "modal child closed by clicking its button", st() == "modal closed", st())

def scenario_wpf_coverage(s, tag, shots):
    """Common WPF controls beyond the core set, including headered items whose clickable area is only the header."""
    pfx = f"[{tag}] "; st = lambda: s.get("name=lblStatus")
    check(pfx + "Slider and ProgressBar values readable", s.get("name=sld", "Value") == 3.0 and s.get("name=pbar", "Value") == 40.0)
    s.click({"text": "Save"}); time.sleep(0.4); check(pfx + "ToolBar button click", st() == "toolbar Save", st())
    s.click("name=tglBold"); time.sleep(0.4); check(pfx + "ToggleButton click", st() == "toggle:True", st())
    s.click({"text": "子2"}); time.sleep(0.6); check(pfx + "TreeViewItem click (headerRect, not the item's full width)", st() == "tv:子2", st())
    s.click({"text": "入力"}); time.sleep(0.9); check(pfx + "TabItem selected by its header text", st() == "tab:1", st())
    s.type_text("secret", sel="name=pwd"); time.sleep(0.5); check(pfx + "PasswordBox typing", st() == "pwd:6", st())
    s.type_text("あいう", sel="name=tbMulti"); check(pfx + "multiline TextBox typing", s.get("name=tbMulti", "Text") == "あいう", s.get("name=tbMulti", "Text"))
    s.type_text("abc", sel="name=cbEdit"); check(pfx + "editable ComboBox typing", s.get("name=cbEdit", "Text") == "abc", s.get("name=cbEdit", "Text"))
    s.click("name=dp"); s.type_text("2026/03/04"); s.key("Return"); time.sleep(0.7)
    check(pfx + "DatePicker typing", (st() or "").startswith("dp:"), st())
    s.click({"text": "ツリー"}); time.sleep(0.6); check(pfx + "TabItem switched back", st() == "tab:0", st())
    s.click("name=btnPB"); time.sleep(0.4); check(pfx + "ProgressBar updates", s.get("name=pbar", "Value") == 50.0, s.get("name=pbar", "Value"))
    s.click("name=sld"); s.key("Right"); time.sleep(0.4); check(pfx + "Slider keyboard", (st() or "").startswith("sld:"), st())
    s.click({"text": "詳細"}); time.sleep(0.6); check(pfx + "Expander toggles via its header", st() == "exp:True", st())
    check(pfx + "Expander content becomes visible", s.find_all("name=btnInExpander") != [])
    s.click("name=lv", item=1); time.sleep(0.5); check(pfx + "ListView (GridView) row click", st() == "lv:r2", st())
    s.click("name=rbB"); time.sleep(0.4); check(pfx + "RadioButton click", st() == "rb:B", st())
    s.click("name=btnModal"); time.sleep(1.6)
    check(pfx + "modal child Window is in the tree", "childModal" in [n.get("name") for r in s.tree() for n in e2e.walk(r)])
    s.click("name=btnChildOk"); time.sleep(1.0); check(pfx + "modal child closed by clicking its button", st() == "modal closed", st())

def scenario_nested(s, tag, shots):
    pfx = f"[{tag}] "
    for name in ("b1", "b2", "b4"):
        s.click(f"name={name}"); time.sleep(0.3)
        check(pfx + f"click {name} lands (GroupBox / scrolled bordered Panel / nested Panel)", s.get("name=lblStatus") == name, s.get("name=lblStatus"))
    check(pfx + "scrolled-out control is not findable as visible", s.find_all("name=b3") == [])
    n = [n for r in s.tree() for n in e2e.walk(r) if n.get("name") == "b3"][0]
    check(pfx + "scrolled-out control reports onScreen=false", n.get("onScreen") is False and n.get("visible") is True, n)

def scenario_scroll(s, tag, shots):
    pfx = f"[{tag}] "; is_wpf = "wpf" in tag; st = lambda: s.get("name=lblStatus")
    # an element far down a scroll container: not on screen, but the NotFound hint says so and scroll_into_view fixes it
    hidden = [n for r in s.tree() for n in e2e.walk(r) if n.get("name") == "btnDeep"]
    check(pfx + "deep button reports onScreen=false", hidden and hidden[0].get("onScreen") is False, hidden)
    try: s.find("name=btnDeep", timeout=0.5); msg = ""
    except e2e.NotFound as ex: msg = str(ex)
    check(pfx + "NotFound explains it is scrolled out and names scroll_into_view", "not on screen" in msg and "scroll_into_view" in msg, msg[:160])
    s.scroll_into_view("name=btnDeep" if is_wpf else "id=btnDeep")   # WinForms id= must retain its documented Name fallback
    check(pfx + "scroll_into_view brings it on screen", s.find("name=btnDeep", timeout=3).get("onScreen") is True)
    s.click("name=btnDeep"); time.sleep(0.4)
    check(pfx + "click on the scrolled-in button", st() == "deep clicked", st())
    # list item far down: click(item=...) scrolls by itself
    s.click("name=lstLong", item=150); time.sleep(0.5)
    check(pfx + "click on list item 150 (auto-scrolled)", st() == "lb:item150", st())
    # grid cell far down
    s.click("name=grid", cell=(120, 1)); time.sleep(0.6)
    if is_wpf:
        check(pfx + "click on grid cell row 120 (auto-scrolled)", st() == "cell:120,1", st())
    else:
        check(pfx + "click on grid cell row 120 (auto-scrolled)", st() == "cell:120,1", st())
    check(pfx + "app still alive", s.alive())

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--lanes", default=None); ap.add_argument("--work", default="/tmp/e2e-selftest")
    ap.add_argument("--tfm", default="", help="comma-separated target frameworks, e.g. net6.0-windows,net9.0-windows,net10.0-windows")
    ap.add_argument("--keep-builds", action="store_true", help="keep each lane's published app (default: delete it after the lane, ~160 MB each)")
    a = ap.parse_args()
    tfms = [t for t in a.tfm.split(",") if t] or [None]
    lanes = (a.lanes or ("winforms,wpf,winforms-fd,wpf-fd" if a.tfm else "winforms,wpf,winforms-fd,wpf-fd,net48,wpf48,controls,nested,scroll,wpf-scroll,coverage,wpf-coverage,hidden")).split(",")
    os.makedirs(a.work, exist_ok=True); shots = os.path.join(a.work, "shots"); os.makedirs(shots, exist_ok=True)
    if not e2e.doctor(): print("doctor failed; run scripts/setup.sh"); sys.exit(2)
    driver_regressions(a.work)
    if "hidden" in lanes:
        print("\n=== lane hidden ===", flush=True)
        try: scenario_hidden(a.work)
        except Exception as ex: check("[hidden] lane ran", False, repr(ex)[:1500]); e2e.sh([e2e.WINESERVER, "-k"], env=e2e.wenv())
        lanes = [l for l in lanes if l != "hidden"]
    spec = {"winforms": ("WinFormsSample", True), "wpf": ("WpfSample", True), "winforms-fd": ("WinFormsSample", False),
            "wpf-fd": ("WpfSample", False), "net48": ("WinForms48Sample", True), "wpf48": ("Wpf48Sample", True),
            "controls": ("WinFormsControlsSample", True), "nested": ("WinFormsNestedSample", True),
            "scroll": ("WinFormsScrollSample", True), "wpf-scroll": ("WpfScrollSample", True),
            "coverage": ("WinFormsCoverageSample", True), "wpf-coverage": ("WpfCoverageSample", True)}
    fn = {"controls": scenario_controls, "nested": scenario_nested, "scroll": scenario_scroll, "wpf-scroll": scenario_scroll,
          "coverage": scenario_coverage, "wpf-coverage": scenario_wpf_coverage}
    for tfm in tfms:
        for lane in lanes:
            proj, sc = spec[lane]
            if tfm and proj.endswith("48Sample"): continue      # .NET Framework samples have a fixed target
            tag = lane if not tfm else f"{lane}@{tfm.replace('-windows', '')}"
            print(f"\n=== lane {tag} ===", flush=True)
            exe = None
            try:
                exe = build(a.work, proj, proj, sc, tfm)
                s = Session.start(exe, port=47800, env={"E2E_UI_TIMEOUT_MS": "1500"} if lane == "controls" else None)
                try: fn.get(lane, scenario)(s, tag, shots)
                finally: s.stop()
            except Exception as ex:
                check(f"[{tag}] lane ran", False, repr(ex)[:1500]); e2e.sh([e2e.WINESERVER, "-k"], env=e2e.wenv())
            finally:
                if exe and not a.keep_builds:
                    shutil.rmtree(os.path.dirname(exe), ignore_errors=True)
                    shutil.rmtree(os.path.join(a.work, "src", proj), ignore_errors=True)
    failed = [n for n, ok in results if not ok]
    print(f"\n{len(results) - len(failed)}/{len(results)} passed"); sys.exit(1 if failed else 0)

if __name__ == "__main__":
    main()
