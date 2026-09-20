// E2EAgent: in-process inspector for WinForms / WPF apps. No UI Automation dependency.
// Loaded via DOTNET_STARTUP_HOOKS (.NET 6+) or by E2ELauncher inside the target's AppDomain (.NET Framework).
// Protocol: line-delimited JSON on 127.0.0.1:$E2E_AGENT_PORT
//   {"cmd":"ping"|"tree"|"windows"|"diag"|"uiping"|"chars", ["text":"...","timeout":ms]}  -> one JSON line.
// Every UI-thread access has a timeout (E2E_UI_TIMEOUT_MS, default 5000): a busy/hung UI yields {"ok":false,"code":"ui-timeout"}.
using System; using System.Collections; using System.Collections.Generic; using System.Globalization; using System.IO;
using System.Linq; using System.Net; using System.Net.Sockets; using System.Runtime.CompilerServices; using System.Runtime.InteropServices;
using System.Text; using System.Text.RegularExpressions; using System.Threading;
using System.Drawing;
using WF = System.Windows.Forms;
using System.Windows; using System.Windows.Controls; using System.Windows.Controls.Primitives; using System.Windows.Interop;
using System.Windows.Media; using System.Windows.Threading;

public class StartupHook {
  // Set E2E_AGENT_LOG=<file> to trace agent startup problems.
  static void Log(string m) {
    try { var p = Environment.GetEnvironmentVariable("E2E_AGENT_LOG"); if (!string.IsNullOrEmpty(p)) File.AppendAllText(p, DateTime.Now.ToString("HH:mm:ss.fff") + " " + m + "\n"); } catch { }
  }

  public static void Initialize() { Log("Initialize (runtime " + Environment.Version + ", domain " + AppDomain.CurrentDomain.FriendlyName + ")"); new Thread(Serve) { IsBackground = true, Name = "e2e-agent" }.Start(); }

  static int EnvInt(string name, int def) { int v; return int.TryParse(Environment.GetEnvironmentVariable(name), out v) && v > 0 ? v : def; }
  static int MaxRows() { return EnvInt("E2E_MAX_ROWS", 200); }

  // The listener is loopback-only and single-tenant: it has no authentication, so anything else running in the same
  // sandbox can drive the app through it. These bounds only stop a stuck or runaway client from wedging the agent.
  static int liveClients;

  static void Serve() {
    try {
      int port = int.Parse(Environment.GetEnvironmentVariable("E2E_AGENT_PORT") ?? "47800");
      int maxClients = EnvInt("E2E_MAX_CLIENTS", 4);
      var l = new TcpListener(IPAddress.Loopback, port); l.Start(1 + maxClients); Log("listening on " + port);
      while (true) {
        var c = l.AcceptTcpClient();
        if (Interlocked.Increment(ref liveClients) > maxClients) {
          Interlocked.Decrement(ref liveClients); Log("refused a connection: " + maxClients + " clients already connected");
          try { c.Close(); } catch { }
          continue;
        }
        new Thread(() => { try { Handle(c); } finally { Interlocked.Decrement(ref liveClients); } }) { IsBackground = true }.Start();
      }
    } catch (Exception e) { Log("Serve failed: " + e); }
  }

  // Reads one request line, bounded in length; returns null at end of stream and throws on an over-long line.
  static string ReadLimited(StreamReader r, int maxChars) {
    var sb = new StringBuilder(); int ch;
    while ((ch = r.Read()) >= 0) {
      if (ch == '\n') return sb.ToString();
      if (ch != '\r') sb.Append((char)ch);
      if (sb.Length > maxChars) throw new InvalidDataException("request line longer than " + maxChars + " characters");
    }
    return sb.Length > 0 ? sb.ToString() : null;
  }

  // ---- request parsing (requests are flat JSON objects written by e2e.py)
  static string StrParam(string line, string key) {
    var m = Regex.Match(line, "\"" + key + "\"\\s*:\\s*\"((?:[^\"\\\\]|\\\\.)*)\"");
    return m.Success ? JsonUnescape(m.Groups[1].Value) : null;
  }
  static int IntParam(string line, string key, int def) {
    var m = Regex.Match(line, "\"" + key + "\"\\s*:\\s*(-?\\d+)"); int v;
    return m.Success && int.TryParse(m.Groups[1].Value, NumberStyles.Integer, CultureInfo.InvariantCulture, out v) ? v : def;
  }
  static string JsonUnescape(string s) {
    var sb = new StringBuilder();
    for (int i = 0; i < s.Length; i++) {
      char c = s[i];
      if (c != '\\' || i == s.Length - 1) { sb.Append(c); continue; }
      char n = s[++i];
      switch (n) {
        case 'n': sb.Append('\n'); break; case 'r': sb.Append('\r'); break; case 't': sb.Append('\t'); break;
        case 'b': sb.Append('\b'); break; case 'f': sb.Append('\f'); break;
        case 'u': if (i + 4 < s.Length) { sb.Append((char)Convert.ToInt32(s.Substring(i + 1, 4), 16)); i += 4; } break;
        default: sb.Append(n); break;
      }
    }
    return sb.ToString();
  }

