"""
Desktop Companion — этап 7 (кот + снег + несколько питомцев + рыбки + мастерская + окна + нагрузка + язык + поддержка).
База: DesktopSnowSim/run.bat (V2, Python). Добавлено:
  * единственный экземпляр (повторный запуск открывает лаунчер уже запущенного приложения);
  * профиль поведения кота: «Активный» (как в BlackCat/cat.py) и «Спокойный» (как в версии со снегом);
  * общий конфиг DesktopCompanion_config.json (старый BlackCat_config.json читается как запасной).
  * CatOverlay разделён на Pet (один питомец) и CompanionOverlay (общий слой: снег, окна, мышь);
  * в лаунчере можно добавлять и убирать питомцев (вкладка «Питомцы»);
  * прыжок кота в большой сугроб (работает всегда, когда есть большие сугробы);
  * кормёжка рыбой, мастерская расцветок (до 3 своих), более реалистичный рендер кота, новый детский лаунчер;
  * этап 5: окна отслеживаются по событиям Windows (а не раз в 250 мс), учитывается порядок окон (снег не лежит на
    закрытых кромках), кучи привязаны к окну и ездят вместе с ним, координаты пересчитываются с учётом масштаба
    экрана и положения панели задач, при полноэкранной игре или видео слой ставится на паузу;
  * этап 6: режимы нагрузки («Авто», «Красиво», «Сбалансированно», «Легче», «Очень лёгкий»): число снежинок и частота
    отрисовки подстраиваются под активность и под реальную стоимость кадра; в лаунчере есть показатели нагрузки;
  * в мастерской по кнопке «Узор» разворачивается выбор узоров;
  * этап 7: русский и английский язык (кнопка в лаунчере), вкладка «Поддержать», уведомления только Telegram / MAX /
    браузер, «Полный выход» из трея закрывает всё приложение, снег с закрытого окна падает вниз, исправлена походка
    вправо, режим «Авто» ориентируется на реальную загрузку процессора.
Все прежние функции V1/V2 сохранены. Внешний снег на C# и файловый IPC больше не нужны.
"""
import sys
import os
import re
import json
import math
import random
import sqlite3
import shutil
import tempfile
import threading
import time
import ctypes
from ctypes import wintypes
from collections import namedtuple

from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QPushButton, QLabel, QComboBox, QTabWidget, QTextBrowser,
    QSystemTrayIcon, QMenu, QLineEdit, QListWidget, QScrollArea, QFrame, QGridLayout, QColorDialog
)
from PyQt6.QtCore import Qt, QTimer, QPointF, QRectF, QRect, pyqtSignal, QObject, QLockFile, QThread
from PyQt6.QtNetwork import QLocalServer, QLocalSocket
from PyQt6.QtGui import (
    QPainter, QColor, QPen, QBrush, QPainterPath, QPolygonF,
    QFont, QIcon, QPixmap, QAction, QCursor, QRegion, QRadialGradient
)

APP_TITLE = "Desktop Companion"


# ---- язык интерфейса (русский / английский) ----
LANG = "ru"
EN: dict = {}        # заполняется в конце файла: русский текст (ключ) -> английский


def get_language() -> str:
    return LANG


def set_language(code: str):
    global LANG
    LANG = code if code in ("ru", "en") else "ru"


def detect_language() -> str:
    """Язык интерфейса Windows: русский -> «ru», любой другой -> «en» (если определить не удалось: «ru»)."""
    try:
        lid = int(ctypes.windll.kernel32.GetUserDefaultUILanguage())
    except Exception:
        return "ru"
    if lid == 0:
        return "ru"
    return "ru" if (lid & 0xFF) == 0x19 else "en"


def tr(text: str) -> str:
    """Перевод строки интерфейса: ключ — русский текст. Для русского языка возвращает строку как есть."""
    if LANG == "en":
        return EN.get(text, text)
    return text


LANG_BUTTON_TEXT = {"ru": "🌐 English", "en": "🌐 Русский"}      # кнопка показывает язык, НА КОТОРЫЙ переключит
DONATE_FILE = "donate.txt"


def load_donate_info() -> dict:
    """Реквизиты для вкладки «Поддержать»: файл donate.txt рядом с программой (или вшитый при сборке)."""
    info = {"card": "", "holder": "", "bank": "", "note": ""}
    paths = []
    if getattr(sys, "frozen", False):
        paths.append(os.path.join(os.path.dirname(sys.executable), DONATE_FILE))
    paths.append(os.path.join(os.path.dirname(os.path.abspath(__file__)), DONATE_FILE))
    paths.append(resource_path(DONATE_FILE))
    for p in paths:
        if not os.path.exists(p):
            continue
        try:
            with open(p, encoding="utf-8-sig") as f:
                for line in f:
                    line = line.strip()
                    if not line or line.startswith("#") or "=" not in line:
                        continue
                    k, v = line.split("=", 1)
                    k = k.strip().lower()
                    if k in info:
                        info[k] = v.strip()
        except Exception:
            pass
        if info["card"]:
            break
    return info


def resource_path(name: str) -> str:
    """Путь к файлу рядом с программой (и внутри собранного exe)."""
    base = getattr(sys, "_MEIPASS", os.path.dirname(os.path.abspath(__file__)))
    return os.path.join(base, name)


LAUNCHER_TITLE = "Мой котик — Desktop Companion"
LAUNCHER_TITLE_EN = "My Kitty — Desktop Companion"
SINGLE_INSTANCE_ID = "DesktopCompanion_SingleInstance_v1"
CONFIG_NAME = "DesktopCompanion_config.json"
LEGACY_CONFIG_NAME = "BlackCat_config.json"

# Профили поведения кота (значения взяты из V1 и V2 без изменений)
PROFILES = {
    "calm": {"label": "Спокойный (как в версии со снегом)", "sleep_after": 25.0, "walk_speed": 1.45, "walk_phase": 0.16},
    "active": {"label": "Активный (как в BlackCat, бегает ~65 с)", "sleep_after": 65.0, "walk_speed": 1.85, "walk_phase": 0.20},
}
DEFAULT_PROFILE = "calm"
# Предварительный потолок числа питомцев (не измерен: уточним замерами CPU на этапе производительности).
# Его можно изменить ключом "max_pets" (1-20) в конфиге.
MAX_PETS = 8
CUSTOM_COLOR_MAX = 3          # максимум собственных расцветок
# Прыжок в сугроб. Значения подобраны на глаз и легко меняются:
BIG_PILE_MIN_H = 9.0          # px: ниже этой высоты куча считается «кучкой» и кота не интересует (пол: макс. 24 px, крыша окна: 16 px)
BIG_PILE_MIN_W = 5            # клеток сетки (по 8 px): куча должна быть ещё и достаточно широкой
PILE_REACH = 200.0            # px: кот замечает кучу только поблизости (не бежит через весь экран)
PILE_JUMP_START_DIST = 42.0   # px до центра кучи, с которых кот прыгает
COLOR_LABELS = {"black": "чёрный", "ginger": "рыжий", "white": "белый"}

# =====================================================================
# 1. WIN32 API ЧЕРЕЗ СТАНДАРТНЫЙ CTYPES
# =====================================================================
user32 = ctypes.windll.user32
dwmapi = ctypes.windll.dwmapi
kernel32 = ctypes.windll.kernel32

GWL_EXSTYLE = -20
WS_EX_TRANSPARENT = 0x00000020
WS_EX_LAYERED = 0x00080000
WS_EX_TOOLWINDOW = 0x00000080
WS_EX_TOPMOST = 0x00000008

DWMWA_EXTENDED_FRAME_BOUNDS = 9
DWMWA_CLOAKED = 14
PROCESS_QUERY_LIMITED_INFORMATION = 0x1000

WNDENUMPROC = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)


def get_process_name(hwnd) -> str:
    pid = wintypes.DWORD()
    user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
    if not pid.value:
        return ""
    h_proc = kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid.value)
    if not h_proc:
        return ""
    try:
        buf = ctypes.create_unicode_buffer(512)
        size = wintypes.DWORD(512)
        if kernel32.QueryFullProcessImageNameW(h_proc, 0, buf, ctypes.byref(size)):
            return os.path.basename(buf.value).lower()
    finally:
        kernel32.CloseHandle(h_proc)
    return ""



# =====================================================================
# 1б. СЛЕЖЕНИЕ ЗА ОКНАМИ (этап 5)
#     Win32Backend: единственное место, которое говорит с Windows.
#     WindowTracker: чистая логика (фильтры, порядок окон, перекрытия, координаты оверлея).
# =====================================================================
GWL_STYLE = -16
WS_EX_APPWINDOW = 0x00040000
GA_PARENT = 1
EVENT_SYSTEM_FOREGROUND = 0x0003
EVENT_SYSTEM_MOVESIZESTART = 0x000A
EVENT_SYSTEM_MOVESIZEEND = 0x000B
EVENT_SYSTEM_MINIMIZESTART = 0x0016
EVENT_SYSTEM_MINIMIZEEND = 0x0017
EVENT_OBJECT_DESTROY = 0x8001
EVENT_OBJECT_SHOW = 0x8002
EVENT_OBJECT_HIDE = 0x8003
EVENT_OBJECT_REORDER = 0x8004
EVENT_OBJECT_LOCATIONCHANGE = 0x800B
EVENT_OBJECT_CLOAKED = 0x8017
EVENT_OBJECT_UNCLOAKED = 0x8018
WINEVENT_OUTOFCONTEXT = 0x0000
OBJID_WINDOW = 0

WINEVENTPROC = ctypes.WINFUNCTYPE(
    None, wintypes.HANDLE, wintypes.DWORD, wintypes.HWND, wintypes.LONG, wintypes.LONG, wintypes.DWORD, wintypes.DWORD
)

# Окна, которые не считаются «окнами приложений» (рабочий стол, панель задач, наш собственный слой).
JUNK_CLASSES = {"Progman", "WorkerW", "Shell_TrayWnd", "Shell_SecondaryTrayWnd"}
JUNK_TITLES = {"BlackCatOverlay", "DesktopSnowOverlay", "Program Manager"}
MIN_WIN_W, MIN_WIN_H = 40, 24            # меньше этого окно не считается (подсказки в 1 пиксель и т.п.)
MIN_TOOL_W, MIN_TOOL_H = 60, 40          # служебные окна (меню, всплывающие панели) должны быть чуть больше
PILE_KEEP_FRAMES = 3600                  # куча на пропавшем окне живёт ~минуту (окно свёрнули и развернули: куча на месте)

RawWin = namedtuple("RawWin", "hwnd l t r b title cls style ex_style zoomed")


class NullBackend:
    """Заглушка (не Windows, тесты): окон нет, событий нет."""
    hooks_ok = False

    def enum_raw(self):
        return []

    def query_rect(self, hwnd):
        return None

    def window_exists(self, hwnd) -> bool:
        return True

    def fullscreen_app_active(self) -> bool:
        return False

    def install_hooks(self, on_event) -> bool:
        return False

    def shutdown(self):
        pass


class Win32Backend:
    """Единственное место, которое говорит с Windows: список окон, события окон, режим полного экрана."""

    def __init__(self):
        self.hooks_ok = False
        self._hooks = []
        self._proc = None
        self._on_event = None
        self._desktop = 0
        try:
            self._desktop = int(user32.GetDesktopWindow() or 0)
        except Exception:
            pass

    # --- список окон сверху вниз (порядок EnumWindows = порядок по Z) ---
    def enum_raw(self) -> list:
        out = []

        def cb(hwnd, _):
            try:
                if not user32.IsWindowVisible(hwnd) or user32.IsIconic(hwnd):
                    return True
                cloaked = ctypes.c_int(0)
                dwmapi.DwmGetWindowAttribute(hwnd, DWMWA_CLOAKED, ctypes.byref(cloaked), ctypes.sizeof(cloaked))
                if cloaked.value != 0:
                    return True
                style = user32.GetWindowLongW(hwnd, GWL_STYLE) & 0xFFFFFFFF
                ex_style = user32.GetWindowLongW(hwnd, GWL_EXSTYLE) & 0xFFFFFFFF
                rect = self._frame_rect(hwnd)
                n = user32.GetWindowTextLengthW(hwnd)
                title = ""
                if n > 0:
                    buf = ctypes.create_unicode_buffer(n + 1)
                    user32.GetWindowTextW(hwnd, buf, n + 1)
                    title = buf.value
                cbuf = ctypes.create_unicode_buffer(256)
                user32.GetClassNameW(hwnd, cbuf, 256)
                out.append(RawWin(int(hwnd or 0), rect.left, rect.top, rect.right, rect.bottom,
                                  title, cbuf.value, style, ex_style, bool(user32.IsZoomed(hwnd))))
            except Exception:
                pass
            return True

        user32.EnumWindows(WNDENUMPROC(cb), 0)
        return out

    @staticmethod
    def _frame_rect(hwnd):
        rect = wintypes.RECT()
        res = dwmapi.DwmGetWindowAttribute(hwnd, DWMWA_EXTENDED_FRAME_BOUNDS, ctypes.byref(rect), ctypes.sizeof(rect))
        if res != 0:
            user32.GetWindowRect(hwnd, ctypes.byref(rect))
        return rect

    def window_exists(self, hwnd) -> bool:
        """Окно ещё существует (свёрнутое или скрытое существует, закрытое нет)."""
        try:
            return bool(user32.IsWindow(hwnd))
        except Exception:
            return True

    def query_rect(self, hwnd):
        """Быстрый запрос рамки одного окна (при перетаскивании не перебираем все окна)."""
        try:
            r = self._frame_rect(hwnd)
            return (r.left, r.top, r.right, r.bottom)
        except Exception:
            return None

    # --- полный экран (игра, видео): официальный вызов Windows ---
    def fullscreen_app_active(self) -> bool:
        try:
            state = ctypes.c_int(0)
            hr = ctypes.windll.shell32.SHQueryUserNotificationState(ctypes.byref(state))
            # 2 = полноэкранное приложение, 3 = полноэкранный Direct3D, 4 = режим презентации
            return hr == 0 and state.value in (2, 3, 4)
        except Exception:
            return False

    # --- события окон: переместили, показали, свернули, сменили порядок ---
    def install_hooks(self, on_event) -> bool:
        self._on_event = on_event
        try:
            user32.SetWinEventHook.restype = wintypes.HANDLE
            user32.SetWinEventHook.argtypes = [wintypes.DWORD, wintypes.DWORD, wintypes.HMODULE, WINEVENTPROC,
                                               wintypes.DWORD, wintypes.DWORD, wintypes.DWORD]
            user32.UnhookWinEvent.argtypes = [wintypes.HANDLE]
            user32.GetAncestor.restype = wintypes.HWND
            user32.GetAncestor.argtypes = [wintypes.HWND, wintypes.UINT]
            self._proc = WINEVENTPROC(self._callback)   # ссылку держим, иначе Python удалит функцию
            ranges = ((EVENT_SYSTEM_FOREGROUND, EVENT_SYSTEM_FOREGROUND),
                      (EVENT_SYSTEM_MOVESIZESTART, EVENT_SYSTEM_MOVESIZEEND),
                      (EVENT_SYSTEM_MINIMIZESTART, EVENT_SYSTEM_MINIMIZEEND),
                      (EVENT_OBJECT_DESTROY, EVENT_OBJECT_REORDER),
                      (EVENT_OBJECT_LOCATIONCHANGE, EVENT_OBJECT_LOCATIONCHANGE),
                      (EVENT_OBJECT_CLOAKED, EVENT_OBJECT_UNCLOAKED))
            for lo, hi in ranges:
                h = user32.SetWinEventHook(lo, hi, None, self._proc, 0, 0, WINEVENT_OUTOFCONTEXT)
                if h:
                    self._hooks.append(h)
            self.hooks_ok = (len(self._hooks) == len(ranges))
        except Exception:
            self.hooks_ok = False
        return self.hooks_ok

    def _callback(self, hook, event, hwnd, id_object, id_child, thread_id, time_ms):
        try:
            cb = self._on_event
            if cb is None:
                return
            if event in (EVENT_SYSTEM_FOREGROUND, EVENT_SYSTEM_MOVESIZESTART, EVENT_SYSTEM_MOVESIZEEND,
                         EVENT_SYSTEM_MINIMIZESTART, EVENT_SYSTEM_MINIMIZEEND):
                cb(event, hwnd)
                return
            if id_object != OBJID_WINDOW or id_child != 0 or not hwnd:
                return
            # интересуют только окна верхнего уровня (кнопки и поля внутри окон шлют слишком много событий)
            if self._desktop and user32.GetAncestor(hwnd, GA_PARENT) != self._desktop:
                return
            cb(event, hwnd)
        except Exception:
            pass

    def shutdown(self):
        for h in self._hooks:
            try:
                user32.UnhookWinEvent(h)
            except Exception:
                pass
        self._hooks = []
        self._proc = None
        self.hooks_ok = False


class WinRect(tuple):
    """(l, t, r, b, title, is_max), как раньше, плюс hwnd и участки верхней кромки, не закрытые другими окнами."""

    def __new__(cls, l, t, r, b, title="", is_max=False, hwnd=0, exposed=None):
        o = super().__new__(cls, (l, t, r, b, title, is_max))
        o.hwnd = hwnd
        o.exposed = exposed      # None = кромка видна целиком
        return o


def subtract_intervals(base, cuts):
    """Отрезок base=(a, b) минус отрезки cuts: список оставшихся (не закрытых) участков."""
    parts = [(base[0], base[1])]
    for c, d in cuts:
        nxt = []
        for a, b in parts:
            if d <= a or c >= b:
                nxt.append((a, b))
                continue
            if c > a:
                nxt.append((a, c))
            if d < b:
                nxt.append((d, b))
        parts = nxt
    return [(a, b) for a, b in parts if b - a > 0.5]


def win_exposed(w, x: float) -> bool:
    """Видна ли верхняя кромка окна в точке x (не закрыта окном, лежащим выше)."""
    ex = getattr(w, "exposed", None)
    if ex is None:
        return True
    for a, b in ex:
        if a <= x <= b:
            return True
    return False


class WindowTracker:
    """Список видимых окон сверху вниз (по Z) в координатах оверлея. Обновляется по событиям Windows."""

    def __init__(self, backend=None):
        self.backend = backend if backend is not None else NullBackend()
        self.windows: list = []
        self.version = 0
        self.origin = (0.0, 0.0)     # левый верх оверлея в логических пикселях
        self.dpr = 1.0               # физических пикселей на логический
        self.size = (1920, 1080)     # размер оверлея в логических пикселях
        self.fullscreen = False
        self.pinned = False          # список задан вручную (тесты): не обновляется
        self._dirty = True
        self._moved: set = set()
        self._raw: list = []
        self.closed: list = []       # окна, которые закрыли (кучи на них должны осыпаться)
        self._signature: tuple = ()
        self._last_full = -10**9
        self.poll_with_hooks = 30    # кадров: страховочный опрос при работающих событиях (~0.5 с)
        self.poll_without_hooks = 10  # кадров: если события недоступны (~0.17 с)

    # ---- настройка и события ----
    def configure(self, origin, dpr, size):
        self.origin = (float(origin[0]), float(origin[1]))
        self.dpr = float(dpr) if dpr else 1.0
        self.size = (int(size[0]), int(size[1]))
        self._dirty = True

    def install_hooks(self) -> bool:
        return self.backend.install_hooks(self.on_event)

    def shutdown(self):
        self.backend.shutdown()

    def mark_dirty(self):
        self._dirty = True

    def on_event(self, event, hwnd):
        if event == EVENT_OBJECT_LOCATIONCHANGE and hwnd:
            self._moved.add(int(hwnd))      # окно сдвинули или изменили: достаточно спросить только его рамку
        else:
            self._dirty = True              # показали, скрыли, свернули, сменили порядок: нужен полный перебор

    def set_windows(self, wins):
        """Задаёт список вручную (тесты) и больше не обновляет его."""
        self.windows = list(wins)
        self.pinned = True
        self.version += 1
        self._dirty = False

    def unpin(self):
        self.pinned = False
        self._dirty = True

    # ---- кадр ----
    def tick(self, frame: int) -> bool:
        """Вызывается каждый кадр. True, если список окон изменился."""
        if self.pinned:
            return False
        interval = self.poll_with_hooks if getattr(self.backend, "hooks_ok", False) else self.poll_without_hooks
        if (self._dirty and frame - self._last_full >= 2) or (frame - self._last_full >= interval):
            return self.refresh(frame)
        if self._moved:
            return self._refresh_moved()
        return False

    def refresh(self, frame: int = 0) -> bool:
        self._last_full = frame
        self._dirty = False
        self._moved.clear()
        try:
            self._raw = list(self.backend.enum_raw())
        except Exception:
            return False
        return self._apply(self._raw)

    def _refresh_moved(self) -> bool:
        moved, self._moved = self._moved, set()
        known = {r.hwnd: i for i, r in enumerate(self._raw)}
        for hwnd in moved:
            i = known.get(hwnd)
            if i is None:
                self._dirty = True          # неизвестное окно: нужен полный перебор
                continue
            rect = self.backend.query_rect(hwnd)
            if rect is not None:
                l, t, r, b = rect
                self._raw[i] = self._raw[i]._replace(l=l, t=t, r=r, b=b)
        return self._apply(self._raw)

    def _apply(self, raw) -> bool:
        new = self.build(raw)
        sig = tuple((w.hwnd, w[0], w[1], w[2], w[3], w[5]) for w in new)
        if sig == self._signature:
            return False
        old_ids = {w.hwnd for w in self.windows if getattr(w, "hwnd", 0)}
        self._signature = sig
        self.windows = new
        self.version += 1
        for hwnd in old_ids - {w.hwnd for w in new}:
            try:
                exists = bool(self.backend.window_exists(hwnd))
            except Exception:
                exists = True
            if not exists:
                self.closed.append(hwnd)
        return True

    def take_closed(self) -> list:
        out, self.closed = self.closed, []
        return out

    def query_fullscreen(self) -> bool:
        try:
            self.fullscreen = bool(self.backend.fullscreen_app_active())
        except Exception:
            self.fullscreen = False
        return self.fullscreen

    # ---- чистая логика: фильтры, пересчёт координат, перекрытия ----
    def build(self, raw) -> list:
        ox, oy = self.origin
        dpr = self.dpr or 1.0
        W, H = self.size
        kept = []
        for rw in raw:
            if rw.title in JUNK_TITLES or rw.cls in JUNK_CLASSES:
                continue
            # окна, прозрачные для мыши и слоёные (чужие оверлеи): через них видно, снег за ними не прячем
            if (rw.ex_style & WS_EX_TRANSPARENT) and (rw.ex_style & WS_EX_LAYERED):
                continue
            l = int(round(rw.l / dpr - ox))
            t = int(round(rw.t / dpr - oy))
            r = int(round(rw.r / dpr - ox))
            b = int(round(rw.b / dpr - oy))
            w, h = r - l, b - t
            if w < MIN_WIN_W or h < MIN_WIN_H:
                continue
            if (rw.ex_style & WS_EX_TOOLWINDOW) and (w < MIN_TOOL_W or h < MIN_TOOL_H):
                continue
            if r <= 0 or b <= 0 or l >= W or t >= H:
                continue                      # окно целиком вне нашего экрана
            covers = (l <= 8 and t <= 8 and r >= W - 8 and b >= H - 8)
            is_max = covers or (rw.zoomed and w >= 0.9 * W and h >= 0.9 * H)
            kept.append((rw.hwnd, l, t, r, b, rw.title, bool(is_max)))

        # какие участки верхней кромки окна не закрыты окнами, лежащими выше него
        out = []
        for i, (hwnd, l, t, r, b, title, is_max) in enumerate(kept):
            cuts = []
            for j in range(i):
                _, l2, t2, r2, b2, _, _ = kept[j]
                if t2 <= t + 1 <= b2 and r2 > l and l2 < r:
                    cuts.append((max(l, l2), min(r, r2)))
            exposed = subtract_intervals((l, r), cuts) if cuts else None
            out.append(WinRect(l, t, r, b, title, is_max, hwnd, exposed))
        return out



