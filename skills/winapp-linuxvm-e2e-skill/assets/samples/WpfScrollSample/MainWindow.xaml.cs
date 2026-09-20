using System.Collections.ObjectModel; using System.Linq; using System.Windows; using System.Windows.Controls;
namespace WpfSample {
  public class Row { public string Key {get;set;} = ""; public string Value {get;set;} = ""; }
  public partial class MainWindow : Window {
    ObservableCollection<Row> rows = new();
    public MainWindow(){
      InitializeComponent();
      for (int i = 0; i < 200; i++) { lstLong.Items.Add("item" + i); rows.Add(new Row{Key="row"+i, Value=i.ToString()}); }
      grid.ItemsSource = rows;
      lstLong.SelectionChanged += (s,e)=> lblStatus.Text = "lb:" + lstLong.SelectedItem;
      grid.SelectedCellsChanged += (s,e)=> { var c = grid.CurrentCell; if (c.IsValid) lblStatus.Text = "cell:" + rows.IndexOf(c.Item as Row) + "," + grid.Columns.IndexOf(c.Column); };
    }
    void btnDeep_Click(object s, RoutedEventArgs e) => lblStatus.Text = "deep clicked";
  }
}