  sealed class UiTimeoutException : Exception { }

  static void Handle(TcpClient c) {
    int idleMs = EnvInt("E2E_CLIENT_IDLE_MS", 600000);   // drop a client that stops talking (default 10 min)
    int maxLine = EnvInt("E2E_MAX_REQUEST_CHARS", 1 << 20);
    using (c)
    using (var s = c.GetStream())
    using (var r = new StreamReader(s, new UTF8Encoding(false)))
    using (var w = new StreamWriter(s, new UTF8Encoding(false)) { AutoFlush = true, NewLine = "\n" }) {
      s.ReadTimeout = idleMs;
      string line;
      while (true) {
        try { line = ReadLimited(r, maxLine); }
        catch (Exception e) { Log("dropping client: " + e.Message); break; }
        if (line == null) break;
        if (line.Trim().Length == 0) continue;
        object res;
        try {
          var cmd = Regex.Match(line, "\"cmd\"\\s*:\\s*\"([^\"]+)\"").Groups[1].Value;
          int ms = IntParam(line, "timeout", EnvInt("E2E_UI_TIMEOUT_MS", 5000));
          var d = new Dictionary<string, object>();
          switch (cmd) {
            case "ping": d["ok"] = true; d["fw"] = Framework(); break;
            case "tree": d["ok"] = true; d["fw"] = Framework(); d["roots"] = Tree(ms, IntParam(line, "visual", 0) != 0); break;
            case "windows": d["ok"] = true; d["windows"] = Native.Windows(); break;
            case "diag": d["ok"] = true; d["diag"] = Diag(); break;
            case "uiping": d["ok"] = true; d["uiMs"] = UiPing(ms); break;
            case "chars": foreach (var kv in Native.SendChars(StrParam(line, "text") ?? "", ms)) d[kv.Key] = kv.Value; break;
            case "scrollinto": foreach (var kv in ScrollInto(StrParam(line, "name"), StrParam(line, "automationId"), StrParam(line, "text"), StrParam(line, "type"), IntParam(line, "index", -1), ms)) d[kv.Key] = kv.Value; break;
            default: d["ok"] = false; d["error"] = "unknown cmd"; break;
          }
          res = d;
        } catch (UiTimeoutException) {
          res = new Dictionary<string, object> { ["ok"] = false, ["code"] = "ui-timeout", ["error"] = "UI thread did not respond in time (application busy or hung)" };
        } catch (Exception e) { res = new Dictionary<string, object> { ["ok"] = false, ["error"] = e.GetType().Name + ": " + e.Message }; }
        w.WriteLine(MiniJson.Write(res));
      }
    }
  }

  // NOTE: WinForms-only self-contained apps on .NET 9/10 do not ship PresentationFramework (and vice versa may lack WinForms).
  // Every method that touches one UI stack lives in its own NoInlining method so the JIT never needs the other stack's assemblies.
  static bool Loaded(string name) { return AppDomain.CurrentDomain.GetAssemblies().Any(a => a.GetName().Name == name); }

  [MethodImpl(MethodImplOptions.NoInlining)]
  static List<WF.Form> SnapshotForms() {   // OpenForms is not thread-safe: snapshot with retries
    for (int i = 0; i < 5; i++) {
      try { return WF.Application.OpenForms.Cast<WF.Form>().ToList(); }
      catch (InvalidOperationException) { Thread.Sleep(10); }
      catch (ArgumentException) { Thread.Sleep(10); }
    }
    return new List<WF.Form>();
  }
  [MethodImpl(MethodImplOptions.NoInlining)] static int WfCount() { return SnapshotForms().Count; }
  [MethodImpl(MethodImplOptions.NoInlining)] static bool WpfPresent() { return System.Windows.Application.Current != null; }

  static string Framework() {
    if (Loaded("System.Windows.Forms") && WfCount() > 0) return "winforms";
    if (Loaded("PresentationFramework") && WpfPresent()) return "wpf";
    return "none";
  }

  static object Diag() {
    var d = new Dictionary<string, object>();
    d["runtime"] = Environment.Version.ToString(); d["framework"] = Framework(); d["domain"] = AppDomain.CurrentDomain.FriendlyName;
    var ea = System.Reflection.Assembly.GetEntryAssembly(); d["entryAssembly"] = ea == null ? null : ea.GetName().Name;
    d["assemblies"] = AppDomain.CurrentDomain.GetAssemblies().Where(a => a.GetName().Name.StartsWith("System.Windows.Forms") || a.GetName().Name.StartsWith("PresentationFramework")).Select(a => a.GetName().Name + " " + a.GetName().Version).ToList();
    return d;
  }

  static object Tree(int ms, bool visual) {
    var fw = Framework();
    if (fw == "winforms") return WfTree(ms);            // WinForms child controls are always the full control tree
    if (fw == "wpf") return WpfTree(ms, visual);
    return new List<object>();
  }

