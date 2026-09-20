using System.Windows.Forms;
ApplicationConfiguration.Initialize();

// An app whose only window is registered with WinForms (Application.OpenForms) but never visible, like a tray-style UI.
// (A form that is never shown at all is not in OpenForms, so an agent cannot see it.)
var hidden = new Form { Name = "hiddenForm", Text = "Hidden window", ShowInTaskbar = false };
hidden.Show();
hidden.Hide();
Application.Run(new ApplicationContext());
