import time
import numpy as np
import cv2
import moderngl
from PIL import Image

from core import (
    ASCII_CHARS_BLACK_BG, ASCII_CHARS_WHITE_BG, ASCII_CHARS_COLOR_BLOCKY,
    VERTEX_SHADER_PASS1, FRAGMENT_SHADER_PASS1, VERTEX_SHADER_PASS2, FRAGMENT_SHADER_PASS2,
    generate_glyph_atlas_image, hex_to_rgb_float
)


class GPUAsciiVideoPlayer:
    def __init__(
        self,
        video_path,
        width_provider_fn,
        style_provider_fn=None,
        color_mode_provider_fn=None,
        transparency_provider_fn=None,
        transparent_target="black",
        color_mode="Color",
        fullcolor_style="Blocky",
        theme_bg_color="#0F111A",
        audio_player=None,
        update_ui_cb=None,
        update_time_cb=None
    ):
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

    def _get_active_ascii_chars(self, style, color_mode, transparency):
        if color_mode == "Color":
            if str(style).lower() == "blocky":
                return ASCII_CHARS_COLOR_BLOCKY
            else:
                return ASCII_CHARS_WHITE_BG if transparency == "white" else ASCII_CHARS_BLACK_BG
        else:
            return ASCII_CHARS_WHITE_BG if transparency == "white" else ASCII_CHARS_BLACK_BG

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

        ascii_chars = self._get_active_ascii_chars(current_style, current_color_mode, current_transparency)
        atlas_img = generate_glyph_atlas_image(ascii_chars, self.char_w, self.char_h)
        num_chars = len(ascii_chars)

        atlas_tex = ctx.texture((self.char_w * num_chars, self.char_h), 1, atlas_img.tobytes())
        atlas_tex.filter = (moderngl.NEAREST, moderngl.NEAREST)
        atlas_tex.repeat_x = False
        atlas_tex.repeat_y = False
        atlas_tex.use(location=1)

        prog1['u_atlas'].value = 1
        prog1['u_num_chars'].value = num_chars
        prog1['u_color_mode'].value = 1 if current_color_mode == "Color" else 0
        prog1['u_bg_color'].value = hex_to_rgb_float(self.theme_bg_color)
        prog1['u_text_color'].value = (226 / 255.0, 232 / 255.0, 240 / 255.0)

        current_grid_cols = -1
        current_ui_w, current_ui_h = -1, -1
        fbo1, fbo2, render_tex, downsample_tex = None, None, None, None
        frame_tex = None

        if self.audio_player:
            self.audio_player.play(0.0)

        start_time = time.perf_counter()
        current_frame_idx = 0

        try:
            while is_playing_flag_fn() and cap.isOpened():
                if self.seek_target_sec is not None:
                    target_sec = max(0.0, min(self.seek_target_sec, total_duration))
                    self.seek_target_sec = None

                    target_frame_idx = int(target_sec * fps)
                    cap.set(cv2.CAP_PROP_POS_FRAMES, target_frame_idx)

                    ret, frame = cap.read()
                    if not ret:
                        break

                    current_frame_idx = int(cap.get(cv2.CAP_PROP_POS_FRAMES))
                    actual_sec = current_frame_idx / fps

                    start_time = time.perf_counter() - actual_sec
                    if self.audio_player:
                        self.audio_player.seek(actual_sec)

                elif is_paused_flag_fn():
                    time.sleep(0.03)
                    start_time = time.perf_counter() - (current_frame_idx / fps)
                    continue
                else:
                    if self.audio_player and self.audio_player.has_audio:
                        audio_pos = self.audio_player.get_pos()
                        master_time = audio_pos if audio_pos >= 0 else (time.perf_counter() - start_time)
                    else:
                        master_time = time.perf_counter() - start_time

                    if self.update_time_cb:
                        self.update_time_cb(master_time, total_duration)

                    target_frame_idx = int(master_time * fps)

                    if current_frame_idx < target_frame_idx - 1:
                        diff = target_frame_idx - current_frame_idx
                        if diff <= 15:
                            for _ in range(diff - 1):
                                if not cap.grab():
                                    break
                                current_frame_idx += 1
                        else:
                            start_time = time.perf_counter() - (current_frame_idx / fps)

                    expected_frame_time = current_frame_idx / fps
                    time_diff = expected_frame_time - master_time
                    if time_diff > 0.005:
                        time.sleep(min(time_diff, 0.03))

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

                    ascii_chars = self._get_active_ascii_chars(current_style, current_color_mode, current_transparency)
                    atlas_img = generate_glyph_atlas_image(ascii_chars, self.char_w, self.char_h)
                    num_chars = len(ascii_chars)

                    if atlas_tex:
                        atlas_tex.release()
                    atlas_tex = ctx.texture((self.char_w * num_chars, self.char_h), 1, atlas_img.tobytes())
                    atlas_tex.filter = (moderngl.NEAREST, moderngl.NEAREST)
                    atlas_tex.repeat_x = False
                    atlas_tex.repeat_y = False
                    atlas_tex.use(location=1)

                    prog1['u_num_chars'].value = num_chars
                    prog1['u_color_mode'].value = 1 if current_color_mode == "Color" else 0

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
                    render_tex.filter = (moderngl.LINEAR_MIPMAP_LINEAR, moderngl.LINEAR)
                    render_tex.repeat_x = False
                    render_tex.repeat_y = False
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

                render_tex.build_mipmaps()

                fbo2.use()
                ctx.clear(0.0, 0.0, 0.0, 1.0)
                render_tex.use(location=0)
                prog2['u_tex'].value = 0
                vao2.render(moderngl.TRIANGLE_STRIP)

                raw_bytes = fbo2.read(components=3)
                pil_img = Image.frombytes('RGB', (ui_w, ui_h), raw_bytes)

                if self.update_ui_cb:
                    self.update_ui_cb(pil_img)

        finally:
            cap.release()
            if frame_tex: frame_tex.release()
            if atlas_tex: atlas_tex.release()
            if render_tex: render_tex.release()
            if downsample_tex: downsample_tex.release()
            if fbo1: fbo1.release()
            if fbo2: fbo2.release()
            ctx.release()

            if self.audio_player:
                self.audio_player.stop()
