import pygame
import cv2
import numpy as np
import ctypes
from ctypes import wintypes
import sys
import threading
import queue

# ===================== 你的配置 =====================
VIDEO_PATH = r"E:\mp4\6月12日.mov"
POS_X = 200
POS_Y = 150
WINDOW_HEIGHT = 900

# Windows API 常量
WS_EX_LAYERED = 0x80000
ULW_ALPHA = 0x02
AC_SRC_OVER = 0x00
AC_SRC_ALPHA = 0x01

# 定义 Windows 结构体
class POINT(ctypes.Structure):
    _fields_ = [("x", wintypes.LONG), ("y", wintypes.LONG)]

class SIZE(ctypes.Structure):
    _fields_ = [("cx", wintypes.LONG), ("cy", wintypes.LONG)]

class BLENDFUNCTION(ctypes.Structure):
    _fields_ = [
        ("BlendOp", wintypes.BYTE),
        ("BlendFlags", wintypes.BYTE),
        ("SourceConstantAlpha", wintypes.BYTE),
        ("AlphaFormat", wintypes.BYTE)
    ]

class BITMAPINFOHEADER(ctypes.Structure):
    _fields_ = [
        ("biSize", wintypes.DWORD),
        ("biWidth", wintypes.LONG),
        ("biHeight", wintypes.LONG),
        ("biPlanes", wintypes.WORD),
        ("biBitCount", wintypes.WORD),
        ("biCompression", wintypes.DWORD),
        ("biSizeImage", wintypes.DWORD),
        ("biXPelsPerMeter", wintypes.LONG),
        ("biYPelsPerMeter", wintypes.LONG),
        ("biClrUsed", wintypes.DWORD),
        ("biClrImportant", wintypes.DWORD)
    ]

class BITMAPINFO(ctypes.Structure):
    _fields_ = [
        ("bmiHeader", BITMAPINFOHEADER),
        ("bmiColors", wintypes.DWORD * 1)
    ]

# 加载 Windows API
user32 = ctypes.windll.user32
gdi32 = ctypes.windll.gdi32

user32.UpdateLayeredWindow.restype = wintypes.BOOL
user32.UpdateLayeredWindow.argtypes = [
    wintypes.HWND, wintypes.HDC, ctypes.POINTER(POINT),
    ctypes.POINTER(SIZE), wintypes.HDC, ctypes.POINTER(POINT),
    wintypes.DWORD, ctypes.POINTER(BLENDFUNCTION), wintypes.DWORD
]

user32.GetCursorPos.restype = wintypes.BOOL
user32.GetCursorPos.argtypes = [ctypes.POINTER(POINT)]

user32.ShowWindow.restype = wintypes.BOOL
user32.ShowWindow.argtypes = [wintypes.HWND, wintypes.INT]

SW_HIDE = 0
SW_SHOW = 5

def get_cursor_pos():
    pt = POINT()
    user32.GetCursorPos(ctypes.byref(pt))
    return pt.x, pt.y

gdi32.CreateDIBSection.argtypes = [
    wintypes.HDC, ctypes.POINTER(BITMAPINFO),
    wintypes.DWORD, ctypes.POINTER(ctypes.c_void_p),
    wintypes.HANDLE, wintypes.DWORD
]

# ====================================================

