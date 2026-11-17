#!/usr/bin/env python3

import json, math, os, re, sys, time
from PySide6.QtCore import Qt, QPointF, QRectF, QSizeF, QMarginsF, QLineF, QPoint, QSize, Signal, QMimeData, QSettings
from PySide6.QtGui import (QPainter, QPainterPath, QColor, QPen, QFont, QTextLayout, QTextOption, QImage,
                           QPalette, QPdfWriter, QPageSize, QActionGroup, QFontMetricsF, QCursor)
from PySide6.QtSvg import QSvgGenerator
from PySide6.QtWidgets import (QApplication, QMainWindow, QWidget, QTextEdit, QFrame, QVBoxLayout,
                               QAbstractButton, QMenu, QFileDialog, QMessageBox, QHBoxLayout, QTabBar,
                               QLineEdit, QLabel, QDialog, QDialogButtonBox, QFontComboBox, QColorDialog,
                               QToolTip, QInputDialog, QWidgetAction)

FAMILIES = ["Inter", "Helvetica", "Arial", "Liberation Sans", "Sans Serif"]
DEFAULT_FAMILIES = list(FAMILIES)     # what "Default" in the font picker goes back to
FONT_PX = (40, 31, 31, 29)            # root, main, sub, deeper (same sizes as the GTK build, in px)
BOLD = (True, True, False, False)
PADS = ((38, 24), (26, 20), (20, 10), (14, 10))
MAXW = 800
MINFW = 30          # narrowest text width a topic can be dragged to
GRIP = 7            # grab-handle width on a selected topic (screen px)
MIME = "application/x-xmap-nodes"  # clipboard format for copied topics
SHAPES = ["Square", "Rounded", "Pill"]
LINES = ["Curved", "Straight", "Rounded", "Elbow"]
CHILD_TYPES = ["Normal", "Empty"]  # Empty: no underline under the sub topics, lines attach to the middle of the text
CHILD_LINES = ["Straight", "Curve", "Elbow"]  # branch lines from the 2nd level on (not the ones leaving the root)
COLORS = [("Red", "#ed283f"), ("Green", "#00b87d"), ("Orange", "#ffa31a"), ("Off-white", "#e6e6e6")]
ICON_SIZES = (40, 36, 34, 32)
ICON_GAP = 12
NOTE_SIZES = (28, 24, 22, 20)  # note badge size per depth
NOTE_GAP = 10
BND_COLOR = "#ffa31a"  # colour of a new boundary until the user picks another (same orange as the Orange topic colour)
BND_PAD = 12           # space between the topics and the boundary outline
PROG_GAP = 26          # progress chart: space between a main topic and its nearest sub topic
PROG_COL = 70          # progress chart: space between one column and the next
BND_JOIN = 2           # space on the side the lines come in from (hugs the topic, like a coloured sub topic box)
BND_TAB_H = 26         # height of the title tab on top of a boundary

DEFAULT_LINE = "#ffffff"  # colour of the mindmap lines until the user picks another
DEFAULT_BG = "#000000"    # canvas background until the user picks another
DEFAULT_FILL = "#2a2a2e"  # fill colour of the 2nd level topic boxes (when the fill toggle is on)
DEFAULT_ROOT_FILL = "#2a2a2e"  # fill colour of the root topic box (when the fill toggle is on)
# Themes menu: (name, background, root topic fill, other topics fill, lines). Picking one also turns the fill on.
THEMES = [("Default", DEFAULT_BG, DEFAULT_ROOT_FILL, DEFAULT_FILL, DEFAULT_LINE, False),
          ("Noir", "#070707", "#1b0707", "#2a2a2e", "#ffffff", True),
          ("Midnight Blue", "#05090f", "#051327", "#172d39", "#2f5163", True),
          ("Forest", "#040806", "#0e1e17", "#234a31", "#486653", True),
          ("Amber Terminal", "#0b0905", "#3a2504", "#3a3226", "#f2a93b", True)]
WHITE, BLACK = QColor(255, 255, 255), QColor(0, 0, 0)
NOPEN, NOBRUSH = Qt.PenStyle.NoPen, Qt.BrushStyle.NoBrush


def use_family(fam):  # put fam first in the font fallback list (None = the built-in default list)
    FAMILIES[:] = [fam] + [f for f in DEFAULT_FAMILIES if f != fam] if fam else DEFAULT_FAMILIES


def hex_rgb(h):
    return tuple(int(h[i:i + 2], 16) / 255 for i in (1, 3, 5))


def qc(rgb):
    return QColor.fromRgbF(*rgb)


def text_on(h):  # black or white text, whichever contrasts more with background h
    def lin(v):
        return v / 12.92 if v <= 0.03928 else ((v + 0.055) / 1.055) ** 2.4
    r, g, b = (lin(c) for c in hex_rgb(h))
    L = 0.2126 * r + 0.7152 * g + 0.0722 * b
    return (0, 0, 0) if (L + 0.05) / 0.05 > 1.05 / (L + 0.05) else (1, 1, 1)


def tint(h, a=70):  # see-through version of colour h, like the search highlight
    c = QColor(h)
    c.setAlpha(a)
    return c


def pen(color, w, dash=None, round_=False):
    p = QPen(color, w)
    cap = Qt.PenCapStyle.RoundCap if round_ else Qt.PenCapStyle.FlatCap
    join = Qt.PenJoinStyle.RoundJoin if round_ else Qt.PenJoinStyle.MiterJoin
    p.setCapStyle(cap)
    p.setJoinStyle(join)
    if dash:
        p.setDashPattern([d / w for d in dash])  # Qt dash lengths are in units of pen width
    return p


def draw_icon(p, kind, x, y, s):  # round check / error badge in a box of size s
    cx, cy = x + s / 2, y + s / 2
    p.setPen(pen(WHITE, 1.5))
    p.setBrush(QColor(0, 184, 125) if kind == "check" else QColor(237, 84, 84))
    p.drawEllipse(QPointF(cx, cy), s / 2 - 1, s / 2 - 1)
    p.setPen(pen(WHITE, s * 0.14, round_=True))
    p.setBrush(NOBRUSH)
    if kind == "check":
        p.drawPolyline([QPointF(x + s * .27, y + s * .52), QPointF(x + s * .44, y + s * .69),
                        QPointF(x + s * .74, y + s * .33)])
    else:
        p.drawLine(QLineF(x + s * .33, y + s * .33, x + s * .67, y + s * .67))
        p.drawLine(QLineF(x + s * .67, y + s * .33, x + s * .33, y + s * .67))


def draw_note(p, x, y, s, color):  # note badge: three rounded lines, the last one shorter
    p.setPen(pen(color, s * 0.13, round_=True))
    p.setBrush(NOBRUSH)
    for i, end in enumerate((1.0, 1.0, 0.6)):
        yy = y + s * (0.2 + 0.3 * i)
        p.drawLine(QLineF(x + s * .08, yy, x + s * (.08 + .84 * end), yy))


def hgap(depth):  # gap between a node and its children
    return 90 if depth == 0 else 38 if depth == 1 else 28


def rect_path(x, y, w, h, r=0):
    path = QPainterPath()
    if r <= 0:
        path.addRect(QRectF(x, y, w, h))
    else:
        r = min(r, w / 2, h / 2)
        path.addRoundedRect(QRectF(x, y, w, h), r, r)
    return path


def elbow_path(x0, y0, xm, x1, y1, r):
    """Xmind-style elbow: horizontal from (x0,y0), a rounded corner at x=xm, vertical, a second rounded
    corner, then horizontal into (x1,y1). The corner radius shrinks when there is not enough room."""
    path = QPainterPath()
    path.moveTo(x0, y0)
    dy = y1 - y0
    if abs(dy) < 1:
        path.lineTo(x1, y1)
        return path
    sx = 1 if x1 > x0 else -1
    sy = 1 if dy > 0 else -1
    r = min(r, abs(dy) / 2, abs(xm - x0), abs(x1 - xm))
    k = r * 0.4477  # control-point distance that makes a true circular quarter arc
    path.lineTo(xm - sx * r, y0)
    path.cubicTo(xm - sx * k, y0, xm, y0 + sy * k, xm, y0 + sy * r)
    path.lineTo(xm, y1 - sy * r)
    path.cubicTo(xm, y1 - sy * k, xm + sx * k, y1, xm + sx * r, y1)
    path.lineTo(x1, y1)
    return path


class Node:
    def __init__(self, text="New topic", side="R"):
        self.text, self.side, self.folded = text, side, False
        self.children, self.parent = [], None
        self.x = self.y = self.w = self.h = self.tw = self.th = self.sh = 0
        self.depth, self.eff = 0, "R"
        self.color, self.icon, self.note = None, None, ""
        self.fw = None  # custom text width set by dragging the side handle (None = automatic)
        self.up = False  # progress chart: sub topics are stacked above this main topic (else below)

    @property
    def iw(self):  # extra width taken by the icon
        return ICON_SIZES[min(self.depth, 3)] + ICON_GAP if self.icon else 0

    @property
    def nw(self):  # extra width taken by the note badge
        return NOTE_SIZES[min(self.depth, 3)] + NOTE_GAP if self.note else 0

    def add(self, c, i=None):
        c.parent = self
        self.children.insert(len(self.children) if i is None else i, c)

    @property
    def cx(self): return self.x + self.w / 2

    @property
    def cy(self): return self.y + self.h / 2

    @property
    def ay(self):  # y where lines attach: box middle, or underline for sub topics
        return self.cy if self.depth <= 1 else self.y + self.h

    def under(self, other):
        n = self
        while n:
            if n is other:
                return True
            n = n.parent
        return False

    def to_dict(self):
        d = {"text": self.text, "side": self.side, "folded": self.folded}
        if self.color:
            d["color"] = self.color
        if self.icon:
            d["icon"] = self.icon
        if self.fw:
            d["fw"] = self.fw
        if self.note:
            d["note"] = self.note
        d["children"] = [c.to_dict() for c in self.children]
        return d

    @staticmethod
    def from_dict(d):
        n = Node(d.get("text", ""), d.get("side", "R"))
        n.folded = d.get("folded", False)
        n.color, n.icon = d.get("color"), d.get("icon")
        n.note = d.get("note") if isinstance(d.get("note"), str) else ""
        fw = d.get("fw")
        n.fw = int(fw) if isinstance(fw, (int, float)) and fw > 0 else None
        for c in d.get("children", []):
            n.add(Node.from_dict(c))
        return n


BULLET = re.compile(r"^(?:[-*+\u2022\u2013\u25E6\u25AA]|\d+[.)])\s+")  # "- ", "* ", "+ ", "• ", "1. ", "1) "


def parse_outline(txt):
    """Turn bulleted / indented plain text into [{"text":..., "children":[...]}].
    Returns None when the text has no bullets and no indentation (so it stays one topic)."""
    lines = [l.rstrip() for l in txt.replace("\r\n", "\n").replace("\r", "\n").split("\n") if l.strip()]
    if not lines:
        return None
    rows, bullets, indented = [], False, False
    for l in lines:
        lead = len(l) - len(l.lstrip(" \t"))
        ind = len(l[:lead].replace("\t", "    "))
        body = l.lstrip(" \t")
        m = BULLET.match(body)
        if m:
            bullets = True
            body = body[m.end():]
        indented = indented or ind > 0
        rows.append((ind, body.strip()))
    if not (bullets or (indented and len(rows) > 1)):
        return None
    top, stack = [], []  # stack of (indent, node dict)
    for ind, body in rows:
        if not body:
            continue
        while stack and stack[-1][0] >= ind:
            stack.pop()
        d = {"text": body, "children": []}
        (stack[-1][1]["children"] if stack else top).append(d)
        stack.append((ind, d))
    return top or None


def build(spec, i=0):
    text, kids = spec
    n = Node(text, "R" if i % 2 == 0 else "L")
    for k in kids:
        n.add(build(k))
    return n


def default_tree():
    t = ("My Mind Map", [
        ("Information Gathering", [
            ("Internet Scanning", [("Censys", [("https://censys.io/", [])]),
                                   ("Shodan", [("http://shodan.io/", [])])]),
            ("Ports Services", [("nmap", [("https://nmap.org/", [])]),
                                ("masscan", [("https://github.com/masscan", [])])]),
            ("Passive DNS monitoring", [("Sublert", [("https://github.com/sublert", [])])])]),
        ("Wordlists", [
            ("Common Files", [("dirsearch Wordlist", [("https://github.com/dirsearch", [])])]),
            ("Subdomains", [("CommonSpeak", [("https://github.com/commonspeak2", [])])]),
            ("Mixed", [("Seclist", [("https://github.com/SecLists", [])])])]),
        ("Android", [
            ("Emulator", [("Bluestacks", [("https://www.bluestacks.com/", [])]),
                          ("Genymotion", [("https://www.genymotion.com/", [])])]),
            ("Decompiler", [("Jadx", [("https://github.com/skylot/jadx", [])])])]),
        ("Web Application Scanners", [
            ("Nessus", [("https://www.tenable.com/products/nessus", [])]),
            ("OWASP ZAP", [("https://owasp.org/www-project-zap/", [])])])])
    r = build(t)
    for i, c in enumerate(r.children):
        c.side = "R" if i % 2 == 0 else "L"
    return r


class Rel:
    """A relationship: a dashed curved arrow from topic a to topic b. o1/o2 are the two curve handles,
    stored as offsets from the centre of a / b (None = automatic gentle bow)."""

    def __init__(self, a, b, o1=None, o2=None):
        self.a, self.b, self.o1, self.o2 = a, b, o1, o2


def parse_rels(data, root):  # rebuild relationships from saved node paths; anything invalid is skipped
    out = []
    if not isinstance(data, list):
        return out

    def find(path):
        if not isinstance(path, list):
            return None
        n = root
        for i in path:
            if not isinstance(i, int) or isinstance(i, bool) or not 0 <= i < len(n.children):
                return None
            n = n.children[i]
        return n

    def off(o):
        if isinstance(o, (list, tuple)) and len(o) == 2 and all(isinstance(v, (int, float)) for v in o):
            return float(o[0]), float(o[1])
        return None

    for d in data:
        if not isinstance(d, dict):
            continue
        a, b = find(d.get("a")), find(d.get("b"))
        if a is None or b is None or a is b:
            continue
        o1, o2 = off(d.get("o1")), off(d.get("o2"))
        if o1 is None or o2 is None:
            o1 = o2 = None
        out.append(Rel(a, b, o1, o2))
    return out


class Bnd:
    """A boundary: a dashed rounded outline with a soft fill around sibling topics (and their branches).
    It only refers to the topics, so it never changes the layout."""

    def __init__(self, nodes, color=BND_COLOR, title=""):
        self.nodes, self.color, self.title = nodes, color, title
        self.parent = nodes[0].parent  # the shared parent; topics moved elsewhere drop out of the boundary


def parse_bnds(data, root):  # rebuild boundaries from saved node paths; anything invalid is skipped
    out = []
    if not isinstance(data, list):
        return out

    def find(path):
        if not isinstance(path, list):
            return None
        n = root
        for i in path:
            if not isinstance(i, int) or isinstance(i, bool) or not 0 <= i < len(n.children):
                return None
            n = n.children[i]
        return n

    for d in data:
        if not isinstance(d, dict) or not isinstance(d.get("n"), list):
            continue
        nodes = []
        for pa in d["n"]:
            n = find(pa)
            if n is not None and n is not root and n not in nodes:
                nodes.append(n)
        if not nodes or any(n.parent is not nodes[0].parent for n in nodes):
            continue
        c, t = d.get("color"), d.get("title")
        out.append(Bnd(nodes, c if isinstance(c, str) and QColor(c).isValid() else BND_COLOR,
                       t if isinstance(t, str) else ""))
    return out


def bezier(p0, c1, c2, p3, t):
    u = 1 - t
    a, b, c, d = u * u * u, 3 * u * u * t, 3 * u * t * t, t * t * t
    return (a * p0[0] + b * c1[0] + c * c2[0] + d * p3[0], a * p0[1] + b * c1[1] + c * c2[1] + d * p3[1])


def seg_dist(px, py, ax, ay, bx, by):  # distance from point p to segment a-b
    dx, dy = bx - ax, by - ay
    L2 = dx * dx + dy * dy
    t = 0 if L2 == 0 else max(0, min(1, ((px - ax) * dx + (py - ay) * dy) / L2))
    return math.hypot(px - (ax + t * dx), py - (ay + t * dy))


