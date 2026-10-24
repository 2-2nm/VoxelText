import os
import subprocess
import time
import numpy as np
import cv2
import moderngl

from core.ascii import (
    VERTEX_SHADER_PASS1, FRAGMENT_SHADER_PASS1, generate_glyph_atlas_image, get_ascii_chars
)
from core.utils import hex_to_rgb_float


def get_ffmpeg_exe():
    try:
        import imageio_ffmpeg
        return imageio_ffmpeg.get_ffmpeg_exe()
    except ImportError:
        import shutil
        return shutil.which("ffmpeg")


def export_ascii_video(
    video_path,
    output_path,
    target_cols=85,
    color_mode="Color",
    fullcolor_style="Blocky",
    transparent_target="black",
    theme_bg_color="#0F111A",
    progress_cb=None,
    cancel_flag_fn=None
):
    if not os.path.exists(video_path):
        raise FileNotFoundError(f"Source video not found: {video_path}")

    cap = cv2.VideoCapture(video_path)
    if not cap.isOpened():
        raise Exception("Failed to open source video file.")

    orig_w = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    orig_h = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
    total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))

    char_w, char_h = 7, 12
    font_aspect = char_w / char_h
    aspect_factor = (orig_h / orig_w) * font_aspect

    ctx = moderngl.create_standalone_context()
    max_tex_size = ctx.info.get('GL_MAX_TEXTURE_SIZE', 8192)

    max_cols_w = max_tex_size // char_w
    max_rows_h = max_tex_size // char_h
    max_cols_from_h = int(max_rows_h / aspect_factor) if aspect_factor > 0 else max_cols_w

    effective_cols = max(10, min(target_cols, max_cols_w, max_cols_from_h))
    grid_rows = max(1, int(round(aspect_factor * effective_cols)))

    win_w = effective_cols * char_w
    win_h = grid_rows * char_h

    if win_w % 2 != 0:
        win_w += 1
    if win_h % 2 != 0:
        win_h += 1

    verts_pass1 = np.array([-1.0, -1.0, 0.0, 1.0, 1.0, -1.0, 1.0, 1.0, -1.0, 1.0, 0.0, 0.0, 1.0, 1.0, 1.0, 0.0], dtype='f4')
    prog1 = ctx.program(vertex_shader=VERTEX_SHADER_PASS1, fragment_shader=FRAGMENT_SHADER_PASS1)
    vbo1 = ctx.buffer(verts_pass1.tobytes())
    vao1 = ctx.vertex_array(prog1, [(vbo1, '2f 2f', 'in_vert', 'in_texcoord')])

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
    prog1['u_text_color'].value = (226 / 255.0, 232 / 255.0, 240 / 255.0)

    render_tex = ctx.texture((win_w, win_h), 3)
    render_tex.filter = (moderngl.LINEAR_MIPMAP_LINEAR, moderngl.LINEAR)
    render_tex.repeat_x = False
    render_tex.repeat_y = False
    fbo1 = ctx.framebuffer(color_attachments=[render_tex])
    prog1['u_grid_size'].value = (float(effective_cols), float(grid_rows))

    ffmpeg_exe = get_ffmpeg_exe()
    proc = None
    writer = None

    if ffmpeg_exe:
        cmd = [
            ffmpeg_exe, "-y",
            "-f", "rawvideo",
            "-vcodec", "rawvideo",
            "-s", f"{win_w}x{win_h}",
            "-pix_fmt", "rgb24",
            "-r", str(fps),
            "-i", "-",
            "-vn",
            "-i", video_path,
            "-map", "0:v:0",
            "-map", "1:a:0?",
            "-c:v", "libx264",
            "-preset", "medium",
            "-crf", "28",
            "-pix_fmt", "yuv420p",
            "-c:a", "aac",
            "-b:a", "128k",
            "-shortest",
            output_path
        ]
        startupinfo = None
        if os.name == 'nt':
            startupinfo = subprocess.STARTUPINFO()
            startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW

        proc = subprocess.Popen(
            cmd,
            stdin=subprocess.PIPE,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            startupinfo=startupinfo
        )
    else:
        fourcc = cv2.VideoWriter_fourcc(*'mp4v')
        writer = cv2.VideoWriter(output_path, fourcc, fps, (win_w, win_h))

    frame_tex = None
    current_frame = 0
    last_reported_time = time.time()

    try:
        while cap.isOpened():
            if cancel_flag_fn and cancel_flag_fn():
                break

            ret, frame = cap.read()
            if not ret:
                break
            current_frame += 1

            frame_rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
            fh, fw = frame_rgb.shape[:2]

            if frame_tex is None or frame_tex.size != (fw, fh):
                if frame_tex:
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

            raw_bytes = fbo1.read(components=3)

            if proc:
                proc.stdin.write(raw_bytes)
            elif writer:
                img_arr = np.frombuffer(raw_bytes, dtype=np.uint8).reshape((win_h, win_w, 3))
                bgr_arr = cv2.cvtColor(img_arr, cv2.COLOR_RGB2BGR)
                writer.write(bgr_arr)

            now = time.time()
            if progress_cb and (now - last_reported_time >= 0.25 or current_frame == total_frames):
                last_reported_time = now
                progress_cb(current_frame, total_frames, f"Rendered frame {current_frame}/{total_frames}")

    finally:
        cap.release()
        if frame_tex:
            frame_tex.release()
        render_tex.release()
        atlas_tex.release()
        fbo1.release()
        ctx.release()

        if proc:
            proc.stdin.close()
            proc.wait()
            if proc.returncode != 0:
                raise Exception("FFmpeg export failed.")
        elif writer:
            writer.release()