using System.Drawing;
using System.Windows.Forms;
ApplicationConfiguration.Initialize();
Application.Run(new F());

class F : Form {
    TabControl tc = new(){Name="tabs", Left=10, Top=10, Width=460, Height=300};
    ListBox lb = new(){Name="lstItems", Left=10, Top=10, Width=200, Height=100};
    ListView lv = new(){Name="lvItems", Left=10, Top=120, Width=200, Height=100, View=View.List};
    TreeView tv = new(){Name="tvNodes", Left=230, Top=10, Width=200, Height=200};
    NumericUpDown nud = new(){Name="numQty", Left=10, Top=10, Width=80, Minimum=0, Maximum=100, Value=5};
    RadioButton r1 = new(){Name="rbA", Text="A", Left=10, Top=50, Checked=true};
    RadioButton r2 = new(){Name="rbB", Text="B", Left=70, Top=50};
    Label status = new(){Name="lblStatus", Left=10, Top=320, Width=300, Text=""};
    TextBox txtKeys = new(){Name="txtKeys", Left=10, Top=90, Width=200};
    Label lblKeys = new(){Name="lblKeys", Left=10, Top=120, Width=200, Text="keys:0 chg:0"};
    Button btnFreeze = new(){Name="btnFreeze", Text="凍結テスト", Left=330, Top=316, Width=140};
    int keyCount, chgCount;
    public F(){
        Text="Controls E2E Sample"; Name="F"; ClientSize=new Size(490,350);
        var p1 = new TabPage("一覧"){Name="tabList"}; var p2 = new TabPage("設定"){Name="tabSettings"};
        lb.Items.AddRange(new object[]{"りんご","みかん","ぶどう"});
        lv.Items.AddRange(new[]{new ListViewItem("X1"), new ListViewItem("X2")});
        var root = new TreeNode("ルート"); root.Nodes.Add("子1"); root.Nodes.Add("子2"); tv.Nodes.Add(root); root.Expand();
        p1.Controls.AddRange(new Control[]{lb, lv, tv}); p2.Controls.AddRange(new Control[]{nud, r1, r2, txtKeys, lblKeys});
        tc.TabPages.Add(p1); tc.TabPages.Add(p2); Controls.Add(tc); Controls.Add(status); Controls.Add(btnFreeze);
        lb.SelectedIndexChanged += (s,e)=> status.Text = "lb:" + lb.SelectedItem;
        tv.AfterSelect += (s,e)=> status.Text = "tv:" + tv.SelectedNode?.Text;
        lv.SelectedIndexChanged += (s,e)=> { if (lv.SelectedItems.Count>0) status.Text = "lv:" + lv.SelectedItems[0].Text; };
        tc.SelectedIndexChanged += (s,e)=> status.Text = "tab:" + tc.SelectedIndex;
        nud.ValueChanged += (s,e)=> status.Text = "nud:" + nud.Value;
        txtKeys.KeyPress += (s,e)=> { keyCount++; lblKeys.Text = $"keys:{keyCount} chg:{chgCount}"; };
        txtKeys.TextChanged += (s,e)=> { chgCount++; lblKeys.Text = $"keys:{keyCount} chg:{chgCount}"; };
        btnFreeze.Click += (s,e)=> { status.Text = "freezing"; status.Refresh(); Thread.Sleep(7000); status.Text = "unfrozen"; };
        r2.CheckedChanged += (s,e)=> { if (r2.Checked) status.Text = "rb:B"; };
    }
}
