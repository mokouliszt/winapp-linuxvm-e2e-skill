#!/usr/bin/env python3
"""winapp-linuxvm-e2e-skill driver: Xvfb + Wine + in-process agent + xdotool.

Library:   sys.path.insert(0, "<skill>/scripts"); from e2e import Session
CLI:       python3 e2e.py --help        (exit codes: 0 ok, 1 check failed, 3 no session/app unreachable, 4 element not found, 5 app not responding)
"""
import argparse, hashlib, json, os, re, shutil, signal, socket, subprocess, sys, tempfile, time, urllib.request, zipfile

HOME = os.environ.get("E2E_HOME", "/opt/winapp-linuxvm-e2e-skill")
WINE = os.environ.get("WINE", f"{HOME}/wine/bin/wine")
WINESERVER = os.path.join(os.path.dirname(WINE), "wineserver")
PREFIX = os.environ.get("WINEPREFIX", f"{HOME}/prefix")
DISPLAY = os.environ.get("E2E_DISPLAY", os.environ.get("DISPLAY", ":99"))
SKILL_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
AGENT_BIN = os.path.join(SKILL_DIR, "agent", "bin")
STATE = os.path.join(HOME, "session.json")
LOGS = os.path.join(HOME, "logs")
DEVNULL = subprocess.DEVNULL


# ------------------------------------------------------------------ errors
class NotFound(Exception):
    """No (visible) element matches the selector."""

class AppNotResponding(Exception):
    """The application's UI thread did not answer within the agent's timeout (busy or hung)."""

class AgentError(RuntimeError):
    """The in-process agent reported an error."""

class SessionError(RuntimeError):
    """No session, session already running, or the app could not be started/reached."""


# ------------------------------------------------------------------ helpers
def sh(cmd, **kw):
    return subprocess.run(cmd, capture_output=True, text=True, **kw)

def wenv(extra=None):
    e = dict(os.environ)
    for k in ("DOTNET_ROOT", "DOTNET_ROOT_SDK", "DOTNET_STARTUP_HOOKS"):  # Linux-side values must not leak into Wine
        e.pop(k, None)
    e.update(DISPLAY=DISPLAY, WINEPREFIX=PREFIX, WINEARCH="win64", WINEDLLOVERRIDES="mshtml=",
             WINEDEBUG=os.environ.get("E2E_WINEDEBUG", "-all"), DOTNET_CLI_TELEMETRY_OPTOUT="1")
    e.update(extra or {})
    return e

def to_win(path):
    return "Z:" + os.path.abspath(path).replace("/", "\\")

def xenv():
    return dict(os.environ, DISPLAY=DISPLAY)

def xvfb_up():
    return sh(["xdpyinfo", "-display", DISPLAY]).returncode == 0

def ensure_xvfb(size="1280x800x24"):
    if xvfb_up():
        return
    subprocess.Popen(["Xvfb", DISPLAY, "-screen", "0", size, "-nolisten", "tcp"], stdout=DEVNULL, stderr=DEVNULL,
                     stdin=DEVNULL, start_new_session=True)
    for _ in range(40):
        if xvfb_up():
            return
        time.sleep(0.25)
    raise RuntimeError("Xvfb did not start")

def _download(url, dest):
    with urllib.request.urlopen(url, timeout=300) as r, open(dest, "wb") as f:
        expected = int(r.headers.get("Content-Length") or -1)
        shutil.copyfileobj(r, f)
    if expected >= 0 and os.path.getsize(dest) != expected:
        os.remove(dest)
        raise RuntimeError(f"truncated download of {url}: got {os.path.getsize(dest) if os.path.exists(dest) else 0} of {expected} bytes")

def _extract_atomically(zip_path, dest, must_contain=()):
    """Extract into a sibling staging directory and rename into place, so an interrupted run never leaves a
    half-extracted directory that later looks complete."""
    parent = os.path.dirname(os.path.abspath(dest))
    os.makedirs(parent, exist_ok=True)
    staging = dest + ".partial"
    shutil.rmtree(staging, ignore_errors=True); os.makedirs(staging)
    zipfile.ZipFile(zip_path).extractall(staging)
    for rel in must_contain:
        if not os.path.exists(os.path.join(staging, rel)):
            shutil.rmtree(staging, ignore_errors=True)
            raise RuntimeError(f"{os.path.basename(zip_path)} did not contain {rel}")
    shutil.rmtree(dest, ignore_errors=True); os.replace(staging, dest)

def _verify_sha512(path, expected):
    h = hashlib.sha512()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    if h.hexdigest().lower() != expected.lower():
        os.remove(path)
        raise RuntimeError(f"SHA-512 mismatch for {os.path.basename(path)} (download discarded)")

def _tail(path, n=800):
    try:
        return open(path, errors="replace").read()[-n:].strip()
    except OSError:
        return "(missing)"