def make_layered_window(hwnd):
    try:
        style = user32.GetWindowLongW(hwnd, -20)
        user32.SetWindowLongW(hwnd, -20, style | WS_EX_LAYERED)
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
        hbitmap = gdi32.CreateDIBSection(hdc_memdc, ctypes.byref(bmi), 0, ctypes.byref(ppv_bits), None, 0)
        
        if hbitmap == 0:
            gdi32.DeleteDC(hdc_memdc)
            user32.ReleaseDC(hwnd, hdc_window)
            print("创建 DIB 位图失败")
            return
        
        old_obj = gdi32.SelectObject(hdc_memdc, hbitmap)
        
        pixel_data = pygame.image.tostring(surface, 'RGBA', True)
        
        ctypes.memmove(ppv_bits.value, pixel_data, width * height * 4)
        
        blend = BLENDFUNCTION()
        blend.BlendOp = AC_SRC_OVER
        blend.BlendFlags = 0
        blend.SourceConstantAlpha = 255
        blend.AlphaFormat = AC_SRC_ALPHA
        
        pt_dst = POINT(x, y)
        size = SIZE(width, height)
        pt_src = POINT(0, 0)
        
        user32.UpdateLayeredWindow(
            hwnd, hdc_window, ctypes.byref(pt_dst),
            ctypes.byref(size), hdc_memdc, ctypes.byref(pt_src),
            0, ctypes.byref(blend), ULW_ALPHA
        )
        
        gdi32.SelectObject(hdc_memdc, old_obj)
        gdi32.DeleteObject(hbitmap)
        gdi32.DeleteDC(hdc_memdc)
        user32.ReleaseDC(hwnd, hdc_window)
        
    except Exception as e:
        print(f"UpdateLayeredWindow 错误: {e}")

# ====================================================

print("初始化 pygame...")
pygame.init()
pygame.mixer.init()
print("pygame 初始化完成")

audio_queue = queue.Queue(maxsize=50)
audio_thread_running = True
container = None
av = None
cap = None

try:
    import av
    print("正在加载 PyAV...")
    container = av.open(VIDEO_PATH)
    print(f"PyAV 打开视频成功: {VIDEO_PATH}")
    
    video_stream = container.streams.video[0]
    print(f"找到视频流: {video_stream}")
    video_stream.thread_type = 'AUTO'
    
    vw = video_stream.codec_context.width
    vh = video_stream.codec_context.height
    print(f"视频分辨率: {vw}x{vh}")
    
    fps = 30
    try:
        if hasattr(video_stream, 'rate'):
            fps = video_stream.rate
        elif hasattr(video_stream.codec_context, 'framerate'):
            fps = video_stream.codec_context.framerate
        elif hasattr(video_stream, 'average_rate'):
            fps = video_stream.average_rate
        if hasattr(fps, 'numerator') and hasattr(fps, 'denominator'):
            fps = fps.numerator / fps.denominator
    except Exception as e:
        print(f"获取帧率失败，使用默认值 30: {e}")
    
    ratio = vh / vw
    
    print(f"PyAV 读取成功")
    print(f"视频流: {video_stream}")
    print(f"编码格式: {video_stream.codec.name}")
    print(f"分辨率: {vw}x{vh}")
    print(f"帧率: {fps}")
    
    has_alpha = False
    print("正在检测透明通道...")
    for frame in container.decode(video=0):
        frame_array = frame.to_ndarray(format='rgba')
        print(f"帧格式: {frame.format.name}")
        print(f"帧形状: {frame_array.shape}")
        if frame_array.ndim == 3 and frame_array.shape[2] == 4:
            has_alpha = True
            alpha_min = np.min(frame_array[:, :, 3])
            print(f"Alpha 通道最小值: {alpha_min}")
            if alpha_min < 255:
                print("检测到透明数据")
        break
    
    audio_stream = None
    audio_container = None
    if len(container.streams.audio) > 0:
        audio_container = av.open(VIDEO_PATH)
        audio_stream = audio_container.streams.audio[0]
        print(f"找到音频流: {audio_stream}")
        print(f"音频采样率: {audio_stream.codec_context.sample_rate}")
        print(f"音频通道数: {audio_stream.codec_context.channels}")
    else:
        print("未找到音频流")
    
    container.seek(0)
    print("初始化完成")
    
except ImportError:
    print("警告: PyAV 未安装，尝试使用 OpenCV")
    av = None
    container = None
    
    cap = cv2.VideoCapture(VIDEO_PATH, cv2.CAP_FFMPEG)
    if not cap.isOpened():
        cap = cv2.VideoCapture(VIDEO_PATH)
        if not cap.isOpened():
            print(f"无法打开视频: {VIDEO_PATH}")
            sys.exit(1)
    
    vw = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    vh = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    fps = cap.get(cv2.CAP_PROP_FPS) or 30
    ratio = vh / vw
    has_alpha = False
    audio_stream = None
    