  // Scrolls the first matching control into view (WinForms ScrollControlIntoView / WPF BringIntoView), so the driver can click it afterwards.
  static Dictionary<string, object> ScrollInto(string name, string autoId, string text, string type, int index, int ms) {
    var fw = Framework();
    if (fw == "winforms") return WfScrollInto(name, autoId, text, type, index, ms);
    if (fw == "wpf") return WpfScrollInto(name, autoId, text, type, index, ms);
    return new Dictionary<string, object> { ["ok"] = false, ["error"] = "no UI" };
  }

  static bool Hit(string nodeName, string nodeAutoId, string nodeText, string nodeType, string name, string autoId, string text, string type) {
    if (name != null && nodeName != name) return false;
    if (autoId != null && nodeAutoId != autoId) return false;
    if (type != null && nodeType != type) return false;
    if (text != null && StripMnemonic(nodeText) != StripMnemonic(text)) return false;
    return name != null || autoId != null || text != null || type != null;
  }
  static string StripMnemonic(string s) { return s == null ? null : s.Replace("&", "").Replace("_", ""); }

  [MethodImpl(MethodImplOptions.NoInlining)]
  static Dictionary<string, object> WfScrollInto(string name, string autoId, string text, string type, int index, int ms) {
    var res = new Dictionary<string, object>();
    foreach (var f in SnapshotForms()) {
      try {
        if (!f.IsHandleCreated || f.IsDisposed) continue;
        var form = f;
        var done = (bool)WfInvoke(form, () => {
          // WinForms has no AutomationId in the agent schema: id= is an alias for Name, as it is in driver-side selectors.
          var hit = WfWalk(form).FirstOrDefault(c => Hit(c.Name, c.Name, c.Text, c.GetType().Name, name, autoId, text, type));
          if (hit == null) return false;
          for (var par = hit.Parent; par != null; par = par.Parent) {
            var sc = par as WF.ScrollableControl;
            if (sc != null && sc.AutoScroll) sc.ScrollControlIntoView(hit);
          }
          if (index >= 0) {   // list item: make that item visible
            var lb = hit as WF.ListBox; if (lb != null && index < lb.Items.Count) lb.TopIndex = Math.Max(0, Math.Min(index, lb.Items.Count - 1));
            var lv = hit as WF.ListView; if (lv != null && index < lv.Items.Count) lv.EnsureVisible(index);
            var g = hit as WF.DataGridView; if (g != null && index < g.Rows.Count) g.FirstDisplayedScrollingRowIndex = index;
          }
          return true;
        }, ms);
        if (done) { res["ok"] = true; return res; }
      } catch (ObjectDisposedException) { } catch (InvalidOperationException) { }
    }
    res["ok"] = false; res["code"] = "not-found"; res["error"] = "no control matched"; return res;
  }

  static IEnumerable<WF.Control> WfWalk(WF.Control c) {
    yield return c;
    foreach (WF.Control k in c.Controls) foreach (var x in WfWalk(k)) yield return x;
  }

  [MethodImpl(MethodImplOptions.NoInlining)]
  static Dictionary<string, object> WpfScrollInto(string name, string autoId, string text, string type, int index, int ms) {
    var r = (Dictionary<string, object>)WpfInvoke(() => {
      var res = new Dictionary<string, object>();
      foreach (Window win in System.Windows.Application.Current.Windows.Cast<Window>().ToArray()) {
        foreach (var fe in WpfWalk(win)) {
          var cc0 = fe as ContentControl;
          var t = cc0 != null && cc0.Content != null ? cc0.Content.ToString() : (fe is TextBlock ? ((TextBlock)fe).Text : null);
          var id = System.Windows.Automation.AutomationProperties.GetAutomationId(fe);
          if (!Hit(fe.Name, id, t, fe.GetType().Name, name, autoId, text, type)) continue;
          var ic = fe as ItemsControl;
          if (index >= 0 && ic != null && index < ic.Items.Count) {
            var sv = ic as ListBox; if (sv != null) sv.ScrollIntoView(ic.Items[index]);
            var dg2 = ic as DataGrid; if (dg2 != null) dg2.ScrollIntoView(ic.Items[index]);
            var cont = ic.ItemContainerGenerator.ContainerFromIndex(index) as FrameworkElement; if (cont != null) cont.BringIntoView();
          } else fe.BringIntoView();
          res["ok"] = true; return res;
        }
      }
      res["ok"] = false; res["code"] = "not-found"; res["error"] = "no element matched"; return res;
    }, ms);
    return r;
  }

  static IEnumerable<FrameworkElement> WpfWalk(DependencyObject o) {
    var fe = o as FrameworkElement; if (fe != null) yield return fe;
    foreach (var k in LogicalTreeHelper.GetChildren(o)) { var dk = k as DependencyObject; if (dk == null) continue; foreach (var x in WpfWalk(dk)) yield return x; }
  }

