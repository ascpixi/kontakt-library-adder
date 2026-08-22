import glob
import json
import os
import pwd
import plistlib
import re
import sys
from pathlib import Path

import xmltodict

__version__ = "1.1.0"

try:
  import winreg
except ImportError:
  winreg = None


def print_usage(script_name: str) -> None:
  print(
    f"usage: {script_name} [--dry] [--debug] [--help] [--version] <path>", file=sys.stderr)
  print("", file=sys.stderr)
  print("Options:", file=sys.stderr)
  print("  --dry                               Read-only mode: print what would be written.", file=sys.stderr)
  print("  --debug                             Show low-level NICNT diagnostics if parsing fails.", file=sys.stderr)
  print("  --help, -h                          Show this help message and exit.", file=sys.stderr)
  print("  --version, -v                       Show the script version and exit.", file=sys.stderr)


def print_version() -> None:
  print(f"kontakt-library-adder {__version__}")


def parse_legacy_arguments(argv: list[str]) -> tuple[bool, bool, bool, bool, str | None]:
  dry_run = False
  debug = False
  show_help = False
  show_version = False
  args = []

  for arg in argv[1:]:
    if arg == "--dry":
      dry_run = True
    elif arg == "--debug":
      debug = True
    elif arg in {"--help", "-h"}:
      show_help = True
    elif arg in {"--version", "-v"}:
      show_version = True
    else:
      args.append(arg)

  if show_help or show_version:
    return dry_run, debug, show_help, show_version, None

  if len(args) != 1:
    raise ValueError("expected exactly one path argument")

  return dry_run, debug, show_help, show_version, args[0]


def parse_arguments(argv: list[str]) -> tuple[bool, bool, bool, bool, str | None]:
  return parse_legacy_arguments(argv)


def resolve_effective_user_home() -> Path:
  """Return the non-root user home when running under sudo."""
  if os.name == "posix" and hasattr(os, "geteuid") and os.geteuid() == 0:
    sudo_user = os.environ.get("SUDO_USER")
    if sudo_user:
      try:
        return Path(pwd.getpwnam(sudo_user).pw_dir)
      except KeyError:
        pass
  return Path.home()


def select_library_root(arg: str) -> str:
  if arg != "[gui]":
    return arg

  try:
    import tkinter as tk
    from tkinter import filedialog
  except ImportError:
    print("[-] GUI mode requires tkinter to be installed.", file=sys.stderr)
    raise SystemExit(1)

  root = tk.Tk()
  root.withdraw()

  print("[.] Please select the target library directory to continue.")
  print("[.] The selected directory must contain at least one .nicnt file.")

  selected = filedialog.askdirectory(
      mustexist=True,
      title="Select the directory of the target library",
  )
  root.destroy()

  if not selected:
    print("[-] Canceled by user.")
    raise SystemExit(0)

  return selected


def find_nicnt_files(lib_root: str) -> list[str]:
  lib_root = os.path.abspath(lib_root)

  def is_valid_nicnt(path: Path) -> bool:
    if path.name.startswith("._"):
      return False
    return path.name.lower().endswith(".nicnt")

  if os.path.isfile(lib_root) and lib_root.lower().endswith(".nicnt") and not os.path.basename(lib_root).startswith("._"):
    return [lib_root]

  if os.path.isdir(lib_root):
    matches = [
        str(path)
        for path in sorted(Path(lib_root).rglob("*.nicnt"), key=lambda p: str(p).lower())
        if is_valid_nicnt(path)
    ]
    if matches:
      return matches

    matches = [
        path for path in sorted(glob.glob(os.path.join(lib_root, "*.nicnt")))
        if not os.path.basename(path).startswith("._")
    ]
    if matches:
      return matches

  raise FileNotFoundError(f"no NICNT files found in {lib_root}")


def read_version(nicnt: bytes) -> str:
  raw = nicnt[0x42:0x42 + 32]
  version = raw.decode("utf-16-le", errors="ignore")
  version = version.split("\x00", 1)[0].strip()
  if version.count(".") == 1:
    version += ".0"
  return version


def extract_manifest_xml(nicnt: bytes) -> str:
  xml_end = b"</ProductHints>"
  starts = []
  for marker in (0x100, nicnt.find(b"<?xml"), nicnt.find(b"<ProductHints")):
    if marker != -1:
      starts.append(marker)

  if not starts:
    raise ValueError("No XML manifest found in NICNT payload")

  for start in sorted(set(starts)):
    end = nicnt.find(xml_end, start)
    if end == -1:
      continue

    chunk = nicnt[start:end + len(xml_end)]
    for encoding in ("utf-8", "utf-16", "utf-16-le"):
      try:
        text = chunk.decode(encoding, errors="strict")
      except UnicodeDecodeError:
        continue

      if "<ProductHints" in text:
        return text[text.index("<ProductHints"):]

  raise ValueError("Unable to locate ProductHints XML in NICNT payload")