# =====================================================================
# 2. ГИБРИДНЫЙ СКАНЕР УВЕДОМЛЕНИЙ
# =====================================================================
class NotificationBridge(QObject):
    notification_received = pyqtSignal(str, str)


class HybridNotificationWatcher:
    def __init__(self, bridge: NotificationBridge):
        self.bridge = bridge
        self.running = True
        self.target_filter = "default"
        self.known_titles = {}
        self.known_popups = set()
        self.last_emit_time = 0.0
        self.last_seen_db_id = self._get_latest_db_id()

    def set_filter(self, app_filter: str):
        self.target_filter = app_filter.strip().lower()
        self.known_titles.clear()

    def _matches_target(self, proc_name: str, title: str) -> bool:
        if self.target_filter == "default":
            return False
        if self.target_filter == "max":
            # мессенджер MAX: только по имени процесса / идентификатору приложения и только слово «max» целиком
            return re.search(r"(?<![a-z0-9])max(?![a-z0-9])", str(proc_name).lower()) is not None
        haystack = f"{proc_name} {title}".lower()
        if self.target_filter == "browser":
            return any(b in haystack for b in ("brave", "chrome", "msedge", "firefox", "opera", "yandex"))
        if self.target_filter == "claude":
            return any(c in haystack for c in ("claude", "brave", "chrome", "msedge", "firefox"))
        return self.target_filter in haystack

    def _emit_safe(self, app_label: str, message: str):
        now = time.time()
        if now - self.last_emit_time < 1.8:
            return
        self.last_emit_time = now
        self.bridge.notification_received.emit(app_label, message)

    def start(self):
        t = threading.Thread(target=self._loop, daemon=True)
        t.start()

    def _loop(self):
        n = 0
        while self.running:
            try:
                if self.target_filter != "default":
                    self._scan_windows_and_popups()
                    if n % 3 == 0:                 # база уведомлений Windows копируется и читается реже: это самая тяжёлая часть
                        self._scan_wpn_database()
            except Exception:
                pass
            n += 1
            time.sleep(0.7)

    def _scan_windows_and_popups(self):
        current_hwnds = set()

        def enum_cb(hwnd, _):
            if not user32.IsWindowVisible(hwnd):
                return True

            proc = get_process_name(hwnd)
            length = user32.GetWindowTextLengthW(hwnd)
            buf = ctypes.create_unicode_buffer(length + 1) if length > 0 else None
            if buf:
                user32.GetWindowTextW(hwnd, buf, length + 1)
            title = buf.value if buf else ""

            if title in ("BlackCatOverlay", "DesktopSnowOverlay", LAUNCHER_TITLE, LAUNCHER_TITLE_EN, "Program Manager"):
                return True

            rect = wintypes.RECT()
            user32.GetWindowRect(hwnd, ctypes.byref(rect))
            w = rect.right - rect.left
            h = rect.bottom - rect.top

            ex_style = user32.GetWindowLongW(hwnd, GWL_EXSTYLE)
            is_popup = bool(ex_style & WS_EX_TOPMOST) and (140 <= w <= 550) and (40 <= h <= 280)

            if is_popup and self._matches_target(proc, title):
                if hwnd not in self.known_popups:
                    self.known_popups.add(hwnd)
                    pretty = self._pretty_name(proc, title)
                    msg = title if title and title.lower() != pretty.lower() else tr("Новое сообщение! 💬")
                    self._emit_safe(pretty, msg[:44])
                current_hwnds.add(hwnd)
                return True

            if title and self._matches_target(proc, title):
                old_title = self.known_titles.get(hwnd)
                self.known_titles[hwnd] = title

                if old_title and old_title != title:
                    old_badge = re.search(r"[\(\[](\d+)[\)\]]", old_title)
                    new_badge = re.search(r"[\(\[](\d+)[\)\]]", title)

                    if new_badge:
                        new_cnt = int(new_badge.group(1))
                        old_cnt = int(old_badge.group(1)) if old_badge else 0
                        if new_cnt > old_cnt:
                            pretty = self._pretty_name(proc, title)
                            clean_t = re.sub(r"[\(\[]\d+[\)\]]\s*", "", title)
                            self._emit_safe(pretty, tr('Новых: {0} ({1})').format(new_cnt, clean_t[:30]))
                    elif "telegram" in proc and title != "Telegram":
                        self._emit_safe("Telegram", f"{title[:42]}")
                    elif self.target_filter == "claude" and "claude" in title.lower():
                        self._emit_safe("Claude", f"{title[:42]}")

            return True

        user32.EnumWindows(WNDENUMPROC(enum_cb), 0)
        self.known_popups.intersection_update(current_hwnds)

    def _pretty_name(self, proc: str, title: str) -> str:
        low = f"{proc} {title}".lower()
        if self.target_filter == "max" and re.search(r"(?<![a-z0-9])max(?![a-z0-9])", str(proc).lower()):
            return "MAX"
        if "telegram" in low:
            return "Telegram"
        if "claude" in low:
            return "Claude"
        if "brave" in low:
            return "Brave"
        if "chrome" in low:
            return "Chrome"
        if "discord" in low:
            return "Discord"
        return proc.replace(".exe", "").capitalize() or tr("Уведомление")

    def _db_dir(self) -> str:
        return os.path.join(os.environ.get("LOCALAPPDATA", ""), "Microsoft", "Windows", "Notifications")

    def _query_wpn(self, sql: str):
        base_dir = self._db_dir()
        src_db = os.path.join(base_dir, "wpndatabase.db")
        if not os.path.exists(src_db):
            return []

        tmp_dir = tempfile.mkdtemp(prefix="cat_wpn_")
        try:
            for ext in ("", "-wal", "-shm"):
                s = src_db + ext
                if os.path.exists(s):
                    shutil.copy2(s, os.path.join(tmp_dir, "wpndatabase.db" + ext))

            conn = sqlite3.connect(os.path.join(tmp_dir, "wpndatabase.db"))
            cur = conn.cursor()
            cur.execute(sql)
            rows = cur.fetchall()
            conn.close()
            return rows
        except Exception:
            return []
        finally:
            shutil.rmtree(tmp_dir, ignore_errors=True)

    def _get_latest_db_id(self) -> int:
        rows = self._query_wpn("SELECT MAX(Id) FROM Notification;")
        if rows and rows[0][0] is not None:
            return int(rows[0][0])
        return 0

    def _scan_wpn_database(self):
        sql = f"""
            SELECT n.Id, h.PrimaryId, n.Payload
            FROM Notification n
            LEFT JOIN NotificationHandler h ON n.HandlerId = h.RecordId
            WHERE n.Id > {self.last_seen_db_id}
            ORDER BY n.Id ASC;
        """
        rows = self._query_wpn(sql)
        for row_id, primary_id, payload in rows:
            self.last_seen_db_id = max(self.last_seen_db_id, int(row_id))
            app_id = str(primary_id or "")
            raw = payload.decode("utf-8", errors="ignore") if isinstance(payload, bytes) else str(payload or "")
            if self._matches_target(app_id, raw):
                texts = re.findall(r"<text[^>]*>(.*?)</text>", raw, flags=re.DOTALL)
                cleaned = " — ".join([t.strip() for t in texts if t.strip()]) or tr("Новое уведомление!")
                self._emit_safe(self._pretty_name(app_id, raw), cleaned[:44])


# =====================================================================
# 3. ВСТРОЕННЫЙ ДВИЖОК СНЕГА И ГЛАДКИХ СУГРОБОВ (БЕЗ ЧЁРНОЙ ОБВОДКИ!)
# =====================================================================
# ---- нагрузка на компьютер (этап 6) ----
# Физика всегда считается 60 раз в секунду (иначе поменялась бы скорость котов); меняется только то, как часто слой
# перерисовывается и сколько снежинок. Делитель 2 = рисуем каждый 2-й кадр = 30 к/с.
QUALITY_LEVELS = ("high", "medium", "low", "eco")
QUALITY = {
    "high":   {"label": "Красиво",          "flakes": 160, "splash_cap": 230, "relax": 3, "render_active": 1, "render_calm": 1, "render_still": 4},
    "medium": {"label": "Сбалансированно",  "flakes": 110, "splash_cap": 160, "relax": 3, "render_active": 1, "render_calm": 2, "render_still": 6},
    "low":    {"label": "Легче для ПК",     "flakes": 70,  "splash_cap": 110, "relax": 6, "render_active": 2, "render_calm": 3, "render_still": 8},
    "eco":    {"label": "Очень лёгкий",     "flakes": 40,  "splash_cap": 70,  "relax": 9, "render_active": 2, "render_calm": 4, "render_still": 10},
}
PERF_MODES = {"auto": "Авто (рекомендуется)", "high": "Красиво", "medium": "Сбалансированно", "low": "Легче для ПК", "eco": "Очень лёгкий"}
AUTO_WINDOW_TICKS = 300       # кадров между оценками (~5 с)
AUTO_DOWN_CPU = 5.0           # % всего процессора (как в Диспетчере задач) выше этого два раза подряд: снижаем качество
AUTO_UP_CPU = 2.0             # ниже этого три раза подряд (и не раньше, чем через 10 с): поднимаем качество
AUTO_FLOOR = "low"            # автоматически ниже «Легче для ПК» не опускаемся («Очень лёгкий» только вручную)


class PerfGovernor:
    """Следит за реальной загрузкой процессора программой и выбирает уровень качества (в режиме «Авто» меняет его сам)."""

    def __init__(self, cpu_clock=time.process_time, wall_clock=time.perf_counter, ncpu=None):
        self.mode = "auto"
        self.level = "high"
        self.avg_phys = 0.0      # мс на кадр: логика
        self.avg_paint = 0.0     # мс на кадр: рисование
        self.avg_late = 0.0      # мс на кадр: насколько запаздывает таймер
        self.cpu_pct = 0.0       # % всего процессора, который занимает программа (как в Диспетчере задач)
        self.render_fps = 0.0
        self.measured = False
        self._cpu_clock = cpu_clock
        self._wall_clock = wall_clock
        self.ncpu = max(1, int(ncpu or os.cpu_count() or 1))
        self._down_votes = 0
        self._up_votes = 0
        self._since_change = 99
        self.reset_window()

    def reset_window(self):
        """Начинает окно измерения заново (после паузы, чтобы простой не считался лёгкой нагрузкой)."""
        self._ticks = 0
        self._phys = self._paint = self._late = 0.0
        self._paints = 0
        self._cpu0 = self._cpu_clock()
        self._wall0 = self._wall_clock()

    @property
    def params(self) -> dict:
        return QUALITY[self.level]

    def set_mode(self, mode: str):
        self.mode = mode if mode in PERF_MODES else "auto"
        if self.mode != "auto":
            self.level = self.mode
        self._down_votes = self._up_votes = 0

    def render_divisor(self, activity: str) -> int:
        return self.params["render_" + activity]

    def record_tick(self, phys_s: float, paint_s: float, late_s: float, painted: bool) -> bool:
        """Учитывает один кадр. True, если уровень качества изменился."""
        self._ticks += 1
        self._phys += phys_s
        self._paint += paint_s
        self._late += late_s
        self._paints += 1 if painted else 0
        if self._ticks < AUTO_WINDOW_TICKS:
            return False
        n = float(self._ticks)
        wall = max(self._wall_clock() - self._wall0, 1e-6)
        cpu = max(0.0, self._cpu_clock() - self._cpu0)
        self.cpu_pct = cpu / wall / self.ncpu * 100.0
        self.avg_phys, self.avg_paint, self.avg_late = self._phys / n * 1000.0, self._paint / n * 1000.0, self._late / n * 1000.0
        self.render_fps = self._paints / wall
        self.measured = True
        self.reset_window()
        return self._evaluate()

    @property
    def cost_ms(self) -> float:
        return self.avg_phys + self.avg_paint + self.avg_late

    def _evaluate(self) -> bool:
        if self.mode != "auto":
            return False
        self._since_change += 1
        cpu = self.cpu_pct
        idx = QUALITY_LEVELS.index(self.level)
        floor_idx = QUALITY_LEVELS.index(AUTO_FLOOR)
        if cpu > AUTO_DOWN_CPU:
            self._up_votes = 0
            self._down_votes += 1
            if self._down_votes >= 2 and idx < floor_idx:
                self.level = QUALITY_LEVELS[idx + 1]
                self._down_votes = 0
                self._since_change = 0
                return True
        elif cpu < AUTO_UP_CPU and idx > 0:
            self._down_votes = 0
            self._up_votes += 1
            if self._up_votes >= 3 and self._since_change >= 2:
                self.level = QUALITY_LEVELS[idx - 1]
                self._up_votes = 0
                self._since_change = 0
                return True
        else:
            self._down_votes = self._up_votes = 0
        return False


class SnowFlake:
    __slots__ = ("x", "y", "vx", "vy", "size", "phase", "splash")

    def __init__(self, x: float, y: float, size: float, splash: bool = False):
        self.x = x
        self.y = y
        self.vx = 0.0
        self.vy = random.uniform(1.1, 2.2)
        self.size = size
        self.phase = random.uniform(0.0, 6.28)
        self.splash = splash