class Doc:
    """Everything that belongs to one tab. The canvas is shared; its state is swapped in and out."""

    def __init__(self, root=None, layout="Map", shape="Square", line="Curved", path=None, line_color=DEFAULT_LINE,
                 child_line="Straight", child_type="Normal", bg_color=DEFAULT_BG, fill_on=False, fill_color=DEFAULT_FILL,
                 root_fill_color=DEFAULT_ROOT_FILL):
        self.line_color = line_color if QColor(line_color).isValid() else DEFAULT_LINE
        self.bg_color = bg_color if QColor(bg_color).isValid() else DEFAULT_BG
        self.fill_on = bool(fill_on)
        self.fill_color = fill_color if QColor(fill_color).isValid() else DEFAULT_FILL
        self.root_fill_color = root_fill_color if QColor(root_fill_color).isValid() else DEFAULT_ROOT_FILL
        self.root = root or Node("My Mind Map")
        self.layout_mode = layout if layout in ("Map", "Logic chart", "Progress chart") else "Map"
        self.shape = shape if shape in SHAPES else "Square"
        self.line = line if line in LINES else "Straight"
        self.child_line = child_line if child_line in CHILD_LINES else "Straight"
        self.child_type = child_type if child_type in CHILD_TYPES else "Normal"
        self.path, self.dirty, self.sel_path = path, False, []
        self.undo, self.redo = [], []
        self.rels = []
        self.bnds = []
        self.zoom, self.ox, self.oy, self.need_fit = 1.0, 0.0, 0.0, True
        self.id, self.untitled = 0, 0

    def name(self, path=None):
        path = path if path is not None else self.path
        if path:
            return os.path.basename(path)
        return "Untitled" if self.untitled <= 1 else f"Untitled {self.untitled}"


class EditBox(QTextEdit):
    """Multi-line topic editor. Enter = finish, Shift/Ctrl/Alt+Enter = new line."""
    cancelled = Signal()
    blurred = Signal()
    returnPressed = Signal()
    MAX_H = 800  # max editor height in px; longer text scrolls

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAcceptRichText(False)  # pasting always gives plain text, line breaks kept
        self.setTabChangesFocus(True)
        self.setLineWrapMode(QTextEdit.LineWrapMode.WidgetWidth)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)  # scrollbar only when text exceeds MAX_H
        self.verticalScrollBar().setStyleSheet("QScrollBar:vertical{width:6px;background:transparent;}QScrollBar::handle:vertical{background:#666;border-radius:3px;min-height:20px;}QScrollBar::add-line:vertical,QScrollBar::sub-line:vertical{height:0;}")
        self.textChanged.connect(self.refit)

    def text(self):
        return self.toPlainText().replace("\r\n", "\n").replace("\r", "\n").replace("\u2028", "\n").replace("\u2029", "\n")

    def setText(self, t):
        self.setPlainText(t)

    def refit(self):  # grow/shrink the box with its content
        self.document().setTextWidth(max(self.width() - 18, 20))
        h = min(max(38, int(math.ceil(self.document().size().height())) + 14), self.MAX_H)
        if h != self.height():
            self.resize(self.width(), h)

    def keyPressEvent(self, e):
        k = e.key()
        if k == Qt.Key.Key_Escape:
            self.cancelled.emit()
            return
        if k in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
            mods = Qt.KeyboardModifier.ShiftModifier | Qt.KeyboardModifier.ControlModifier | Qt.KeyboardModifier.AltModifier
            if e.modifiers() & mods:
                self.insertPlainText("\n")
            else:
                self.returnPressed.emit()
            e.accept()
            return
        super().keyPressEvent(e)
        e.accept()  # don't let keys reach the map while typing

    def focusOutEvent(self, e):
        super().focusOutEvent(e)
        self.blurred.emit()


class NoteBox(QTextEdit):
    """Popup editor for a topic's note. Esc or a click elsewhere closes it (and keeps the text)."""
    closed = Signal()
    blurred = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAcceptRichText(False)
        self.setPlaceholderText("Write a note...")
        self.set_bg(DEFAULT_BG)
        self.verticalScrollBar().setStyleSheet(  # slim scrollbar, no arrows
            "QScrollBar:vertical{width:8px;background:transparent;margin:4px 2px 4px 0;}"
            "QScrollBar::handle:vertical{background:#4a4a4d;border-radius:3px;min-height:24px;}"
            "QScrollBar::handle:vertical:hover{background:#6a6a6e;}"
            "QScrollBar::add-line:vertical,QScrollBar::sub-line:vertical{height:0;}"
            "QScrollBar::add-page:vertical,QScrollBar::sub-page:vertical{background:transparent;}")
        self._edge_acc, self._edge_t, self._edge_dir = 0, 0.0, 0  # wheel resistance at the ends of the note
        self.setVisible(False)

    def set_bg(self, bg):  # the note box takes the map's background colour
        if getattr(self, "_bg", None) == bg:
            return
        self._bg = bg
        self.setStyleSheet("QTextEdit{background:" + bg + ";color:#fff;border:2px solid #851d26;"
                           "border-radius:8px;padding:6px 10px;font-size:18.5px;"
                           "font-family:'Inter','Helvetica','Arial',sans-serif;font-weight:500;"
                           "selection-background-color:#3a6ea5;}")

    EDGE_TICKS = 10  # extra wheel notches needed at the top/bottom of a note before the map itself scrolls

    def wheelEvent(self, e):
        sb = self.verticalScrollBar()
        d = e.angleDelta().y() or e.pixelDelta().y() * 3
        if not d or sb.maximum() <= sb.minimum():  # sideways wheel, or nothing to scroll: leave it to the map
            e.ignore()
            return
        up = d > 0
        at_edge = sb.value() <= sb.minimum() if up else sb.value() >= sb.maximum()
        if not at_edge:  # still scrolling inside the note
            self._edge_acc = 0
            super().wheelEvent(e)
            return
        now = time.monotonic()
        if now - self._edge_t > 0.6 or self._edge_dir != (1 if up else -1):  # a new push against the edge
            self._edge_acc = 0
        self._edge_t, self._edge_dir = now, 1 if up else -1
        self._edge_acc += abs(d)
        if self._edge_acc >= self.EDGE_TICKS * 120:  # pushed hard enough: now the map scrolls too
            e.ignore()
        else:
            e.accept()  # absorbed: the note is at its end, the map stays put

    def keyPressEvent(self, e):
        if e.key() == Qt.Key.Key_Escape:
            self.closed.emit()
            return
        super().keyPressEvent(e)
        e.accept()  # don't let keys reach the map while typing

    def focusOutEvent(self, e):
        super().focusOutEvent(e)
        if e.reason() != Qt.FocusReason.PopupFocusReason:  # right-click menu keeps the note open
            self.blurred.emit()