# ------------------------------------------------------------------ .NET runtime for framework-dependent apps
def ensure_windows_dotnet(runtimeconfig):
    """Download the Windows .NET runtime zips (no installer) for a framework-dependent app. Returns the DOTNET_ROOT dir.
    Every zip is verified against the SHA-512 published in Microsoft's release metadata."""
    rc = json.load(open(runtimeconfig))["runtimeOptions"]
    fws = rc.get("frameworks") or ([rc["framework"]] if "framework" in rc else [])
    if not fws:
        return None
    names = {f["name"]: f["version"] for f in fws}
    channels = set()
    for version in names.values():
        m = re.match(r"^(\d+)\.(\d+)(?:\.|$)", version) if isinstance(version, str) else None
        if not m:
            raise RuntimeError(f"invalid .NET framework version in {runtimeconfig}: {version!r}")
        channels.add(f"{m.group(1)}.{m.group(2)}")
    if len(channels) != 1:
        raise RuntimeError(f"mixed .NET framework channels in {runtimeconfig}: {sorted(channels)}")
    channel = next(iter(channels))
    root = os.path.join(HOME, "dotnet-win", channel)
    if os.path.exists(os.path.join(root, ".complete")) and os.path.isdir(os.path.join(root, "host", "fxr")):
        return root
    shutil.rmtree(root, ignore_errors=True); shutil.rmtree(root + ".partial", ignore_errors=True)   # discard partial extractions
    staging = root + ".partial"; os.makedirs(staging)
    meta = json.load(urllib.request.urlopen(f"https://builds.dotnet.microsoft.com/dotnet/release-metadata/{channel}/releases.json", timeout=60))
    rel = next(r for r in meta["releases"] if r.get("runtime") and r["runtime"].get("files") and r.get("windowsdesktop", {}).get("files"))
    def zinfo(section, prefix):  # NB: newer channels list apphost-pack / targeting-pack zips first, so match on the file name
        for f in rel[section]["files"]:
            if f["rid"] == "win-x64" and f["url"].endswith("-win-x64.zip") and os.path.basename(f["url"]).startswith(prefix):
                return f["url"], f.get("hash")
        raise RuntimeError(f"no {prefix}*-win-x64.zip in release metadata for {channel}")
    todo = [zinfo("runtime", "dotnet-runtime-")]
    if "Microsoft.WindowsDesktop.App" in names:
        todo.append(zinfo("windowsdesktop", "windowsdesktop-runtime-"))
    try:
        for url, digest in todo:
            tmp = os.path.join(staging, "_dl.zip"); _download(url, tmp)
            if digest:
                _verify_sha512(tmp, digest)
            elif os.environ.get("E2E_ALLOW_UNVERIFIED") == "1":
                print(f"WARNING: no SHA-512 published for {url}; installed unverified (E2E_ALLOW_UNVERIFIED=1)", file=sys.stderr)
            else:   # fail closed, like setup.sh
                os.remove(tmp)
                raise RuntimeError(f"no SHA-512 in the release metadata for {url}; refusing to install it. Set E2E_ALLOW_UNVERIFIED=1 to override.")
            zipfile.ZipFile(tmp).extractall(staging); os.remove(tmp)
        if not os.path.isdir(os.path.join(staging, "host", "fxr")):
            shutil.rmtree(staging, ignore_errors=True)
            raise RuntimeError(f"runtime extraction incomplete for channel {channel}")
        with open(os.path.join(staging, ".complete"), "w") as f: f.write(rel["release-version"])
    except BaseException:
        shutil.rmtree(staging, ignore_errors=True); raise
    os.replace(staging, root)   # only a complete runtime ever appears under its final name
    return root


# ------------------------------------------------------------------ selectors / tree helpers
def norm(s):
    return re.sub(r"[&_]", "", s) if isinstance(s, str) else s

def node_text(n):
    for k in ("Text", "Content", "Header", "Title", "text"):
        v = n.get(k)
        if isinstance(v, str) and v != "":
            return v
    return None

def walk(node):
    yield node
    for c in node.get("children", []):
        yield from walk(c)
    for k in ("items", "nodes"):
        for c in node.get(k, []) if isinstance(node.get(k), list) else []:
            if isinstance(c, dict):
                yield from walk(c)

def parse_sel(sel):
    if isinstance(sel, dict):
        q = dict(sel)
        if not q:
            raise NotFound("invalid empty selector; expected key=value (for example name=btnOK)")
        return q, 0
    idx = 0
    m = re.search(r"#(\d+)$", sel)
    if m:
        idx = int(m.group(1)); sel = sel[:m.start()]
    q = {}
    for part in sel.split(";"):
        if "=" in part:
            k, v = part.split("=", 1); q[k.strip()] = v
    if not q:
        raise NotFound(f"invalid selector {sel!r}; expected key=value (for example name=btnOK)")
    return q, idx

def matches(n, q):
    for k, v in q.items():
        if k == "id":  # WPF AutomationId; WinForms controls have none, so their Name is used
            if n.get("automationId", n.get("name")) != v: return False
        elif k == "text":
            if norm(node_text(n)) != norm(v): return False
        elif k == "contains":
            if v not in (node_text(n) or ""): return False
        elif k == "type":
            if n.get("type") != v: return False
        elif k == "name":
            if n.get("name") != v: return False
        else:
            if str(n.get(k)) != v: return False
    return True

def effectively_visible(n):
    """Has an on-screen rectangle, is visible, and is not scrolled/clipped out of its containers."""
    return bool(n.get("rect")) and n.get("visible", True) and n.get("onScreen", True)

def center(rect):
    x, y, w, h = rect
    return x + w // 2, y + h // 2