  static int UiPing(int ms) {
    var sw = System.Diagnostics.Stopwatch.StartNew(); var fw = Framework();
    if (fw == "winforms") WfPing(ms); else if (fw == "wpf") WpfPing(ms); else throw new InvalidOperationException("no UI yet");
    return (int)sw.ElapsedMilliseconds;
  }

  // ---------------- WinForms ----------------
  [MethodImpl(MethodImplOptions.NoInlining)]
  static object WfInvoke(WF.Control c, Func<object> fn, int ms) {
    object res = null; Exception err = null; int cancelled = 0;
    var ar = c.BeginInvoke(new Action(() => {
      if (Interlocked.CompareExchange(ref cancelled, 0, 0) != 0) return;
      try { res = fn(); } catch (Exception e) { err = e; }
    }));
    var wh = ar.AsyncWaitHandle;
    if (!wh.WaitOne(ms)) { Interlocked.Exchange(ref cancelled, 1); throw new UiTimeoutException(); }
    wh.Close();
    if (err != null) throw err;
    return res;
  }

  [MethodImpl(MethodImplOptions.NoInlining)]
  static void WfPing(int ms) {
    var f = SnapshotForms().FirstOrDefault(x => x.IsHandleCreated && !x.IsDisposed);
    if (f == null) throw new InvalidOperationException("no window yet");
    WfInvoke(f, () => null, ms);
  }

  [MethodImpl(MethodImplOptions.NoInlining)]
  static object WfTree(int ms) {
    var list = new List<object>();
    foreach (var f in SnapshotForms()) {
      // best effort: a form can be closed/disposed between the check and the call, and one dying form must not fail the whole tree
      try {
        if (!f.IsHandleCreated || f.IsDisposed) continue;   // forms without a handle have no UI yet
        var form = f; list.Add(WfInvoke(form, () => WfNode(form, true, null), ms));
      } catch (ObjectDisposedException) { } catch (InvalidOperationException) { }
    }
    return list;
  }

  static readonly string[] Props = { "Text", "Content", "Header", "Title", "IsChecked", "Checked", "SelectedIndex", "Value", "Minimum", "Maximum", "ReadOnly", "IsReadOnly", "IsSelected", "IsExpanded" };
  static int[] R(Rectangle r) { return new[] { r.X, r.Y, r.Width, r.Height }; }
  static object ClipR(Rectangle screenRect, Rectangle vis) { var x = Rectangle.Intersect(screenRect, vis); return x.Width > 0 && x.Height > 0 ? (object)R(x) : null; }

  static void Extra(object o, Dictionary<string, object> d) {
    foreach (var p in Props) {
      var pi = o.GetType().GetProperty(p); if (pi == null || pi.GetIndexParameters().Length > 0) continue;
      try {
        var v = pi.GetValue(o, null); if (v == null) continue;
        if (v is string || v is bool || v is int || v is double || v is decimal) d[p] = v;
        else if (v is Enum) d[p] = v.ToString();
        else if (p == "Content" || p == "Header") d[p + "Type"] = v.GetType().Name;   // keep Content/Header string-only so text= matches the header
      } catch { }
    }
  }

