using System.Drawing;
using System.Windows.Forms;
ApplicationConfiguration.Initialize();
Application.Run(new F());

class F : Form {
    ListBox lb = new(){Name="lstLong", Left=10, Top=10, Width=180, Height=120};
    DataGridView dg = new(){Name="grid", Left=200, Top=10, Width=260, Height=120, AllowUserToAddRows=false};
    Panel pn = new(){Name="pn", Left=10, Top=150, Width=200, Height=120, AutoScroll=true, BorderStyle=BorderStyle.FixedSingle};
    Button deep = new(){Name="btnDeep", Text="deep", Left=10, Top=900, Width=100};
    Label st = new(){Name="lblStatus", Left=220, Top=150, Width=240, Text="-"};
    public F(){
        Text="Scroll E2E Sample"; Name="F"; ClientSize=new Size(480,290);
        for (int i = 0; i < 200; i++) lb.Items.Add("item" + i);
        dg.Columns.Add("c1","項目"); dg.Columns.Add("c2","値");
        for (int i = 0; i < 200; i++) dg.Rows.Add("row" + i, i.ToString());
        pn.Controls.Add(deep);
        Controls.AddRange(new Control[]{lb, dg, pn, st});
        lb.SelectedIndexChanged += (s,e)=> st.Text = "lb:" + lb.SelectedItem;
        deep.Click += (s,e)=> st.Text = "deep clicked";
        dg.CellClick += (s,e)=> { if (e.RowIndex >= 0) st.Text = $"cell:{e.RowIndex},{e.ColumnIndex}"; };
    }
}
