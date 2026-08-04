#!/usr/bin/env python3
"""Generate in662_howto_overview.png: a concise overview of the tdc-runner workflow."""

from pathlib import Path

from PIL import Image, ImageDraw, ImageFont


SCALE = 2
LOGICAL_WIDTH = 1200
LOGICAL_HEIGHT = 880
OUTPUT = Path(__file__).with_name("in662_howto_overview.png")

ARIAL = "/System/Library/Fonts/Supplemental/Arial.ttf"
ARIAL_BOLD = "/System/Library/Fonts/Supplemental/Arial Bold.ttf"
COURIER = "/System/Library/Fonts/Supplemental/Courier New.ttf"

COLORS = {
    "white": "#FFFFFF",
    "ink": "#172235",
    "muted": "#5D687A",
    "line": "#D9E1EB",
    "soft_line": "#E8EDF3",
    "green": "#087A68",
    "green_dark": "#075E52",
    "green_bg": "#F1FAF7",
    "green_soft": "#E2F5EF",
    "blue": "#2B64C8",
    "blue_dark": "#204D9D",
    "blue_bg": "#F2F6FD",
    "blue_soft": "#E5EDFC",
    "purple": "#6C4BB8",
    "purple_bg": "#F4F0FC",
    "amber": "#A15C00",
    "amber_bg": "#FFF5D9",
    "amber_soft": "#FFE9B0",
    "red": "#A23A35",
    "red_bg": "#FBECEA",
    "gray_bg": "#F5F7FA",
}


def s(value):
    """Scale a logical coordinate to the final 2x canvas."""
    return int(round(value * SCALE))


def box(x, y, width, height):
    return (s(x), s(y), s(x + width), s(y + height))


image = Image.new(
    "RGB", (LOGICAL_WIDTH * SCALE, LOGICAL_HEIGHT * SCALE), COLORS["white"]
)
draw = ImageDraw.Draw(image)
_font_cache = {}


def font(size, *, bold=False, mono=False):
    key = (size, bold, mono)
    if key not in _font_cache:
        path = COURIER if mono else (ARIAL_BOLD if bold else ARIAL)
        _font_cache[key] = ImageFont.truetype(path, s(size))
    return _font_cache[key]


def text_width(value, text_font):
    return draw.textlength(value, font=text_font) / SCALE


def write(x, y, value, text_font, fill=None, *, anchor=None):
    draw.text(
        (s(x), s(y)),
        value,
        font=text_font,
        fill=fill or COLORS["ink"],
        anchor=anchor,
    )


def wrap_lines(value, text_font, max_width):
    """Wrap text by measured pixel width while preserving explicit newlines."""
    result = []
    for paragraph in value.split("\n"):
        if not paragraph:
            result.append("")
            continue
        words = paragraph.split()
        line = words[0]
        for word in words[1:]:
            candidate = f"{line} {word}"
            if text_width(candidate, text_font) <= max_width:
                line = candidate
            else:
                result.append(line)
                line = word
        result.append(line)
    return result


def write_wrapped(
    x,
    y,
    value,
    text_font,
    fill,
    max_width,
    *,
    line_height=15,
    max_lines=None,
):
    lines = wrap_lines(value, text_font, max_width)
    if max_lines is not None:
        lines = lines[:max_lines]
    for index, line in enumerate(lines):
        write(x, y + index * line_height, line, text_font, fill)
    return y + len(lines) * line_height


def rounded_rect(x, y, width, height, radius, fill, outline=None, stroke=1):
    draw.rounded_rectangle(
        box(x, y, width, height),
        radius=s(radius),
        fill=fill,
        outline=outline,
        width=s(stroke) if outline else 1,
    )


def pill(x, y, label, *, fill, color, outline=None, fixed_width=None, height=24):
    label_font = font(10, bold=True)
    width = fixed_width or (text_width(label, label_font) + 20)
    rounded_rect(x, y, width, height, height / 2, fill, outline, 1)
    write(x + width / 2, y + height / 2 + 0.5, label, label_font, color, anchor="mm")
    return width


def circle_number(x, y, number, color, diameter=26):
    draw.ellipse(box(x, y, diameter, diameter), fill=color)
    write(
        x + diameter / 2,
        y + diameter / 2 + 0.5,
        str(number),
        font(11, bold=True),
        COLORS["white"],
        anchor="mm",
    )


