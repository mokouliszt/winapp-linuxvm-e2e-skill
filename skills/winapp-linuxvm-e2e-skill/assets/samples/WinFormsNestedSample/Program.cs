using System.Drawing; using System.Windows.Forms;
ApplicationConfiguration.Initialize(); Application.Run(new F());
class F : Form {
  Label st = new(){Name="lblStatus", Left=10, Top=290, Width=300, Text="-"};
  public F(){
    Text="Nest"; ClientSize=new Size(420,320);
    var gb = new GroupBox(){Name="gb", Text="Group", Left=10, Top=10, Width=200, Height=100};
    var b1 = new Button(){Name="b1", Text="b1", Left=10, Top=25, Width=80}; b1.Click += (s,e)=>st.Text="b1"; gb.Controls.Add(b1);
    var pn = new Panel(){Name="pn", Left=10, Top=130, Width=200, Height=100, BorderStyle=BorderStyle.Fixed3D, AutoScroll=true};
    var b3 = new Button(){Name="b3", Text="b3", Left=10, Top=10, Width=80}; b3.Click += (s,e)=>st.Text="b3";
    var b2 = new Button(){Name="b2", Text="b2", Left=10, Top=150, Width=80}; b2.Click += (s,e)=>st.Text="b2";
    pn.Controls.AddRange(new Control[]{b3,b2});
    var gb2 = new GroupBox(){Name="gb2", Text="Outer", Left=220, Top=10, Width=190, Height=200};
    var inner = new Panel(){Name="inner", Left=10, Top=30, Width=160, Height=150, BorderStyle=BorderStyle.FixedSingle, Padding=new Padding(8)};
    var b4 = new Button(){Name="b4", Text="b4", Left=20, Top=40, Width=80}; b4.Click += (s,e)=>st.Text="b4"; inner.Controls.Add(b4); gb2.Controls.Add(inner);
    Controls.AddRange(new Control[]{gb,pn,gb2,st});
    Shown += (s,e)=> pn.AutoScrollPosition = new Point(0, 80);   // scroll so b2 becomes visible and b3 is scrolled out
  }
}