class MapView(QWidget):
    def __init__(self, win):
        super().__init__()
        self.win = win
        self.rail = None
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setMouseTracking(True)
        self._lc = {}   # text layouts used for drawing (bounded: only what is on screen needs them)
        self._sz = {}   # (text, depth, width) -> (w, h): tiny, so it can hold every topic of a huge map
        self._lod = False
        self._curves = {}  # cached shapes of the Curve child branch lines
        self._deco = set()
        self.line_color = DEFAULT_LINE
        self.bg_color, self.fill_on, self.fill_color = DEFAULT_BG, False, DEFAULT_FILL
        self.root_fill_color = DEFAULT_ROOT_FILL
        self.child_line = "Straight"
        self.child_type = "Normal"
        #self.root, self.layout_mode, self.shape, self.line = default_tree(), "Map", "Square", "Straight"
        self.root, self.layout_mode, self.shape, self.line = Node("My Mind Map"), "Map", "Square", "Curved"
        self.sel, self.path, self.dirty = self.root, None, False
        self.undo, self.redo, self.vis = [], [], []
        self.zoom, self.ox, self.oy, self.need_fit = 1.0, 0.0, 0.0, True
        self.edit_node, self.edit_new, self.drag, self.mx, self.my = None, False, None, 0, 0
        self.rels, self.sel_rel, self.rel_from = [], None, None  # relationships; selected one; source of a pending one
        self.bnds, self.sel_bnd, self.bnd_color, self._brects = [], None, BND_COLOR, []  # boundaries; selected one; colour for new ones; cached outlines
        try:  # the colour picked for boundaries is remembered between runs
            sc = str(QSettings("xmap", "xmap").value("bnd_color", "") or "")
            if sc and QColor(sc).isValid():
                self.bnd_color = QColor(sc).name()
        except Exception:
            pass

        self.entry = EditBox(self)
        self.entry.setVisible(False)
        self.entry_css = ("QTextEdit{background:%s;color:#fff;border:2px solid #851d26;"
                          "border-radius:6px;padding:4px 8px;font-size:18px;"
                          "selection-background-color:#3a6ea5;}")
        self.entry.setStyleSheet(self.entry_css % self.bg_color)
        self.entry.returnPressed.connect(lambda: self.commit_edit())
        self.entry.cancelled.connect(lambda: self.commit_edit(False))
        self.entry.blurred.connect(lambda: self.commit_edit())
        self.note_node, self._nb = None, None  # note being edited; (node, time) of a note closed by a click elsewhere
        self.note_box = NoteBox(self)
        self.note_box.closed.connect(lambda: self.close_note())
        self.note_box.blurred.connect(lambda: self.close_note(True))
        self.search_q, self.found, self._fs, self.found_cur = "", [], set(), None  # Ctrl+F state
        self.sbar = SearchBar(self)
        self.relayout()

    def focusNextPrevChild(self, nxt):  # keep Tab for "add child"
        return False

    @property
    def sel(self):  # primary selected node; assigning it collapses any multi-selection
        return self._sel

    @sel.setter
    def sel(self, n):
        self._sel, self.sels, self.sel_rel = n, [n], None
        self.sel_bnd = None

    def targets(self):  # all selected, visible nodes in map order
        ids = {id(n) for n in self.sels}
        return [n for n in self.vis if id(n) in ids]

    def select_all(self):
        ns = [n for n in self.vis if n is not self.root]
        if ns:
            self.sel = ns[0]
            self.sels = ns
            self.update()

    def collapse_sel(self):
        self.sel = self.sel
        self.update()

    # ---------- layout ----------
    def lay(self, text, depth, fw=None):
        d = min(depth, 3)
        key = (text, d, fw)
        hit = self._lc.get(key)
        if hit:
            return hit
        f = QFont()
        f.setFamilies(FAMILIES)
        f.setPixelSize(FONT_PX[d])
        f.setBold(BOLD[d])
        tl = QTextLayout((text or " ").replace("\n", "\u2028"), f)  # U+2028 = hard line break in QTextLayout
        opt = QTextOption(Qt.AlignmentFlag.AlignLeft)
        opt.setWrapMode(QTextOption.WrapMode.WrapAtWordBoundaryOrAnywhere)
        tl.setTextOption(opt)
        tl.beginLayout()
        y, lines = 0.0, []
        while True:
            ln = tl.createLine()
            if not ln.isValid():
                break
            ln.setLineWidth(fw or MAXW)
            ln.setPosition(QPointF(0, y))
            y += ln.height()
            lines.append(ln)
        tl.endLayout()
        res = (tl, lines, math.ceil(max(l.naturalTextWidth() for l in lines)), math.ceil(y))
        if len(self._lc) > 6000:
            self._lc.clear()
        self._lc[key] = res
        return res

    def measure(self, n, depth, eff):
        n.depth, n.eff = depth, eff
        key = (n.text, min(depth, 3), n.fw)
        sz = self._sz.get(key)
        if sz is None:
            _, _, tw, th = self.lay(n.text, depth, n.fw)
            if len(self._sz) > 400000:
                self._sz.clear()
            sz = self._sz[key] = (tw, th)
        n.tw, n.th = sz
        if n.fw:
            n.tw = n.fw  # custom width: the box is exactly that wide, lines centred inside
        px, py = PADS[min(depth, 3)]
        n.w, n.h = n.tw + 2 * px + n.iw + n.nw, n.th + 2 * py
        kids = [] if n.folded else n.children
        for c in kids:
            self.measure(c, depth + 1, ("R" if self.layout_mode != "Map" else c.side) if depth == 0 else eff)
        n.sh = max(n.h, sum(c.sh for c in kids) + 20 * (len(kids) - 1)) if kids else n.h

    def place(self, n, cy):
        n.y = cy - n.h / 2
        kids = [] if n.folded else n.children
        if not kids:
            return
        hg = hgap(n.depth)
        if n.depth >= 1 and self.child_line == "Curve":  # room for the curve to bend
            hg = 56
        elif n.depth >= 1 and self.child_type == "Empty":  # same dot-to-text distance at every level: dot line, tail and gap stay equal
            hg = 68 + self.dot_off(n) - PADS[min(n.depth + 1, 3)][0]
        tot = sum(c.sh for c in kids) + 20 * (len(kids) - 1)
        y = cy - tot / 2
        for c in kids:
            c.x = n.x + n.w + hg if c.eff == "R" else n.x - hg - c.w
            self.vis.append(c)
            self.place(c, y + c.sh / 2)
            y += c.sh + 20

    def dot_off(self, n):  # how far the fold dot sits outside the topic's edge
        if n.depth == 1:
            return 6
        if n.depth >= 2 and self.child_type == "Empty" and self.child_line != "Curve":
            return max(20 - PADS[min(n.depth, 3)][0], 11 if n.color else 0)
        return 0

    def kid_gap(self, n):  # the gap place() leaves between a topic and its children
        hg = hgap(n.depth)
        if n.depth >= 1 and self.child_line == "Curve":
            hg = 56
        elif n.depth >= 1 and self.child_type == "Empty":
            hg = 68 + self.dot_off(n) - PADS[min(n.depth + 1, 3)][0]
        return hg

    def sub_w(self, n):  # width of a topic together with everything that branches off it to the right
        kids = [] if n.folded else n.children
        return n.w + (self.kid_gap(n) + max(self.sub_w(c) for c in kids) if kids else 0)

    def place_progress(self):  # layout "Progress chart": main topics in a row, sub topics stacked above / below them in turn
        r = self.root  # (already placed in the middle, self.vis holds just the root)
        x = r.x + r.w + hgap(0)
        for i, m in enumerate(r.children):
            m.x, m.y, m.up = x, -m.h / 2, i % 2 == 0
            self.vis.append(m)
            right = m.x + m.w
            kids = [] if m.folded else m.children
            if kids:
                tot = sum(c.sh for c in kids) + 20 * (len(kids) - 1)
                y = (-m.h / 2 - PROG_GAP - tot) if m.up else (m.h / 2 + PROG_GAP)
                for c in kids:  # listed top to bottom; they all start on the vertical line through the main topic
                    c.x = m.cx + (46 - PADS[2][0] if self.child_type == "Empty" else 0)  # Empty: same tick + gap to the text as in Map
                    self.vis.append(c)
                    self.place(c, y + c.sh / 2)
                    y += c.sh + 20
                    right = max(right, c.x + self.sub_w(c))
            x = right + PROG_COL

    def relayout(self):
        r = self.root
        if self.rels:  # drop relationships whose topics were deleted
            alive = {id(n) for n in self.walk(r)}
            self.rels = [x for x in self.rels if id(x.a) in alive and id(x.b) in alive]
            if self.sel_rel not in self.rels:
                self.sel_rel = None
        if self.bnds:
            self.bnd_prune()
        self.measure(r, 0, "R")
        r.x, r.y, self.vis = -r.w / 2, -r.h / 2, [r]
        if self.layout_mode == "Progress chart":
            self.place_progress()
        for side in ("" if self.layout_mode == "Progress chart" else "RL"):
            kids = [c for c in r.children if c.eff == side]
            if not kids:
                continue
            tot = sum(c.sh for c in kids) + 28 * (len(kids) - 1)
            y = -tot / 2
            for c in kids:
                c.x = r.x + r.w + hgap(0) if side == "R" else r.x - hgap(0) - c.w
                self.vis.append(c)
                self.place(c, y + c.sh / 2)
                y += c.sh + 28
        if self.search_q:  # the tree may have changed (edit, undo, tab switch): keep the matches current
            self.search_scan()
        self.bnd_refresh()
        self.update()

    def bounds(self):
        return (min(n.x for n in self.vis) - 24, min(n.y for n in self.vis) - 8,
                max(n.x + n.w for n in self.vis) + 24, max(n.y + n.h for n in self.vis) + 8)

    def fit(self, W, H):
        x0, y0, x1, y1 = self.bounds()
        #self.zoom = max(0.1, min(1.0, (W - 80) / max(x1 - x0, 1), (H - 80) / max(y1 - y0, 1)))
        self.zoom = 0.62
        self.ox = W / 2 - (x0 + x1) / 2 * self.zoom
        self.oy = H / 2 - (y0 + y1) / 2 * self.zoom
        self.need_fit = False

    def refont(self):  # FAMILIES changed: drop cached text layouts and re-measure everything
        self._lc.clear()
        self._sz.clear()
        f = self.entry.font()
        f.setFamilies(FAMILIES)
        self.entry.setFont(f)
        self.relayout()

    def fit_now(self):
        self.need_fit = True
        self.update()

    # ---------- drawing ----------
    def paintEvent(self, ev):
        W, H = self.width(), self.height()
        if self.need_fit and W > 10:
            self.fit(W, H)
        self.place_note()
        p = QPainter(self)
        p.setRenderHints(QPainter.RenderHint.Antialiasing | QPainter.RenderHint.TextAntialiasing)
        p.fillRect(self.rect(), QColor(self.bg_color))
        p.translate(self.ox, self.oy)
        p.scale(self.zoom, self.zoom)
        self.draw_scene(p, True)
        p.end()

    def box_path(self, n, x, y, g=0):  # outline path of a root/main topic, grown by g
        r = 0 if n.depth > 1 else {"Square": 0, "Rounded": 16, "Pill": n.h / 2}[self.shape]
        return rect_path(x - g, y - g, n.w + 2 * g, n.h + 2 * g, r + g if r else 0)

    def draw_scene(self, p, interactive):
        self._lod = interactive and self.zoom < 0.15 and len(self.vis) > 3000
        self._deco = ({id(n) for n in self.sels} | self._fs) if interactive else set()  # topics with a selection / search box
        if interactive:  # only draw what is on screen
            m = 40 / self.zoom
            x0, y0 = self.to_world(0, 0)
            x1, y1 = self.to_world(self.width(), self.height())
            x0, y0, x1, y1 = x0 - m, y0 - m, x1 + m, y1 + m
        else:  # export draws everything
            x0 = y0 = -1e12
            x1 = y1 = 1e12
        if self.bnds:
            self.draw_bnds(p, interactive, x0, y0, x1, y1)
        for n in self.vis:
            q = n.parent
            if q and min(n.x, q.x) < x1 and max(n.x + n.w, q.x + q.w) > x0 \
                    and min(n.y, q.y) < y1 and max(n.y + n.h, q.y + q.h) > y0:
                self.draw_conn(p, q, n)
        self.draw_rels(p, interactive)
        for n in self.vis:
            if n.x < x1 and n.x + n.w > x0 and n.y < y1 and n.y + n.h > y0:
                self.draw_node(p, n)
        if not interactive:
            return
        self.draw_rel_ui(p)
        if self.found:  # search matches: yellow for all, orange for the current one
            for n in self.vis:
                if id(n) in self._fs:
                    cur = n is self.found_cur
                    # p.setPen(pen(QColor(237, 40, 63) if cur else QColor(255, 204, 0), 3 if cur else 2))
                    # p.setBrush(QColor(237, 40, 63, 120) if cur else QColor(255, 204, 0, 70))
                    p.setPen(pen(QColor(0, 126, 217) if cur else QColor(73, 166, 209), 3 if cur else 2))
                    p.setBrush(QColor(0, 126, 217, 120) if cur else QColor(73, 166, 209, 70))
                    p.drawPath(self.box_path(n, n.x, n.y, 3) if n.depth <= 1
                               else rect_path(n.x - 3, n.y - 3, n.w + 6, n.h + 6, 6))
        if not self.edit_node:
            p.setPen(pen(WHITE, 1.5, [5, 4]))
            p.setBrush(NOBRUSH)
            vis_ids = {id(v) for v in self.vis} if len(self.sels) > 1 else None
            for n in self.sels:
                if vis_ids is None or id(n) in vis_ids:
                    p.drawPath(self.box_path(n, n.x, n.y, 6))
            if len(self.sels) == 1 and self.sel in self.vis:  # width handles
                z = self.zoom
                p.setPen(NOPEN)
                p.setBrush(WHITE)
                for hx, _, gy in self.grips(self.sel):
                    p.drawRoundedRect(QRectF(hx - 2 / z, gy - 11 / z, 4 / z, 22 / z), 2 / z, 2 / z)
                p.setPen(pen(WHITE, 1.5, [5, 4]))
                p.setBrush(NOBRUSH)
        d = self.drag
        if d and d["mode"] == "node" and d["active"]:
            p.save()
            p.setOpacity(0.55)
            n0 = d["node"]
            for g in d["group"]:
                self.draw_node(p, g, d["px"] - d["gx"] + g.x - n0.x, d["py"] - d["gy"] + g.y - n0.y, False)
            p.restore()
            if d["target"]:  # drawn after the ghost so it is never hidden behind it
                m, pos = d["target"]
                p.setBrush(NOBRUSH)
                if m is self.root:
                    p.setPen(pen(WHITE, 4))
                    xx = m.x + m.w + 10 if self.drop_side(d["px"]) == "R" else m.x - 10
                    p.drawLine(QLineF(xx, m.y, xx, m.y + m.h))
                elif pos == "child":
                    p.setPen(pen(WHITE, 4, [6, 4]))
                    p.drawPath(self.box_path(m, m.x, m.y, 6))
                else:
                    p.setPen(pen(WHITE, 4))
                    yy = m.y - 8 if pos == "before" else m.y + m.h + 8
                    p.drawLine(QLineF(m.x - 10, yy, m.x + m.w + 10, yy))
        if d and d["mode"] == "marquee" and d["active"]:
            x0, y0, x1, y1 = d["rect"]
            p.setPen(pen(WHITE, 1.5, [5, 4]))
            p.setBrush(QColor(255, 255, 255, 26))
            p.drawRect(QRectF(x0, y0, x1 - x0, y1 - y0))

    # ---------- relationships (P) ----------
    def live_rels(self):  # relationships whose two topics are both on screen (not inside a folded branch)
        if not self.rels:  # no relationships: nothing to work out on every repaint
            return []
        ids = {id(n) for n in self.vis}
        return [r for r in self.rels if id(r.a) in ids and id(r.b) in ids]

    @staticmethod
    def edge_pt(n, tx, ty):  # where the line from the centre of n towards (tx, ty) leaves n's box
        dx, dy = tx - n.cx, ty - n.cy
        if not dx and not dy:
            return n.cx, n.cy
        t = min((n.w / 2 + 4) / abs(dx) if dx else 1e9, (n.h / 2 + 4) / abs(dy) if dy else 1e9, 1)
        return n.cx + dx * t, n.cy + dy * t

    def rel_ctrl(self, r):  # absolute positions of the two curve handles
        ax, ay, bx, by = r.a.cx, r.a.cy, r.b.cx, r.b.cy
        if r.o1 is not None and r.o2 is not None:
            return (ax + r.o1[0], ay + r.o1[1]), (bx + r.o2[0], by + r.o2[1])
        vx, vy = bx - ax, by - ay
        L = math.hypot(vx, vy) or 1
        nx, ny, bow = -vy / L, vx / L, min(L * 0.25, 160)
        return ((ax + vx * .33 + nx * bow, ay + vy * .33 + ny * bow),
                (bx - vx * .33 + nx * bow, by - vy * .33 + ny * bow))

    def rel_geom(self, r):  # (start, handle1, handle2, end): the curve leaves / enters at the topic edges
        c1, c2 = self.rel_ctrl(r)
        return self.edge_pt(r.a, *c1), c1, c2, self.edge_pt(r.b, *c2)

    def rel_path(self, g):
        path = QPainterPath(QPointF(*g[0]))
        path.cubicTo(QPointF(*g[1]), QPointF(*g[2]), QPointF(*g[3]))
        return path

    def arrow_head(self, p, tip, frm, size=20):
        a = math.atan2(tip[1] - frm[1], tip[0] - frm[0])
        pts = [QPointF(*tip)] + [QPointF(tip[0] - size * math.cos(a + s), tip[1] - size * math.sin(a + s))
                                 for s in (0.42, -0.42)]
        p.setPen(NOPEN)
        p.setBrush(QColor(self.line_color))
        p.drawPolygon(pts)

    def draw_rels(self, p, interactive):
        for r in self.live_rels():
            g = self.rel_geom(r)
            path = self.rel_path(g)
            p.setBrush(NOBRUSH)
            if interactive and r is self.sel_rel:  # soft glow under the selected one
                p.setPen(pen(QColor(255, 255, 255, 60), 9, round_=True))
                p.drawPath(path)
            p.setPen(pen(QColor(self.line_color), 2.5, [9, 6]))
            p.drawPath(path)
            tail = g[2] if g[2] != g[3] else g[1]
            self.arrow_head(p, g[3], tail)

    def draw_rel_ui(self, p):  # handles of the selected relationship, and the rubber band of a pending one
        z = self.zoom
        r = self.sel_rel
        if r is not None and r in self.live_rels():
            g = self.rel_geom(r)
            p.setBrush(NOBRUSH)
            p.setPen(pen(QColor(255, 255, 255, 140), 1.2, [4, 4]))
            p.drawLine(QLineF(*g[0], *g[1]))
            p.drawLine(QLineF(*g[3], *g[2]))
            p.setPen(pen(BLACK, 1.5 / z))
            p.setBrush(WHITE)
            for c in (g[1], g[2]):
                p.drawEllipse(QPointF(*c), 6 / z, 6 / z)
        a = self.rel_from
        if a is not None and a in self.vis:
            mx, my = self.to_world(self.mx, self.my)
            hov, _ = self.hit(mx, my)
            if hov is a:
                hov = None
            tx, ty = (hov.cx, hov.cy) if hov else (mx, my)
            sx, sy = self.edge_pt(a, tx, ty)
            p.setBrush(NOBRUSH)
            if hov:
                p.setPen(pen(WHITE, 3))
                p.drawPath(self.box_path(hov, hov.x, hov.y, 6) if hov.depth <= 1
                           else rect_path(hov.x - 6, hov.y - 6, hov.w + 12, hov.h + 12, 6))
                tx, ty = self.edge_pt(hov, sx, sy)
            p.setPen(pen(WHITE, 2.5, [9, 6]))
            p.drawLine(QLineF(sx, sy, tx, ty))
            self.arrow_head(p, (tx, ty), (sx, sy))

    def rel_at(self, wx, wy):  # topmost relationship whose curve passes near the point
        tol = 9 / self.zoom
        for r in reversed(self.live_rels()):
            g = self.rel_geom(r)
            pts = [bezier(*g, i / 24) for i in range(25)]
            if any(seg_dist(wx, wy, *pts[i], *pts[i + 1]) <= tol for i in range(24)):
                return r
        return None

    def rel_handle_at(self, wx, wy):  # (relationship, 0|1) if a handle of the selected relationship is under the point
        r = self.sel_rel
        if r is None or r not in self.live_rels():
            return None
        for i, c in enumerate(self.rel_geom(r)[1:3]):
            if math.hypot(wx - c[0], wy - c[1]) <= 10 / self.zoom:
                return r, i
        return None

    def rel_start(self):  # key P: pick the target topic next (P again or Esc cancels)
        if self.rel_from is not None:
            return self.rel_cancel()
        if self.sel in self.vis and not self.edit_node:
            self.rel_from = self.sel
            self.setCursor(Qt.CursorShape.CrossCursor)
            self.update()

    def rel_cancel(self):
        self.rel_from = None
        self._hcur = False
        self.unsetCursor()
        self.update()

    def rel_finish(self, target):  # click on the target topic
        a, self.rel_from = self.rel_from, None
        self._hcur = False
        self.unsetCursor()
        if target is not None and target is not a:
            ex = next((r for r in self.rels if r.a is a and r.b is target), None)
            if ex is None:
                self.push_undo()
                ex = Rel(a, target)
                self.rels.append(ex)
            self.sels = []
            self.sel_rel = ex  # selected, so its handles can be dragged right away
        self.update()

    def rels_data(self):  # relationships as node paths, for undo snapshots and files
        alive = {id(n) for n in self.walk(self.root)}
        return [{"a": self.path_of(r.a), "b": self.path_of(r.b), "o1": r.o1, "o2": r.o2}
                for r in self.rels if id(r.a) in alive and id(r.b) in alive]

    # ---------- boundaries (B) ----------
    def bnds_data(self):  # boundaries as node paths, for undo snapshots and files
        if not self.bnds:
            return []
        alive = {id(n) for n in self.walk(self.root)}
        return [{"n": [self.path_of(n) for n in b.nodes if id(n) in alive and n.parent is b.parent],
                 "color": b.color, "title": b.title} for b in self.bnds]

    def bnd_prune(self):  # drop topics that were deleted or moved away; a boundary left with none goes too
        alive = {id(n) for n in self.walk(self.root)}
        out = []
        for b in self.bnds:
            ns = [n for n in b.nodes if id(n) in alive and n.parent is b.parent]
            if ns:
                b.nodes = ns
                out.append(b)
        self.bnds = out
        if self.sel_bnd not in self.bnds:
            self.sel_bnd = None

    def bnd_refresh(self):  # outlines (and title tabs) of the boundaries: worked out only when the layout changes
        self._brects = []
        if not self.bnds:
            return
        ids = {id(n) for n in self.vis}
        g = BND_PAD
        for b in self.bnds:
            if id(b.nodes[0]) not in ids:  # inside a folded branch: nothing to draw
                continue
            x0 = y0 = 1e18
            x1 = y1 = -1e18
            stack = list(b.nodes)
            while stack:
                n = stack.pop()
                x0, y0 = min(x0, n.x), min(y0, n.y)
                x1, y1 = max(x1, n.x + n.w), max(y1, n.y + n.h)
                if not n.folded:
                    stack.extend(n.children)
            pl = pr = g  # left / right space; smaller on the side the lines come in from
            effs = {n.eff for n in b.nodes}
            if len(effs) == 1:
                tight = BND_JOIN if b.nodes[0].depth >= 2 else 8  # main topics have a thick outline of their own
                if "R" in effs:
                    pl = tight
                else:
                    pr = tight
            r = QRectF(x0 - pl, y0 - g, x1 - x0 + pl + pr, y1 - y0 + 2 * g)
            tr = None
            if b.title:
                tr = QRectF(r.left() + 16, r.top() - BND_TAB_H + 4,
                            QFontMetricsF(self.bnd_font()).horizontalAdvance(b.title) + 24, BND_TAB_H)
            self._brects.append((b, r, tr))

    def bnd_font(self):
        f = QFont()
        f.setFamilies(FAMILIES)
        f.setPixelSize(16)
        f.setBold(True)
        return f

    def draw_bnds(self, p, interactive, x0, y0, x1, y1):  # underneath the lines and topics
        font = None
        for b, r, tr in self._brects:
            if r.left() > x1 or r.right() < x0 or r.top() - BND_TAB_H > y1 or r.bottom() < y0:
                continue
            p.setBrush(NOBRUSH)
            if interactive and b is self.sel_bnd:  # soft glow under the selected one
                p.setPen(pen(QColor(255, 255, 255, 60), 9, round_=True))
                p.drawRoundedRect(r, 18, 18)
            p.setPen(pen(QColor(b.color), 2.5, [9, 6]))
            p.setBrush(tint(b.color, 38))
            p.drawRoundedRect(r, 18, 18)
            if tr is not None:
                p.setPen(NOPEN)
                p.setBrush(QColor(b.color))
                p.drawRoundedRect(tr, 8, 8)
                if font is None:
                    font = self.bnd_font()
                p.setFont(font)
                p.setPen(qc(text_on(b.color)))
                p.drawText(tr, Qt.AlignmentFlag.AlignCenter, b.title)

    def bnd_at(self, wx, wy):  # topmost boundary whose outline or title tab is under the point
        if not self.bnds:
            return None
        tol = min(9 / self.zoom, 14)
        for b, r, tr in reversed(self._brects):
            if tr is not None and tr.contains(wx, wy):
                return b
            if r.adjusted(-tol, -tol, tol, tol).contains(wx, wy) and not (
                    r.width() > 2 * tol and r.height() > 2 * tol
                    and r.adjusted(tol, tol, -tol, -tol).contains(wx, wy)):
                return b
        return None

    def bnd_toggle(self):  # key B: boundary around the selected topics; B again (or Delete) removes it
        if self.edit_node:
            return
        b, ts = self.sel_bnd, []
        if b is None:
            ts = [n for n in self.top_selected() if n is not self.root]
            if not ts:
                return
            if any(n.parent is not ts[0].parent for n in ts):
                QToolTip.showText(QCursor.pos(), "Select topics that share the same parent")
                return
            ids = {id(n) for n in ts}
            b = next((x for x in self.bnds if {id(n) for n in x.nodes} == ids), None)
        self.push_undo()
        if b is not None:  # already there: remove it
            was_sel = b is self.sel_bnd
            self.bnds = [x for x in self.bnds if x is not b]
            self.sel_bnd = None
            if was_sel:
                self.sels = [self.sel]
        else:
            par = ts[0].parent
            ts.sort(key=par.children.index)
            nb = Bnd(ts, self.bnd_color)
            self.bnds.append(nb)
            self.sels, self.sel_bnd = [], nb  # selected, so its colour can be changed right away
        self.relayout()

    def bnd_rename(self, b):  # double-click on a boundary: set its title (empty = no title tab)
        self.sel_bnd, self.sels = b, []
        self.update()
        t, ok = QInputDialog.getText(self.win, "Boundary", "Title (leave empty for none)", text=b.title)
        if ok:
            t = " ".join(t.split())[:40]
            if t != b.title:
                self.push_undo()
                b.title = t
                self.relayout()
        self.setFocus()

    def dotpos(self, n, x=None, y=None):
        x = n.x if x is None else x
        y = n.y if y is None else y
        if self.layout_mode == "Progress chart" and n.depth == 1:  # sub topics hang off the top / bottom edge
            return x + n.w / 2, (y if n.up else y + n.h)
        R = n.eff == "R"
        edge = x + n.w if R else x
        off = self.dot_off(n)
        return edge + (off if R else -off), y + (n.h / 2 if n.depth <= 1 or self.child_type == "Empty" else n.h)

    def draw_prog_conn(self, p, pa, c):  # progress chart: one line through the main topics, and a vertical line out of each
        if pa.parent is None:
            i = pa.children.index(c)
            a = pa.children[i - 1] if i else pa
            p.setPen(pen(QColor(self.line_color), 4))
            p.drawLine(QLineF(a.x + a.w, c.cy, c.x, c.cy))
            return
        empty = self.child_type == "Empty"
        ay = c.cy if empty else c.ay
        x0, y0 = pa.cx, (pa.y if pa.up else pa.y + pa.h)
        px = PADS[min(c.depth, 3)][0]
        ex = c.x + (px - 16) if empty else c.x + min(40.0, c.w)  # where the line ends (Empty: same as Map, leaving a gap before the text)
        tail = ex - x0
        cend = ex - 10 if empty else ex  # where the curve itself finishes and the flat tail starts
        if self.child_line == "Curve":  # tapered curve: leaves the main topic vertically, bends into the sub topic
            key = ("prog", round(x0, 1), round(y0, 1), round(ex, 1), round(ay, 1), empty)
            poly = self._curves.get(key)
            if poly is None:
                dy = ay - y0
                x1, y1 = x0, y0 + dy * 0.6
                x2, y2 = cend - (cend - x0) * 0.6, ay
                left, right = [], []
                N = 28
                for i in range(N + 1):
                    t = i / N
                    u = 1 - t
                    bx = u ** 3 * x0 + 3 * u * u * t * x1 + 3 * u * t * t * x2 + t ** 3 * cend
                    by = u ** 3 * y0 + 3 * u * u * t * y1 + 3 * u * t * t * y2 + t ** 3 * ay
                    tx = 3 * u * u * (x1 - x0) + 6 * u * t * (x2 - x1) + 3 * t * t * (cend - x2)
                    ty = 3 * u * u * (y1 - y0) + 6 * u * t * (y2 - y1) + 3 * t * t * (ay - y2)
                    ln = math.hypot(tx, ty) or 1.0
                    m = min(1.0, max(0.0, (t - 0.3) / 0.7))
                    m = m * m * (3 - 2 * m)
                    hw = (5.5 + (3.0 - 5.5) * m) / 2
                    nx, ny = -ty / ln, tx / ln
                    left.append(QPointF(bx + nx * hw, by + ny * hw))
                    right.append(QPointF(bx - nx * hw, by - ny * hw))
                if ex != cend:  # flat tail from the end of the curve toward the text
                    left.append(QPointF(ex, left[-1].y()))
                    right.append(QPointF(ex, right[-1].y()))
                poly = QPainterPath(left[0])
                for q in left[1:] + right[::-1]:
                    poly.lineTo(q)
                poly.closeSubpath()
                if len(self._curves) > 5000:
                    self._curves.clear()
                self._curves[key] = poly
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QColor(self.line_color))
            p.drawPath(poly)
            p.setBrush(NOBRUSH)
            return
        path = QPainterPath(QPointF(x0, y0))
        if self.child_line == "Elbow":  # straight down / up, rounded corner, then sideways
            sy = 1 if ay > y0 else -1
            r = min(14.0, tail, abs(ay - y0))
            path.lineTo(x0, ay - sy * r)
            path.cubicTo(x0, ay - sy * r * 0.5523, x0 + r * 0.4477, ay, x0 + r, ay)
            path.lineTo(ex, ay)
        else:
            path.lineTo(x0, ay)
            if empty:  # short tail towards the text
                path.lineTo(ex, ay)
        p.setBrush(NOBRUSH)
        p.setPen(pen(QColor(self.line_color), 3.0))
        p.drawPath(path)

    def draw_conn(self, p, pa, c):
        R = c.eff == "R"
        p.setBrush(NOBRUSH)
        path = QPainterPath()
        if self.layout_mode == "Progress chart" and pa.depth <= 1:
            return self.draw_prog_conn(p, pa, c)
        if pa.parent is None:
            ex = c.x if R else c.x + c.w
            if self.line == "Curved":
                mx = (pa.cx + ex) / 2
                path.moveTo(pa.cx, pa.cy)
                path.cubicTo(mx, pa.cy, mx, c.cy, ex, c.cy)
            elif self.line == "Rounded":  # leaves the root vertically, bends round into the topic horizontally
                # start where the Curved line to this topic would cross the root's top/bottom edge,
                # so the lines are spaced out along the root exactly like Curved (and never cross)
                dyy = c.cy - pa.cy
                q = (pa.h / 2) / abs(dyy) if dyy else 1.0  # share of the way up/down that the root edge is
                f = 1.0
                if q < 1:
                    lo, hi = 0.0, 1.0
                    for _ in range(30):  # solve 3t^2 - 2t^3 = q (the Curved line's height at parameter t)
                        t = (lo + hi) / 2
                        lo, hi = (t, hi) if 3 * t * t - 2 * t ** 3 < q else (lo, t)
                    f = 1.5 * t - 1.5 * t * t + t ** 3  # the Curved line's sideways travel at that point
                lim = pa.w / 2 - 14  # keep the start inside the root's width
                x0 = pa.cx + max(-lim, min(lim, (ex - pa.cx) * f))
                dxx = ex - x0
                k = 0.5523  # makes the cubic a true quarter ellipse
                path.moveTo(x0, pa.cy)
                path.cubicTo(x0, pa.cy + k * dyy, ex - k * dxx, c.cy, ex, c.cy)
            elif self.line == "Elbow":  # horizontal - rounded corner - vertical - rounded corner - horizontal
                edge = pa.x + pa.w if R else pa.x
                path = elbow_path(pa.cx, pa.cy, (edge + ex) / 2, ex, c.cy, 24)
            else:
                path.moveTo(ex, c.cy)
                path.lineTo(pa.cx, pa.cy)
            p.setPen(pen(QColor(self.line_color), 4))
            p.drawPath(path)
            return
        dx, dy = self.dotpos(pa)
        bus = c.x if R else c.x + c.w
        ay = c.cy if self.child_type == "Empty" else c.ay  # Empty: no underline, so aim at the middle of the text
        sg = 1 if R else -1
        end = bus + sg * (PADS[min(c.depth, 3)][0] - 16) if self.child_type == "Empty" else bus  # tail reaching toward the text, leaving a small gap
        if self.child_type == "Empty" and (c.color or c is self.edit_node or id(c) in self._deco):
            end = bus - sg * 9  # a box is drawn round this topic: don't run the line into it
        cend = end - sg * 10 if self.child_type == "Empty" else bus  # where the curve itself finishes and the flat tail starts
        if self.child_line == "Curve":  # smooth S-curve from the parent's dot into the child's underline
            key = (round(dx, 1), round(dy, 1), round(cend, 1), round(ay, 1), round(end, 1))
            poly = self._curves.get(key)  # the shape only depends on the geometry: build it once, reuse on every repaint
            if poly is None:
                k = (cend - dx) * 0.8  # long handles: a rounder, more pronounced S
                x1, x2 = dx + k, cend - k
                left, right = [], []
                N = 28
                for i in range(N + 1):  # thick at the parent, tapering smoothly down to the underline's 3.0
                    t = i / N
                    u = 1 - t
                    bx = u ** 3 * dx + 3 * u * u * t * x1 + 3 * u * t * t * x2 + t ** 3 * cend
                    by = u ** 3 * dy + 3 * u * u * t * dy + 3 * u * t * t * ay + t ** 3 * ay
                    tx = 3 * u * u * (x1 - dx) + 6 * u * t * (x2 - x1) + 3 * t * t * (cend - x2)
                    ty = 6 * u * t * (ay - dy)
                    ln = math.hypot(tx, ty) or 1.0
                    m = min(1.0, max(0.0, (t - 0.3) / 0.7))
                    m = m * m * (3 - 2 * m)  # smoothstep
                    hw = (5.5 + (3.0 - 5.5) * m) / 2
                    nx, ny = -ty / ln, tx / ln
                    left.append(QPointF(bx + nx * hw, by + ny * hw))
                    right.append(QPointF(bx - nx * hw, by - ny * hw))
                if end != cend:  # flat tail from the end of the curve toward the text
                    left.append(QPointF(end, left[-1].y()))
                    right.append(QPointF(end, right[-1].y()))
                poly = QPainterPath(left[0])
                for q in left[1:] + right[::-1]:
                    poly.lineTo(q)
                poly.closeSubpath()
                if len(self._curves) > 5000:
                    self._curves.clear()
                self._curves[key] = poly
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QColor(self.line_color))
            p.drawPath(poly)
            p.setBrush(NOBRUSH)
            return
        if self.child_line == "Elbow" and self.child_type == "Empty":  # same dot line / tail / gap as the straight Empty style
            path = elbow_path(dx, dy, dx + sg * min(22, abs(bus - dx) / 2), end, ay, 14)
        elif self.child_line == "Elbow":  # corner into the vertical, second corner into the topic's underline
            path = elbow_path(dx, dy, bus, bus + (14 if R else -14), ay, 14)
        elif self.child_type == "Empty":  # no underline: pull the vertical back a little so each child gets a short horizontal tail
            vx = dx + sg * min(30, abs(bus - dx) / 2)
            path.moveTo(dx, dy)
            path.lineTo(vx, dy)
            path.lineTo(vx, ay)
            path.lineTo(end, ay)
        else:
            path.moveTo(dx, dy)
            path.lineTo(bus, dy)
            path.lineTo(bus, ay)
        p.setPen(pen(QColor(self.line_color), 3.0))
        p.drawPath(path)

    def draw_node(self, p, n, x=None, y=None, marker=True):
        x = n.x if x is None else x
        y = n.y if y is None else y
        px, py = PADS[min(n.depth, 3)]
        base = (self.root_fill_color if n.depth == 0 else self.fill_color) if (n.depth <= 1 and self.fill_on and not n.color) else self.bg_color
        fg = qc(text_on(base))  # white on dark backgrounds, black on light ones
        if n.depth <= 1:
            p.setBrush(tint(n.color) if n.color else QColor(self.root_fill_color if n.depth == 0 else self.fill_color) if self.fill_on else QColor(self.bg_color))
            p.setPen(pen(QColor(n.color) if n.color else QColor(self.line_color), 4 if not n.color else 3))
            p.drawPath(self.box_path(n, x, y, -1))
        else:
            if n.color:  # sub topics get a filled background behind the text
                p.setPen(pen(QColor(n.color), 2))
                p.setBrush(tint(n.color))
                p.drawPath(rect_path(x, y, n.w, n.h, 4))
            if self.child_type != "Empty":
                p.setPen(pen(QColor(self.line_color), 3.0))
                p.drawLine(QLineF(x, y + n.h, x + n.w, y + n.h))
        if n.icon:
            s = ICON_SIZES[min(n.depth, 3)]
            draw_icon(p, n.icon, x + px, y + n.h / 2 - s / 2, s)
        if not self._lod and n is not self.edit_node:  # far zoomed out on a huge map the text is unreadable anyway: skip it
            _, lines, _, _ = self.lay(n.text, n.depth, n.fw)
            p.setPen(fg)
            ox = x + px + n.iw
            for ln in lines:
                ln.draw(p, QPointF(ox + (n.tw - ln.naturalTextWidth()) / 2, y + py))
        if n.note:
            draw_note(p, *self.note_pos(n, x, y), fg)
        if marker and n.children and n.parent:
            dx, dy = self.dotpos(n, x, y)
            p.setPen(NOPEN)
            p.setBrush(QColor(self.line_color))
            if n.folded:
                p.drawEllipse(QPointF(dx, dy), 8, 8)
                f = QFont()
                f.setFamilies(FAMILIES)
                f.setPixelSize(12)
                f.setBold(True)
                p.setFont(f)
                p.setPen(qc(text_on(self.line_color)))
                p.drawText(QRectF(dx - 8, dy - 8, 16, 16), Qt.AlignmentFlag.AlignCenter, str(len(n.children)))
            else:
                r = 9 if n.depth <= 2 else 8
                p.drawEllipse(QPointF(dx, dy), r, r)

    # ---------- notes ----------
    def note_pos(self, n, x=None, y=None):  # (x, y, size) of the note badge, at the right end of the topic
        x = n.x if x is None else x
        y = n.y if y is None else y
        s = NOTE_SIZES[min(n.depth, 3)]
        px = PADS[min(n.depth, 3)][0]
        return x + px + n.iw + n.tw + NOTE_GAP, y + n.h / 2 - s / 2, s

    def on_badge(self, n, wx, wy):
        bx, by, s = self.note_pos(n)
        return bx - 6 <= wx <= bx + s + 6 and by - 6 <= wy <= by + s + 6

    def place_note(self):  # keep the popup just below its topic (above it near the bottom edge)
        n = self.note_node
        if n is None:
            return
        z, w, h = self.zoom, 600, 240
        x, y = int(n.x * z + self.ox), int((n.y + n.h) * z + self.oy + 10)
        if y + h > self.height() - 8:
            y = int(n.y * z + self.oy - h - 10)
        self.note_box.setGeometry(max(8, min(x, self.width() - w - 8)), max(8, y), w, h)

    def open_note(self, n):
        self.commit_edit()
        self.note_node = n
        self.note_box.set_bg(self.bg_color)
        self.note_box.setPlainText(n.note)
        self.place_note()
        self.note_box.setVisible(True)
        self.note_box.setFocus()
        self.note_box.moveCursor(self.note_box.textCursor().MoveOperation.End)

    def close_note(self, by_blur=False):  # saves the text; empty text removes the note
        n = self.note_node
        if n is None:
            return
        self.note_node = None
        txt = self.note_box.toPlainText().strip()
        self.note_box.setVisible(False)
        if txt != n.note:
            self.push_undo()
            n.note = txt
            self.relayout()
        if by_blur:
            self._nb = (n, time.monotonic())
        self.setFocus()
        self.update()

    def toggle_note(self):  # key N / toolbar button: write or show the note of the selected topic
        if self.note_node is self.sel:
            self.close_note()
        else:
            self.open_note(self.sel)

    def note_click(self, n):  # click on a badge: open the note, or close it if it was open
        was = self.note_node or (self._nb[0] if self._nb and time.monotonic() - self._nb[1] < 0.5 else None)
        self._nb = None
        self.close_note()
        self.sel = n
        if was is not n:
            self.open_note(n)
        self.update()

    # ---------- coordinates / hit testing ----------
    def to_world(self, x, y):
        return (x - self.ox) / self.zoom, (y - self.oy) / self.zoom

    def hit(self, wx, wy):
        for n in reversed(self.vis):
            if n.children and n.parent:
                dx, dy = self.dotpos(n)
                if math.hypot(wx - dx, wy - dy) < 9:
                    return n, True
            if n.x - 3 <= wx <= n.x + n.w + 3 and n.y - 3 <= wy <= n.y + n.h + 3:
                return n, False
        return None, False

    def zoom_at(self, f, sx, sy):
        wx, wy = self.to_world(sx, sy)
        self.zoom = max(0.1, min(3.0, self.zoom * f))
        self.ox, self.oy = sx - wx * self.zoom, sy - wy * self.zoom
        self.update()

    def zoom_center(self, f):
        self.zoom_at(f, self.width() / 2, self.height() / 2)

    def ensure_visible(self, n):
        W, H, z = self.width(), self.height(), self.zoom
        sx, sy = n.x * z + self.ox, n.y * z + self.oy
        if sx < 30: self.ox += 30 - sx
        if sx + n.w * z > W - 30: self.ox -= sx + n.w * z - (W - 30)
        if sy < 30: self.oy += 30 - sy
        if sy + n.h * z > H - 30: self.oy -= sy + n.h * z - (H - 30)

    # ---------- width handle on the selected topic ----------
    def grips(self, n):  # [(x, side, y)] of the grab handles: on the edge facing away from the parent
        gy = n.y + n.h * 0.22 if (n.parent and n.children and n.depth <= 1) else n.cy  # keep clear of the fold dot
        if n.parent is None:
            return [(n.x - 6, -1, gy), (n.x + n.w + 6, 1, gy)]
        return [(n.x + n.w + 6, 1, gy)] if n.eff == "R" else [(n.x - 6, -1, gy)]

    def handle_at(self, wx, wy):
        if self.edit_node or len(self.sels) != 1 or self.sels[0] not in self.vis:
            return None
        n = self.sels[0]
        if not (n.y - 6 <= wy <= n.y + n.h + 6):
            return None
        if n.parent and n.children:  # the fold dot wins over the handle
            dx, dy = self.dotpos(n)
            if math.hypot(wx - dx, wy - dy) < 9:
                return None
        for hx, side, _ in self.grips(n):
            if abs(wx - hx) <= (GRIP + 2) / self.zoom:
                return n, side
        return None

    def update_cursor(self, x, y):
        if self.rel_from is not None:  # picking a relationship target: keep the cross cursor
            self.setCursor(Qt.CursorShape.CrossCursor)
            return
        wx, wy = self.to_world(x, y)
        if self.rel_handle_at(wx, wy) is not None:
            self._hcur = True
            self.setCursor(Qt.CursorShape.SizeAllCursor)
            return
        on = self.handle_at(wx, wy) is not None
        if on != getattr(self, "_hcur", False):
            self._hcur = on
            if on:
                self.setCursor(Qt.CursorShape.SizeHorCursor)
            else:
                self.unsetCursor()

    # ---------- mouse ----------
    def has_mods(self, e):  # Ctrl or Shift held
        return bool(e.modifiers() & (Qt.KeyboardModifier.ControlModifier | Qt.KeyboardModifier.ShiftModifier))

    def mousePressEvent(self, e):
        self.setFocus()
        self.commit_edit()
        x, y = e.position().x(), e.position().y()
        self.mx, self.my = x, y
        self.drag = {"mode": "none", "sx": x, "sy": y}
        b, M = e.button(), Qt.MouseButton
        if b in (M.MiddleButton, M.RightButton):  # middle / right button pans
            self.drag.update(mode="pan", ox=self.ox, oy=self.oy)
            return
        if b != M.LeftButton:
            return
        self.sel_bnd = None  # (set again below when a boundary is clicked)
        mods = self.has_mods(e)
        wx, wy = self.to_world(x, y)
        if self.rel_from is not None:  # relationship pending: this click picks the target (empty space cancels)
            self.rel_finish(self.hit(wx, wy)[0])
            return
        rh = None if mods else self.rel_handle_at(wx, wy)
        if rh:  # grab a curve handle of the selected relationship
            self.drag.update(mode="relh", rel=rh[0], h=rh[1], active=False)
            return
        h = None if mods else self.handle_at(wx, wy)
        if h:  # grab the width handle of the selected topic
            hn, side = h
            edge = hn.x + hn.w if side > 0 else hn.x
            root = hn.parent is None
            anchor = hn.cx if root else (hn.x if side > 0 else hn.x + hn.w)
            self.drag.update(mode="resize", node=hn, side=side, off=wx - edge, anchor=anchor,
                             k=2 if root else 1, active=False)
            self.setCursor(Qt.CursorShape.SizeHorCursor)
            return
        n, mk = self.hit(wx, wy)
        if n is None and not mods:
            r = self.rel_at(wx, wy)
            if r:  # click on a relationship curve selects it (shows its handles)
                self.sels = []
                self.sel_rel = r
                self.update()
                return
            bd = self.bnd_at(wx, wy)
            if bd:  # click on a boundary outline or its title tab selects it
                self.sels = []
                self.sel_rel = None
                self.sel_bnd = bd
                self.update()
                return
        self.sel_rel = None
        if n is not None:
            if mk:
                self.push_undo()
                n.folded = not n.folded
                self.relayout()
                return
            if n.note and not mods and self.on_badge(n, wx, wy):
                return self.note_click(n)
            if mods:  # Ctrl/Shift+click adds or removes a node
                cur = list(self.sels)
                if n in cur and len(cur) > 1:
                    cur.remove(n)
                elif n not in cur:
                    cur.append(n)
                self.sel = n if n in cur else cur[-1]
                self.sels = cur
            elif not (n in self.sels and len(self.sels) > 1 and n is not self.root):
                self.sel = n  # (a click inside a group keeps it, so the group can be dragged)
            self.update()
        if n is None:  # left drag on empty canvas draws a selection box
            self.sels = list(self.sels) if mods else []
            self.drag.update(mode="marquee", wx=wx, wy=wy, rect=(wx, wy, wx, wy), active=False,
                             base=list(self.sels))
        elif n is self.root and not self.edit_node:  # dragging the root moves the whole map
            self.drag.update(mode="pan", ox=self.ox, oy=self.oy)
        elif n is not self.root and not self.edit_node:
            ts = self.targets()
            multi = n in ts and len(ts) > 1
            group = [m for m in ts if m is not self.root and not any(m is not o and m.under(o) for o in ts)] if multi else [n]
            self.drag.update(mode="node", node=n, group=group, gx=wx - n.x, gy=wy - n.y,
                             active=False, target=None, px=wx, py=wy,
                             collapse=multi and not mods)
        self.update()

    def mouseDoubleClickEvent(self, e):
        if e.button() != Qt.MouseButton.LeftButton:
            return
        wx, wy = self.to_world(e.position().x(), e.position().y())
        h = self.handle_at(wx, wy)
        if h:  # double-click the handle: back to automatic width
            if h[0].fw:
                self.push_undo()
                h[0].fw = None
                self.relayout()
            return
        n, mk = self.hit(wx, wy)
        if n is None:
            bd = self.bnd_at(wx, wy)
            if bd:
                self.bnd_rename(bd)
            return
        if mk:
            self.push_undo()
            n.folded = not n.folded
            self.relayout()
            return
        if n.note and self.on_badge(n, wx, wy):
            return self.note_click(n)
        self.sel = n
        self.start_edit(n)

    def mouseMoveEvent(self, e):
        x, y = e.position().x(), e.position().y()
        self.mx, self.my = x, y
        d = self.drag
        if not d or d["mode"] == "none":
            if not d:
                self.update_cursor(x, y)
                if self.rel_from is not None:
                    self.update()  # redraw the rubber band
            return
        dx, dy = x - d["sx"], y - d["sy"]
        if d["mode"] == "relh":
            r = d["rel"]
            if not d["active"]:
                if math.hypot(dx, dy) < 3:
                    return
                d["active"] = True
                self.push_undo()  # one undo step for the whole drag
                if r.o1 is None:  # first drag: turn the automatic bow into explicit handles
                    c1, c2 = self.rel_ctrl(r)
                    r.o1, r.o2 = (c1[0] - r.a.cx, c1[1] - r.a.cy), (c2[0] - r.b.cx, c2[1] - r.b.cy)
            wx, wy = self.to_world(x, y)
            n = r.a if d["h"] == 0 else r.b
            o = (wx - n.cx, wy - n.cy)
            if d["h"] == 0:
                r.o1 = o
            else:
                r.o2 = o
            self.update()
            return
        if d["mode"] == "resize":
            if not d["active"]:
                if abs(dx) < 2:
                    return
                d["active"] = True
                self.push_undo()  # one undo step for the whole drag
            n = d["node"]
            wx = self.to_world(x, y)[0]
            w = d["k"] * d["side"] * ((wx - d["off"]) - d["anchor"])
            fw = int(round(w - 2 * PADS[min(n.depth, 3)][0] - n.iw - n.nw))
            n.fw = max(MINFW, min(4000, fw))
            self.relayout()
            return
        if d["mode"] == "pan":
            self.ox, self.oy = d["ox"] + dx, d["oy"] + dy
        else:
            if math.hypot(dx, dy) > 6:
                d["active"] = True
            if d["active"]:
                px, py = self.to_world(d["sx"] + dx, d["sy"] + dy)
                if d["mode"] == "node":
                    d["px"], d["py"] = px, py
                    d["target"] = self.find_target(d["node"], px, py, d["group"])
                else:
                    r = d["rect"] = (min(d["wx"], px), min(d["wy"], py), max(d["wx"], px), max(d["wy"], py))
                    hit = [m for m in self.vis if m is not self.root and m.x < r[2] and m.x + m.w > r[0]
                           and m.y < r[3] and m.y + m.h > r[1]]
                    self.sels = d["base"] + [m for m in hit if m not in d["base"]]
        self.update()

    def mouseReleaseEvent(self, e):
        d, self.drag = self.drag, None
        self._hcur = True  # force the cursor to be re-evaluated below
        self.update_cursor(e.position().x(), e.position().y())
        if d and d["mode"] == "pan" and e.button() == Qt.MouseButton.RightButton:
            rx, ry = e.position().x(), e.position().y()
            if math.hypot(rx - d["sx"], ry - d["sy"]) < 4 and self.hit(*self.to_world(rx, ry))[0] is self.root:
                self.win.pick_root_fill_color()  # right-click on the root topic: its fill colour
                return
        if d and d["mode"] == "node":
            if d["active"] and d["target"]:
                self.do_move(d["group"], *d["target"], side=self.drop_side(d["px"]))
            elif not d["active"] and d["collapse"]:
                self.sel = d["node"]
        elif d and d["mode"] == "marquee":
            ss = [m for m in self.sels if m in self.vis]
            if ss:
                self.sel = self.sel if self.sel in ss else ss[0]
                self.sels = ss
            else:
                self.sels = []  # clicked / dragged over empty space: deselect everything
        self.update()

    def drop_side(self, wx):
        return "R" if self.layout_mode != "Map" or wx >= self.root.cx else "L"

    def find_target(self, node, wx, wy, group=None):
        group = group or [node]
        GX, GY = 14, 10  # grow every box so the gaps between siblings are droppable
        blocked = lambda m: any(m.under(g) for g in group)  # can't drop a topic into itself
        for m in reversed(self.vis):
            if m.x - GX <= wx <= m.x + m.w + GX and m.y - GY <= wy <= m.y + m.h + GY and not blocked(m):
                if m is self.root:
                    return m, "child"
                f = (wy - (m.y - GY)) / (m.h + 2 * GY)
                return m, ("before" if f < .3 else "after" if f > .7 else "child")
        if all(g.parent is self.root for g in group):
            # main topic(s) released in free space: side from pointer x, slot from pointer y
            kids = [c for c in self.root.children if c not in group and c.eff == self.drop_side(wx)]
            for c in kids:
                if wy < c.cy:
                    return c, "before"
            return (kids[-1], "after") if kids else (self.root, "child")
        # nothing under the pointer: snap to the nearest node in the same column
        best, bd = None, 40
        for m in self.vis:
            if m is self.root or not (m.x - GX <= wx <= m.x + m.w + GX) or blocked(m):
                continue
            d = max(m.y - wy, wy - (m.y + m.h), 0)
            if d < bd:
                best, bd = m, d
        if best:
            return best, ("before" if wy < best.cy else "after")
        return None

    def wheelEvent(self, e):
        ad, pd, mods, pos = e.angleDelta(), e.pixelDelta(), e.modifiers(), e.position()
        if mods & Qt.KeyboardModifier.ControlModifier:
            if ad.y():
                self.zoom_at(1.1 if ad.y() > 0 else 0.9, pos.x(), pos.y())
        elif mods & Qt.KeyboardModifier.ShiftModifier:  # Shift+wheel scrolls sideways
            self.ox += (ad.y() or ad.x()) / 120 * 80
        elif not pd.isNull():
            self.ox += pd.x()
            self.oy += pd.y()
        else:
            self.ox += ad.x() / 120 * 40
            self.oy += ad.y() / 120 * 40
        self.update()
        e.accept()

    def resizeEvent(self, e):
        super().resizeEvent(e)
        if self.rail:
            self.rail.move((self.width() - self.rail.width()) // 2, 14)
        if not self.sbar.isHidden():
            self.sbar.place()

    # ---------- undo ----------
    def path_of(self, n):
        p = []
        while n.parent:
            p.append(n.parent.children.index(n))
            n = n.parent
        return p[::-1]

    def node_at(self, path):
        n = self.root
        for i in path:
            if i >= len(n.children):
                break
            n = n.children[i]
        return n

    def snap(self):
        return json.dumps(self.root.to_dict()), self.path_of(self.sel), self.rels_data(), self.bnds_data()

    def push_undo(self):
        self.undo.append(self.snap())
        del self.undo[:-100]
        while len(self.undo) > 5 and sum(len(u[0]) for u in self.undo) > 60_000_000:  # huge maps: keep memory in check
            del self.undo[0]
        self.redo.clear()
        self.set_dirty(True)

    def restore(self, s):
        self.root = Node.from_dict(json.loads(s[0]))
        self.rels = parse_rels(s[2], self.root) if len(s) > 2 else []
        self.bnds = parse_bnds(s[3], self.root) if len(s) > 3 else []
        self.sel = self.node_at(s[1])
        self.rel_from = None
        self.edit_node, self.note_node = None, None
        self.entry.setVisible(False)
        self.note_box.setVisible(False)
        self.set_dirty(True)
        self.relayout()

    def undo_op(self):
        if self.undo:
            self.redo.append(self.snap())
            self.restore(self.undo.pop())

    def redo_op(self):
        if self.redo:
            self.undo.append(self.snap())
            self.restore(self.redo.pop())

    def set_dirty(self, v):
        self.dirty = v
        self.win.update_title()

    # ---------- editing ----------
    def fewer_side(self, exclude=None):
        k = [c for c in self.root.children if c is not exclude]
        return "R" if sum(c.side == "R" for c in k) <= sum(c.side == "L" for c in k) else "L"

    def new_node(self, parent, idx=None):
        self.push_undo()
        n = Node("New topic", self.fewer_side() if parent is self.root else "R")
        parent.folded = False
        parent.add(n, idx)
        self.sel = n
        self.relayout()
        self.ensure_visible(n)
        self.start_edit(n, True)

    def add_child(self):
        self.new_node(self.sel)

    def add_sibling(self):
        s = self.sel
        if s is self.root:
            return self.add_child()
        self.new_node(s.parent, s.parent.children.index(s) + 1)
        if s.parent is self.root:
            self.sel.side = s.side
            self.relayout()

    def delete(self):
        if self.sel_bnd is not None:  # a selected boundary goes first
            self.push_undo()
            self.bnds = [b for b in self.bnds if b is not self.sel_bnd]
            self.sel_bnd = None
            self.sels = [self.sel]
            self.relayout()
            return
        if self.sel_rel is not None:  # a selected relationship goes first
            self.push_undo()
            self.rels = [r for r in self.rels if r is not self.sel_rel]
            self.sel_rel = None
            self.sels = [self.sel]
            self.update()
            return
        ts = [n for n in self.targets() if n is not self.root]
        if not ts:
            return
        self.push_undo()
        top = self.tops(ts)
        p, i = top[0].parent, top[0].parent.children.index(top[0])
        gone = {id(n) for n in top}
        for q in {id(n.parent): n.parent for n in top}.values():  # one pass per parent, not one remove() per topic
            q.children = [c for c in q.children if id(c) not in gone]
        self.sel = p.children[min(i, len(p.children) - 1)] if p.children else p
        self.relayout()

    def reset_width(self):  # back to automatic width for every selected topic
        ts = [n for n in self.targets() if n.fw]
        if ts:
            self.push_undo()
            for n in ts:
                n.fw = None
            self.relayout()

    def toggle_fold(self):
        ts = [n for n in self.targets() if n is not self.root and n.children]
        if ts:
            self.push_undo()
            f = not ts[0].folded
            for n in ts:
                n.folded = f
            self.relayout()

    def set_color(self, hexv):  # None clears; applying the colour every target already has clears it
        ts = self.targets()
        if not ts:
            return
        self.push_undo()
        clear = hexv is None or all(n.color == hexv for n in ts)
        for n in ts:
            n.color = None if clear else hexv
        self.relayout()

    def toggle_icon(self, kind):
        ts = self.targets()
        if not ts:
            return
        self.push_undo()
        off = all(n.icon == kind for n in ts)
        for n in ts:
            n.icon = None if off else kind
        self.relayout()

    def clear_icon(self):
        ts = [n for n in self.targets() if n.icon]
        if ts:
            self.push_undo()
            for n in ts:
                n.icon = None
            self.relayout()

    def do_move(self, nodes, t, pos, side=None):
        nodes = nodes if isinstance(nodes, list) else [nodes]
        self.push_undo()
        for n in nodes:
            n.parent.children.remove(n)
        if pos == "child":
            t.folded = False
            for n in nodes:
                t.add(n)
                if t is self.root:
                    n.side = side or self.fewer_side(n)
        else:
            p = t.parent
            i = p.children.index(t) + (1 if pos == "after" else 0)
            for k, n in enumerate(nodes):
                p.add(n, i + k)
                if p is self.root:
                    n.side = t.side
        self.relayout()

    # ---------- copy / cut / paste of topics (with their children) ----------
    def top_selected(self):  # selected topics, without ones already inside another selected topic
        return self.tops(self.targets())

    @staticmethod
    def tops(ts):  # drop topics that sit inside another one of ts (walks up the parents: fast for huge selections)
        ids = {id(n) for n in ts}
        out = []
        for n in ts:
            q = n.parent
            while q is not None and id(q) not in ids:
                q = q.parent
            if q is None:
                out.append(n)
        return out

    def copy_nodes(self):
        ns = self.top_selected()
        if not ns:
            return False

        def outline(n, d):
            out = ["\t" * d + n.text.replace("\n", " ")]
            for c in n.children:
                out += outline(c, d + 1)
            return out

        data = QMimeData()
        data.setData(MIME, json.dumps([n.to_dict() for n in ns]).encode("utf-8"))
        data.setText("\n".join(l for n in ns for l in outline(n, 0)))  # plain-text outline for other apps
        QApplication.clipboard().setMimeData(data)
        return True

    def cut_nodes(self):
        if self.copy_nodes():
            self.delete()

    def paste_nodes(self):
        md = QApplication.clipboard().mimeData()
        if md is None:
            return
        specs = None
        if md.hasFormat(MIME):
            try:
                specs = json.loads(bytes(md.data(MIME)).decode("utf-8"))
            except Exception:
                specs = None
            if not (isinstance(specs, list) and all(isinstance(d, dict) for d in specs)):
                specs = None
        elif md.hasText():  # plain text: bullet/indented lists become topics, anything else one topic
            txt = md.text().replace("\r\n", "\n").replace("\r", "\n").strip()
            if txt:
                specs = parse_outline(txt) or [{"text": txt}]  # bullets / indentation -> child topics
        if not specs:
            return
        t = self.sel
        self.push_undo()
        t.folded = False
        new = []
        for d in specs:
            n = Node.from_dict(d)
            t.add(n)
            if t is self.root:
                n.side = self.fewer_side(n)
            new.append(n)
        self.relayout()
        self.sel = new[0]
        self.sels = new
        self.ensure_visible(self.sel)
        self.update()

    def start_edit(self, n, new=False):
        self.edit_node, self.edit_new = n, new
        z = self.zoom
        self.entry.setStyleSheet(self.entry_css % self.bg_color)  # same background as the map
        self.entry.setText(n.text)
        self.entry.setGeometry(max(0, int(n.x * z + self.ox - 8)), max(0, int(n.y * z + self.oy - 6)),
                               int(max(300, n.w * z + 24)), 38)
        self.entry.refit()
        self.entry.setVisible(True)
        self.entry.setFocus()
        self.entry.selectAll()
        self.update()

    def commit_edit(self, save=True):
        self.close_note()
        n = self.edit_node
        if n is None:
            return
        self.edit_node = None
        txt = self.entry.text().strip()
        self.entry.setVisible(False)
        if save and txt and txt != n.text:
            if not self.edit_new:
                self.push_undo()
            n.text = txt
            self.set_dirty(True)
            self.relayout()
        self.setFocus()
        self.update()

    def navigate(self, key):
        s = self.sel
        if self.layout_mode == "Progress chart" and s.depth == 1:  # Left / Right: along the row; Up / Down: into the sub topics
            K, ks = Qt.Key, self.root.children
            i = ks.index(s)
            if key == K.Key_Left:
                self.sel = ks[i - 1] if i else self.root
            elif key == K.Key_Right:
                if i + 1 < len(ks):
                    self.sel = ks[i + 1]
            elif s.children and (key == K.Key_Up) == s.up:
                s.folded = False
                self.relayout()
                self.sel = s.children[-1] if s.up else s.children[0]  # the nearest one
            self.ensure_visible(self.sel)
            self.update()
            return
        if key in (Qt.Key.Key_Up, Qt.Key.Key_Down):
            up = key == Qt.Key.Key_Up
            c = [m for m in self.vis if m is not s and m.depth == s.depth and m.eff == s.eff
                 and (m.cy < s.cy if up else m.cy > s.cy)]
            if c:
                self.sel = min(c, key=lambda m: abs(m.cy - s.cy))
        else:
            right = key == Qt.Key.Key_Right
            if s is self.root:
                k = [c for c in s.children if c.eff == ("R" if right else "L")]
                if k:
                    self.sel = k[0]
            elif (s.eff == "R") == right:
                if s.children:
                    s.folded = False
                    self.relayout()
                    self.sel = s.children[0]
            else:
                self.sel = s.parent
        self.ensure_visible(self.sel)
        self.update()

    # ---------- search (Ctrl+F) ----------
    @staticmethod
    def fold_text(s):  # case- and whitespace-insensitive form used for matching
        return " ".join(s.split()).casefold()

    def walk(self, n):  # every topic, including ones inside folded branches
        yield n
        for c in n.children:
            yield from self.walk(c)

    def search_scan(self):  # rebuild the match list for the current query
        q = self.search_q
        self.found = [n for n in self.walk(self.root) if q in self.fold_text(n.text)] if q else []
        self._fs = {id(n) for n in self.found}
        if self.found_cur not in self.found:
            self.found_cur = None
        self.search_label()

    def search_label(self):
        n = len(self.found)
        if not self.search_q:
            txt = ""
        elif not n:
            txt = "No results"
        elif self.found_cur in self.found:
            txt = f"{self.found.index(self.found_cur) + 1} of {n}"
        else:
            txt = f"{n} found"
        self.sbar.set_state(txt, bool(self.search_q) and not n)

    def search_set(self, text):  # called on every keystroke in the search box
        self.search_q = self.fold_text(text)
        self.search_scan()
        if self.found and self.found_cur is None:  # jump to the first match at or after the selection
            order = {id(n): i for i, n in enumerate(self.walk(self.root))}
            at = order.get(id(self.sel), 0)
            self.search_show(next((n for n in self.found if order[id(n)] >= at), self.found[0]))
        self.update()

    def search_show(self, n):  # make n the current match: unfold its ancestors, select it, bring it into view
        self.found_cur = n
        p, opened = n.parent, False
        while p:
            if p.folded:
                p.folded, opened = False, True
            p = p.parent
        if opened:
            self.relayout()
        self.sel = n
        self.reveal(n)
        self.search_label()
        self.update()

    def reveal(self, n):  # centre n unless it is already comfortably on screen
        z, W, H = self.zoom, self.width(), self.height()
        sx, sy = n.x * z + self.ox, n.y * z + self.oy
        if not (sx > 40 and sy > 120 and sx + n.w * z < W - 40 and sy + n.h * z < H - 40):
            self.ox = W / 2 - (n.x + n.w / 2) * z
            self.oy = H / 2 - (n.y + n.h / 2) * z

    def search_step(self, d):  # next (+1) / previous (-1) match, wrapping around
        if not self.found:
            return
        if self.found_cur in self.found:
            i = (self.found.index(self.found_cur) + d) % len(self.found)
        else:
            i = 0 if d > 0 else len(self.found) - 1
        self.search_show(self.found[i])

    def search_open(self):
        self.commit_edit()
        self.sbar.open()
        self.search_set(self.sbar.edit.text())  # reopening restores the previous query's highlights

    def search_close(self):
        self.sbar.hide()
        self.search_q, self.found, self._fs, self.found_cur = "", [], set(), None
        self.setFocus()  # the last match stays selected
        self.update()

    def escape(self):
        if self.rel_from is not None:
            self.rel_cancel()
        elif self.sbar.isHidden():
            self.collapse_sel()
        else:
            self.search_close()

    # ---------- keyboard ----------
    def keyPressEvent(self, e):
        if self.edit_node:
            return super().keyPressEvent(e)
        w, K = self.win, Qt.Key
        ctl = bool(e.modifiers() & Qt.KeyboardModifier.ControlModifier)
        sh = bool(e.modifiers() & Qt.KeyboardModifier.ShiftModifier)
        k = e.key()
        if ctl:
            acts = {K.Key_Z: self.redo_op if sh else self.undo_op, K.Key_Y: self.redo_op,
                    K.Key_S: w.save_as if sh else w.save, K.Key_O: w.open, K.Key_N: w.new,
                    K.Key_E: w.export, K.Key_0: self.fit_now, K.Key_A: self.select_all,
                    K.Key_C: self.copy_nodes, K.Key_V: self.paste_nodes, K.Key_X: self.cut_nodes,
                    K.Key_D: self.reset_width,
                    K.Key_F: self.search_open, K.Key_G: lambda: self.search_step(-1 if sh else 1),
                    K.Key_T: w.new, K.Key_W: w.close_current,
                    K.Key_Tab: lambda: w.next_tab(1), K.Key_Backtab: lambda: w.next_tab(-1),
                    K.Key_PageDown: lambda: w.next_tab(1), K.Key_PageUp: lambda: w.next_tab(-1)}
        else:
            acts = {K.Key_Escape: self.escape, K.Key_F3: lambda: self.search_step(-1 if sh else 1),
                    K.Key_Tab: self.add_child, K.Key_Return: self.add_sibling,
                    K.Key_Enter: self.add_sibling, K.Key_Delete: self.delete, K.Key_Backspace: self.delete,
                    #K.Key_Space: self.toggle_fold, K.Key_F2: lambda: self.start_edit(self.sel),
                    K.Key_Space: self.toggle_fold, K.Key_F: self.toggle_fold, K.Key_F2: lambda: self.start_edit(self.sel),
                    K.Key_E: lambda: self.start_edit(self.sel),
                    K.Key_1: lambda: self.set_color(COLORS[0][1]), K.Key_2: lambda: self.set_color(COLORS[1][1]),
                    K.Key_3: lambda: self.set_color(COLORS[2][1]), K.Key_4: lambda: self.set_color(COLORS[3][1]),
                    K.Key_0: lambda: self.set_color(None),
                    K.Key_C: lambda: self.toggle_icon("check"), K.Key_X: lambda: self.toggle_icon("error"),
                    K.Key_Q: self.clear_icon, K.Key_A: self.toggle_note, K.Key_R: self.rel_start,
                    K.Key_B: self.bnd_toggle,
                    K.Key_Plus: lambda: self.zoom_center(1.15), K.Key_Equal: lambda: self.zoom_center(1.15),
                    K.Key_Minus: lambda: self.zoom_center(1 / 1.15)}
            for a in (K.Key_Up, K.Key_Down, K.Key_Left, K.Key_Right):
                acts[a] = (lambda a=a: self.navigate(a))
            # vim-style: h/j/k/l mirror left/down/up/right
            for a, tgt in ((K.Key_H, K.Key_Left), (K.Key_J, K.Key_Down),
                           (K.Key_K, K.Key_Up), (K.Key_L, K.Key_Right)):
                acts[a] = (lambda t=tgt: self.navigate(t))
        fn = acts.get(k)
        if fn:
            fn()
            e.accept()
        else:
            super().keyPressEvent(e)

    # ---------- tabs: swap a document in and out of the canvas ----------
    def capture(self, d):
        d.root, d.layout_mode, d.shape, d.line = self.root, self.layout_mode, self.shape, self.line
        d.line_color = self.line_color
        d.bg_color, d.fill_on, d.fill_color = self.bg_color, self.fill_on, self.fill_color
        d.root_fill_color = self.root_fill_color
        d.child_line = self.child_line
        d.child_type = self.child_type
        d.sel_path = self.path_of(self.sel)
        d.path, d.dirty, d.undo, d.redo = self.path, self.dirty, self.undo, self.redo
        d.rels = self.rels
        d.bnds = self.bnds
        d.zoom, d.ox, d.oy, d.need_fit = self.zoom, self.ox, self.oy, self.need_fit

    def apply(self, d):
        self.root, self.layout_mode, self.shape, self.line = d.root, d.layout_mode, d.shape, d.line
        self.line_color = d.line_color
        self.bg_color, self.fill_on, self.fill_color = d.bg_color, d.fill_on, d.fill_color
        self.root_fill_color = d.root_fill_color
        self.child_line = d.child_line
        self.child_type = d.child_type
        self.sel = self.node_at(d.sel_path)
        self.path, self.dirty, self.undo, self.redo = d.path, d.dirty, d.undo, d.redo
        self.rels = d.rels
        self.bnds = d.bnds
        self.zoom, self.ox, self.oy, self.need_fit = d.zoom, d.ox, d.oy, d.need_fit
        self.edit_node, self.drag = None, None
        if self.rel_from is not None:
            self.rel_cancel()
        self.entry.setVisible(False)
        self.relayout()
        self.win.sync_controls()
        self.win.update_title()

    # ---------- files ----------
    def write(self, path):
        data = {"layout": self.layout_mode, "shape": self.shape, "line": self.line, "line_color": self.line_color,
                "bg_color": self.bg_color, "fill_on": self.fill_on, "fill_color": self.fill_color,
                "root_fill_color": self.root_fill_color,
                "child_line": self.child_line, "child_type": self.child_type,
                "root": self.root.to_dict(), "rels": self.rels_data()}
        if self.bnds:  # files without boundaries stay exactly as before
            data["bnds"] = self.bnds_data()
        tmp = path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=1)
        os.replace(tmp, path)
        self.path = path
        self.set_dirty(False)

    def load(self, d, path=None):
        self.root = Node.from_dict(d["root"]) if d else default_tree()
        self.layout_mode = d.get("layout", "Map") if d else self.layout_mode
        self.shape = d.get("shape", "Square") if d else self.shape
        self.line = d.get("line", "Straight") if d else self.line
        if self.line not in LINES:  # e.g. old files saved with the removed "Round" style
            self.line = "Straight"
        self.child_line = d.get("child_line", "Straight") if d else self.child_line
        if self.child_line not in CHILD_LINES:
            self.child_line = "Straight"
        self.child_type = d.get("child_type", "Normal") if d else self.child_type
        if self.child_type not in CHILD_TYPES:
            self.child_type = "Normal"
        lc = d.get("line_color") if d else None
        self.line_color = lc if isinstance(lc, str) and QColor(lc).isValid() else DEFAULT_LINE
        bc = d.get("bg_color") if d else None
        self.bg_color = bc if isinstance(bc, str) and QColor(bc).isValid() else DEFAULT_BG
        self.fill_on = bool(d.get("fill_on", False)) if d else False
        fc = d.get("fill_color") if d else None
        self.fill_color = fc if isinstance(fc, str) and QColor(fc).isValid() else DEFAULT_FILL
        rc = d.get("root_fill_color") if d else None
        self.root_fill_color = rc if isinstance(rc, str) and QColor(rc).isValid() else DEFAULT_ROOT_FILL
        self.sel, self.path = self.root, path
        self.rels = parse_rels(d.get("rels"), self.root) if d else []
        self.bnds = parse_bnds(d.get("bnds"), self.root) if d else []
        if self.rel_from is not None:
            self.rel_cancel()
        self.undo.clear()
        self.redo.clear()
        self.need_fit = True
        self.set_dirty(False)
        self.relayout()
        self.win.sync_controls()

    def export(self, path):
        x0, y0, x1, y1 = self.bounds()
        pad, S = 40, 2
        W, H = x1 - x0 + 2 * pad, y1 - y0 + 2 * pad
        ext = path.lower().rsplit(".", 1)[-1]
        img = None
        if ext == "svg":
            gen = QSvgGenerator()
            gen.setFileName(path)
            gen.setSize(QSize(int(W), int(H)))
            gen.setViewBox(QRectF(0, 0, W, H))
            p = QPainter(gen)
        elif ext == "pdf":
            wr = QPdfWriter(path)
            wr.setResolution(72)
            wr.setPageSize(QPageSize(QSizeF(W, H), QPageSize.Unit.Point))
            wr.setPageMargins(QMarginsF(0, 0, 0, 0))
            p = QPainter(wr)
        else:
            if W * H * S * S > 1.2e8 or max(W, H) * S > 32000:  # too big at 2x: fall back to 1x
                S = 1
            if W * H > 1.2e8 or max(W, H) > 32000:
                raise OSError("The map is too large to export as PNG - try SVG or PDF.")
            img = QImage(int(W * S), int(H * S), QImage.Format.Format_ARGB32)
            if img.isNull():
                raise OSError("The map is too large to export as PNG - try SVG or PDF.")
            img.fill(QColor(self.bg_color))
            p = QPainter(img)
            p.scale(S, S)
        p.setRenderHints(QPainter.RenderHint.Antialiasing | QPainter.RenderHint.TextAntialiasing)
        p.fillRect(QRectF(0, 0, W, H), QColor(self.bg_color))
        p.translate(pad - x0, pad - y0)
        self.draw_scene(p, False)
        p.end()
        if img is not None:
            if not img.save(path, "PNG"):
                raise OSError("Couldn't write the PNG file.")


