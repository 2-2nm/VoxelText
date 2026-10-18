import os
import tempfile
import subprocess
import uuid
import time

class AudioPlayer:
    def __init__(self):
        self.audio_file = None
        self.is_initialized = False
        self.has_audio = False
        self.init_error = None
        
        self.start_offset = 0.0
        self.start_ticks = 0.0
        self.is_paused = False
        self.pause_time = 0.0
        
        self.is_muted = False
        self.volume = 1.0
        
        self._init_mixer()

    def _init_mixer(self):
        try:
            import pygame
            if not pygame.mixer.get_init():
                pygame.mixer.init(frequency=44100, size=-16, channels=2, buffer=512)
            self.is_initialized = True
        except ImportError:
            self.is_initialized = False
            self.init_error = "nah"
        except Exception as e:
            self.is_initialized = False
            self.init_error = f"dunno: {e}"

    def set_volume(self, vol):
        self.volume = max(0.0, min(1.0, vol))
        if self.is_initialized and self.has_audio and not self.is_muted:
            try:
                import pygame
                pygame.mixer.music.set_volume(self.volume)
            except Exception:
                pass

    def toggle_mute(self):
        if self.has_audio and self.is_initialized:
            try:
                import pygame
                self.is_muted = not self.is_muted
                if self.is_muted:
                    pygame.mixer.music.set_volume(0.0)
                else:
                    pygame.mixer.music.set_volume(self.volume)
            except Exception:
                pass
        return self.is_muted

    def load_audio_from_video(self, video_path):
        self.stop()
        if not self.is_initialized:
            return False, self.init_error or "tmsc"

        ffmpeg_exe = None
        try:
            import imageio_ffmpeg
            ffmpeg_exe = imageio_ffmpeg.get_ffmpeg_exe()
        except ImportError:
            import shutil
            ffmpeg_exe = shutil.which("ffmpeg")

        if not ffmpeg_exe:
            return False, "you're hacked"

        temp_dir = tempfile.gettempdir()
        unique_id = uuid.uuid4().hex[:8]
        self.audio_file = os.path.join(temp_dir, f"voxeltext_temp_{unique_id}.wav")

        try:
            cmd = [
                ffmpeg_exe, "-y", "-i", video_path,
                "-vn", "-acodec", "pcm_s16le", "-ar", "44100", "-ac", "2",
                self.audio_file
            ]
            
            startupinfo = None
            if os.name == 'nt':
                startupinfo = subprocess.STARTUPINFO()
                startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW

            p = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, startupinfo=startupinfo, timeout=60)

            if os.path.exists(self.audio_file) and os.path.getsize(self.audio_file) > 1000:
                import pygame
                pygame.mixer.music.load(self.audio_file)
                self.has_audio = True
                if self.is_muted:
                    pygame.mixer.music.set_volume(0.0)
                else:
                    pygame.mixer.music.set_volume(self.volume)
                return True, "gonna cum"
            else:
                self.has_audio = False
                return False, "This video don't have audio"
        except subprocess.TimeoutExpired:
            self.has_audio = False
            return False, "cum for me or meh?"
        except Exception as e:
            self.has_audio = False
            return False, f"Err: {e}"

    def play(self, start_sec=0.0):
        if self.has_audio and self.is_initialized:
            try:
                import pygame
                self.start_offset = start_sec
                pygame.mixer.music.play(start=start_sec)
                if self.is_muted:
                    pygame.mixer.music.set_volume(0.0)
                else:
                    pygame.mixer.music.set_volume(self.volume)
                self.start_ticks = time.perf_counter()
                self.is_paused = False
            except Exception:
                pass

    def seek(self, target_sec):
        if self.has_audio and self.is_initialized:
            try:
                import pygame
                self.start_offset = target_sec
                pygame.mixer.music.play(start=target_sec)
                if self.is_muted:
                    pygame.mixer.music.set_volume(0.0)
                else:
                    pygame.mixer.music.set_volume(self.volume)
                if self.is_paused:
                    pygame.mixer.music.pause()
                self.start_ticks = time.perf_counter()
            except Exception:
                pass

    def pause(self):
        if self.has_audio and self.is_initialized and not self.is_paused:
            try:
                import pygame
                pygame.mixer.music.pause()
                self.pause_time = time.perf_counter()
                self.is_paused = True
            except Exception:
                pass

    def resume(self):
        if self.has_audio and self.is_initialized and self.is_paused:
            try:
                import pygame
                pygame.mixer.music.unpause()
                if self.is_muted:
                    pygame.mixer.music.set_volume(0.0)
                else:
                    pygame.mixer.music.set_volume(self.volume)
                self.start_ticks += (time.perf_counter() - self.pause_time)
                self.is_paused = False
            except Exception:
                pass

    def get_pos(self):
        if self.has_audio and self.is_initialized:
            if self.is_paused:
                return self.start_offset + (self.pause_time - self.start_ticks)
            
            import pygame
            if pygame.mixer.music.get_busy():
                pm_pos = pygame.mixer.music.get_pos()
                if pm_pos >= 0:
                    return self.start_offset + (pm_pos / 1000.0)
            
            return self.start_offset + (time.perf_counter() - self.start_ticks)
        return -1.0

    def stop(self):
        if self.is_initialized:
            try:
                import pygame
                pygame.mixer.music.stop()
                if hasattr(pygame.mixer.music, "unload"):
                    pygame.mixer.music.unload()
            except Exception:
                pass
        self.has_audio = False
        self.is_paused = False
        if self.audio_file and os.path.exists(self.audio_file):
            try:
                os.remove(self.audio_file)
            except Exception:
                pass
            self.audio_file = None