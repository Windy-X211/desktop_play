import os, sys, json, time, queue, threading, ctypes, random, faulthandler, struct, subprocess, wave
from ctypes import wintypes

import numpy as np
import cv2
import pygame
from pygame import mixer

from PyQt5.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QPushButton, QListWidget, QLabel, QComboBox, QFileDialog, QSpinBox,
)
from PyQt5.QtCore import Qt, QTimer, QThread, pyqtSignal

faulthandler.enable()

VIDEO_EXT = ('.mov', '.mp4', '.avi', '.mkv', '.flv', '.wmv', '.webm', '.m4v')

WS_EX_LAYERED = 0x80000
WS_EX_TOPMOST = 0x8
WS_EX_NOACTIVATE = 0x08000000
WS_EX_TOOLWINDOW = 0x80
ULW_ALPHA = 0x02
AC_SRC_OVER = 0x00
AC_SRC_ALPHA = 0x01
HWND_TOPMOST = -1
HWND_NOTOPMOST = -2
SWP_NOMOVE = 0x0002
SWP_NOSIZE = 0x0001
SWP_FRAMECHANGED = 0x0020
SWP_NOACTIVATE = 0x0010
SWP_SHOWWINDOW = 0x0040
SW_HIDE = 0
SW_SHOW = 5
GWL_WNDPROC = -4
WM_MOUSEWHEEL = 0x020A
WM_LBUTTONDOWN = 0x0201
WM_LBUTTONUP = 0x0202
WM_MOUSEMOVE = 0x0200

user32 = ctypes.windll.user32
gdi32 = ctypes.windll.gdi32


class POINT(ctypes.Structure): _fields_ = [("x", wintypes.LONG), ("y", wintypes.LONG)]
class SIZE(ctypes.Structure): _fields_ = [("cx", wintypes.LONG), ("cy", wintypes.LONG)]
class BLENDFUNCTION(ctypes.Structure):
    _fields_ = [("BlendOp", wintypes.BYTE), ("BlendFlags", wintypes.BYTE),
                ("SourceConstantAlpha", wintypes.BYTE), ("AlphaFormat", wintypes.BYTE)]
class BITMAPINFOHEADER(ctypes.Structure):
    _fields_ = [("biSize", wintypes.DWORD), ("biWidth", wintypes.LONG), ("biHeight", wintypes.LONG),
                ("biPlanes", wintypes.WORD), ("biBitCount", wintypes.WORD), ("biCompression", wintypes.DWORD),
                ("biSizeImage", wintypes.DWORD), ("biXPelsPerMeter", wintypes.LONG), ("biYPelsPerMeter", wintypes.LONG),
                ("biClrUsed", wintypes.DWORD), ("biClrImportant", wintypes.DWORD)]
class BITMAPINFO(ctypes.Structure): _fields_ = [("bmiHeader", BITMAPINFOHEADER), ("bmiColors", wintypes.DWORD * 1)]
class RECT(ctypes.Structure):
    _fields_ = [("left", wintypes.LONG), ("top", wintypes.LONG),
                ("right", wintypes.LONG), ("bottom", wintypes.LONG)]

user32.UpdateLayeredWindow.restype = wintypes.BOOL
user32.UpdateLayeredWindow.argtypes = [wintypes.HWND, wintypes.HDC, ctypes.POINTER(POINT),
    ctypes.POINTER(SIZE), wintypes.HDC, ctypes.POINTER(POINT), wintypes.DWORD,
    ctypes.POINTER(BLENDFUNCTION), wintypes.DWORD]
user32.GetCursorPos.restype = wintypes.BOOL
user32.GetCursorPos.argtypes = [ctypes.POINTER(POINT)]
user32.ShowWindow.restype = wintypes.BOOL
user32.ShowWindow.argtypes = [wintypes.HWND, wintypes.INT]
user32.GetWindowRect.restype = wintypes.BOOL
user32.GetWindowRect.argtypes = [wintypes.HWND, ctypes.POINTER(RECT)]
WNDPROC = ctypes.WINFUNCTYPE(ctypes.c_ssize_t, wintypes.HWND, ctypes.c_uint, wintypes.WPARAM, wintypes.LPARAM)
user32.CallWindowProcW.restype = ctypes.c_ssize_t
user32.CallWindowProcW.argtypes = [ctypes.c_ssize_t, wintypes.HWND, ctypes.c_uint, wintypes.WPARAM, wintypes.LPARAM]
user32.SetWindowLongPtrW.restype = ctypes.c_ssize_t
user32.SetWindowLongPtrW.argtypes = [wintypes.HWND, ctypes.c_int, ctypes.c_void_p]
user32.GetWindowLongPtrW.restype = ctypes.c_ssize_t
user32.GetWindowLongPtrW.argtypes = [wintypes.HWND, ctypes.c_int]
user32.SetWindowPos.restype = wintypes.BOOL
user32.SetWindowPos.argtypes = [wintypes.HWND, wintypes.HWND, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int, wintypes.UINT]
gdi32.CreateDIBSection.argtypes = [wintypes.HDC, ctypes.POINTER(BITMAPINFO), wintypes.DWORD,
    ctypes.POINTER(ctypes.c_void_p), wintypes.HANDLE, wintypes.DWORD]


def _do_set_windowpos(hwnd, topmost, x=0, y=0, w=0, h=0, flags=SWP_NOMOVE | SWP_NOSIZE):
    flag = HWND_TOPMOST if topmost else HWND_NOTOPMOST
    user32.SetWindowPos(hwnd, flag, int(x), int(y), int(w), int(h),
                        flags | SWP_FRAMECHANGED | SWP_NOACTIVATE | SWP_SHOWWINDOW)


_ev_lock = threading.Lock()
_ev_queue = queue.Queue(maxsize=512)
_old_wndproc = None
_wndproc_ref_keep = None