  // clip = screen rectangle that ancestors leave visible (scrolled-out / clipped children get onScreen=false).
  static object WfNode(WF.Control c, bool top, Rectangle? clip) {
    var d = new Dictionary<string, object> { ["type"] = c.GetType().Name, ["name"] = c.Name, ["enabled"] = c.Enabled, ["visible"] = c.Visible, ["focused"] = c.Focused };
    Rectangle r = top ? c.Bounds : (c.Parent != null ? c.Parent.RectangleToScreen(c.Bounds) : c.Bounds);
    d["rect"] = R(r);
    Rectangle vis = clip.HasValue ? Rectangle.Intersect(r, clip.Value) : r;
    bool on = vis.Width > 0 && vis.Height > 0;
    d["onScreen"] = on; if (on) d["vrect"] = R(vis);
    Extra(c, d);
    try {
      if (c is WF.ComboBox cb) { d["SelectedItem"] = cb.SelectedItem == null ? null : cb.SelectedItem.ToString(); d["Items"] = cb.Items.Cast<object>().Select(x => x == null ? null : x.ToString()).ToList(); }
      if (c is WF.ListBox lb) {
        d["Items"] = lb.Items.Cast<object>().Select(x => x == null ? null : x.ToString()).ToList(); d["SelectedIndex"] = lb.SelectedIndex;
        var rs = new List<object>(); for (int i = 0; i < lb.Items.Count && i < 500; i++) { var ir = lb.GetItemRectangle(i); rs.Add(on && lb.ClientRectangle.IntersectsWith(ir) ? ClipR(lb.RectangleToScreen(ir), vis) : null); } d["itemRects"] = rs;
      }
      if (c is WF.ListView lv) {
        d["Items"] = lv.Items.Cast<WF.ListViewItem>().Select(x => x.Text).ToList();
        d["itemRects"] = lv.Items.Cast<WF.ListViewItem>().Take(500).Select(x => { var b = x.GetBounds(WF.ItemBoundsPortion.Label); if (b.Width <= 0) b = x.Bounds; return on ? ClipR(lv.RectangleToScreen(b), vis) : null; }).ToList();
      }
      if (c is WF.TreeView tv) d["nodes"] = TvNodes(tv, tv.Nodes, vis, on);
      if (c is WF.TabControl tc) { d["SelectedIndex"] = tc.SelectedIndex; d["tabs"] = tc.TabPages.Cast<WF.TabPage>().Select(t => t.Text).ToList(); d["tabRects"] = Enumerable.Range(0, tc.TabCount).Select(i => on ? ClipR(tc.RectangleToScreen(tc.GetTabRect(i)), vis) : null).ToList(); }
      if (c is WF.DataGridView g) {
        int max = MaxRows();
        var cols = g.Columns.Cast<WF.DataGridViewColumn>().ToList(); d["columns"] = cols.Select(x => x.HeaderText).ToList();
        var rows = g.Rows.Cast<WF.DataGridViewRow>().Where(x => !x.IsNewRow).ToList();
        d["rowCount"] = rows.Count; if (rows.Count > max) d["truncated"] = true;
        d["rows"] = rows.Take(max).Select(x => x.Cells.Cast<WF.DataGridViewCell>().Select(y => y.Value == null ? null : y.Value.ToString()).ToList()).ToList();
        var cr = new List<object>();
        foreach (var row in rows.Take(Math.Min(max, 300))) { var rr = new List<object>(); foreach (var col in cols) { var cell = g.GetCellDisplayRectangle(col.Index, row.Index, false); rr.Add(on && cell.Width > 0 && cell.Height > 0 ? ClipR(g.RectangleToScreen(cell), vis) : null); } cr.Add(rr); }
        d["cellRects"] = cr;
        if (g.CurrentCell != null) d["currentCell"] = new[] { g.CurrentCell.RowIndex, g.CurrentCell.ColumnIndex };
      }
      if (c is WF.ToolStrip ts) d["items"] = ts.Items.Cast<WF.ToolStripItem>().Select(i => TsItem(ts, i)).ToList();
    } catch (Exception e) { d["extraError"] = e.GetType().Name + ": " + e.Message; }
    Rectangle client = c.RectangleToScreen(c.ClientRectangle);
    Rectangle childClip = clip.HasValue ? Rectangle.Intersect(client, clip.Value) : client;
    var kids = new List<object>(); foreach (WF.Control k in c.Controls) kids.Add(WfNode(k, false, childClip));
    var cms = c.ContextMenuStrip; if (cms != null && cms.Visible) kids.Add(WfNode(cms, true, null));   // an open context menu
    d["children"] = kids; return d;
  }

  static object TvNodes(WF.TreeView tv, WF.TreeNodeCollection nodes, Rectangle vis, bool on) {
    var l = new List<object>();
    foreach (WF.TreeNode n in nodes) {
      var d = new Dictionary<string, object> { ["text"] = n.Text, ["expanded"] = n.IsExpanded, ["selected"] = n.IsSelected };
      d["rect"] = on && n.IsVisible ? ClipR(tv.RectangleToScreen(n.Bounds), vis) : null;
      d["nodes"] = TvNodes(tv, n.Nodes, vis, on); l.Add(d);
    }
    return l;
  }

  // Items of a closed drop-down report visible=false (their rectangles are meaningless until the menu is open).
  static object TsItem(WF.ToolStrip owner, WF.ToolStripItem i) {
    var r = owner.RectangleToScreen(i.Bounds);
    var d = new Dictionary<string, object> { ["type"] = i.GetType().Name, ["name"] = i.Name, ["text"] = i.Text, ["enabled"] = i.Enabled, ["visible"] = owner.Visible && i.Available, ["rect"] = R(r) };
    var ci = i as WF.ToolStripMenuItem; if (ci != null) d["checked"] = ci.Checked;
    var dd = i as WF.ToolStripDropDownItem; if (dd != null) d["items"] = dd.DropDownItems.Cast<WF.ToolStripItem>().Select(x => TsItem(dd.DropDown, x)).ToList();
    return d;
  }

  // ---------------- WPF ----------------
  [MethodImpl(MethodImplOptions.NoInlining)]
  static object WpfInvoke(Func<object> fn, int ms) {
    object res = null; Exception err = null;
    var op = System.Windows.Application.Current.Dispatcher.BeginInvoke(new Action(() => { try { res = fn(); } catch (Exception e) { err = e; } }));
    var st = op.Wait(TimeSpan.FromMilliseconds(ms));
    if (st != DispatcherOperationStatus.Completed) { try { op.Abort(); } catch { } throw new UiTimeoutException(); }
    if (err != null) throw err;
    return res;
  }

  [MethodImpl(MethodImplOptions.NoInlining)] static void WpfPing(int ms) { WpfInvoke(() => null, ms); }