def horizontal_arrow(x1, x2, y, color, *, width=2, head=6):
    draw.line((s(x1), s(y), s(x2 - head), s(y)), fill=color, width=s(width))
    draw.polygon(
        [(s(x2), s(y)), (s(x2 - head), s(y - head / 1.5)), (s(x2 - head), s(y + head / 1.5))],
        fill=color,
    )


def vertical_arrow(x, y1, y2, color, *, width=2, head=7):
    draw.line((s(x), s(y1), s(x), s(y2 - head)), fill=color, width=s(width))
    draw.polygon(
        [(s(x), s(y2)), (s(x - head / 1.5), s(y2 - head)), (s(x + head / 1.5), s(y2 - head))],
        fill=color,
    )


def section_heading(x, y, label, color, note=None, note_x=None):
    write(x, y, label, font(12, bold=True), color)
    if note:
        write(note_x, y, note, font(10), COLORS["muted"])


def card_base(x, y, width, height, accent, number, title):
    rounded_rect(x + 1, y + 2, width, height, 11, COLORS["soft_line"])
    rounded_rect(x, y, width, height, 11, COLORS["white"], COLORS["line"], 1)
    circle_number(x + 14, y + 12, number, accent)
    write(x + 50, y + 14, title, font(14, bold=True), COLORS["ink"])


# Header
write(40, 28, "Интеграционные тесты после коммита", font(31, bold=True), COLORS["ink"])
pill(
    931,
    32,
    "КОД ТЕСТОВ МЕНЯТЬ НЕ НУЖНО",
    fill=COLORS["green_soft"],
    color=COLORS["green_dark"],
    fixed_width=229,
    height=28,
)
write(
    40,
    72,
    "Вы описываете окружение один раз — tdc-runner проверяет его, запускает тесты, сохраняет результат и убирает всё сам.",
    font(16),
    COLORS["muted"],
)

chip_x = 40
for chip, chip_width in (("C++ / .NET", 96), ("Linux x64", 92), ("post_commit", 105)):
    pill(
        chip_x,
        105,
        chip,
        fill=COLORS["gray_bg"],
        color=COLORS["muted"],
        outline=COLORS["line"],
        fixed_width=chip_width,
        height=24,
    )
    chip_x += chip_width + 10
write(
    1160,
    109,
    "Один профиль = один набор тестов; наборов может быть несколько",
    font(10),
    COLORS["muted"],
    anchor="ra",
)


# Lane 1: developer actions
rounded_rect(32, 142, 1136, 207, 16, COLORS["green_bg"], COLORS["green_soft"], 1)
section_heading(
    48,
    153,
    "1  ·  РАЗРАБОТЧИК — ОДИН РАЗ",
    COLORS["green_dark"],
    "Три файла живут в репозитории компонента",
    812,
)

dev_y = 181
dev_h = 152
dev_w = 256
dev_xs = [48, 320, 592, 864]

card_base(dev_xs[0], dev_y, dev_w, dev_h, COLORS["green"], 1, "Скопируйте шаблон")
write(dev_xs[0] + 14, dev_y + 52, "Выберите C++ или .NET.", font(11), COLORS["ink"])
write_wrapped(
    dev_xs[0] + 14,
    dev_y + 72,
    "Нужен готовый образ тестов из ProGet — обязательно с конкретным тегом.",
    font(11),
    COLORS["muted"],
    dev_w - 28,
    line_height=15,
)
pill(
    dev_xs[0] + 14,
    dev_y + 121,
    "RUNNER ОБРАЗ НЕ СОБИРАЕТ",
    fill=COLORS["amber_bg"],
    color=COLORS["amber"],
    fixed_width=187,
    height=20,
)