def _install_window_subclass(hwnd):
    global _old_wndproc, _wndproc_ref_keep

    def _wndproc(wh, msg, wp, lp):
        try:
            msg_i = int(msg)
            wp_i = int(wp)
            lp_i = int(lp)
            if msg_i == WM_MOUSEWHEEL:
                delta = (wp_i >> 16) & 0xFFFF
                if delta >= 0x8000: delta -= 0x10000
                cx = lp_i & 0xFFFF
                if cx >= 0x8000: cx -= 0x10000
                cy = (lp_i >> 16) & 0xFFFF
                if cy >= 0x8000: cy -= 0x10000
                with _ev_lock:
                    try: _ev_queue.put_nowait(('wheel', cx, cy, delta))
                    except queue.Full: pass
                return 0
            elif msg_i == WM_LBUTTONDOWN:
                cx = lp_i & 0xFFFF
                if cx >= 0x8000: cx -= 0x10000
                cy = (lp_i >> 16) & 0xFFFF
                if cy >= 0x8000: cy -= 0x10000
                with _ev_lock:
                    try: _ev_queue.put_nowait(('down', cx, cy, 0))
                    except queue.Full: pass
            elif msg_i == WM_LBUTTONUP:
                cx = lp_i & 0xFFFF
                if cx >= 0x8000: cx -= 0x10000
                cy = (lp_i >> 16) & 0xFFFF
                if cy >= 0x8000: cy -= 0x10000
                with _ev_lock:
                    try: _ev_queue.put_nowait(('up', cx, cy, 0))
                    except queue.Full: pass
            elif msg_i == WM_MOUSEMOVE:
                cx = lp_i & 0xFFFF
                if cx >= 0x8000: cx -= 0x10000
                cy = (lp_i >> 16) & 0xFFFF
                if cy >= 0x8000: cy -= 0x10000
                with _ev_lock:
                    try: _ev_queue.put_nowait(('move', cx, cy, 0))
                    except queue.Full: pass
        except Exception: pass
        return user32.CallWindowProcW(int(_old_wndproc), int(wh), int(msg), int(wp), int(lp))

    _wndproc_ref_keep = WNDPROC(_wndproc)
    _old_wndproc = user32.SetWindowLongPtrW(hwnd, GWL_WNDPROC, ctypes.cast(_wndproc_ref_keep, ctypes.c_void_p))


def _uninstall_window_subclass(hwnd):
    global _old_wndproc, _wndproc_ref_keep
    if hwnd is not None and _old_wndproc is not None:
        try:
            user32.SetWindowLongPtrW(hwnd, GWL_WNDPROC, ctypes.c_void_p(_old_wndproc))
        except Exception: pass
    _old_wndproc = None
    _wndproc_ref_keep = None


def _poll_events():
    out = []
    with _ev_lock:
        while not _ev_queue.empty():
            try: out.append(_ev_queue.get_nowait())
            except queue.Empty: break
    return out


def make_layered_window(hwnd, topmost=False):
    try:
        GWL_EXSTYLE = -20
        full_ex = WS_EX_LAYERED | WS_EX_TOOLWINDOW | WS_EX_NOACTIVATE
        if topmost:
            full_ex |= WS_EX_TOPMOST
        style = user32.GetWindowLongPtrW(hwnd, GWL_EXSTYLE)
        new_style = style | full_ex
        if new_style != style:
            user32.SetWindowLongPtrW(hwnd, GWL_EXSTYLE, ctypes.c_void_p(new_style))
        flag = HWND_TOPMOST if topmost else HWND_NOTOPMOST
        user32.ShowWindow(hwnd, SW_SHOW)
        user32.SetWindowPos(hwnd, flag, 0, 0, 0, 0,
                            SWP_NOMOVE | SWP_NOSIZE | SWP_FRAMECHANGED | SWP_NOACTIVATE | SWP_SHOWWINDOW)
        if topmost:
            import time as _t
            for _ in range(3):
                _t.sleep(0.02)
                user32.SetWindowPos(hwnd, HWND_TOPMOST, 0, 0, 0, 0,
                                    SWP_NOMOVE | SWP_NOSIZE | SWP_NOACTIVATE | SWP_SHOWWINDOW)
    except Exception as e:
        print(f"设置分层窗口失败: {e}")


def update_layered_window(hwnd, surface, x, y):
    try:
        width, height = surface.get_size()
        hdc_window = user32.GetDC(hwnd)
        hdc_memdc = gdi32.CreateCompatibleDC(hdc_window)
        bmi = BITMAPINFO()
        bmi.bmiHeader.biSize = ctypes.sizeof(BITMAPINFOHEADER)
        bmi.bmiHeader.biWidth = width
        bmi.bmiHeader.biHeight = -height
        bmi.bmiHeader.biPlanes = 1
        bmi.bmiHeader.biBitCount = 32
        bmi.bmiHeader.biCompression = 0
        bmi.bmiHeader.biSizeImage = 0
        ppv_bits = ctypes.c_void_p()
        hbitmap = gdi32.CreateDIBSection(hdc_memdc, ctypes.byref(bmi), 0,
                                          ctypes.byref(ppv_bits), None, 0)
        if hbitmap == 0:
            gdi32.DeleteDC(hdc_memdc); user32.ReleaseDC(hwnd, hdc_window); return
        old_obj = gdi32.SelectObject(hdc_memdc, hbitmap)
        pixel_data = pygame.image.tostring(surface, 'RGBA', True)
        ctypes.memmove(ppv_bits.value, pixel_data, width * height * 4)
        blend = BLENDFUNCTION()
        blend.BlendOp = AC_SRC_OVER
        blend.BlendFlags = 0
        blend.SourceConstantAlpha = 255
        blend.AlphaFormat = AC_SRC_ALPHA
        user32.UpdateLayeredWindow(
            hwnd, hdc_window, ctypes.byref(POINT(x, y)), ctypes.byref(SIZE(width, height)),
            hdc_memdc, ctypes.byref(POINT(0, 0)), 0, ctypes.byref(blend), ULW_ALPHA)
        gdi32.SelectObject(hdc_memdc, old_obj)
        gdi32.DeleteObject(hbitmap)
        gdi32.DeleteDC(hdc_memdc)
        user32.ReleaseDC(hwnd, hdc_window)
    except Exception as e:
        print(f"UpdateLayeredWindow 错误: {e}")


