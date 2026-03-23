using Avalonia.Controls;
using Avalonia.Input;
using Avalonia.Threading;
using System;
using System.Net.Sockets;
using System.Text;
using System.Threading.Tasks;

namespace JarvisUI;

public partial class MainWindow : Window
{
    public MainWindow()
    {
        InitializeComponent();
    }

    private async void OnKeyDown(object sender, KeyEventArgs e)
    {
        if (e.Key == Key.Enter)
        {
            var prompt = UserInput.Text;
            if (string.IsNullOrWhiteSpace(prompt)) return;

            ChatDisplay.Text += $"\n👤 Tú: {prompt}";
            UserInput.Text = "";

            // Comunicación asíncrona
            string respuesta = await Task.Run(() => EnviarAPython(prompt));
            
            ChatDisplay.Text += $"\n💠 JARVIS: {respuesta}";
        }
    }

    private string EnviarAPython(string mensaje)
    {
        try
        {
            // Usamos localhost en Ubuntu
            using var client = new TcpClient("127.0.0.1", 65432);
            var data = Encoding.UTF8.GetBytes(mensaje);
            using var stream = client.GetStream();
            stream.Write(data, 0, data.Length);

            var buffer = new byte[4096];
            int bytesRead = stream.Read(buffer, 0, buffer.Length);
            return Encoding.UTF8.GetString(buffer, 0, bytesRead);
        }
        catch (Exception)
        {
            return "Error: ¿El cerebro de Python está corriendo?";
        }
    }
}