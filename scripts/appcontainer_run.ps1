# scripts/appcontainer_run.ps1
# Runs a command inside a Windows AppContainer (Low Privilege Sandbox).
#
# v4.104.0: this script is no longer just a best-effort launcher.  It grants
# the AppContainer SID access to the per-run scratch directory, redirects stdout
# and stderr through inheritable file handles, applies a wall timeout, and fails
# closed when profile creation, ACL grants, or process launch fail.

param (
    # Back-compat path used by the older generic sandbox runtime.  When this is
    # supplied without -ApplicationPath we run it through cmd.exe inside a fresh
    # scratch directory.
    [Parameter(Position=0)]
    [string]$CommandLine,

    # Preferred code.run path: launch a concrete interpreter/executable with an
    # explicit argv and scratch cwd.
    [string]$ApplicationPath,
    [string[]]$Arguments = @(),
    [string]$ScratchDir,
    [string]$RuntimeGrantDir,
    [int]$TimeoutSec = 60,
    [string]$ContainerName = "ArenaCodeRun"
)

$ErrorActionPreference = "Stop"

function Fail-Closed([string]$Message, [int]$Code = 125) {
    [Console]::Error.WriteLine("arena-appcontainer: " + $Message)
    exit $Code
}

if (-not $IsWindows -and $PSVersionTable.PSEdition -eq "Core") {
    Fail-Closed "AppContainer is Windows-only" 125
}

if ([string]::IsNullOrWhiteSpace($ApplicationPath)) {
    if ([string]::IsNullOrWhiteSpace($CommandLine)) {
        Fail-Closed "missing -ApplicationPath or legacy CommandLine" 125
    }
    $ApplicationPath = $env:ComSpec
    if ([string]::IsNullOrWhiteSpace($ApplicationPath)) { $ApplicationPath = "$env:SystemRoot\System32\cmd.exe" }
    $Arguments = @('/d', '/c', $CommandLine)
}

try {
    $ApplicationPath = (Resolve-Path -LiteralPath $ApplicationPath).Path
} catch {
    Fail-Closed "application path does not exist: $ApplicationPath" 125
}

if ([string]::IsNullOrWhiteSpace($ScratchDir)) {
    $ScratchDir = Join-Path ([System.IO.Path]::GetTempPath()) ("arena-code-" + [Guid]::NewGuid().ToString("N"))
}
New-Item -ItemType Directory -Force -Path $ScratchDir | Out-Null
$ScratchDir = (Resolve-Path -LiteralPath $ScratchDir).Path

if ([string]::IsNullOrWhiteSpace($RuntimeGrantDir)) {
    $RuntimeGrantDir = Split-Path -Parent $ApplicationPath
}
try {
    $RuntimeGrantDir = (Resolve-Path -LiteralPath $RuntimeGrantDir).Path
} catch {
    Fail-Closed "runtime grant path does not exist: $RuntimeGrantDir" 125
}

$stdoutPath = Join-Path $ScratchDir "stdout.txt"
$stderrPath = Join-Path $ScratchDir "stderr.txt"
New-Item -ItemType File -Force -Path $stdoutPath | Out-Null
New-Item -ItemType File -Force -Path $stderrPath | Out-Null

$code = @"
using System;
using System.Runtime.InteropServices;
using System.Text;

public class AppContainerRunner {
    [DllImport("userenv.dll", CharSet = CharSet.Unicode, SetLastError = true)]
    public static extern int CreateAppContainerProfile(
        string pszAppContainerName, string pszDisplayName, string pszDescription,
        IntPtr pCapabilities, uint dwCapabilityCount, out IntPtr ppSid);

    [DllImport("userenv.dll", CharSet = CharSet.Unicode, SetLastError = true)]
    public static extern int DeriveAppContainerSidFromAppContainerName(
        string pszAppContainerName, out IntPtr ppSid);

    [DllImport("userenv.dll", CharSet = CharSet.Unicode, SetLastError = true)]
    public static extern int DeleteAppContainerProfile(string pszAppContainerName);

