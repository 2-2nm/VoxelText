import time
import numpy as np
import cv2
import moderngl
from PIL import Image, ImageDraw, ImageFont

from core import (
    ASCII_CHARS_BLACK_BG, ASCII_CHARS_WHITE_BG, ASCII_CHARS_COLOR_BLOCKY,
    ASCII_CHARS_COLOR_PURE, MAX_WORKERS
)

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


class GPUAsciiVideoPlayer:
    def __init__(self, video_path, width_provider_fn, style_provider_fn=None, color_mode_provider_fn=None, transparency_provider_fn=None, transparent_target="black", color_mode="Color", fullcolor_style="Blocky", theme_bg_color="#0F111A", audio_player=None, update_ui_cb=None, update_time_cb=None):
        self.video_path = video_path
        self.width_provider_fn = width_provider_fn
        self.style_provider_fn = style_provider_fn
        self.color_mode_provider_fn = color_mode_provider_fn
        self.transparency_provider_fn = transparency_provider_fn
        self.transparent_target = transparent_target
        self.color_mode = color_mode
        self.fullcolor_style = fullcolor_style
        self.theme_bg_color = theme_bg_color
        self.audio_player = audio_player
        self.update_ui_cb = update_ui_cb
        self.update_time_cb = update_time_cb
        self.char_w = 7
        self.char_h = 12
        self.seek_target_sec = None

    def seek(self, target_sec):
        self.seek_target_sec = target_sec

    def run(self, is_playing_flag_fn, is_paused_flag_fn):
        cap = cv2.VideoCapture(self.video_path)
        if not cap.isOpened():
            return

        orig_w = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
        orig_h = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
        fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
        total_frames = cap.get(cv2.CAP_PROP_FRAME_COUNT)
        total_duration = (total_frames / fps) if (total_frames > 0 and fps > 0) else 0.0
        font_aspect = self.char_w / self.char_h

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

        current_style = self.style_provider_fn() if self.style_provider_fn else self.fullcolor_style
        current_color_mode = self.color_mode_provider_fn() if self.color_mode_provider_fn else self.color_mode
        current_transparency = self.transparency_provider_fn() if self.transparency_provider_fn else self.transparent_target

        if current_color_mode == "Color":
            ascii_chars = ASCII_CHARS_COLOR_BLOCKY if str(current_style).lower() == "blocky" else ASCII_CHARS_COLOR_PURE
        else:
            ascii_chars = ASCII_CHARS_BLACK_BG if current_transparency == "white" else ASCII_CHARS_WHITE_BG

        atlas_img = generate_glyph_atlas_image(ascii_chars, self.char_w, self.char_h)
        num_chars = len(ascii_chars)

        atlas_tex = ctx.texture((self.char_w * num_chars, self.char_h), 1, atlas_img.tobytes())
        atlas_tex.filter = (moderngl.NEAREST, moderngl.NEAREST)
        atlas_tex.use(location=1)

        prog1['u_atlas'].value = 1
        prog1['u_num_chars'].value = num_chars
        prog1['u_color_mode'].value = 1 if current_color_mode == "Color" else 0

        if current_transparency == "black":
            prog1['u_bg_color'].value = hex_to_rgb_float(self.theme_bg_color)
            prog1['u_text_color'].value = (226 / 255.0, 232 / 255.0, 240 / 255.0)
        else:
            prog1['u_bg_color'].value = (226 / 255.0, 232 / 255.0, 240 / 255.0)
            prog1['u_text_color'].value = (15 / 255.0, 11 / 255.0, 9 / 255.0)

        current_grid_cols = -1
        current_ui_w, current_ui_h = -1, -1
        fbo1, fbo2, render_tex, downsample_tex = None, None, None, None
        frame_tex = None

        if self.audio_player:
            self.audio_player.play(0.0)

        start_time = time.perf_counter()
        current_frame_idx = 0

        while is_playing_flag_fn() and cap.isOpened():
            if self.seek_target_sec is not None:
                target_sec = max(0.0, min(self.seek_target_sec, total_duration))
                self.seek_target_sec = None
                
                target_frame_idx = int(target_sec * fps)
                cap.set(cv2.CAP_PROP_POS_FRAMES, target_frame_idx)
                current_frame_idx = target_frame_idx
                
                start_time = time.perf_counter() - target_sec
                if self.audio_player:
                    self.audio_player.seek(target_sec)

            if is_paused_flag_fn():
                time.sleep(0.03)
                start_time = time.perf_counter() - (current_frame_idx / fps)
                continue

            if self.audio_player and self.audio_player.has_audio:
                audio_pos = self.audio_player.get_pos()
                master_time = audio_pos if audio_pos >= 0 else (time.perf_counter() - start_time)
            else:
                master_time = time.perf_counter() - start_time

            if self.update_time_cb:
                self.update_time_cb(master_time, total_duration)

            target_frame_idx = int(master_time * fps)

            if current_frame_idx < target_frame_idx - 1:
                if target_frame_idx - current_frame_idx > 10:
                    cap.set(cv2.CAP_PROP_POS_FRAMES, target_frame_idx)
                    current_frame_idx = target_frame_idx
                else:
                    while current_frame_idx < target_frame_idx - 1 and is_playing_flag_fn():
                        ret_grab = cap.grab()
                        if not ret_grab:
                            break
                        current_frame_idx += 1

            expected_frame_time = current_frame_idx / fps
            time_diff = expected_frame_time - master_time
            if time_diff > 0.005:
                time.sleep(min(time_diff, 0.05))

            ret, frame = cap.read()
            if not ret:
                break
            current_frame_idx += 1

            new_style = self.style_provider_fn() if self.style_provider_fn else self.fullcolor_style
            new_color_mode = self.color_mode_provider_fn() if self.color_mode_provider_fn else self.color_mode
            new_transparency = self.transparency_provider_fn() if self.transparency_provider_fn else self.transparent_target

            if new_style != current_style or new_color_mode != current_color_mode or new_transparency != current_transparency:
                current_style = new_style
                current_color_mode = new_color_mode
                current_transparency = new_transparency

                if current_color_mode == "Color":
                    ascii_chars = ASCII_CHARS_COLOR_BLOCKY if str(current_style).lower() == "blocky" else ASCII_CHARS_COLOR_PURE
                else:
                    ascii_chars = ASCII_CHARS_BLACK_BG if current_transparency == "white" else ASCII_CHARS_WHITE_BG

                atlas_img = generate_glyph_atlas_image(ascii_chars, self.char_w, self.char_h)
                num_chars = len(ascii_chars)

                if atlas_tex:
                    atlas_tex.release()
                atlas_tex = ctx.texture((self.char_w * num_chars, self.char_h), 1, atlas_img.tobytes())
                atlas_tex.filter = (moderngl.NEAREST, moderngl.NEAREST)
                atlas_tex.use(location=1)

                prog1['u_num_chars'].value = num_chars
                prog1['u_color_mode'].value = 1 if current_color_mode == "Color" else 0

                if current_transparency == "black":
                    prog1['u_bg_color'].value = hex_to_rgb_float(self.theme_bg_color)
                    prog1['u_text_color'].value = (226 / 255.0, 232 / 255.0, 240 / 255.0)
                else:
                    prog1['u_bg_color'].value = (226 / 255.0, 232 / 255.0, 240 / 255.0)
                    prog1['u_text_color'].value = (15 / 255.0, 11 / 255.0, 9 / 255.0)

            target_cols, max_ui_w, max_ui_h = self.width_provider_fn()
            if target_cols != current_grid_cols or max_ui_w != current_ui_w or max_ui_h != current_ui_h:
                current_grid_cols = target_cols
                current_ui_w, current_ui_h = max_ui_w, max_ui_h

                aspect_factor = (orig_h / orig_w) * font_aspect
                max_cols_w = max_tex_size // self.char_w
                max_rows_h = max_tex_size // self.char_h

                max_cols_from_h = int(max_rows_h / aspect_factor) if aspect_factor > 0 else max_cols_w
                effective_cols = max(10, min(current_grid_cols, max_cols_w, max_cols_from_h))

                grid_rows = max(1, int(round(aspect_factor * effective_cols)))

                win_w = effective_cols * self.char_w
                win_h = grid_rows * self.char_h

                sf = min(max_ui_w / float(win_w), max_ui_h / float(win_h))
                ui_w = max(1, int(round(win_w * sf)))
                ui_h = max(1, int(round(win_h * sf)))

                if fbo1: fbo1.release()
                if fbo2: fbo2.release()
                if render_tex: render_tex.release()
                if downsample_tex: downsample_tex.release()

                render_tex = ctx.texture((win_w, win_h), 3)
                render_tex.filter = (moderngl.LINEAR, moderngl.LINEAR)
                fbo1 = ctx.framebuffer(color_attachments=[render_tex])

                downsample_tex = ctx.texture((ui_w, ui_h), 3)
                fbo2 = ctx.framebuffer(color_attachments=[downsample_tex])

                prog1['u_grid_size'].value = (float(effective_cols), float(grid_rows))

            frame_rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
            fh, fw = frame_rgb.shape[:2]

            if frame_tex is None:
                frame_tex = ctx.texture((fw, fh), 3, frame_rgb.tobytes())
                frame_tex.filter = (moderngl.LINEAR, moderngl.LINEAR)
            elif frame_tex.size != (fw, fh):
                frame_tex.release()
                frame_tex = ctx.texture((fw, fh), 3, frame_rgb.tobytes())
                frame_tex.filter = (moderngl.LINEAR, moderngl.LINEAR)
            else:
                frame_tex.write(frame_rgb.tobytes())

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

            if self.update_ui_cb:
                self.update_ui_cb(pil_img)

        cap.release()
        ctx.release()
        if self.audio_player:
            self.audio_player.stop()


def convert_video_frame_to_ascii(frame_rgba, new_width=80, transparent_target="white", color_mode="White", max_preview_width=1200):
    try:
        import cv2
        cv2.setNumThreads(MAX_WORKERS)
    except ImportError:
        raise Exception("OpenCV (cv2) is required.")

    h, w = frame_rgba.shape[:2]
    char_w, char_h = 7, 12
    font_aspect = char_w / char_h

    new_h = max(1, int(round((h / w) * new_width * font_aspect)))
    resized = cv2.resize(frame_rgba, (new_width, new_h), interpolation=cv2.INTER_AREA)

    alpha = resized[:, :, 3]
    gray = cv2.cvtColor(resized, cv2.COLOR_RGBA2GRAY)

    if color_mode == "Color":
        ascii_chars = ASCII_CHARS_COLOR_BLOCKY
    else:
        ascii_chars = ASCII_CHARS_BLACK_BG if transparent_target == "white" else ASCII_CHARS_WHITE_BG

    nc = len(ascii_chars)
    anp = np.array(list(ascii_chars))
    idx = np.clip((gray.astype(np.uint16) * nc) // 256, 0, nc - 1)

    cm = anp[idx]
    cm[alpha < 128] = " "
    return "\n".join("".join(row) for row in cm)