def debug_nicnt_file(path: str) -> None:
  nicnt = Path(path).read_bytes()
  print(f"\n[debug] NICNT file: {path}")
  print(f"[debug] size: {len(nicnt)} bytes")
  print("[debug] first 128 bytes:")
  sample = nicnt[:128]
  print("[debug] " + " ".join(f"{b:02x}" for b in sample))

  needles = [b"ProductHints", b"<ProductHints",
             b"<", b"\x3c\x00", b"\xff\xfe\x3c\x00"]
  hits = []
  for needle in needles:
    pos = nicnt.find(needle)
    while pos != -1:
      hits.append((needle, pos))
      pos = nicnt.find(needle, pos + 1)

  print("[debug] XML-ish offsets:")
  for needle, pos in sorted(set(hits), key=lambda item: item[1])[:40]:
    print(f"[debug]   {needle!r} @ 0x{pos:04x}")

  for start in sorted({0x100, 0x200, 0x400, 0x800, 0x1000}):
    chunk = nicnt[start:start + 256]
    try:
      utf16 = chunk.decode("utf-16", errors="strict")
      if "ProductHints" in utf16 or "<" in utf16:
        print(f"[debug] utf-16 around 0x{start:04x}: {utf16[:120]!r}")
    except Exception:
      pass


def parse_manifest(nicnt: bytes):
  manifest_xml = extract_manifest_xml(nicnt)
  manifest = xmltodict.parse(manifest_xml)
  return manifest["ProductHints"]["Product"]


def get_product_specific(product: dict) -> dict:
  product_specific = product.get("ProductSpecific", {})
  if product_specific is None:
    return {}
  return product_specific


def scalar_text(value, default: str = "") -> str:
  if value is None:
    return default
  if isinstance(value, dict):
    for key in ("#text", "@value", "value"):
      if key in value and value[key] is not None:
        return str(value[key]).strip()
    return default
  if isinstance(value, list):
    if not value:
      return default
    return scalar_text(value[0], default=default)
  return str(value).strip()


def normalize_snpid(value: str | None) -> str:
  if value is None:
    return ""

  # Kontakt can use decimal, hex, or vendor-specific SNPID forms.
  # Preserve file-provided format to avoid identifier mismatches.
  return str(value).strip()


def get_library_info(nicnt_path: str) -> dict:
  nicnt = Path(nicnt_path).read_bytes()
  manifest_xml = extract_manifest_xml(nicnt)
  product = parse_manifest(nicnt)
  product_specific = get_product_specific(product)
  version = read_version(nicnt)

  library_root = str(Path(nicnt_path).parent)

  return {
      "path": nicnt_path,
      "library_root": library_root,
      "manifest_xml": manifest_xml,
      "name": scalar_text(product.get("Name")),
      "company": scalar_text(product.get("Company")),
      "regkey": scalar_text(product.get("RegKey")),
      "version": version,
      "snpid": normalize_snpid(product.get("SNPID")),
      "hu": scalar_text(product_specific.get("HU")),
      "jdx": scalar_text(product_specific.get("JDX")),
      "visibility": scalar_text(product_specific.get("Visibility", product.get("Visibility", "3")), default="3"),
      "auth_system": scalar_text(product.get("AuthSystem"), default="RAS3"),
      "type": scalar_text(product.get("Type"), default="Content"),
      "powered_by": scalar_text(product.get("PoweredBy"), default="Kontakt"),
      "icon": scalar_text(product.get("Icon")),
      "upid": scalar_text(product.get("UPID")),
  }


def print_library_info(info: dict) -> None:
  print()
  print("[.] Library information:")
  print(f"[.]    Path: {info['library_root']}")
  print(f"[.]    Name: {info['name']}")
  print(f"[.]    Company: {info['company']}")
  print(f"[.]    Registry key: {info['regkey']}")
  if info["snpid"]:
    print(f"[.]    SNPID: {info['snpid']}")
  print(f"[.]    Version: {info['version']}")
  print()


def write_windows_registry(info: dict, lib_root: str, dry_run: bool = False) -> None:
  values = {
      "ContentDir": lib_root.replace("/", "\\"),
      "ContentVersion": info["version"],
      "SNPID": info["snpid"],
      "HU": info["hu"],
      "JDX": info["jdx"],
      "Visibility": 3,
  }

  if dry_run:
    print("[dry-run] Would write to Windows registry:")
    print(f"[dry-run]   Key: SOFTWARE\\Native Instruments\\{info['regkey']}")
    for name, value in values.items():
      print(f"[dry-run]   {name} = {value!r}")
    return

  if winreg is None:
    raise RuntimeError("winreg is not available on this platform")

  key = winreg.CreateKey(
      winreg.HKEY_LOCAL_MACHINE,
      fr"SOFTWARE\Native Instruments\{info['regkey']}",
  )

  for name, value in values.items():
    if isinstance(value, int):
      winreg.SetValueEx(key, name, 0, winreg.REG_DWORD, value)
    else:
      winreg.SetValueEx(key, name, 0, winreg.REG_SZ, value)

  winreg.CloseKey(key)
  print("[+] Library added on Windows!")


