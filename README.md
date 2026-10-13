# PixelFactory 像素工厂

一款 Windows 桌面端**图片快速处理与批量格式转换**工具。深色现代界面，拖拽即用，零学习成本。

![Python](https://img.shields.io/badge/Python-3.10+-blue) ![GUI](https://img.shields.io/badge/GUI-ttkbootstrap%20(dark)-green) ![License](https://img.shields.io/badge/License-MIT-yellow)

## 功能特性

- **全格式互转**：WebP / JPG / PNG / BMP / GIF / TIFF / ICO / TGA / PPM 输入，JPG / PNG / WEBP / BMP / TIFF / ICO 输出
- **拖拽导入**：图片或整个文件夹直接拖进窗口，递归扫描子目录
- **双栏实时预览**：点击左侧缩略图列表，中间看原图、右侧实时看转换效果，分辨率一目了然
- **保持比例的五种缩放模式**：
  - 不缩放 / 指定宽度 / 指定高度
  - 适配框（不超过）：保证结果 ≤ 指定宽高
  - 保证不小于宽×高：短边也达标，适合「网站要求分辨率不低于多少」的场景
- **框选裁剪**：iPhone 风格矩形选框，8 个控制点 + 整体移动 + 三分构图线，双栏实时预览
- **旋转校正**：角度条 / 精确输入（0.01°），修正倾斜照片，画布自动扩展
- **质量滑块**：JPG / WEBP 输出质量 50–100 实时可调
- **配置自动存盘**：格式、尺寸、质量、输出目录、文件列表全部自动记忆，重启即恢复
- **输出目录联动**：更换输入来源自动重置输出目录，支持一键清除
- **智能落盘**：未指定输出目录时跟随所选图片原目录；同名文件自动加序号（name(1).jpg），永不覆盖
- **暗色主题**：ttkbootstrap darkly + DWM 暗色标题栏，跟随系统深色风格

## 快速开始

### 直接使用（推荐）

从 [Releases](../../releases) 下载 `PixelFactory.exe`，双击即用，可固定到任务栏。

### 从源码运行

```bash
pip install pillow ttkbootstrap tkinterdnd2
python pixelfactory.py
```

命令行批量模式：

```bash
python pixelfactory.py -f png -w 1920 -o 输出目录 图片文件夹
```

### 打包

```bash
pyinstaller --onefile --windowed --name "PixelFactory" \
  --collect-all tkinterdnd2 --collect-all ttkbootstrap pixelfactory.py
```

## 技术栈

Python · tkinter / ttkbootstrap · Pillow · tkinterdnd2 · Windows DWM

## License

MIT