def get_cursor_pos():
    pt = POINT()
    user32.GetCursorPos(ctypes.byref(pt))
    return pt.x, pt.y


class PlayClock:
    def __init__(self):
        self.lock = threading.Lock()
        self.start_wall = None  # monotonic time when media t=0 starts (audio DAC)
        self._paused_at = None  # monotonic time when we entered pause
        self._paused_elapsed = 0.0  # accumulated "virtual wall time" during pause
        self.playing = False

    def begin(self):
        with self.lock:
            self.start_wall = None
            self._paused_at = None
            self._paused_elapsed = 0.0
            self.playing = True

    def set_start_wall_now(self):
        with self.lock:
            if self.playing:
                self.start_wall = time.monotonic() - self._paused_elapsed

    def pause(self):
        with self.lock:
            if not self.playing or self.start_wall is None: return
            self._paused_at = time.monotonic()
            self.playing = False

    def resume(self):
        with self.lock:
            if self.playing or self.start_wall is None or self._paused_at is None: return
            paused_wall = self._paused_at
            now = time.monotonic()
            pause_dur = now - paused_wall
            self.start_wall += pause_dur  # shift virtual start forward
            self._paused_elapsed += pause_dur
            self._paused_at = None
            self.playing = True

    def elapsed(self):
        with self.lock:
            if self.start_wall is None: return 0.0
            if self.playing:
                return time.monotonic() - self.start_wall
            if self._paused_at is not None:
                return self._paused_at - self.start_wall
            return 0.0


class AudioManager:
    TARGET_RATE = 44100
    TARGET_CHANNELS = 2
    TARGET_SAMPLE_WIDTH = 2

    def __init__(self):
        self._lock = threading.Lock()
        self._current_path = None
        self._current_sound = None
        self._current_channel = None
        self._ffmpeg_proc = None
        self._load_thread = None
        self._stopped = False
        self.muted = False

    def init_mixer(self):
        try: mixer.quit()
        except Exception: pass
        try:
            mixer.init(frequency=self.TARGET_RATE, size=-self.TARGET_SAMPLE_WIDTH * 8,
                       channels=self.TARGET_CHANNELS, buffer=1024)
        except Exception as e:
            print(f"[Audio] mixer.init 失败: {e}")
            try: mixer.init()
            except Exception: pass

    def _decode_audio(self, path):
        cmd = [
            'ffmpeg', '-y', '-i', path,
            '-vn', '-acodec', 'pcm_s16le',
            '-ar', str(self.TARGET_RATE),
            '-ac', str(self.TARGET_CHANNELS),
            '-f', 's16le', '-',
        ]
        try:
            proc = subprocess.Popen(cmd, stdout=subprocess.PIPE,
                                    stderr=subprocess.DEVNULL, bufsize=0)
        except FileNotFoundError:
            print("[Audio] 未找到 ffmpeg, 无音频")
            return None
        except Exception as e:
            print(f"[Audio] 启动 ffmpeg 失败: {e}")
            return None
        chunks = []
        try:
            while True:
                data = proc.stdout.read(1 << 20)
                if not data: break
                chunks.append(data)
        except Exception as e:
            print(f"[Audio] 读取失败: {e}")
        finally:
            try: proc.kill()
            except Exception: pass
            try: proc.wait(timeout=1)
            except Exception: pass
        pcm = b''.join(chunks)
        if not pcm: return None
        return pcm

    def _load_and_play(self, path, loop, play_clock):
        try:
            pcm = self._decode_audio(path)
            if pcm is None:
                if play_clock is not None:
                    play_clock.set_start_wall_now()
                return
            with self._lock:
                if self._stopped: return
                if self._current_path != path: return
                try:
                    sound = mixer.Sound(buffer=pcm)
                except Exception as e:
                    print(f"[Audio] Sound 创建失败: {e}")
                    if play_clock is not None:
                        play_clock.set_start_wall_now()
                    return
                self._current_sound = sound
                try:
                    channel = sound.play(loops=-1 if loop else 0)
                except Exception as e:
                    print(f"[Audio] play 失败: {e}")
                    if play_clock is not None:
                        play_clock.set_start_wall_now()
                    return
                self._current_channel = channel
                if self.muted:
                    try: channel.set_volume(0.0)
                    except Exception: pass
                if play_clock is not None:
                    play_clock.set_start_wall_now()
        except Exception as e:
            print(f"[Audio] 加载异常: {e}")
            if play_clock is not None:
                try: play_clock.set_start_wall_now()
                except Exception: pass

    def play_file(self, path, loop=False, play_clock=None):
        with self._lock:
            self._current_path = path
            self._current_sound = None
            self._current_channel = None
            try: mixer.stop()
            except Exception: pass
        if path is None or not os.path.isfile(path):
            if play_clock is not None:
                play_clock.set_start_wall_now()
            return
        self._load_thread = threading.Thread(
            target=self._load_and_play, args=(path, loop, play_clock), daemon=True)
        self._load_thread.start()

    def stop(self):
        with self._lock:
            try: mixer.stop()
            except Exception: pass
            self._current_sound = None
            self._current_channel = None
            self._current_path = None

    def pause(self):
        try: mixer.pause()
        except Exception: pass

    def unpause(self):
        try: mixer.unpause()
        except Exception: pass

    def set_volume(self, v):
        v = max(0.0, min(1.0, float(v)))
        try: mixer.music.set_volume(v)
        except Exception: pass
        with self._lock:
            try:
                if self._current_channel is not None:
                    self._current_channel.set_volume(0.0 if self.muted else v)
            except Exception: pass

    def set_muted(self, muted):
        self.muted = bool(muted)
        with self._lock:
            try:
                if self._current_channel is not None:
                    self._current_channel.set_volume(0.0 if self.muted else 1.0)
            except Exception: pass

    def toggle_mute(self):
        self.set_muted(not self.muted)
        return self.muted

    def close(self):
        with self._lock:
            self._stopped = True
            try: mixer.stop()
            except Exception: pass
            try: mixer.quit()
            except Exception: pass