except Exception as e:
    print(f"PyAV 读取失败: {e}")
    av = None
    container = None
    
    cap = cv2.VideoCapture(VIDEO_PATH)
    if not cap.isOpened():
        print(f"无法打开视频: {VIDEO_PATH}")
        sys.exit(1)
    
    vw = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    vh = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    fps = cap.get(cv2.CAP_PROP_FPS) or 30
    ratio = vh / vw
    has_alpha = False
    audio_stream = None

# ====================================================

def audio_decoding_thread():
    global audio_thread_running
    if not av or not audio_container or not audio_stream:
        return
    while audio_thread_running:
        try:
            for frame in audio_container.decode(audio=0):
                if not audio_thread_running:
                    break
                audio_samples = frame.to_ndarray()
                if audio_samples.ndim == 2:
                    audio_samples = audio_samples.T
                audio_samples = (audio_samples * 32767).astype(np.int16)
                if audio_stream.codec_context.channels == 2:
                    audio_data = audio_samples.flatten().tobytes()
                else:
                    audio_data = audio_samples.repeat(2).flatten().tobytes()
                while audio_queue.full() and audio_thread_running:
                    pass
                if audio_thread_running:
                    audio_queue.put(audio_data)
            audio_container.seek(0)
        except Exception as e:
            print(f"音频解码错误: {e}")
            continue

def audio_playback_thread_func():
    global audio_thread_running
    while audio_thread_running:
        try:
            if audio_queue.empty():
                pygame.time.delay(10)
                continue
            frame_data = audio_queue.get()
            pygame.mixer.Sound(buffer=frame_data).play()
        except Exception as e:
            print(f"音频播放错误: {e}")
            continue

if audio_stream and av:
    audio_decode_thread = threading.Thread(target=audio_decoding_thread, daemon=True)
    audio_decode_thread.start()
    audio_playback_thread = threading.Thread(target=audio_playback_thread_func, daemon=True)
    audio_playback_thread.start()

# ====================================================

WH = WINDOW_HEIGHT
WW = int(WH / ratio)

import os
os.environ['SDL_VIDEO_WINDOW_POS'] = f"{POS_X},{POS_Y}"

screen = pygame.display.set_mode((WW, WH), pygame.NOFRAME | pygame.SRCALPHA)
hwnd = pygame.display.get_wm_info()["window"]
user32.ShowWindow(hwnd, SW_HIDE)
make_layered_window(hwnd)

running = True
clock = pygame.time.Clock()
dragging = False
drag_offset_x = 0
drag_offset_y = 0
current_x, current_y = POS_X, POS_Y

print(f"\n播放中... 分辨率: {vw}x{vh}, FPS: {fps}")
print(f"是否有透明通道: {'是' if has_alpha else '否'}")
print(f"是否有音频: {'是' if audio_stream else '否'}")
print("按 ESC 退出，鼠标拖动可移动窗口，滚轮可缩放画面")

fps = float(fps) if fps else 30

