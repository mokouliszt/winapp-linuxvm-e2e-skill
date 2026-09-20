using System;
using System.Drawing;
using System.Windows.Forms;
ApplicationConfiguration.Initialize();
Application.Run(new F());

// Common WinForms controls that the other samples do not cover, laid out so nothing overlaps the docked ToolStrip/StatusStrip.
class F : Form {
    Label st = new(){Name="st", Left=10, Top=430, Width=560, Text="-"};
    public F(){
        Text="Coverage E2E Sample"; Name="F"; ClientSize=new Size(580,470);
        var tbMulti = new TextBox{Name="tbMulti", Left=10, Top=40, Width=200, Height=50, Multiline=true, ScrollBars=ScrollBars.Vertical};
        var tbPass  = new TextBox{Name="tbPass", Left=10, Top=100, Width=200, UseSystemPasswordChar=true};
        var mtb     = new MaskedTextBox{Name="mtb", Left=10, Top=130, Width=200, Mask="000-0000"};
        var rtb     = new RichTextBox{Name="rtb", Left=10, Top=160, Width=200, Height=50, Text="rich"};
        var cbEdit  = new ComboBox{Name="cbEdit", Left=10, Top=220, Width=200, DropDownStyle=ComboBoxStyle.DropDown};
        var clb     = new CheckedListBox{Name="clb", Left=10, Top=250, Width=200, Height=60};
        var dtp     = new DateTimePicker{Name="dtp", Left=230, Top=40, Width=200, Format=DateTimePickerFormat.Short, Value=new DateTime(2026,3,4)};
        var trk     = new TrackBar{Name="trk", Left=230, Top=75, Width=200, Minimum=0, Maximum=10, Value=3};
        var pbar    = new ProgressBar{Name="pbar", Left=230, Top=120, Width=200, Value=40};
        var link    = new LinkLabel{Name="link", Left=230, Top=150, Width=200, Text="リンク"};
        var pic     = new PictureBox{Name="pic", Left=230, Top=175, Width=60, Height=40, BorderStyle=BorderStyle.FixedSingle};
        var split   = new SplitContainer{Name="split", Left=230, Top=225, Width=330, Height=85};
        var btnLeft = new Button{Name="btnLeft", Text="L", Width=40};
        split.Panel1.Controls.Add(btnLeft);
        var tlp     = new TableLayoutPanel{Name="tlp", Left=10, Top=320, Width=280, Height=50, ColumnCount=2, RowCount=1};
        var btnCell = new Button{Name="btnCell", Text="cell"};
        tlp.Controls.Add(btnCell, 1, 0);
        var btnModal = new Button{Name="btnModal", Text="modal", Left=300, Top=325, Width=80};
        var btnPB    = new Button{Name="btnPB", Text="+10", Left=390, Top=325, Width=60};
        var ts = new ToolStrip{Name="ts"};
        var tsbSave = new ToolStripButton("Save"){Name="tsbSave"};
        var tsdMore = new ToolStripDropDownButton("More"){Name="tsdMore"};
        var tsmItem1 = new ToolStripMenuItem("Item1"){Name="tsmItem1"};
        tsdMore.DropDownItems.Add(tsmItem1); ts.Items.Add(tsbSave); ts.Items.Add(tsdMore);
        var ss = new StatusStrip{Name="ss"}; ss.Items.Add(new ToolStripStatusLabel("ready"){Name="slMain"});
        Controls.AddRange(new Control[]{tbMulti,tbPass,mtb,rtb,cbEdit,clb,dtp,trk,pbar,link,pic,split,tlp,btnModal,btnPB,st,ts,ss});
        cbEdit.Items.AddRange(new object[]{"one","two"});
        clb.Items.AddRange(new object[]{"c1","c2","c3"});
        tbMulti.TextChanged += (s,e)=> st.Text = "multi:" + tbMulti.Lines.Length;
        mtb.TextChanged += (s,e)=> st.Text = "mtb:" + mtb.Text;
        trk.ValueChanged += (s,e)=> st.Text = "trk:" + trk.Value;
        dtp.ValueChanged += (s,e)=> st.Text = "dtp:" + dtp.Value.ToString("yyyy-MM-dd");
        link.LinkClicked += (s,e)=> st.Text = "link clicked";
        pic.Click += (s,e)=> st.Text = "pic clicked";
        tsbSave.Click += (s,e)=> st.Text = "toolstrip Save";
        tsmItem1.Click += (s,e)=> st.Text = "toolstrip Item1";
        clb.ItemCheck += (s,e)=> st.Text = "clb:" + e.Index + "=" + e.NewValue;
        btnLeft.Click += (s,e)=> st.Text = "split left";
        btnCell.Click += (s,e)=> st.Text = "tlp cell";
        btnPB.Click += (s,e)=> { pbar.Value = Math.Min(100, pbar.Value + 10); st.Text = "pbar:" + pbar.Value; };
        btnModal.Click += (s,e)=> {
            using var d = new Form{Name="childModal", Text="子ダイアログ", ClientSize=new Size(220,100)};
            var ok = new Button{Name="btnChildOk", Text="OK", Left=70, Top=40, Width=80};
            ok.Click += (a,b)=> d.Close(); d.Controls.Add(ok); d.ShowDialog(this); st.Text = "modal closed";
        };
    }
}