  [MethodImpl(MethodImplOptions.NoInlining)]
  static object WpfTree(int ms, bool visual) {
    return WpfInvoke(() => {
      nodeBudget = EnvInt("E2E_MAX_NODES", 20000);
      var l = new List<object>(); var app = System.Windows.Application.Current;
      // visual=true walks the visual tree, i.e. also control-template internals (ContentPresenter, Border, scroll bars, ...)
      foreach (Window win in app.Windows.Cast<Window>().ToArray()) {
        try { l.Add(WpfNode(win, null, visual)); } catch (ObjectDisposedException) { } catch (InvalidOperationException) { }
      }
      // popups (ContextMenu, open sub-menus, drop-downs, tooltips) live in their own HwndSource, outside the window's logical tree
      foreach (var ps in PresentationSource.CurrentSources.OfType<PresentationSource>().ToArray()) {   // snapshot: a popup may close while we walk
        try {
          var hs = ps as HwndSource; if (hs == null || hs.IsDisposed) continue;
          var root = hs.RootVisual as FrameworkElement; if (root == null || root is Window) continue;
          l.Add(WpfNode(root, null, true));
        } catch (ObjectDisposedException) { } catch (InvalidOperationException) { }
      }
      return l;
    }, ms);
  }

  static int[] RectOf(FrameworkElement fe) {
    var src = PresentationSource.FromVisual(fe); if (src == null) return null;
    var s = VisualTreeHelper.GetDpi(fe).PixelsPerDip; var p = fe.PointToScreen(new System.Windows.Point(0, 0));
    return new[] { (int)p.X, (int)p.Y, (int)(fe.ActualWidth * s), (int)(fe.ActualHeight * s) };
  }

  static int[] Inter(int[] a, int[] b) {
    if (a == null) return b; if (b == null) return a;
    int x1 = Math.Max(a[0], b[0]), y1 = Math.Max(a[1], b[1]), x2 = Math.Min(a[0] + a[2], b[0] + b[2]), y2 = Math.Min(a[1] + a[3], b[1] + b[3]);
    return x2 > x1 && y2 > y1 ? new[] { x1, y1, x2 - x1, y2 - y1 } : new[] { 0, 0, 0, 0 };
  }
  static bool NonEmpty(int[] r) { return r != null && r[2] > 0 && r[3] > 0; }

  static int nodeBudget;   // UI-thread only; protects the agent from huge visual trees (E2E_MAX_NODES)

  static T FindAncestor<T>(DependencyObject o) where T : class {
    while (o != null) { var t = o as T; if (t != null) return t; o = VisualTreeHelper.GetParent(o); }
    return null;
  }

  // visual=true walks the visual tree (popup roots; template internals on request); otherwise the logical tree.
  static object WpfNode(DependencyObject o, int[] clip, bool visual) {
    var d = new Dictionary<string, object> { ["type"] = o.GetType().Name };
    if (--nodeBudget < 0) { d["truncated"] = true; return d; }
    var fe = o as FrameworkElement; int[] childClip = clip; int[] vis = null;
    if (fe != null) {
      d["name"] = fe.Name; d["automationId"] = System.Windows.Automation.AutomationProperties.GetAutomationId(fe);
      d["enabled"] = fe.IsEnabled; d["visible"] = fe.IsVisible; d["focused"] = fe.IsKeyboardFocused;
      int[] rect = null; try { rect = RectOf(fe); } catch { }
      d["rect"] = rect;
      vis = rect == null ? null : Inter(rect, clip);
      bool on = NonEmpty(vis); d["onScreen"] = on; if (on) d["vrect"] = vis;
      if (rect != null && (fe is ScrollViewer || fe is ScrollContentPresenter || fe.ClipToBounds)) childClip = Inter(clip, rect);
    }
    Extra(o, d);
    try {
      if (o is HeaderedItemsControl || o is HeaderedContentControl) {
        var hdr = HeaderPart(o);   // PART_Header / ContentSite / HeaderSite in the default templates
        if (hdr != null) { var hr = RectOf(hdr); if (hr != null) { hr = Inter(hr, vis); if (NonEmpty(hr)) d["headerRect"] = hr; } }
      }
      var sel = o as Selector;
      if (sel != null) { d["SelectedIndex"] = sel.SelectedIndex; var cc = sel.SelectedItem as ContentControl; d["SelectedItem"] = cc != null ? (cc.Content == null ? null : cc.Content.ToString()) : (sel.SelectedItem == null ? null : sel.SelectedItem.ToString()); }
      var dg = o as DataGrid;
      if (dg != null) {
        int max = MaxRows();
        var items = dg.Items.Cast<object>().Where(it => !object.ReferenceEquals(it, System.Windows.Data.CollectionView.NewItemPlaceholder)).ToList();
        d["columns"] = dg.Columns.Select(x => x.Header == null ? null : x.Header.ToString()).ToList();
        d["rowCount"] = items.Count; if (items.Count > max) d["truncated"] = true;
        d["rows"] = items.Take(max).Select(it => it.GetType().GetProperties().Where(p => p.GetIndexParameters().Length == 0).Select(p => { var v = p.GetValue(it, null); return v == null ? null : v.ToString(); }).ToList()).ToList();
        // cell rectangles [row][column] for realized, on-screen cells (same indexing as WinForms DataGridView)
        var cr = new List<object>();
        foreach (var it in items.Take(Math.Min(max, 300))) {
          var rr = new List<object>(); var row = dg.ItemContainerGenerator.ContainerFromItem(it) as DataGridRow;
          foreach (var col in dg.Columns) {
            int[] rc = null;
            if (row != null && row.IsVisible) {
              var content = col.GetCellContent(row);
              if (content != null) {
                var cellEl = FindAncestor<DataGridCell>(content) as FrameworkElement ?? content;
                var r0 = RectOf(cellEl); if (r0 != null) { rc = Inter(r0, vis); if (!NonEmpty(rc)) rc = null; }
              }
            }
            rr.Add(rc);
          }
          cr.Add(rr);
        }
        d["cellRects"] = cr;
        var cur = dg.CurrentCell;
        if (cur.IsValid) { int ri = items.IndexOf(cur.Item), ci = dg.Columns.IndexOf(cur.Column); if (ri >= 0 && ci >= 0) d["currentCell"] = new[] { ri, ci }; }
      }
      var ic = o as ItemsControl;
      if (ic != null) {
        var rs = new List<object>();
        for (int i = 0; i < ic.Items.Count && i < 500; i++) {
          var cont = ic.ItemContainerGenerator.ContainerFromIndex(i) as FrameworkElement; int[] ir = null;
          if (cont != null && cont.IsVisible) { var cr = RectOf(cont); if (cr != null) { ir = Inter(cr, vis); if (!NonEmpty(ir)) ir = null; } }
          rs.Add(ir);
        }
        d["itemRects"] = rs;
      }
    } catch (Exception e) { d["extraError"] = e.GetType().Name + ": " + e.Message; }
    var kids = new List<object>();
    if (!visual) {
      foreach (var k in LogicalTreeHelper.GetChildren(o)) { if (nodeBudget < 0) break; var dk = k as DependencyObject; if (dk != null) kids.Add(WpfNode(dk, childClip, false)); }
    } else VisualKids(o, childClip, kids);
    d["children"] = kids; return d;
  }