card_base(dev_xs[1], dev_y, dev_w, dev_h, COLORS["green"], 2, "Опишите набор")
write(dev_xs[1] + 14, dev_y + 50, "test_docker_config/post_commit/", font(9, mono=True), COLORS["green_dark"])
write(dev_xs[1] + 14, dev_y + 63, "<набор>/", font(9, mono=True), COLORS["green_dark"])
file_rows = [
    ("docker-compose.yml", "сервисы, образ, command"),
    (".env.default", "параметры без паролей"),
    ("test_cfg.xml", "входы, отчёты, таймаут"),
]
for row_index, (filename, description) in enumerate(file_rows):
    row_y = dev_y + 82 + row_index * 20
    draw.ellipse(box(dev_xs[1] + 14, row_y + 4, 5, 5), fill=COLORS["green"])
    write(dev_xs[1] + 25, row_y, filename, font(9, mono=True), COLORS["ink"])
    write(dev_xs[1] + 130, row_y, description, font(9), COLORS["muted"])

card_base(dev_xs[2], dev_y, dev_w, dev_h, COLORS["green"], 3, "Проверьте локально")
write(dev_xs[2] + 14, dev_y + 51, "Команды — из каталога tdc-runner:", font(9), COLORS["muted"])
rounded_rect(dev_xs[2] + 14, dev_y + 69, dev_w - 28, 24, 5, COLORS["gray_bg"])
write(dev_xs[2] + 21, dev_y + 75, "python3 -m tdc validate --repo …", font(9, mono=True), COLORS["ink"])
rounded_rect(dev_xs[2] + 14, dev_y + 98, dev_w - 28, 24, 5, COLORS["gray_bg"])
write(dev_xs[2] + 21, dev_y + 104, "./run_local.sh <набор> --repo …", font(9, mono=True), COLORS["ink"])
write(dev_xs[2] + 14, dev_y + 130, "validate не поднимает контейнеры", font(9), COLORS["green_dark"])

card_base(dev_xs[3], dev_y, dev_w, dev_h, COLORS["green"], 4, "Закоммитьте профиль")
write_wrapped(
    dev_xs[3] + 14,
    dev_y + 52,
    "Коммитятся эти 3 файла. После коммита профиль подхватит TeamCity.",
    font(11),
    COLORS["ink"],
    dev_w - 28,
    line_height=16,
)
write_wrapped(
    dev_xs[3] + 14,
    dev_y + 101,
    "Дальше ручных шагов в прогоне нет.",
    font(10),
    COLORS["muted"],
    dev_w - 28,
    line_height=14,
)
pill(
    dev_xs[3] + 14,
    dev_y + 121,
    "COMMIT  →  TEAMCITY",
    fill=COLORS["green_soft"],
    color=COLORS["green_dark"],
    fixed_width=156,
    height=20,
)

for left_x in (dev_xs[0], dev_xs[1], dev_xs[2]):
    horizontal_arrow(left_x + dev_w + 3, left_x + dev_w + 13, dev_y + 76, COLORS["green"], width=2, head=5)


# Handoff between the human lane and the automated lane.
vertical_arrow(600, 349, 385, COLORS["green"], width=2, head=7)
pill(
    535,
    355,
    "ПОСЛЕ КОММИТА",
    fill=COLORS["white"],
    color=COLORS["green_dark"],
    outline=COLORS["green_soft"],
    fixed_width=130,
    height=22,
)


# Lane 2: tdc-runner automation
rounded_rect(32, 383, 1136, 267, 16, COLORS["blue_bg"], COLORS["blue_soft"], 1)
section_heading(
    48,
    394,
    "2  ·  TDC-RUNNER — АВТОМАТИЧЕСКИ КАЖДЫЙ ПРОГОН",
    COLORS["blue_dark"],
    "Одинаково для C++ и .NET",
    978,
)

auto_y = 422
auto_h = 210
auto_w = 203
auto_xs = [48, 265, 482, 699, 916]

card_base(auto_xs[0], auto_y, auto_w, auto_h, COLORS["blue"], 1, "Проверяет профиль")
pill(
    auto_xs[0] + 14,
    auto_y + 49,
    "ДО ЗАПУСКА КОНТЕЙНЕРОВ",
    fill=COLORS["blue_soft"],
    color=COLORS["blue_dark"],
    fixed_width=175,
    height=20,
)
check_rows = ["test_cfg.xml", "имена переменных", "docker compose config"]
for row_index, label in enumerate(check_rows):
    row_y = auto_y + 81 + row_index * 22
    draw.ellipse(box(auto_xs[0] + 15, row_y + 3, 6, 6), fill=COLORS["blue"])
    write(auto_xs[0] + 28, row_y, label, font(10, mono=row_index != 1), COLORS["ink"])