class SmoothSnowEngine:
    """
    Полностью встроенный в PyQt6 генератор снега:
    - Никакой чёрной обводки (чистый альфа-канал Qt)
    - Сугробы рисуются плавной сплошной кривой Безье (никаких острых гор!)
    - Снег не рисуется внутри открытых окон
    - Прямое взаимодействие с лапами кота без файловых задержек
    """
    STEP = 8  # Шаг сетки сугроба для идеально гладких холмов

    def __init__(self, width: int, height: int):
        self.w = width
        self.h = height
        self.enabled = True
        self.grid_len = (width // self.STEP) + 2
        self.floor_drift = [0.0] * self.grid_len
        self.max_flakes = 160     # сколько обычных снежинок падает одновременно (меняется режимом нагрузки)
        self.splash_cap = 230     # потолок вместе с брызгами из-под лап
        self.relax_every = 3      # как часто сглаживаются сугробы (в кадрах)
        self._clip_sig = None     # кэш области вырезания окон
        self._clip_region = None
        self.win_drifts = {}  # ключ окна (hwnd) -> [float]
        self._win_seen = {}   # ключ окна -> кадр, когда его видели в последний раз
        self._win_rect = {}   # ключ окна -> (левый край, верх, правый край) в последний раз

        self.flakes = [
            SnowFlake(random.uniform(0, width), random.uniform(0, height), random.uniform(2.8, 5.5))
            for _ in range(160)
        ]

    def clear_drifts(self):
        self.floor_drift = [0.0] * self.grid_len
        self.win_drifts.clear()

    # ---- кучи на окнах: ключ = идентификатор окна, поэтому куча едет вместе с окном ----
    @staticmethod
    def wkey(w):
        h = getattr(w, "hwnd", 0)
        return h if h else (w[1], w[0], w[2])     # запасной ключ для окон без идентификатора

    @staticmethod
    def _resample(arr: list[float], n: int) -> list[float]:
        if n <= 1 or len(arr) < 2:
            return [0.0] * max(n, 0)
        out = []
        scale = (len(arr) - 1) / float(n - 1)
        for i in range(n):
            x = i * scale
            j = int(x)
            fr = x - j
            nxt = arr[min(j + 1, len(arr) - 1)]
            out.append(arr[j] * (1.0 - fr) + nxt * fr)
        return out

    def _win_arr(self, w, create: bool = False):
        """Массив кучи окна (подгоняется под текущую ширину окна, если окно растянули)."""
        key = self.wkey(w)
        w_len = ((w[2] - w[0]) // self.STEP) + 2
        arr = self.win_drifts.get(key)
        if arr is None:
            if not create:
                return None
            arr = self.win_drifts[key] = [0.0] * w_len
        elif len(arr) != w_len:
            arr = self.win_drifts[key] = self._resample(arr, w_len)
        return arr

    def _track_windows(self, windows, frame_idx: int):
        """Помнит, когда окно видели в последний раз; кучи пропавших окон удаляются через ~минуту."""
        for w in windows:
            k = self.wkey(w)
            self._win_seen[k] = frame_idx
            self._win_rect[k] = (w[0], w[1], w[2])
        if frame_idx % 120 == 0:
            for k in list(self.win_drifts):
                last = self._win_seen.get(k)
                if last is None:
                    self._win_seen[k] = frame_idx
                elif frame_idx - last > PILE_KEEP_FRAMES:
                    self.collapse_pile(k)      # окно так и не вернулось: снег осыпается вниз

    def collapse_piles(self, keys):
        for k in keys:
            self.collapse_pile(k)

    def collapse_pile(self, key):
        """Куча осталась без окна (его закрыли): превращается в падающие снежинки, которые ложатся ниже (на пол или другие окна)."""
        arr = self.win_drifts.pop(key, None)
        rect = self._win_rect.pop(key, None)
        self._win_seen.pop(key, None)
        if arr is None or rect is None or not self.enabled:
            return
        wl, wt, wr = rect
        cells = [(i, h) for i, h in enumerate(arr) if h > 0.6]
        if not cells:
            return
        n = max(4, min(70, int(sum(h for _, h in cells) / 0.55)))      # одна севшая снежинка добавляет ~0.55
        n = min(n, max(0, self.splash_cap + 30 - len(self.flakes)))
        weights = [h for _, h in cells]
        for _ in range(n):
            i, h = random.choices(cells, weights=weights)[0]
            f = SnowFlake(wl + i * self.STEP + random.uniform(-4.0, 4.0), wt + 2 - h * random.uniform(0.2, 1.0),
                          random.uniform(2.8, 4.6), splash=True)
            f.vx = random.uniform(-0.8, 0.8)
            f.vy = random.uniform(0.3, 1.4)
            self.flakes.append(f)

    def _masked(self, arr: list[float], w) -> list[float]:
        """Куча без тех участков, где кромку окна закрыло другое окно."""
        if getattr(w, "exposed", None) is None:
            return arr
        return [h if win_exposed(w, w[0] + i * self.STEP) else 0.0 for i, h in enumerate(arr)]

    def set_quality(self, flakes: int, splash_cap: int, relax_every: int):
        """Режим нагрузки: сколько снежинок и как часто сглаживать сугробы. Лишние снежинки убираются сразу, недостающие добавляются сверху."""
        self.max_flakes, self.splash_cap, self.relax_every = int(flakes), int(splash_cap), max(1, int(relax_every))
        regular = [f for f in self.flakes if not f.splash]
        extra = len(regular) - self.max_flakes
        if extra > 0:
            drop = set(id(f) for f in regular[self.max_flakes:])
            self.flakes = [f for f in self.flakes if id(f) not in drop]
        else:
            for _ in range(-extra):
                f = SnowFlake(random.uniform(0, self.w), random.uniform(-60, 0), random.uniform(2.8, 5.5))
                f.vy = random.uniform(1.1, 2.2)
                self.flakes.append(f)

    def resize(self, width: int, height: int):
        """Экран изменился (разрешение, панель задач): подгоняем размеры без потери сугробов."""
        self.w, self.h = int(width), int(height)
        self.grid_len = (self.w // self.STEP) + 2
        arr = self.floor_drift
        if len(arr) < self.grid_len:
            arr = arr + [0.0] * (self.grid_len - len(arr))
        self.floor_drift = arr[: self.grid_len]
        for f in self.flakes:
            if self.w > 0:
                f.x = f.x % self.w

    def _add_smooth_snow(self, arr: list[float], center_idx: int, amount: float, max_h: float):
        # Распределяем упавшую снежинку широким колоколом на 9 соседних точек — сугроб всегда плоский и круглый!
        radius = 4
        n = len(arr)
        for d in range(-radius, radius + 1):
            idx = center_idx + d
            if 0 <= idx < n:
                w = math.cos((d / (radius + 1)) * (math.pi * 0.5)) ** 2
                arr[idx] = min(max_h, arr[idx] + amount * w)

    def _relax_array(self, arr: list[float]):
        # Физика осыпания: убирает любые неровности и делает сугробы мягкими волнами
        n = len(arr)
        if n < 3:
            return
        for i in range(1, n - 1):
            arr[i] = (arr[i - 1] + arr[i] * 2.0 + arr[i + 1]) * 0.25

    def interact_with_cat(self, cx: float, cy: float, cvx: float, cvy: float, windows):
        if not self.enabled:
            return
        moving = abs(cvx) > 0.4 or abs(cvy) > 1.2
        idx = int(cx // self.STEP)

        # 1. Кот бежит по сугробу на панели задач
        if abs(cy - self.h) <= 22:
            for i in range(max(1, idx - 3), min(self.grid_len - 1, idx + 4)):
                if self.floor_drift[i] > 1.5:
                    kicked = self.floor_drift[i] * (0.45 if moving else 0.12)
                    self.floor_drift[i] -= kicked
                    if moving and len(self.flakes) < self.splash_cap and random.random() < 0.45:
                        sf = SnowFlake(i * self.STEP, self.h - 5, random.uniform(2.8, 4.5), splash=True)
                        sf.vx = cvx * 0.5 + random.uniform(-2.2, 2.2)
                        sf.vy = random.uniform(-4.2, -1.8)
                        self.flakes.append(sf)

        # 2. Кот бежит по сугробу на шапке окна
        for w in windows:
            wl, wt, wr, wb, _, is_max = w
            if is_max:
                continue
            arr = self._win_arr(w)
            if arr is not None and abs(cy - wt) <= 22 and wl <= cx <= wr:
                l_idx = int((cx - wl) // self.STEP)
                for i in range(max(1, l_idx - 3), min(len(arr) - 1, l_idx + 4)):
                    if arr[i] > 1.5:
                        kicked = arr[i] * (0.45 if moving else 0.12)
                        arr[i] -= kicked
                        if moving and len(self.flakes) < self.splash_cap and random.random() < 0.45:
                            sf = SnowFlake(wl + i * self.STEP, wt - 4, random.uniform(2.8, 4.2), splash=True)
                            sf.vx = cvx * 0.5 + random.uniform(-2.2, 2.2)
                            sf.vy = random.uniform(-4.2, -1.8)
                            self.flakes.append(sf)

    def surface_at(self, x: float, surface_y: float, windows):
        """Поверхность, на которой стоит кот: (массив сугроба, x начала, y основания, мин. x, макс. x) или None."""
        if surface_y >= self.h - 10:
            return self.floor_drift, 0.0, float(self.h), 35.0, float(self.w - 35)
        for w in windows:
            wl, wt, wr, wb, _, is_max = w
            if not is_max and abs(wt - surface_y) <= 3 and wl <= x <= wr and win_exposed(w, x):
                arr = self._win_arr(w)
                if arr is not None:
                    return arr, float(wl), float(wt + 2), wl + 26.0, wr - 26.0
        return None

    def find_big_pile(self, arr: list[float], base_x: float, from_x: float, reach: float, lo_x: float, hi_x: float):
        """Лучшая БОЛЬШАЯ куча в пределах reach: (x вершины, высота) или None. Маленькие кучки игнорируются."""
        n = len(arr)
        if n < 5:
            return None
        lo = max(1, int((max(from_x - reach, lo_x) - base_x) // self.STEP))
        hi = min(n - 2, int((min(from_x + reach, hi_x) - base_x) // self.STEP))
        best = None
        best_score = -1e9
        for i in range(lo, hi + 1):
            h = arr[i]
            if h < BIG_PILE_MIN_H or h < arr[i - 1] or h < arr[i + 1]:
                continue
            half = h * 0.5
            l = i
            while l > 0 and arr[l - 1] >= half:
                l -= 1
            r = i
            while r < n - 1 and arr[r + 1] >= half:
                r += 1
            if (r - l + 1) < BIG_PILE_MIN_W:
                continue
            px = base_x + i * self.STEP
            score = h - 0.03 * abs(px - from_x)   # побольше важнее, но чем ближе, тем лучше
            if score > best_score:
                best_score = score
                best = (px, h)
        return best

    def add_mound(self, arr: list[float], base_x: float, x: float, height: float):
        """Насыпает демонстрационную кучу (для кнопки показа прыжка)."""
        i = int((x - base_x) // self.STEP)
        for k in range(max(1, i - 6), min(len(arr) - 1, i + 7)):
            w = math.cos((abs(k - i) / 7.0) * math.pi * 0.5) ** 2
            arr[k] = max(arr[k], height * w)

    def plunge(self, arr: list[float], base_x: float, base_y: float, x: float) -> float:
        """Кот приземлился в сугроб: вмятина и фонтан снега. Возвращает высоту сугроба в точке падения."""
        n = len(arr)
        i = max(1, min(n - 2, int((x - base_x) // self.STEP)))
        h = max(arr[max(0, i - 2): min(n, i + 3)])
        if h < BIG_PILE_MIN_H * 0.8:
            return h
        for k in range(max(1, i - 5), min(n - 1, i + 6)):
            w = math.cos((abs(k - i) / 6.0) * math.pi * 0.5) ** 2
            arr[k] *= (1.0 - 0.55 * w)
        for _ in range(min(28, 8 + int(h))):
            if len(self.flakes) >= self.splash_cap + 30:
                break
            sf = SnowFlake(x + random.uniform(-14.0, 14.0), base_y - h * 0.8, random.uniform(2.8, 4.6), splash=True)
            sf.vx = random.uniform(-3.6, 3.6)
            sf.vy = random.uniform(-7.0, -2.5)
            self.flakes.append(sf)
        return h

    def step(self, cursor: QPointF, mouse_vx: float, mouse_vy: float, windows, frame_idx: int):
        self._track_windows(windows, frame_idx)
        if not self.enabled:
            return

        has_maximized = any(w[5] for w in windows)
        land = [(w, w[1], w[0] + 10, w[2] - 10) for w in windows if not w[5] and w[1] > 30]
        if has_maximized:
            return

        mx, my = cursor.x(), cursor.y()

        for i in range(len(self.flakes) - 1, -1, -1):
            f = self.flakes[i]

            # Вихрь от курсора мыши
            dx = f.x - mx
            dy = f.y - my
            dist_sq = dx * dx + dy * dy
            if 4.0 < dist_sq < 5600.0:
                dist = math.sqrt(dist_sq)
                force = (75.0 - dist) / 75.0
                f.vx += (mouse_vx * 0.14 + (dx / dist) * 0.55) * force
                f.vy += (mouse_vy * 0.14 + (dy / dist) * 0.55) * force

            f.vx *= 0.95
            if f.splash:
                f.vy += 0.22  # Гравитация для подброшенных лапами снежинок
            else:
                # Плавное падение строго вниз без полётов вверх!
                f.vy = min(2.4, max(0.8, f.vy + 0.05))

            sway = math.sin(frame_idx * 0.03 + f.phase) * 0.35 if not f.splash else 0.0
            f.x += f.vx + sway
            f.y += f.vy

            if f.x < 0:
                f.x += self.w
            elif f.x >= self.w:
                f.x -= self.w

            landed = False
            if f.vy > 0:
                # Посадка на верхние рамки открытых окон (сначала дешёвая проверка высоты: куча не выше 24 px)
                fy = f.y
                for (w, wt, xl, xr) in land:
                    if wt - 40 <= fy <= wt + 8 and xl <= f.x <= xr and win_exposed(w, f.x):
                        # снег ложится только на видимую часть кромки (не на ту, что закрыта другим окном)
                        arr = self._win_arr(w, create=True)
                        w_len = len(arr)
                        l_idx = max(0, min(w_len - 1, int((f.x - w[0]) // self.STEP)))
                        if (wt - arr[l_idx] - 2) <= fy <= (wt + 8):
                            self._add_smooth_snow(arr, l_idx, 0.45, 16.0)
                            landed = True
                            break

                # Посадка на панель задач внизу экрана
                g_idx = max(0, min(self.grid_len - 1, int(f.x // self.STEP)))
                if not landed and f.y >= (self.h - self.floor_drift[g_idx]):
                    self._add_smooth_snow(self.floor_drift, g_idx, 0.55, 24.0)
                    landed = True

            if landed or f.y > self.h + 15:
                if f.splash or len(self.flakes) > self.max_flakes:
                    self.flakes.pop(i)
                    continue
                f.x = random.uniform(0, self.w)
                f.y = random.uniform(-60, -10)
                f.vx = 0.0
                f.vy = random.uniform(1.1, 2.2)

        if frame_idx % self.relax_every == 0:
            self._relax_array(self.floor_drift)
            for arr in self.win_drifts.values():
                self._relax_array(arr)

    def _draw_smooth_drift_polygon(self, painter: QPainter, arr: list[float], start_x: float, base_y: float):
        """Рисует сугроб единой гладкой волной без ступенек и острых углов."""
        if not any(h > 0.6 for h in arr):
            return
        path = QPainterPath()
        path.moveTo(start_x, base_y + 2)
        for i, h in enumerate(arr):
            px = start_x + i * self.STEP
            py = base_y - h
            if i == 0:
                path.lineTo(px, py)
            else:
                prev_x = start_x + (i - 1) * self.STEP
                prev_y = base_y - arr[i - 1]
                mid_x = (prev_x + px) * 0.5
                mid_y = (prev_y + py) * 0.5
                path.quadTo(prev_x, prev_y, mid_x, mid_y)
        path.lineTo(start_x + (len(arr) - 1) * self.STEP, base_y + 2)
        path.closeSubpath()

        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(246, 250, 255, 235))
        painter.drawPath(path)

    def draw(self, painter: QPainter, windows):
        if not self.enabled or any(w[5] for w in windows):
            return

        painter.save()

        # Вырезаем внутреннюю область всех открытых окон, чтобы снег шёл ТОЛЬКО снаружи окон!
        # (область строится только когда окна сдвинулись: раньше она пересчитывалась в каждом кадре)
        sig = (self.w, self.h, tuple((w[0], w[1], w[2], w[3]) for w in windows))
        if sig != self._clip_sig or self._clip_region is None:
            clip_region = QRegion(0, 0, self.w, self.h)
            for (wl, wt, wr, wb, _, _) in windows:
                win_interior = QRegion(wl + 1, wt + 2, max(1, wr - wl - 2), max(1, wb - wt - 2))
                clip_region = clip_region.subtracted(win_interior)
            self._clip_sig, self._clip_region = sig, clip_region
        painter.setClipRegion(self._clip_region)

        # 1. Отрисовка чистых белых снежинок без обводки
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(255, 255, 255, 225))
        for f in self.flakes:
            if f.y >= 0:
                r = f.size * 0.5
                painter.drawEllipse(QPointF(f.x, f.y), r, r)

        # 2. Отрисовка гладких сугробов на панели задач и на крышах окон
        self._draw_smooth_drift_polygon(painter, self.floor_drift, 0.0, float(self.h))
        for w in windows:
            if not w[5]:
                arr = self._win_arr(w)
                if arr is not None:
                    self._draw_smooth_drift_polygon(painter, self._masked(arr, w), float(w[0]), float(w[1] + 2))

        painter.restore()


# =====================================================================
# 4. ОВЕРЛЕЙ КОТА + СНЕГА (ЕДИНЫЕ 60 FPS БЕЗ НАГРУЗКИ)
# =====================================================================
CAT_PATTERNS = {
    "none": "Без узора",
    "stripes": "Полоски",
    "spots": "Пятнышки",
    "socks": "Белые носочки",
    "tuxedo": "Смокинг",
}


def _mix(c: QColor, k: float, a: int | None = None) -> QColor:
    """k > 1 осветляет цвет (к белому), k < 1 затемняет."""
    if k >= 1.0:
        t = min(1.0, k - 1.0)
        r, g, b = (c.red() + (255 - c.red()) * t, c.green() + (255 - c.green()) * t, c.blue() + (255 - c.blue()) * t)
    else:
        r, g, b = c.red() * k, c.green() * k, c.blue() * k
    return QColor(int(r), int(g), int(b), c.alpha() if a is None else a)


def _lum(c: QColor) -> float:
    return 0.299 * c.red() + 0.587 * c.green() + 0.114 * c.blue()


def _stroke(p, a, b, w, color):
    p.setPen(QPen(color, w, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
    p.drawLine(QPointF(a[0], a[1]), QPointF(b[0], b[1]))


def _blob(p, cx, cy, rx, ry, color):
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(color)
    p.drawEllipse(QPointF(cx, cy), rx, ry)


def _leg(p, joint, paw, color, w_top, w_bot, sock=None):
    mx, my = joint[0] * 0.42 + paw[0] * 0.58, joint[1] * 0.42 + paw[1] * 0.58
    _stroke(p, joint, (mx, my), w_top, color)
    _stroke(p, (mx, my), paw, w_bot, color)
    _blob(p, paw[0], paw[1] + 0.6, w_bot * 0.72, w_bot * 0.5, color)
    if sock is not None:   # «носочек»: нижняя часть лапки другого цвета
        sx, sy = (mx + paw[0]) * 0.5, (my + paw[1]) * 0.5
        _stroke(p, (sx, sy), paw, w_bot, sock)
        _blob(p, paw[0], paw[1] + 0.6, w_bot * 0.72, w_bot * 0.5, sock)


def paint_cat_body(p, n, pal, facing=1, sleeping=False, happy=False, laser=False, ground_y=None):
    """Рисует кота по 11 узлам скелета n (n[i].x, n[i].y). Используется и на экране, и в предпросмотре мастерской."""
    body = pal["body"]
    belly = pal.get("belly", _mix(body, 1.3))
    limb = pal.get("limb", _mix(body, 0.85))
    ear_in, eye, nose = pal["ear_inner"], pal["eye"], pal["nose"]
    tail_tip = pal.get("tail_tip", body)
    pat = pal.get("pattern", "none")
    patc = pal.get("pattern_color", QColor(70, 48, 36))
    dark = _lum(body) < 80
    rim = QColor(255, 255, 255, 30) if dark else QColor(0, 0, 0, 55)
    sheen = _mix(body, 1.35, 110)
    whisker = QColor(255, 255, 255, 170) if dark else QColor(70, 70, 80, 150)

    C = (n[1].x, n[1].y)
    Pv = (n[2].x, n[2].y)
    H = (n[0].x, n[0].y)
    ax, ay = C[0] - Pv[0], C[1] - Pv[1]
    L = math.hypot(ax, ay) or 1.0
    ux, uy = ax / L, ay / L
    nx, ny = -uy, ux
    if ny < 0:
        nx, ny = -nx, -ny

    def on_body(t, off):
        return (Pv[0] + ux * L * t + nx * off, Pv[1] + uy * L * t + ny * off)

    # 1. тень на земле
    if ground_y is not None:
        _blob(p, (C[0] + Pv[0]) * 0.5, ground_y + 1.0, 27.0, 3.6, QColor(0, 0, 0, 55))

    # 2. дальние лапы (темнее, чтобы был объём)
    far = _mix(limb, 0.8)
    sock = patc if pat == "socks" else None
    _leg(p, (n[1].x, n[1].y), (n[3].x, n[3].y), far, 8.5, 7.0, sock)
    _leg(p, (n[2].x, n[2].y), (n[5].x, n[5].y), far, 10.5, 7.0, sock)

    # 3. хвост: сужается к кончику, кончик может быть другого цвета
    pts = []
    for i in range(13):
        t = i / 12.0
        pts.append(((1 - t) ** 2 * Pv[0] + 2 * (1 - t) * t * n[7].x + t * t * n[8].x,
                    (1 - t) ** 2 * Pv[1] + 2 * (1 - t) * t * n[7].y + t * t * n[8].y))
    for i in range(12):
        _stroke(p, pts[i], pts[i + 1], 8.2 - 3.6 * (i / 11.0), tail_tip if i >= 9 else body)

    # 4. туловище: обводка, шерсть, светлое брюшко, блик на спинке, бедро
    _stroke(p, C, Pv, 25.0, rim)
    _stroke(p, C, Pv, 23.0, body)
    _stroke(p, on_body(1.0, 5.2), on_body(0.0, 5.2), 11.0, belly)
    _stroke(p, on_body(0.9, -6.2), on_body(0.1, -6.2), 4.5, sheen)
    _blob(p, Pv[0] - ux * 1.0, Pv[1] - uy * 1.0, 10.5, 11.0, _mix(body, 1.07))

    if pat == "stripes":
        for t in (0.10, 0.27, 0.44, 0.61, 0.78):
            _stroke(p, on_body(t, -10.5), on_body(t + 0.03, -1.0), 2.6, QColor(patc.red(), patc.green(), patc.blue(), 200))
    elif pat == "spots":
        for t, off, r in ((0.16, -5.5, 3.0), (0.33, 3.5, 2.4), (0.50, -4.0, 3.3), (0.68, 3.0, 2.6), (0.85, -6.0, 2.3)):
            q = on_body(t, off)
            _blob(p, q[0], q[1], r, r * 0.9, patc)
    elif pat == "tuxedo":
        q = on_body(0.97, 5.5)
        _blob(p, q[0], q[1], 6.0, 7.5, patc)

    # 5. ближние лапы
    _leg(p, (n[1].x, n[1].y), (n[4].x, n[4].y), limb, 8.8, 7.4, sock)
    _leg(p, (n[2].x, n[2].y), (n[6].x, n[6].y), limb, 10.8, 7.4, sock)

    # 6. шея
    _stroke(p, C, H, 15.0, body)

    # 7. ушки: наружное, внутреннее, обводка
    hx, hy = H
    p.setPen(QPen(rim, 1.2))
    p.setBrush(body)
    t1 = (n[9].x - 2.0, n[9].y - 9.0)
    t2 = (n[10].x + 2.0, n[10].y - 9.0)
    p.drawPolygon(QPolygonF([QPointF(hx - 13.5, hy - 2), QPointF(t1[0], t1[1]), QPointF(hx - 1.5, hy - 11)]))
    p.drawPolygon(QPolygonF([QPointF(hx + 1.5, hy - 11), QPointF(t2[0], t2[1]), QPointF(hx + 13.5, hy - 2)]))
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(ear_in)
    p.drawPolygon(QPolygonF([QPointF(hx - 10, hy - 5), QPointF(t1[0] * 0.72 + (hx - 6.5) * 0.28, t1[1] * 0.72 + (hy - 9) * 0.28), QPointF(hx - 3.5, hy - 9.5)]))
    p.drawPolygon(QPolygonF([QPointF(hx + 3.5, hy - 9.5), QPointF(t2[0] * 0.72 + (hx + 6.5) * 0.28, t2[1] * 0.72 + (hy - 9) * 0.28), QPointF(hx + 10, hy - 5)]))

    # 8. голова: обводка, пухлые щёчки, мордочка
    eo = facing * 3.0
    _blob(p, hx, hy, 16.2, 14.6, rim)
    _blob(p, hx, hy, 15.0, 13.5, body)
    _blob(p, hx - 9.5, hy + 5.0, 6.8, 5.4, _mix(body, 1.06))
    _blob(p, hx + 9.5, hy + 5.0, 6.8, 5.4, _mix(body, 1.06))
    _blob(p, hx + eo * 0.6, hy + 6.2, 7.4, 5.0, patc if pat == "tuxedo" else belly)
    if pat == "stripes":
        for dx in (-4.5, 0.0, 4.5):
            _stroke(p, (hx + dx, hy - 12.5), (hx + dx * 0.8, hy - 7.5), 1.9, QColor(patc.red(), patc.green(), patc.blue(), 210))
    elif pat == "spots":
        _blob(p, hx + 8.5, hy - 5.0, 2.4, 2.1, patc)
        _blob(p, hx - 9.0, hy + 1.0, 1.9, 1.7, patc)

    # 9. глаза
    ey = hy - 2.2
    for ex in (hx + eo - 5.2, hx + eo + 5.2):
        if sleeping or happy:
            p.setPen(QPen(eye, 2.0, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawArc(QRectF(ex - 3.4, ey - 1.6, 6.8, 5.0), 0, -180 * 16)
        else:
            _blob(p, ex, ey, 3.9, 4.5, QColor(10, 10, 12, 150))
            _blob(p, ex, ey, 3.4, 4.0, eye)
            _blob(p, ex + facing * 0.3, ey + 0.2, 3.9 if laser else 1.5, 3.3, QColor(14, 14, 18))
            _blob(p, ex - 1.0, ey - 1.6, 1.15, 1.15, QColor(255, 255, 255, 235))

    # 10. носик, ротик, усы
    nx0, ny0 = hx + eo * 0.7, hy + 3.3
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(nose)
    p.drawPolygon(QPolygonF([QPointF(nx0 - 2.3, ny0), QPointF(nx0 + 2.3, ny0), QPointF(nx0, ny0 + 2.7)]))
    mouth = QColor(30, 20, 24, 150) if not dark else QColor(255, 255, 255, 90)
    _stroke(p, (nx0, ny0 + 2.9), (nx0 - 2.0, ny0 + 4.6), 0.8, mouth)
    _stroke(p, (nx0, ny0 + 2.9), (nx0 + 2.0, ny0 + 4.6), 0.8, mouth)
    for side in (-1, 1):
        for ang in (-0.22, 0.0, 0.22):
            sx, sy = hx + eo * 0.7 + side * 6.0, hy + 5.6
            ex2 = sx + side * 13.0 * math.cos(ang)
            ey2 = sy + 13.0 * math.sin(ang) + 1.0
            _stroke(p, (sx, sy), (ex2, ey2), 0.9, whisker)


def _pal(body, belly, limb, ear_inner, eye, nose, pattern="none", pattern_color=(70, 48, 36), tail_tip=None):
    return {
        "body": QColor(*body), "belly": QColor(*belly), "limb": QColor(*limb),
        "ear_inner": QColor(*ear_inner), "eye": QColor(*eye), "nose": QColor(*nose),
        "tail_tip": QColor(*(tail_tip or body)),
        "pattern": pattern, "pattern_color": QColor(*pattern_color),
    }


CAT_PALETTES = {
    "black": _pal((24, 24, 28), (46, 46, 54), (15, 15, 19), (115, 65, 78), (255, 212, 45), (220, 125, 135)),
    "ginger": _pal((235, 128, 48), (250, 214, 168), (205, 105, 32), (255, 185, 175), (80, 210, 95), (235, 120, 125)),
    "white": _pal((244, 244, 248), (255, 255, 255), (222, 222, 234), (252, 182, 195), (65, 175, 250), (242, 145, 155)),
}
PALETTE_LABELS = {"black": "Чёрный", "ginger": "Рыжий", "white": "Белый"}
BUILTIN_COLORS = ("black", "ginger", "white")
PALETTE_COLOR_FIELDS = ("body", "belly", "limb", "ear_inner", "eye", "nose", "tail_tip")


def copy_palette(pal: dict) -> dict:
    return {k: (QColor(v) if isinstance(v, QColor) else v) for k, v in pal.items()}


def _hex(c: QColor) -> str:
    return "#%02x%02x%02x" % (c.red(), c.green(), c.blue())


def _from_hex(text, fallback: QColor) -> QColor:
    try:
        t = str(text).lstrip("#")
        return QColor(int(t[0:2], 16), int(t[2:4], 16), int(t[4:6], 16))
    except Exception:
        return QColor(fallback)


def palette_to_dict(key: str, name: str, pal: dict) -> dict:
    d = {"key": key, "name": name, "pattern": pal.get("pattern", "none"), "pattern_color": _hex(pal["pattern_color"])}
    for f in PALETTE_COLOR_FIELDS:
        d[f] = _hex(pal[f])
    return d


def palette_from_dict(d: dict) -> dict:
    base = CAT_PALETTES["black"]
    pal = {f: _from_hex(d.get(f), base[f]) for f in PALETTE_COLOR_FIELDS}
    pal["pattern"] = d.get("pattern", "none") if d.get("pattern", "none") in CAT_PATTERNS else "none"
    pal["pattern_color"] = _from_hex(d.get("pattern_color"), base["pattern_color"])
    return pal


def register_custom_palette(d: dict) -> str:
    key = str(d.get("key", ""))
    CAT_PALETTES[key] = palette_from_dict(d)
    PALETTE_LABELS[key] = str(d.get("name", tr("Мой кот")))[:24]
    return key


def color_label(key: str) -> str:
    """Название окраса: встроенные переводятся, свои (придуманные пользователем) показываются как есть."""
    if key in BUILTIN_COLORS:
        return tr(PALETTE_LABELS[key])
    return PALETTE_LABELS.get(key, key)


def unregister_custom_palette(key: str):
    if key not in BUILTIN_COLORS:
        CAT_PALETTES.pop(key, None)
        PALETTE_LABELS.pop(key, None)


class RagdollNode:
    def __init__(self, x: float, y: float, name: str):
        self.x = x
        self.y = y
        self.vx = 0.0
        self.vy = 0.0
        self.name = name


FISH_COLORS = [((255, 159, 67), (230, 110, 20)), ((84, 160, 255), (40, 110, 210)),
               ((255, 107, 129), (215, 60, 95)), ((110, 220, 160), (40, 160, 105))]


class Fish:
    __slots__ = ("x", "y", "vy", "landed", "age", "color", "fin", "eaten", "claimed_by", "phase")

    def __init__(self, x: float, y: float):
        self.x = x
        self.y = y
        self.vy = random.uniform(2.0, 4.0)
        self.landed = False
        self.age = 0
        self.color, self.fin = random.choice(FISH_COLORS)
        self.eaten = False
        self.claimed_by = None
        self.phase = random.uniform(0.0, 6.28)


def draw_fish(p, f: "Fish"):
    p.save()
    p.translate(f.x, f.y)
    p.rotate(-8.0 if f.landed else math.sin(f.phase + f.age * 0.18) * 22.0)
    fin = QColor(*f.fin)
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(fin)
    p.drawPolygon(QPolygonF([QPointF(-8, 0), QPointF(-17.5, -6.5), QPointF(-17.5, 6.5)]))
    p.drawPolygon(QPolygonF([QPointF(-3, -5), QPointF(1, -10), QPointF(5.5, -5)]))
    p.setBrush(QColor(*f.color))
    p.drawEllipse(QPointF(0, 0), 11.5, 5.8)
    p.setBrush(QColor(255, 255, 255, 80))
    p.drawEllipse(QPointF(1.0, 2.0), 8.0, 2.2)
    p.setBrush(QColor(255, 255, 255))
    p.drawEllipse(QPointF(6.5, -1.3), 2.0, 2.0)
    p.setBrush(QColor(20, 20, 24))
    p.drawEllipse(QPointF(6.9, -1.3), 1.0, 1.0)
    p.restore()


class Pet:
    """Один питомец: скелет Ragdoll, поведение, пузыри, окрас. Рисуется и обновляется общим слоем CompanionOverlay."""

    def __init__(self, host, num: int, color_key: str = "black", profile: str = DEFAULT_PROFILE,
                 spawn_x: float | None = None, meow_interval_ms: int = 16000):
        self.host = host
        self.num = num
        self.profile = profile if profile in PROFILES else DEFAULT_PROFILE

        self.facing = 1
        self.color_key = color_key if color_key in CAT_PALETTES else "black"
        self.state = "idle"
        self.state_timer = 100
        self.idle_seconds = 0.0
        self.walk_phase = 0.0
        self.tail_phase = 0.0
        self.breath_phase = 0.0
        self.flip_frames = 0
        self.airborne = False

        self.drop_ignore_y = -1.0
        self.drop_ignore_frames = 0

        self.anchor_x = float(host.width() // 2)
        self.anchor_y = float(host.height() - 4)

        self.laser_mode = False
        self.pet_score = 0.0

        self.grabbed_node: int | None = None
        self.hovered_node: int | None = None

        self.bubble_text = ""
        self.bubble_timer = 0
        self.notif_mode = host.notif_mode

        # прыжок в сугроб
        self.pile_phase = None        # None / "run" (бежит к куче) / "jump" (в прыжке)
        self.pile_target_x = 0.0
        self.pile_run_frames = 0
        self.pile_cooldown = 0
        self.sink_px = 0.0            # на сколько пикселей кот «провалился»
        self.sink_depth = 0.0
        self.sink_frames = 0
        # кормёжка
        self.fish_target = None
        self.eat_frames = 0

        self.reset_cat_position(spawn_x)

        self.meow_timer = QTimer(host)
        self.meow_timer.timeout.connect(self.random_meow)
        self.meow_timer.start(meow_interval_ms)

    @property
    def name(self) -> str:
        return tr('Питомец {0}').format(self.num)

    def shutdown(self):
        self.meow_timer.stop()
        self.meow_timer.deleteLater()

    def reset_cat_position(self, cx: float | None = None):
        host = self.host
        cx = float(host.width() // 2) if cx is None else float(cx)
        cy = float(host.height() - 80)
        self.anchor_x = cx
        self.anchor_y = float(host.height() - 4)
        self.grabbed_node = None
        self.airborne = True
        self.drop_ignore_frames = 0
        self.state = "idle"
        self.nodes = [
            RagdollNode(cx + 18, cy - 16, "Голова"),         # 0
            RagdollNode(cx + 10, cy, "Грудь"),               # 1
            RagdollNode(cx - 14, cy, "Таз"),                 # 2
            RagdollNode(cx + 6, cy + 22, "Передняя лапа"),   # 3
            RagdollNode(cx + 14, cy + 22, "Передняя лапа"),  # 4
            RagdollNode(cx - 18, cy + 22, "Задняя лапа"),    # 5
            RagdollNode(cx - 10, cy + 22, "Задняя лапа"),    # 6
            RagdollNode(cx - 28, cy - 10, "Хвост"),          # 7
            RagdollNode(cx - 38, cy - 22, "Кончик хвоста"),  # 8
            RagdollNode(cx + 12, cy - 30, "Ушко"),           # 9
            RagdollNode(cx + 24, cy - 30, "Ушко"),           # 10
        ]
        self.bones = [
            (1, 2, 22.0, 26.0),
            (0, 1, 14.0, 18.0),
            (1, 3, 10.0, 24.0),
            (1, 4, 10.0, 24.0),
            (2, 5, 10.0, 24.0),
            (2, 6, 10.0, 24.0),
            (2, 7, 14.0, 18.0),
            (7, 8, 14.0, 18.0),
            (0, 9, 13.0, 16.0),
            (0, 10, 13.0, 16.0),
            (9, 10, 10.0, 14.0),
        ]

    def closest_node(self, pos: QPointF, max_dist: float = 28.0):
        """Возвращает (индекс узла или None, расстояние)."""
        priority = [3, 4, 5, 6, 8, 7, 9, 10, 0, 1, 2]
        best_idx = None
        best_d = max_dist
        for idx in priority:
            n = self.nodes[idx]
            d = math.hypot(pos.x() - n.x, pos.y() - n.y)
            if d < best_d:
                best_d = d
                best_idx = idx
        return best_idx, best_d

    def find_closest_node(self, pos: QPointF, max_dist: float = 28.0) -> int | None:
        return self.closest_node(pos, max_dist)[0]

    def set_color(self, color_key: str, announce: bool = True):
        if color_key in CAT_PALETTES:
            self.color_key = color_key
            if announce:
                self.show_bubble(tr("Мяу! Новый окрас ✨"), 110)
            self.host.update()

    def set_notification_mode(self, mode: str, announce: bool = True):
        self.notif_mode = mode
        if not announce:
            return
        if mode == "default":
            self.show_bubble(tr("Режим: обычное Мяу 🐾"), 100)
        else:
            self.show_bubble(tr('Уведомления: {0} 🔔').format(mode.capitalize()), 120)

    def toggle_laser(self):
        self.laser_mode = not self.laser_mode
        self.pile_phase = None
        if self.laser_mode:
            self.state = "laser"
            self.idle_seconds = 0
            self.show_bubble(tr("Охота за лазером! 🔴"), 110)
        else:
            self.state = "walk" if self.profile == "active" else "idle"
            self.show_bubble(tr("Фух, набегался!"), 90)

    def set_profile(self, key: str, announce: bool = False):
        if key not in PROFILES:
            key = DEFAULT_PROFILE
        self.profile = key
        self.idle_seconds = 0.0
        if key == "active" and self.state in ("idle", "sleep") and not self.laser_mode:
            self.state = "walk"
            self.state_timer = random.randint(180, 320)
        if announce:
            self.show_bubble(tr("Режим: активный 🏃") if key == "active" else tr("Режим: спокойный 😺"), 100)

    def _wake_up_and_run(self):
        """Сброс простоя. В активном профиле ещё и будит кота (поведение V1)."""
        was_sleeping = (self.state == "sleep")
        self.idle_seconds = 0.0
        if self.profile == "active" and (was_sleeping or self.state == "idle"):
            self.state = "walk"
            self.state_timer = random.randint(180, 320)

    def show_bubble(self, text: str, duration_frames: int = 180, wake: bool = True):
        self.bubble_text = text
        self.bubble_timer = duration_frames
        if wake:
            self._wake_up_and_run()

    def on_external_notification(self, app_name: str, text: str, show_text: bool = True):
        self.airborne = True
        for n in self.nodes:
            n.vy = -8.0
        if show_text:
            prefix = f"[{app_name}] " if app_name else ""
            self.show_bubble(f"🔔 {prefix}{text}", 280)
        else:
            self._wake_up_and_run()

    def random_meow(self):
        if self.state == "sleep" or self.bubble_timer > 0:
            return
        if self.host.snow.enabled and random.random() < 0.42:
            if self.try_start_pile_jump():
                return
            self.airborne = True
            for n in self.nodes:
                n.vy = -6.5
                n.vx = self.facing * 2.0
            self.show_bubble(random.choice([tr("Снежок! ❄️"), tr("Хрусь-хрусь 🐾"), tr("Ловлю снежинку! ❄️")]), 140, wake=self.profile != "active")
            return
        if self.notif_mode == "default" and random.random() < 0.55:
            self.show_bubble(random.choice([tr("Мяу!"), tr("Мяу~"), tr("Мрр?"), tr("Мяу ❤️")]), 130, wake=self.profile != "active")

    # --- кормёжка ---
    def can_chase_fish(self) -> bool:
        """Бежать к рыбке может только свободный кот, стоящий на полу."""
        return (not self.airborne and self.grabbed_node is None and not self.laser_mode
                and self.pile_phase is None and self.sink_frames <= 0 and self.eat_frames <= 0
                and self.anchor_y >= self.host.height() - 10)

    # --- прыжок в большой сугроб ---
    def try_start_pile_jump(self, force: bool = False) -> bool:
        """Если рядом (в пределах PILE_REACH) есть БОЛЬШАЯ куча, кот бежит к ней и прыгает. Маленькие кучки игнорирует."""
        host = self.host
        if (self.airborne or self.grabbed_node is not None or self.laser_mode or self.pile_phase is not None
                or self.state == "sleep" or self.sink_frames > 0 or not host.snow.enabled
                or self.fish_target is not None or self.eat_frames > 0):
            return False
        if not force and self.pile_cooldown > 0:
            return False
        if any(w[5] for w in host.windows_cache):   # при развёрнутом окне снег скрыт
            return False
        surf = host.snow.surface_at(self.anchor_x, self.anchor_y, host.windows_cache)
        if surf is None:
            return False
        arr, base_x, base_y, lo_x, hi_x = surf
        found = host.snow.find_big_pile(arr, base_x, self.anchor_x, PILE_REACH, lo_x, hi_x)
        if found is None:
            return False
        self.pile_target_x = found[0]
        self.pile_phase = "run"
        self.pile_run_frames = 0
        self.show_bubble(random.choice([tr("Какой сугроб! ❄️"), tr("Ща как прыгну! 🐾"), tr("Сугроб! Мой!")]), 110,
                         wake=self.profile != "active")
        return True

    def _plunge(self):
        """Приземление после прыжка: вмятина в куче, фонтан снега, кот увязает."""
        host = self.host
        surf = host.snow.surface_at(self.anchor_x, self.anchor_y, host.windows_cache)
        h = 0.0
        if surf is not None:
            arr, base_x, base_y, lo_x, hi_x = surf
            h = host.snow.plunge(arr, base_x, base_y, self.anchor_x)
        self.pile_cooldown = random.randint(1200, 2400)   # 20-40 с до следующего прыжка
        if h >= BIG_PILE_MIN_H * 0.8:
            self.sink_depth = min(14.0, h * 0.6)
            self.sink_frames = 55
            self.show_bubble(random.choice([tr("Пуф! ❄️"), tr("Ууух, глубоко!"), tr("Тону в сугробе! ⛄")]), 120)
        else:
            self.show_bubble(tr("Эй, а где сугроб? 🙀"), 100)

    # --- реакции на мышь (хозяин-слой выбирает ближайшего питомца и вызывает их) ---
    def on_press(self, button, idx: int):
        if button == Qt.MouseButton.LeftButton:
            self.grabbed_node = idx
            self.airborne = True
            self._wake_up_and_run()
            if idx in (3, 4, 5, 6):
                self.show_bubble(tr("Ой, за лапу! 🐾"), 75)
            elif idx in (7, 8):
                self.show_bubble(tr("Хвост не тяни! 🙀"), 75)
            elif idx in (9, 10):
                self.show_bubble(tr("За ушко щекотно!"), 75)
            else:
                self.show_bubble(tr("Уиии!"), 65)
        elif button == Qt.MouseButton.RightButton:
            self.toggle_laser()

    def on_double_click(self):
        self.pile_phase = None
        self.grabbed_node = None
        self.airborne = True
        self.flip_frames = 22
        for n in self.nodes:
            n.vy = -11.0
            n.vx = self.facing * 2.8
        self.show_bubble(tr("Сальто! 🐾"), 100)

    def on_petting(self, pos: QPointF):
        dist = math.hypot(pos.x() - self.host.last_cursor_pos.x(), pos.y() - self.host.last_cursor_pos.y())
        if 2 < dist < 40:
            self.pet_score += dist
            self._wake_up_and_run()
            if self.pet_score > 140:
                self.pet_score = 0
                self.show_bubble(tr("Мррр... ❤️"), 120)

    def on_release(self):
        self.grabbed_node = None
        self.airborne = True
        if self.profile == "active":
            self._wake_up_and_run()

    def _get_support_surface(self, x: float, foot_y: float) -> float | None:
        host = self.host
        floor_y = float(host.height() - 4)
        for w in host.windows_cache:
            wl, wt, wr, wb, _, is_max = w
            if not is_max and wt > 30 and (wl + 24) <= x <= (wr - 24) and win_exposed(w, x):
                if abs(foot_y - wt) <= 14:
                    return float(wt)
        if foot_y >= floor_y - 6:
            return floor_y
        return None

    def _smooth_to(self, node: RagdollNode, tx: float, ty: float, rate: float = 0.28):
        node.x += (tx - node.x) * rate
        node.y += (ty - node.y) * rate
        node.vx = 0.0
        node.vy = 0.0

    def tick(self):
        """Один кадр физики и поведения (вызывается общим слоем после обновления снега)."""
        host = self.host

        if self.bubble_timer > 0:
            self.bubble_timer -= 1
        if self.flip_frames > 0:
            self.flip_frames -= 1
        if self.drop_ignore_frames > 0:
            self.drop_ignore_frames -= 1
        if self.pile_cooldown > 0:
            self.pile_cooldown -= 1

        self.tail_phase += 0.09
        self.breath_phase += 0.05

        # прямое взаимодействие питомца с сугробами
        cat_cx = (self.nodes[1].x + self.nodes[2].x) * 0.5
        cat_cy = max(self.nodes[3].y, self.nodes[4].y, self.nodes[5].y, self.nodes[6].y)
        cat_vx = self.nodes[1].vx if (self.airborne or self.grabbed_node is not None) else (self.facing * 2.2 if self.state in ("walk", "laser") else 0.0)
        cat_vy = self.nodes[1].vy if (self.airborne or self.grabbed_node is not None) else 0.0
        if self.pile_phase != "jump" and self.sink_frames <= 0:
            host.snow.interact_with_cat(cat_cx, cat_cy, cat_vx, cat_vy, host.windows_cache)

        # =================================================================
        # РЕЖИМ А: RAGDOLL В ВОЗДУХЕ ИЛИ ЗАХВАТ КОНЕЧНОСТИ МЫШКОЙ
        # =================================================================
        if self.grabbed_node is not None or self.airborne:
            if self.grabbed_node is not None:
                self.pile_phase = None
                gn = self.nodes[self.grabbed_node]
                gn.vx = (host.cursor_pos.x() - gn.x) * 0.45
                gn.vy = (host.cursor_pos.y() - gn.y) * 0.45
                gn.x = host.cursor_pos.x()
                gn.y = host.cursor_pos.y()
                if abs(gn.vx) > 1.8:
                    self.facing = 1 if gn.vx > 0 else -1

            MAX_SPEED = 16.0
            floor_y = float(host.height() - 4)

            for i, n in enumerate(self.nodes):
                if i == self.grabbed_node:
                    continue

                n.vy += 0.52
                n.vx *= 0.92
                n.vy *= 0.92
                n.vx = max(-MAX_SPEED, min(MAX_SPEED, n.vx))
                n.vy = max(-MAX_SPEED, min(MAX_SPEED, n.vy))

                n.x += n.vx
                n.y += n.vy

                if n.y >= floor_y:
                    n.y = floor_y
                    n.vy = 0.0
                    n.vx *= 0.6

                if n.x < 18:
                    n.x = 18
                    n.vx = abs(n.vx) * 0.5
                    self.facing = 1
                elif n.x > host.width() - 18:
                    n.x = host.width() - 18
                    n.vx = -abs(n.vx) * 0.5
                    self.facing = -1
                if n.y < 18:
                    n.y = 18
                    n.vy = 0.0

            if self.flip_frames > 0 and self.grabbed_node is None:
                cx = (self.nodes[1].x + self.nodes[2].x) * 0.5
                cy = (self.nodes[1].y + self.nodes[2].y) * 0.5
                ang = 0.36 * self.facing
                ca, sa = math.cos(ang), math.sin(ang)
                for n in self.nodes:
                    dx, dy = n.x - cx, n.y - cy
                    n.x = cx + dx * ca - dy * sa
                    n.y = cy + dx * sa + dy * ca

            for _ in range(6):
                for idx_a, idx_b, min_len, max_len in self.bones:
                    na = self.nodes[idx_a]
                    nb = self.nodes[idx_b]
                    dx = nb.x - na.x
                    dy = nb.y - na.y
                    dist = math.hypot(dx, dy) or 0.001

                    if dist < min_len:
                        target_len = min_len
                    elif dist > max_len:
                        target_len = max_len
                    else:
                        continue

                    diff = (dist - target_len) / dist * 0.45
                    if idx_a == self.grabbed_node:
                        nb.x -= dx * diff * 2.0
                        nb.y -= dy * diff * 2.0
                    elif idx_b == self.grabbed_node:
                        na.x += dx * diff * 2.0
                        na.y += dy * diff * 2.0
                    else:
                        na.x += dx * diff
                        na.y += dy * diff
                        nb.x -= dx * diff
                        nb.y -= dy * diff

            if self.grabbed_node is None and self.flip_frames <= 0:
                body_cx = (self.nodes[1].x + self.nodes[2].x) * 0.5
                feet_y = max(self.nodes[1].y, self.nodes[2].y, self.nodes[3].y, self.nodes[4].y, self.nodes[5].y, self.nodes[6].y)
                avg_vy = (self.nodes[1].vy + self.nodes[2].vy) * 0.5

                landed_y = None
                if avg_vy >= -0.5:
                    for w in host.windows_cache:
                        wl, wt, wr, wb, _, is_max = w
                        if is_max or wt <= 30:
                            continue
                        if self.drop_ignore_frames > 0 and abs(wt - self.drop_ignore_y) < 20:
                            continue
                        if (wl + 26) <= body_cx <= (wr - 26) and win_exposed(w, body_cx):
                            if (wt - 12) <= feet_y <= (wt + 16):
                                landed_y = float(wt)
                                break

                if landed_y is None and feet_y >= floor_y - 2:
                    landed_y = floor_y

                if landed_y is not None:
                    self.airborne = False
                    self.anchor_x = body_cx
                    self.anchor_y = landed_y
                    for n in self.nodes:
                        n.vx = 0.0
                        n.vy = 0.0
                    if self.pile_phase == "jump":
                        self._plunge()
                    self.pile_phase = None

            return

        # =================================================================
        # РЕЖИМ Б: КОТ СТОИТ НА ОКНЕ ИЛИ ПОЛУ
        # =================================================================
        support_y = self._get_support_surface(self.anchor_x, self.anchor_y)
        if support_y is None:
            self.airborne = True
            self.pile_phase = None
            self.drop_ignore_y = self.anchor_y
            self.drop_ignore_frames = 25
            for n in self.nodes:
                n.vx = self.facing * 3.0
                n.vy = 1.5
            return

        self.anchor_y = support_y

        if self.sink_frames > 0:
            self.sink_frames -= 1
            self.sink_px += (self.sink_depth - self.sink_px) * 0.22
        elif self.sink_px > 0.3:
            self.sink_px *= 0.90   # выбирается из сугроба
        else:
            self.sink_px = 0.0
        if self.eat_frames > 0:
            self.eat_frames -= 1

        is_moving = False
        if self.laser_mode:
            self.state = "laser"
            dx = host.cursor_pos.x() - self.anchor_x
            dy = host.cursor_pos.y() - self.anchor_y
            if abs(dx) > 18:
                self.facing = 1 if dx > 0 else -1
                speed = min(4.2, abs(dx) * 0.06)
                self.anchor_x += self.facing * speed
                self.walk_phase += 0.26
                is_moving = True
            if dy < -75 and abs(dx) < 110 and random.random() < 0.04:
                self.airborne = True
                for n in self.nodes:
                    n.vy = -10.5
                    n.vx = self.facing * 2.0
                return
        elif self.fish_target is not None:
            fish = self.fish_target
            dx = fish.x - self.anchor_x
            self.facing = 1 if dx > 0 else -1
            self.state = "walk"
            self.idle_seconds = 0.0
            if abs(self.anchor_y - fish.y) > 26.0 and fish.landed:
                fish.claimed_by = None          # рыбка внизу, а кот на окне: пусть достанется другому
                self.fish_target = None
            elif abs(dx) > 14.0:
                self.anchor_x += self.facing * 2.9
                self.walk_phase += 0.30
                is_moving = True
            elif fish.landed:
                fish.eaten = True
                self.fish_target = None
                self.eat_frames = 55
                self.show_bubble(random.choice([tr("Ням! 🐟"), tr("Вкуснятина! 😻"), tr("Мррр, рыбка!")]), 110)
        elif self.pile_phase == "run":
            self.pile_run_frames += 1
            dx = self.pile_target_x - self.anchor_x
            self.facing = 1 if dx > 0 else -1
            self.state = "walk"
            self.idle_seconds = 0.0
            if self.pile_run_frames >= 420:
                self.pile_phase = None          # не добежал: отменяем
                self.pile_cooldown = 600
            elif abs(dx) > PILE_JUMP_START_DIST:
                self.anchor_x += self.facing * 2.4
                self.walk_phase += 0.24
                is_moving = True
            else:
                self.pile_phase = "jump"
                self.airborne = True
                for n in self.nodes:
                    n.vy = -8.5
                    n.vx = self.facing * 3.9
                return
        elif self.sink_frames > 0 or self.eat_frames > 0:
            pass   # увяз в сугробе или ест рыбку: стоит на месте
        else:
            prof = PROFILES[self.profile]
            active = (self.profile == "active")
            self.idle_seconds += 0.016
            if self.idle_seconds >= prof["sleep_after"]:
                self.state = "sleep"
            else:
                if self.state == "sleep":
                    if active:
                        self.state = "walk"
                        self.state_timer = random.randint(180, 320)
                    else:
                        self.state = "idle"
                self.state_timer -= 1
                if self.state_timer <= 0:
                    if active:
                        # V1: 88% времени бодрствования кот бегает, редко останавливаясь на 0.4-0.9 с
                        if self.state == "idle" or random.random() < 0.88:
                            self.state = "walk"
                            self.facing = random.choice([-1, 1])
                            self.state_timer = random.randint(180, 360)
                        else:
                            self.state = "idle"
                            self.state_timer = random.randint(25, 55)
                    else:
                        if random.random() < 0.55:
                            self.state = "walk"
                            self.facing = random.choice([-1, 1])
                            self.state_timer = random.randint(90, 220)
                        else:
                            self.state = "idle"
                            self.state_timer = random.randint(90, 200)

                if self.state == "walk":
                    self.anchor_x += self.facing * prof["walk_speed"]
                    self.walk_phase += prof["walk_phase"]
                    is_moving = True

        if self.anchor_x < 35:
            self.anchor_x = 35
            self.facing = 1
        elif self.anchor_x > host.width() - 35:
            self.anchor_x = host.width() - 35
            self.facing = -1

        f = self.facing
        gx = self.anchor_x
        gy = self.anchor_y + self.sink_px

        if self.state == "sleep":
            breath = math.sin(self.breath_phase) * 0.8
            chest_x, chest_y = gx + f * 9.0, gy - 11.0 + breath
            hip_x, hip_y = gx - f * 11.0, gy - 11.0 + breath
            head_x, head_y = chest_x + f * 8.0, gy - 14.0 + breath

            self._smooth_to(self.nodes[1], chest_x, chest_y, 0.20)
            self._smooth_to(self.nodes[2], hip_x, hip_y, 0.20)
            self._smooth_to(self.nodes[0], head_x, head_y, 0.20)

            self._smooth_to(self.nodes[9], head_x - 6.0, head_y - 14.0, 0.25)
            self._smooth_to(self.nodes[10], head_x + 6.0, head_y - 14.0, 0.25)

            self._smooth_to(self.nodes[3], chest_x - 3.0, gy - 3.0, 0.25)
            self._smooth_to(self.nodes[4], chest_x + 3.0, gy - 3.0, 0.25)
            self._smooth_to(self.nodes[5], hip_x - 3.0, gy - 3.0, 0.25)
            self._smooth_to(self.nodes[6], hip_x + 3.0, gy - 3.0, 0.25)

            sway = math.sin(self.tail_phase * 0.5) * 2.0
            self._smooth_to(self.nodes[7], hip_x - f * 12.0, gy - 9.0, 0.20)
            self._smooth_to(self.nodes[8], hip_x - f * 20.0 + sway, gy - 12.0, 0.20)
        else:
            bob = abs(math.sin(self.walk_phase)) * 1.5 if is_moving else math.sin(self.breath_phase) * 0.6
            chest_x, chest_y = gx + f * 12.0, gy - 22.0 - bob
            hip_x, hip_y = gx - f * 12.0, gy - 22.0 - bob
            head_x, head_y = chest_x + f * 10.0, chest_y - 14.0
            if self.eat_frames > 0:   # ест: опускает мордочку к рыбке
                head_y += 10.0 + math.sin(self.eat_frames * 0.9) * 2.0
                head_x += f * 5.0

            self._smooth_to(self.nodes[1], chest_x, chest_y, 0.35)
            self._smooth_to(self.nodes[2], hip_x, hip_y, 0.35)
            self._smooth_to(self.nodes[0], head_x, head_y, 0.35)

            self._smooth_to(self.nodes[9], head_x - 6.0, head_y - 15.0, 0.40)
            self._smooth_to(self.nodes[10], head_x + 6.0, head_y - 15.0, 0.40)

            if is_moving:
                # лапа на земле должна ехать ПРОТИВ движения тела, поэтому знак зависит от направления (f)
                s1 = -f * math.sin(self.walk_phase) * 7.5
                s2 = -f * math.sin(self.walk_phase + math.pi) * 7.5
                l1 = max(0.0, -math.cos(self.walk_phase) * 5.5)
                l2 = max(0.0, -math.cos(self.walk_phase + math.pi) * 5.5)
            else:
                s1 = s2 = l1 = l2 = 0.0

            self._smooth_to(self.nodes[3], chest_x - 3.0 + s1, gy - 2.0 - l1, 0.45)
            self._smooth_to(self.nodes[4], chest_x + 3.0 + s2, gy - 2.0 - l2, 0.45)
            self._smooth_to(self.nodes[5], hip_x - 3.0 + s2, gy - 2.0 - l2, 0.45)
            self._smooth_to(self.nodes[6], hip_x + 3.0 + s1, gy - 2.0 - l1, 0.45)

            sway = math.sin(self.tail_phase) * 8.0
            self._smooth_to(self.nodes[7], hip_x - f * 12.0, hip_y - 9.0, 0.28)
            self._smooth_to(self.nodes[8], hip_x - f * 18.0 + sway, hip_y - 22.0, 0.24)

    def paint(self, painter):
        """Рисует одного питомца (снег и лазерная точка рисуются слоем-хозяином)."""
        host = self.host
        pal = CAT_PALETTES.get(self.color_key) or CAT_PALETTES["black"]
        n = self.nodes
        hx, hy = n[0].x, n[0].y
        on_ground = (not self.airborne) and self.grabbed_node is None
        paint_cat_body(painter, n, pal, self.facing,
                       sleeping=(self.state == "sleep"), happy=(tr("Мррр") in self.bubble_text),
                       laser=self.laser_mode, ground_y=(self.anchor_y if on_ground else None))

        if self.sink_px > 1.0:
            sx = (n[1].x + n[2].x) * 0.5
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QColor(246, 250, 255, 240))
            painter.drawEllipse(QPointF(sx, self.anchor_y + 4.0), 30.0 + self.sink_px * 0.9, 5.0 + self.sink_px * 1.5)

        active_idx = self.grabbed_node if self.grabbed_node is not None else self.hovered_node
        if active_idx is not None:
            gn = self.nodes[active_idx]
            painter.setBrush(QColor(162, 155, 254, 160))
            painter.setPen(QPen(QColor(255, 255, 255, 210), 1.5))
            painter.drawEllipse(QPointF(gn.x, gn.y), 5.5, 5.5)

        display_text = self.bubble_text if self.bubble_timer > 0 else ("Zzz..." if self.state == "sleep" else "")
        if display_text:
            font = QFont("Segoe UI", 9, QFont.Weight.Bold)
            painter.setFont(font)
            fm = painter.fontMetrics()
            tw = fm.horizontalAdvance(display_text) + 22
            th = 28
            bx = max(10.0, min(host.width() - tw - 10.0, hx - tw / 2))
            by = max(10.0, hy - 54)

            painter.setBrush(QColor(22, 24, 30, 238))
            painter.setPen(QPen(QColor(108, 92, 231), 1.4))
            painter.drawRoundedRect(QRectF(bx, by, tw, th), 10, 10)

            painter.setPen(QColor(245, 245, 250))
            painter.drawText(QRectF(bx, by, tw, th), Qt.AlignmentFlag.AlignCenter, display_text)


class CompanionOverlay(QWidget):
    """Один полноэкранный прозрачный слой: снег, список окон, мышь и все питомцы в одном процессе и одном таймере."""

    selection_changed = pyqtSignal()

    def __init__(self):
        super().__init__()
        self.setWindowTitle("BlackCatOverlay")
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint |
            Qt.WindowType.WindowStaysOnTopHint |
            Qt.WindowType.Tool
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
        self.setMouseTracking(True)

        screen = QApplication.primaryScreen().availableGeometry()
        self.setGeometry(screen)

        self.snow = SmoothSnowEngine(screen.width(), screen.height())
        self.notif_mode = "default"
        self.max_pets = MAX_PETS
        self.fish: list[Fish] = []
        self.perf = PerfGovernor()
        self.clock = time.perf_counter
        self._ticks_since_paint = 0
        self._painted_now = False
        self._paint_acc = 0.0
        self._last_tick_t = None
        self.pet_count_note = ""

        self.cursor_pos = QPointF(float(screen.width() // 2), float(screen.height() - 4))
        self.last_cursor_pos = QPointF(float(screen.width() // 2), float(screen.height() - 4))

        self.frame_counter = 0
        self._is_click_through = False

        # слежение за окнами: события Windows + пересчёт координат под масштаб экрана и панель задач
        self.tracker = WindowTracker(Win32Backend() if sys.platform == "win32" else NullBackend())
        self.paused = False
        self.pause_on_fullscreen = True      # при полноэкранной игре или видео слой ставится на паузу
        self._configure_tracker()
        self.tracker.install_hooks()
        try:
            scr = QApplication.primaryScreen()
            scr.availableGeometryChanged.connect(self._relayout)
            scr.geometryChanged.connect(self._relayout)
        except Exception:
            pass

        self.pets: list[Pet] = []
        self.selected_index = 0
        self._pet_counter = 0
        self.add_pet()

        self.timer = QTimer(self)
        self.timer.timeout.connect(self.update_physics)
        self.timer.start(16)

    # ------------------------------------------------------------ окна, пауза, размер экрана
    @property
    def windows_cache(self):
        return self.tracker.windows

    @windows_cache.setter
    def windows_cache(self, wins):
        self.tracker.set_windows(wins)

    def _configure_tracker(self):
        """Сообщает слежению, где лежит наш слой и какой масштаб у экрана."""
        scr = QApplication.primaryScreen()
        geo = scr.availableGeometry()
        try:
            dpr = float(scr.devicePixelRatio())
        except Exception:
            dpr = 1.0
        ox = geo.x() if hasattr(geo, "x") else 0
        oy = geo.y() if hasattr(geo, "y") else 0
        self.tracker.configure((ox, oy), dpr, (geo.width(), geo.height()))

    def _relayout(self, *args):
        """Разрешение, масштаб или панель задач изменились: подгоняем слой, снег и котов."""
        geo = QApplication.primaryScreen().availableGeometry()
        size_changed = (geo.width() != self.snow.w or geo.height() != self.snow.h)
        self.setGeometry(geo)
        if size_changed:
            self.snow.resize(geo.width(), geo.height())
            self.fish.clear()
            for p in self.pets:
                p.reset_cat_position()
        self._configure_tracker()

    def windows_report(self) -> str:
        """Текстовый отчёт: какие окна видит программа и какие из них учтены (для диагностики)."""
        kept = {w.hwnd for w in self.tracker.windows}
        lines = [tr('Слой: {0}x{1}, масштаб экрана {2}, начало {3}').format(self.width(), self.height(), self.tracker.dpr, self.tracker.origin),
                 tr('События Windows работают: {0}').format(getattr(self.tracker.backend, 'hooks_ok', False)),
                 tr('Полный экран сейчас: {0}').format(self.tracker.fullscreen), tr('Учтено окон: {0}').format(len(kept)), ""]
        for r in self.tracker._raw:
            mark = tr("УЧТЕНО   ") if r.hwnd in kept else tr("пропущено")
            lines.append(tr('{0} hwnd={1} класс={2} заголовок={3!r} рамка=({4},{5},{6},{7}) style=0x{8:08x} ex=0x{9:08x}').format(mark, r.hwnd, r.cls, r.title, r.l, r.t, r.r, r.b, r.style, r.ex_style))
        return "\n".join(lines)

    def _set_paused(self, flag: bool):
        """Полноэкранная игра или видео: прячем слой и почти не тратим процессор."""
        if flag == self.paused:
            return
        self.paused = flag
        self.perf.reset_window()
        self.timer.setInterval(500 if flag else 16)
        if flag:
            self.hide()
        else:
            self.show()
            self.tracker.mark_dirty()

    # ------------------------------------------------------------ питомцы
    @property
    def pet(self) -> "Pet | None":
        """Выбранный питомец (к нему применяются окрас, лазер, профиль и «вернуть в центр»)."""
        if not self.pets:
            return None
        return self.pets[min(self.selected_index, len(self.pets) - 1)]

    def add_pet(self, color: str = "black", profile: str | None = None, announce: bool = False):
        if len(self.pets) >= self.max_pets:
            return None
        self._pet_counter += 1
        first = not self.pets
        if profile is None:
            profile = self.pets[0].profile if self.pets else DEFAULT_PROFILE
        spawn_x = None if first else random.uniform(60.0, max(61.0, self.width() - 60.0))
        # у первого питомца интервал как в V1/V2; у остальных небольшой разброс, чтобы не мяукали хором
        interval = 16000 if first else 16000 + random.randint(-3000, 3000)
        pet = Pet(self, self._pet_counter, color, profile, spawn_x, interval)
        self.pets.append(pet)
        if announce:
            pet.show_bubble(tr("Привет! 🐾"), 100)
        return pet

    def remove_pet(self, pet: "Pet") -> bool:
        if pet not in self.pets or len(self.pets) <= 1:
            return False
        idx = self.pets.index(pet)
        self.pets.remove(pet)
        pet.shutdown()
        if self.selected_index >= len(self.pets):
            self.selected_index = len(self.pets) - 1
        elif idx < self.selected_index:
            self.selected_index -= 1
        self.update()
        return True

    def select_index(self, i: int):
        if 0 <= i < len(self.pets):
            self.selected_index = i

    def _select(self, pet: "Pet"):
        i = self.pets.index(pet)
        if i != self.selected_index:
            self.selected_index = i
            self.selection_changed.emit()

    def pets_config(self) -> list:
        return [{"color": p.color_key, "profile": p.profile} for p in self.pets]

    def apply_pets_config(self, cfgs: list):
        cfgs = [c for c in cfgs if isinstance(c, dict)][: self.max_pets] or [{}]
        for i, c in enumerate(cfgs):
            color = c.get("color", "black")
            color = color if color in CAT_PALETTES else "black"
            prof = c.get("profile", DEFAULT_PROFILE)
            prof = prof if prof in PROFILES else DEFAULT_PROFILE
            if i < len(self.pets):
                self.pets[i].set_color(color, announce=False)
                self.pets[i].set_profile(prof)
            else:
                self.add_pet(color, prof)
        while len(self.pets) > len(cfgs) and len(self.pets) > 1:
            self.remove_pet(self.pets[-1])
        self.selected_index = min(self.selected_index, len(self.pets) - 1)

    # ------------------------------------------------------------ команды лаунчера (выбранному питомцу или всем)
    def set_color(self, color_key: str):
        if self.pet:
            self.pet.set_color(color_key)

    def toggle_laser(self):
        if self.pet:
            self.pet.toggle_laser()

    def reset_cat_position(self):
        if self.pet:
            self.pet.reset_cat_position()

    def set_profile(self, key: str, announce: bool = False):
        if self.pet:
            self.pet.set_profile(key, announce)

    def set_notification_mode(self, mode: str):
        self.notif_mode = mode
        voice = self.pet
        for p in self.pets:
            p.set_notification_mode(mode, announce=(p is voice))

    def toggle_snow(self) -> bool:
        self.snow.enabled = not self.snow.enabled
        voice = self.pet
        if voice:
            if self.snow.enabled:
                voice.show_bubble(tr("Ура, пушистый снег! ❄️"), 120)
            else:
                voice.show_bubble(tr("Снег выключен ☀️"), 100)
        return self.snow.enabled

    def clear_snow(self):
        self.snow.clear_drifts()
        if self.pet:
            self.pet.show_bubble(tr("Сугробы расчищены! 🧹"), 100)

    def drop_fish(self) -> int:
        """Выдаёт по одной рыбке на каждого питомца в случайных местах. 0 — прошлые рыбки ещё не съедены."""
        if self.fish or not self.pets:
            return 0
        xs: list[float] = []
        for _ in range(len(self.pets)):
            x = random.uniform(60.0, max(61.0, self.width() - 60.0))
            for _try in range(30):
                if all(abs(x - o) >= 70.0 for o in xs):
                    break
                x = random.uniform(60.0, max(61.0, self.width() - 60.0))
            xs.append(x)
        for x in xs:
            self.fish.append(Fish(x, -20.0 - random.uniform(0.0, 160.0)))   # падают не одновременно
        self.pets[0].show_bubble(tr("Рыбка! 🐟"), 100, wake=False)
        return len(xs)

    def _update_fish(self):
        if not self.fish and not any(p.fish_target is not None for p in self.pets):
            return
        floor_y = self.height() - 8.0
        for f in self.fish:
            f.age += 1
            if not f.landed:
                f.vy = min(9.0, f.vy + 0.35)
                f.y += f.vy
                if f.y >= floor_y:
                    f.y = floor_y
                    f.landed = True
                    f.age = 0
        self.fish = [f for f in self.fish if not f.eaten and not (f.landed and f.age > 2400)]   # лежит не дольше ~40 с
        for f in self.fish:
            if f.claimed_by is not None and (f.claimed_by not in self.pets or f.claimed_by.fish_target is not f):
                f.claimed_by = None
        free = [f for f in self.fish if f.claimed_by is None]
        for pet in self.pets:
            if pet.fish_target is not None and (pet.fish_target.eaten or pet.fish_target not in self.fish):
                pet.fish_target = None
            if pet.fish_target is None and free and pet.can_chase_fish():
                best = min(free, key=lambda f: abs(f.x - pet.anchor_x))
                free.remove(best)
                best.claimed_by = pet
                pet.fish_target = best
                if pet.state == "sleep":
                    pet.state = "walk"

    def remove_color(self, key: str):
        """Расцветка удалена: питомцы с ней становятся чёрными."""
        for p in self.pets:
            if p.color_key == key:
                p.color_key = "black"
        self.update()

    def pile_demo(self):
        """Кнопка «Показать прыжок»: выбранный кот прыгает в ближайшую большую кучу (если её нет, насыпаем показательную)."""
        pet = self.pet
        if pet is None:
            return
        if not self.snow.enabled:
            pet.show_bubble(tr("Сначала включи снег ❄️"), 110)
            return
        if pet.airborne or pet.grabbed_node is not None:
            return
        pet.pile_cooldown = 0
        if pet.try_start_pile_jump(force=True):
            return
        surf = self.snow.surface_at(pet.anchor_x, pet.anchor_y, self.windows_cache)
        if surf is None:
            pet.show_bubble(tr("Тут негде прыгать 🐾"), 100)
            return
        arr, base_x, base_y, lo_x, hi_x = surf
        side = 1 if pet.anchor_x < (lo_x + hi_x) / 2 else -1
        tx = min(hi_x, max(lo_x, pet.anchor_x + side * 110.0))
        self.snow.add_mound(arr, base_x, tx, 20.0)
        pet.try_start_pile_jump(force=True)

    def on_external_notification(self, app_name: str, text: str):
        """Прыгают все питомцы; текст уведомления показывает первый (основной)."""
        for i, p in enumerate(self.pets):
            p.on_external_notification(app_name, text, show_text=(i == 0))

    # ------------------------------------------------------------ окно / мышь
    def _set_click_through(self, transparent: bool):
        if self._is_click_through == transparent:
            return
        self._is_click_through = transparent
        hwnd = int(self.winId())
        ex_style = user32.GetWindowLongW(hwnd, GWL_EXSTYLE)
        if transparent:
            user32.SetWindowLongW(hwnd, GWL_EXSTYLE, ex_style | WS_EX_TRANSPARENT | WS_EX_LAYERED)
        else:
            user32.SetWindowLongW(hwnd, GWL_EXSTYLE, (ex_style & ~WS_EX_TRANSPARENT) | WS_EX_LAYERED)

    def _pick(self, pos: QPointF, max_dist: float, only_free: bool = False):
        """Ближайший к точке питомец и его узел: (питомец, индекс) или None."""
        best = None
        best_d = float("inf")
        for pet in self.pets:
            if only_free and pet.grabbed_node is not None:
                continue
            idx, d = pet.closest_node(pos, max_dist)
            if idx is not None and d < best_d:
                best_d = d
                best = (pet, idx)
        return best

    def mousePressEvent(self, event):
        hit = self._pick(event.position(), 32.0)
        if hit is None:
            return
        pet, idx = hit
        pet.on_press(event.button(), idx)
        self._select(pet)

    def mouseDoubleClickEvent(self, event):
        if event.button() != Qt.MouseButton.LeftButton:
            return
        hit = self._pick(event.position(), 36.0)
        if hit is not None:
            hit[0].on_double_click()

    def mouseMoveEvent(self, event):
        pos = event.position()
        hit = self._pick(pos, 26.0, only_free=True)
        if hit is not None:
            hit[0].on_petting(pos)

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            for pet in self.pets:
                if pet.grabbed_node is not None:
                    pet.on_release()

    # ------------------------------------------------------------ кадр
    # ------------------------------------------------------------ нагрузка на компьютер
    def set_perf_mode(self, mode: str):
        self.perf.set_mode(mode)
        self._apply_quality()

    def _apply_quality(self):
        q = self.perf.params
        self.snow.set_quality(q["flakes"], q["splash_cap"], q["relax"])

    def _activity(self) -> str:
        """«active»: нужна плавность (взяли кота, прыжок, рыбка, лазер); «still»: все спят и снега не видно; иначе «calm»."""
        if self.fish:
            return "active"
        for p in self.pets:
            if (p.grabbed_node is not None or p.hovered_node is not None or p.airborne or p.laser_mode
                    or p.flip_frames > 0 or p.pile_phase is not None or p.fish_target is not None
                    or p.eat_frames > 0 or p.sink_frames > 0):
                return "active"
        snow_visible = self.snow.enabled and not any(w[5] for w in self.windows_cache)
        if not snow_visible and all(p.state == "sleep" and p.bubble_timer <= 0 for p in self.pets):
            return "still"
        return "calm"

    def perf_report(self) -> str:
        g = self.perf
        mode = tr(PERF_MODES.get(g.mode, g.mode))
        level = tr(QUALITY[g.level]["label"])
        now = tr('{0} (выбрано автоматически)').format(level) if g.mode == "auto" else level
        if not g.measured:
            return tr('Режим: {0}. Сейчас: {1}. Показатели появятся через несколько секунд.').format(mode, now)
        return (tr('Процессор: {0:.1f}% · кадр {1:.1f} мс (логика {2:.1f}, рисование {3:.1f}) · отрисовка {4:.0f} к/с · снежинок {5} · котов {6}\nКачество сейчас: {7}').format(g.cpu_pct, g.cost_ms, g.avg_phys, g.avg_paint, g.render_fps, len(self.snow.flakes), len(self.pets), now))

    def update_physics(self):
        if self.paused:
            self._last_tick_t = None
            if not self.tracker.query_fullscreen():
                self._set_paused(False)
            return
        t0 = self.clock()
        late = 0.0
        if self._last_tick_t is not None:
            gap = t0 - self._last_tick_t
            if gap < 0.25:                               # паузы и сон компьютера не считаем
                late = max(0.0, gap - 0.016)
        self._last_tick_t = t0
        self._painted_now = False
        self._tick_body()
        phys = max(0.0, self.clock() - t0)
        paint, self._paint_acc = self._paint_acc, 0.0
        if self.perf.record_tick(phys, paint, late, self._painted_now):
            self._apply_quality()

    def _tick_body(self):
        g_pos = QCursor.pos()
        local_cursor = QPointF(self.mapFromGlobal(g_pos))
        mouse_vx = (local_cursor.x() - self.last_cursor_pos.x()) * 0.25
        mouse_vy = (local_cursor.y() - self.last_cursor_pos.y()) * 0.25
        self.last_cursor_pos = local_cursor
        self.cursor_pos = local_cursor

        interactive = False
        for pet in self.pets:
            pet.hovered_node = pet.find_closest_node(local_cursor, 30.0)
            if pet.grabbed_node is not None or pet.hovered_node is not None:
                interactive = True
        self._set_click_through(not interactive)

        self.frame_counter += 1
        self.tracker.tick(self.frame_counter)
        closed = self.tracker.take_closed()
        if closed:
            self.snow.collapse_piles(closed)
        if self.pause_on_fullscreen and self.frame_counter % 60 == 0 and self.tracker.query_fullscreen():
            self._set_paused(True)
            return

        self._update_fish()
        self.snow.step(local_cursor, mouse_vx, mouse_vy, self.windows_cache, self.frame_counter)
        for pet in self.pets:
            pet.tick()
        self._ticks_since_paint += 1
        if self._ticks_since_paint >= self.perf.render_divisor(self._activity()):
            self._ticks_since_paint = 0
            self._painted_now = True
            self.update()

    def paintEvent(self, event):
        t_paint = self.clock()
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        # 1. Снег и сугробы
        self.snow.draw(painter, self.windows_cache)

        # 2. Лазерная точка (одна на всех, она следует за курсором)
        if any(p.laser_mode for p in self.pets):
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QColor(255, 30, 30, 90))
            painter.drawEllipse(self.cursor_pos, 11, 11)
            painter.setBrush(QColor(255, 60, 60, 240))
            painter.drawEllipse(self.cursor_pos, 4, 4)

        # 2б. Рыбки
        for f in self.fish:
            draw_fish(painter, f)

        # 3. Питомцы; тот, которого держат мышью, рисуется поверх остальных
        for pet in sorted(self.pets, key=lambda p: p.grabbed_node is not None):
            pet.paint(painter)
        self._paint_acc += self.clock() - t_paint


# =====================================================================
# 5. ЛАУНЧЕР УПРАВЛЕНИЯ (КОТ + ВСТРОЕННЫЙ СНЕГ + README)
# =====================================================================
PATTERN_ICONS = {"none": "🚫", "stripes": "🦓", "spots": "🐆", "socks": "🧦", "tuxedo": "🤵"}
PARTS = [("body", "🧶 Шерсть"), ("belly", "🍼 Животик"), ("limb", "🐾 Лапки"), ("ear_inner", "👂 Ушки"),
         ("eye", "👁 Глаза"), ("nose", "👃 Носик"), ("tail_tip", "🎀 Хвост"), ("pattern_color", "✏️ Узор")]
SWATCHES = ["#181820", "#4A4A55", "#8C8C98", "#D9D9E2", "#FFFFFF", "#7A4B2A", "#B87333", "#E8863A",
            "#F6B26B", "#FAD7A0", "#F2E0C8", "#FF8FA3", "#E63946", "#FF5E7E", "#F4A6D7", "#B388EB",
            "#6C5CE7", "#4D96FF", "#74B9FF", "#2EC4B6", "#55EFC4", "#7BD389", "#FFD166", "#FFEE58"]

KID_QSS = """
QMainWindow { background: qlineargradient(x1:0, y1:0, x2:0, y2:1, stop:0 #2B1B6B, stop:1 #15132F); }
QWidget { color: #F4F1FF; font-family: 'Segoe UI', 'Segoe UI Emoji', sans-serif; font-size: 13px; }
QLabel { background: transparent; }
#title { font-size: 28px; font-weight: 800; color: #FFFFFF; }
#subtitle { font-size: 12px; color: #C9BEFF; }
QTabWidget::pane { border: none; background: transparent; }
QTabBar::tab { background: rgba(255,255,255,24); color: #E2DBFF; padding: 10px 14px; margin-right: 6px;
               border-radius: 14px; font-weight: bold; }
QTabBar::tab:selected { background: #7C5CFF; color: #FFFFFF; }
QTabBar::tab:hover { background: rgba(255,255,255,50); }
#card { background: rgba(255,255,255,22); border: 1px solid rgba(255,255,255,30); border-radius: 18px; }
#cardTitle { font-size: 14px; font-weight: 800; color: #FFD166; }
#hint { color: #C9BEFF; font-size: 12px; }
#cardNumber { font-size: 22px; font-weight: 800; color: #FFD166; padding: 6px 0; }
#patternPanel { background: rgba(124,92,255,45); border: 1px solid rgba(124,92,255,140); border-radius: 14px; }
QPushButton { background: rgba(255,255,255,34); border: none; border-radius: 14px; padding: 12px 14px;
              font-weight: bold; color: #FFFFFF; }
QPushButton:hover { background: rgba(255,255,255,62); }
QPushButton:pressed { background: rgba(255,255,255,90); }
QPushButton:checked { background: #7C5CFF; }
#bigFish { background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #FF9A3C, stop:1 #FF5E7E);
           font-size: 18px; padding: 18px; border-radius: 18px; }
#bigFish:hover { background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #FFB067, stop:1 #FF7C96); }
#good { background: #2ECC71; }
#danger { background: #FF5E7E; }
QComboBox, QLineEdit { background: rgba(255,255,255,28); border: 1px solid rgba(255,255,255,50);
                       border-radius: 12px; padding: 9px 12px; color: #FFFFFF; }
QComboBox QAbstractItemView { background: #26214F; color: #FFFFFF; selection-background-color: #7C5CFF; }
QListWidget { background: rgba(255,255,255,16); border: none; border-radius: 14px; padding: 6px; }
QListWidget::item { padding: 9px; border-radius: 10px; }
QListWidget::item:selected { background: #7C5CFF; color: #FFFFFF; }
QScrollArea { border: none; background: transparent; }
QScrollArea > QWidget > QWidget { background: transparent; }
QScrollBar:vertical { background: transparent; width: 10px; }
QScrollBar::handle:vertical { background: rgba(255,255,255,70); border-radius: 5px; min-height: 30px; }
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0px; }
QTextBrowser { background: transparent; border: none; font-size: 13px; }
"""


def _seg_dist(px, py, ax, ay, bx, by) -> float:
    dx, dy = bx - ax, by - ay
    L2 = dx * dx + dy * dy
    t = 0.0 if L2 == 0 else max(0.0, min(1.0, ((px - ax) * dx + (py - ay) * dy) / L2))
    return math.hypot(px - (ax + t * dx), py - (ay + t * dy))


class CatPreview(QWidget):
    """Большой предпросмотр кота в мастерской. Клик по части кота выбирает, какую часть красить."""
    part_clicked = pyqtSignal(str)
    SCALE = 2.6
    CX, CY = 6.0, -7.0

    def __init__(self, pal: dict):
        super().__init__()
        self.setFixedSize(330, 215)
        self.pal = pal
        pts = [(18, -16), (10, 0), (-14, 0), (6, 22), (14, 22), (-18, 22), (-10, 22),
               (-28, -10), (-38, -22), (12, -30), (24, -30)]
        self.nodes = [RagdollNode(x, y, "") for x, y in pts]

    def set_palette(self, pal: dict):
        self.pal = pal
        self.update()

    def _origin(self):
        return self.width() / 2 - self.CX * self.SCALE, self.height() / 2 - self.CY * self.SCALE

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(255, 255, 255, 22))
        p.drawRoundedRect(QRectF(0, 0, self.width(), self.height()), 20, 20)
        ox, oy = self._origin()
        p.translate(ox, oy)
        p.scale(self.SCALE, self.SCALE)
        p.setBrush(QColor(246, 250, 255, 235))
        p.drawEllipse(QPointF(6.0, 26.0), 66.0, 6.0)
        paint_cat_body(p, self.nodes, self.pal, 1, ground_y=24.0)

    def part_at(self, x: float, y: float):
        n = self.nodes
        hx, hy = n[0].x, n[0].y

        def d(ax, ay):
            return math.hypot(x - ax, y - ay)
        if min(d(hx + 3.0 - 5.2, hy - 2.2), d(hx + 3.0 + 5.2, hy - 2.2)) <= 5.5:
            return "eye"
        if d(hx + 2.1, hy + 4.6) <= 4.5:
            return "nose"
        if d(n[9].x - 2, n[9].y - 6) <= 8 or d(n[10].x + 2, n[10].y - 6) <= 8:
            return "ear_inner"
        if d(n[8].x, n[8].y) <= 9:
            return "tail_tip"
        for i in (3, 4, 5, 6):
            if d(n[i].x, n[i].y) <= 7.5:
                return "limb"
        if d(hx, hy) <= 16:
            return "body"
        if _seg_dist(x, y, n[2].x, n[2].y, n[1].x, n[1].y) <= 13:
            return "belly" if y > (n[1].y + n[2].y) / 2 + 3.5 else "body"
        if _seg_dist(x, y, n[2].x, n[2].y, n[7].x, n[7].y) <= 6 or _seg_dist(x, y, n[7].x, n[7].y, n[8].x, n[8].y) <= 6:
            return "body"
        return None

    def mousePressEvent(self, event):
        pos = event.position()
        ox, oy = self._origin()
        part = self.part_at((pos.x() - ox) / self.SCALE, (pos.y() - oy) / self.SCALE)
        if part is not None:
            self.part_clicked.emit(part)


class CatLauncherWindow(QMainWindow):
    def __init__(self, cat_overlay: CompanionOverlay, watcher: HybridNotificationWatcher):
        super().__init__()
        self.cat = cat_overlay
        self.watcher = watcher
        _cfg_dir = os.environ.get("LOCALAPPDATA", tempfile.gettempdir())
        self.config_path = os.path.join(_cfg_dir, CONFIG_NAME)
        self.legacy_config_path = os.path.join(_cfg_dir, LEGACY_CONFIG_NAME)

        self.custom_colors: list[dict] = []     # сохранённые свои расцветки (в виде словарей)
        self.color_buttons: dict = {}
        self.editor_key = None                  # ключ редактируемой сохранённой расцветки (None: новая)
        self.editor_pal = copy_palette(CAT_PALETTES["ginger"])
        self.editor_part = "body"
        self.editor_pattern_manual = False
        self.part_buttons: dict = {}
        self.pattern_buttons: dict = {}

        self.setMinimumSize(520, 560)
        self.resize(570, 700)
        self.setStyleSheet(KID_QSS)
        self._really_quit = False

        set_language(self._saved_language())
        self.perf_timer = QTimer(self)
        self.perf_timer.timeout.connect(self.update_perf_label)
        self.perf_timer.start(1000)
        self._build_ui()

        self.setup_tray()
        self.cat.selection_changed.connect(self._on_host_selection)
        self.load_config()

    def _saved_language(self) -> str:
        """Язык из настроек; если их нет, язык Windows."""
        for p in (self.config_path, self.legacy_config_path):
            try:
                with open(p, "r", encoding="utf-8") as f:
                    lang = json.load(f).get("language")
                if lang in ("ru", "en"):
                    return lang
            except Exception:
                pass
        return detect_language()

    def _build_ui(self):
        """Строит окно заново на текущем языке (вызывается при запуске и при переключении языка)."""
        self.setWindowTitle(tr(LAUNCHER_TITLE))
        self.color_buttons = {}
        self.part_buttons = {}
        self.pattern_buttons = {}

        central = QWidget()
        self.setCentralWidget(central)
        root = QVBoxLayout(central)
        root.setContentsMargins(18, 16, 18, 14)
        root.setSpacing(10)

        head = QHBoxLayout()
        title = QLabel(tr("🐱 Мой котик"))
        title.setObjectName("title")
        self.btn_lang = QPushButton(LANG_BUTTON_TEXT[get_language()])
        self.btn_lang.setFixedHeight(38)
        self.btn_lang.clicked.connect(self.on_toggle_language)
        head.addWidget(title, 1)
        head.addWidget(self.btn_lang)
        root.addLayout(head)
        subtitle = QLabel(tr("Живой питомец на твоём рабочем столе: ловит снежинки, любит рыбку и носит твои цвета ❄️🐟🎨"))
        subtitle.setObjectName("subtitle")
        subtitle.setWordWrap(True)
        root.addWidget(subtitle)

        self.tabs = QTabWidget()
        root.addWidget(self.tabs, 1)
        self.tabs.addTab(self._build_play_tab(), tr("🏠 Играть"))
        self.tabs.addTab(self._build_pets_tab(), tr("🐾 Мои коты"))
        self.tabs.addTab(self._build_workshop_tab(), tr("🎨 Мастерская"))
        self.tabs.addTab(self._build_about_tab(), tr("📖 О котике"))
        self.tabs.addTab(self._build_donate_tab(), tr("💖 Поддержать"))

    def on_toggle_language(self):
        """Переключает весь интерфейс между русским и английским."""
        set_language("en" if get_language() == "ru" else "ru")
        try:
            idx = int(self.tabs.currentIndex())
        except Exception:
            idx = 0
        self._build_ui()
        self._sync_ui_from_model()
        self._rebuild_tray_menu()
        self.tabs.setCurrentIndex(max(0, min(idx, 4)))
        self.save_config()

    def _sync_ui_from_model(self):
        """После перестройки окна подтягивает состояние кнопок и списков из программы."""
        snow_on = self.cat.snow.enabled
        self.btn_snow.setChecked(snow_on)
        self.btn_snow.setText(tr("❄️ Снег: ВКЛ") if snow_on else tr("❄️ Снег: ВЫКЛ"))
        for combo, value in ((self.app_combo, self.cat.notif_mode), (self.perf_combo, self.cat.perf.mode)):
            combo.blockSignals(True)
            combo.setCurrentIndex(max(0, combo.findData(value)))
            combo.blockSignals(False)
        self.rebuild_color_chips()
        self.rebuild_saved_combo()
        self.editor_refresh()
        self.refresh_pet_list()
        self.update_perf_label()

    # ------------------------------------------------------------------ каркас
    def _make_page(self):
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        inner = QWidget()
        lay = QVBoxLayout(inner)
        lay.setContentsMargins(2, 8, 8, 8)
        lay.setSpacing(12)
        scroll.setWidget(inner)
        return scroll, lay

    def _card(self, title: str):
        frame = QFrame()
        frame.setObjectName("card")
        v = QVBoxLayout(frame)
        v.setContentsMargins(16, 14, 16, 14)
        v.setSpacing(10)
        lbl = QLabel(title)
        lbl.setObjectName("cardTitle")
        v.addWidget(lbl)
        return frame, v

    def _hint(self, text: str) -> QLabel:
        lbl = QLabel(text)
        lbl.setObjectName("hint")
        lbl.setWordWrap(True)
        return lbl

    # ------------------------------------------------------------------ вкладка «Играть»
    def _build_play_tab(self):
        page, lay = self._make_page()

        card, v = self._card(tr("🐟 Покормить котиков"))
        self.btn_fish = QPushButton(tr("🐟  Покормить рыбкой!"))
        self.btn_fish.setObjectName("bigFish")
        self.btn_fish.clicked.connect(self.on_feed)
        self.lbl_fish_info = self._hint("")
        v.addWidget(self.btn_fish)
        v.addWidget(self.lbl_fish_info)
        lay.addWidget(card)

        card, v = self._card(tr("🎮 Игры"))
        grid = QGridLayout()
        grid.setSpacing(10)
        btn_laser = QPushButton(tr("🔴 Лазерная указка"))
        btn_laser.clicked.connect(lambda: self.cat.toggle_laser())
        btn_notif = QPushButton(tr("🔔 Тест уведомления"))
        btn_notif.clicked.connect(lambda: self.cat.on_external_notification("Telegram", tr("Новое сообщение получено!")))
        btn_jump = QPushButton(tr("🏔 Прыжок в сугроб"))
        btn_jump.clicked.connect(lambda: self.cat.pile_demo())
        btn_center = QPushButton(tr("🔄 Кота в центр"))
        btn_center.clicked.connect(lambda: self.cat.reset_cat_position())
        grid.addWidget(btn_laser, 0, 0)
        grid.addWidget(btn_notif, 0, 1)
        grid.addWidget(btn_jump, 1, 0)
        grid.addWidget(btn_center, 1, 1)
        v.addLayout(grid)
        v.addWidget(self._hint(tr("Кот сам прыгает в большие сугробы, когда видит их рядом. Кнопка «Прыжок в сугроб» показывает это сразу.")))
        lay.addWidget(card)

        card, v = self._card(tr("❄️ Снег"))
        row = QHBoxLayout()
        row.setSpacing(10)
        self.btn_snow = QPushButton(tr("❄️ Снег: ВКЛ"))
        self.btn_snow.setCheckable(True)
        self.btn_snow.setChecked(True)
        self.btn_snow.clicked.connect(self.on_toggle_snow)
        btn_clear = QPushButton(tr("🧹 Очистить сугробы"))
        btn_clear.clicked.connect(lambda: self.cat.clear_snow())
        row.addWidget(self.btn_snow)
        row.addWidget(btn_clear)
        v.addLayout(row)
        lay.addWidget(card)

        card, v = self._card(tr("🔔 Уведомления вместо «Мяу»"))
        self.app_combo = QComboBox()
        self.app_combo.addItem(tr("По умолчанию (обычное «Мяу»)"), "default")
        self.app_combo.addItem("Telegram", "telegram")
        self.app_combo.addItem("MAX", "max")
        self.app_combo.addItem(tr("Браузер (Brave / Chrome / Edge)"), "browser")
        self.app_combo.currentIndexChanged.connect(self.on_app_changed)
        v.addWidget(self.app_combo)
        lay.addWidget(card)

        card, v = self._card(tr("⚙️ Нагрузка на компьютер"))
        self.perf_combo = QComboBox()
        for key, label in PERF_MODES.items():
            self.perf_combo.addItem(tr(label), key)
        self.perf_combo.currentIndexChanged.connect(self.on_perf_changed)
        v.addWidget(self.perf_combo)
        self.lbl_perf = self._hint("")
        v.addWidget(self.lbl_perf)
        v.addWidget(self._hint(tr("«Авто» сама делает кота и снег чуть менее плавными, если компьютеру тяжело. «Красиво» плавнее, но заметнее "
                               "нагружает процессор; «Легче» и «Очень лёгкий» экономят заряд и подходят для слабых компьютеров.")))
        lay.addWidget(card)

        btn_hide = QPushButton(tr("Свернуть в трей (кот и снег останутся)"))
        btn_hide.clicked.connect(self.hide)
        lay.addWidget(btn_hide)
        lay.addStretch()
        return page

    # ------------------------------------------------------------------ вкладка «Мои коты»
    def _build_pets_tab(self):
        page, lay = self._make_page()

        card, v = self._card(tr("🐾 Мои коты"))
        v.addWidget(self._hint(tr("Выбери кота в списке (или кликни по нему на экране): окрас, лазер и характер относятся к выбранному.")))
        self.pet_list = QListWidget()
        self.pet_list.setMinimumHeight(120)
        self.pet_list.currentRowChanged.connect(self.on_pet_row_changed)
        v.addWidget(self.pet_list)
        row = QHBoxLayout()
        row.setSpacing(10)
        btn_add = QPushButton(tr("➕ Добавить кота"))
        btn_add.setObjectName("good")
        btn_add.clicked.connect(self.on_add_pet)
        btn_remove = QPushButton(tr("➖ Убрать выбранного"))
        btn_remove.clicked.connect(self.on_remove_pet)
        row.addWidget(btn_add)
        row.addWidget(btn_remove)
        v.addLayout(row)
        self.lbl_pet_limit = self._hint("")
        v.addWidget(self.lbl_pet_limit)
        lay.addWidget(card)

        card, v = self._card(tr("🎨 Окрас выбранного кота"))
        self.lbl_color = self._hint("")
        v.addWidget(self.lbl_color)
        self.chip_holder = QWidget()
        self.chip_layout = QHBoxLayout(self.chip_holder)
        self.chip_layout.setContentsMargins(0, 0, 0, 0)
        self.chip_layout.setSpacing(10)
        self.chip_layout.setAlignment(Qt.AlignmentFlag.AlignLeft)
        v.addWidget(self.chip_holder)
        v.addWidget(self._hint(tr("Свои расцветки можно нарисовать на вкладке «Мастерская» — они появятся здесь.")))
        lay.addWidget(card)
        self.rebuild_color_chips()

        card, v = self._card(tr("🧠 Характер выбранного кота"))
        self.profile_combo = QComboBox()
        for _key, _p in PROFILES.items():
            self.profile_combo.addItem(tr(_p["label"]), _key)
        self.profile_combo.currentIndexChanged.connect(self.on_profile_changed)
        v.addWidget(self.profile_combo)
        lay.addWidget(card)
        lay.addStretch()
        return page

    # ------------------------------------------------------------------ вкладка «Мастерская»
    def _build_workshop_tab(self):
        page, lay = self._make_page()

        card, v = self._card(tr("🎨 Нарисуй своего кота"))
        self.preview = CatPreview(self.editor_pal)
        self.preview.part_clicked.connect(self.on_preview_part)
        v.addWidget(self.preview, 0, Qt.AlignmentFlag.AlignHCenter)
        v.addWidget(self._hint(tr("1. Нажми на часть кота (или на кнопку ниже; «✏️ Узор» откроет выбор узоров).  2. Выбери цвет.  3. Придумай имя и сохрани!")))

        parts = QGridLayout()
        parts.setSpacing(6)
        for i, (key, label) in enumerate(PARTS):
            b = QPushButton(tr(label))
            b.setCheckable(True)
            b.clicked.connect(lambda _=False, k=key: self.on_preview_part(k))
            parts.addWidget(b, i // 4, i % 4)
            self.part_buttons[key] = b
        v.addLayout(parts)

        # панель узоров разворачивается по кнопке «✏️ Узор»
        self.pattern_panel = QFrame()
        self.pattern_panel.setObjectName("patternPanel")
        pp = QVBoxLayout(self.pattern_panel)
        pp.setContentsMargins(12, 10, 12, 10)
        pp.setSpacing(8)
        pp.addWidget(self._hint(tr("Выбери узор. Цвет узора выбирай ниже, среди кружков 🎨")))
        pgrid = QGridLayout()
        pgrid.setSpacing(6)
        for i, (key, label) in enumerate(CAT_PATTERNS.items()):
            b = QPushButton(PATTERN_ICONS.get(key, "") + " " + tr(label))
            b.setCheckable(True)
            b.clicked.connect(lambda _=False, k=key: self.on_pattern_chosen(k))
            pgrid.addWidget(b, i // 3, i % 3)
            self.pattern_buttons[key] = b
        pp.addLayout(pgrid)
        self.pattern_panel.setVisible(False)
        v.addWidget(self.pattern_panel)

        sw = QGridLayout()
        sw.setSpacing(6)
        for i, hexcol in enumerate(SWATCHES):
            b = QPushButton("")
            b.setFixedSize(34, 34)
            b.setStyleSheet(f"QPushButton {{ background: {hexcol}; border: 2px solid rgba(255,255,255,80); border-radius: 17px; padding: 0; }}"
                            f"QPushButton:hover {{ border: 3px solid #FFFFFF; }}")
            b.clicked.connect(lambda _=False, h=hexcol: self.editor_set_color(_from_hex(h, QColor(0, 0, 0))))
            sw.addWidget(b, i // 12, i % 12)
        v.addLayout(sw)
        btn_any = QPushButton(tr("🌈 Любой другой цвет…"))
        btn_any.clicked.connect(self.on_pick_any_color)
        v.addWidget(btn_any)

        self.editor_name = QLineEdit()
        self.editor_name.setPlaceholderText(tr("Имя расцветки (например: Космо-кот)"))
        self.editor_name.setMaxLength(24)
        v.addWidget(self.editor_name)

        row = QHBoxLayout()
        row.setSpacing(8)
        btn_save = QPushButton(tr("💾 Сохранить"))
        btn_save.setObjectName("good")
        btn_save.clicked.connect(self.on_editor_save)
        btn_new = QPushButton(tr("➕ Новая"))
        btn_new.clicked.connect(self.editor_new)
        btn_del = QPushButton(tr("🗑 Удалить"))
        btn_del.setObjectName("danger")
        btn_del.clicked.connect(self.on_editor_delete)
        row.addWidget(btn_save)
        row.addWidget(btn_new)
        row.addWidget(btn_del)
        v.addLayout(row)
        self.lbl_editor_status = self._hint("")
        v.addWidget(self.lbl_editor_status)
        lay.addWidget(card)

        card, v = self._card(tr("📚 Мои расцветки"))
        self.saved_combo = QComboBox()
        self.saved_combo.currentIndexChanged.connect(self.on_saved_picked)
        v.addWidget(self.saved_combo)
        self.lbl_saved_count = self._hint("")
        v.addWidget(self.lbl_saved_count)
        lay.addWidget(card)
        lay.addStretch()
        self.rebuild_saved_combo()
        self.editor_refresh()
        return page

    # ------------------------------------------------------------------ вкладка «О котике»
    def _build_about_tab(self):
        browser = QTextBrowser()
        browser.setHtml(tr("""
        <h2 style="color:#FFD166; margin-top:0;">Что умеет твой котик</h2>

        <h3 style="color:#FF9A9A;">🐟 Рыбка</h3>
        <p>Нажми «Покормить рыбкой»: в случайных местах упадёт по рыбке на каждого кота, и все побегут её есть.</p>

        <h3 style="color:#74B9FF;">🎮 Играй с котом</h3>
        <ul>
            <li><b>Взять за лапу, хвост или ушко:</b> зажми левую кнопку мыши на коте и потяни.</li>
            <li><b>Погладить:</b> води курсором по коту без клика, и он замурлычет.</li>
            <li><b>Сальто:</b> двойной клик по коту.</li>
            <li><b>Лазерная указка:</b> правая кнопка мыши по коту или кнопка «Лазерная указка».</li>
            <li><b>Сугробы:</b> кот топчет снег и поднимает брызги. Когда рядом большой сугроб, кот бежит к нему, прыгает, увязает и поднимает фонтан снега. Маленькие кучки он не замечает.</li>
        </ul>

        <h3 style="color:#55EFC4;">🐾 Много котов и своя расцветка</h3>
        <ul>
            <li>На вкладке «Мои коты» можно добавлять и убирать котов.</li>
            <li>В «Мастерской» раскрась кота как хочешь: цвет шерсти, животика, лапок, ушек, глаз, носика, хвоста, узор (полоски, пятнышки, носочки, смокинг). Можно сохранить до 3 своих расцветок и удалить любую.</li>
        </ul>

        <h3 style="color:#FFEAA7;">🔔 Уведомления</h3>
        <p>Выбери Telegram, MAX или браузер: когда придёт сообщение, кот подпрыгнет и покажет текст над головой.</p>

        <h3 style="color:#FD79A8;">⚙️ Прочее</h3>
        <ul>
            <li><b>Снег</b> можно включить и выключить, а сугробы очистить кнопкой.</li>
            <li><b>Характер:</b> «Активный» (бегает около минуты) или «Спокойный» (засыпает через 25 секунд).</li>
            <li><b>Снег и окна:</b> снег идёт за окнами и ложится на видимую кромку верхнего окна; сугроб едет вместе с окном. Во время полноэкранной игры или видео кот и снег прячутся и не тратят процессор.</li>
            <li><b>Нагрузка:</b> на вкладке «Играть» можно выбрать «Авто», «Красиво», «Сбалансированно», «Легче» или «Очень лёгкий». Там же видно, сколько времени занимает кадр.</li>
            <li><b>Язык:</b> кнопка «🌐 English» в правом верхнем углу переключает весь интерфейс на английский (и обратно).</li>
            <li><b>Один экземпляр:</b> если запустить программу ещё раз, она просто покажет это окно.</li>
        </ul>
        """))
        page = QWidget()
        lay = QVBoxLayout(page)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(8)
        lay.addWidget(browser, 1)
        btn_report = QPushButton(tr("🛠 Сохранить список окон (для поддержки)"))
        btn_report.clicked.connect(self.on_save_windows_report)
        self.lbl_report = self._hint("")
        lay.addWidget(btn_report)
        lay.addWidget(self.lbl_report)
        return page

    # ------------------------------------------------------------------ вкладка «Поддержать»
    def _build_donate_tab(self):
        page, lay = self._make_page()
        info = load_donate_info()
        note = info["note"] or tr("Мой котик")

        card, v = self._card(tr("💖 Поддержать автора"))
        for text in (tr("Привет! 👋 «Мой котик» сделал один человек, и программа бесплатная. Если она подарила тебе улыбку и ты "
                     "хочешь сказать спасибо, можешь отправить любую сумму. Это полностью по желанию и никак не влияет на "
                     "работу программы 💖"),
                     tr('Как перевести:\n1. Переведи деньги на карту ниже.\n2. В комментарии к переводу напиши «{0}» и, если хочешь, свой ник или что понравилось больше всего (кот, снег, рыбки, мастерская). Так я пойму, за что перевод, и смогу сказать тебе спасибо!').format(note),
                     tr("Если тебе нет 18 лет, сначала спроси разрешения у родителей."),
                     tr("Спасибо, что ты с нами! 🐱")):
            lbl = QLabel(text)
            lbl.setWordWrap(True)
            v.addWidget(lbl)
        lay.addWidget(card)

        card, v = self._card(tr("💳 Реквизиты"))
        self.lbl_copy_status = self._hint("")
        if info["card"]:
            number = QLabel(info["card"])
            number.setObjectName("cardNumber")
            number.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
            v.addWidget(number)
            if info["holder"]:
                v.addWidget(self._hint(tr('Получатель: {0}').format(info['holder'])))
            if info["bank"]:
                v.addWidget(self._hint(tr('Банк: {0}').format(info['bank'])))
            btn_copy_card = QPushButton(tr("📋 Скопировать номер карты"))
            btn_copy_card.clicked.connect(lambda: self._copy_text(info["card"]))
            btn_copy_note = QPushButton(tr("📋 Скопировать подпись для перевода"))
            btn_copy_note.clicked.connect(lambda: self._copy_text(note))
            v.addWidget(btn_copy_card)
            v.addWidget(btn_copy_note)
            v.addWidget(self.lbl_copy_status)
        else:
            v.addWidget(self._hint(tr("Реквизиты пока не указаны автором.")))
        lay.addWidget(card)
        lay.addStretch()
        return page

    def _copy_text(self, text: str):
        QApplication.clipboard().setText(text)
        self.lbl_copy_status.setText(tr("Скопировано ✅"))

    def on_save_windows_report(self):
        try:
            path = os.path.join(os.environ.get("LOCALAPPDATA", tempfile.gettempdir()), "DesktopCompanion_windows.txt")
            with open(path, "w", encoding="utf-8") as f:
                f.write(self.cat.windows_report())
            self.lbl_report.setText(tr('Сохранено: {0}').format(path))
        except Exception as e:
            self.lbl_report.setText(tr('Не удалось сохранить: {0}').format(e))

    # ------------------------------------------------------------------ снег / уведомления / характер
    def on_perf_changed(self, idx: int):
        self.cat.set_perf_mode(self.perf_combo.itemData(idx))
        self.update_perf_label()
        self.save_config()

    def update_perf_label(self):
        if self.isVisible():
            self.lbl_perf.setText(self.cat.perf_report())

    def on_toggle_snow(self):
        state = self.cat.toggle_snow()
        self.btn_snow.setChecked(state)
        self.btn_snow.setText(tr("❄️ Снег: ВКЛ") if state else tr("❄️ Снег: ВЫКЛ"))
        self.save_config()

    def on_app_changed(self, *_):
        data = self.app_combo.currentData()
        self.cat.set_notification_mode(data)
        self.watcher.set_filter(data)
        self.save_config()

    def on_profile_changed(self, idx: int):
        key = self.profile_combo.itemData(idx)
        self.cat.set_profile(key, announce=True)
        self.refresh_pet_list()
        self.save_config()

    # ------------------------------------------------------------------ рыбка
    def on_feed(self):
        n = self.cat.drop_fish()
        if n == 0:
            pet = self.cat.pet
            if pet is not None:
                pet.show_bubble(tr("Я ещё не доел! 🐟"), 100, wake=False)
            self.lbl_fish_info.setText(tr("Коты ещё едят! Подожди, пока доедят 🐟"))
        else:
            self.lbl_fish_info.setText(tr('Упало рыбок: {0} 🐟 — по одной на каждого кота. Смотри, как они бегут!').format(n))

    # ------------------------------------------------------------------ питомцы и цвета-чипы
    def rebuild_color_chips(self):
        for b in self.color_buttons.values():
            b.setParent(None)
            b.deleteLater()
        self.color_buttons = {}
        for key in list(BUILTIN_COLORS) + [d["key"] for d in self.custom_colors]:
            pal = CAT_PALETTES.get(key)
            if pal is None:
                continue
            body, belly = _hex(pal["body"]), _hex(pal["belly"])
            btn = QPushButton("")
            btn.setCheckable(True)
            btn.setToolTip(color_label(key))
            btn.setFixedSize(48, 48)
            btn.setStyleSheet(
                "QPushButton { background: qlineargradient(x1:0, y1:0, x2:0, y2:1, "
                f"stop:0 {body}, stop:0.6 {body}, stop:0.61 {belly}, stop:1 {belly}); "
                "border: 3px solid rgba(255,255,255,80); border-radius: 24px; padding: 0; }"
                "QPushButton:hover { border-color: #FFFFFF; }"
                "QPushButton:checked { border: 4px solid #FFD166; }")
            btn.clicked.connect(lambda _=False, k=key: self.select_color(k))
            self.chip_layout.addWidget(btn)
            self.color_buttons[key] = btn

    def select_color(self, color_key: str, save: bool = True):
        self.cat.set_color(color_key)
        self.refresh_pet_list()
        if save:
            self.save_config()

    def refresh_pet_list(self):
        """Перерисовывает список котов и подстраивает чипы цвета и характер под выбранного."""
        pets = self.cat.pets
        sel = self.cat.selected_index
        self.pet_list.blockSignals(True)
        self.pet_list.clear()
        for p in pets:
            mode = tr("активный") if p.profile == "active" else tr("спокойный")
            self.pet_list.addItem(f"🐱 {p.name} — {color_label(p.color_key)}, {mode}")
        if 0 <= sel < len(pets):
            self.pet_list.setCurrentRow(sel)
        self.pet_list.blockSignals(False)

        pet = self.cat.pet
        if pet is not None:
            for key, btn in self.color_buttons.items():
                btn.setChecked(key == pet.color_key)
            self.profile_combo.blockSignals(True)
            self.profile_combo.setCurrentIndex(max(0, self.profile_combo.findData(pet.profile)))
            self.profile_combo.blockSignals(False)
            self.lbl_color.setText(f"{pet.name}: {color_label(pet.color_key)}")
        self.lbl_pet_limit.setText(tr('Котов: {0} из {1}').format(len(pets), self.cat.max_pets))
        if not self.cat.fish:
            self.lbl_fish_info.setText(tr('Выдаст рыбок: {0} 🐟 (по одной на каждого кота)').format(len(pets)))

    def on_pet_row_changed(self, row: int):
        if row < 0:
            return
        self.cat.select_index(row)
        self.refresh_pet_list()

    def _on_host_selection(self):
        self.refresh_pet_list()

    def on_add_pet(self):
        pet = self.cat.add_pet(announce=True)
        if pet is None:
            if self.cat.pet:
                self.cat.pet.show_bubble(tr('Больше {0} котов пока нельзя 🐾').format(self.cat.max_pets), 120)
            return
        self.cat.select_index(len(self.cat.pets) - 1)
        self.refresh_pet_list()
        self.save_config()

    def on_remove_pet(self):
        pet = self.cat.pet
        if pet is None:
            return
        if len(self.cat.pets) <= 1:
            pet.show_bubble(tr("Последнего кота убрать нельзя 🐾"), 120)
            return
        self.cat.remove_pet(pet)
        self.refresh_pet_list()
        self.save_config()

    # ------------------------------------------------------------------ мастерская
    def editor_refresh(self):
        self.preview.set_palette(self.editor_pal)
        for key, b in self.part_buttons.items():
            b.setChecked(key == self.editor_part)
        self.pattern_panel.setVisible(self.editor_part == "pattern_color")
        for key, b in self.pattern_buttons.items():
            b.setChecked(key == self.editor_pal.get("pattern", "none"))

    def on_preview_part(self, part: str):
        self.editor_part = part
        self.editor_refresh()

    def editor_set_color(self, color: QColor):
        self.editor_pal[self.editor_part] = QColor(color)
        if self.editor_part == "pattern_color":
            self.editor_pattern_manual = True
        self.editor_refresh()

    def on_pick_any_color(self):
        start = self.editor_pal.get(self.editor_part, QColor(255, 255, 255))
        color = QColorDialog.getColor(QColor(start), self, tr("Выбери любой цвет"))
        if color.isValid():
            self.editor_set_color(color)

    def on_pattern_chosen(self, key: str):
        if key not in CAT_PATTERNS:
            return
        self.editor_pal["pattern"] = key
        if not self.editor_pattern_manual:
            body = self.editor_pal["body"]
            if key in ("socks", "tuxedo"):
                self.editor_pal["pattern_color"] = QColor(250, 250, 252)
            elif key in ("stripes", "spots"):
                self.editor_pal["pattern_color"] = QColor(int(body.red() * 0.55), int(body.green() * 0.55), int(body.blue() * 0.55))
        self.editor_refresh()

    def editor_new(self):
        """Новая расцветка: за основу берём окрас выбранного кота."""
        pet = self.cat.pet
        base = CAT_PALETTES.get(pet.color_key) if pet is not None else None
        self.editor_pal = copy_palette(base or CAT_PALETTES["ginger"])
        self.editor_key = None
        self.editor_pattern_manual = False
        self.editor_name.setText("")
        self.lbl_editor_status.setText(tr("Новая расцветка: начни с любой части кота 🎨"))
        self.rebuild_saved_combo()
        self.editor_refresh()

    def rebuild_saved_combo(self):
        self.saved_combo.blockSignals(True)
        self.saved_combo.clear()
        self.saved_combo.addItem(tr("✨ Новая расцветка"), None)
        pick = 0
        for i, d in enumerate(self.custom_colors):
            self.saved_combo.addItem(d.get("name", tr("Мой кот")), d["key"])
            if d["key"] == self.editor_key:
                pick = i + 1
        self.saved_combo.setCurrentIndex(pick)
        self.saved_combo.blockSignals(False)
        self.lbl_saved_count.setText(tr('Своих расцветок: {0} из {1}').format(len(self.custom_colors), CUSTOM_COLOR_MAX))

    def on_saved_picked(self, idx: int):
        key = self.saved_combo.itemData(idx)
        if key is None:
            self.editor_new()
            return
        d = next((c for c in self.custom_colors if c["key"] == key), None)
        if d is None:
            return
        self.editor_pal = palette_from_dict(d)
        self.editor_key = key
        self.editor_pattern_manual = True
        self.editor_name.setText(d.get("name", ""))
        self.lbl_editor_status.setText(tr("Меняй цвета и нажми «Сохранить», чтобы обновить расцветку"))
        self.editor_refresh()

    def _free_custom_key(self):
        used = {d["key"] for d in self.custom_colors}
        for i in range(1, CUSTOM_COLOR_MAX + 1):
            if f"custom{i}" not in used:
                return f"custom{i}"
        return None

    def on_editor_save(self):
        name = self.editor_name.text().strip() or tr('Мой кот {0}').format(len(self.custom_colors) + 1)
        key = self.editor_key
        if key is None:
            key = self._free_custom_key() if len(self.custom_colors) < CUSTOM_COLOR_MAX else None
            if key is None:
                self.lbl_editor_status.setText(tr('Уже {0} своих расцветки. Удали одну 🗑, чтобы сохранить новую').format(CUSTOM_COLOR_MAX))
                return
        entry = palette_to_dict(key, name, self.editor_pal)
        for i, d in enumerate(self.custom_colors):
            if d["key"] == key:
                self.custom_colors[i] = entry
                break
        else:
            self.custom_colors.append(entry)
        register_custom_palette(entry)
        self.editor_key = key
        self.rebuild_color_chips()
        self.rebuild_saved_combo()
        self.cat.set_color(key)          # сразу надеваем на выбранного кота
        self.refresh_pet_list()
        self.lbl_editor_status.setText(tr('Сохранено: «{0}» 🎉 Она появилась в выборе цвета на вкладке «Мои коты»').format(name))
        self.save_config()

    def on_editor_delete(self):
        key = self.editor_key
        if key is None:
            self.lbl_editor_status.setText(tr("Выбери сохранённую расцветку в списке «Мои расцветки», чтобы удалить её"))
            return
        self.custom_colors = [d for d in self.custom_colors if d["key"] != key]
        unregister_custom_palette(key)
        self.cat.remove_color(key)
        self.editor_key = None
        self.rebuild_color_chips()
        self.rebuild_saved_combo()
        self.refresh_pet_list()
        self.lbl_editor_status.setText(tr("Расцветка удалена 🗑"))
        self.save_config()

    # ------------------------------------------------------------------ настройки
    def save_config(self):
        try:
            pets = self.cat.pets_config()
            first = pets[0] if pets else {"color": "black", "profile": DEFAULT_PROFILE}
            data = {
                "color": first["color"],        # первый кот дублируется для совместимости со старыми версиями
                "profile": first["profile"],
                "pets": pets,
                "custom_colors": self.custom_colors,
                "max_pets": self.cat.max_pets,
                "pause_on_fullscreen": self.cat.pause_on_fullscreen,
                "perf_mode": self.cat.perf.mode,
                "notify": self.app_combo.currentData(),
                "language": get_language(),
                "snow_enabled": self.cat.snow.enabled,
            }
            with open(self.config_path, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False)
        except Exception:
            pass

    def load_config(self):
        src_path = self.config_path if os.path.exists(self.config_path) else self.legacy_config_path
        if os.path.exists(src_path):
            try:
                with open(src_path, "r", encoding="utf-8") as f:
                    data = json.load(f)

                # 1. свои расцветки (раньше котов: коты могут ходить в них)
                for d in (data.get("custom_colors") or [])[:CUSTOM_COLOR_MAX]:
                    if isinstance(d, dict) and re.fullmatch(r"custom[1-9]", str(d.get("key", ""))) \
                            and all(d["key"] != c["key"] for c in self.custom_colors):
                        register_custom_palette(d)
                        self.custom_colors.append(palette_to_dict(d["key"], str(d.get("name", tr("Мой кот")))[:24], CAT_PALETTES[d["key"]]))
                self.rebuild_color_chips()

                try:
                    self.cat.max_pets = max(1, min(20, int(data.get("max_pets", MAX_PETS))))
                except Exception:
                    self.cat.max_pets = MAX_PETS
                self.cat.pause_on_fullscreen = bool(data.get("pause_on_fullscreen", True))
                pm = data.get("perf_mode", "auto")
                pm = pm if pm in PERF_MODES else "auto"
                self.perf_combo.blockSignals(True)
                self.perf_combo.setCurrentIndex(max(0, self.perf_combo.findData(pm)))
                self.perf_combo.blockSignals(False)
                self.cat.set_perf_mode(pm)

                # 2. коты
                pets_cfg = data.get("pets")
                if not isinstance(pets_cfg, list) or not pets_cfg:
                    pets_cfg = [{"color": data.get("color", "black"), "profile": data.get("profile", DEFAULT_PROFILE)}]
                self.cat.apply_pets_config(pets_cfg)

                # 3. снег и уведомления
                snow_on = bool(data.get("snow_enabled", True))
                self.cat.snow.enabled = snow_on
                self.btn_snow.setChecked(snow_on)
                self.btn_snow.setText(tr("❄️ Снег: ВКЛ") if snow_on else tr("❄️ Снег: ВЫКЛ"))

                notify = data.get("notify")
                if notify is None:      # конфиг старых версий хранил номер пункта списка
                    try:
                        notify = {1: "telegram", 2: "browser", 3: "browser"}.get(int(data.get("app_index", 0) or 0), "default")
                    except Exception:
                        notify = "default"
                if notify not in ("default", "telegram", "max", "browser"):
                    notify = "default"
                self.app_combo.setCurrentIndex(max(0, self.app_combo.findData(notify)))
            except Exception:
                pass
        self.refresh_pet_list()
        self.editor_new()

    # ------------------------------------------------------------------ трей
    def setup_tray(self):
        pix = QPixmap(32, 32)
        pix.fill(Qt.GlobalColor.transparent)
        painter = QPainter(pix)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setBrush(QColor(124, 92, 255))
        painter.setPen(Qt.PenStyle.NoPen)
        painter.drawEllipse(2, 2, 28, 28)
        painter.setBrush(QColor(255, 255, 255))
        painter.drawEllipse(9, 11, 5, 6)
        painter.drawEllipse(18, 11, 5, 6)
        painter.end()

        tray_icon = QIcon(pix)
        icon_file = resource_path("cat.ico")
        if os.path.exists(icon_file):
            tray_icon = QIcon(icon_file)
        self.tray = QSystemTrayIcon(tray_icon, self)
        self.tray.activated.connect(
            lambda reason: self.bring_to_front() if reason == QSystemTrayIcon.ActivationReason.DoubleClick else None
        )
        self._rebuild_tray_menu()
        self.tray.show()

    def _rebuild_tray_menu(self):
        """Меню значка в трее (пересобирается при смене языка)."""
        menu = QMenu()
        act_open = QAction(tr("Открыть окно котика"), self)
        act_fish = QAction(tr("Покормить рыбкой"), self)
        act_snow = QAction(tr("Вкл/Выкл Снег"), self)
        act_clear = QAction(tr("Очистить сугробы"), self)
        act_reset = QAction(tr("Вернуть кота в центр"), self)
        act_laser = QAction(tr("Вкл/Выкл лазер"), self)
        act_add_pet = QAction(tr("Добавить кота"), self)
        act_exit = QAction(tr("Полный выход"), self)
        for a in (act_open, act_fish, act_snow, act_clear, act_reset, act_laser, act_add_pet):
            menu.addAction(a)
        menu.addSeparator()
        menu.addAction(act_exit)
        self._tray_menu = menu
        self._tray_actions = [act_open, act_fish, act_snow, act_clear, act_reset, act_laser, act_add_pet, act_exit]
        self.tray.setContextMenu(menu)

        act_open.triggered.connect(self.bring_to_front)
        act_fish.triggered.connect(self.on_feed)
        act_snow.triggered.connect(self.on_toggle_snow)
        act_clear.triggered.connect(lambda: self.cat.clear_snow())
        act_reset.triggered.connect(lambda: self.cat.reset_cat_position())
        act_laser.triggered.connect(lambda: self.cat.toggle_laser())
        act_add_pet.triggered.connect(self.on_add_pet)
        act_exit.triggered.connect(self.quit_app)

    def bring_to_front(self):
        """Вызывается, когда пользователь запустил приложение повторно или кликнул по трею."""
        self.showNormal()
        self.raise_()
        self.activateWindow()
        try:
            user32.SetForegroundWindow(ctypes.c_void_p(int(self.winId())))
        except Exception:
            pass

    def quit_app(self):
        """«Полный выход» из трея закрывает всё приложение (крестик окна закрывает только лаунчер)."""
        self._really_quit = True
        try:
            self.tray.hide()
        except Exception:
            pass
        QApplication.instance().quit()

    def closeEvent(self, event):
        if self._really_quit:       # Qt при выходе закрывает все окна: пропускаем, иначе выход «застревает» на лаунчере
            event.accept()
            return
        event.ignore()
        self.hide()


# =====================================================================
# Перевод интерфейса на английский (ключ: русский текст)
# =====================================================================
EN.update({
    '\n        <h2 style="color:#FFD166; margin-top:0;">Что умеет твой котик</h2>\n\n        <h3 style="color:#FF9A9A;">🐟 Рыбка</h3>\n        <p>Нажми «Покормить рыбкой»: в случайных местах упадёт по рыбке на каждого кота, и все побегут её есть.</p>\n\n        <h3 style="color:#74B9FF;">🎮 Играй с котом</h3>\n        <ul>\n            <li><b>Взять за лапу, хвост или ушко:</b> зажми левую кнопку мыши на коте и потяни.</li>\n            <li><b>Погладить:</b> води курсором по коту без клика, и он замурлычет.</li>\n            <li><b>Сальто:</b> двойной клик по коту.</li>\n            <li><b>Лазерная указка:</b> правая кнопка мыши по коту или кнопка «Лазерная указка».</li>\n            <li><b>Сугробы:</b> кот топчет снег и поднимает брызги. Когда рядом большой сугроб, кот бежит к нему, прыгает, увязает и поднимает фонтан снега. Маленькие кучки он не замечает.</li>\n        </ul>\n\n        <h3 style="color:#55EFC4;">🐾 Много котов и своя расцветка</h3>\n        <ul>\n            <li>На вкладке «Мои коты» можно добавлять и убирать котов.</li>\n            <li>В «Мастерской» раскрась кота как хочешь: цвет шерсти, животика, лапок, ушек, глаз, носика, хвоста, узор (полоски, пятнышки, носочки, смокинг). Можно сохранить до 3 своих расцветок и удалить любую.</li>\n        </ul>\n\n        <h3 style="color:#FFEAA7;">🔔 Уведомления</h3>\n        <p>Выбери Telegram, MAX или браузер: когда придёт сообщение, кот подпрыгнет и покажет текст над головой.</p>\n\n        <h3 style="color:#FD79A8;">⚙️ Прочее</h3>\n        <ul>\n            <li><b>Снег</b> можно включить и выключить, а сугробы очистить кнопкой.</li>\n            <li><b>Характер:</b> «Активный» (бегает около минуты) или «Спокойный» (засыпает через 25 секунд).</li>\n            <li><b>Снег и окна:</b> снег идёт за окнами и ложится на видимую кромку верхнего окна; сугроб едет вместе с окном. Во время полноэкранной игры или видео кот и снег прячутся и не тратят процессор.</li>\n            <li><b>Нагрузка:</b> на вкладке «Играть» можно выбрать «Авто», «Красиво», «Сбалансированно», «Легче» или «Очень лёгкий». Там же видно, сколько времени занимает кадр.</li>\n            <li><b>Язык:</b> кнопка «🌐 English» в правом верхнем углу переключает весь интерфейс на английский (и обратно).</li>\n            <li><b>Один экземпляр:</b> если запустить программу ещё раз, она просто покажет это окно.</li>\n        </ul>\n        ': '\n        <h2 style="color:#FFD166; margin-top:0;">What your kitty can do</h2>\n\n        <h3 style="color:#FF9A9A;">🐟 Fish</h3>\n        <p>Press "Feed some fish": one fish per cat will drop in random places and everyone runs to eat it.</p>\n\n        <h3 style="color:#74B9FF;">🎮 Play with the cat</h3>\n        <ul>\n            <li><b>Grab a paw, tail or ear:</b> hold the left mouse button on the cat and drag.</li>\n            <li><b>Pet it:</b> move the cursor over the cat without clicking and it will purr.</li>\n            <li><b>Flip:</b> double-click the cat.</li>\n            <li><b>Laser pointer:</b> right-click the cat or use the "Laser pointer" button.</li>\n            <li><b>Snowdrifts:</b> the cat tramples the snow and kicks up splashes. When there is a big snowdrift nearby, the cat runs to it, jumps in, sinks and sends up a fountain of snow. It ignores small piles.</li>\n        </ul>\n\n        <h3 style="color:#55EFC4;">🐾 Many cats and your own colors</h3>\n        <ul>\n            <li>On the "My cats" tab you can add and remove cats.</li>\n            <li>In the "Workshop" color the cat any way you like: fur, tummy, paws, ears, eyes, nose, tail and pattern (stripes, spots, socks, tuxedo). You can save up to 3 of your own color schemes and delete any of them.</li>\n        </ul>\n\n        <h3 style="color:#FFEAA7;">🔔 Notifications</h3>\n        <p>Choose Telegram, MAX or a browser: when a message arrives, the cat jumps and shows the text above its head.</p>\n\n        <h3 style="color:#FD79A8;">⚙️ More</h3>\n        <ul>\n            <li><b>Snow</b> can be switched on and off, and the snowdrifts can be cleared with a button.</li>\n            <li><b>Personality:</b> "Active" (runs for about a minute) or "Calm" (falls asleep after 25 seconds).</li>\n            <li><b>Snow and windows:</b> snow falls behind windows and settles on the visible edge of the top window; the snowdrift travels with the window. During a fullscreen game or video the cat and snow hide and use almost no CPU.</li>\n            <li><b>Computer load:</b> on the "Play" tab you can choose "Auto", "Beautiful", "Balanced", "Lighter" or "Very light". It also shows how long a frame takes.</li>\n            <li><b>Language:</b> the language button in the top right corner switches the whole interface between English and Russian.</li>\n            <li><b>One instance:</b> if you start the program again, it simply shows this window.</li>\n        </ul>\n        ',
    '1. Нажми на часть кота (или на кнопку ниже; «✏️ Узор» откроет выбор узоров).  2. Выбери цвет.  3. Придумай имя и сохрани!': '1. Tap a part of the cat (or a button below; "✏️ Pattern" opens the pattern choices).  2. Pick a color.  3. Give it a name and save!',
    '{0} (выбрано автоматически)': '{0} (chosen automatically)',
    '{0} hwnd={1} класс={2} заголовок={3!r} рамка=({4},{5},{6},{7}) style=0x{8:08x} ex=0x{9:08x}': '{0} hwnd={1} class={2} title={3!r} frame=({4},{5},{6},{7}) style=0x{8:08x} ex=0x{9:08x}',
    '«Авто» сама делает кота и снег чуть менее плавными, если компьютеру тяжело. «Красиво» плавнее, но заметнее нагружает процессор; «Легче» и «Очень лёгкий» экономят заряд и подходят для слабых компьютеров.': '"Auto" makes the cat and snow a little less smooth by itself when your computer is struggling. "Beautiful" is smoother but uses noticeably more CPU; "Lighter" and "Very light" save power and suit weak computers.',
    'Банк: {0}': 'Bank: {0}',
    'Больше {0} котов пока нельзя 🐾': 'No more than {0} cats for now 🐾',
    'Браузер (Brave / Chrome / Edge)': 'Browser (Brave / Chrome / Edge)',
    'Вернуть кота в центр': 'Put the cat back in the center',
    'Вкл/Выкл Снег': 'Snow on/off',
    'Вкл/Выкл лазер': 'Laser on/off',
    'Вкуснятина! 😻': 'Yummy! 😻',
    'Выбери кота в списке (или кликни по нему на экране): окрас, лазер и характер относятся к выбранному.': 'Pick a cat in the list (or click it on the screen): color, laser and personality apply to the selected one.',
    'Выбери любой цвет': 'Pick any color',
    'Выбери сохранённую расцветку в списке «Мои расцветки», чтобы удалить её': 'Pick a saved color scheme in "My color schemes" to delete it',
    'Выбери узор. Цвет узора выбирай ниже, среди кружков 🎨': 'Pick a pattern. Choose the pattern color below, among the circles 🎨',
    'Выдаст рыбок: {0} 🐟 (по одной на каждого кота)': 'Will drop {0} fish 🐟 (one for each cat)',
    'Добавить кота': 'Add a cat',
    'Если тебе нет 18 лет, сначала спроси разрешения у родителей.': 'If you are under 18, please ask your parents for permission first.',
    'Живой питомец на твоём рабочем столе: ловит снежинки, любит рыбку и носит твои цвета ❄️🐟🎨': 'A living pet on your desktop: catches snowflakes, loves fish and wears your colors ❄️🐟🎨',
    'За ушко щекотно!': 'My ear tickles!',
    'Имя расцветки (например: Космо-кот)': 'Color scheme name (for example: Space Cat)',
    'Как перевести:\n1. Переведи деньги на карту ниже.\n2. В комментарии к переводу напиши «{0}» и, если хочешь, свой ник или что понравилось больше всего (кот, снег, рыбки, мастерская). Так я пойму, за что перевод, и смогу сказать тебе спасибо!': 'How to send:\n1. Transfer the money to the card below.\n2. In the payment comment write "{0}" and, if you like, your nickname or what you liked most (the cat, snow, fish, workshop). That way I will know what the payment is for and can say thank you!',
    'Какой сугроб! ❄️': 'What a snowdrift! ❄️',
    'Кот сам прыгает в большие сугробы, когда видит их рядом. Кнопка «Прыжок в сугроб» показывает это сразу.': 'The cat jumps into big snowdrifts by itself when it sees them nearby. The "Snowdrift jump" button shows it right away.',
    'Котов: {0} из {1}': 'Cats: {0} of {1}',
    'Коты ещё едят! Подожди, пока доедят 🐟': 'The cats are still eating! Wait until they finish 🐟',
    'Ловлю снежинку! ❄️': 'Catching a snowflake! ❄️',
    'Меняй цвета и нажми «Сохранить», чтобы обновить расцветку': 'Change the colors and press "Save" to update the color scheme',
    'Мой кот': 'My cat',
    'Мой кот {0}': 'My cat {0}',
    'Мой котик': 'My Kitty',
    'Мрр?': 'Mrr?',
    'Мррр': 'Purr',
    'Мррр, рыбка!': 'Purr, fishy!',
    'Мррр... ❤️': 'Purrr... ❤️',
    'Мяу ❤️': 'Meow ❤️',
    'Мяу!': 'Meow!',
    'Мяу! Новый окрас ✨': 'Meow! New colors ✨',
    'Мяу~': 'Meow~',
    'Не удалось сохранить: {0}': 'Could not save: {0}',
    'Новая расцветка: начни с любой части кота 🎨': 'New color scheme: start with any part of the cat 🎨',
    'Новое сообщение получено!': 'New message received!',
    'Новое сообщение! 💬': 'New message! 💬',
    'Новое уведомление!': 'New notification!',
    'Новых: {0} ({1})': 'New: {0} ({1})',
    'Ням! 🐟': 'Yum! 🐟',
    'Ой, за лапу! 🐾': 'Ouch, my paw! 🐾',
    'Открыть окно котика': 'Open the kitty window',
    'Охота за лазером! 🔴': 'Hunting the laser! 🔴',
    'Очистить сугробы': 'Clear the snowdrifts',
    'Питомец {0}': 'Pet {0}',
    'По умолчанию (обычное «Мяу»)': 'Default (plain "Meow")',
    'Покормить рыбкой': 'Feed some fish',
    'Полный выход': 'Quit completely',
    'Полный экран сейчас: {0}': 'Fullscreen app now: {0}',
    'Получатель: {0}': 'Recipient: {0}',
    'Последнего кота убрать нельзя 🐾': "You can't remove the last cat 🐾",
    'Привет! 🐾': 'Hello! 🐾',
    'Привет! 👋 «Мой котик» сделал один человек, и программа бесплатная. Если она подарила тебе улыбку и ты хочешь сказать спасибо, можешь отправить любую сумму. Это полностью по желанию и никак не влияет на работу программы 💖': 'Hi! 👋 "My Kitty" was made by one person, and the program is free. If it made you smile and you would like to say thanks, you can send any amount. It is entirely optional and does not affect how the program works 💖',
    'Процессор: {0:.1f}% · кадр {1:.1f} мс (логика {2:.1f}, рисование {3:.1f}) · отрисовка {4:.0f} к/с · снежинок {5} · котов {6}\nКачество сейчас: {7}': 'CPU: {0:.1f}% · frame {1:.1f} ms (logic {2:.1f}, drawing {3:.1f}) · rendering {4:.0f} fps · snowflakes {5} · cats {6}\nQuality now: {7}',
    'Пуф! ❄️': 'Poof! ❄️',
    'Расцветка удалена 🗑': 'Color scheme deleted 🗑',
    'Режим: {0}. Сейчас: {1}. Показатели появятся через несколько секунд.': 'Mode: {0}. Now: {1}. Numbers will appear in a few seconds.',
    'Режим: активный 🏃': 'Mode: active 🏃',
    'Режим: обычное Мяу 🐾': 'Mode: plain Meow 🐾',
    'Режим: спокойный 😺': 'Mode: calm 😺',
    'Реквизиты пока не указаны автором.': 'The author has not added payment details yet.',
    'Рыбка! 🐟': 'Fish! 🐟',
    'Сальто! 🐾': 'Flip! 🐾',
    'Свернуть в трей (кот и снег останутся)': 'Minimize to tray (the cat and snow stay)',
    'Свои расцветки можно нарисовать на вкладке «Мастерская» — они появятся здесь.': 'You can design your own color schemes in the "Workshop" tab; they will appear here.',
    'Своих расцветок: {0} из {1}': 'Your color schemes: {0} of {1}',
    'Скопировано ✅': 'Copied ✅',
    'Слой: {0}x{1}, масштаб экрана {2}, начало {3}': 'Layer: {0}x{1}, screen scale {2}, origin {3}',
    'Сначала включи снег ❄️': 'Turn the snow on first ❄️',
    'Снег выключен ☀️': 'Snow is off ☀️',
    'Снежок! ❄️': 'Snowball! ❄️',
    'События Windows работают: {0}': 'Windows events working: {0}',
    'Сохранено: {0}': 'Saved: {0}',
    'Сохранено: «{0}» 🎉 Она появилась в выборе цвета на вкладке «Мои коты»': 'Saved: "{0}" 🎉 It now appears in the color choices on the "My cats" tab',
    'Спасибо, что ты с нами! 🐱': 'Thank you for being with us! 🐱',
    'Сугроб! Мой!': 'A snowdrift! Mine!',
    'Сугробы расчищены! 🧹': 'Snowdrifts cleared! 🧹',
    'Тону в сугробе! ⛄': "I'm sinking in the snowdrift! ⛄",
    'Тут негде прыгать 🐾': 'Nowhere to jump here 🐾',
    'УЧТЕНО   ': 'USED     ',
    'Уведомление': 'Notification',
    'Уведомления: {0} 🔔': 'Notifications: {0} 🔔',
    'Уже {0} своих расцветки. Удали одну 🗑, чтобы сохранить новую': 'You already have {0} color schemes. Delete one 🗑 to save a new one',
    'Уиии!': 'Wheee!',
    'Упало рыбок: {0} 🐟 — по одной на каждого кота. Смотри, как они бегут!': 'Fish dropped: {0} 🐟, one for each cat. Watch them run!',
    'Ура, пушистый снег! ❄️': 'Hooray, fluffy snow! ❄️',
    'Ууух, глубоко!': "Whoa, it's deep!",
    'Учтено окон: {0}': 'Windows used: {0}',
    'Фух, набегался!': 'Phew, that was a lot of running!',
    'Хвост не тяни! 🙀': "Don't pull my tail! 🙀",
    'Хрусь-хрусь 🐾': 'Crunch crunch 🐾',
    'Ща как прыгну! 🐾': "I'm gonna jump! 🐾",
    'Эй, а где сугроб? 🙀': 'Hey, where is the snowdrift? 🙀',
    'Я ещё не доел! 🐟': "I'm not done eating! 🐟",
    'активный': 'active',
    'пропущено': 'skipped  ',
    'спокойный': 'calm',
    '⚙️ Нагрузка на компьютер': '⚙️ Computer load',
    '✨ Новая расцветка': '✨ New color scheme',
    '❄️ Снег': '❄️ Snow',
    '❄️ Снег: ВКЛ': '❄️ Snow: ON',
    '❄️ Снег: ВЫКЛ': '❄️ Snow: OFF',
    '➕ Добавить кота': '➕ Add a cat',
    '➕ Новая': '➕ New',
    '➖ Убрать выбранного': '➖ Remove selected',
    '🌈 Любой другой цвет…': '🌈 Any other color…',
    '🎨 Мастерская': '🎨 Workshop',
    '🎨 Нарисуй своего кота': '🎨 Design your cat',
    '🎨 Окрас выбранного кота': "🎨 Selected cat's colors",
    '🎮 Игры': '🎮 Games',
    '🏔 Прыжок в сугроб': '🏔 Snowdrift jump',
    '🏠 Играть': '🏠 Play',
    '🐟  Покормить рыбкой!': '🐟  Feed some fish!',
    '🐟 Покормить котиков': '🐟 Feed the cats',
    '🐱 Мой котик': '🐱 My Kitty',
    '🐾 Мои коты': '🐾 My cats',
    '💖 Поддержать': '💖 Support',
    '💖 Поддержать автора': '💖 Support the author',
    '💳 Реквизиты': '💳 Payment details',
    '💾 Сохранить': '💾 Save',
    '📋 Скопировать номер карты': '📋 Copy card number',
    '📋 Скопировать подпись для перевода': '📋 Copy payment comment',
    '📖 О котике': '📖 About',
    '📚 Мои расцветки': '📚 My color schemes',
    '🔄 Кота в центр': '🔄 Cat to center',
    '🔔 Тест уведомления': '🔔 Test notification',
    '🔔 Уведомления вместо «Мяу»': '🔔 Notifications instead of "Meow"',
    '🔴 Лазерная указка': '🔴 Laser pointer',
    '🗑 Удалить': '🗑 Delete',
    '🛠 Сохранить список окон (для поддержки)': '🛠 Save window list (for support)',
    '🧠 Характер выбранного кота': "🧠 Selected cat's personality",
    '🧹 Очистить сугробы': '🧹 Clear snowdrifts',
    'Авто (рекомендуется)': 'Auto (recommended)',
    'Активный (как в BlackCat, бегает ~65 с)': 'Active (runs for about a minute)',
    'Без узора': 'No pattern',
    'Белые носочки': 'White socks',
    'Белый': 'White',
    'Красиво': 'Beautiful',
    'Легче для ПК': 'Lighter for PC',
    'Мой котик — Desktop Companion': 'My Kitty — Desktop Companion',
    'Очень лёгкий': 'Very light',
    'Полоски': 'Stripes',
    'Пятнышки': 'Spots',
    'Рыжий': 'Ginger',
    'Сбалансированно': 'Balanced',
    'Смокинг': 'Tuxedo',
    'Спокойный (как в версии со снегом)': 'Calm (falls asleep after 25 s)',
    'Чёрный': 'Black',
    '✏️ Узор': '✏️ Pattern',
    '🍼 Животик': '🍼 Tummy',
    '🎀 Хвост': '🎀 Tail',
    '🐾 Лапки': '🐾 Paws',
    '👁 Глаза': '👁 Eyes',
    '👂 Ушки': '👂 Ears',
    '👃 Носик': '👃 Nose',
    '🧶 Шерсть': '🧶 Fur',
})


def _notify_running_instance() -> bool:
    """Просит уже запущенный экземпляр показать лаунчер. True — он ответил."""
    sock = QLocalSocket()
    sock.connectToServer(SINGLE_INSTANCE_ID)
    if not sock.waitForConnected(1000):
        return False
    sock.write(b"activate")
    sock.flush()
    sock.waitForBytesWritten(1000)
    sock.disconnectFromServer()
    return True


def main():
    app = QApplication(sys.argv)
    app.setQuitOnLastWindowClosed(False)
    icon_file = resource_path("cat.ico")
    if os.path.exists(icon_file):
        app.setWindowIcon(QIcon(icon_file))

    # --- единственный экземпляр: блокировка + локальный сервер для активации ---
    lock = QLockFile(os.path.join(tempfile.gettempdir(), SINGLE_INSTANCE_ID + ".lock"))
    lock.setStaleLockTime(0)
    if not lock.tryLock(0):
        try:
            user32.AllowSetForegroundWindow(wintypes.DWORD(0xFFFFFFFF))
        except Exception:
            pass
        for _ in range(6):
            if _notify_running_instance():
                return 0
            QThread.msleep(300)
        # блокировка занята, но ответа нет: пробуем убрать только «мёртвую» блокировку
        lock.removeStaleLockFile()
        if not lock.tryLock(0):
            return 0  # лучше не запускаться, чем создать второго кота

    QLocalServer.removeServer(SINGLE_INSTANCE_ID)
    server = QLocalServer()
    server.listen(SINGLE_INSTANCE_ID)

    cat = CompanionOverlay()
    cat.show()

    bridge = NotificationBridge()
    bridge.notification_received.connect(cat.on_external_notification)

    watcher = HybridNotificationWatcher(bridge)
    watcher.start()

    launcher = CatLauncherWindow(cat, watcher)
    launcher.show()

    def _on_new_connection():
        while server.hasPendingConnections():
            conn = server.nextPendingConnection()

            def _read(c=conn):
                data = bytes(c.readAll()).decode("utf-8", errors="ignore")
                if "activate" in data:
                    launcher.bring_to_front()
            conn.readyRead.connect(_read)
            conn.disconnected.connect(conn.deleteLater)

    server.newConnection.connect(_on_new_connection)

    def _shutdown():
        watcher.running = False
        cat.tracker.shutdown()
        server.close()
        lock.unlock()

    app.aboutToQuit.connect(_shutdown)
    code = app.exec()
    return code


if __name__ == "__main__":
    sys.exit(main())