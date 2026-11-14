import winreg
import sys
import os
import glob
import ctypes
import xmltodict

from ctypes import wintypes

def is_admin():
    try:
        return bool(ctypes.windll.shell32.IsUserAnAdmin())
    except OSError:
        return False

class GUID(ctypes.Structure):
    _fields_ = [
        ("Data1", wintypes.DWORD),
        ("Data2", wintypes.WORD),
        ("Data3", wintypes.WORD),
        ("Data4", ctypes.c_ubyte * 8)
    ]

    def __init__(self, text):
        super().__init__()
        ctypes.oledll.ole32.CLSIDFromString(text, ctypes.byref(self))

CLSID_FileOpenDialog = "{DC1C5A9C-E88A-4DDE-A5A1-60F82A20AEF7}"
IID_IFileOpenDialog = "{D57C7288-D4AD-4768-BE02-9D969532D960}"

FOS_PICKFOLDERS = 0x20
FOS_FORCEFILESYSTEM = 0x40
FOS_ALLOWMULTISELECT = 0x200
FOS_PATHMUSTEXIST = 0x800
SIGDN_FILESYSPATH = 0x80058000 - (1 << 32) # as a signed int
HRESULT_CANCELLED = 0x800704C7 - (1 << 32) # HRESULT_FROM_WIN32(ERROR_CANCELLED)

def com_call(obj, index, *args, argtypes = ()):
    """Calls the method at the given vtable index of a COM object, returning its HRESULT."""
    vtable = ctypes.cast(obj, ctypes.POINTER(ctypes.POINTER(ctypes.c_void_p)))[0]
    proto = ctypes.WINFUNCTYPE(ctypes.c_long, ctypes.c_void_p, *argtypes)
    return proto(vtable[index])(obj, *args)

def com_check(hr):
    if hr < 0:
        raise OSError(None, f"COM call failed (HRESULT 0x{hr & 0xFFFFFFFF:08X})", None, hr)

def com_release(obj):
    if obj:
        com_call(obj, 2) # IUnknown::Release

def ask_directories(title):
    """Shows a native folder picker that allows multiple selections. Returns a (possibly empty) list of paths."""
    ole32 = ctypes.oledll.ole32
    ctypes.windll.ole32.CoInitializeEx(None, 0x2) # COINIT_APARTMENTTHREADED; may return S_FALSE, which is fine

    dialog = ctypes.c_void_p()
    results = ctypes.c_void_p()

    try:
        ole32.CoCreateInstance(
            ctypes.byref(GUID(CLSID_FileOpenDialog)), None, 1, # CLSCTX_INPROC_SERVER
            ctypes.byref(GUID(IID_IFileOpenDialog)), ctypes.byref(dialog)
        )

        # IFileDialog::GetOptions (10) / SetOptions (9)
        options = wintypes.DWORD()
        com_check(com_call(dialog, 10, ctypes.byref(options), argtypes = (ctypes.POINTER(wintypes.DWORD),)))
        options.value |= FOS_PICKFOLDERS | FOS_ALLOWMULTISELECT | FOS_FORCEFILESYSTEM | FOS_PATHMUSTEXIST
        com_check(com_call(dialog, 9, options, argtypes = (wintypes.DWORD,)))

        # IFileDialog::SetTitle (17)
        com_check(com_call(dialog, 17, title, argtypes = (wintypes.LPCWSTR,)))

        # IModalWindow::Show (3)
        hr = com_call(dialog, 3, None, argtypes = (wintypes.HWND,))
        if hr == HRESULT_CANCELLED:
            return []

        com_check(hr)

        # IFileOpenDialog::GetResults (27) -> IShellItemArray
        com_check(com_call(dialog, 27, ctypes.byref(results), argtypes = (ctypes.POINTER(ctypes.c_void_p),)))

        # IShellItemArray::GetCount (7)
        count = wintypes.DWORD()
        com_check(com_call(results, 7, ctypes.byref(count), argtypes = (ctypes.POINTER(wintypes.DWORD),)))

        paths = []
        for i in range(count.value):
            item = ctypes.c_void_p()
            # IShellItemArray::GetItemAt (8) -> IShellItem
            com_check(com_call(
                results, 8, i, ctypes.byref(item),
                argtypes = (wintypes.DWORD, ctypes.POINTER(ctypes.c_void_p))
            ))

            try:
                # IShellItem::GetDisplayName (5)
                name = ctypes.c_wchar_p()
                com_check(com_call(
                    item, 5, SIGDN_FILESYSPATH, ctypes.byref(name),
                    argtypes = (ctypes.c_int, ctypes.POINTER(ctypes.c_wchar_p))
                ))

                paths.append(name.value)
                ctypes.windll.ole32.CoTaskMemFree(name)
            finally:
                com_release(item)

        return paths
    finally:
        com_release(results)
        com_release(dialog)

