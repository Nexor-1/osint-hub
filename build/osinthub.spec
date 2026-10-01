# PyInstaller spec for OSINT Hub (one-folder build).
#   pyinstaller build/osinthub.spec --noconfirm --workpath build/work --distpath dist
# Bundled third-party tools (tools/) are copied next to OSINTHub.exe by build.bat,
# not packed here: they are separate programs and must stay updatable in place.

from pathlib import Path

from PyInstaller.utils.hooks import collect_data_files, collect_submodules, copy_metadata

ROOT = Path(SPECPATH).parent  # noqa: F821 (SPECPATH is injected by PyInstaller)

datas = [
    (str(ROOT / "app" / "ui" / "fonts"), "app/ui/fonts"),
    (str(ROOT / "app" / "ui" / "map"), "app/ui/map"),
    (str(ROOT / "app" / "core" / "templates"), "app/core/templates"),
]
datas += collect_data_files("sherlock_project")       # resources/data.json (offline site list)
datas += collect_data_files("holehe")
datas += copy_metadata("holehe") + copy_metadata("sherlock-project")  # versions via importlib.metadata

# mypyc-compiled wheels (e.g. tomli, imported by sherlock_project) need a hashed
# top-level helper extension "<hash>__mypyc" that PyInstaller does not detect.
import sysconfig  # noqa: E402

_site = Path(sysconfig.get_paths()["purelib"])
MYPYC = sorted({p.name.split(".")[0] for p in _site.glob("*__mypyc*.pyd")})

hiddenimports = MYPYC + (
    collect_submodules("app.adapters")
    + collect_submodules("holehe")                    # modules are discovered dynamically
    + collect_submodules("sherlock_project")
    + ["keyring.backends.Windows", "PySide6.QtWebEngineWidgets", "PySide6.QtWebEngineCore", "PySide6.QtSvg"]
)

excludes = [
    "tkinter", "pandas", "numpy", "openpyxl", "matplotlib", "IPython", "pytest", "PIL",
    "PySide6.Qt3DCore", "PySide6.Qt3DRender", "PySide6.QtCharts", "PySide6.QtDataVisualization",
    "PySide6.QtMultimedia", "PySide6.QtQuick3D", "PySide6.QtBluetooth", "PySide6.QtSensors",
    "PySide6.QtSerialPort", "PySide6.QtDesigner", "PySide6.QtPdf3D",
]

a = Analysis(  # noqa: F821
    [str(ROOT / "osinthub.py")],
    pathex=[str(ROOT)],
    datas=datas,
    hiddenimports=hiddenimports,
    excludes=excludes,
    noarchive=False,
)

# --- trim Qt: keep only what Widgets + Svg + WebEngineWidgets actually link against.
QT_DLLS = {
    "Qt6Core", "Qt6Gui", "Qt6Widgets", "Qt6Svg", "Qt6Network", "Qt6OpenGL", "Qt6Positioning",
    "Qt6PrintSupport", "Qt6Qml", "Qt6QmlMeta", "Qt6QmlModels", "Qt6QmlWorkerScript", "Qt6Quick",
    "Qt6QuickWidgets", "Qt6WebChannel", "Qt6WebEngineCore", "Qt6WebEngineWidgets",
}
KEEP_TRANSLATIONS = ("qt_ru", "qtbase_ru", "qtwebengine_ru", "ru.pak", "en-US.pak")


def _keep(dest: str) -> bool:
    d = dest.replace("\\", "/")
    name = d.rsplit("/", 1)[-1]
    if "/qml/" in d or d.startswith("PySide6/qml"):
        return False                                    # no QML UI in this app
    if ".debug." in name or "devtools_resources" in name:
        return False                                    # WebEngine debug/devtools packs (~85 MB)
    if "/translations/" in d:
        return name.startswith(KEEP_TRANSLATIONS)
    if name.startswith("Qt6") and name.endswith(".dll"):
        return name[:-4] in QT_DLLS
    return True


a.binaries = [x for x in a.binaries if _keep(x[0])]
a.datas = [x for x in a.datas if _keep(x[0])]

pyz = PYZ(a.pure)  # noqa: F821

exe = EXE(  # noqa: F821
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="OSINTHub",
    icon=str(ROOT / "build" / "app.ico"),
    version=str(ROOT / "build" / "version_info.txt"),
    console=False,
    disable_windowed_traceback=False,
    upx=False,
)

coll = COLLECT(  # noqa: F821
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    name="OSINTHub",
)