  static readonly string[] HeaderPartNames = { "PART_Header", "ContentSite", "HeaderSite" };

  static FrameworkElement HeaderPart(DependencyObject o) {
    int n = VisualTreeHelper.GetChildrenCount(o);
    for (int i = 0; i < n; i++) {
      var ch = VisualTreeHelper.GetChild(o, i);
      var fe = ch as FrameworkElement;
      if (fe != null && Array.IndexOf(HeaderPartNames, fe.Name) >= 0) return fe;
      if (ch is HeaderedItemsControl || ch is HeaderedContentControl) continue;   // do not descend into nested items
      var deep = HeaderPart(ch); if (deep != null) return deep;
    }
    return null;
  }

  static void VisualKids(DependencyObject o, int[] clip, List<object> into) {
    int n = VisualTreeHelper.GetChildrenCount(o);
    for (int i = 0; i < n && nodeBudget >= 0; i++) {
      var ch = VisualTreeHelper.GetChild(o, i);
      if (ch is FrameworkElement) into.Add(WpfNode(ch, clip, true)); else VisualKids(ch, clip, into);
    }
  }
}

// ---------------- Native (MessageBox, common dialogs, focus, WM_CHAR) ----------------
static class Native {
  delegate bool EnumProc(IntPtr h, IntPtr l);
  [DllImport("user32")] static extern bool EnumWindows(EnumProc p, IntPtr l);
  [DllImport("user32")] static extern bool EnumChildWindows(IntPtr h, EnumProc p, IntPtr l);
  [DllImport("user32")] static extern uint GetWindowThreadProcessId(IntPtr h, out uint pid);
  [DllImport("user32", CharSet = CharSet.Unicode)] static extern int GetClassName(IntPtr h, StringBuilder sb, int n);
  [DllImport("user32", CharSet = CharSet.Unicode)] static extern int GetWindowText(IntPtr h, StringBuilder sb, int n);
  [DllImport("user32")] static extern bool IsWindowVisible(IntPtr h);
  [DllImport("user32")] static extern bool IsWindowEnabled(IntPtr h);
  [DllImport("user32")] static extern bool GetWindowRect(IntPtr h, out RECT r);
  [DllImport("user32")] static extern bool GetGUIThreadInfo(uint idThread, ref GUITHREADINFO info);
  // CharSet.Unicode => SendMessageTimeoutW. The default (ANSI) entry point would truncate WM_CHAR's wParam to one byte.
  [DllImport("user32", CharSet = CharSet.Unicode, SetLastError = true)] static extern IntPtr SendMessageTimeout(IntPtr h, uint msg, IntPtr wParam, IntPtr lParam, uint flags, uint timeout, out IntPtr result);
  [StructLayout(LayoutKind.Sequential)] struct RECT { public int L, T, R, B; }
  [StructLayout(LayoutKind.Sequential)] struct GUITHREADINFO { public int cbSize, flags; public IntPtr hwndActive, hwndFocus, hwndCapture, hwndMenuOwner, hwndMoveSize, hwndCaret; public RECT rcCaret; }
  const uint WM_CHAR = 0x0102, SMTO_ABORTIFHUNG = 0x0002;

