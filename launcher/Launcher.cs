// Tiny launcher for the Background Remover GUI.
// Starts the app with the project's virtual environment and no console window.
using System;
using System.Diagnostics;
using System.IO;
using System.Reflection;
using System.Windows.Forms;

[assembly: AssemblyTitle("Background Remover")]
[assembly: AssemblyProduct("Background Remover")]
[assembly: AssemblyDescription("Launches the Background Remover GUI")]
[assembly: AssemblyVersion("1.0.0.0")]
[assembly: AssemblyFileVersion("1.0.0.0")]

static class Launcher
{
    [STAThread]
    static int Main()
    {
        string root = AppDomain.CurrentDomain.BaseDirectory;
        string python = Path.Combine(root, ".venv", "Scripts", "pythonw.exe");

        if (!Directory.Exists(Path.Combine(root, "bgremover_gui")))
        {
            return Fail("BackgroundRemover.exe must stay in the project folder, next to the \"bgremover_gui\" folder.");
        }
        if (!File.Exists(python))
        {
            return Fail("The Python environment was not found.\n\nRun setup.ps1 in this folder once to create it.");
        }

        try
        {
            var start = new ProcessStartInfo(python, "-m bgremover_gui")
            {
                WorkingDirectory = root,
                UseShellExecute = false,
            };
            Process.Start(start);
            return 0;
        }
        catch (Exception e)
        {
            return Fail("Could not start Background Remover:\n\n" + e.Message);
        }
    }

    static int Fail(string message)
    {
        MessageBox.Show(message, "Background Remover", MessageBoxButtons.OK, MessageBoxIcon.Error);
        return 1;
    }
}