# ---------- toolbar ----------
def gpen():
    return pen(QColor(205, 205, 210), 1.7, round_=True)


def L(p, x1, y1, x2, y2):
    p.drawLine(QLineF(x1, y1, x2, y2))


def poly(p, pts):
    path = QPainterPath()
    path.moveTo(*pts[0])
    for pt in pts[1:]:
        path.lineTo(*pt)
    p.drawPath(path)


def g_new(p):
    p.setPen(gpen()); p.setBrush(NOBRUSH)
    poly(p, [(6, 3), (14, 3), (18, 7), (18, 21), (6, 21), (6, 3)])
    L(p, 12, 11, 12, 17); L(p, 9, 14, 15, 14)


def g_plus(p):
    p.setPen(gpen()); L(p, 12, 5, 12, 19); L(p, 5, 12, 19, 12)


def g_open(p):
    p.setPen(gpen()); p.setBrush(NOBRUSH)
    poly(p, [(3, 7), (9, 7), (11, 9), (21, 9), (21, 19), (3, 19), (3, 7)])


def g_save(p):
    p.setPen(gpen()); p.setBrush(NOBRUSH)
    L(p, 12, 4, 12, 15); L(p, 7, 10, 12, 15); L(p, 17, 10, 12, 15); L(p, 5, 19, 19, 19)