write_wrapped(
    auto_xs[0] + 14,
    auto_y + 153,
    "Белый список отклоняет опасные настройки.",
    font(10),
    COLORS["muted"],
    auto_w - 28,
    line_height=14,
)

card_base(auto_xs[1], auto_y, auto_w, auto_h, COLORS["blue"], 2, "Готовит изоляцию")
mount_rows = [
    ("/test/input", "входы · только чтение"),
    ("/test/secrets", "секреты файлами · только чтение"),
    ("/test/output", "сюда писать отчёты"),
]
for row_index, (path, description) in enumerate(mount_rows):
    row_y = auto_y + 51 + row_index * 43
    fill = COLORS["amber_bg"] if path == "/test/output" else COLORS["gray_bg"]
    rounded_rect(auto_xs[1] + 14, row_y, auto_w - 28, 36, 6, fill)
    write(auto_xs[1] + 22, row_y + 5, path, font(9, mono=True), COLORS["ink"])
    write(auto_xs[1] + 22, row_y + 19, description, font(8), COLORS["muted"])
write(auto_xs[1] + 14, auto_y + 185, "Накладывает защитный слой", font(9), COLORS["blue_dark"])

card_base(auto_xs[2], auto_y, auto_w, auto_h, COLORS["blue"], 3, "Поднимает сервисы")
write_wrapped(
    auto_xs[2] + 14,
    auto_y + 51,
    "Берёт готовые образы из ProGet и запускает compose.",
    font(10),
    COLORS["ink"],
    auto_w - 28,
    line_height=15,
)
rounded_rect(auto_xs[2] + 14, auto_y + 105, auto_w - 28, 52, 7, COLORS["blue_soft"])
write(auto_xs[2] + auto_w / 2, auto_y + 119, "ЖДЁТ HEALTHCHECK", font(10, bold=True), COLORS["blue_dark"], anchor="ma")
write(auto_xs[2] + auto_w / 2, auto_y + 139, "не просто «контейнер started»", font(8), COLORS["muted"], anchor="ma")
write_wrapped(
    auto_xs[2] + 14,
    auto_y + 170,
    "Зависимые сервисы успевают стать готовыми.",
    font(9),
    COLORS["muted"],
    auto_w - 28,
    line_height=13,
)

card_base(auto_xs[3], auto_y, auto_w, auto_h, COLORS["blue"], 4, "Запускает тесты")
write_wrapped(
    auto_xs[3] + 14,
    auto_y + 51,
    "В контейнере выполняется ваша command.",
    font(10),
    COLORS["ink"],
    auto_w - 28,
    line_height=15,
)
rounded_rect(auto_xs[3] + 14, auto_y + 94, 68, 32, 6, COLORS["blue_soft"], COLORS["blue_soft"], 1)
rounded_rect(auto_xs[3] + 119, auto_y + 94, 70, 32, 6, COLORS["green_soft"], COLORS["green_soft"], 1)
write(auto_xs[3] + 48, auto_y + 110, "tests", font(9, mono=True), COLORS["blue_dark"], anchor="mm")
write(auto_xs[3] + 154, auto_y + 110, "postgres", font(9, mono=True), COLORS["green_dark"], anchor="mm")
horizontal_arrow(auto_xs[3] + 85, auto_xs[3] + 116, auto_y + 110, COLORS["blue"], width=2, head=6)
write(auto_xs[3] + 14, auto_y + 139, "По имени из compose", font(10, bold=True), COLORS["blue_dark"])
pill(
    auto_xs[3] + 14,
    auto_y + 162,
    "НЕ LOCALHOST",
    fill=COLORS["red_bg"],
    color=COLORS["red"],
    fixed_width=112,
    height=20,
)