# ------------------------------------------------------------------ Session
class Session:
    """One running app + its agent connection."""

    def __init__(self, port=47800):
        self.port = port; self.sock = None; self.f = None; self.p = None; self.timeout = 5.0
        self.visual = False   # WPF: True = walk the visual tree (control-template internals) in tree()/find()/click()

    # ---- lifecycle
    @staticmethod
    def _port_open(port):
        try:
            socket.create_connection(("127.0.0.1", port), timeout=1).close(); return True
        except OSError:
            return False

    @classmethod
    def start(cls, exe, args=(), port=47800, env=None, lane=None, log=None, connect_timeout=90, keep_on_failure=False,
              require_window=True, window_timeout=30):
        """Launch `exe` under Wine with the agent. On failure the half-started app and the state file are cleaned up
        (keep_on_failure=True leaves them for inspection).
        require_window=True (default): fail if no application window becomes visible within `window_timeout` seconds.
        Pass require_window=False for apps that start hidden (tray apps, background UIs): start() then returns as soon as the agent answers."""
        exe = os.path.abspath(exe)
        if not os.path.isfile(exe):
            raise SessionError(f"executable not found: {exe}")
        ensure_xvfb()
        if cls._port_open(port):
            raise SessionError(f"agent port {port} is already in use: a session (or an orphaned app) is still running. Call stop first.")
        try: os.remove(STATE)   # stale state of a dead session
        except OSError: pass
        d = os.path.dirname(exe); stem = os.path.splitext(os.path.basename(exe))[0]
        rc = os.path.join(d, stem + ".runtimeconfig.json")
        lane = lane or ("core" if (os.path.exists(rc) or os.path.exists(os.path.join(d, "coreclr.dll"))) else "framework")
        os.makedirs(LOGS, exist_ok=True)
        agent_log = os.path.join(LOGS, "agent.log")
        try: os.remove(agent_log)
        except OSError: pass
        e = wenv(); e.update(env or {})
        e.update(E2E_AGENT_PORT=str(port), E2E_AGENT_LOG=to_win(agent_log))   # reserved: must agree with the driver
        run_exe, run_args, cwd = exe, list(args), d
        if lane == "core":
            e["DOTNET_STARTUP_HOOKS"] = to_win(os.path.join(AGENT_BIN, "core", "E2EAgent.dll"))
            if os.path.exists(rc) and not os.path.exists(os.path.join(d, "coreclr.dll")):
                root = ensure_windows_dotnet(rc)
                if root:
                    e["DOTNET_ROOT"] = to_win(root); e["DOTNET_ROOT_X64"] = to_win(root)
        else:  # .NET Framework: run the target in its own AppDomain inside E2ELauncher, staged next to a copy of the app
            stage = os.path.join(HOME, "stage", stem)
            shutil.rmtree(stage, ignore_errors=True); shutil.copytree(d, stage)
            for f in ("E2EAgent.dll", "E2ELauncher.exe", "E2ELauncher.exe.config"):
                shutil.copy(os.path.join(AGENT_BIN, "net48", f), stage)
            run_exe, run_args, cwd = os.path.join(stage, "E2ELauncher.exe"), [os.path.basename(exe)] + list(args), stage
        app_log = log or os.path.join(LOGS, "app.log")
        s = cls(port)
        try:
            with open(app_log, "w") as logf:   # the child keeps its own descriptor
                s.p = subprocess.Popen([WINE, run_exe, *run_args], cwd=cwd, env=e, stdout=logf, stderr=subprocess.STDOUT, start_new_session=True)
            with open(STATE, "w") as f:
                json.dump({"port": port, "exe": exe, "lane": lane, "log": app_log}, f)
            s.connect(connect_timeout, wait_visible=require_window, window_timeout=window_timeout)
        except Exception as ex:
            msg = f"{ex}\n--- app.log tail ---\n{_tail(app_log)}\n--- agent.log tail ---\n{_tail(agent_log)}"
            if not keep_on_failure:
                if s.p is not None:
                    s.stop()
                else:
                    try: os.remove(STATE)
                    except OSError: pass
            raise SessionError(f"could not start {os.path.basename(exe)}: {msg}") from ex
        return s

    @classmethod
    def attach(cls):
        if not os.path.exists(STATE):
            raise SessionError("no session (run `start` first)")
        try:
            with open(STATE) as f: st = json.load(f)
            port = st["port"]
        except (OSError, ValueError, KeyError, TypeError) as ex:
            raise SessionError(f"invalid session state in {STATE}: {ex}. Run `stop`, then `start` again.") from ex
        s = cls(port)
        try:
            s.connect(15, wait_visible=False)
        except Exception as ex:
            raise SessionError(f"app not reachable on port {st['port']} (exited or hung?): {ex}. Run `stop`, then `start` again.") from ex
        return s

    def connect(self, timeout=60, wait_visible=True, window_timeout=30):
        t0 = time.time(); last = None; no_window = False
        while time.time() - t0 < timeout:
            try:
                self._close_connection()
                self.sock = socket.create_connection(("127.0.0.1", self.port), timeout=15)
                self.f = self.sock.makefile("rw", encoding="utf-8", newline="\n")
                r = self._raw("ping")
                if r.get("ok") and r.get("fw") != "none":
                    t1 = time.time(); visible = not wait_visible
                    while wait_visible and time.time() - t1 < window_timeout and time.time() - t0 < timeout:  # a framework is reported before the first window is shown
                        try:
                            if any(effectively_visible(n) for rt in self.tree() for n in walk(rt)):
                                visible = True; break
                        except AppNotResponding:
                            pass
                        except Exception:
                            pass
                        time.sleep(0.3)
                    if not visible:
                        no_window = True; last = "agent is ready, but no visible application window appeared"
                        break
                    time.sleep(0.5 if wait_visible else 0); return r
                if not r.get("ok"): last = r.get("error")
            except Exception as ex:
                last = ex
            self._close_connection()
            time.sleep(0.5)
        self._close_connection()
        hint = _tail(os.path.join(LOGS, "agent.log")) if os.path.exists(os.path.join(LOGS, "agent.log")) else "(agent.log empty: startup hook / launcher never ran)"
        if no_window:
            raise TimeoutError(f"agent ready but no visible application window appeared within {min(window_timeout, timeout)}s (for apps that start hidden use require_window=False / --no-wait-window); see {LOGS}/app.log. agent.log: {hint}")
        raise TimeoutError(f"agent not ready after {timeout}s ({last}); see {LOGS}/app.log. agent.log: {hint}")

    def _close_connection(self):
        try:
            if self.f: self.f.close()
        except Exception:
            pass
        try:
            if self.sock: self.sock.close()
        except Exception:
            pass
        self.f = None; self.sock = None

    def _raw(self, cmd, **params):
        self.f.write(json.dumps({"cmd": cmd, **params}) + "\n"); self.f.flush()
        line = self.f.readline()
        if not line:
            raise ConnectionError("agent closed the connection (app exited?)")
        return json.loads(line)

    def call(self, cmd, **params):
        r = self._raw(cmd, **params)
        if not r.get("ok"):
            if r.get("code") == "ui-timeout":
                raise AppNotResponding(r.get("error") or "UI thread not responding")
            raise AgentError(r.get("error") or str(r))
        return r

    def alive(self):
        """The process still answers on the agent socket (says nothing about the UI thread; see responsive())."""
        try:
            self._raw("ping"); return True
        except Exception:
            return False

    def responsive(self, timeout=2.0):
        """True if the UI thread answers within `timeout` seconds."""
        try:
            return bool(self._raw("uiping", timeout=int(timeout * 1000)).get("ok"))
        except Exception:
            return False

    def wait_responsive(self, timeout=30.0):
        t0 = time.time()
        while time.time() - t0 < timeout:
            if self.responsive(1.0): return True
            time.sleep(0.3)
        raise AppNotResponding(f"UI thread still unresponsive after {timeout}s")

    def stop(self):
        self._close_connection()
        sh([WINESERVER, "-k"], env=wenv())
        try: os.remove(STATE)
        except OSError: pass

    def __enter__(self): return self
    def __exit__(self, *a): self.stop()

    # ---- inspection
    def tree(self, visual=None):
        """Control tree. WPF: visual=True (or s.visual = True) also lists control-template internals; default is the logical tree plus open popups."""
        v = self.visual if visual is None else visual
        return (self.call("tree", visual=1) if v else self.call("tree"))["roots"]

    def windows(self):
        return self.call("windows")["windows"]

    def find_all(self, sel, visible=True):
        q, _ = parse_sel(sel); out = []
        for r in self.tree():
            for n in walk(r):
                if matches(n, q) and (not visible or effectively_visible(n)):
                    out.append(n)
        return out

    def _find_once(self, sel):
        q, idx = parse_sel(sel); hits = self.find_all(sel)
        if len(hits) <= idx:
            offscreen = [n for n in self.find_all(sel, visible=False) if n.get("rect") and not effectively_visible(n)]
            if offscreen:
                raise NotFound(f"{sel!r} exists but is not on screen (scrolled out of its container or hidden): "
                               f"visible={offscreen[0].get('visible')}, onScreen={offscreen[0].get('onScreen')}. "
                               f"Call scroll_into_view({sel!r}) (CLI: scroll {sel!r}) or scroll the container, then retry.")
            cands = [(n.get("type"), n.get("name") or n.get("automationId"), node_text(n)) for r in self.tree() for n in walk(r) if effectively_visible(n)]
            raise NotFound(f"no match for {sel!r}. visible candidates: {cands[:40]}")
        return hits[idx]

    def find(self, sel, timeout=None):
        """Like Playwright auto-wait: polls until the element is visible (default self.timeout seconds)."""
        t0 = time.time(); limit = self.timeout if timeout is None else timeout
        while True:
            try:
                return self._find_once(sel)
            except NotFound:
                if time.time() - t0 >= limit: raise
                time.sleep(0.3)

    def scroll_into_view(self, sel, item=None, timeout=3.0):
        """Ask the app to scroll the element (or list/grid item) into view: WinForms ScrollControlIntoView / EnsureVisible,
        WPF BringIntoView / ScrollIntoView. Returns the element once it is on screen."""
        q, _ = parse_sel(sel)
        params = {k: v for k, v in q.items() if k in ("name", "text", "type")}
        if "id" in q: params["automationId"] = q["id"]
        if not params:
            raise NotFound(f"scroll_into_view needs name=/id=/text=/type= in the selector, got {sel!r}")
        if item is not None: params["index"] = item
        r = self._raw("scrollinto", **params)
        if not r.get("ok") and r.get("code") == "ui-timeout":
            raise AppNotResponding(r.get("error") or "UI thread not responding")
        t0 = time.time()
        while time.time() - t0 < timeout:
            try:
                return self._find_once(sel)
            except NotFound:
                time.sleep(0.2)
        return self._find_once(sel)   # raises NotFound with the usual hint

    def get(self, sel, prop="text"):
        n = self.find(sel)
        return node_text(n) if prop == "text" else n.get(prop)

    def wait(self, sel, timeout=10, gone=False, interval=0.3):
        t0 = time.time()
        while time.time() - t0 < timeout:
            try:
                self._find_once(sel); found = True
            except NotFound:
                found = False
            if found != gone:
                return True
            time.sleep(interval)
        raise TimeoutError(f"wait {'gone' if gone else 'appear'} {sel!r} timed out")

    def wait_prop(self, sel, prop, expected, timeout=10):
        t0 = time.time(); v = None
        while time.time() - t0 < timeout:
            v = self.get(sel, prop)
            if v == expected: return v
            time.sleep(0.3)
        raise AssertionError(f"{sel!r}.{prop} = {v!r}, expected {expected!r}")

    def dialogs(self):
        """Native dialogs (#32770: MessageBox, common dialogs) with their captions and child texts."""
        out = []
        for w in self.windows():
            if w["class"] == "#32770":
                out.append({"title": w["text"], "rect": w["rect"], "hwnd": w["hwnd"],
                            "texts": [c["text"] for c in w["children"] if c["class"] == "Static" and c["text"]],
                            "buttons": [{"text": c["text"], "rect": c["rect"]} for c in w["children"] if c["class"] == "Button"]})
        return out

    def press_dialog(self, button, title=None):
        for d in self.dialogs():
            if title is None or d["title"] == title:
                for b in d["buttons"]:
                    if norm(b["text"]) == norm(button) or button in b["text"]:
                        self._click_xy(*center(b["rect"])); return d
        raise NotFound(f"dialog button {button!r} not found: {self.dialogs()}")

    # ---- input (real X11 events -> Win32 messages)
    def _xdo(self, *a):
        r = sh(["xdotool", *map(str, a)], env=xenv())
        if r.returncode != 0:
            raise RuntimeError(f"xdotool {' '.join(map(str, a))} failed ({r.returncode}): {r.stderr.strip()}")
        return r

    def _click_xy(self, x, y, button=1, count=1):
        self._xdo("mousemove", x, y); time.sleep(0.15)
        self._xdo("click", "--repeat", count, "--delay", 80, button); time.sleep(0.3)

    def _target_rect(self, n, item, cell):
        if item is not None:  # list/combo/grid rows via itemRects, TabControl tabs via tabRects
            rects = n.get("itemRects") or n.get("tabRects")
            if rects is None:
                raise NotFound(f"{n.get('type')} exposes no item rectangles (item= unsupported)")
            if not (0 <= item < len(rects)):
                raise NotFound(f"item {item} out of range (0..{len(rects) - 1})")
            return rects[item]
        if cell is not None:
            cr = n.get("cellRects")
            if cr is None:
                raise NotFound(f"{n.get('type')} exposes no cell rectangles (cell= works for WinForms DataGridView and WPF DataGrid)")
            if not (0 <= cell[0] < len(cr) and 0 <= cell[1] < len(cr[cell[0]])):
                raise NotFound(f"cell {cell} out of range")
            return cr[cell[0]][cell[1]]
        # WPF headered items (TreeViewItem, TabItem, Expander) span their whole subtree but only react on the header strip
        return n.get("headerRect") or n.get("vrect") or n["rect"]   # the visible part if the control is partly clipped

    def click(self, sel, button=1, count=1, item=None, cell=None, scroll=True):
        """scroll=True (default): if the element or the item/cell is scrolled out, ask the app to bring it into view first."""
        try:
            n = self.find(sel)
        except NotFound:
            if not scroll: raise
            n = self.scroll_into_view(sel)
        rect = self._target_rect(n, item, cell)
        if not rect and scroll and (item is not None or cell is not None):
            self.scroll_into_view(sel, item=item if item is not None else cell[0]); time.sleep(0.3)
            n = self.find(sel); rect = self._target_rect(n, item, cell)
        if not rect:
            raise NotFound(f"{sel!r}: target is not on screen (scrolled out / not displayed); scroll_into_view did not help")
        self._click_xy(*center(rect), button=button, count=count)

    def hover(self, sel, wait=1.5):
        """Move the mouse over the element (with a tiny jiggle so MouseMove is delivered) and wait, e.g. for a tooltip to appear."""
        n = self.find(sel); x, y = center(self._target_rect(n, None, None))
        self._xdo("mousemove", x, y); time.sleep(0.2); self._xdo("mousemove_relative", 2, 1); time.sleep(0.1); self._xdo("mousemove", x, y)
        time.sleep(wait)

    def tooltip(self, timeout=3.0):
        """Text of the WPF ToolTip currently shown (it is a popup root in the tree), or None. WinForms tooltips are native windows and are not read."""
        t0 = time.time()
        while True:
            for r in self.tree():
                for n in walk(r):
                    if n.get("type") == "ToolTip" and effectively_visible(n):
                        txt = node_text(n)
                        if txt is None:   # rich content: first text found inside
                            txt = next((node_text(c) for c in walk(n) if c is not n and node_text(c)), None)
                        return txt
            if time.time() - t0 >= timeout: return None
            time.sleep(0.3)

    def dblclick(self, sel, **kw): self.click(sel, count=2, **kw)
    def rclick(self, sel, **kw): self.click(sel, button=3, **kw)

    def menu(self, path, timeout=3.0):
        """path like 'ファイル(&F)>終了(&X)'. Works for WinForms ToolStrip menus and WPF menus (items of a closed menu are not visible)."""
        types = ("ToolStripMenuItem", "MenuItem", "ToolStripDropDownButton", "ToolStripSplitButton")
        for seg in path.split(">"):
            t0 = time.time(); rect = None
            while rect is None:
                for r in self.tree():
                    for n in walk(r):
                        if n.get("type") in types and norm(node_text(n)) == norm(seg) and effectively_visible(n) and n["rect"][2] > 1:
                            rect = n.get("vrect") or n["rect"]; break
                    if rect: break
                if rect is None:
                    if time.time() - t0 >= timeout: raise NotFound(f"menu segment {seg!r} not found/visible")
                    time.sleep(0.3)
            self._click_xy(*center(rect)); time.sleep(0.3)

    def chars(self, text):
        """Send `text` to the focused control as WM_CHAR messages from inside the app (what an IME's result string produces)."""
        return self.call("chars", text=text)

    def type_text(self, text, sel=None, clear=False, mode="auto"):
        """Type text into the focused control (or click `sel` first).
        mode="auto"   ASCII is typed as real key events; runs of non-ASCII (e.g. Japanese) are delivered as WM_CHAR messages by the agent
                      (falls back to clipboard paste if the agent cannot find a focused window).
        mode="wmchar" every character is delivered as WM_CHAR by the agent.
        mode="keys"   every character is sent as X11 key events; non-ASCII one by one with a priming Shift (drops characters, flaky).
        mode="paste"  the whole string is pasted through the X clipboard."""
        if sel:
            self.click(sel)
        if clear:
            self.key("ctrl+a"); self.key("BackSpace")
        if mode == "paste":
            self._paste_now(text); return
        if mode == "wmchar":
            self.chars(text); time.sleep(0.2); return
        buf = ""; primed = False; run = ""
        def flush_ascii():
            nonlocal buf
            if buf: self._xdo("type", "--delay", 60, buf); buf = ""
        def flush_run():
            nonlocal run
            if run:
                r = self._raw("chars", text=run)
                if not r.get("ok"):
                    if r.get("code") == "no-focus" and not r.get("sent", 0):
                        self._paste_now(run)
                    elif r.get("code") == "ui-timeout":
                        raise AppNotResponding(r.get("error") or "UI thread not responding")
                    else:
                        raise AgentError(r.get("error") or str(r))
                run = ""
        for ch in text:
            if ord(ch) < 128:
                if mode == "auto": flush_run()
                buf += ch
            elif mode == "auto":
                flush_ascii(); run += ch
            else:  # keys
                flush_ascii()
                if not primed: self._xdo("key", "shift"); time.sleep(0.5); primed = True
                self._xdo("type", ch); time.sleep(0.35)
        flush_ascii(); flush_run()
        time.sleep(0.4)

    def _paste_now(self, text):
        p = subprocess.Popen(["xclip", "-selection", "clipboard", "-i"], stdin=subprocess.PIPE, stdout=DEVNULL, stderr=DEVNULL, env=xenv(), start_new_session=True)
        try: p.communicate(input=text.encode("utf-8"), timeout=5)   # xclip forks into the background once it owns the selection
        except subprocess.TimeoutExpired: pass
        t0 = time.time(); served = False
        while time.time() - t0 < 3:   # wait until the X selection really serves our text
            r = subprocess.run(["xclip", "-selection", "clipboard", "-o"], capture_output=True, env=xenv(), timeout=3)
            if r.stdout.decode("utf-8", "replace") == text: served = True; break
            time.sleep(0.1)
        if not served:   # pasting now would insert whatever was on the clipboard before
            raise TimeoutError("the X clipboard did not serve the requested text within 3s; nothing was pasted")
        self.key("ctrl+v"); time.sleep(0.4)

    def paste(self, text, sel=None):
        if sel: self.click(sel)
        self._paste_now(text)

    def key(self, *keys):
        for k in keys:
            self._xdo("key", k); time.sleep(0.3)

    # ---- capture
    def shot(self, path, region=None, window=False):
        """region='x,y,w,h' crops; window=True crops to the main top-level window (raises NotFound if there is none)."""
        if window and not region:
            ws = [w for w in self.windows() if w["class"] != "#32770" and w.get("visible", True) and w["rect"][2] >= 50 and w["rect"][3] >= 30]
            if not ws:
                raise NotFound("no top-level application window found for shot(window=True)")
            w0 = ([w for w in ws if w["text"]] or ws)[0]
            x, y, w, h = w0["rect"]; region = f"{w}x{h}+{max(x, 0)}+{max(y, 0)}"
        elif region and "," in region:
            x, y, w, h = [int(v) for v in region.split(",")]; region = f"{w}x{h}+{x}+{y}"
        cmd = ["import", "-window", "root"] + (["-crop", region, "+repage"] if region else []) + [path]
        r = sh(cmd, env=xenv())
        if r.returncode != 0: raise RuntimeError(r.stderr)
        return path

    def record_start(self, path, fps=10):
        p = subprocess.Popen(["ffmpeg", "-y", "-loglevel", "error", "-f", "x11grab", "-framerate", str(fps), "-video_size", "1280x800",
                              "-i", DISPLAY, "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p", path],
                             stdin=subprocess.PIPE, stdout=DEVNULL, stderr=DEVNULL, start_new_session=True)
        self._rec = p; return p.pid

    def record_stop(self):
        p = getattr(self, "_rec", None)
        if p:
            try: p.stdin.write(b"q"); p.stdin.flush()
            except Exception: p.send_signal(signal.SIGINT)
            try: p.wait(timeout=15)
            except Exception: p.kill()


