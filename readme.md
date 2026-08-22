# kontakt-library-adder

A small Python utility to inspect Kontakt library metadata from `.nicnt` files, and to generate registration metadata for macOS while keeping Windows registry support.

## Quick Start

Run these scripts to bootstrap and run the Python script.

| OS      | Command |
|---------|---------|
| Windows | `run.bat` |
| macOS   | `./run.sh "/path/to/your/libraries"` |

## Setup

Create a Python 3 virtual environment and install the dependencies:

```bash
cd /path/to/kontakt-library-adder
python3 -m venv .venv 
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
```

## Usage

The script runs registration by default when you pass a library path.

Real registration mode:

```bash
python add-library.py "/path/to/kontakt/lib"
```

Dry-run (scan only, no write):

```bash
python add-library.py --dry "/path/to/kontakt/lib"
```

You may also use GUI mode:

```bash
python add-library.py "[gui]"
```

> Note: on macOS, add `sudo` to be able to write system-level metadata.

## Example output

```text
[.] Library information:
[.]    Path: /path/to/kontakt/lib/Some Kontakt Library
[.]    Name: Some Kontakt Library
[.]    Company: Native Instruments GmbH
[.]    Registry key: Some Kontakt Library
[.]    SNPID: 438
[.]    Version: 1.0.0

[dry-run] Would write macOS metadata:
[dry-run]   plist: ~/Library/Application Support/Native Instruments/Kontakt/Libraries/Some Kontakt Library.plist
[dry-run]   registry: ~/Library/Application Support/Native Instruments/Kontakt/LibraryRegistration.plist
```

## Notes

- On macOS, there is no direct Windows registry equivalent. The script creates metadata files in `~/Library/Application Support/Native Instruments/Kontakt/` instead.
- On macOS, the script also writes a per-library preferences plist and a Service Center XML file, including SNPID, to improve Kontakt library detection.
- Some legacy Kontakt libraries also rely on system-level metadata (e.g. `/Library/Preferences` and `/Library/Application Support/Native Instruments/Service Center`). If permissions are denied, re-run with administrator rights.
- Hidden macOS resource-fork duplicates such as `._*.nicnt` are ignored automatically.
- The parser reads the actual UTF-8 XML inside the NICNT payload and the UTF-16LE version block in the file header.
- The script stays compatible with Windows by still writing registry values when running on Windows.
