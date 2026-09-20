using System; using System.Configuration; using System.Drawing; using System.Reflection; using System.Windows.Forms; using System.Linq;
static class Program { [STAThread] static void Main() { Application.EnableVisualStyles(); Application.SetCompatibleTextRenderingDefault(false); Application.Run(new MainForm()); } }
class MainForm : Form {
    TextBox tb = new(){Name="txtName", Left=20, Top=50, Width=200};
    Button btn = new(){Name="btnGreet", Text="挨拶", Left=230, Top=48, Width=80};
    Label lbl = new(){Name="lblResult", Left=20, Top=90, Width=300, Text="(未実行)"};
    ComboBox cb = new(){Name="cmbMode", Left=20, Top=120, Width=200, DropDownStyle=ComboBoxStyle.DropDownList};
    CheckBox chk = new(){Name="chkUpper", Text="大文字化", Left=230, Top=122};
    DataGridView dg = new(){Name="grid", Left=20, Top=160, Width=380, Height=120, AllowUserToAddRows=false};
    public MainForm(){
        Text="WinForms E2E Sample"; ClientSize=new Size(420,330); Name="MainForm";
        cb.Items.AddRange(new object[]{"通常","丁寧","カジュアル"}); cb.SelectedIndex=0;
        dg.Columns.Add("c1","項目"); dg.Columns.Add("c2","値");
        dg.Rows.Add("A","1"); dg.Rows.Add("B","2");
        var ms = new MenuStrip(); var f = new ToolStripMenuItem("ファイル(&F)"); var ex = new ToolStripMenuItem("終了(&X)"); ex.Click += (s,e)=>Close();
        f.DropDownItems.Add(ex); ms.Items.Add(f); MainMenuStrip=ms; Controls.Add(ms);
        Controls.AddRange(new Control[]{tb,btn,lbl,cb,chk,dg});
        var cms = new ContextMenuStrip(); var reset = new ToolStripMenuItem("リセット(&R)"); reset.Click += (s,e)=> lbl.Text = "(未実行)"; cms.Items.Add(reset); lbl.ContextMenuStrip = cms;
        var info = new Label(){Name="lblInfo", Left=20, Top=300, Width=400, Height=20};
        info.Text = "entry=" + Assembly.GetEntryAssembly().GetName().Name + "|product=" + Application.ProductName + "|cfg=" + ConfigurationManager.AppSettings["k"];
        Controls.Add(info);
        btn.Click += (s,e)=>{
            var t = tb.Text; if (string.IsNullOrWhiteSpace(t)) { MessageBox.Show("名前を入力してください","入力エラー",MessageBoxButtons.OK,MessageBoxIcon.Warning); return; }
            var pre = cb.SelectedItem?.ToString()=="丁寧" ? "はじめまして、" : "こんにちは、";
            var r = pre + t + "さん"; lbl.Text = chk.Checked ? r.ToUpperInvariant() : r;
            dg.Rows.Add(t, lbl.Text.Length.ToString());
        };
    }
}