def g_undo(p):
    p.setPen(gpen()); p.setBrush(NOBRUSH)
    poly(p, [(9, 6), (5, 10), (9, 14)])
    path = QPainterPath()
    path.moveTo(5, 10); path.lineTo(14, 10)
    path.cubicTo(18, 10, 19.5, 12.5, 19.5, 15)
    path.cubicTo(19.5, 17.5, 18, 19.5, 14, 19.5)
    path.lineTo(9, 19.5)
    p.drawPath(path)


def g_redo(p):
    p.save(); p.translate(24, 0); p.scale(-1, 1); g_undo(p); p.restore()


def g_export(p):
    p.setPen(gpen()); p.setBrush(NOBRUSH)
    L(p, 12, 15, 12, 4); L(p, 8, 8, 12, 4); L(p, 16, 8, 12, 4)
    poly(p, [(5, 12), (5, 20), (19, 20), (19, 12)])


def g_style(p):
    p.setPen(gpen()); p.setBrush(QColor(28, 28, 31))
    L(p, 4, 8, 20, 8); L(p, 4, 16, 20, 16)
    p.drawEllipse(QPointF(9, 8), 2.4, 2.4); p.drawEllipse(QPointF(15, 16), 2.4, 2.4)


def g_font(p):  # big "A" + small "a"
    p.setPen(gpen()); p.setBrush(NOBRUSH)
    poly(p, [(3, 19), (8, 5), (13, 19)]); L(p, 4.8, 14, 11.2, 14)
    p.drawEllipse(QPointF(17.5, 15.5), 2.7, 2.7); L(p, 20.2, 12.8, 20.2, 18.2)


