# Build StickyNotes for Windows

Run from the repository root with Python 3 and Tkinter.

```powershell
python StickyNotes.py
```

To build the desktop executable:

```powershell
python -m pip install pyinstaller
python -m PyInstaller --noconfirm --clean --windowed --name StickyNotes --icon StickyNotes.ico StickyNotes.py
```

Open StickyNotes.iss in Inno Setup 6 and compile it to generate installer/StickyNotesSetup.exe.
