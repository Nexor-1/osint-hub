# Сторонние компоненты OSINT Hub

Сам OSINT Hub распространяется под лицензией **GNU GPL v3** ([LICENSE](LICENSE)).

Внутри сборки и установщика (`OSINTHub-Setup-*.exe`, папка `OSINTHub\`) лежат перечисленные ниже сторонние компоненты, каждый под своей лицензией. Тексты лицензий входят в поставку.

## Встроенные инструменты (папка `tools\`)

Это отдельные программы. OSINT Hub запускает их как внешние процессы и не изменяет.

| Компонент | Версия | Лицензия | Текст лицензии в поставке | Исходный код этой версии |
|---|---|---|---|---|
| ExifTool (Phil Harvey) | 13.59 | GPL-1.0+ или Artistic License («the same terms as Perl itself») | `tools\exiftool\exiftool_files\LICENSE` | <https://sourceforge.net/projects/exiftool/files/Image-ExifTool-13.59.tar.gz/download> |
| Strawberry Perl (внутри Windows-сборки ExifTool) | 5.32 | GPL-1.0+ / Artistic и другие | `tools\exiftool\exiftool_files\Licenses_Strawberry_Perl.zip` | <https://strawberryperl.com/releases.html> |
| PhoneInfoga | 2.11.0 | GPL-3.0 | `tools\phoneinfoga\LICENSE` | <https://github.com/sundowndev/phoneinfoga/tree/v2.11.0> |
| SpiderFoot | 4.0, коммит `0f815a2` | MIT | `tools\spiderfoot\spiderfoot\LICENSE` | <https://github.com/smicallef/spiderfoot/tree/0f815a203afebf05c98b605dba5cf0475a0ee5fd> |
| CPython (встроенный Python для SpiderFoot) | 3.11.9 | PSF-2.0 | `tools\spiderfoot\python\LICENSE.txt` | <https://www.python.org/downloads/release/python-3119/> |
| Python-пакеты SpiderFoot (lxml, CherryPy и др.) | см. `requirements.txt` SpiderFoot | разные (BSD, MIT, Apache-2.0 и др.) | папки `*.dist-info` в `tools\spiderfoot\python\Lib\site-packages\` | PyPI |

## Библиотеки внутри `OSINTHub.exe`

| Компонент | Версия | Лицензия | Исходный код |
|---|---|---|---|
| Holehe | 1.61 | GPL-3.0 | <https://github.com/megadose/holehe> (PyPI: <https://pypi.org/project/holehe/1.61/>) |
| Sherlock (`sherlock-project`) | 0.16.2 | MIT | <https://github.com/sherlock-project/sherlock/tree/v0.16.2> |
| Qt 6 / PySide6 / Shiboken6 | 6.11.2 | LGPL-3.0 | <https://code.qt.io/cgit/pyside/pyside-setup.git/tag/?h=v6.11.2>, <https://download.qt.io/official_releases/qt/> |
| Chromium (в составе Qt WebEngine) | — | BSD-3-Clause и др. | <https://code.qt.io/cgit/qt/qtwebengine-chromium.git/> |
| CPython | 3.12 | PSF-2.0 | <https://www.python.org/> |
| Остальные Python-пакеты | — | MIT / BSD / Apache-2.0 / MPL-2.0 / LGPL-3.0 | перечень и тексты: [licenses/python/INDEX.md](licenses/python/INDEX.md) |

**Про LGPL (Qt/PySide6).** Библиотеки Qt лежат в сборке отдельными DLL (`_internal\PySide6\Qt6*.dll`, `_internal\PySide6\*.pyd`, `_internal\shiboken6\`). Их можно заменить своими совместимыми версиями. Текст лицензии — [licenses/LGPL-3.0.txt](licenses/LGPL-3.0.txt); сама LGPL-3.0 опирается на GPL-3.0 из [LICENSE](LICENSE).

## Ресурсы интерфейса

| Компонент | Лицензия | Текст |
|---|---|---|
| Шрифт Inter (Rasmus Andersson) | SIL OFL 1.1 | `app/ui/fonts/Inter-LICENSE.txt` |
| Шрифт JetBrains Mono | SIL OFL 1.1 | `app/ui/fonts/JetBrainsMono-LICENSE.txt` |
| Иконки Lucide | ISC | [licenses/Lucide-ISC.txt](licenses/Lucide-ISC.txt) |
| Leaflet 1.9.4 | BSD-2-Clause | `app/ui/map/LEAFLET-LICENSE.txt` |
| Картографические данные | © участники OpenStreetMap, ODbL | <https://www.openstreetmap.org/copyright> (тайлы загружаются с серверов OSM во время работы и в поставку не входят) |

## Как получить исходный код

Полный исходный код OSINT Hub, а также скрипты, которые скачивают и собирают перечисленные компоненты (`scripts/fetch_tools.py`, `build.bat`, `build/osinthub.spec`), лежат в этом репозитории. Исходный код GPL-компонентов доступен по ссылкам выше. В течение трёх лет с момента выпуска релиза его можно также запросить через Issues репозитория.
