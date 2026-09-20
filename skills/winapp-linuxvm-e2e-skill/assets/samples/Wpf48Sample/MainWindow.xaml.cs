using System.Collections.ObjectModel; using System.Windows;
namespace WpfSample {
  public class Row { public string Key {get;set;} = ""; public string Value {get;set;} = ""; }
  public partial class MainWindow : Window {
    ObservableCollection<Row> rows = new();
    public MainWindow(){ InitializeComponent(); rows.Add(new Row{Key="A",Value="1"}); rows.Add(new Row{Key="B",Value="2"}); grid.ItemsSource = rows; }
    void btnGreet_Click(object s, RoutedEventArgs e){
      var t = txtName.Text; if (string.IsNullOrWhiteSpace(t)) { MessageBox.Show("名前を入力してください","入力エラー",MessageBoxButton.OK,MessageBoxImage.Warning); return; }
      var pre = (cmbMode.SelectedItem as System.Windows.Controls.ComboBoxItem)?.Content?.ToString()=="丁寧" ? "はじめまして、" : "こんにちは、";
      var r = pre + t + "さん"; lblResult.Text = chkUpper.IsChecked==true ? r.ToUpperInvariant() : r; rows.Add(new Row{Key=t, Value=lblResult.Text.Length.ToString()});
    }
    void mnuExit_Click(object s, RoutedEventArgs e) => Close();
    void mnuReset_Click(object s, RoutedEventArgs e) => lblResult.Text = "(未実行)";
  }
}