# ------------------------------------------------------------------ image comparison
def _image_size(path):
    r = sh(["identify", "-format", "%w %h", f"{path}[0]"])
    if r.returncode != 0 or len(r.stdout.split()) != 2:
        raise RuntimeError(f"cannot read image {path}: {r.stderr.strip()}")
    w, h = r.stdout.split(); return int(w), int(h)

def compare(actual, baseline, fuzz="1%", masks=(), diff_out=None):
    """Pixel diff via ImageMagick. masks: iterable of (x,y,w,h) blanked on both images.
    Returns dict(pixels,total,ratio). Images of different size are a mismatch: ratio=1.0, size_mismatch=True (ImageMagick would silently
    compare only the overlapping area)."""
    masks = tuple(tuple(mask) for mask in masks)
    sa, sb = _image_size(actual), _image_size(baseline)
    if sa != sb:
        tot = max(sa[0] * sa[1], sb[0] * sb[1])
        return {"pixels": tot, "total": tot, "ratio": 1.0, "size_mismatch": True, "actual_size": list(sa), "baseline_size": list(sb)}
    with tempfile.TemporaryDirectory(prefix="e2e-compare-") as tmp:
        def prep(src, tag):
            if not masks: return src
            if any(w <= 0 or h <= 0 for _, _, w, h in masks):
                raise RuntimeError("comparison mask width and height must be positive")
            dst = os.path.join(tmp, tag + ".png")
            draw = " ".join(f"rectangle {x},{y} {x+w-1},{y+h-1}" for x, y, w, h in masks)
            r = sh(["convert", src, "-fill", "black", "-draw", draw, dst])
            if r.returncode != 0:
                raise RuntimeError(f"ImageMagick mask failed: {r.stderr.strip()}")
            return dst
        a, b = prep(actual, "a"), prep(baseline, "b")
        total = sa[0] * sa[1]
        r = sh(["compare", "-metric", "AE", "-fuzz", fuzz, a, b, diff_out or os.path.join(tmp, "diff.png")])
        if r.returncode >= 2:
            raise RuntimeError(f"ImageMagick compare failed: {r.stderr.strip()}")
        txt = r.stderr.strip().split()[0] if r.stderr.strip() else ""
        try:
            px = int(float(txt))
        except ValueError:
            raise RuntimeError(f"cannot parse compare output: {r.stderr.strip()!r}")
        return {"pixels": px, "total": total, "ratio": px / total}