def build_macos_library_record(info: dict, lib_root: str) -> dict:
  return {
      "DisplayName": info["name"],
      "Name": info["name"],
      "Company": info["company"],
      "RegKey": info["regkey"],
      "SNPID": info["snpid"],
      "UPID": info["upid"],
      "ContentDir": lib_root,
      "ContentVersion": info["version"],
      "LibraryRoot": lib_root,
      "HU": info["hu"],
      "JDX": info["jdx"],
      "Visibility": 3,
      "Platform": "macOS",
      "Installed": True,
      "Path": lib_root,
  }


def build_macos_preference_record(info: dict, lib_root: str) -> dict:
  return {
      "ContentDir": lib_root,
      "ContentVersion": info["version"],
      "SNPID": info["snpid"],
      "HU": info["hu"],
      "JDX": info["jdx"],
      "Visibility": 3,
  }


def build_service_center_record(info: dict) -> dict:
  product_specific = {
      "HU": info["hu"],
      "JDX": info["jdx"],
      "Visibility": str(info["visibility"]),
  }

  product = {
      "@version": "1",
      "Name": info["name"],
      "RegKey": info["regkey"],
      "Company": info["company"],
      "SNPID": info["snpid"],
      "Type": info["type"],
      "AuthSystem": info["auth_system"],
      "PoweredBy": info["powered_by"],
      "Visibility": str(info["visibility"]),
      "ProductSpecific": product_specific,
  }

  if info["icon"]:
    product["Icon"] = info["icon"]
  if info["upid"]:
    product["UPID"] = info["upid"]

  return {"ProductHints": {"Product": product}}


def build_service_center_xml_text(info: dict) -> str:
  manifest_xml = info.get("manifest_xml", "")
  if manifest_xml:
    manifest_xml = manifest_xml.strip()
    if manifest_xml.startswith("<?xml"):
      return manifest_xml + ("" if manifest_xml.endswith("\n") else "\n")
    return '<?xml version="1.0" encoding="utf-8"?>\n' + manifest_xml + ("" if manifest_xml.endswith("\n") else "\n")

  fallback_xml = xmltodict.unparse(
    build_service_center_record(info), pretty=True)
  return fallback_xml + "\n"