MB_YESNO = 0x04
MB_ICONERROR = 0x10
MB_ICONQUESTION = 0x20
MB_ICONWARNING = 0x30
MB_ICONINFORMATION = 0x40
MB_SETFOREGROUND = 0x10000
IDYES = 6

def message_box(text, title, flags):
    return ctypes.windll.user32.MessageBoxW(None, text, title, flags | MB_SETFOREGROUND)

def add_library(lib_root):
    """Registers the library at the given directory. Returns its name; raises an exception on failure."""
    nicnt_files = glob.glob(os.path.join(glob.escape(lib_root), "*.nicnt"))
    if not nicnt_files:
        raise ValueError(f"no NICNT files found in {lib_root}")

    nicnt = open(nicnt_files[0], "rb").read()

    # read the version, UTF-16, ends with NULL, at most 16 bytes
    version = nicnt[0x42:0x42 + 16][::2]
    version = version[:version.index(0x00)].decode()

    if version.count(".") == 1:
        version += ".0"

    # read the manifest block; starts at 0x100, and ends with NULL
    manifest = xmltodict.parse(nicnt[0x100:nicnt.index(0x00, 0x100)].decode())
    product = manifest["ProductHints"]["Product"]

    regkey = product["RegKey"]

    print()
    print("[.] Library information:")
    print(f"[.]    Name: {product["Name"]}")
    print(f"[.]    Company: {product["Company"]}")
    print(f"[.]    Registry key: {regkey}")
    print(f"[.]    Version: {version}")
    print(f"[.]    Location: {lib_root}")

    key = winreg.CreateKey(winreg.HKEY_LOCAL_MACHINE, fr"SOFTWARE\Native Instruments\{regkey}")
    try:
        winreg.SetValueEx(key, "ContentDir", 0, winreg.REG_SZ, lib_root.replace("/", "\\"))
        winreg.SetValueEx(key, "ContentVersion", 0, winreg.REG_SZ, version)
        winreg.SetValueEx(key, "HU", 0, winreg.REG_SZ, product["ProductSpecific"]["HU"])
        winreg.SetValueEx(key, "JDX", 0, winreg.REG_SZ, product["ProductSpecific"]["JDX"])
        winreg.SetValueEx(key, "Visibility", 0, winreg.REG_DWORD, 3)
    finally:
        winreg.CloseKey(key)

    print("[+] Library added!")
    return product["Name"]

def add_libraries(lib_roots):
    """Registers all given libraries. Returns a tuple of (added names, list of (path, error))."""
    added, failed = [], []

    for lib_root in lib_roots:
        try:
            added.append(add_library(lib_root))
        except Exception as e:
            print(f"[-] error: could not add {lib_root}: {e}", file = sys.stderr)
            failed.append((lib_root, e))

    return added, failed

def run_gui():
    title = "Kontakt Library Adder"

    while True:
        print()
        print("[.] please select the directories of the target libraries to continue")
        print("[.] each directory should have at least one .nicnt file in it")

        lib_roots = ask_directories("Select the directories of the target libraries")
        if not lib_roots:
            print("[-] cancelled")
            return 0

        added, failed = add_libraries(lib_roots)

        lines = []
        if added:
            lines.append("Library added!" if len(added) == 1 else f"{len(added)} libraries added!")
            lines += [f"  •  {name}" for name in added]

        if failed:
            if lines:
                lines.append("")

            lines.append("The following directories could not be added:")
            lines += [f"  •  {path}: {e}" for path, e in failed]

        lines += ["", "Do you want to add another one?"]

        icon = MB_ICONQUESTION if not failed else (MB_ICONWARNING if added else MB_ICONERROR)
        if message_box("\n".join(lines), title, MB_YESNO | icon) != IDYES:
            return 0 if not failed else 1

def main(args):
    if not args:
        print(f"[-] usage: {sys.argv[0]} [path...] | [gui]", file = sys.stderr)
        return 1

    if not is_admin():
        print("[-] error: administrator permissions are required!", file = sys.stderr)
        return 1

    if args == ["[gui]"]:
        return run_gui()

    _, failed = add_libraries(args)
    return 1 if failed else 0

if __name__ == "__main__":
    try:
        code = main(sys.argv[1:])
    except Exception as e:
        print(f"[-] error: {e}", file = sys.stderr)
        code = 1

    sys.exit(code)