# ------------------------------------------------------------------ doctor
def doctor():
    ok = True
    def chk(name, cond, hint=""):
        nonlocal ok
        print(("OK   " if cond else "FAIL ") + name + ("" if cond else f"  -> {hint}")); ok = ok and cond
    chk("wine", os.path.exists(WINE), "run scripts/setup.sh")
    chk("wine prefix", os.path.exists(os.path.join(PREFIX, "system.reg")), "run scripts/setup.sh")
    mono = os.path.join(os.path.dirname(os.path.dirname(WINE)), "share/wine/mono")
    chk("wine-mono (.NET Framework lane)", os.path.isdir(mono) and bool(os.listdir(mono)), "run scripts/setup.sh")
    for t in ("xdotool", "xclip", "import", "compare", "identify", "ffmpeg", "Xvfb", "xdpyinfo"):
        chk(t, shutil.which(t) is not None, "apt-get install (setup.sh)")
    chk("CJK fonts", "Noto Sans CJK JP" in sh(["fc-list"]).stdout, "apt-get install fonts-noto-cjk")
    chk("agent (core)", os.path.exists(os.path.join(AGENT_BIN, "core", "E2EAgent.dll")), "scripts/build_agent.sh")
    chk("agent (net48)", os.path.exists(os.path.join(AGENT_BIN, "net48", "E2ELauncher.exe")), "scripts/build_agent.sh")
    print("INFO .NET SDK:", "present" if os.path.exists(os.path.join(HOME, "dotnet", "dotnet")) else "absent (only needed to build apps from source)")
    print("INFO Xvfb", DISPLAY, "up" if xvfb_up() else "down (started automatically on demand)")
    return ok


