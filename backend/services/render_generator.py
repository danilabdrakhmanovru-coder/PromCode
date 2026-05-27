from __future__ import annotations

import math
import tempfile
from pathlib import Path
from typing import Dict, Iterable, Tuple

from PIL import Image, ImageDraw, ImageFont, ImageFilter

from ..models import InvestorInput, RankedRegion, Region, RegionBrief

GENERATED_DIR = Path(tempfile.gettempdir()) / "naslediye_industrii_generated"
RENDER_DIR = GENERATED_DIR / "renders"
RENDER_DIR.mkdir(parents=True, exist_ok=True)

DIRECTIONS = [
    ("south", "Южный фасад", "главный вход, АБК и общественная зона"),
    ("north", "Северный фасад", "производственный цех, склад и инженерный блок"),
    ("west", "Западный фасад", "благоустройство, пешеходная аллея и социальные объекты"),
    ("east", "Восточный фасад", "грузовой двор, погрузка и связь с трассой"),
]

AMENITY_LABELS = {
    "alley": "аллея",
    "square": "сквер",
    "gazebo": "беседки",
    "stage": "сцена",
    "health_trail": "тропа",
    "pond": "пруд",
    "art_object": "арт-объект",
}
SPORT_LABELS = {
    "outdoor_gym": "спорт-зона",
    "stadium": "стадион",
    "pool": "бассейн",
    "gym": "спортзал",
    "hockey_rink": "хоккей",
}
ARCH_LABELS = {
    "authenticity": "региональная аутентичность",
    "techno": "техно-стиль",
    "eco": "экодизайн",
}


def _value(obj) -> str:
    return obj.value if hasattr(obj, "value") else str(obj)


def _hex_to_rgb(value: str, default: Tuple[int, int, int]) -> Tuple[int, int, int]:
    if not value:
        return default
    value = str(value).strip().replace("#", "")
    if len(value) == 3:
        value = "".join(ch * 2 for ch in value)
    if len(value) != 6:
        return default
    try:
        return tuple(int(value[i:i+2], 16) for i in (0, 2, 4))  # type: ignore[return-value]
    except ValueError:
        return default


def _mix(a: Tuple[int, int, int], b: Tuple[int, int, int], t: float) -> Tuple[int, int, int]:
    return tuple(int(a[i] * (1 - t) + b[i] * t) for i in range(3))  # type: ignore[return-value]


def _font(size: int, bold: bool = False):
    candidates = [
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf" if bold else "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSerif-Bold.ttf" if bold else "/usr/share/fonts/truetype/dejavu/DejaVuSerif.ttf",
        "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf" if bold else "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",
        "/usr/share/fonts/truetype/liberation2/LiberationSans-Bold.ttf" if bold else "/usr/share/fonts/truetype/liberation2/LiberationSans-Regular.ttf",
        "/usr/share/fonts/truetype/noto/NotoSans-Bold.ttf" if bold else "/usr/share/fonts/truetype/noto/NotoSans-Regular.ttf",
        "C:/Windows/Fonts/arialbd.ttf" if bold else "C:/Windows/Fonts/arial.ttf",
        "C:/Windows/Fonts/timesbd.ttf" if bold else "C:/Windows/Fonts/times.ttf",
    ]
    for p in candidates:
        if Path(p).exists():
            return ImageFont.truetype(p, size=size)
    # Последний fallback на Linux без установленных шрифтов. Он не поддерживает кириллицу,
    # поэтому в Dockerfile обязательно устанавливаются fonts-dejavu-core/fonts-liberation.
    return ImageFont.load_default()


def _rounded_rect(draw: ImageDraw.ImageDraw, box, radius, fill, outline=None, width=1):
    draw.rounded_rectangle(box, radius=radius, fill=fill, outline=outline, width=width)


def _poly_shadow(draw: ImageDraw.ImageDraw, poly, offset=(8, 10), fill=(0, 0, 0, 45)):
    shifted = [(x + offset[0], y + offset[1]) for x, y in poly]
    draw.polygon(shifted, fill=fill)