  static uint Me() { return (uint)System.Diagnostics.Process.GetCurrentProcess().Id; }

  static Dictionary<string, object> One(IntPtr h) {
    var cn = new StringBuilder(256); var tx = new StringBuilder(2048); GetClassName(h, cn, 256); GetWindowText(h, tx, 2048); RECT r; GetWindowRect(h, out r);
    return new Dictionary<string, object> { ["hwnd"] = h.ToInt64(), ["class"] = cn.ToString(), ["text"] = tx.ToString(), ["visible"] = IsWindowVisible(h), ["enabled"] = IsWindowEnabled(h), ["rect"] = new[] { r.L, r.T, r.R - r.L, r.B - r.T } };
  }

  public static object Windows() {
    var res = new List<object>(); uint me = Me();
    EnumWindows((h, _) => {
      uint pid; GetWindowThreadProcessId(h, out pid);
      if (pid == me && IsWindowVisible(h)) {
        var w = One(h); var kids = new List<object>();
        EnumChildWindows(h, (k, __) => { kids.Add(One(k)); return true; }, IntPtr.Zero);
        w["children"] = kids; res.Add(w);
      }
      return true;
    }, IntPtr.Zero);
    return res;
  }

  // The window that currently has keyboard focus in one of this process's UI threads.
  public static IntPtr FocusedHwnd() {
    var tids = new HashSet<uint>(); uint me = Me();
    EnumWindows((h, _) => { uint pid; uint tid = GetWindowThreadProcessId(h, out pid); if (pid == me) tids.Add(tid); return true; }, IntPtr.Zero);
    foreach (var tid in tids) {
      var i = new GUITHREADINFO(); i.cbSize = Marshal.SizeOf(typeof(GUITHREADINFO));
      if (GetGUIThreadInfo(tid, ref i) && i.hwndFocus != IntPtr.Zero) return i.hwndFocus;
    }
    return IntPtr.Zero;
  }

  // Delivers text exactly like the result string of an IME: one WM_CHAR per UTF-16 unit to the focused window (synchronous, with timeout).
  public static Dictionary<string, object> SendChars(string text, int ms) {
    var res = new Dictionary<string, object>(); var h = FocusedHwnd();
    if (h == IntPtr.Zero) { res["ok"] = false; res["code"] = "no-focus"; res["error"] = "no focused window in this process"; return res; }
    int sent = 0;
    foreach (char ch in text) {
      IntPtr r; var ok = SendMessageTimeout(h, WM_CHAR, (IntPtr)(int)ch, (IntPtr)1, SMTO_ABORTIFHUNG, (uint)ms, out r);
      if (ok == IntPtr.Zero) { res["ok"] = false; res["code"] = "ui-timeout"; res["error"] = "WM_CHAR not processed in time after " + sent + " chars"; res["sent"] = sent; return res; }
      sent++;
    }
    res["ok"] = true; res["sent"] = sent; res["hwnd"] = h.ToInt64(); return res;
  }
}

static class MiniJson {
  public static string Write(object o) { var sb = new StringBuilder(); W(sb, o); return sb.ToString(); }
  static void W(StringBuilder sb, object o) {
    if (o == null) { sb.Append("null"); return; }
    var s = o as string; if (s != null) { Str(sb, s); return; }
    if (o is bool) { sb.Append((bool)o ? "true" : "false"); return; }
    if (o is int || o is long || o is short || o is byte || o is double || o is float || o is decimal) { sb.Append(Convert.ToString(o, CultureInfo.InvariantCulture)); return; }
    if (o is Enum) { Str(sb, o.ToString()); return; }
    var d = o as IDictionary<string, object>;
    if (d != null) { sb.Append('{'); bool first = true; foreach (var kv in d) { if (!first) sb.Append(','); first = false; Str(sb, kv.Key); sb.Append(':'); W(sb, kv.Value); } sb.Append('}'); return; }
    var e = o as IEnumerable;
    if (e != null) { sb.Append('['); bool first = true; foreach (var x in e) { if (!first) sb.Append(','); first = false; W(sb, x); } sb.Append(']'); return; }
    Str(sb, o.ToString());
  }
  static void Str(StringBuilder sb, string s) {
    sb.Append('"');
    foreach (var c in s) {
      switch (c) {
        case '"': sb.Append("\\\""); break;
        case '\\': sb.Append("\\\\"); break;
        case '\n': sb.Append("\\n"); break;
        case '\r': sb.Append("\\r"); break;
        case '\t': sb.Append("\\t"); break;
        default: if (c < 0x20) sb.Append("\\u" + ((int)c).ToString("x4")); else sb.Append(c); break;
      }
    }
    sb.Append('"');
  }
}