# ------------------------------------------------------------------ CLI
def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--visual", action="store_true", help="WPF: use the visual tree (control-template internals) for tree / selectors / clicks")
    sp = ap.add_subparsers(dest="cmd", required=True)
    sp.add_parser("doctor")
    s = sp.add_parser("start"); s.add_argument("exe"); s.add_argument("args", nargs="*"); s.add_argument("--port", type=int, default=47800); s.add_argument("--lane", choices=["core", "framework"]); s.add_argument("--keep-on-failure", action="store_true"); s.add_argument("--no-wait-window", action="store_true", help="do not require a visible window (apps that start hidden)"); s.add_argument("--window-timeout", type=float, default=30)
    t = sp.add_parser("tree"); t.add_argument("--flat", action="store_true"); t.add_argument("--sel")
    sp.add_parser("windows"); sp.add_parser("dialogs"); sp.add_parser("stop"); sp.add_parser("responsive")
    for name in ("click", "dblclick", "rclick"):
        c = sp.add_parser(name); c.add_argument("sel"); c.add_argument("--item", type=int); c.add_argument("--cell", help="row,col (WinForms DataGridView / WPF DataGrid)"); c.add_argument("--no-scroll", action="store_true", help="do not scroll the target into view first")
    c = sp.add_parser("type"); c.add_argument("text"); c.add_argument("--sel"); c.add_argument("--clear", action="store_true"); c.add_argument("--mode", choices=["auto", "wmchar", "keys", "paste"], default="auto")
    c = sp.add_parser("paste"); c.add_argument("text"); c.add_argument("--sel")
    c = sp.add_parser("key"); c.add_argument("keys", nargs="+")
    c = sp.add_parser("menu"); c.add_argument("path")
    c = sp.add_parser("scroll"); c.add_argument("sel"); c.add_argument("--item", type=int)
    c = sp.add_parser("hover"); c.add_argument("sel"); c.add_argument("--wait", type=float, default=1.5)
    sp.add_parser("tooltip")
    c = sp.add_parser("get"); c.add_argument("sel"); c.add_argument("prop", nargs="?", default="text")
    c = sp.add_parser("wait"); c.add_argument("sel"); c.add_argument("--gone", action="store_true"); c.add_argument("--timeout", type=float, default=10)
    c = sp.add_parser("press"); c.add_argument("button"); c.add_argument("--title")
    c = sp.add_parser("shot"); c.add_argument("path"); c.add_argument("--region"); c.add_argument("--window", action="store_true")
    c = sp.add_parser("compare"); c.add_argument("actual"); c.add_argument("baseline"); c.add_argument("--fuzz", default="1%"); c.add_argument("--mask", action="append", default=[], help="x,y,w,h"); c.add_argument("--diff")
    a = ap.parse_args(argv)

    try:
        return _run(a)
    except SessionError as ex:
        print(f"error: {ex}", file=sys.stderr); return 3
    except (ConnectionError, TimeoutError) as ex:
        print(f"error: app not reachable ({ex}). Run `stop`, then `start` again.", file=sys.stderr); return 3
    except NotFound as ex:
        print(f"error: {ex}", file=sys.stderr); return 4
    except AppNotResponding as ex:
        print(f"error: application not responding: {ex}", file=sys.stderr); return 5
    except (AgentError, RuntimeError) as ex:
        print(f"error: {ex}", file=sys.stderr); return 1