    [DllImport("advapi32.dll", EntryPoint = "ConvertSidToStringSidW", CharSet = CharSet.Unicode, SetLastError = true)]
    [return: MarshalAs(UnmanagedType.Bool)]
    public static extern bool ConvertSidToStringSid(IntPtr Sid, out IntPtr StringSid);

    [DllImport("kernel32.dll", SetLastError = true)]
    public static extern IntPtr LocalFree(IntPtr hMem);

    [StructLayout(LayoutKind.Sequential)]
    public struct SECURITY_CAPABILITIES {
        public IntPtr AppContainerSid;
        public IntPtr Capabilities;
        public uint CapabilityCount;
        public uint Reserved;
    }

    [StructLayout(LayoutKind.Sequential)]
    public struct SECURITY_ATTRIBUTES {
        public int nLength;
        public IntPtr lpSecurityDescriptor;
        [MarshalAs(UnmanagedType.Bool)] public bool bInheritHandle;
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
    public static extern bool TerminateProcess(IntPtr hProcess, uint uExitCode);

    [DllImport("kernel32.dll", SetLastError = true)]
    [return: MarshalAs(UnmanagedType.Bool)]
    public static extern bool CloseHandle(IntPtr hObject);

    [DllImport("kernel32.dll", SetLastError = true)]
    public static extern void DeleteProcThreadAttributeList(IntPtr lpAttributeList);

    [DllImport("kernel32.dll", CharSet = CharSet.Unicode, SetLastError = true)]
    public static extern IntPtr CreateFile(string lpFileName, uint dwDesiredAccess, uint dwShareMode, ref SECURITY_ATTRIBUTES lpSecurityAttributes, uint dwCreationDisposition, uint dwFlagsAndAttributes, IntPtr hTemplateFile);

    const uint EXTENDED_STARTUPINFO_PRESENT = 0x00080000;
    const int PROC_THREAD_ATTRIBUTE_SECURITY_CAPABILITIES = 0x00020009;
    const int STARTF_USESTDHANDLES = 0x00000100;
    const uint WAIT_TIMEOUT = 0x00000102;
    const uint WAIT_FAILED = 0xFFFFFFFF;
    const uint GENERIC_READ = 0x80000000;
    const uint GENERIC_WRITE = 0x40000000;
    const uint FILE_SHARE_READ = 0x00000001;
    const uint FILE_SHARE_WRITE = 0x00000002;
    const uint CREATE_ALWAYS = 2;
    const uint OPEN_EXISTING = 3;
    const uint FILE_ATTRIBUTE_NORMAL = 0x00000080;
    static readonly IntPtr INVALID_HANDLE_VALUE = new IntPtr(-1);

    public static string EnsureProfileSidString(string acName) {
        IntPtr sid;
        int hr = CreateAppContainerProfile(acName, acName, acName, IntPtr.Zero, 0, out sid);
        if (hr != 0) {
            hr = DeriveAppContainerSidFromAppContainerName(acName, out sid);
            if (hr != 0) throw new InvalidOperationException("DeriveAppContainerSid failed hr=0x" + hr.ToString("X"));
        }
        IntPtr strPtr;
        if (!ConvertSidToStringSid(sid, out strPtr)) {
            throw new InvalidOperationException("ConvertSidToStringSid failed err=" + Marshal.GetLastWin32Error());
        }
        string s = Marshal.PtrToStringUni(strPtr);
        LocalFree(strPtr);
        return s;
    }

    static string QuoteArg(string s) {
        if (s == null) return "\"\"";
        StringBuilder b = new StringBuilder();
        b.Append('"');
        int slashCount = 0;
        foreach (char c in s) {
            if (c == '\\') { slashCount++; continue; }
            if (c == '"') {
                b.Append('\\', slashCount * 2 + 1);
                b.Append('"');
                slashCount = 0;
                continue;
            }
            if (slashCount > 0) { b.Append('\\', slashCount); slashCount = 0; }
            b.Append(c);
        }
        if (slashCount > 0) b.Append('\\', slashCount * 2);
        b.Append('"');
        return b.ToString();
    }

    static string BuildCommandLine(string app, string[] args) {
        StringBuilder b = new StringBuilder();
        b.Append(QuoteArg(app));
        if (args != null) {
            foreach (string a in args) { b.Append(' '); b.Append(QuoteArg(a)); }
        }
        return b.ToString();
    }