def g_clear(p):
    p.setPen(gpen()); p.setBrush(NOBRUSH)
    p.drawEllipse(QPointF(12, 12), 7.5, 7.5); L(p, 7, 17, 17, 7)


def g_x(p):
    p.setPen(gpen()); L(p, 7, 7, 17, 17); L(p, 17, 7, 7, 17)


def g_search(p):
    p.setPen(gpen()); p.setBrush(NOBRUSH)
    p.drawEllipse(QPointF(10.5, 10.5), 6, 6); L(p, 15, 15, 20, 20)


def g_up(p):
    p.setPen(gpen()); p.setBrush(NOBRUSH)
    poly(p, [(6, 15), (12, 9), (18, 15)])


def g_down(p):
    p.setPen(gpen()); p.setBrush(NOBRUSH)
    poly(p, [(6, 9), (12, 15), (18, 9)])


def g_note(p):  # three lines, the last one shorter
    p.setPen(gpen()); L(p, 5, 7, 19, 7); L(p, 5, 12, 19, 12); L(p, 5, 17, 13, 17)


def g_rel(p):  # one dashed curved arrow
    p.setPen(gpen()); p.setBrush(NOBRUSH)
    path = QPainterPath()
    path.moveTo(3.5, 20)
    path.cubicTo(3.5, 8, 9, 4.5, 18, 4.5)
    p.setPen(pen(QColor(205, 205, 210), 2, [5, 2.6]))
    p.drawPath(path)
    p.setPen(gpen())
    poly(p, [(14.5, 1.2), (19.5, 4.5), (14.5, 7.8)])