def _run(a):
    if a.cmd == "doctor": return 0 if doctor() else 1
    if a.cmd == "start":
        Session.start(a.exe, a.args, port=a.port, lane=a.lane, keep_on_failure=a.keep_on_failure, require_window=not a.no_wait_window, window_timeout=a.window_timeout)
        print(json.dumps({"started": True, "port": a.port, "lane": json.load(open(STATE))["lane"]})); return 0
    if a.cmd == "compare":
        r = compare(a.actual, a.baseline, a.fuzz, [tuple(int(v) for v in m.split(",")) for m in a.mask], a.diff); print(json.dumps(r))
        return 0 if r["pixels"] == 0 and not r.get("size_mismatch") else 1
    if a.cmd == "stop":
        sh([WINESERVER, "-k"], env=wenv())
        try: os.remove(STATE)
        except OSError: pass
        print("stopped"); return 0

    s = Session.attach(); s.visual = a.visual
    if a.cmd == "tree":
        roots = s.tree()
        if a.sel: print(json.dumps(s.find_all(a.sel), ensure_ascii=False, indent=1)); return 0
        if a.flat:
            for r in roots:
                for n in walk(r):
                    if n.get("rect") is not None or n.get("type"):
                        extra = {k: n[k] for k in ("SelectedItem", "SelectedIndex", "Checked", "IsChecked", "rows", "Items", "enabled", "visible", "onScreen", "truncated") if k in n}
                        print(f"{n.get('type')}\tname={n.get('name') or n.get('automationId') or ''}\ttext={node_text(n) or ''}\trect={n.get('rect')}\t{json.dumps(extra, ensure_ascii=False) if extra else ''}")
        else:
            print(json.dumps(roots, ensure_ascii=False, indent=1))
    elif a.cmd == "windows": print(json.dumps(s.windows(), ensure_ascii=False, indent=1))
    elif a.cmd == "dialogs": print(json.dumps(s.dialogs(), ensure_ascii=False, indent=1))
    elif a.cmd == "responsive":
        ok = s.responsive(3.0); print("responsive" if ok else "not responding"); return 0 if ok else 5
    elif a.cmd in ("click", "dblclick", "rclick"):
        cell = tuple(int(v) for v in a.cell.split(",")) if a.cell else None
        {"click": s.click, "dblclick": s.dblclick, "rclick": s.rclick}[a.cmd](a.sel, item=a.item, cell=cell, scroll=not a.no_scroll)
    elif a.cmd == "type": s.type_text(a.text, sel=a.sel, clear=a.clear, mode=a.mode)
    elif a.cmd == "paste": s.paste(a.text, sel=a.sel)
    elif a.cmd == "key": s.key(*a.keys)
    elif a.cmd == "menu": s.menu(a.path)
    elif a.cmd == "scroll": s.scroll_into_view(a.sel, item=a.item); print("ok")
    elif a.cmd == "hover": s.hover(a.sel, a.wait)
    elif a.cmd == "tooltip":
        t = s.tooltip(); print(json.dumps(t, ensure_ascii=False)); return 0 if t is not None else 4
    elif a.cmd == "get": print(json.dumps(s.get(a.sel, a.prop), ensure_ascii=False))
    elif a.cmd == "wait": s.wait(a.sel, a.timeout, a.gone); print("ok")
    elif a.cmd == "press": s.press_dialog(a.button, a.title)
    elif a.cmd == "shot": print(s.shot(a.path, a.region, a.window))
    return 0

if __name__ == "__main__":
    sys.exit(main())
