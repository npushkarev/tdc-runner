"""Генератор схем IN-662: одно описание -> .excalidraw (редактируемый) + .png.

Схема описывается списком боксов и стрелок в координатах сетки; рендер в PNG
делает PIL, тот же список сериализуется в формат excalidraw.
"""
import json
import random
from PIL import Image, ImageDraw, ImageFont

FONT_R = "/System/Library/Fonts/Supplemental/Arial.ttf"
FONT_B = "/System/Library/Fonts/Supplemental/Arial Bold.ttf"
FONT_M = "/System/Library/Fonts/Supplemental/Courier New.ttf"
SCALE = 2  # рендерим в 2x для чёткости

PALETTE = {
    "contract": ("#1971c2", "#d0ebff"),   # контракт разработчика
    "core":     ("#2f9e44", "#d3f9d8"),   # общее ядро
    "launch":   ("#e8590c", "#ffe8cc"),   # пускалки
    "infra":    ("#495057", "#e9ecef"),   # инфраструктура
    "warn":     ("#c92a2a", "#ffe3e3"),   # запреты и падения
    "plain":    ("#1e1e1e", "#ffffff"),
}


class Diagram:
    def __init__(self, width, height, title, subtitle=""):
        self.w, self.h = width, height
        self.title, self.subtitle = title, subtitle
        self.boxes = []
        self.arrows = []
        self.notes = []
        self.bands = []

    def band(self, x, y, w, h, label, kind="infra"):
        self.bands.append((x, y, w, h, label, kind))

    def box(self, x, y, w, h, lines, kind="plain", mono_from=99):
        """h=None — высота подгоняется под число строк."""
        if h is None:
            h = boxh(lines)
        self.boxes.append(dict(x=x, y=y, w=w, h=h, lines=lines, kind=kind,
                               mono_from=mono_from))
        return y + h

    def arrow(self, x1, y1, x2, y2, label="", kind="plain", dashed=False,
              head=True):
        self.arrows.append(dict(x1=x1, y1=y1, x2=x2, y2=y2, label=label,
                                kind=kind, dashed=dashed, head=head))

    def note(self, x, y, text, kind="plain", size=13, bold=False):
        self.notes.append(dict(x=x, y=y, text=text, kind=kind, size=size,
                               bold=bold))

    # --- PNG ---------------------------------------------------------------
    def render_png(self, path):
        s = SCALE
        img = Image.new("RGB", (self.w * s, self.h * s), "#ffffff")
        d = ImageDraw.Draw(img)
        f_title = ImageFont.truetype(FONT_B, 26 * s)
        f_sub = ImageFont.truetype(FONT_R, 15 * s)
        f_head = ImageFont.truetype(FONT_B, 15 * s)
        f_body = ImageFont.truetype(FONT_R, 13 * s)
        f_mono = ImageFont.truetype(FONT_M, 12 * s)
        f_band = ImageFont.truetype(FONT_B, 13 * s)

        d.text((40 * s, 26 * s), self.title, font=f_title, fill="#1e1e1e")
        if self.subtitle:
            d.text((40 * s, 60 * s), self.subtitle, font=f_sub, fill="#666666")

        for x, y, w, h, label, kind in self.bands:
            stroke, fill = PALETTE[kind]
            d.rounded_rectangle([x * s, y * s, (x + w) * s, (y + h) * s],
                                radius=10 * s, fill=fill, outline=stroke,
                                width=1 * s)
            if label:
                d.text(((x + 12) * s, (y + 8) * s), label, font=f_band,
                       fill=stroke)

        for b in self.boxes:
            stroke, fill = PALETTE[b["kind"]]
            x, y, w, h = b["x"], b["y"], b["w"], b["h"]
            d.rounded_rectangle([x * s, y * s, (x + w) * s, (y + h) * s],
                                radius=8 * s, fill=fill, outline=stroke,
                                width=2 * s)
            ty = y + 10
            for i, line in enumerate(b["lines"]):
                if i == 0:
                    font, fill_c = f_head, stroke
                elif i >= b["mono_from"]:
                    font, fill_c = f_mono, "#333333"
                else:
                    font, fill_c = f_body, "#333333"
                d.text(((x + 12) * s, ty * s), line, font=font, fill=fill_c)
                ty += 22 if i == 0 else 18

        for a in self.arrows:
            stroke, _ = PALETTE[a["kind"]]
            x1, y1, x2, y2 = a["x1"], a["y1"], a["x2"], a["y2"]
            if a["dashed"]:
                _dashed_line(d, x1 * s, y1 * s, x2 * s, y2 * s, stroke, 2 * s)
            else:
                d.line([x1 * s, y1 * s, x2 * s, y2 * s], fill=stroke,
                       width=2 * s)
            if a["head"]:
                _arrow_head(d, x1 * s, y1 * s, x2 * s, y2 * s, stroke, 7 * s)
            if a["label"]:
                mx, my = (x1 + x2) / 2, (y1 + y2) / 2
                tw = d.textlength(a["label"], font=f_body)
                d.rectangle([mx * s - tw / 2 - 4 * s, my * s - 10 * s,
                             mx * s + tw / 2 + 4 * s, my * s + 10 * s],
                            fill="#ffffff")
                d.text((mx * s - tw / 2, my * s - 8 * s), a["label"],
                       font=f_body, fill=stroke)

        for n in self.notes:
            stroke, _ = PALETTE[n["kind"]]
            font = ImageFont.truetype(FONT_B if n["bold"] else FONT_R,
                                      n["size"] * s)
            d.text((n["x"] * s, n["y"] * s), n["text"], font=font, fill=stroke)

        img.save(path)
        return path

    # --- excalidraw --------------------------------------------------------
    def render_excalidraw(self, path):
        rnd = random.Random(20260803)
        els = []

        def base(kind, **kw):
            stroke, fill = PALETTE[kind]
            e = dict(id="e%d" % len(els), angle=0, strokeColor=stroke,
                     backgroundColor=fill, fillStyle="solid", strokeWidth=1,
                     strokeStyle="solid", roughness=1, opacity=100,
                     groupIds=[], frameId=None, roundness={"type": 3},
                     seed=rnd.randint(1, 2 ** 31), version=1,
                     versionNonce=rnd.randint(1, 2 ** 31), isDeleted=False,
                     boundElements=None, updated=1, link=None, locked=False)
            e.update(kw)
            return e

        def text(x, y, s_, size=13, kind="plain", bold=False):
            stroke, _ = PALETTE[kind]
            els.append(base(kind, type="text", x=x, y=y,
                            width=max(10, int(len(s_) * size * 0.55)),
                            height=int(size * 1.25), text=s_, fontSize=size,
                            fontFamily=2 if not bold else 2,
                            textAlign="left", verticalAlign="top",
                            containerId=None, originalText=s_,
                            backgroundColor="transparent", strokeColor=stroke,
                            lineHeight=1.25))

        text(40, 24, self.title, size=24, bold=True)
        if self.subtitle:
            text(40, 58, self.subtitle, size=14)

        for x, y, w, h, label, kind in self.bands:
            els.append(base(kind, type="rectangle", x=x, y=y, width=w,
                            height=h, strokeStyle="dashed"))
            if label:
                text(x + 12, y + 8, label, size=13, kind=kind, bold=True)

        for b in self.boxes:
            els.append(base(b["kind"], type="rectangle", x=b["x"], y=b["y"],
                            width=b["w"], height=b["h"], strokeWidth=2))
            ty = b["y"] + 10
            for i, line in enumerate(b["lines"]):
                text(b["x"] + 12, ty, line, size=15 if i == 0 else 13,
                     kind=b["kind"] if i == 0 else "plain", bold=(i == 0))
                ty += 22 if i == 0 else 18

        for a in self.arrows:
            stroke, _ = PALETTE[a["kind"]]
            els.append(base(a["kind"], type="arrow", x=a["x1"], y=a["y1"],
                            width=a["x2"] - a["x1"], height=a["y2"] - a["y1"],
                            points=[[0, 0], [a["x2"] - a["x1"],
                                             a["y2"] - a["y1"]]],
                            backgroundColor="transparent", strokeWidth=2,
                            strokeStyle="dashed" if a["dashed"] else "solid",
                            startBinding=None, endBinding=None,
                            startArrowhead=None,
                            endArrowhead="arrow" if a["head"] else None,
                            roundness={"type": 2}))
            if a["label"]:
                text((a["x1"] + a["x2"]) / 2 - len(a["label"]) * 3,
                     (a["y1"] + a["y2"]) / 2 - 18, a["label"], size=12,
                     kind=a["kind"])

        for n in self.notes:
            text(n["x"], n["y"], n["text"], size=n["size"], kind=n["kind"],
                 bold=n["bold"])

        doc = dict(type="excalidraw", version=2, source="IN-662 diagen",
                   elements=els,
                   appState=dict(gridSize=None, viewBackgroundColor="#ffffff"),
                   files={})
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(doc, fh, ensure_ascii=False, indent=1)
        return path


def boxh(lines):
    """Высота блока: отступы + заголовок + строки."""
    return 10 + 22 + 18 * (len(lines) - 1) + 12


def _arrow_head(d, x1, y1, x2, y2, color, size):
    import math
    ang = math.atan2(y2 - y1, x2 - x1)
    for delta in (2.6, -2.6):
        d.line([x2, y2, x2 + size * math.cos(ang + delta),
                y2 + size * math.sin(ang + delta)], fill=color,
               width=max(2, size // 3))


def _dashed_line(d, x1, y1, x2, y2, color, width, dash=12, gap=8):
    import math
    total = math.hypot(x2 - x1, y2 - y1)
    if total == 0:
        return
    dx, dy = (x2 - x1) / total, (y2 - y1) / total
    pos = 0.0
    while pos < total:
        end = min(pos + dash, total)
        d.line([x1 + dx * pos, y1 + dy * pos, x1 + dx * end, y1 + dy * end],
               fill=color, width=width)
        pos = end + gap


def emit(dia, stem, outdir):
    png = dia.render_png("%s/%s.png" % (outdir, stem))
    exc = dia.render_excalidraw("%s/%s.excalidraw" % (outdir, stem))
    return png, exc