def _draw_isometric_block(draw: ImageDraw.ImageDraw, x: int, y: int, w: int, d: int, h: int, color: Tuple[int, int, int], accent: Tuple[int, int, int], label: str):
    # Front rectangle + top plane + side plane in a simple architectural axonometry.
    front = [(x, y), (x + w, y), (x + w, y + h), (x, y + h)]
    top = [(x, y), (x + int(d * 0.55), y - int(d * 0.35)), (x + w + int(d * 0.55), y - int(d * 0.35)), (x + w, y)]
    side = [(x + w, y), (x + w + int(d * 0.55), y - int(d * 0.35)), (x + w + int(d * 0.55), y + h - int(d * 0.35)), (x + w, y + h)]
    _poly_shadow(draw, front, offset=(10, 13), fill=(20, 25, 35, 45))
    draw.polygon(top, fill=_mix(color, (255, 255, 255), 0.36))
    draw.polygon(side, fill=_mix(color, (0, 0, 0), 0.16))
    draw.polygon(front, fill=color)
    draw.line(top + [top[0]], fill=_mix(accent, (0, 0, 0), 0.10), width=2)
    draw.line(side + [side[0]], fill=_mix(accent, (0, 0, 0), 0.10), width=2)
    draw.line(front + [front[0]], fill=_mix(accent, (0, 0, 0), 0.10), width=2)

    # Facade rhythm.
    stripe = _mix(color, accent, 0.28)
    step = max(28, w // 8)
    for sx in range(x + step, x + w - 8, step):
        draw.line((sx, y + 8, sx, y + h - 8), fill=stripe, width=2)
    # Windows / gates.
    if w > 210:
        for i in range(3):
            gx = x + 34 + i * 66
            _rounded_rect(draw, (gx, y + h - 58, gx + 40, y + h - 12), 3, fill=_mix(color, (25, 32, 45), 0.60))
    else:
        for i in range(3):
            wx = x + 18 + i * 38
            _rounded_rect(draw, (wx, y + 22, wx + 24, y + 40), 3, fill=(220, 235, 245), outline=_mix(accent, (0, 0, 0), 0.2))

    # Label
    if label:
        tw = draw.textbbox((0, 0), label, font=_font(20, True))[2]
        _rounded_rect(draw, (x, y + h + 8, x + tw + 20, y + h + 40), 10, fill=(255, 255, 255, 220))
        draw.text((x + 10, y + h + 12), label, fill=(34, 39, 54), font=_font(20, True))


def _draw_tree(draw: ImageDraw.ImageDraw, x: int, y: int, scale: float, trunk=(110, 73, 44), leaf=(70, 118, 78)):
    draw.rectangle((x - int(3*scale), y - int(18*scale), x + int(3*scale), y), fill=trunk)
    draw.ellipse((x - int(18*scale), y - int(42*scale), x + int(18*scale), y - int(8*scale)), fill=leaf)
    draw.ellipse((x - int(10*scale), y - int(55*scale), x + int(22*scale), y - int(20*scale)), fill=_mix(leaf, (255,255,255), .12))


def _draw_truck(draw: ImageDraw.ImageDraw, x: int, y: int, scale: float, accent: Tuple[int,int,int]):
    body = (x, y, x + int(110*scale), y + int(32*scale))
    cab = (x + int(78*scale), y - int(16*scale), x + int(118*scale), y + int(32*scale))
    _rounded_rect(draw, body, int(5*scale), fill=(245, 247, 250), outline=(80, 90, 100), width=2)
    _rounded_rect(draw, cab, int(5*scale), fill=_mix(accent, (255,255,255), .2), outline=(80, 90, 100), width=2)
    draw.rectangle((x + int(86*scale), y - int(10*scale), x + int(108*scale), y + int(8*scale)), fill=(210,235,245))
    for wx in [x + int(22*scale), x + int(94*scale)]:
        draw.ellipse((wx, y + int(24*scale), wx + int(18*scale), y + int(42*scale)), fill=(28, 31, 40))
        draw.ellipse((wx + int(5*scale), y + int(29*scale), wx + int(13*scale), y + int(37*scale)), fill=(210, 215, 220))


def _wrap_text(draw: ImageDraw.ImageDraw, text: str, font, max_width: int) -> Iterable[str]:
    words = str(text).split()
    line = ""
    for word in words:
        candidate = (line + " " + word).strip()
        if draw.textbbox((0, 0), candidate, font=font)[2] <= max_width:
            line = candidate
        else:
            if line:
                yield line
            line = word
    if line:
        yield line



def _fit_text(draw: ImageDraw.ImageDraw, text: str, font, max_width: int) -> str:
    """Compatibility wrapper for old concept-board code."""
    return _fit_line(draw, text, font, max_width)


def _fit_line(draw: ImageDraw.ImageDraw, text: str, font, max_width: int) -> str:
    text = str(text or "")
    if draw.textbbox((0, 0), text, font=font)[2] <= max_width:
        return text
    ell = "…"
    lo, hi = 0, len(text)
    while lo < hi:
        mid = (lo + hi + 1) // 2
        candidate = text[:mid].rstrip() + ell
        if draw.textbbox((0, 0), candidate, font=font)[2] <= max_width:
            lo = mid
        else:
            hi = mid - 1
    return text[:lo].rstrip() + ell



LAYOUTS_3D = {
    "linear": {
        "title": "Линейная схема",
        "workshop": (-24, -18), "warehouse": (36, -18), "office": (-82, 34), "checkpoint": (-110, 72), "parking": (-66, 46),
        "logistics": (74, -24), "social": (46, 40), "housing": (22, 32), "green": (0, 54)
    },
    "campus": {
        "title": "Кампусная схема",
        "workshop": (-22, -16), "warehouse": (34, -12), "office": (58, 32), "checkpoint": (112, 72), "parking": (40, 46),
        "logistics": (74, -26), "social": (-74, 38), "housing": (-92, 30), "green": (-34, 54)
    },
    "logistics": {
        "title": "Логистическая схема",
        "workshop": (-28, -22), "warehouse": (24, -20), "office": (-82, 34), "checkpoint": (-110, 72), "parking": (-64, 46),
        "logistics": (74, -16), "social": (22, 40), "housing": (48, 32), "green": (-18, 54)
    },
    "compact": {
        "title": "Компактная схема",
        "workshop": (-18, -12), "warehouse": (24, -8), "office": (50, 34), "checkpoint": (112, 72), "parking": (36, 46),
        "logistics": (74, -22), "social": (-74, 40), "housing": (-92, 32), "green": (-32, 56)
    },
}
LAYOUT_ORDER_3D = list(LAYOUTS_3D.keys())


def normalize_layout_key(layout_key: str | None, region_id: str | None = None) -> str:
    if layout_key in LAYOUTS_3D:
        return str(layout_key)
    return _layout_key_for_region(region_id or "")


def _layout_key_for_region(region_id: str) -> str:
    total = sum(ord(ch) for ch in str(region_id or ""))
    return LAYOUT_ORDER_3D[total % len(LAYOUT_ORDER_3D)]


def _rotate_for_direction(x: float, z: float, direction: str) -> tuple[float, float]:
    if direction == "south":
        return x, z
    if direction == "north":
        return -x, -z
    if direction == "east":
        return z, -x
    if direction == "west":
        return -z, x
    return x, z


def _project_iso(x: float, z: float, y: float, *, cx: float = 800, cy: float = 620, scale: float = 3.9) -> tuple[int, int]:
    sx = cx + (x - z) * scale * 1.02
    sy = cy + (x + z) * scale * 0.52 - y * scale * 0.95
    return int(sx), int(sy)


def _box_poly(center_x: float, center_z: float, width: float, depth: float, height: float, direction: str):
    corners = [
        (center_x - width / 2, center_z - depth / 2),
        (center_x + width / 2, center_z - depth / 2),
        (center_x + width / 2, center_z + depth / 2),
        (center_x - width / 2, center_z + depth / 2),
    ]
    rotated = [_rotate_for_direction(x, z, direction) for x, z in corners]
    top = [_project_iso(x, z, height) for x, z in rotated]

    south_indices = sorted(sorted(range(4), key=lambda i: rotated[i][1], reverse=True)[:2], key=lambda i: rotated[i][0])
    east_indices = sorted(sorted(range(4), key=lambda i: rotated[i][0], reverse=True)[:2], key=lambda i: rotated[i][1])
    i, j = south_indices[0], south_indices[1]
    front = [_project_iso(*rotated[k], 0) for k in [i, j]] + [_project_iso(*rotated[k], height) for k in [j, i]]
    i, j = east_indices[0], east_indices[1]
    side = [_project_iso(*rotated[k], 0) for k in [i, j]] + [_project_iso(*rotated[k], height) for k in [j, i]]
    return top, front, side, rotated


def _draw_parking(draw: ImageDraw.ImageDraw, center_x: float, center_z: float, width: float, depth: float, direction: str):
    top, _, _, rotated = _box_poly(center_x, center_z, width, depth, 0.5, direction)
    draw.polygon(top, fill=(205, 206, 208), outline=(120, 124, 130))
    rx = [x for x, _ in rotated]
    rz = [z for _, z in rotated]
    minx, maxx = min(rx), max(rx)
    minz, maxz = min(rz), max(rz)
    # stripes along the long side
    steps = 8
    for i in range(steps):
        tx = minx + (i + 0.8) * (maxx - minx) / (steps + 0.4)
        a = _project_iso(tx, maxz - 1.5, 0.8)
        b = _project_iso(tx, minz + 1.5, 0.8)
        draw.line((a[0], a[1], b[0], b[1]), fill=(245, 245, 240), width=2)


def _draw_road_poly(draw: ImageDraw.ImageDraw, poly_world, fill=(84, 87, 93), outline=(64, 66, 71)):
    pts = [_project_iso(x, z, 0.1) for x, z in poly_world]
    draw.polygon(pts, fill=fill, outline=outline)


def _draw_tree_cluster(draw: ImageDraw.ImageDraw, center_x: float, center_z: float, count: int, spread: int, direction: str, leaf):
    for i in range(count):
        ox = center_x + ((i % 4) - 1.5) * spread * 0.45 + (i // 4) * 3
        oz = center_z + ((i // 4) - 0.5) * spread * 0.55
        rx, rz = _rotate_for_direction(ox, oz, direction)
        px, py = _project_iso(rx, rz, 0)
        _draw_tree(draw, px, py - 2, 0.72 if i % 2 else 0.84, leaf=leaf)



def _scene_spec(layout: dict, ranked: RankedRegion, inp: InvestorInput):
    volume = float(inp.production_volume_kt or 500)
    workshop_w = max(54, min(74, 50 + volume * 0.032))
    workshop_d = max(26, min(34, 24 + volume * 0.012))
    warehouse_w = max(22, min(32, 22 + (ranked.areas.warehouse_m2 or 0) * 0.012))
    social_x, social_z = layout['social']
    buildings = [
        (layout['workshop'][0], layout['workshop'][1], workshop_w, workshop_d, 22, 'цех'),
        (layout['warehouse'][0], layout['warehouse'][1], warehouse_w, 18, 14, 'склад'),
        (layout['office'][0], layout['office'][1], 18, 12, 13, 'АБК'),
        (layout['checkpoint'][0], layout['checkpoint'][1], 12, 8, 7, 'КПП'),
    ]
    if inp.housing.pct > 0:
        buildings.append((layout['housing'][0], layout['housing'][1], 18, 11, 10, 'жильё'))
    if inp.kindergarten_per_100 > 0:
        buildings.append((social_x + 4, social_z - 1, 16, 10, 7, 'детсад'))
    if inp.sport_objects:
        buildings.append((social_x + 15, social_z + 6, 12, 8, 4, 'спорт-зона'))
    return {
        'roads': [((0, 62), (226, 14)), ((102, -2), (14, 136))],
        'parking': (layout['parking'][0], layout['parking'][1], 28, 14),
        'logistics': (layout['logistics'][0], layout['logistics'][1], 28, 16),
        'green': (layout['green'][0], layout['green'][1], 40, 16),
        'buildings': buildings,
    }
def _draw_header(draw: ImageDraw.ImageDraw, region: Region, direction_label: str, palette, subtext: str):
    w = 1600
    _rounded_rect(draw, (58, 46, w - 58, 146), 26, fill=(255, 255, 255, 228), outline=(228, 226, 220), width=2)
    draw.text((90, 67), direction_label, fill=(28, 34, 54), font=_font(38, True))
    meta_font = _font(24)
    meta = _fit_line(draw, f"{region.name} · {region.federal_subject}", meta_font, 600)
    draw.text((90, 112), meta, fill=(83, 90, 110), font=meta_font)
    x = w - 360
    for c in palette[:5]:
        _rounded_rect(draw, (x, 78, x + 42, 120), 13, fill=c, outline=(230, 230, 230), width=2)
        x += 52
    info_font = _font(18)
    info = _fit_line(draw, subtext, info_font, 300)
    draw.text((w - 650, 112), info, fill=(93, 99, 115), font=info_font)


def create_project_render(region: Region, ranked: RankedRegion, inp: InvestorInput, brief: RegionBrief, direction: str, output_path: Path, layout_key: str | None = None) -> Path:
    """Строит PNG-рендер на основе той же схемы, что и 3D-макет площадки."""
    output_path.parent.mkdir(parents=True, exist_ok=True)
    W, H = 1600, 900
    raw_palette = region.culture.color_palette or []
    palette = [
        _hex_to_rgb(raw_palette[0] if len(raw_palette) > 0 else "", (132, 103, 74)),
        _hex_to_rgb(raw_palette[1] if len(raw_palette) > 1 else "", (198, 160, 82)),
        _hex_to_rgb(raw_palette[2] if len(raw_palette) > 2 else "", (245, 242, 232)),
        _hex_to_rgb(raw_palette[3] if len(raw_palette) > 3 else "", (58, 96, 84)),
        _hex_to_rgb(raw_palette[4] if len(raw_palette) > 4 else "", (124, 58, 58)),
    ]
    base, accent, light, green, brick = palette

    layout_key = normalize_layout_key(layout_key, region.id)
    layout = LAYOUTS_3D[layout_key]

    sky_map = {
        "south": ((176, 205, 227), (246, 239, 217)),
        "north": ((166, 184, 205), (229, 237, 244)),
        "west": ((190, 210, 200), (244, 240, 220)),
        "east": ((170, 194, 219), (240, 235, 219)),
    }
    sky_top, sky_bot = sky_map.get(direction, ((176, 205, 227), (246, 239, 217)))
    img = Image.new("RGB", (W, H), sky_top)
    draw = ImageDraw.Draw(img, "RGBA")
    for y in range(H):
        c = _mix(sky_top, sky_bot, min(1, (y / H) * 1.28))
        draw.line((0, y, W, y), fill=c)

    sun = {"south": (1220, 115), "north": (180, 120), "west": (1260, 145), "east": (220, 135)}.get(direction, (1220, 115))
    draw.ellipse((sun[0], sun[1], sun[0] + 170, sun[1] + 170), fill=(255, 242, 205, 55))
    draw.ellipse((sun[0] + 42, sun[1] + 42, sun[0] + 128, sun[1] + 128), fill=(255, 248, 220, 82))

    # Ground and site boundary.
    ground = [(-170, -130), (170, -130), (170, 130), (-170, 130)]
    draw.polygon([_project_iso(x, z, 0) for x, z in ground], fill=_mix(green, light, 0.58))
    site = [(-130, -95), (130, -95), (130, 95), (-130, 95)]
    site_pts = [_project_iso(*_rotate_for_direction(x, z, direction), 0.1) for x, z in site]
    draw.polygon(site_pts, fill=(226, 224, 213, 236), outline=(120, 122, 115))

    # Perimeter fence.
    fence = [_project_iso(*_rotate_for_direction(x, z, direction), 0.2) for x, z in site]
    draw.line(fence + [fence[0]], fill=(58, 63, 72), width=3)
    for x in range(-120, 121, 20):
        for z in (-95, 95):
            px, py = _project_iso(*_rotate_for_direction(x, z, direction), 0)
            draw.line((px, py, px, py - 14), fill=(58, 63, 72), width=3)
    for z in range(-80, 81, 20):
        for x in (-130, 130):
            px, py = _project_iso(*_rotate_for_direction(x, z, direction), 0)
            draw.line((px, py, px, py - 14), fill=(58, 63, 72), width=3)

    scene = _scene_spec(layout, ranked, inp)

    # Roads from the same macro-layout as the 3D model.
    for (cx, cz), (rw, rd) in scene['roads']:
        _draw_road_poly(draw, [(cx-rw/2, cz-rd/2), (cx+rw/2, cz-rd/2), (cx+rw/2, cz+rd/2), (cx-rw/2, cz+rd/2)])

    # Building program derived from the same scene spec as the 3D model.
    objects = []
    for bx, bz, bw, bd, bh, blabel in scene['buildings']:
        if blabel == 'цех':
            color, stroke = _mix(light, base, 0.18), accent
        elif blabel == 'склад':
            color, stroke = _mix(light, base, 0.32), base
        elif blabel == 'АБК':
            color, stroke = _mix(light, brick, 0.20), brick
        elif blabel == 'КПП':
            color, stroke = (245, 245, 242), (90, 96, 105)
        elif blabel == 'жильё':
            color, stroke = _mix(light, brick, 0.14), brick
        elif blabel == 'детсад':
            color, stroke = _mix((255, 246, 215), accent, 0.12), accent
        else:
            color, stroke = _mix((219, 236, 210), green, 0.10), green
        objects.append((bx, bz, bw, bd, bh, color, stroke, blabel))

    # Decorative/functional flat zones from the same scene spec.
    _draw_parking(draw, *scene['parking'], direction)
    _draw_parking(draw, *scene['logistics'], direction)
    gx, gz, gw, gd = scene['green']
    topg, _, _, _ = _box_poly(gx, gz, gw, gd, 0.3, direction)
    draw.polygon(topg, fill=_mix(green, light, 0.35), outline=(94, 130, 92))

    # Trees and site details.
    _draw_tree_cluster(draw, gx, gz, 6, 18, direction, green)
    if inp.amenities and any(_value(a) in {'alley', 'square', 'health_trail'} for a in inp.amenities):
        sx, sz = layout['social']
        for i in range(6):
            rx, rz = _rotate_for_direction(sx - 26 + i * 10, sz + 18, direction)
            px, py = _project_iso(rx, rz, 0)
            _draw_tree(draw, px, py, 0.72, leaf=green)

    # Sort objects by depth relative to camera.
    def depth(item):
        _, _, _, _, _, _, _, label = item
        rx, rz = _rotate_for_direction(item[0], item[1], direction)
        return rx + rz
    for obj in sorted(objects, key=depth):
        top, front, side, _ = _box_poly(obj[0], obj[1], obj[2], obj[3], obj[4], direction)
        shadow = [(x + 9, y + 10) for x, y in front[:2] + side[:1]]
        color, stroke = obj[5], obj[6]
        draw.polygon(top, fill=_mix(color, (255, 255, 255), 0.34), outline=_mix(stroke, (0, 0, 0), 0.10))
        draw.polygon(side, fill=_mix(color, (0, 0, 0), 0.15), outline=_mix(stroke, (0, 0, 0), 0.10))
        draw.polygon(front, fill=color, outline=_mix(stroke, (0, 0, 0), 0.12))
        x1 = min(p[0] for p in front); x2 = max(p[0] for p in front); y1 = min(p[1] for p in front); y2 = max(p[1] for p in front)
        # label pill without fixed width to avoid text overflow
        label = obj[7]
        label_font = _font(12, True)
        label_text = _fit_line(draw, label, label_font, 108)
        tw = draw.textbbox((0, 0), label_text, font=label_font)[2]
        lx = int((x1 + x2) / 2 - (tw + 20) / 2)
        ly = y1 - 22
        _rounded_rect(draw, (lx, ly, lx + tw + 20, ly + 24), 10, fill=(255,255,255,228), outline=(218, 216, 210), width=1)
        draw.text((lx + 10, ly + 5), label_text, fill=(42, 48, 62), font=label_font)

    dir_label = next((label for key, label, _ in DIRECTIONS if key == direction), direction)
    subtext = f"рендер построен из 3D-макета · {layout['title'].lower()}"
    _draw_header(draw, region, dir_label, palette, subtext)

    direction_badges = {
        'south': ('ОБЩЕСТВЕННЫЙ ВХОД', (70, 110, 98)),
        'north': ('ПРОИЗВОДСТВЕННЫЙ ТЫЛ', (75, 83, 96)),
        'west': ('СОЦИАЛЬНАЯ ЗОНА', (78, 128, 84)),
        'east': ('ГРУЗОВОЙ КОНТУР', (125, 86, 56)),
    }
    badge_text, badge_color = direction_badges.get(direction, (dir_label.upper(), accent))
    _rounded_rect(draw, (90, 158, 420, 210), 18, fill=badge_color + (236,), outline=(255,255,255,120), width=2)
    draw.text((112, 173), badge_text, fill=(255,255,255), font=_font(24, True))

    # footer panel with short facts.
    panel_y = 792
    _rounded_rect(draw, (58, panel_y, 1542, 872), 22, fill=(255, 255, 255, 225), outline=(225, 222, 215), width=2)
    draw.text((92, panel_y + 18), 'Основа:', fill=(34, 38, 54), font=_font(23, True))
    desc = f"тот же макет, что и во вкладке 3D-модель; схема: {layout['title'].lower()}; участок {ranked.site_and_network_mln:.1f} млн ₽; мощности {region.infrastructure.free_power_kva} кВА; газ: {'есть' if region.infrastructure.gas_available else 'нет'}."
    lines = list(_wrap_text(draw, desc, _font(22), 1240))[:2]
    for i, line in enumerate(lines):
        draw.text((198, panel_y + 18 + i * 28), line, fill=(63, 68, 86), font=_font(22))

    img.save(output_path, quality=95)
    return output_path

def render_job_id(region_id: str, inp: InvestorInput, layout_key: str | None = None) -> str:
    layout_part = normalize_layout_key(layout_key, region_id)
    return f"{region_id}_{layout_part}_{inp.production_volume_kt}_{inp.employees}_{inp.budget_mln_rub}_{_value(inp.arch_priority)}_{inp.housing.pct}_{inp.kindergarten_per_100}"


def generate_project_renders(region: Region, ranked: RankedRegion, inp: InvestorInput, brief: RegionBrief, layout_key: str | None = None) -> Dict[str, Path]:
    layout_key = normalize_layout_key(layout_key, region.id)
    job = render_job_id(region.id, inp, layout_key)
    out_dir = RENDER_DIR / job
    out_dir.mkdir(parents=True, exist_ok=True)
    paths: Dict[str, Path] = {}
    for key, _, _ in DIRECTIONS:
        path = out_dir / f"render_{key}.png"
        create_project_render(region, ranked, inp, brief, key, path, layout_key)
        paths[key] = path
    return paths


def generate_site_plan(region: Region, ranked: RankedRegion, inp: InvestorInput, layout_key: str | None = None, output_path: Path | None = None) -> Path:
    """Формирует устойчивую инженерную схему участка без наложений.

    Версия v26: безопасная сетка. Все здания стоят в отдельных зонах, дорога и
    ж/д не проходят под текстом, экспликация отделена от схемы. Схема должна
    выглядеть нормально в браузере, Word и презентации.
    """
    layout_key = normalize_layout_key(layout_key, region.id)
    layout = LAYOUTS_3D[layout_key]
    job = render_job_id(region.id, inp, layout_key)
    if output_path is None:
        output_path = RENDER_DIR / job / "site_plan.png"
    output_path.parent.mkdir(parents=True, exist_ok=True)

    W, H = 1500, 980
    dark = (7, 28, 58)
    blue = (37, 99, 235)
    cyan = (14, 165, 233)
    muted = (83, 105, 138)
    line = (191, 207, 231)
    bg = (246, 249, 255)
    white = (255, 255, 255)
    road = (84, 94, 110)
    green = (113, 170, 118)

    img = Image.new("RGB", (W, H), bg)
    draw = ImageDraw.Draw(img, "RGBA")

    def area(v: float) -> str:
        return f"{max(0, float(v)):.0f} м²"

    def box(x, y, w, h):
        return (x, y, x + w, y + h)

    def rr(b, fill, outline=(95, 113, 140), width=2, radius=12):
        _rounded_rect(draw, b, radius, fill=fill, outline=outline, width=width)
        return b

    def centered_title(b, title, size=16, color=dark):
        x1, y1, x2, y2 = b
        f = _font(size, True)
        txt = _fit_line(draw, title, f, int(x2 - x1 - 24))
        bb = draw.textbbox((0, 0), txt, font=f)
        tw, th = bb[2] - bb[0], bb[3] - bb[1]
        draw.text((x1 + ((x2-x1)-tw)/2, y1 + ((y2-y1)-th)/2 - 2), txt, fill=color, font=f)

    def draw_area_label(b, label):
        x1, y1, x2, y2 = b
        f = _font(12)
        txt = _fit_line(draw, label, f, int(x2 - x1 - 16))
        bb = draw.textbbox((0, 0), txt, font=f)
        tw = bb[2] - bb[0]
        draw.text((x1 + ((x2-x1)-tw)/2, y2 - 28), txt, fill=muted, font=f)

    # Header.
    rr((42, 34, W - 42, 118), fill=white, outline=(207, 220, 240), width=2, radius=24)
    draw.text((74, 54), "Инженерный план участка", fill=dark, font=_font(31, True))
    subtitle = f"{region.name} · {region.federal_subject} · {layout['title'].lower()}"
    draw.text((74, 90), _fit_line(draw, subtitle, _font(18), 1050), fill=muted, font=_font(18))
    draw.polygon([(1400, 52), (1378, 104), (1422, 104)], fill=(37, 99, 235, 230))
    draw.text((1395, 108), "С", fill=blue, font=_font(16, True))

    # Plot area.
    px1, py1, px2, py2 = 54, 142, W - 54, 752
    rr((px1, py1, px2, py2), fill=(240, 246, 253), outline=line, width=2, radius=24)

    def pbox(x, y, w, h):
        return (px1 + x, py1 + y, px1 + x + w, py1 + y + h)

    # Fixed safe lanes. Road is at the bottom and never covers buildings.
    main_road = rr(pbox(80, 455, 1220, 54), fill=road, outline=(70, 78, 92), radius=7)
    for x in range(px1 + 135, px1 + 1250, 105):
        draw.line((x, py1 + 482, x + 42, py1 + 482), fill=(226, 232, 240), width=3)

    if inp.needs_railway:
        rail_y = py1 + 548
        draw.line((px1 + 110, rail_y, px2 - 110, rail_y), fill=(42, 48, 60), width=3)
        draw.line((px1 + 110, rail_y + 20, px2 - 110, rail_y + 20), fill=(42, 48, 60), width=3)
        for x in range(px1 + 132, px2 - 130, 70):
            draw.line((x, rail_y - 6, x + 24, rail_y + 28), fill=(120, 91, 64), width=3)

    # КПП is outside the road body, attached to entry but not overlapping it.
    kpp = rr(pbox(28, 408, 88, 58), fill=white, outline=blue, width=2, radius=10)
    centered_title(kpp, "КПП", 14)

    # Production zone: left side, strictly above road.
    workshop = rr(pbox(120, 185, 475, 155), fill=(209, 225, 251), outline=blue, width=3, radius=14)
    for x in range(int(workshop[0]) + 42, int(workshop[2]) - 20, 62):
        draw.line((x, workshop[1] + 20, x, workshop[3] - 20), fill=(152, 180, 225), width=2)
    centered_title(workshop, "Производственный цех", 18)
    draw_area_label(workshop, area(ranked.areas.workshop_m2))

    abk = rr(pbox(120, 60, 225, 78), fill=(216, 236, 255), outline=cyan, width=2, radius=12)
    centered_title(abk, "АБК", 18)
    draw_area_label(abk, area(ranked.areas.office_m2))

    parking = rr(pbox(420, 60, 310, 78), fill=(226, 232, 240), outline=(125, 139, 161), width=2, radius=12)
    centered_title(parking, "Парковка", 16)
    draw_area_label(parking, area(ranked.areas.parking_m2))
    for x in range(int(parking[0]) + 26, int(parking[2]) - 12, 42):
        draw.line((x, parking[1] + 16, x, parking[3] - 18), fill=(255, 255, 255), width=2)

    # Social zone is above road with clear gap.
    social = rr(pbox(120, 360, 475, 72), fill=(236, 248, 241), outline=(81, 145, 91), radius=14)
    centered_title(social, "Социальный блок", 16, color=(34, 95, 49))
    # Icons are small and centered, not touching the road.
    icon_y1 = social[3] - 26
    icon_count = 3
    icon_w = 56
    icon_gap = ((social[2] - social[0]) - icon_count * icon_w) / (icon_count + 1)
    for i, color in enumerate([(234, 221, 196), (255, 237, 178), (213, 238, 223)]):
        x = int(social[0] + icon_gap + i * (icon_w + icon_gap))
        _rounded_rect(draw, (x, icon_y1, x + icon_w, icon_y1 + 18), 6, fill=color, outline=(145, 179, 154), width=1)

    # Middle warehouse cluster. No vertical road line between blocks anymore.
    warehouse = rr(pbox(660, 225, 250, 125), fill=(222, 232, 244), outline=(79, 99, 128), width=2, radius=12)
    centered_title(warehouse, "Склад", 18)
    draw_area_label(warehouse, area(ranked.areas.warehouse_m2))

    raw_yard = rr(pbox(660, 378, 250, 62), fill=(235, 240, 247), outline=(100, 116, 139), radius=11)
    centered_title(raw_yard, "Сырьевой двор", 14)
    for x in range(int(raw_yard[0]) + 26, int(raw_yard[2]) - 22, 38):
        draw.ellipse((x, raw_yard[1] + 39, x + 14, raw_yard[1] + 53), fill=(148, 163, 184), outline=(71, 85, 105), width=1)

    # Short service road between warehouse and main road, behind empty gap only.
    service_road = rr(pbox(928, 205, 54, 250), fill=road, outline=(70, 78, 92), radius=7)
    draw.line((px1 + 955, py1 + 455, px1 + 955, py1 + 509), fill=road, width=54)

    # Right cluster.
    green_box = rr(pbox(1080, 60, 260, 90), fill=(220, 244, 226), outline=(91, 158, 111), radius=14)
    centered_title(green_box, "Благоустройство", 15, color=(35, 104, 58))
    for i in range(5):
        x = int(green_box[0] + 44 + i * 44)
        y = int(green_box[1] + 67)
        _draw_tree(draw, x, y, 0.24, leaf=green)

    logistics = rr(pbox(1080, 225, 260, 110), fill=(235, 238, 243), outline=(100, 116, 139), radius=12)
    centered_title(logistics, "Грузовой двор", 16)
    # Доковые ворота строго внутри контура, без выхода за границу блока.
    dock_count = 4
    dock_w, dock_h = 32, 18
    gap = ((logistics[2] - logistics[0]) - dock_count * dock_w) / (dock_count + 1)
    for i in range(dock_count):
        x = int(logistics[0] + gap + i * (dock_w + gap))
        y = int(logistics[1] + 76)
        _rounded_rect(draw, (x, y, x + dock_w, y + dock_h), 4, fill=(248, 250, 252), outline=(70, 78, 92), width=1)

    engineering = rr(pbox(1080, 365, 260, 70), fill=(239, 242, 247), outline=(100, 116, 139), radius=12)
    centered_title(engineering, "Инженерная зона", 14)

    panels = rr(pbox(1080, 455, 260, 46), fill=(239, 246, 255), outline=(100, 116, 139), radius=11)
    centered_title(panels, "Готовые панели", 13)

    # Bottom explication in a separate panel, no collision with plot.
    panel = (54, 780, W - 54, 948)
    rr(panel, fill=white, outline=(207, 220, 240), width=2, radius=22)
    draw.text((84, 804), "Экспликация", fill=dark, font=_font(21, True))

    chips = [
        ("1. Цех", area(ranked.areas.workshop_m2)),
        ("2. Склад", area(ranked.areas.warehouse_m2)),
        ("3. АБК", area(ranked.areas.office_m2)),
        ("4. Парковка", area(ranked.areas.parking_m2)),
        ("5. Соц. объекты", area(ranked.areas.housing_m2 + ranked.areas.kindergarten_m2 + ranked.areas.canteen_m2 + ranked.areas.medical_m2)),
        ("6. Дороги", area(ranked.areas.roads_m2)),
        ("Итого", area(ranked.areas.total_m2)),
    ]
    x, y = 238, 796
    for name, val in chips:
        label = f"{name}: {val}"
        f = _font(14, True)
        tw = draw.textbbox((0, 0), label, font=f)[2]
        if x + tw + 36 > W - 80:
            x = 84
            y += 42
        _rounded_rect(draw, (x, y, x + tw + 28, y + 30), 9, fill=(239, 246, 255), outline=(207, 220, 240), width=1)
        draw.text((x + 14, y + 7), label, fill=dark, font=f)
        x += tw + 42

    note = "Предварительная схема. Точное положение объектов уточняется по инженерным изысканиям, ПЗЗ, ТУ, санитарным разрывам и проектной документации."
    draw.text((84, 888), _fit_line(draw, note, _font(14), 1260), fill=muted, font=_font(14))

    img.save(output_path, quality=95)
    return output_path



def generate_concept_board(region: Region, ranked: RankedRegion, inp: InvestorInput, brief: RegionBrief, output_path: Path | None = None) -> Path:
    """Создаёт отдельный концепт-борд: палитра, материалы, стиль, благоустройство и производственный образ."""
    job = render_job_id(region.id, inp)
    if output_path is None:
        output_path = RENDER_DIR / job / "concept_board.png"
    output_path.parent.mkdir(parents=True, exist_ok=True)

    W, H = 1600, 900
    raw_palette = region.culture.color_palette or []
    colors = [
        _hex_to_rgb(raw_palette[i] if len(raw_palette) > i else "", default)
        for i, default in enumerate([
            (132, 103, 74), (198, 160, 82), (245, 242, 232), (58, 96, 84), (124, 58, 58)
        ])
    ]
    base, accent, light, green, brick = colors
    img = Image.new("RGB", (W, H), (248, 247, 243))
    draw = ImageDraw.Draw(img, "RGBA")

    # background
    for y in range(H):
        t = y / H
        draw.line((0, y, W, y), fill=_mix((250, 249, 245), _mix(light, green, 0.16), t))
    _rounded_rect(draw, (48, 42, 1552, 858), 36, fill=(255,255,255,236), outline=(222,218,207), width=3)

    draw.text((86, 78), "Концепт-борд региона", fill=(28,34,54), font=_font(48, True))
    draw.text((88, 137), f"{region.name} · {region.federal_subject}", fill=(82,90,108), font=_font(26))
    _rounded_rect(draw, (86, 182, 250, 190), 4, fill=accent)

    # Palette block
    draw.text((90, 230), "Цветовая палитра", fill=(28,34,54), font=_font(31, True))
    x = 90
    for idx, c in enumerate(colors):
        _rounded_rect(draw, (x, 285, x+180, 450), 24, fill=c, outline=(228,226,219), width=2)
        code = raw_palette[idx] if len(raw_palette) > idx else "#%02X%02X%02X" % c
        _rounded_rect(draw, (x+18, 397, x+162, 432), 12, fill=(255,255,255,220))
        draw.text((x+34, 405), code, fill=(30,34,46), font=_font(18, True))
        x += 205

    # Materials block
    draw.text((90, 505), "Материалы и фактуры", fill=(28,34,54), font=_font(31, True))
    materials = list(region.culture.traditional_materials or [])[:4]
    if not materials:
        materials = ["металл", "кирпич", "дерево", "озеленение"]
    material_fills = [
        _mix(light, base, .28), _mix(brick, light, .28), _mix((125,82,48), light, .18), _mix(green, light, .18)
    ]
    for i, material in enumerate(materials):
        mx = 90 + i * 250
        _rounded_rect(draw, (mx, 560, mx+220, 720), 22, fill=(249,248,244), outline=(226,223,215), width=2)
        # simple texture sample
        _rounded_rect(draw, (mx+18, 582, mx+202, 650), 16, fill=material_fills[i % len(material_fills)], outline=(200,196,186), width=1)
        if i == 0:
            for sx in range(mx+26, mx+196, 22):
                draw.line((sx, 584, sx+26, 648), fill=(255,255,255,65), width=2)
        elif i == 1:
            for yy in range(590, 647, 18):
                draw.line((mx+20, yy, mx+200, yy), fill=(85,60,52,75), width=2)
                for sx in range(mx+25+(yy%36), mx+195, 52):
                    draw.line((sx, yy, sx, yy+16), fill=(85,60,52,55), width=2)
        elif i == 2:
            for yy in range(590, 648, 12):
                draw.arc((mx+18, yy-20, mx+202, yy+24), 5, 175, fill=(80,54,38,60), width=2)
        else:
            for sx in range(mx+35, mx+190, 35):
                _draw_tree(draw, sx, 642, .42, leaf=green)
        draw.text((mx+22, 670), _fit_text(draw, material, _font(21, True), 170), fill=(38,44,58), font=_font(21, True))

    # Style / logic card
    right_x = 1130
    _rounded_rect(draw, (right_x, 230, 1508, 720), 26, fill=(249,248,244), outline=(226,223,215), width=2)
    draw.text((right_x+28, 260), "Архитектурный образ", fill=(28,34,54), font=_font(30, True))
    arch = ARCH_LABELS.get(_value(inp.arch_priority), _value(inp.arch_priority))
    styles = ", ".join((region.culture.dominant_styles or [])[:3]) or arch
    amenities = ", ".join(AMENITY_LABELS.get(_value(x), _value(x)) for x in (inp.amenities or [])) or "базовое озеленение"
    sports = ", ".join(SPORT_LABELS.get(_value(x), _value(x)) for x in (inp.sport_objects or [])) or "без отдельного спортобъекта"
    lines = [
        f"Приоритет: {arch}",
        f"Стили: {styles}",
        f"Благоустройство: {amenities}",
        f"Спорт: {sports}",
        f"Рабочие места: {inp.employees}",
        f"Площадь цеха: {ranked.areas.workshop_m2:.0f} м²",
    ]
    y = 320
    for line in lines:
        _rounded_rect(draw, (right_x+28, y, right_x+344, y+52), 15, fill=(255,255,255,210), outline=(232,229,220), width=1)
        fitted = _fit_text(draw, line, _font(18), 270)
        draw.text((right_x+48, y+16), fitted, fill=(63,68,86), font=_font(18))
        y += 62

    # Mini factory silhouette
    idea = "Ключевая идея: современный промышленный корпус + региональные акценты в АБК, навигации и общественной зоне"
    for i, line in enumerate(list(_wrap_text(draw, idea, _font(22, True), 980))[:2]):
        draw.text((90, 758 + i*30), line, fill=(63,68,86), font=_font(22, True))
    _draw_isometric_block(draw, 1110, 740, 250, 75, 62, _mix(light, base, 0.24), accent, "")
    _draw_isometric_block(draw, 1350, 770, 105, 45, 42, _mix(light, brick, 0.22), brick, "")

    img.save(output_path, quality=95)
    return output_path
