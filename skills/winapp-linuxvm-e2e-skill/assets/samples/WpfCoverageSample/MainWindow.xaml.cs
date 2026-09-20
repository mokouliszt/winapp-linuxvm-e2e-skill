using System; using System.Collections.ObjectModel; using System.Windows; using System.Windows.Controls;
namespace WpfSample {
  public class LvRow { public string Key {get;set;} = ""; public string Value {get;set;} = ""; }
  public partial class MainWindow : Window {
    public MainWindow(){
      InitializeComponent();
      var rows = new ObservableCollection<LvRow>{ new LvRow{Key="r1", Value="1"}, new LvRow{Key="r2", Value="2"} };
      lv.ItemsSource = rows; cbEdit.Items.Add("one"); cbEdit.Items.Add("two");
    }
    void tbSave_Click(object s, RoutedEventArgs e) => lblStatus.Text = "toolbar Save";
    void tgl_Changed(object s, RoutedEventArgs e) => lblStatus.Text = "toggle:" + (tglBold.IsChecked == true);
    void tabs_Changed(object s, SelectionChangedEventArgs e) { if (lblStatus != null) lblStatus.Text = "tab:" + tabs.SelectedIndex; }
    void tv_Changed(object s, RoutedPropertyChangedEventArgs<object> e) { if (e.NewValue is TreeViewItem i) lblStatus.Text = "tv:" + i.Header; }
    void pwd_Changed(object s, RoutedEventArgs e) => lblStatus.Text = "pwd:" + pwd.Password.Length;
    void multi_Changed(object s, TextChangedEventArgs e) { if (lblStatus != null) lblStatus.Text = "multi:" + tbMulti.LineCount; }
    void dp_Changed(object s, SelectionChangedEventArgs e) => lblStatus.Text = "dp:" + dp.SelectedDate?.ToString("yyyy-MM-dd");
    void sld_Changed(object s, RoutedPropertyChangedEventArgs<double> e) { if (lblStatus != null) lblStatus.Text = "sld:" + (int)sld.Value; }
    void btnPB_Click(object s, RoutedEventArgs e) { pbar.Value = Math.Min(100, pbar.Value + 10); lblStatus.Text = "pbar:" + (int)pbar.Value; }
    void exp_Changed(object s, RoutedEventArgs e) => lblStatus.Text = "exp:" + exp.IsExpanded;
    void lv_Changed(object s, SelectionChangedEventArgs e) { if (lv.SelectedItem is LvRow r) lblStatus.Text = "lv:" + r.Key; }
    void rb_Changed(object s, RoutedEventArgs e) => lblStatus.Text = "rb:B";
    void btnModal_Click(object s, RoutedEventArgs e) {
      var w = new Window{ Name = "childModal", Title = "子ダイアログ", Width = 240, Height = 130, Owner = this, WindowStartupLocation = WindowStartupLocation.CenterOwner };
      var ok = new Button{ Name = "btnChildOk", Content = "OK", Width = 80, Height = 26 };
      ok.Click += (a,b) => w.Close(); w.Content = ok; w.ShowDialog(); lblStatus.Text = "modal closed";
    }
  }
}