    public static int Run(string acName, string app, string[] args, string cwd, string stdoutPath, string stderrPath, int timeoutSec) {
        IntPtr sid;
        int hr = DeriveAppContainerSidFromAppContainerName(acName, out sid);
        if (hr != 0) throw new InvalidOperationException("DeriveAppContainerSid failed hr=0x" + hr.ToString("X"));

        IntPtr attrSize = IntPtr.Zero;
        InitializeProcThreadAttributeList(IntPtr.Zero, 1, 0, ref attrSize);
        IntPtr attrList = Marshal.AllocHGlobal(attrSize.ToInt32());
        if (!InitializeProcThreadAttributeList(attrList, 1, 0, ref attrSize)) {
            throw new InvalidOperationException("InitializeProcThreadAttributeList failed err=" + Marshal.GetLastWin32Error());
        }

        SECURITY_CAPABILITIES secCaps = new SECURITY_CAPABILITIES();
        secCaps.AppContainerSid = sid;
        secCaps.Capabilities = IntPtr.Zero;
        secCaps.CapabilityCount = 0; // no capabilities: no internetClient, no privateNetwork
        secCaps.Reserved = 0;
        if (!UpdateProcThreadAttribute(attrList, 0, (IntPtr)PROC_THREAD_ATTRIBUTE_SECURITY_CAPABILITIES, ref secCaps, (IntPtr)Marshal.SizeOf(secCaps), IntPtr.Zero, IntPtr.Zero)) {
            throw new InvalidOperationException("UpdateProcThreadAttribute failed err=" + Marshal.GetLastWin32Error());
        }

        SECURITY_ATTRIBUTES sa = new SECURITY_ATTRIBUTES();
        sa.nLength = Marshal.SizeOf(typeof(SECURITY_ATTRIBUTES));
        sa.lpSecurityDescriptor = IntPtr.Zero;
        sa.bInheritHandle = true;
        IntPtr hOut = CreateFile(stdoutPath, GENERIC_WRITE, FILE_SHARE_READ | FILE_SHARE_WRITE, ref sa, CREATE_ALWAYS, FILE_ATTRIBUTE_NORMAL, IntPtr.Zero);
        if (hOut == INVALID_HANDLE_VALUE) throw new InvalidOperationException("CreateFile(stdout) failed err=" + Marshal.GetLastWin32Error());
        IntPtr hErr = CreateFile(stderrPath, GENERIC_WRITE, FILE_SHARE_READ | FILE_SHARE_WRITE, ref sa, CREATE_ALWAYS, FILE_ATTRIBUTE_NORMAL, IntPtr.Zero);
        if (hErr == INVALID_HANDLE_VALUE) throw new InvalidOperationException("CreateFile(stderr) failed err=" + Marshal.GetLastWin32Error());
        IntPtr hIn = CreateFile("NUL", GENERIC_READ, FILE_SHARE_READ | FILE_SHARE_WRITE, ref sa, OPEN_EXISTING, FILE_ATTRIBUTE_NORMAL, IntPtr.Zero);
        if (hIn == INVALID_HANDLE_VALUE) throw new InvalidOperationException("CreateFile(NUL) failed err=" + Marshal.GetLastWin32Error());

        STARTUPINFOEX siex = new STARTUPINFOEX();
        siex.StartupInfo.cb = Marshal.SizeOf(siex);
        siex.StartupInfo.dwFlags = STARTF_USESTDHANDLES;
        siex.StartupInfo.hStdInput = hIn;
        siex.StartupInfo.hStdOutput = hOut;
        siex.StartupInfo.hStdError = hErr;
        siex.lpAttributeList = attrList;

        PROCESS_INFORMATION pi = new PROCESS_INFORMATION();
        string cmdLine = BuildCommandLine(app, args);
        bool created = CreateProcess(app, cmdLine, IntPtr.Zero, IntPtr.Zero, true, EXTENDED_STARTUPINFO_PRESENT, IntPtr.Zero, cwd, ref siex, out pi);
        if (!created) {
            int err = Marshal.GetLastWin32Error();
            CloseHandle(hIn); CloseHandle(hOut); CloseHandle(hErr);
            DeleteProcThreadAttributeList(attrList);
            Marshal.FreeHGlobal(attrList);
            throw new InvalidOperationException("CreateProcess failed err=" + err);
        }

        uint waitMs = timeoutSec <= 0 ? 60000u : (uint)Math.Min((long)timeoutSec * 1000L, (long)UInt32.MaxValue - 1L);
        uint wait = WaitForSingleObject(pi.hProcess, waitMs);
        uint exitCode = 1;
        if (wait == WAIT_TIMEOUT) {
            TerminateProcess(pi.hProcess, 124);
            WaitForSingleObject(pi.hProcess, 5000);
            exitCode = 124;
        } else if (wait == WAIT_FAILED) {
            exitCode = 125;
        } else {
            GetExitCodeProcess(pi.hProcess, out exitCode);
        }

        CloseHandle(pi.hProcess);
        CloseHandle(pi.hThread);
        CloseHandle(hIn);
        CloseHandle(hOut);
        CloseHandle(hErr);
        DeleteProcThreadAttributeList(attrList);
        Marshal.FreeHGlobal(attrList);
        return (int)exitCode;
    }
}
"@

try {
    Add-Type -TypeDefinition $code -Language CSharp
} catch {
    Fail-Closed ("cannot compile AppContainer launcher: " + $_.Exception.Message) 125
}

try {
    $sidString = [AppContainerRunner]::EnsureProfileSidString($ContainerName)
} catch {
    Fail-Closed ("cannot create/derive AppContainer profile: " + $_.Exception.Message) 125
}

function Grant-AppContainerPath([string]$Path, [System.Security.AccessControl.FileSystemRights]$Rights) {
    # Use .NET ACL APIs instead of icacls account-name parsing.  AppContainer
    # SIDs (S-1-15-2-...) are real SecurityIdentifier values, but icacls may try
    # to translate them as account names and fail with ERROR_NONE_MAPPED (1337).
    $resolved = (Resolve-Path -LiteralPath $Path).Path
    $identity = New-Object System.Security.Principal.SecurityIdentifier($sidString)
    $inherit = [System.Security.AccessControl.InheritanceFlags]::None
    if (Test-Path -LiteralPath $resolved -PathType Container) {
        $inherit = [System.Security.AccessControl.InheritanceFlags]::ContainerInherit -bor [System.Security.AccessControl.InheritanceFlags]::ObjectInherit
    }
    $propagation = [System.Security.AccessControl.PropagationFlags]::None
    $rule = New-Object System.Security.AccessControl.FileSystemAccessRule($identity, $Rights, $inherit, $propagation, [System.Security.AccessControl.AccessControlType]::Allow)
    $acl = Get-Acl -LiteralPath $resolved
    $acl.SetAccessRule($rule)
    Set-Acl -LiteralPath $resolved -AclObject $acl
}

try {
    Grant-AppContainerPath $ScratchDir ([System.Security.AccessControl.FileSystemRights]::Modify)
    # The runtime grant is intentionally narrower than the user's profile: just
    # the interpreter/runtime root chosen by arena.autonomy.runner.  If Windows
    # says we cannot grant it, we refuse instead of silently launching unfenced.
    Grant-AppContainerPath $RuntimeGrantDir ([System.Security.AccessControl.FileSystemRights]::ReadAndExecute)
} catch {
    Fail-Closed ("cannot grant AppContainer ACL: " + $_.Exception.Message) 125
}

try {
    $exitCode = [AppContainerRunner]::Run($ContainerName, $ApplicationPath, $Arguments, $ScratchDir, $stdoutPath, $stderrPath, $TimeoutSec)
} catch {
    Fail-Closed ("AppContainer launch failed: " + $_.Exception.Message) 125
}

try {
    if (Test-Path -LiteralPath $stdoutPath) { [Console]::Out.Write([System.IO.File]::ReadAllText($stdoutPath)) }
    if (Test-Path -LiteralPath $stderrPath) { [Console]::Error.Write([System.IO.File]::ReadAllText($stderrPath)) }
} catch {
    Fail-Closed ("cannot read captured output: " + $_.Exception.Message) 125
}

exit $exitCode
