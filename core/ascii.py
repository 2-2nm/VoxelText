import numpy as np
from PIL import Image, ImageDraw, ImageFont
import moderngl

from core.utils import hex_to_rgb_float

ASCII_CHARS_COLOR_BLOCKY = ["█"]

VERTEX_SHADER_PASS1 = """
#version 330 core
in vec2 in_vert;
in vec2 in_texcoord;
out vec2 v_texcoord;

void main() {
    gl_Position = vec4(in_vert, 0.0, 1.0);
    v_texcoord = vec2(in_texcoord.x, 1.0 - in_texcoord.y);
}
"""

FRAGMENT_SHADER_PASS1 = """
#version 330 core
uniform sampler2D u_frame;
uniform sampler2D u_atlas;
uniform vec2 u_grid_size;
uniform vec2 u_cell_px;        // render pixels per cell. (0,0) = legacy glyph-only.
uniform float u_glyph_cov[32]; // mean ink coverage per glyph (used when cells are tiny)
uniform vec2 u_frame_size;     // (0,0) = point sampling (legacy). Else area-average via mipmaps.
uniform int u_num_chars;
uniform int u_color_mode;
uniform float u_tone;          // 0 = legacy linear. 1 = lift shadows + fade dark glyphs.
uniform float u_color_boost;   // 0 = raw pixel colour. 1 = full-brightness hue (density carries brightness).
uniform vec3 u_text_color;
uniform vec3 u_bg_color;

in vec2 v_texcoord;
out vec4 fragColor;

void main() {
    vec2 cell_idx = floor(v_texcoord * u_grid_size);
    vec2 cell_uv = fract(v_texcoord * u_grid_size);
    vec2 clamped_cell_uv = clamp(cell_uv, vec2(0.001), vec2(0.999));

    vec2 frame_uv = (cell_idx + vec2(0.5)) / u_grid_size;

    float lod = 0.0;
    if (u_frame_size.x > 0.0) {
        vec2 texels_per_cell = u_frame_size / u_grid_size;
        lod = max(0.0, 0.5 * (log2(max(texels_per_cell.x, 1.0)) + log2(max(texels_per_cell.y, 1.0))));
    }
    vec4 frame_pixel = textureLod(u_frame, frame_uv, lod);

    if (u_color_mode == 1) {
        frame_pixel.r = floor(frame_pixel.r * 31.0 + 0.5) / 31.0;
        frame_pixel.g = floor(frame_pixel.g * 63.0 + 0.5) / 63.0;
        frame_pixel.b = floor(frame_pixel.b * 31.0 + 0.5) / 31.0;
    }

    float brightness = dot(frame_pixel.rgb, vec3(0.299, 0.587, 0.114));
    brightness = pow(clamp(brightness, 0.0, 1.0), 1.0 - 0.5 * u_tone);
    int char_idx = clamp(int(brightness * float(u_num_chars)), 0, u_num_chars - 1);

    float u_char = (float(char_idx) + clamped_cell_uv.x) / float(u_num_chars);
    float v_char = clamped_cell_uv.y;

    float mask = texture(u_atlas, vec2(u_char, v_char)).r;
    if (u_cell_px.x > 0.0) {
        // Below ~3px per cell a glyph cannot be resolved: sampling it just aliases into stripes.
        // Use the glyph's average coverage instead (what a proper downscale would produce).
        float detail = smoothstep(2.5, 6.0, u_cell_px.x);
        mask = mix(u_glyph_cov[char_idx], mask, detail);
    }

    vec3 fg_color = u_text_color;
    if (u_color_mode == 1) {
        float mx = max(max(frame_pixel.r, frame_pixel.g), frame_pixel.b);
        vec3 hue = (mx > 0.001) ? frame_pixel.rgb / mx : vec3(1.0);
        fg_color = mix(frame_pixel.rgb, hue, u_color_boost);
    }
    fg_color *= mix(1.0, 0.35 + 0.65 * brightness, u_tone);

    vec3 final_rgb = mix(u_bg_color, fg_color, mask);
    fragColor = vec4(final_rgb, 1.0);
}
"""

VERTEX_SHADER_PASS2 = """
#version 330 core
in vec2 in_vert;
in vec2 in_texcoord;
out vec2 v_texcoord;

void main() {
    gl_Position = vec4(in_vert, 0.0, 1.0);
    v_texcoord = in_texcoord;
}
"""