def get_frame():
    first_frame = True
    if av and container:
        while True:
            try:
                frame_count = 0
                for frame in container.decode(video=0):
                    argb_frame = frame.to_ndarray(format='argb')
                    
                    if first_frame:
                        print("\n=== 像素数据格式日志 ===")
                        print(f"ARGB 原始数据: shape={argb_frame.shape}, dtype={argb_frame.dtype}")
                        print(f"ARGB 通道0 (Alpha): min={argb_frame[:, :, 0].min()}, max={argb_frame[:, :, 0].max()}, mean={argb_frame[:, :, 0].mean():.2f}")
                        print(f"ARGB 通道1: min={argb_frame[:, :, 1].min()}, max={argb_frame[:, :, 1].max()}, mean={argb_frame[:, :, 1].mean():.2f}")
                        print(f"ARGB 通道2: min={argb_frame[:, :, 2].min()}, max={argb_frame[:, :, 2].max()}, mean={argb_frame[:, :, 2].mean():.2f}")
                        print(f"ARGB 通道3: min={argb_frame[:, :, 3].min()}, max={argb_frame[:, :, 3].max()}, mean={argb_frame[:, :, 3].mean():.2f}")
                        print(f"\n中心像素值:")
                        print(f"  ARGB: {argb_frame[argb_frame.shape[0]//2, argb_frame.shape[1]//2]}")
                        print("=== 日志结束 ===\n")
                        first_frame = False
                    
                    rgba_frame = np.zeros((argb_frame.shape[0], argb_frame.shape[1], 4), dtype=np.uint8)
                    rgba_frame[:, :, 0] = argb_frame[:, :, 3]
                    rgba_frame[:, :, 1] = argb_frame[:, :, 2]
                    rgba_frame[:, :, 2] = argb_frame[:, :, 1]
                    rgba_frame[:, :, 3] = argb_frame[:, :, 0]
                    
                    yield rgba_frame
                    frame_count += 1
                if frame_count == 0:
                    raise Exception("没有读取到任何帧")
                container.seek(0)
            except Exception as e:
                print(f"解码错误: {e}")
                container.seek(0)
                continue
    else:
        while True:
            ret, frame = cap.read()
            if not ret:
                cap.set(cv2.CAP_PROP_POS_FRAMES, 0)
                continue
            if frame.shape[2] == 4:
                yield cv2.cvtColor(frame, cv2.COLOR_BGRA2RGBA)
            else:
                rgba = cv2.cvtColor(frame, cv2.COLOR_BGR2RGBA)
                rgba[:, :, 3] = 255
                yield rgba

frame_generator = get_frame()

try:
    init_frame = next(frame_generator)
    init_frame = cv2.flip(init_frame, 0)
    init_frame = cv2.resize(init_frame, (WW, WH))
    init_frame = np.ascontiguousarray(init_frame, dtype=np.uint8)
    init_surf = pygame.image.frombuffer(init_frame.tobytes(), (WW, WH), 'RGBA')
    update_layered_window(hwnd, init_surf, POS_X, POS_Y)
except Exception as e:
    print(f"初始化第一帧失败: {e}")

user32.ShowWindow(hwnd, SW_SHOW)

clock = pygame.time.Clock()

while running:
    for event in pygame.event.get():
        if event.type == pygame.QUIT or (event.type == pygame.KEYDOWN and event.key == pygame.K_ESCAPE):
            running = False

        if event.type == pygame.MOUSEBUTTONDOWN:
            dragging = True
            mx, my = get_cursor_pos()
            drag_offset_x = mx - current_x
            drag_offset_y = my - current_y

        if event.type == pygame.MOUSEBUTTONUP:
            dragging = False

        if event.type == pygame.MOUSEMOTION and dragging:
            mx, my = get_cursor_pos()
            current_x = mx - drag_offset_x
            current_y = my - drag_offset_y

        if event.type == pygame.MOUSEWHEEL:
            scale_factor = 1.1 if event.y > 0 else 0.9
            new_wh = int(WH * scale_factor)
            new_wh = max(100, min(new_wh, 2000))
            new_ww = int(new_wh / ratio)
            
            mx, my = get_cursor_pos()
            rel_x = mx - current_x
            rel_y = my - current_y
            
            WW = new_ww
            WH = new_wh
            current_x = mx - rel_x
            current_y = my - rel_y
            
            ctypes.windll.user32.SetWindowPos(hwnd, 0, int(current_x), int(current_y), WW, WH, 0x0001)

    try:
        frame = next(frame_generator)
    except StopIteration:
        frame_generator = get_frame()
        frame = next(frame_generator)
    
    try:
        frame = cv2.flip(frame, 0)
        frame = cv2.resize(frame, (WW, WH))
        frame = np.ascontiguousarray(frame, dtype=np.uint8)
        surf = pygame.image.frombuffer(frame.tobytes(), (WW, WH), 'RGBA')
        update_layered_window(hwnd, surf, int(current_x), int(current_y))
        
    except Exception as e:
        import traceback
        print(f"渲染错误: {e}")
        print(traceback.format_exc())
        continue

    clock.tick(fps)

audio_thread_running = False
if av and container:
    container.close()
    if audio_container:
        audio_container.close()
else:
    cap.release()

pygame.quit()
