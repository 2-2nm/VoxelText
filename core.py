import os, numpy as np
from PIL import Image, ImageDraw, ImageFont
from concurrent.futures import ProcessPoolExecutor
import moderngl

MAX_WORKERS = os.cpu_count() or 8
ASCII_CHARS_BLACK_BG = ["@", "#", "S", "%", "?", "*", "+", ";", ":", ",", ".", " "]
ASCII_CHARS_WHITE_BG = [" ", ".", ",", ":", ";", "+", "*", "?", "%", "S", "#", "@"]
ASCII_CHARS_COLOR_BLACK_BG = ["█"]
ASCII_CHARS_COLOR_BLOCKY = ["█"]
ASCII_CHARS_COLOR_PURE = [" ", ".", ",", ":", ";", "+", "*", "?", "%", "S", "#", "@"]

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
uniform int u_num_chars;
uniform int u_color_mode;
uniform vec3 u_text_color;
uniform vec3 u_bg_color;

in vec2 v_texcoord;
out vec4 fragColor;

void main() {
    vec2 cell_idx = floor(v_texcoord * u_grid_size);
    vec2 cell_uv = fract(v_texcoord * u_grid_size);
    
    vec2 frame_uv = (cell_idx + vec2(0.5)) / u_grid_size;
    vec4 frame_pixel = texture(u_frame, frame_uv);
    
    if (u_color_mode == 1) {
        frame_pixel.r = floor(frame_pixel.r * 31.0 + 0.5) / 31.0;
        frame_pixel.g = floor(frame_pixel.g * 63.0 + 0.5) / 63.0;
        frame_pixel.b = floor(frame_pixel.b * 31.0 + 0.5) / 31.0;
    }
    
    float brightness = dot(frame_pixel.rgb, vec3(0.299, 0.587, 0.114));
    int char_idx = clamp(int(brightness * float(u_num_chars)), 0, u_num_chars - 1);
    
    float u_char = (float(char_idx) + cell_uv.x) / float(u_num_chars);
    float v_char = cell_uv.y;
    
    float mask = texture(u_atlas, vec2(u_char, v_char)).r;
    
    vec3 fg_color = (u_color_mode == 1) ? frame_pixel.rgb : u_text_color;
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
        if ch in ["█"]:
            draw.rectangle([x_offset, 0, x_offset + char_w, char_h], fill=255)
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


def hex_to_rgb_float(hex_str):
    hex_str = hex_str.lstrip('#')
    return tuple(int(hex_str[i:i+2], 16) / 255.0 for i in (0, 2, 4))


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

    if color_mode == "Color":
        ascii_chars = ASCII_CHARS_COLOR_BLOCKY if str(fullcolor_style).lower() == "blocky" else ASCII_CHARS_COLOR_PURE
    else:
        ascii_chars = ASCII_CHARS_BLACK_BG if transparent_target == "white" else ASCII_CHARS_WHITE_BG

    atlas_img = generate_glyph_atlas_image(ascii_chars, char_w, char_h)
    num_chars = len(ascii_chars)

    atlas_tex = ctx.texture((char_w * num_chars, char_h), 1, atlas_img.tobytes())
    atlas_tex.filter = (moderngl.NEAREST, moderngl.NEAREST)
    atlas_tex.use(location=1)

    prog1['u_atlas'].value = 1
    prog1['u_num_chars'].value = num_chars
    prog1['u_color_mode'].value = 1 if color_mode == "Color" else 0
    prog1['u_text_color'].value = hex_to_rgb_float(palette_hex)
    prog1['u_bg_color'].value = hex_to_rgb_float(theme_bg_color)

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
    render_tex.filter = (moderngl.LINEAR, moderngl.LINEAR)
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


def resize_image_aspect_ratio(image, new_width=55, font_aspect_ratio=0.50):
    w, h = image.size
    return image.resize((new_width, max(1, int((h / w) * new_width * font_aspect_ratio))), Image.Resampling.LANCZOS)


def _process_color_chunk_process(task_data):
    y_range, width, r_sub, g_sub, b_sub, a_sub, mapped_chars_sub = task_data
    A, G = [], []
    for idx, y in enumerate(y_range):
        al, gl = [], []
        ar, rr, gr, br, cr = a_sub[idx], r_sub[idx], g_sub[idx], b_sub[idx], mapped_chars_sub[idx]
        for x in range(width):
            if ar[x] < 128:
                al.append(" ")
                gl.append((" ", "#121212"))
            else:
                rv, gv, bv, ch = rr[x], gr[x], br[x], cr[x]
                al.append(f"\033[38;2;{rv};{gv};{bv}m{ch}\033[0m")
                gl.append((ch, f"#{rv:02x}{gv:02x}{bv:02x}"))
        A.append((y, "".join(al)))
        G.append((y, gl))
    return A, G


def convert_image_to_fullcolor(image_path, size_txt=55, num_workers=None):
    if num_workers is None:
        num_workers = MAX_WORKERS
    try:
        img = Image.open(image_path)
    except Exception as e:
        raise Exception(f"Failed: {e}")
        
    r_img = resize_image_aspect_ratio(img, new_width=size_txt, font_aspect_ratio=0.50)
    arr = np.array(r_img.convert("RGBA"))
    h, w, _ = arr.shape
    r, g, b, a = arr[:, :, 0], arr[:, :, 1], arr[:, :, 2], arr[:, :, 3]

    r = r & 0xF8
    g = g & 0xFC
    b = b & 0xF8

    gray = (0.299 * r + 0.587 * g + 0.114 * b).astype(np.uint8)
    ac = ASCII_CHARS_COLOR_BLACK_BG
    nc = len(ac)
    anp = np.array(list(ac))
    ci = np.clip((gray.astype(np.uint16) * nc) // 256, 0, nc - 1)
    mc = anp[ci]
    cs = max(1, h // num_workers)
    tasks = []
    
    for i in range(num_workers):
        sy = i * cs
        ey = h if i == num_workers - 1 else (i + 1) * cs
        if sy < h:
            tasks.append((list(range(sy, ey)), w, r[sy:ey], g[sy:ey], b[sy:ey], a[sy:ey], mc[sy:ey]))
            
    aa, ag = [], []
    with ProcessPoolExecutor(max_workers=num_workers) as ex:
        res = ex.map(_process_color_chunk_process, tasks)
        for anc, gnc in res:
            aa.extend(anc)
            ag.extend(gnc)
            
    aa.sort(key=lambda x: x[0])
    ag.sort(key=lambda x: x[0])
    return "\n".join([l for _, l in aa]), [l for _, l in ag]


def _render_chunk_worker(task_data):
    y_start, lines, bg_color, cw, ch, font_file, font_size, text_color = task_data
    mr = len(lines)
    if mr == 0:
        return y_start, None
    mc = max((len(l) for l in lines), default=1)
    
    img = Image.new("RGB", (mc * cw, mr * ch), color=bg_color)
    dr = ImageDraw.Draw(img)
    
    try:
        f = ImageFont.truetype(font_file, font_size) if font_file else ImageFont.load_default()
    except Exception:
        f = ImageFont.load_default()
    
    if lines and isinstance(lines[0], list): 
        for y, line in enumerate(lines):
            py = y * ch
            x = 0
            n = len(line)
            while x < n:
                char, col = line[x]
                sx = x
                if char in ["█", "⬛"]:
                    while x < n and line[x][0] in ["█", "⬛"] and line[x][1] == col:
                        x += 1
                    dr.rectangle([sx * cw, py, x * cw, py + ch], fill=col)
                else:
                    rc = [char]
                    x += 1
                    while x < n and line[x][1] == col and line[x][0] not in ["█", "⬛"]:
                        rc.append(line[x][0])
                        x += 1
                    dr.text((sx * cw, py), "".join(rc), font=f, fill=col)
    else:
        for y, line in enumerate(lines):
            dr.text((0, y * ch), line, font=f, fill=text_color)
            
    return y_start, img


def render_gui_preview_to_image(gui_preview_data, bg_color="#0F111A"):
    if not gui_preview_data:
        return None
    font_file, font_size = None, 12
    f = None
    for fn in ["consola.ttf", "Consolas.ttf", "cour.ttf", "Courier New.ttf"]:
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
    cw, ch = max(cw, 7), max(ch, 14)
    
    mr, mc = len(gui_preview_data), max((len(l) for l in gui_preview_data), default=1)
    p = 10
    iw, ih = mc * cw + (p * 2), mr * ch + (p * 2)
    img = Image.new("RGB", (iw, ih), color=bg_color)
    
    num_workers = MAX_WORKERS
    cs = max(1, mr // num_workers)
    tasks = []
    for i in range(num_workers):
        sy = i * cs
        ey = mr if i == num_workers - 1 else (i + 1) * cs
        if sy < mr:
            tasks.append((sy, gui_preview_data[sy:ey], bg_color, cw, ch, font_file, font_size, None))
        
    with ProcessPoolExecutor(max_workers=num_workers) as ex:
        for sy, chunk_img in ex.map(_render_chunk_worker, tasks):
            if chunk_img:
                img.paste(chunk_img, (p, p + sy * ch))
            
    return img


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
    ac = ASCII_CHARS_BLACK_BG if transparent_target == "white" else ASCII_CHARS_WHITE_BG
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
    
    if gui_preview_data: 
        mr, mc = len(gui_preview_data), max((len(l) for l in gui_preview_data), default=1)
        data_to_render = gui_preview_data
    else:
        lines = ascii_content.splitlines() if isinstance(ascii_content, str) else []
        while lines and not lines[-1]:
            lines.pop()
        mr = len(lines) if lines else 1
        mc = max((len(l) for l in lines), default=1) if lines else 1
        data_to_render = lines
        
    p = 16
    iw, ih = mc * cw + (p * 2), mr * ch + (p * 2)
    img = Image.new("RGB", (iw, ih), color=bg_color)
    
    num_workers = MAX_WORKERS
    cs = max(1, mr // num_workers)
    tasks = []
    for i in range(num_workers):
        sy = i * cs
        ey = mr if i == num_workers - 1 else (i + 1) * cs
        if sy < mr:
            tasks.append((sy, data_to_render[sy:ey], bg_color, cw, ch, font_file, font_size, text_color))
        
    with ProcessPoolExecutor(max_workers=num_workers) as ex:
        for sy, chunk_img in ex.map(_render_chunk_worker, tasks):
            if chunk_img:
                img.paste(chunk_img, (p, p + sy * ch))
            
    img.save(output_path)


def get_resource_path(relative_path):
    return os.path.join(getattr(os.sys, "_MEIPASS", os.path.abspath(".")), relative_path)