card_base(auto_xs[4], auto_y, auto_w, auto_h, COLORS["blue"], 5, "Собирает и убирает")
pill(
    auto_xs[4] + 14,
    auto_y + 49,
    "ВСЕГДА — ДАЖЕ ПРИ ПАДЕНИИ",
    fill=COLORS["amber_bg"],
    color=COLORS["amber"],
    fixed_width=175,
    height=20,
)
write(auto_xs[4] + 14, auto_y + 81, "СНАЧАЛА", font(9, bold=True), COLORS["blue_dark"])
write_wrapped(
    auto_xs[4] + 14,
    auto_y + 98,
    "Отчёты, покрытие, состояние и логи контейнеров.",
    font(10),
    COLORS["ink"],
    auto_w - 28,
    line_height=14,
)
draw.line(
    (s(auto_xs[4] + 14), s(auto_y + 140), s(auto_xs[4] + auto_w - 14), s(auto_y + 140)),
    fill=COLORS["line"],
    width=s(1),
)
write(auto_xs[4] + 14, auto_y + 150, "ПОТОМ", font(9, bold=True), COLORS["green_dark"])
write_wrapped(
    auto_xs[4] + 14,
    auto_y + 167,
    "down -v, остатки по метке и временные секреты.",
    font(9),
    COLORS["muted"],
    auto_w - 28,
    line_height=13,
)

for left_x in auto_xs[:-1]:
    horizontal_arrow(left_x + auto_w + 3, left_x + auto_w + 13, auto_y + 105, COLORS["blue"], width=2, head=5)


# Output and the two rules that most often determine whether the run succeeds.
vertical_arrow(600, 650, 682, COLORS["purple"], width=2, head=7)

rounded_rect(32, 679, 730, 150, 14, COLORS["purple_bg"], "#E5DCF7", 1)
write(48, 692, "РЕЗУЛЬТАТ ДЛЯ РАЗРАБОТЧИКА", font(12, bold=True), COLORS["purple"])
write(48, 713, "reports/<набор>/", font(14, mono=True), COLORS["ink"])

result_boxes = [
    (48, 218, "tests/", "TRX / JUnit"),
    (274, 218, "coverage/", "Cobertura"),
    (500, 246, "_infra/", "логи и состояние"),
]
for result_x, result_w, folder, description in result_boxes:
    rounded_rect(result_x, 739, result_w, 43, 7, COLORS["white"], "#E5DCF7", 1)
    write(result_x + 12, 746, folder, font(10, mono=True), COLORS["purple"])
    write(result_x + 12, 763, description, font(9), COLORS["muted"])

write(48, 791, "При сбое сначала смотрите:", font(9, bold=True), COLORS["ink"])
write(174, 791, "_infra/compose-logs.txt", font(9, mono=True), COLORS["red"])
write(48, 809, "Код возврата + публикация отчётов в TeamCity", font(9), COLORS["muted"])

rounded_rect(778, 679, 390, 150, 14, COLORS["amber_bg"], COLORS["amber_soft"], 1)
write(794, 692, "ДВА ПРАВИЛА, КОТОРЫЕ НЕЛЬЗЯ ПРОПУСТИТЬ", font(12, bold=True), COLORS["amber"])

circle_number(794, 721, 1, COLORS["amber"], diameter=24)
write(829, 720, "Отчёты пишите только в", font(11), COLORS["ink"])
write(829, 738, "/test/output", font(11, mono=True), COLORS["red"])
write(935, 738, "— иначе они исчезнут.", font(10), COLORS["muted"])

circle_number(794, 770, 2, COLORS["amber"], diameter=24)
write(829, 769, "К сервисам — по имени compose:", font(11), COLORS["ink"])
write(829, 787, "postgres", font(11, mono=True), COLORS["green_dark"])
write(890, 787, ", не", font(10), COLORS["muted"])
write(916, 787, "localhost", font(11, mono=True), COLORS["red"])


# Scope footer
pill(
    32,
    844,
    "СЕЙЧАС: LINUX X64 · POST_COMMIT · ТЕСТЫ ВНУТРИ КОНТЕЙНЕРА",
    fill=COLORS["gray_bg"],
    color=COLORS["muted"],
    outline=COLORS["line"],
    fixed_width=497,
    height=24,
)
pill(
    543,
    844,
    "ПОКА НЕТ: WINDOWS · ТЕСТЫ САМИ СОЗДАЮТ КОНТЕЙНЕРЫ ЧЕРЕЗ DOCKER API",
    fill=COLORS["red_bg"],
    color=COLORS["red"],
    outline="#F3D1CE",
    fixed_width=625,
    height=24,
)


image.save(OUTPUT, format="PNG", optimize=True)
print(f"Created {OUTPUT.name}: {image.width}x{image.height}px")
