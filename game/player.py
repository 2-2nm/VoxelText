import time
import numpy as np
import moderngl
from PIL import Image

from core.ascii import (
    VERTEX_SHADER_PASS1, FRAGMENT_SHADER_PASS1, VERTEX_SHADER_PASS2, FRAGMENT_SHADER_PASS2,
    generate_glyph_atlas_image, get_ascii_chars, get_charset, set_glyph_coverage
)
from core.utils import hex_to_rgb_float
from game.capture import FrameSource

class GPUAsciiGamePlayer:
    def __init__(
        self,
        hwnd,
        width_provider_fn,
        style_provider_fn=None,
        color_mode_provider_fn=None,
        transparency_provider_fn=None,
        transparent_target="black",
        color_mode="Color",
        fullcolor_style="Blocky",
        theme_bg_color="#0F111A",
        update_ui_cb=None,
        update_fps_cb=None,
        log_cb=None,
        tone=1.0,
        color_boost=0.6
    ):
        self.hwnd = hwnd
        self.width_provider_fn = width_provider_fn
        self.style_provider_fn = style_provider_fn
        self.color_mode_provider_fn = color_mode_provider_fn
        self.transparency_provider_fn = transparency_provider_fn
        self.transparent_target = transparent_target
        self.color_mode = color_mode
        self.fullcolor_style = fullcolor_style
        self.theme_bg_color = theme_bg_color
        self.update_ui_cb = update_ui_cb
        self.update_fps_cb = update_fps_cb
        self.log_cb = log_cb
        self.tone = tone
        self.color_boost = color_boost
        self.char_w = 7
        self.char_h = 12
        self.source = FrameSource(hwnd=self.hwnd, log_cb=log_cb)

    def _get_active_ascii_chars(self, style, color_mode, transparency):
        return get_ascii_chars(color_mode, style, transparency)

    def _color_boost_for(self, style, color_mode):
        if color_mode == "Color" and str(style).lower() == "blocky":
            return 0.0
        return self.color_boost

    def run(self, is_playing_flag_fn):
        if not self.source.is_valid():
            return

        ctx = moderngl.create_standalone_context()
        if self.log_cb:
            self.log_cb(f"Game stream GPU: {ctx.info.get('GL_RENDERER', '?')}", "info")
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

        current_charset = get_charset()
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
        set_glyph_coverage(prog1, atlas_img, num_chars, self.char_w)
        prog1['u_color_mode'].value = 1 if current_color_mode == "Color" else 0
        prog1['u_bg_color'].value = hex_to_rgb_float(self.theme_bg_color)
        prog1['u_text_color'].value = (226 / 255.0, 232 / 255.0, 240 / 255.0)
        prog1['u_tone'].value = float(self.tone)
        prog1['u_color_boost'].value = self._color_boost_for(current_style, current_color_mode)

        current_grid_cols = -1
        current_frame_aspect = None
        current_ui_w, current_ui_h = -1, -1
        fbo1, fbo2, render_tex, downsample_tex = None, None, None, None
        frame_tex = None

        pbo = [None, None]
        pbo_cur = 0
        pbo_pending = False
        last_frame = None
        last_id = 0
        dirty = False
        ui_w, ui_h = 1, 1

        def emit_from(buf):
            raw = buf.read()
            img = Image.frombytes('RGB', (ui_w, ui_h), raw)
            if self.update_ui_cb:
                self.update_ui_cb(img)

        self.source.start()
        if self.log_cb:
            self.log_cb(f"Game capture backend: {self.source.backend}", "info")

        frame_count = 0
        last_time = time.perf_counter()

        perf_t = time.perf_counter()
        perf_wait = perf_work = 0.0
        perf_n = 0
        perf_src0 = 0
        effective_cols = grid_rows = win_w = win_h = 0
        font_aspect = self.char_w / self.char_h

        try:
            while is_playing_flag_fn():
                if not self.source.is_valid():
                    time.sleep(0.05)
                    continue

                t_wait0 = time.perf_counter()
                frame_rgb, fid = self.source.wait_frame(last_id, 0.05)
                t_got = time.perf_counter()
                perf_wait += t_got - t_wait0
                is_new = frame_rgb is not None
                if is_new:
                    last_frame, last_id = frame_rgb, fid
                    dirty = True
                elif last_frame is None:
                    continue
                else:
                    frame_rgb = last_frame

                fh, fw = frame_rgb.shape[:2]
                if fh <= 0 or fw <= 0:
                    continue

                if not dirty and pbo_pending:
                    emit_from(pbo[pbo_cur ^ 1])
                    pbo_pending = False

                if is_new:
                    frame_count += 1
                    now = time.perf_counter()
                    if now - last_time >= 1.0:
                        current_fps = frame_count / (now - last_time)
                        if self.update_fps_cb:
                            self.update_fps_cb(current_fps)
                        frame_count = 0
                        last_time = now

                new_style = self.style_provider_fn() if self.style_provider_fn else self.fullcolor_style
                new_color_mode = self.color_mode_provider_fn() if self.color_mode_provider_fn else self.color_mode
                new_transparency = self.transparency_provider_fn() if self.transparency_provider_fn else self.transparent_target

                new_charset = get_charset()
                if new_style != current_style or new_color_mode != current_color_mode or new_transparency != current_transparency or new_charset != current_charset:
                    current_style = new_style
                    current_color_mode = new_color_mode
                    current_transparency = new_transparency
                    current_charset = new_charset

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
                    set_glyph_coverage(prog1, atlas_img, num_chars, self.char_w)
                    prog1['u_color_mode'].value = 1 if current_color_mode == "Color" else 0
                    prog1['u_color_boost'].value = self._color_boost_for(current_style, current_color_mode)
                    dirty = True

                target_cols, max_ui_w, max_ui_h = self.width_provider_fn()
                frame_aspect = fh / float(fw)
                aspect_changed = current_frame_aspect is None or abs(frame_aspect / current_frame_aspect - 1.0) > 0.04
                if target_cols != current_grid_cols or max_ui_w != current_ui_w or max_ui_h != current_ui_h or aspect_changed:
                    current_grid_cols = target_cols
                    current_ui_w, current_ui_h = max_ui_w, max_ui_h
                    current_frame_aspect = frame_aspect

                    aspect_factor = frame_aspect * font_aspect
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
                    if sf < 0.5:
                        win_w = max(ui_w * 2, effective_cols)
                        win_h = max(ui_h * 2, grid_rows)

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
                    prog1['u_cell_px'].value = (win_w / float(effective_cols), win_h / float(grid_rows))

                    on_screen_px = ui_w / float(effective_cols)
                    if on_screen_px < 4.0 and self.log_cb:
                        self.log_cb(
                            f"Width {effective_cols} on a {ui_w}px preview = {on_screen_px:.1f}px per character: "
                            f"glyphs are not legible below ~4px. Use <= {max(10, int(ui_w // 4))} columns or enlarge the preview.",
                            "warn"
                        )

                    for b in pbo:
                        if b: b.release()
                    pbo = [ctx.buffer(reserve=ui_w * ui_h * 3) for _ in range(2)]
                    pbo_cur = 0
                    pbo_pending = False
                    dirty = True

                if not dirty:
                    continue
                dirty = False

                if frame_tex is None or frame_tex.size != (fw, fh):
                    if frame_tex:
                        frame_tex.release()
                    frame_tex = ctx.texture((fw, fh), 3, frame_rgb)
                    frame_tex.filter = (moderngl.LINEAR_MIPMAP_LINEAR, moderngl.LINEAR)
                    frame_tex.repeat_x = False
                    frame_tex.repeat_y = False
                    prog1['u_frame_size'].value = (float(fw), float(fh))
                else:
                    frame_tex.write(frame_rgb)
                frame_tex.build_mipmaps()

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

                if is_new:
                    if pbo_pending:
                        emit_from(pbo[pbo_cur ^ 1])
                    fbo2.read_into(pbo[pbo_cur], components=3)
                    pbo_cur ^= 1
                    pbo_pending = True
                else:
                    fbo2.read_into(pbo[pbo_cur], components=3)
                    emit_from(pbo[pbo_cur])
                    pbo_pending = False

                perf_work += time.perf_counter() - t_got
                perf_n += 1
                perf_now = time.perf_counter()
                if perf_now - perf_t >= 5.0 and self.log_cb:
                    dt = perf_now - perf_t
                    src_total = self.source.total_frames
                    cb_avg, cb_max = self.source.pop_cb_stats()
                    self.log_cb(
                        f"[perf] capture {(src_total - perf_src0) / dt:.0f} fps | render {perf_n / dt:.0f} fps | "
                        f"idle-wait {1000 * perf_wait / max(perf_n, 1):.1f} ms | work {1000 * perf_work / max(perf_n, 1):.1f} ms | "
                        f"callback avg {cb_avg:.1f} / max {cb_max:.1f} ms | "
                        f"grid {effective_cols}x{grid_rows} -> {win_w}x{win_h}px",
                        "note"
                    )
                    perf_t, perf_wait, perf_work, perf_n, perf_src0 = perf_now, 0.0, 0.0, 0, src_total

        finally:
            self.source.stop()
            for b in pbo:
                if b: b.release()
            if frame_tex: frame_tex.release()
            if atlas_tex: atlas_tex.release()
            if render_tex: render_tex.release()
            if downsample_tex: downsample_tex.release()
            if fbo1: fbo1.release()
            if fbo2: fbo2.release()
            ctx.release()
