# Fidelity: what a pass here means

The apps run on Wine, not Windows. .NET code runs unchanged (CoreCLR or wine-mono) and receives real Win32 messages from Wine's user32,
so behaviour is close to Windows; rendering and OS-level services are not.

| Aspect | Equivalence | Notes |
|---|---|---|
| Event handling, business logic, data binding, validation, dialog flow, navigation, menus, context menus | **high** | driven by real X11 mouse/keyboard events → Win32 messages |
| Control state (text, checked, selection, rows, enabled/visible/on-screen) | **high** | read in-process by the agent, not by OCR |
| Native dialogs (MessageBox etc.) | **high** | detected by EnumWindows; buttons clicked with real input. Common file dialogs are Wine's own implementation: untested, expect differences |
| Keyboard text entry | **medium–high** | ASCII = real key events. Japanese/non-ASCII = one `WM_CHAR` per character sent by the agent (what an IME result string produces: KeyPress + TextChanged per character). No composition UI, no KeyDown/KeyUp for those characters |
| Process identity (.NET Framework lane) | high | the target runs in its own AppDomain: entry assembly, `Application.ProductName`, `ExecutablePath`, `<app>.exe.config` are the app's own. It runs from a staged copy of its folder |
| Layout / pixels / fonts | **low–medium** | Noto CJK / IPA fonts substitute Segoe UI, Yu Gothic UI, Meiryo, MS UI Gothic (different metrics → wrapping, truncation and auto-size can differ). Wine's default message font is Tahoma 8pt vs Windows' 9pt UI font |
| Theme | **low** | WinForms uses Wine's "light" theme; WPF renders with the Classic look (Aero2 not applied); the .NET Framework lane (wine-mono) uses Mono's WinForms and looks classic/beige |
| DPI / scaling | not covered | fixed 96 dpi, single 1280×800 screen |
| Non-client area | different | drawn by Wine (no window manager) |
| IME conversion UI, COM/ActiveX (vendor OCX), drivers, USB/serial, GPU-specific rendering, Windows services | **not testable** | mock them (loopback TCP/SLMP simulator, fake COM shim) or use a real Windows runner |
| UI Automation clients (FlaUI, WinAppDriver, pywinauto-UIA) | **unusable** | Wine 11.0 and 11.17 implement too little of UIAutomationCore; use the agent |

## How to word results

- "Ran on Wine 11 (Linux). Verified: <flows>, values read from the app: <…>, dialogs seen: <…>. Screenshots attached."
- "Layout was not judged against Windows; font metrics differ under Wine." when visuals matter.
- Regression images are only comparable with baselines produced by this same setup. Blank volatile regions (clocks, caret, animations) with `masks`; an image of a different size is always a mismatch.
- A failure that only shows up in look-and-feel (clipped label, odd theme) → say it may be a Wine artefact and recommend a check on real Windows.
- A failure in behaviour (wrong value, missing dialog, exception dialog, `AppNotResponding`) is a genuine finding: re-run once, keep the screenshot and `app.log`.

## Tighten fidelity when it matters (untested ideas)

Metric-compatible fonts (e.g. Selawik for Segoe UI) and setting Wine's NonClientMetrics to 9pt UI fonts; a real Windows runner (e.g. a hosted Windows CI job)
for the final visual sign-off.