def write_macos_metadata(info: dict, lib_root: str, dry_run: bool = False) -> None:
  user_home = resolve_effective_user_home()
  support_dir = user_home / "Library" / \
      "Application Support" / "Native Instruments"
  system_support_dir = Path("/Library/Application Support/Native Instruments")
  kontakt_dir = support_dir / "Kontakt"
  service_center_dir = support_dir / "Service Center"
  system_service_center_dir = system_support_dir / "Service Center"
  library_dir = kontakt_dir / "Libraries"
  payload = build_macos_library_record(info, lib_root)
  preference_payload = build_macos_preference_record(info, lib_root)
  service_center_xml = build_service_center_xml_text(info)

  safe_name = info["regkey"].replace("/", "_").replace("\\", "_")
  plist_path = library_dir / f"{safe_name}.plist"
  json_path = library_dir / f"{safe_name}.json"
  registry_path = kontakt_dir / "LibraryRegistration.plist"
  registry_json = kontakt_dir / "LibraryRegistration.json"
  preference_path = user_home / "Library" / "Preferences" / \
      f"com.native-instruments.{safe_name}.plist"
  system_preference_path = Path("/Library/Preferences") / \
      f"com.native-instruments.{safe_name}.plist"
  service_center_path = service_center_dir / f"{safe_name}.xml"
  system_service_center_path = system_service_center_dir / f"{safe_name}.xml"

  if dry_run:
    print("[dry-run] Would write macOS metadata:")
    print(f"[dry-run]   plist: {plist_path}")
    print(f"[dry-run]   json: {json_path}")
    print(f"[dry-run]   registry: {registry_path}")
    print(f"[dry-run]   registry json: {registry_json}")
    print(f"[dry-run]   user preferences plist: {preference_path}")
    print(f"[dry-run]   system preferences plist: {system_preference_path}")
    print(f"[dry-run]   user service center xml: {service_center_path}")
    print(
      f"[dry-run]   system service center xml: {system_service_center_path}")
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return

  library_dir.mkdir(parents=True, exist_ok=True)
  service_center_dir.mkdir(parents=True, exist_ok=True)
  preference_path.parent.mkdir(parents=True, exist_ok=True)

  with plist_path.open("wb") as handle:
    plistlib.dump(payload, handle)

  json_path.write_text(
      json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
      encoding="utf-8",
  )

  with preference_path.open("wb") as handle:
    plistlib.dump(preference_payload, handle)

  service_center_path.write_text(service_center_xml, encoding="utf-8")

  # Some Kontakt setups read system-level NI paths.
  try:
    system_service_center_dir.mkdir(parents=True, exist_ok=True)
    system_service_center_path.write_text(service_center_xml, encoding="utf-8")
    print(
      f"[+] System Service Center XML written to: {system_service_center_path}")
  except PermissionError:
    print(
      f"[-] No permission to write system Service Center XML: {system_service_center_path}")

  try:
    system_preference_path.parent.mkdir(parents=True, exist_ok=True)
    with system_preference_path.open("wb") as handle:
      plistlib.dump(preference_payload, handle)
    print(f"[+] System preferences plist written to: {system_preference_path}")
  except PermissionError:
    print(
      f"[-] No permission to write system preferences plist: {system_preference_path}")

  registry = {"Libraries": [], "Version": 1}
  if registry_path.exists():
    try:
      with registry_path.open("rb") as handle:
        registry = plistlib.load(handle)
    except Exception:
      registry = {"Libraries": [], "Version": 1}

  libraries = registry.setdefault("Libraries", [])
  item = next((entry for entry in libraries if entry.get(
    "RegKey") == info["regkey"]), None)
  if item is None:
    libraries.append(payload)
  else:
    libraries[libraries.index(item)] = payload

  registry["Version"] = 1
  with registry_path.open("wb") as handle:
    plistlib.dump(registry, handle)

  registry_json.write_text(
      json.dumps(registry, ensure_ascii=False, indent=2) + "\n",
      encoding="utf-8",
  )

  print(f"[+] macOS library metadata written to: {plist_path}")
  print(f"[+] macOS registry written to: {registry_path}")
  print(f"[+] JSON fallback written to: {json_path}")
  print(f"[+] macOS preferences plist written to: {preference_path}")
  print(f"[+] Service Center XML written to: {service_center_path}")


def write_library_registration(info: dict, lib_root: str, dry_run: bool = False) -> None:
  if sys.platform.startswith("win"):
    write_windows_registry(info, lib_root, dry_run=dry_run)
    return

  if sys.platform == "darwin":
    write_macos_metadata(info, lib_root, dry_run=dry_run)
    return

  print("[-] Unsupported platform for automatic registration.", file=sys.stderr)
  print(f"[-] Detected platform: {sys.platform}", file=sys.stderr)
  raise SystemExit(1)


def process_libraries(lib_root_arg: str, dry_run: bool, debug: bool) -> None:
  lib_root = select_library_root(lib_root_arg)

  try:
    nicnt_files = find_nicnt_files(lib_root)
  except FileNotFoundError:
    print(f"[-] error: no NICNT files found in {lib_root}", file=sys.stderr)
    raise SystemExit(1)
  except Exception as exc:
    print(f"[-] error: {exc}", file=sys.stderr)
    raise SystemExit(1)

  if dry_run:
    print("[dry-run] mode enabled: no files or registry entries will be modified")

  if debug:
    print("[debug] enabled")

  try:
    if len(nicnt_files) == 1:
      info = get_library_info(nicnt_files[0])
      print_library_info(info)
      write_library_registration(info, info["library_root"], dry_run=dry_run)
      return

    for nicnt_file in nicnt_files:
      info = get_library_info(nicnt_file)
      print_library_info(info)
      write_library_registration(info, info["library_root"], dry_run=dry_run)

    print(f"[+] Processed {len(nicnt_files)} libraries.")
  except Exception as exc:
    if debug:
      for nicnt_file in nicnt_files:
        debug_nicnt_file(nicnt_file)
    print(f"[-] error: {exc}", file=sys.stderr)
    raise SystemExit(1)


def main() -> None:
  try:
    dry_run, debug, show_help, show_version, lib_root_arg = parse_arguments(
      sys.argv)
  except ValueError as exc:
    print_usage(sys.argv[0])
    print(f"[-] {exc}", file=sys.stderr)
    raise SystemExit(1)

  if show_help:
    print_usage(sys.argv[0])
    raise SystemExit(0)

  if show_version:
    print_version()
    raise SystemExit(0)

  if lib_root_arg is None:
    print("[-] missing required path argument", file=sys.stderr)
    print_usage(sys.argv[0])
    raise SystemExit(1)

  process_libraries(lib_root_arg, dry_run=dry_run, debug=debug)


if __name__ == "__main__":
  main()