def g_bnd(p):  # dashed rounded box with two short lines inside
    p.setPen(pen(QColor(205, 205, 210), 1.8, [4, 2.4])); p.setBrush(NOBRUSH)
    p.drawRoundedRect(QRectF(3, 4, 18, 16), 4, 4)
    p.setPen(gpen()); L(p, 8, 10, 16, 10); L(p, 8, 14.5, 13, 14.5)


def g_bndcolor(get):  # a small dashed box drawn in the colour new boundaries get
    def f(p):
        c = get()
        p.setPen(pen(QColor(c), 2.4, [3.6, 2.4])); p.setBrush(tint(c, 90))
        p.drawRoundedRect(QRectF(4.5, 4.5, 15, 15), 4, 4)
    return f


def g_fillnodes(get):  # on / off switch: dark track + knob right when on, grey track + knob left when off
    def f(p):
        on = get()
        p.setPen(QPen(QColor(205, 205, 210, 150), 1.2))
        p.setBrush(QColor("#242424") if on else QColor(90, 90, 98))
        p.drawRoundedRect(QRectF(0.6, 3.6, 32.8, 16.8), 8.4, 8.4)
        p.setPen(NOPEN)
        p.setBrush(QColor(255, 255, 255))
        p.drawEllipse(QPointF(25.4 if on else 9, 12), 5.6, 5.6)
    return f


def g_bgcolor(get):  # a rounded box filled with the background colour
    def f(p):
        p.setPen(QPen(QColor(255, 255, 255, 110), 1.5)); p.setBrush(QColor(get()))
        p.drawRoundedRect(QRectF(4.5, 4.5, 15, 15), 4, 4)
    return f


def g_fillcolor(get):  # a small topic box filled with the node fill colour
    def f(p):
        p.setPen(QPen(QColor(255, 255, 255, 110), 1.5)); p.setBrush(QColor(get()))
        p.drawRoundedRect(QRectF(3.5, 7, 17, 10), 3, 3)
    return f


def g_icon(kind):
    return lambda p: draw_icon(p, kind, 2, 2, 20)


def g_swatch(col):
    def f(p):
        p.setPen(QPen(QColor(255, 255, 255, 110), 1.5)); p.setBrush(QColor(col))
        p.drawEllipse(QPointF(12, 12), 7.5, 7.5)
    return f


def g_linecolor(get):  # a line segment drawn in the current line colour, inside a rounded box
    def f(p):
        p.setPen(QPen(QColor(255, 255, 255, 110), 1.5)); p.setBrush(NOBRUSH)
        p.drawRoundedRect(QRectF(4.5, 4.5, 15, 15), 4, 4)
        p.setPen(pen(QColor(get()), 3.2, round_=True))
        L(p, 7.5, 16.5, 16.5, 7.5)
    return f


class RailButton(QAbstractButton):
    def __init__(self, glyph, tip, cb=None, parent=None):
        super().__init__(parent)
        self.glyph = glyph
        self.setToolTip(tip)
        self.setFixedSize(34, 34)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setAttribute(Qt.WidgetAttribute.WA_Hover)
        if cb:
            self.clicked.connect(lambda *_: cb())

    def paintEvent(self, e):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        if self.isDown() or self.underMouse():
            p.setPen(NOPEN)
            p.setBrush(QColor(255, 255, 255, 46 if self.isDown() else 24))
            p.drawRoundedRect(QRectF(1, 1, self.width() - 2, 32), 8, 8)
        p.translate(5, 5)
        self.glyph(p)
        p.end()


class CloseBtn(QAbstractButton):
    def __init__(self):
        super().__init__()
        self.setFixedSize(18, 18)
        self.setToolTip("Close tab (Ctrl+W)")
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setAttribute(Qt.WidgetAttribute.WA_Hover)

    def paintEvent(self, e):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        if self.underMouse():
            p.setPen(NOPEN)
            p.setBrush(QColor(255, 255, 255, 40))
            p.drawEllipse(QRectF(1, 1, 16, 16))
        p.setPen(pen(QColor(200, 200, 205), 1.5, round_=True))
        L(p, 6, 6, 12, 12)
        L(p, 12, 6, 6, 12)
        p.end()


class SearchEdit(QLineEdit):
    """Find box. Enter / Down / F3 / Ctrl+G = next, Shift+Enter / Up / Shift+F3 = previous, Esc = close."""
    stepped = Signal(int)
    closed = Signal()

    def focusNextPrevChild(self, nxt):  # keep Tab inside the box
        return False

    def keyPressEvent(self, e):
        K, k = Qt.Key, e.key()
        ctl = bool(e.modifiers() & Qt.KeyboardModifier.ControlModifier)
        back = bool(e.modifiers() & Qt.KeyboardModifier.ShiftModifier)
        if k == K.Key_Escape:
            self.closed.emit()
        elif k in (K.Key_Return, K.Key_Enter, K.Key_F3, K.Key_Up, K.Key_Down) or (ctl and k == K.Key_G):
            self.stepped.emit(-1 if k == K.Key_Up else 1 if k == K.Key_Down else -1 if back else 1)
        elif ctl and k == K.Key_F:
            self.selectAll()
        else:
            super().keyPressEvent(e)
            if not ctl:
                e.accept()  # plain keys (Tab, arrows...) must not reach the map
            return  # unhandled Ctrl shortcuts (Ctrl+S ...) still reach the map
        e.accept()


class SearchBar(QFrame):
    """Floating find bar (Ctrl+F) in the top-right corner of the canvas."""

    def __init__(self, view):
        super().__init__(view)
        self.view = view
        self.setObjectName("search")
        self.setAttribute(Qt.WidgetAttribute.WA_NoMousePropagation)  # clicks on the bar don't hit the map
        self.setStyleSheet(
            "#search{background:#1c1c1f;border:1px solid #2e2e33;border-radius:14px;}"
            "QLineEdit{background:#111113;color:#fff;border:1px solid #3a3a40;border-radius:6px;"
            "padding:2px 8px;font-size:15px;selection-background-color:#3a6ea5;}"
            "QLineEdit:focus{border-color:#fff;}"
            "QLineEdit[bad=\"true\"]{border-color:#ed5454;}"
            "QLabel{color:#8a8a90;font-size:13px;}"
            "QToolTip{background:#2a2a2e;color:#eee;border:1px solid #3a3a40;padding:3px 6px;}")
        lay = QHBoxLayout(self)
        lay.setContentsMargins(10, 6, 8, 6)
        lay.setSpacing(1)
        self.edit = SearchEdit()
        self.edit.setPlaceholderText("Find topic")
        self.edit.setFixedSize(200, 30)
        self.count = QLabel()
        self.count.setFixedWidth(76)
        self.count.setAlignment(Qt.AlignmentFlag.AlignCenter)
        lay.addWidget(self.edit)
        lay.addWidget(self.count)
        for glyph, tip, cb in ((g_up, "Previous match (Shift+Enter)", lambda: view.search_step(-1)),
                               (g_down, "Next match (Enter)", lambda: view.search_step(1)),
                               (g_x, "Close (Esc)", view.search_close)):
            lay.addWidget(RailButton(glyph, tip, cb))
        self.edit.textChanged.connect(view.search_set)
        self.edit.stepped.connect(view.search_step)
        self.edit.closed.connect(view.search_close)
        self.hide()

    def open(self):
        self.show()
        self.place()
        self.raise_()
        self.edit.setFocus()
        self.edit.selectAll()

    def place(self):  # just below the toolbar, right-aligned
        v = self.view
        self.adjustSize()
        y = v.rail.geometry().bottom() + 10 if v.rail else 14
        self.move(max(8, v.width() - self.width() - 16), y)

    def set_state(self, text, bad):  # match counter text; red outline when nothing matches
        self.count.setText(text)
        if bool(self.edit.property("bad")) != bad:
            self.edit.setProperty("bad", bad)
            st = self.edit.style()
            st.unpolish(self.edit)
            st.polish(self.edit)


class TabBar(QTabBar):
    middleClicked = Signal(int)

    def mouseReleaseEvent(self, e):
        if e.button() == Qt.MouseButton.MiddleButton:
            i = self.tabAt(e.position().toPoint())
            if i >= 0:
                self.middleClicked.emit(i)
                return
        super().mouseReleaseEvent(e)


class ThemeItem(QWidget):  # one row of the Themes menu: a small mind map drawn in the theme's colours + its name
    PW, PH, K = 170, 64, 0.85  # preview size (before scaling)

    def __init__(self, theme, active, cb):
        super().__init__()
        self.t, self.active, self.cb = theme, active, cb
        self.setFixedSize(int(self.PW * self.K) + 20, int(self.PH * self.K) + 36)
        self.setAttribute(Qt.WidgetAttribute.WA_Hover)
        self.setCursor(Qt.CursorShape.PointingHandCursor)

    def mouseReleaseEvent(self, e):
        if e.button() == Qt.MouseButton.LeftButton:
            self.cb(self.t)

    def paintEvent(self, e):
        name, bg, root, fill, line, on = self.t
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        if self.underMouse():
            p.setPen(NOPEN)
            p.setBrush(QColor(255, 255, 255, 24))
            p.drawRoundedRect(QRectF(3, 2, self.width() - 6, self.height() - 4), 6, 6)
        p.save()
        p.translate(10, 8)
        p.scale(self.K, self.K)
        W, H = self.PW, self.PH
        p.setPen(pen(QColor("#555560"), 1))
        p.setBrush(QColor(bg))
        p.drawRoundedRect(QRectF(0, 0, W, H), 7, 7)
        lc = QColor(line)
        nf = QColor(fill if on else bg)
        rf = QColor(root if on else bg)
        for sx in (1, -1):  # right side, then the mirrored left side
            X = (lambda x: x) if sx == 1 else (lambda x: W - x)
            for cy, ry in ((16, 28), (48, 36)):
                p.setPen(pen(lc, 1.5))
                p.setBrush(NOBRUSH)
                path = QPainterPath(QPointF(X(112), cy))  # curve from the topic to the root
                path.cubicTo(QPointF(X(102), cy), QPointF(X(100), ry), QPointF(X(95), ry))
                p.drawPath(path)
                p.setBrush(nf)
                p.drawRoundedRect(QRectF(min(X(112), X(134)), cy - 5, 22, 10), 5, 5)  # topic pill
                p.drawLine(QPointF(X(134), cy), QPointF(X(139), cy))
                p.setPen(pen(lc, 1.2))
                p.drawLine(QPointF(X(139), cy - 8), QPointF(X(139), cy + 8))  # bracket + 3 sub topic underlines
                for dy in (-8, 0, 8):
                    p.drawLine(QPointF(X(139), cy + dy), QPointF(X(164), cy + dy))
        p.setPen(pen(lc, 1.8))
        p.setBrush(rf)
        p.drawRoundedRect(QRectF(W / 2 - 22, H / 2 - 9, 44, 18), 9, 9)  # root pill
        p.restore()
        p.setPen(self.palette().color(QPalette.ColorRole.WindowText))
        f = QFont(self.font())
        f.setPixelSize(14)
        p.setFont(f)
        p.drawText(QRectF(0, self.height() - 24, self.width(), 20), Qt.AlignmentFlag.AlignCenter, name)
        if self.active():
            p.setPen(NOPEN)
            p.setBrush(QColor("#3a6ea5"))
            p.drawEllipse(QPointF(12, self.height() - 14), 4, 4)
        p.end()


