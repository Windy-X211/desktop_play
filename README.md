# 桌面透明视频播放器 (desktop_play)

一个运行在 Windows 桌面上的**透明视频播放器**：把带 Alpha 通道的视频（MOV / ProRes 4444 / QuickTime RLE 等）以无边框、无背景的方式直接叠在桌面上，可以拖动、缩放、置顶、锁定，也可以当作动态桌宠、动态壁纸或桌面 HUD 使用。

内核不用色键抠图，而是通过 **Win32 分层窗口（UpdateLayeredWindow）+ 逐像素 Alpha 混合** 渲染，因此半透明边缘、柔和阴影、发光效果都能正常显示，不会出现绿边或硬边。

## 功能特性

- **真透明叠加**：`WS_EX_LAYERED` + `UpdateLayeredWindow` 逐帧提交 RGBA 位图，源视频的 Alpha 通道原样保留
- **无边框、不抢焦点**：窗口带 `WS_EX_NOACTIVATE | WS_EX_TOOLWINDOW`，不占任务栏、点击不打断当前工作
- **鼠标交互**
  - 左键拖拽移动视频窗口（拖出窗口外也不会断）
  - 滚轮以鼠标位置为锚点等比缩放（高度限制 100–3000 px）
- **置顶 / 固定**：置顶带后台守护线程，被其他程序抢到最前时会自动拉回；「固定」可临时锁掉拖拽与缩放，防止误碰
- **播放控制**：顺序播放 / 单曲循环 / 随机播放、上一个 / 下一个、暂停、静音
- **音画同步**：视频按 `PlayClock` 的墙钟节奏出帧，严重落后时自动丢帧；音频由 ffmpeg 解码后交给 pygame 播放并与画面同一起点
- **位置记忆**：初始 X / Y / 高度可设置，关闭时写入配置文件，下次启动自动恢复上次的文件夹与窗口状态
- **一键隐藏**：不退出程序即可临时隐藏视频窗口

## 目录结构

```
桌面展示/
├── mov_play.py          # 主程序：完整 GUI 播放器（PyQt5 控制面板 + pygame 渲染窗口）
├── mp4_play.py          # 极简示例：纯透明窗口 + ffmpeg 管道解码（PySide6，无控制面板）
├── play_with_sound.py   # 早期原型：单文件版，路径/位置写在代码顶部常量里
├── .mov_play_config.json# 运行后自动生成的本地配置（已被 .gitignore 忽略）
└── README.md
```

三个脚本是同一套思路的不同阶段版本，日常使用只需要 `mov_play.py`。

## 环境要求

| 项目 | 说明 |
| --- | --- |
| 操作系统 | Windows 10 / 11（依赖 Win32 GDI 分层窗口 API，**不支持** macOS / Linux） |
| Python | 3.9 及以上（开发环境为 3.13） |
| 外部程序 | **ffmpeg**，需在 `PATH` 中可用（音频解码依赖它；缺失则静音播放） |

### 安装依赖

```bash
pip install PyQt5 pygame opencv-python av numpy
```

可选（仅运行 `mp4_play.py` 时需要）：

```bash
pip install PySide6 ffmpeg-python
```

安装 ffmpeg（任选其一）：

```bash
winget install Gyan.FFmpeg
# 或从 https://www.gyan.dev/ffmpeg/builds/ 下载后把 bin 目录加入 PATH
```

验证：

```bash
ffmpeg -version
```

## 快速开始

```bash
python mov_play.py
```

1. 点「**选择文件夹**」，选中存放视频的目录，列表会自动列出该目录下的视频文件
2. **双击**列表中的某一项开始播放，视频窗口会按视频原始宽高比出现在桌面上
3. 在「初始X / 初始Y / 初始高度」里填好位置和高度，点「**初始化**」应用；调整好位置后点「**设为初始值**」可把当前位置存回输入框，「恢复默认」回到 `200, 150, 900`
4. 勾选「**置顶窗口**」让它常驻最前层；勾选「**固定**」锁掉拖拽与缩放
5. 右键不需要？直接关掉控制面板即可退出，配置会自动保存

> 配置文件 `.mov_play_config.json` 与脚本同目录，记录上次文件夹、位置、高度、锁定与静音状态。

## 视频格式说明

支持扫描的扩展名：`.mov` `.mp4` `.avi` `.mkv` `.flv` `.wmv` `.webm` `.m4v`

**想要透明效果，源视频必须自带 Alpha 通道**，常见做法：

| 编码 / 容器 | 说明 |
| --- | --- |
| QuickTime MOV + **ProRes 4444** | 影视后期最常用，透明质量最好，文件较大 |
| QuickTime MOV + **QuickTime RLE (Animation)** | 传统 GIF 类动画的透明方案，适合扁平风格素材 |
| MOV / WebM + **PNG / VP9 Alpha** | 无损或高压缩比的透明方案 |
| MP4 + H.264 | **没有 Alpha 通道**，播放时是一个不透明矩形，只适合普通画面 |

导出时注意勾选「包含 Alpha 通道 / 使用 Alpha 通道渲染」，并把背景设为透明而不是纯黑或纯绿。

## 工作原理

```
视频文件
  ├─ PyAV 解码视频流 ──► BGRA/RGBA 帧 ──► pygame.image.frombuffer (SRCALPHA)
  │                                        ├─ 尺寸不同则 smoothscale 到窗口尺寸
  │                                        └─ UpdateLayeredWindow 提交到分层窗口
  └─ ffmpeg 管道解码音频 ──► PCM s16le 44.1kHz 立体声 ──► pygame.mixer.Sound 播放
                                                        └─ PlayClock 对齐音画起点
```

- **窗口**：pygame 创建 `NOFRAME | SRCALPHA` 的 SDL 窗口，取出 HWND 后改为分层窗口并加 `NOACTIVATE / TOOLWINDOW` 扩展样式
- **渲染**：`UpdateLayeredWindow` 一次性提交带 Alpha 的位图，绕开普通 GDI 绘制的合成限制
- **节流**：以「帧序号 × 帧间隔」推算目标墙钟时间，晚到超过 40 ms 直接丢帧，保证长时间播放不越滑越慢
- **事件**：`SetWindowLongPtrW` 子类化窗口过程，把滚轮 / 左键消息压入队列，由 Qt 定时器（8 ms）在主线程消费
- **解码回退**：PyAV 打不开时自动回退到 OpenCV `VideoCapture`

## 常见问题

**播放出来是一块黑色 / 白色矩形，没有透明**
源视频没有 Alpha 通道。用含 ProRes 4444 / PNG / VP9 Alpha 的 MOV 或 WebM 重新导出，而不是 MP4 + H.264。

**没有声音**
`ffmpeg` 不在 `PATH` 里。装好后重启终端；也可在代码第 305 行附近把 `'ffmpeg'` 改成绝对路径。

**视频窗口点不动 / 拖不了**
检查是否勾选了「固定」。取消勾选即可恢复拖拽与滚轮缩放。

**画面卡顿或掉帧**
把「初始高度」调小（如 900 → 600）以降低合成像素量；同时确认使用的是 PyAV 而非 OpenCV 回退路径（终端会打印解码器信息）。

**窗口位置和高 DPI 不对**
Windows 缩放比例大于 100% 时，SDL 与 Win32 的坐标口径可能不一致，建议在「显示设置 → 缩放」设为 100%，或直接拖动窗口到合适位置后点「设为初始值」。

**关闭后视频仍在最前层**
程序被强制结束时 pygame 窗口可能残留，重新运行一次程序并正常关闭即可；置顶守护线程只在运行期间生效。