class VideoDecoder(QThread):
    frame_ready = pyqtSignal(object, int, int)
    file_switched = pyqtSignal(int, str, int, int)

    def __init__(self):
        super().__init__()
        self.files = []; self.index = 0; self.mode = "sequence"
        self.running = True; self.paused = False
        self._pause_cv = threading.Condition()
        self._req_idx = None; self._req_next = False; self._req_prev = False
        self._req_pause = None; self._new_mode = None
        self._cur_path = None; self._cur_fps = 30.0
        self._cur_type = None; self._cur_container = None
        self._ui_ww = 0; self._ui_wh = 0
        self._ratio = 1.7777777778
        self._play_clock = None

    def set_play_clock(self, clock): self._play_clock = clock

    def set_files(self, files): self.files = list(files)
    def set_mode(self, mode): self._new_mode = mode
    def set_index(self, i): self._req_idx = i
    def set_pause(self, p):
        with self._pause_cv:
            self.paused = p
            self._pause_cv.notify_all()

    def request_next(self): self._req_next = True
    def request_prev(self): self._req_prev = True
    def set_target_size(self, w, h, ratio): self._ui_ww = w; self._ui_wh = h; self._ratio = ratio

    def _open_one(self, path):
        try:
            import av
            c = av.open(path)
            vs = c.streams.video[0]
            try:
                if hasattr(vs, 'rate'): fps = float(vs.rate)
                elif hasattr(vs.codec_context, 'framerate'): fps = float(vs.codec_context.framerate)
                else: fps = 30.0
                if hasattr(fps, 'numerator') and hasattr(fps, 'denominator'):
                    if fps.denominator != 0: fps = fps.numerator / fps.denominator
            except Exception: fps = 30.0
            fps = max(1.0, float(fps))
            return ('av', c, fps, vs.codec_context.height, vs.codec_context.width)
        except Exception:
            cap = cv2.VideoCapture(path, cv2.CAP_FFMPEG)
            if not cap.isOpened(): cap = cv2.VideoCapture(path)
            vw = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
            vh = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
            fc = cap.get(cv2.CAP_PROP_FPS)
            fps = max(1.0, float(fc)) if fc and fc > 0 else 30.0
            return ('cv2', cap, fps, vh, vw)

    def _switch_to(self, idx):
        if idx < 0 or idx >= len(self.files): return
        self.index = idx; self._cur_path = self.files[idx]
        try:
            if self._cur_container is not None and self._cur_type == 'av': self._cur_container.close()
            if self._cur_type == 'cv2' and self._cur_container is not None: self._cur_container.release()
        except Exception: pass
        try:
            info = self._open_one(self._cur_path)
            self._cur_type = info[0]; self._cur_container = info[1]; self._cur_fps = info[2]
            src_h, src_w = int(info[3]), int(info[4])
            if src_w > 0 and src_h > 0: self._ratio = src_h / src_w
        except Exception as e:
            print(f"[Decoder] 打开失败: {e}")
            self._switch_to((self.index + 1) % len(self.files)); return
        self.file_switched.emit(self.index, self._cur_path, src_h, src_w)

    def _pacing_sleep(self, frame_index):
        fps = max(1.0, float(self._cur_fps))
        if self._play_clock is None:
            time.sleep(max(0.001, 1.0 / fps * 0.95))
            return True
        start = self._play_clock.start_wall
        if start is None:
            time.sleep(max(0.001, 1.0 / fps * 0.95))
            return True
        target_play = frame_index / fps
        target_wall = start + target_play
        now = time.monotonic()
        delta = target_wall - now
        if delta > 0.001:
            time.sleep(delta)
            return True
        if delta < -0.040:
            return False  # too far behind, drop this frame
        return True

    def run(self):
        if not self.files: return
        self._switch_to(0)
        while self.running:
            if self._new_mode is not None: self.mode = self._new_mode; self._new_mode = None
            if self._req_idx is not None: self._switch_to(self._req_idx); self._req_idx = None
            if self._req_next: self._switch_to((self.index + 1) % len(self.files)); self._req_next = False
            if self._req_prev: self._switch_to((self.index - 1) % len(self.files)); self._req_prev = False
            if self._req_pause is not None:
                with self._pause_cv:
                    self.paused = self._req_pause
                    if not self.paused: self._pause_cv.notify_all()
                self._req_pause = None
            with self._pause_cv:
                while self.paused: self._pause_cv.wait(0.05)
            if self._cur_container is None: self._switch_to((self.index + 1) % len(self.files)); continue

            if self._ui_ww > 0 and self._ui_wh > 0:
                tw, th = self._ui_ww, self._ui_wh
            else:
                th, tw = 900, int(900 / max(0.0001, self._ratio))

            if tw > 0 and th > 0:
                real_th = th; real_tw = int(max(40, real_th / max(0.0001, self._ratio)))
            else:
                real_th = 900; real_tw = int(real_th / max(0.0001, self._ratio))

            frame_index = 0
            try:
                if self._cur_type == 'av':
                    try: frame_iter = self._cur_container.decode(video=0)
                    except Exception: self._switch_to((self.index + 1) % len(self.files)); continue
                    try:
                        for frame in frame_iter:
                            if not self.running: break
                            if self._req_idx is not None or self._req_next or self._req_prev: break
                            if self._new_mode is not None: self.mode = self._new_mode; self._new_mode = None
                            with self._pause_cv:
                                while self.paused: self._pause_cv.wait(0.05)
                            keep = self._pacing_sleep(frame_index)
                            frame_index += 1
                            if not keep:
                                continue
                            argb = frame.to_ndarray(format='argb')
                            rgba = np.zeros((argb.shape[0], argb.shape[1], 4), dtype=np.uint8)
                            rgba[:, :, 0] = argb[:, :, 3]
                            rgba[:, :, 1] = argb[:, :, 2]
                            rgba[:, :, 2] = argb[:, :, 1]
                            rgba[:, :, 3] = argb[:, :, 0]
                            del argb
                            f = cv2.flip(rgba, 0); f = cv2.resize(f, (real_tw, real_th))
                            f = np.ascontiguousarray(f, dtype=np.uint8)
                            self.frame_ready.emit(f.tobytes(), real_tw, real_th)
                            del rgba, f
                    except Exception: pass

                    if self._req_idx is not None or self._req_next or self._req_prev: continue
                    if self.mode == "loop": self._switch_to(self.index); continue
                    elif self.mode == "shuffle":
                        if len(self.files) > 1:
                            while True:
                                nxt = random.randrange(len(self.files))
                                if nxt != self.index: self._switch_to(nxt); break
                        else: self._switch_to(self.index)
                    else: self._switch_to((self.index + 1) % len(self.files))
                else:
                    ret, frame = self._cur_container.read()
                    if not ret:
                        if self.mode == "loop": self._switch_to(self.index); continue
                        elif self.mode == "shuffle":
                            if len(self.files) > 1:
                                while True:
                                    nxt = random.randrange(len(self.files))
                                    if nxt != self.index: self._switch_to(nxt); break
                            else: self._switch_to(self.index)
                        else: self._switch_to((self.index + 1) % len(self.files))
                        continue
                    keep = self._pacing_sleep(frame_index)
                    frame_index += 1
                    if keep:
                        if frame.shape[2] == 4: rgba = cv2.cvtColor(frame, cv2.COLOR_BGRA2RGBA)
                        else:
                            rgba = cv2.cvtColor(frame, cv2.COLOR_BGR2RGBA)
                            rgba[:, :, 3] = 255
                        f = cv2.flip(rgba, 0); f = cv2.resize(f, (real_tw, real_th))
                        f = np.ascontiguousarray(f, dtype=np.uint8)
                        self.frame_ready.emit(f.tobytes(), real_tw, real_th)
                        del rgba, f
            except Exception as e:
                import traceback
                print(f"[Decoder] 主循环异常: {e}\n{traceback.format_exc()}")
                time.sleep(0.1)


class PlayerMainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("透明视频播放器")
        self.resize(460, 580)
        self.setWindowFlags(self.windowFlags() | Qt.WindowStaysOnTopHint)
        self.folder = None; self._files = []
        self.topmost = False
        self.locked = False

        self.engine_hwnd = None
        self.engine_WW = 0; self.engine_WH = 0
        self.engine_ratio = 1.7777777778
        self.engine_current_x = 200; self.engine_current_y = 150
        self.engine_dragging = False
        self.engine_drag_mouse_x0 = 0
        self.engine_drag_mouse_y0 = 0
        self.engine_drag_window_x0 = 0
        self.engine_drag_window_y0 = 0
        self._render_lock = threading.Lock()

        central = QWidget(); self.setCentralWidget(central)
        vbox = QVBoxLayout(central)

        row1 = QHBoxLayout()
        self.btn_folder = QPushButton("选择文件夹")
        self.btn_folder.clicked.connect(self.pick_folder)
        self.btn_refresh = QPushButton("刷新")
        self.btn_refresh.clicked.connect(self.refresh_list)
        row1.addWidget(self.btn_folder); row1.addWidget(self.btn_refresh)
        vbox.addLayout(row1)

        self.lbl_folder = QLabel("当前文件夹: (未选择)")
        self.lbl_folder.setWordWrap(True); vbox.addWidget(self.lbl_folder)

        self.lst_videos = QListWidget()
        self.lst_videos.itemDoubleClicked.connect(self.on_item_double_clicked)
        vbox.addWidget(self.lst_videos, 1)

        row2 = QHBoxLayout()
        self.btn_play = QPushButton("播放")
        self.btn_play.clicked.connect(self.toggle_play)
        self.btn_mute = QPushButton("静音")
        self.btn_mute.setCheckable(True)
        self.btn_mute.clicked.connect(self.toggle_mute)
        self.btn_prev = QPushButton("上一个")
        self.btn_prev.clicked.connect(self.prev_video)
        self.btn_next = QPushButton("下一个")
        self.btn_next.clicked.connect(self.next_video)
        row2.addWidget(self.btn_play); row2.addWidget(self.btn_mute); row2.addWidget(self.btn_prev); row2.addWidget(self.btn_next)
        vbox.addLayout(row2)

        row3 = QHBoxLayout()
        self.lbl_mode = QLabel("播放模式:")
        self.combo_mode = QComboBox()
        self.combo_mode.addItem("顺序播放")
        self.combo_mode.addItem("单曲循环")
        self.combo_mode.addItem("随机播放")
        self.combo_mode.setCurrentIndex(0)
        self.combo_mode.currentIndexChanged.connect(self.on_mode_changed)
        self.lbl_x = QLabel("初始X:")
        self.spin_x = QSpinBox(); self.spin_x.setRange(-5000, 5000); self.spin_x.setValue(200)
        self.lbl_y = QLabel("初始Y:")
        self.spin_y = QSpinBox(); self.spin_y.setRange(-5000, 5000); self.spin_y.setValue(150)
        self.lbl_h = QLabel("初始高度:")
        self.spin_h = QSpinBox(); self.spin_h.setRange(100, 3000); self.spin_h.setValue(900)
        row3.addWidget(self.lbl_mode); row3.addWidget(self.combo_mode)
        row3.addWidget(self.lbl_x); row3.addWidget(self.spin_x)
        row3.addWidget(self.lbl_y); row3.addWidget(self.spin_y)
        row3.addWidget(self.lbl_h); row3.addWidget(self.spin_h)
        vbox.addLayout(row3)

        row3c = QHBoxLayout()
        self.btn_apply_cfg = QPushButton("初始化")
        self.btn_apply_cfg.clicked.connect(self._apply_spinbox_size_pos)
        self.btn_capture_cfg = QPushButton("设为初始值")
        self.btn_capture_cfg.clicked.connect(self._capture_engine_to_spinbox)
        self.btn_restore_cfg = QPushButton("恢复默认")
        self.btn_restore_cfg.clicked.connect(self._restore_defaults)
        row3c.addWidget(self.btn_apply_cfg); row3c.addWidget(self.btn_capture_cfg); row3c.addWidget(self.btn_restore_cfg)
        vbox.addLayout(row3c)

        row4 = QHBoxLayout()
        self.btn_topmost = QPushButton("置顶窗口")
        self.btn_topmost.setCheckable(True)
        self.btn_topmost.clicked.connect(self.toggle_topmost)
        self.btn_locked = QPushButton("固定")
        self.btn_locked.setCheckable(True)
        self.btn_locked.clicked.connect(self.toggle_locked)
        self.btn_showhide = QPushButton("隐藏视频")
        self.btn_showhide.setCheckable(True)
        self.btn_showhide.setChecked(True)
        self.btn_showhide.clicked.connect(self.toggle_video_visible)
        row4.addWidget(self.btn_topmost); row4.addWidget(self.btn_locked); row4.addWidget(self.btn_showhide)
        vbox.addLayout(row4)

        self.lbl_status = QLabel("就绪"); vbox.addWidget(self.lbl_status)

        self._config_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".mov_play_config.json")

        self.play_clock = PlayClock()
        self.audio = AudioManager()

        self.decoder = VideoDecoder()
        self.decoder.frame_ready.connect(self.on_frame_ready)
        self.decoder.file_switched.connect(self.on_file_switched)
        self.decoder.set_play_clock(self.play_clock)

        self._restore_last_folder()

        self._ui_timer = QTimer(self)
        self._ui_timer.timeout.connect(self._pump_events)
        self._ui_timer.start(8)

        self._pending_frame = None

    def _ensure_sdl_window(self, ratio):
        if self.engine_hwnd is not None:
            if abs(ratio - self.engine_ratio) > 0.0001:
                self.engine_ratio = ratio
                self.engine_WH = max(50, self.engine_WH)
                self.engine_WW = int(max(40, self.engine_WH / max(0.0001, self.engine_ratio)))
                try:
                    _do_set_windowpos(self.engine_hwnd, self.topmost,
                                      int(self.engine_current_x), int(self.engine_current_y),
                                      self.engine_WW, self.engine_WH, 0)
                    self.decoder.set_target_size(self.engine_WW, self.engine_WH, self.engine_ratio)
                except Exception as e: print(f"重置尺寸失败: {e}")
            return
        try: pygame.init()
        except Exception as e: print(f"pygame init 失败: {e}")
        self.audio.init_mixer()
        self.engine_ratio = ratio
        height = int(self.spin_h.value())
        self.engine_WH = max(50, height)
        self.engine_WW = int(max(40, self.engine_WH / max(0.0001, self.engine_ratio)))
        os.environ['SDL_VIDEO_WINDOW_POS'] = f"{self.engine_current_x},{self.engine_current_y}"
        try: pygame.display.quit()
        except Exception: pass
        try:
            pygame.display.set_mode((self.engine_WW, self.engine_WH), pygame.NOFRAME | pygame.SRCALPHA)
            hwnd = pygame.display.get_wm_info()["window"]
            user32.ShowWindow(hwnd, SW_HIDE)
            make_layered_window(hwnd, topmost=self.topmost)
            # 强制把窗口摆到指定位置和尺寸，再读真实值
            _do_set_windowpos(hwnd, self.topmost,
                              int(self.engine_current_x), int(self.engine_current_y),
                              self.engine_WW, self.engine_WH, 0)
            rect = RECT()
            user32.GetWindowRect(hwnd, ctypes.byref(rect))
            self.engine_current_x = int(rect.left)
            self.engine_current_y = int(rect.top)
            self.engine_WW = int(max(40, rect.right - rect.left))
            self.engine_WH = int(max(50, rect.bottom - rect.top))
            print(f"[init] 视频窗口左上角位置: ({self.engine_current_x},{self.engine_current_y}) 尺寸 {self.engine_WW}x{self.engine_WH} ratio={self.engine_ratio}")
            user32.ShowWindow(hwnd, SW_SHOW)
            self.engine_hwnd = hwnd
            _install_window_subclass(hwnd)
            self.decoder.set_target_size(self.engine_WW, self.engine_WH, self.engine_ratio)
        except Exception as e: print(f"SDL 窗口创建失败: {e}")

    def _pump_events(self):
        events = _poll_events()
        for et, x, y, wheel in events:
            if self.locked:
                continue
            # Subclass 给的 cx,cy 是窗口客户区相对坐标
            if et == 'wheel':
                if wheel == 0 or self.engine_hwnd is None: continue
                mx, my = get_cursor_pos()  # 桌面绝对
                cur_w = int(self.engine_WW)
                cur_h = int(self.engine_WH)
                cur_x = int(self.engine_current_x)
                cur_y = int(self.engine_current_y)
                rel_x = mx - cur_x
                rel_y = my - cur_y
                if rel_x < 0: rel_x = 0
                if rel_y < 0: rel_y = 0
                if rel_x > cur_w: rel_x = cur_w
                if rel_y > cur_h: rel_y = cur_h
                rx_ratio = rel_x / max(1, cur_w)
                ry_ratio = rel_y / max(1, cur_h)
                if wheel > 0: scale = 1.1
                else: scale = 0.9
                new_wh = int(cur_h * scale)
                new_wh = max(100, min(new_wh, 3000))
                new_ww = int(new_wh / max(0.0001, self.engine_ratio))
                new_left = mx - int(rx_ratio * new_ww)
                new_top = my - int(ry_ratio * new_wh)
                self.engine_WW = new_ww
                self.engine_WH = new_wh
                self.engine_current_x = new_left
                self.engine_current_y = new_top
                try:
                    _do_set_windowpos(self.engine_hwnd, self.topmost,
                                      new_left, new_top, new_ww, new_wh, 0)
                    self.decoder.set_target_size(new_ww, new_wh, float(self.engine_ratio))
                except Exception as e: print(f"wheel resize error: {e}")

            elif et == 'down':
                mx, my = get_cursor_pos()
                self.engine_dragging = True
                self.engine_drag_mouse_x0 = mx
                self.engine_drag_mouse_y0 = my
                self.engine_drag_window_x0 = int(self.engine_current_x)
                self.engine_drag_window_y0 = int(self.engine_current_y)
                
            elif et == 'up':
                self.engine_dragging = False

        # dragging 期间每 8ms 直接查桌面鼠标绝对坐标（不管鼠标在不在窗口里）
        if self.engine_dragging and self.engine_hwnd is not None:
            mx, my = get_cursor_pos()
            dx = mx - self.engine_drag_mouse_x0
            dy = my - self.engine_drag_mouse_y0
            self.engine_current_x = self.engine_drag_window_x0 + dx
            self.engine_current_y = self.engine_drag_window_y0 + dy
            try:
                _do_set_windowpos(self.engine_hwnd, self.topmost,
                                  int(self.engine_current_x), int(self.engine_current_y),
                                  0, 0, SWP_NOSIZE)
            except Exception: pass

        pf = self._pending_frame
        if pf is not None and self.engine_hwnd is not None:
            with self._render_lock:
                frame_bytes, w, h = pf
                if (w, h) != (self.engine_WW, self.engine_WH):
                    try:
                        surf = pygame.image.frombuffer(frame_bytes, (w, h), 'RGBA')
                        surf = pygame.transform.smoothscale(surf, (self.engine_WW, self.engine_WH))
                    except Exception:
                        try:
                            surf = pygame.image.frombuffer(frame_bytes, (w, h), 'RGBA')
                        except Exception:
                            self._pending_frame = None
                            return
                else:
                    try:
                        surf = pygame.image.frombuffer(frame_bytes, (w, h), 'RGBA')
                    except Exception:
                        self._pending_frame = None
                        return
                try:
                    update_layered_window(
                        self.engine_hwnd, surf,
                        int(self.engine_current_x), int(self.engine_current_y))
                except Exception as e: print(f"render err: {e}")
                self._pending_frame = None

    def on_frame_ready(self, frame_bytes, w, h):
        self._pending_frame = (bytes(frame_bytes), int(w), int(h))

    def on_file_switched(self, idx, path, src_h, src_w):
        if 0 <= idx < self.lst_videos.count(): self.lst_videos.setCurrentRow(idx)
        self.lbl_status.setText(f"播放: {os.path.basename(path)}")
        try:
            mode = {0: False, 1: True, 2: False}.get(self.combo_mode.currentIndex(), False)
            self.play_clock.begin()
            self.audio.play_file(path, loop=mode, play_clock=self.play_clock)
        except Exception as e:
            print(f"[Audio] 切换播放失败: {e}")
        if src_w > 0 and src_h > 0 and self.engine_hwnd is not None:
            new_ratio = src_h / src_w
            self.engine_ratio = new_ratio
            self.engine_WH = max(50, int(self.engine_WH))
            self.engine_WW = int(max(40, self.engine_WH / max(0.0001, self.engine_ratio)))
            try:
                user32.SetWindowPos(self.engine_hwnd,
                                    HWND_TOPMOST if self.topmost else HWND_NOTOPMOST,
                                    int(self.engine_current_x), int(self.engine_current_y),
                                    self.engine_WW, self.engine_WH,
                                    SWP_FRAMECHANGED | SWP_NOACTIVATE)
                self.decoder.set_target_size(self.engine_WW, self.engine_WH, self.engine_ratio)
            except Exception as e: print(f"切换视频重置窗口失败: {e}")

    def _restore_last_folder(self):
        try:
            if os.path.exists(self._config_path):
                with open(self._config_path, "r", encoding="utf-8") as f: cfg = json.load(f)
                last = cfg.get("last_folder")
                if last and os.path.isdir(last): self.folder = last; self.refresh_list()
                pos_x = cfg.get("pos_x", 200)
                pos_y = cfg.get("pos_y", 150)
                h = cfg.get("height", 900)
                if not isinstance(pos_x, int): pos_x = 200
                if not isinstance(pos_y, int): pos_y = 150
                if not isinstance(h, int): h = 900
                self.spin_x.setValue(pos_x)
                self.spin_y.setValue(pos_y)
                self.spin_h.setValue(h)
                self.engine_current_x = pos_x
                self.engine_current_y = pos_y
                self.engine_WH = h
                locked = bool(cfg.get("locked", False))
                self.locked = locked
                self.btn_locked.setChecked(locked)
                self.btn_locked.setText("已固定" if locked else "固定")
                muted = bool(cfg.get("muted", False))
                self.audio.set_muted(muted)
                self.btn_mute.setChecked(muted)
                self.btn_mute.setText("已静音" if muted else "静音")
        except Exception: pass

    def _save_config(self):
        try:
            cfg = {}
            if os.path.exists(self._config_path):
                try:
                    with open(self._config_path, "r", encoding="utf-8") as f: cfg = json.load(f)
                except Exception: cfg = {}
            cfg["last_folder"] = self.folder
            cfg["pos_x"] = self.spin_x.value()
            cfg["pos_y"] = self.spin_y.value()
            cfg["height"] = self.spin_h.value()
            cfg["locked"] = bool(self.locked)
            cfg["muted"] = bool(self.audio.muted)
            with open(self._config_path, "w", encoding="utf-8") as f: json.dump(cfg, f, ensure_ascii=False, indent=2)
        except Exception: pass

    def toggle_mute(self, checked):
        self.audio.set_muted(bool(checked))
        self.btn_mute.setText("已静音" if checked else "静音")

    def _apply_spinbox_size_pos(self):
        x = self.spin_x.value(); y = self.spin_y.value(); h = self.spin_h.value()
        self.engine_current_x = x; self.engine_current_y = y; self.engine_WH = h
        if self.engine_hwnd is not None:
            self.engine_WW = int(max(40, self.engine_WH / max(0.0001, self.engine_ratio)))
            try:
                user32.SetWindowPos(self.engine_hwnd,
                                    HWND_TOPMOST if self.topmost else HWND_NOTOPMOST,
                                    x, y, self.engine_WW, self.engine_WH,
                                    SWP_FRAMECHANGED | SWP_NOACTIVATE)
                self.decoder.set_target_size(self.engine_WW, self.engine_WH, float(self.engine_ratio))
            except Exception: pass

    def _capture_engine_to_spinbox(self):
        self.spin_x.setValue(int(self.engine_current_x))
        self.spin_y.setValue(int(self.engine_current_y))
        self.spin_h.setValue(int(self.engine_WH))

    def _restore_defaults(self):
        self.spin_x.setValue(200); self.spin_y.setValue(150); self.spin_h.setValue(900)
        self._apply_spinbox_size_pos()

    def pick_folder(self):
        d = QFileDialog.getExistingDirectory(self, "选择视频文件夹", self.folder or "")
        if not d: return
        self.folder = d; self._save_config(); self.refresh_list()

    def refresh_list(self):
        self.lst_videos.clear()
        if not self.folder or not os.path.isdir(self.folder):
            self.lbl_folder.setText("当前文件夹: (未选择)")
            self.lbl_status.setText("请先选择一个文件夹"); return
        files = sorted(os.path.join(self.folder, n)
                       for n in os.listdir(self.folder)
                       if n.lower().endswith(VIDEO_EXT))
        for p in files: self.lst_videos.addItem(os.path.basename(p))
        self.lbl_folder.setText(f"当前文件夹: {self.folder}  共 {len(files)} 个文件")
        self._files = files; self.decoder.set_files(files)

    def on_item_double_clicked(self, item):
        row = self.lst_videos.row(item)
        if row < 0 or row >= len(self._files): return
        ratio_guess = self.engine_ratio
        try:
            fpath = self._files[row]
            import av
            c = av.open(fpath); vs = c.streams.video[0]
            vh = vs.codec_context.height; vw = vs.codec_context.width
            c.close()
            if vw > 0 and vh > 0: ratio_guess = vh / vw
        except Exception: pass

        self._ensure_sdl_window(ratio_guess)
        self.decoder.set_index(row)
        with self.decoder._pause_cv:
            self.decoder.paused = False
            self.decoder._pause_cv.notify_all()
        if not self.decoder.isRunning(): self.decoder.start()
        self.lbl_status.setText(f"播放: {os.path.basename(self._files[row])}")

    def toggle_play(self):
        if not self.decoder.isRunning():
            if self._files:
                self.decoder.set_index(0); self._ensure_sdl_window(self.engine_ratio)
                self.decoder.start()
            return
        with self.decoder._pause_cv:
            self.decoder.paused = not self.decoder.paused
            if not self.decoder.paused: self.decoder._pause_cv.notify_all()
        if self.decoder.paused:
            try: self.play_clock.pause()
            except Exception: pass
            self.audio.pause()
        else:
            try: self.play_clock.resume()
            except Exception: pass
            self.audio.unpause()

    def next_video(self): self.decoder.request_next()
    def prev_video(self): self.decoder.request_prev()

    def on_mode_changed(self, idx):
        mode = {0: "sequence", 1: "loop", 2: "shuffle"}[idx]
        self.decoder.set_mode(mode)

    def toggle_topmost(self, checked):
        self.topmost = bool(checked)
        self.btn_topmost.setText("取消置顶" if self.topmost else "置顶窗口")
        if self.engine_hwnd is not None:
            try:
                make_layered_window(self.engine_hwnd, topmost=self.topmost)
                if self.topmost:
                    def _guard():
                        GWL_EXSTYLE = -20
                        while self.topmost and self.engine_hwnd:
                            try:
                                style = user32.GetWindowLongPtrW(self.engine_hwnd, GWL_EXSTYLE)
                                full = WS_EX_LAYERED | WS_EX_TOOLWINDOW | WS_EX_NOACTIVATE | WS_EX_TOPMOST
                                if not (style & WS_EX_TOPMOST):
                                    user32.SetWindowLongPtrW(self.engine_hwnd, GWL_EXSTYLE, ctypes.c_void_p(style | full))
                                user32.ShowWindow(self.engine_hwnd, SW_SHOW)
                                _do_set_windowpos(self.engine_hwnd, True)
                            except Exception: pass
                            time.sleep(0.2)
                    threading.Thread(target=_guard, daemon=True).start()
            except Exception: pass

    def toggle_locked(self, checked):
        self.locked = bool(checked)
        self.btn_locked.setText("已固定" if self.locked else "固定")

    def toggle_video_visible(self, checked):
        if self.engine_hwnd is None: return
        if checked:
            user32.ShowWindow(self.engine_hwnd, SW_SHOW)
            self.btn_showhide.setText("隐藏视频")
        else:
            user32.ShowWindow(self.engine_hwnd, SW_HIDE)
            self.btn_showhide.setText("显示视频")

    def closeEvent(self, event):
        try: self._save_config()
        except Exception: pass
        _uninstall_window_subclass(self.engine_hwnd)
        try: self.audio.close()
        except Exception: pass
        self.decoder.running = False
        try: self.decoder.wait(1500)
        except Exception: pass
        try: pygame.quit()
        except Exception: pass
        super().closeEvent(event)


def main():
    app = QApplication(sys.argv)
    w = PlayerMainWindow()
    w.show()
    sys.exit(app.exec_())


if __name__ == "__main__": main()