class Win(QMainWindow):
    def __init__(self):
        super().__init__()
        self.resize(1200, 760)
        self.setMinimumSize(700, 640)
        self.docs, self.cur, self._next_id, self._untitled = {}, None, 1, 0
        self.view = MapView(self)
        v = self.view

        central = QWidget()
        cl = QVBoxLayout(central)
        cl.setContentsMargins(0, 0, 0, 0)
        cl.setSpacing(0)
        cl.addWidget(v, 1)
        bar = QFrame()
        bar.setObjectName("tabbar")
        bar.setFixedHeight(34)
        bar.setStyleSheet("#tabbar{background:#0d0d0d;border-top:1px solid #26262a;}")
        bl = QHBoxLayout(bar)
        bl.setContentsMargins(10, 0, 10, 0)
        bl.setSpacing(4)
        self.tabs = TabBar()
        self.tabs.setShape(QTabBar.Shape.RoundedSouth)
        self.tabs.setExpanding(False)
        self.tabs.setMovable(True)
        self.tabs.setDrawBase(False)
        self.tabs.setUsesScrollButtons(True)
        self.tabs.setElideMode(Qt.TextElideMode.ElideRight)
        self.tabs.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.tabs.setStyleSheet(
            "QTabBar{background:transparent;}"
            "QTabBar::tab{background:#151518;color:#8a8a90;padding:6px 10px 6px 14px;margin:0 3px 0 0;"
            "border:1px solid #26262a;border-top:none;border-bottom-left-radius:8px;"
            "border-bottom-right-radius:8px;min-width:90px;max-width:220px;font-size:13px;}"
            "QTabBar::tab:selected{background:#26262b;color:#f2f2f4;}"
            "QTabBar::tab:hover:!selected{background:#1c1c20;color:#d0d0d5;}"
            "QToolTip{background:#2a2a2e;color:#eee;border:1px solid #3a3a40;padding:3px 6px;}")
        self.tabs.currentChanged.connect(self.on_tab_changed)
        self.tabs.middleClicked.connect(lambda i: self.close_id(self.tabs.tabData(i)))
        bl.addWidget(self.tabs)
        bl.addWidget(RailButton(g_plus, "New tab (Ctrl+T)", self.new))
        bl.addStretch(1)
        cl.addWidget(bar)
        self.setCentralWidget(central)

        rail = QFrame(v)
        rail.setObjectName("rail")
        rail.setStyleSheet("#rail{background:#1c1c1f;border:1px solid #2e2e33;border-radius:14px;}"
                           "QToolTip{background:#2a2a2e;color:#eee;border:1px solid #3a3a40;padding:3px 6px;}")
        lay = QHBoxLayout(rail)
        lay.setContentsMargins(8, 6, 8, 6)
        lay.setSpacing(1)

        def add(glyph, tip, cb):
            b = RailButton(glyph, tip, cb)
            lay.addWidget(b)
            return b

        def sep():
            f = QFrame()
            f.setFixedSize(1, 20)
            f.setStyleSheet("background:#33333a;")
            lay.addSpacing(4)
            lay.addWidget(f, 0, Qt.AlignmentFlag.AlignVCenter)
            lay.addSpacing(4)

        add(g_new, "New tab (Ctrl+N)", self.new)
        add(g_open, "Open (Ctrl+O)", self.open)
        add(g_save, "Save (Ctrl+S)", self.save)
        add(g_export, "Export PNG / SVG / PDF (Ctrl+E)", self.export)
        add(g_search, "Search (Ctrl+F)", v.search_open)
        add(g_undo, "Undo (Ctrl+Z)", v.undo_op)
        add(g_redo, "Redo (Ctrl+Y)", v.redo_op)
        sep()
        add(g_note, "Note on selected topic (key N)", v.toggle_note)
        add(g_rel, "Relationship from selected topic (key R)", v.rel_start)
        add(g_bnd, "Boundary around selected topics (key B)", v.bnd_toggle)
        self.fill_btn = add(g_fillnodes(lambda: v.fill_on), "Fill topic boxes on / off (root + 2nd level)", self.toggle_fill)
        self.fill_btn.setFixedSize(44, 34)  # wider than the other buttons so the switch has room
        sep()
        self.bg_btn = add(g_bgcolor(lambda: v.bg_color), "Background colour", self.pick_bg_color)
        self.fillc_btn = add(g_fillcolor(lambda: v.fill_color), "Topic box fill colour (2nd level)", self.pick_fill_color)
        self.line_btn = add(g_linecolor(lambda: v.line_color), "Line colour (all mindmap lines)", self.pick_line_color)
        self.bnd_btn = add(g_bndcolor(lambda: v.bnd_color), "Boundary colour (selected boundary, or new ones)", self.pick_bnd_color)
        for i, (name, h) in enumerate(COLORS):
            add(g_swatch(h), f"{name} {h} (key {i + 1})", lambda h=h: v.set_color(h))
        add(g_clear, "Clear colour (key 0)", lambda: v.set_color(None))
        sep()
        add(g_icon("check"), "Done icon (key C)", lambda: v.toggle_icon("check"))
        add(g_icon("error"), "Error icon (key X)", lambda: v.toggle_icon("error"))
        add(g_x, "Remove icon (key Q)", v.clear_icon)
        #add(g_note, "Note on selected topic (key N)", v.toggle_note)
        sep()
        self.style_btn = add(g_style, "Layout, shape and branch lines", self.show_style_menu)
        add(g_font, "Font", self.pick_font)

        self.menu = QMenu(self)
        self.menu.setStyleSheet("QMenu{font-size:18px;} QMenu::item{padding:8px 28px 8px 20px;}")  # menu text size
        self.acts = {}
        for title, items, attr in (("Layout", ["Map", "Logic chart", "Progress chart"], "layout_mode"),
                                   ("Topic shape", SHAPES, "shape"), ("Branch lines", LINES, "line"),
                                   ("Child branch lines", CHILD_LINES, "child_line"),
                                   ("Child lines", CHILD_TYPES, "child_type")):
            sub = self.menu.addMenu(title)
            grp = QActionGroup(sub)
            grp.setExclusive(True)
            self.acts[attr] = {}
            for it in items:
                a = sub.addAction(it)
                a.setCheckable(True)
                grp.addAction(a)
                a.triggered.connect(lambda _c=False, it=it, attr=attr: self.set_style(attr, it))
                self.acts[attr][it] = a

        tm = self.menu.addMenu("Themes")  # ready-made colour sets: background, topic fills, lines
        for th in THEMES:
            wa = QWidgetAction(tm)
            wa.setDefaultWidget(ThemeItem(th, lambda th=th: self.theme_active(th), self.apply_theme))
            tm.addAction(wa)
        self.themes_menu = tm

        rail.adjustSize()
        v.rail = rail
        rail.move((v.width() - rail.width()) // 2, 14)
        self.sync_controls()
        d = Doc()
        v.capture(d)  # the first tab holds the starting map already on the canvas
        d.untitled = self.next_untitled()
        self.tabs.blockSignals(True)
        self.add_tab(d)
        self.tabs.blockSignals(False)
        self.cur = d.id
        self.update_title()

    def toggle_fill(self):  # fill the boxes of the main topics (children of the root) on / off; saved with the file
        v = self.view
        v.fill_on = not v.fill_on
        v.set_dirty(True)
        self.fill_btn.update()
        v.update()
        v.setFocus()

    def pick_bg_color(self):  # canvas background colour of the current mindmap; saved with the file
        v = self.view
        c = QColorDialog.getColor(QColor(v.bg_color), self, "Background colour")
        if c.isValid() and c.name() != QColor(v.bg_color).name():
            v.bg_color = c.name()
            v.set_dirty(True)
            v.update()
        self.bg_btn.update()
        v.setFocus()

    def pick_fill_color(self):  # fill colour of the 2nd level topic boxes; saved with the file
        v = self.view
        c = QColorDialog.getColor(QColor(v.fill_color), self, "Topic box fill colour")
        if c.isValid() and c.name() != QColor(v.fill_color).name():
            v.fill_color = c.name()
            v.set_dirty(True)
            v.update()
        self.fillc_btn.update()
        v.setFocus()

    def pick_root_fill_color(self):  # fill colour of the root topic box (right-click the root); saved with the file
        v = self.view
        c = QColorDialog.getColor(QColor(v.root_fill_color), self, "Root topic fill colour")
        if c.isValid() and c.name() != QColor(v.root_fill_color).name():
            v.root_fill_color = c.name()
            v.set_dirty(True)
            v.update()
        v.setFocus()

    def pick_line_color(self):  # one colour for every line of the current mindmap; saved with the file
        v = self.view
        c = QColorDialog.getColor(QColor(v.line_color), self, "Line colour")
        if c.isValid() and c.name() != QColor(v.line_color).name():
            v.line_color = c.name()
            v.set_dirty(True)
            v.update()
        self.line_btn.update()
        v.setFocus()

    def pick_bnd_color(self):  # colour of the selected boundary, or of the boundaries made from now on
        v = self.view
        b = v.sel_bnd
        c = QColorDialog.getColor(QColor(b.color if b else v.bnd_color), self, "Boundary colour")
        if c.isValid():
            if b is not None:
                if c.name() != QColor(b.color).name():
                    v.push_undo()
                    b.color = c.name()
            v.bnd_color = c.name()  # also the colour of new boundaries + the top-bar swatch
            QSettings("xmap", "xmap").setValue("bnd_color", v.bnd_color)
        self.bnd_btn.update()
        v.update()
        v.setFocus()

    def theme_active(self, th):  # does the current map use exactly this theme?
        v = self.view
        _n, bg, root, fill, line, on = th
        same = lambda a, b: QColor(a).name() == QColor(b).name()
        if not on:
            return not v.fill_on and same(v.bg_color, bg) and same(v.line_color, line)
        return (v.fill_on and same(v.bg_color, bg) and same(v.root_fill_color, root)
                and same(v.fill_color, fill) and same(v.line_color, line))

    def apply_theme(self, th):  # sets the colours of the current map only; saved with the file like any colour pick
        v = self.view
        _n, v.bg_color, v.root_fill_color, v.fill_color, v.line_color, v.fill_on = th
        self.themes_menu.close()
        self.menu.close()
        v.set_dirty(True)
        self.sync_controls()
        v.update()
        v.setFocus()

    def pick_font(self):  # choose any installed font for all topics; remembered between runs
        dlg = QDialog(self)
        dlg.setWindowTitle("Font")
        dlg.setMinimumWidth(340)
        lay = QVBoxLayout(dlg)
        lay.addWidget(QLabel("Font for topics"))
        combo = QFontComboBox()
        combo.setCurrentFont(QFont(FAMILIES[0]))
        lay.addWidget(combo)
        B = QDialogButtonBox.StandardButton
        bb = QDialogButtonBox(B.Ok | B.Cancel | B.RestoreDefaults)
        lay.addWidget(bb)
        reset = []

        def on_click(b):
            if bb.buttonRole(b) == QDialogButtonBox.ButtonRole.ResetRole:
                reset.append(1)
                dlg.accept()

        bb.accepted.connect(dlg.accept)
        bb.rejected.connect(dlg.reject)
        bb.clicked.connect(on_click)
        if not dlg.exec():
            self.view.setFocus()
            return
        fam = None if reset else combo.currentFont().family()
        use_family(fam)
        QSettings("xmap", "xmap").setValue("font", fam or "")
        self.view.refont()
        self.view.setFocus()

    def show_style_menu(self):
        b = self.style_btn
        self.menu.exec(b.mapToGlobal(QPoint(0, b.height() + 8)))

    def set_style(self, attr, val):
        v = self.view
        if getattr(v, attr) == val:
            return
        setattr(v, attr, val)
        v.set_dirty(True)
        if attr == "layout_mode":
            v.relayout()
            v.fit_now()
        elif attr in ("child_line", "child_type"):  # the gap to the children changes with the style
            v.relayout()
        else:
            v.update()

    def update_title(self):
        d = self.docs.get(self.cur)
        if d is None:
            self.setWindowTitle("xmap")
            return
        v = self.view
        label = f"{d.name(v.path)}{' *' if v.dirty else ''}"
        self.setWindowTitle(f"{label} - xmap")
        i = self.tab_index(self.cur)
        if i >= 0:
            self.tabs.setTabText(i, label)
            self.tabs.setTabToolTip(i, v.path or d.name(v.path))

    def sync_controls(self):
        v = self.view
        if hasattr(self, "line_btn"):
            self.line_btn.update()
        for n in ("bg_btn", "fillc_btn", "fill_btn"):
            if hasattr(self, n):
                getattr(self, n).update()
        for attr, acts in self.acts.items():
            acts[getattr(v, attr)].setChecked(True)

    # ---------- tabs ----------
    def next_untitled(self):
        self._untitled += 1
        return self._untitled

    def tab_index(self, id):
        for i in range(self.tabs.count()):
            if self.tabs.tabData(i) == id:
                return i
        return -1

    def add_tab(self, d):
        d.id = self._next_id
        self._next_id += 1
        self.docs[d.id] = d
        prev = self.tabs.blockSignals(True)  # the tab's id isn't attached yet
        i = self.tabs.addTab(d.name())
        self.tabs.setTabData(i, d.id)
        self.tabs.blockSignals(prev)
        b = CloseBtn()
        b.clicked.connect(lambda _=False, id=d.id: self.close_id(id))
        self.tabs.setTabButton(i, QTabBar.ButtonPosition.RightSide, b)
        self.tabs.setTabToolTip(i, d.name())
        return i

    def snapshot(self):  # copy the live canvas state back into the current tab's document
        d = self.docs.get(self.cur)
        if d:
            self.view.commit_edit()
            self.view.capture(d)

    def on_tab_changed(self, i):
        if i < 0:
            return
        id = self.tabs.tabData(i)
        if id == self.cur or id not in self.docs:
            return
        self.snapshot()
        self.cur = id
        self.view.apply(self.docs[id])
        self.view.setFocus()

    def show_doc(self, d):
        i = self.add_tab(d)
        self.tabs.setCurrentIndex(i)
        self.on_tab_changed(i)  # also covers the case where the bar was empty
        self.save_session()

    # ---------- remember open files between runs ----------
    _restoring = False

    def save_session(self):
        if self._restoring:
            return
        files, cur = [], None
        for i in range(self.tabs.count()):
            id = self.tabs.tabData(i)
            d = self.docs.get(id)
            if d is None:
                continue
            path = self.view.path if id == self.cur else d.path  # live canvas holds the current tab's path
            if path:
                files.append(os.path.abspath(path))
                if id == self.cur:
                    cur = files[-1]
        QSettings("xmap", "xmap").setValue("session", json.dumps({"files": files, "current": cur}))

    def restore_session(self):
        try:
            data = json.loads(QSettings("xmap", "xmap").value("session", "") or "{}")
            files, cur = data.get("files", []), data.get("current")
        except (ValueError, AttributeError):
            return
        self._restoring = True
        try:
            for p in files:
                if os.path.isfile(p):  # files that were moved/deleted are skipped silently
                    self.open_path(p)
            if cur and os.path.isfile(cur):
                self.open_path(cur)  # already open -> just switches to that tab
        finally:
            self._restoring = False
        self.save_session()

    def next_tab(self, step):
        n = self.tabs.count()
        if n > 1:
            self.tabs.setCurrentIndex((self.tabs.currentIndex() + step) % n)

    def close_current(self):
        self.close_id(self.cur)

    def close_id(self, id):
        if id == self.cur:
            self.snapshot()
        d = self.docs.get(id)
        if d is None:
            return
        if d.dirty:
            B = QMessageBox.StandardButton
            r = QMessageBox.question(self, "xmap", f'Discard unsaved changes in "{d.name()}"?',
                                     B.Discard | B.Cancel, B.Cancel)
            if r != B.Discard:
                return
        i = self.tab_index(id)
        if id == self.cur:
            self.cur = None
        del self.docs[id]
        self.tabs.removeTab(i)
        if self.tabs.count() == 0:
            self.new()
        self.view.setFocus()
        self.save_session()

    def closeEvent(self, e):
        self.snapshot()
        n = sum(1 for d in self.docs.values() if d.dirty)
        if n:
            B = QMessageBox.StandardButton
            msg = f"{n} tab{'s have' if n > 1 else ' has'} unsaved changes. Discard?"
            if QMessageBox.question(self, "xmap", msg, B.Discard | B.Cancel, B.Cancel) != B.Discard:
                e.ignore()
                return
        self.save_session()
        e.accept()

    def new(self):
        d = Doc()
        d.untitled = self.next_untitled()
        self.show_doc(d)

    def open(self):
        ps, _ = QFileDialog.getOpenFileNames(self, "Open", "", "Mind maps (*.json);;All files (*)")
        for p in ps:
            self.open_path(p)

    def open_path(self, p):
        p = os.path.abspath(p)
        self.snapshot()
        for d in self.docs.values():  # already open: just switch to it
            if d.path and os.path.abspath(d.path) == p:
                self.tabs.setCurrentIndex(self.tab_index(d.id))
                return
        try:
            with open(p, encoding="utf-8") as f:
                data = json.load(f)
            root = Node.from_dict(data["root"])
        except (OSError, ValueError, KeyError, AttributeError, TypeError, IndexError, RecursionError) as ex:
            if not self._restoring:  # a bad file in the remembered session is skipped silently
                QMessageBox.warning(self, "xmap", f"Couldn't open that file.\n{ex}")
            return
        cur = self.docs.get(self.cur)
        if cur and not cur.path and not cur.dirty and not cur.undo:  # reuse an untouched Untitled tab
            self.view.load(data, p)
            return
        doc = Doc(root, data.get("layout", "Map"), data.get("shape", "Square"),
                  data.get("line", "Straight"), p, data.get("line_color", DEFAULT_LINE),
                  data.get("child_line", "Straight"), data.get("child_type", "Normal"),
                  data.get("bg_color", DEFAULT_BG), data.get("fill_on", False), data.get("fill_color", DEFAULT_FILL),
                  data.get("root_fill_color", DEFAULT_ROOT_FILL))
        doc.rels = parse_rels(data.get("rels"), root)
        doc.bnds = parse_bnds(data.get("bnds"), root)
        self.show_doc(doc)

    def save(self):
        if self.view.path:
            try:
                self.view.write(self.view.path)
            except OSError as ex:
                QMessageBox.warning(self, "xmap", f"Couldn't save the file.\n{ex}")
        else:
            self.save_as()

    def save_as(self):
        p, _ = QFileDialog.getSaveFileName(self, "Save", "mindmap.json", "Mind maps (*.json);;All files (*)")
        if p:
            try:
                self.view.write(p)
                self.save_session()
            except OSError as ex:
                QMessageBox.warning(self, "xmap", f"Couldn't save the file.\n{ex}")

    def export(self):
        p, _ = QFileDialog.getSaveFileName(self, "Export", "mindmap.png", "PNG (*.png);;SVG (*.svg);;PDF (*.pdf)")
        if p:
            try:
                self.view.export(p if "." in os.path.basename(p) else p + ".png")
            except OSError as ex:
                QMessageBox.warning(self, "xmap", f"Couldn't export the file.\n{ex}")


def dark_palette():
    pal = QPalette()
    C, R = QColor, QPalette.ColorRole
    for role, col in ((R.Window, "#1c1c1f"), (R.WindowText, "#e8e8ea"), (R.Base, "#141416"),
                      (R.AlternateBase, "#1c1c1f"), (R.Text, "#e8e8ea"), (R.Button, "#2a2a2e"),
                      (R.ButtonText, "#e8e8ea"), (R.Highlight, "#3a6ea5"), (R.HighlightedText, "#ffffff"),
                      (R.ToolTipBase, "#2a2a2e"), (R.ToolTipText, "#e8e8ea"), (R.PlaceholderText, "#8a8a90")):
        pal.setColor(role, C(col))
    return pal


def main():
    app = QApplication(sys.argv)
    app.setStyle("Fusion")
    app.setPalette(dark_palette())
    fam = str(QSettings("xmap", "xmap").value("font", "") or "")
    if fam:
        use_family(fam)
    w = Win()
    if fam:
        w.view.refont()  # also gives the edit box the saved font
    w.restore_session()  # reopen the files that were open last time
    for a in sys.argv[1:]:
        if os.path.isfile(a):
            w.open_path(a)
    w.show()
    w.view.setFocus()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()

