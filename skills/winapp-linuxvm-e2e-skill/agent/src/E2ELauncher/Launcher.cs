// Runs a .NET Framework target inside its own AppDomain so that E2EAgent can inspect it, while the target still sees itself as the
// entry assembly (Assembly.GetEntryAssembly, Application.ProductName/ExecutablePath, ...) and reads its own <app>.exe.config.
// Staged next to the target: E2ELauncher.exe + E2EAgent.dll (the child domain loads both from the application base).
using System; using System.IO; using System.Linq;

static class Launcher {
  [STAThread]
  static int Main(string[] args) {
    if (args.Length == 0) { Console.Error.WriteLine("Usage: E2ELauncher <target.exe> [args...]"); return 2; }
    string target = Path.GetFullPath(args[0]);
    if (!File.Exists(target)) { Console.Error.WriteLine("target not found: " + target); return 2; }
    var setup = new AppDomainSetup { ApplicationBase = Path.GetDirectoryName(target), ApplicationName = Path.GetFileNameWithoutExtension(target) };
    var cfg = target + ".config"; if (File.Exists(cfg)) setup.ConfigurationFile = cfg;
    var domain = AppDomain.CreateDomain(setup.ApplicationName, null, setup);
    domain.DoCallBack(new CrossAppDomainDelegate(AgentBoot.Start));
    return domain.ExecuteAssembly(target, args.Skip(1).ToArray());
  }
}

static class AgentBoot { public static void Start() { StartupHook.Initialize(); } }