FRAGMENT_SHADER_PASS2 = """
#version 330 core
uniform sampler2D u_tex;
in vec2 v_texcoord;
out vec4 fragColor;

void main() {
    fragColor = texture(u_tex, v_texcoord);
}
"""


_SHADE_PATTERNS = {
    "░": lambda x, y: x % 2 == 0 and y % 2 == 0,
    "▒": lambda x, y: (x + y) % 2 == 0,
    "▓": lambda x, y: x % 2 == 1 or y % 2 == 1,
}


def generate_glyph_atlas_image(ascii_chars, char_w=7, char_h=12):
    num_chars = len(ascii_chars)
    atlas_w = char_w * num_chars
    atlas_h = char_h

    atlas_pil = Image.new("L", (atlas_w, atlas_h), 0)
    draw = ImageDraw.Draw(atlas_pil)

    font = None
    font_size = char_h - 1
    for fn in ["consola.ttf", "Consolas.ttf", "cour.ttf", "Courier New.ttf", "DejaVuSansMono.ttf"]:
        try:
            font = ImageFont.truetype(fn, font_size)
            break
        except Exception:
            continue
    if font is None:
        font = ImageFont.load_default()

    for i, ch in enumerate(ascii_chars):
        if ch in [" ", ""]:
            continue
        x_offset = i * char_w
        if ch == "█":
            draw.rectangle([x_offset, 0, x_offset + char_w - 1, char_h - 1], fill=255)
        elif ch in _SHADE_PATTERNS:
            pattern = _SHADE_PATTERNS[ch]
            for yy in range(char_h):
                for xx in range(char_w):
                    if pattern(xx, yy):
                        atlas_pil.putpixel((x_offset + xx, yy), 255)
        else:
            try:
                bbox = font.getbbox(ch)
                w_ch = bbox[2] - bbox[0]
                h_ch = bbox[3] - bbox[1]
                x_pos = x_offset + max(0, (char_w - w_ch) // 2) - bbox[0]
                y_pos = max(0, (char_h - h_ch) // 2) - bbox[1]
            except Exception:
                x_pos = x_offset
                y_pos = 0
            draw.text((x_pos, y_pos), ch, fill=255, font=font)

    return np.array(atlas_pil)


_RAMP_CANDIDATES = " .'`^\",:;Il!i><~+_-?][}{1)(|\\/tfjrxnuvczXYUJCLQ0OZmwqpdbkhao*#MW&8%B@$"

MAX_GLYPHS = 32  

CHARSETS = {
    "Standard": ("auto", 16),
    "Fine":     ("auto", 32),
    "Classic":  " .:-=+*#%@",
    "Blocks":   " ░▒▓█",
    "Minimal":  " .oO@",
    "Digits":   " 1234567890",
}
CHARSET_NAMES = list(CHARSETS.keys())

_active_charset = "Standard"
_ramp_cache = {}


def _coverage_of(chars, char_w=7, char_h=12):
    atlas = generate_glyph_atlas_image(list(chars), char_w, char_h)
    return {ch: float(atlas[:, i * char_w:(i + 1) * char_w].mean()) for i, ch in enumerate(chars)}


def build_density_ramp(n=16, candidates=_RAMP_CANDIDATES):
    cands = list(dict.fromkeys(candidates))
    cov = _coverage_of(cands)
    ordered = sorted(cands, key=lambda ch: cov[ch])
    max_c = cov[ordered[-1]] or 1.0
    chosen, used = [], set()
    for k in range(n):
        target = max_c * k / (n - 1)
        best = min((ch for ch in ordered if ch not in used), key=lambda ch: abs(cov[ch] - target))
        used.add(best)
        chosen.append(best)
    chosen.sort(key=lambda ch: cov[ch])
    return chosen


def get_ramp(name=None):
    name = name or _active_charset
    if name not in CHARSETS:
        name = "Standard"
    if name not in _ramp_cache:
        spec = CHARSETS[name]
        if isinstance(spec, tuple):
            ramp = build_density_ramp(spec[1])
        else:
            chars = list(dict.fromkeys(spec))
            cov = _coverage_of(chars)
            ramp = sorted(chars, key=lambda ch: cov[ch])
        _ramp_cache[name] = ramp[:MAX_GLYPHS]
    return list(_ramp_cache[name])


def set_charset(name):
    global _active_charset
    if name in CHARSETS:
        _active_charset = name


def get_charset():
    return _active_charset


def get_ascii_chars(color_mode, style, transparency):
    if color_mode == "Color" and str(style).lower() == "blocky":
        return ASCII_CHARS_COLOR_BLOCKY
    ramp = get_ramp()
    return list(reversed(ramp)) if transparency == "white" else ramp


def set_glyph_coverage(prog, atlas_img, num_chars, char_w=7):
    cov = np.zeros(MAX_GLYPHS, dtype="f4")
    for i in range(min(num_chars, MAX_GLYPHS)):
        cov[i] = float(atlas_img[:, i * char_w:(i + 1) * char_w].mean()) / 255.0
    try:
        prog["u_glyph_cov"].write(cov.tobytes())
    except KeyError:
        pass


ASCII_CHARS_BLACK_BG = get_ramp("Standard")
ASCII_CHARS_WHITE_BG = list(reversed(ASCII_CHARS_BLACK_BG))


def render_image_gpu(image_path, target_cols, max_ui_w, max_ui_h, color_mode="Color", fullcolor_style="Blocky", palette_hex="#8AA090", transparent_target="white", theme_bg_color="#101217"):
    img = Image.open(image_path).convert("RGBA")
    orig_w, orig_h = img.size
    
    char_w, char_h = 7, 12
    font_aspect = char_w / char_h

    ascii_str = convert_image_to_ascii_str(image_path, new_width=target_cols, transparent_target=transparent_target)

    ctx = moderngl.create_standalone_context()
    max_tex_size = ctx.info.get('GL_MAX_TEXTURE_SIZE', 8192)

    verts_pass1 = np.array([-1.0, -1.0, 0.0, 1.0, 1.0, -1.0, 1.0, 1.0, -1.0, 1.0, 0.0, 0.0, 1.0, 1.0, 1.0, 0.0], dtype='f4')
    prog1 = ctx.program(vertex_shader=VERTEX_SHADER_PASS1, fragment_shader=FRAGMENT_SHADER_PASS1)
    vbo1 = ctx.buffer(verts_pass1.tobytes())
    vao1 = ctx.vertex_array(prog1, [(vbo1, '2f 2f', 'in_vert', 'in_texcoord')])

    verts_pass2 = np.array([-1.0, -1.0, 0.0, 0.0, 1.0, -1.0, 1.0, 0.0, -1.0, 1.0, 0.0, 1.0, 1.0, 1.0, 1.0, 1.0], dtype='f4')
    prog2 = ctx.program(vertex_shader=VERTEX_SHADER_PASS2, fragment_shader=FRAGMENT_SHADER_PASS2)
    vbo2 = ctx.buffer(verts_pass2.tobytes())
    vao2 = ctx.vertex_array(prog2, [(vbo2, '2f 2f', 'in_vert', 'in_texcoord')])

    ascii_chars = get_ascii_chars(color_mode, fullcolor_style, transparent_target)

    atlas_img = generate_glyph_atlas_image(ascii_chars, char_w, char_h)
    num_chars = len(ascii_chars)

    atlas_tex = ctx.texture((char_w * num_chars, char_h), 1, atlas_img.tobytes())
    atlas_tex.filter = (moderngl.NEAREST, moderngl.NEAREST)
    atlas_tex.repeat_x = False
    atlas_tex.repeat_y = False
    atlas_tex.use(location=1)

    prog1['u_atlas'].value = 1
    prog1['u_num_chars'].value = num_chars
    prog1['u_color_mode'].value = 1 if color_mode == "Color" else 0
    prog1['u_bg_color'].value = hex_to_rgb_float(theme_bg_color)
    prog1['u_text_color'].value = hex_to_rgb_float(palette_hex)

    aspect_factor = (orig_h / orig_w) * font_aspect
    max_cols_w = max_tex_size // char_w
    max_rows_h = max_tex_size // char_h
    max_cols_from_h = int(max_rows_h / aspect_factor) if aspect_factor > 0 else max_cols_w
    
    effective_cols = max(10, min(target_cols, max_cols_w, max_cols_from_h))
    grid_rows = max(1, int(round(aspect_factor * effective_cols)))

    win_w = effective_cols * char_w
    win_h = grid_rows * char_h

    scale = min(max_ui_w / float(win_w), max_ui_h / float(win_h))
    ui_w = max(1, int(round(win_w * scale)))
    ui_h = max(1, int(round(win_h * scale)))

    render_tex = ctx.texture((win_w, win_h), 3)
    render_tex.filter = (moderngl.LINEAR_MIPMAP_LINEAR, moderngl.LINEAR)
    render_tex.repeat_x = False
    render_tex.repeat_y = False
    fbo1 = ctx.framebuffer(color_attachments=[render_tex])

    downsample_tex = ctx.texture((ui_w, ui_h), 3)
    fbo2 = ctx.framebuffer(color_attachments=[downsample_tex])

    prog1['u_grid_size'].value = (float(effective_cols), float(grid_rows))

    img_rgb = img.convert("RGB")
    frame_bytes = img_rgb.tobytes()

    frame_tex = ctx.texture(img_rgb.size, 3, frame_bytes)
    frame_tex.filter = (moderngl.LINEAR, moderngl.LINEAR)
    frame_tex.use(location=0)
    prog1['u_frame'].value = 0

    fbo1.use()
    ctx.clear(0.0, 0.0, 0.0, 1.0)
    vao1.render(moderngl.TRIANGLE_STRIP)

    render_tex.build_mipmaps()

    fbo2.use()
    ctx.clear(0.0, 0.0, 0.0, 1.0)
    render_tex.use(location=0)
    prog2['u_tex'].value = 0
    vao2.render(moderngl.TRIANGLE_STRIP)

    raw_bytes = fbo2.read(components=3)
    pil_img = Image.frombytes('RGB', (ui_w, ui_h), raw_bytes)

    frame_tex.release()
    render_tex.release()
    downsample_tex.release()
    atlas_tex.release()
    fbo1.release()
    fbo2.release()
    ctx.release()

    return pil_img, ascii_str


def convert_image_to_ascii_str(image_path, new_width=80, transparent_target="white"):
    try:
        img = Image.open(image_path)
    except Exception as e:
        raise Exception(f"Failed: {e}")
    
    w, h = img.size
    font_aspect_ratio = 7 / 12
    new_height = max(1, int((h / w) * new_width * font_aspect_ratio))
    ri = img.resize((new_width, new_height), Image.Resampling.LANCZOS)
    
    ra, ga = np.array(ri.convert("RGBA")), np.array(ri.convert("L"))
    ac = get_ascii_chars("White", "", transparent_target)
    nc = len(ac)
    anp = np.array(list(ac))
    idx = np.clip((ga.astype(np.uint16) * nc) // 256, 0, nc - 1)
    cm = anp[idx]
    cm[ra[:, :, 3] < 128] = " "
    return "\n".join("".join(row) for row in cm)


def save_ascii_as_image(ascii_content, output_path, bg_color="#090A0F", text_color="#9ECE6A", gui_preview_data=None):
    font_file, font_size = None, 14
    f = None
    for fn in ["consola.ttf", "Consolas.ttf", "cour.ttf", "Courier New.ttf", "DejaVuSansMono.ttf"]:
        try:
            f = ImageFont.truetype(fn, font_size)
            font_file = fn
            break
        except Exception:
            continue
    if f is None:
        f = ImageFont.load_default()
    
    d = ImageDraw.Draw(Image.new("RGB", (1, 1)))
    try:
        cw = int(d.textlength("M", font=f))
    except AttributeError:
        b = d.textbbox((0, 0), "M", font=f)
        cw = b[2] - b[0]
    try:
        asc, desc = f.getmetrics()
        ch = asc + desc
    except AttributeError:
        b = d.textbbox((0, 0), "M", font=f)
        ch = b[3] - b[1] + 2
    cw, ch = max(cw, 8), max(ch, 16)
    
    lines = ascii_content.splitlines() if isinstance(ascii_content, str) else []
    while lines and not lines[-1]:
        lines.pop()
    mr = len(lines) if lines else 1
    mc = max((len(l) for l in lines), default=1) if lines else 1
    data_to_render = lines
        
    p = 16
    iw, ih = mc * cw + (p * 2), mr * ch + (p * 2)
    img = Image.new("RGB", (iw, ih), color=bg_color)
    dr = ImageDraw.Draw(img)
    for y, line in enumerate(data_to_render):
        dr.text((p, p + y * ch), line, font=f, fill=text_color)
            
    img.save(output_path)
