# scripts/appcontainer_run.ps1
# Runs a command inside a Windows AppContainer (Low Privilege Sandbox)

param (
    [Parameter(Mandatory=$true)]
    [string]$CommandLine
)

$code = @"
using System;
using System.Runtime.InteropServices;
using System.Diagnostics;

public class AppContainerRunner {
    [DllImport("userenv.dll", CharSet = CharSet.Unicode, SetLastError = true)]
    public static extern int CreateAppContainerProfile(
        string pszAppContainerName, string pszDisplayName, string pszDescription,
        IntPtr pCapabilities, uint dwCapabilityCount, out IntPtr ppSid);
        
    [DllImport("userenv.dll", CharSet = CharSet.Unicode, SetLastError = true)]
    public static extern int DeriveAppContainerSidFromAppContainerName(
        string pszAppContainerName, out IntPtr ppSid);

    [StructLayout(LayoutKind.Sequential)]
    public struct SECURITY_CAPABILITIES {
        public IntPtr AppContainerSid;
        public IntPtr Capabilities;
        public uint CapabilityCount;
        public uint Reserved;
    }

    [StructLayout(LayoutKind.Sequential, CharSet = CharSet.Unicode)]
    public struct STARTUPINFOEX {
        public STARTUPINFO StartupInfo;
        public IntPtr lpAttributeList;
    }

    [StructLayout(LayoutKind.Sequential, CharSet = CharSet.Unicode)]
    public struct STARTUPINFO {
        public int cb;
        public string lpReserved;
        public string lpDesktop;
        public string lpTitle;
        public int dwX;
        public int dwY;
        public int dwXSize;
        public int dwYSize;
        public int dwXCountChars;
        public int dwYCountChars;
        public int dwFillAttribute;
        public int dwFlags;
        public short wShowWindow;
        public short cbReserved2;
        public IntPtr lpReserved2;
        public IntPtr hStdInput;
        public IntPtr hStdOutput;
        public IntPtr hStdError;
    }

    [StructLayout(LayoutKind.Sequential)]
    public struct PROCESS_INFORMATION {
        public IntPtr hProcess;
        public IntPtr hThread;
        public int dwProcessId;
        public int dwThreadId;
    }

    [DllImport("kernel32.dll", SetLastError = true)]
    [return: MarshalAs(UnmanagedType.Bool)]
    public static extern bool InitializeProcThreadAttributeList(IntPtr lpAttributeList, int dwAttributeCount, int dwFlags, ref IntPtr lpSize);

    [DllImport("kernel32.dll", SetLastError = true)]
    [return: MarshalAs(UnmanagedType.Bool)]
    public static extern bool UpdateProcThreadAttribute(IntPtr lpAttributeList, uint dwFlags, IntPtr Attribute, ref SECURITY_CAPABILITIES lpValue, IntPtr cbSize, IntPtr lpPreviousValue, IntPtr lpReturnSize);

    [DllImport("kernel32.dll", CharSet = CharSet.Unicode, SetLastError = true)]
    [return: MarshalAs(UnmanagedType.Bool)]
    public static extern bool CreateProcess(string lpApplicationName, string lpCommandLine, IntPtr lpProcessAttributes, IntPtr lpThreadAttributes, bool bInheritHandles, uint dwCreationFlags, IntPtr lpEnvironment, string lpCurrentDirectory, ref STARTUPINFOEX lpStartupInfo, out PROCESS_INFORMATION lpProcessInformation);

    [DllImport("kernel32.dll", SetLastError = true)]
    public static extern uint WaitForSingleObject(IntPtr hHandle, uint dwMilliseconds);

    [DllImport("kernel32.dll", SetLastError = true)]
    [return: MarshalAs(UnmanagedType.Bool)]
    public static extern bool GetExitCodeProcess(IntPtr hProcess, out uint lpExitCode);

    [DllImport("kernel32.dll", SetLastError = true)]
    [return: MarshalAs(UnmanagedType.Bool)]
    public static extern bool CloseHandle(IntPtr hObject);

    [DllImport("kernel32.dll", SetLastError = true)]
    public static extern void DeleteProcThreadAttributeList(IntPtr lpAttributeList);

    public static int Run(string cmdLine) {
        string acName = "ArenaSandboxContainer";
        IntPtr sid;
        int hr = CreateAppContainerProfile(acName, acName, acName, IntPtr.Zero, 0, out sid);
        if (hr != 0) {
            hr = DeriveAppContainerSidFromAppContainerName(acName, out sid);
            if (hr != 0) return -1;
        }

        IntPtr attrSize = IntPtr.Zero;
        InitializeProcThreadAttributeList(IntPtr.Zero, 1, 0, ref attrSize);
        IntPtr attrList = Marshal.AllocHGlobal(attrSize.ToInt32());
        InitializeProcThreadAttributeList(attrList, 1, 0, ref attrSize);

        SECURITY_CAPABILITIES secCaps = new SECURITY_CAPABILITIES();
        secCaps.AppContainerSid = sid;
        IntPtr pSecCaps = Marshal.AllocHGlobal(Marshal.SizeOf(secCaps));
        Marshal.StructureToPtr(secCaps, pSecCaps, false);

        UpdateProcThreadAttribute(attrList, 0, (IntPtr)0x20009, ref secCaps, (IntPtr)Marshal.SizeOf(secCaps), IntPtr.Zero, IntPtr.Zero);

        STARTUPINFOEX siex = new STARTUPINFOEX();
        siex.StartupInfo.cb = Marshal.SizeOf(siex);
        siex.lpAttributeList = attrList;

        PROCESS_INFORMATION pi = new PROCESS_INFORMATION();
        uint EXTENDED_STARTUPINFO_PRESENT = 0x00080000;
        
        bool created = CreateProcess(null, cmdLine, IntPtr.Zero, IntPtr.Zero, false, EXTENDED_STARTUPINFO_PRESENT, IntPtr.Zero, null, ref siex, out pi);
        
        uint exitCode = 1;
        if (created) {
            WaitForSingleObject(pi.hProcess, 0xFFFFFFFF);
            GetExitCodeProcess(pi.hProcess, out exitCode);
            CloseHandle(pi.hProcess);
            CloseHandle(pi.hThread);
        } else {
            exitCode = (uint)Marshal.GetLastWin32Error();
            Console.WriteLine("CreateProcess Error: " + exitCode);
        }
        
        DeleteProcThreadAttributeList(attrList);
        Marshal.FreeHGlobal(attrList);
        Marshal.FreeHGlobal(pSecCaps);
        
        return (int)exitCode;
    }
}
"@

Add-Type -TypeDefinition $code -Language CSharp
$exitCode = [AppContainerRunner]::Run($CommandLine)
exit $exitCode
