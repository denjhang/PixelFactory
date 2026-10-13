# PixelFactory 开发文档

## 项目结构

```
pixelfactory.py    # 全部代码（单文件，约 1200 行）
一键转换.bat        # 开发期双击启动入口
dist/              # pyinstaller 产物（gitignore）
%APPDATA%/ImageConverter/config.json   # 用户配置（自动存盘）
```

## 架构概览

```
┌─────────────────────────────────────────────────────┐
│ UI 线程（tkinter mainloop，60Hz 事件循环）              │
│  · 三栏布局：缩略图列表 | 原图预览(Canvas) | 转换预览      │
│  · 工具栏：框选裁剪 / 旋转校正(0.01° 精度)               │
│  · _cv_poll：15ms 贴帧循环（预览帧 + 转换进度队列）       │
│  · _poll_thumbs：80ms 缩略图上屏循环                    │
└──────────────┬──────────────────────┬────────────────┘
               │ 后台线程               │ 后台线程
      缩略图生成 worker          转换预览 worker(_cv_worker)
      （结果入 _thumb_queue）    （结果入 _cv_queue，丢旧帧）
                                        │
                              最终保存 _worker（全分辨率）
```

**线程纪律：工作线程只生产数据入队列，绝不直接碰 UI；主线程轮询消费。**
跨线程直接调 `widget.after` / `config` 在 mainloop 未运行或高负载时会崩溃，已两次踩坑（缩略图、转换进度），务必走队列。

## 图像管线

```
compose(im, resize_mode, tw, th, crop, angle, resample)
  裁剪(crop) → 旋转(expand=True, 正值顺时针) → 五种保持比例缩放
```

两条管线严格分离：

| 管线 | 源 | 采样 | 用途 |
|---|---|---|---|
| 预览 | `_pv_src` 缓存（≤1000px 降采样副本） | BILINEAR | 拖动/角度实时预览 |
| 保存 | 全分辨率原图，每次现读 | BICUBIC | 一键转换落盘 |

- 预览 worker 在旋转前把图缩到 ≤640px（显示上限），旋转成本与像素数成正比
- 预览面板显示的分辨率信息 = `预览尺寸 ÷ (factor×f2)` 换算回真实输出尺寸
- JPG/BMP/ICO 输出前必须把 RGBA 压平到 RGB（白底）——**这步曾丢失导致保存全挂，勿动**

## 关键设计决策（踩坑记录）

1. **UI 线程零图像运算**：拖动裁剪框时主线程只置脏标记（实测 0.4ms/事件），
   合成在后台线程，贴帧时丢弃过期帧。这是流畅度的根基，改预览逻辑前先读懂
   `_update_converted_preview → _cv_worker → _cv_poll` 这条链。
2. **裁剪框交互统一绝对定位**：`_crop_drag["rect0"]` 记录按下时框位置，
   位移 = 当前鼠标 − 按下点。移动模式曾用「上一帧位置 + 相对位移」累加，
   事件密集时产生肉眼可见的"惯性漂移"，禁止改回。
3. **控制点命中**：命中半径 10px（视觉 5px），角优先于边；框缘外侧 6px 内
   判定为抓边而非重选；"new" 模式拖动 <6px 视为误触，恢复原框。
4. **`_pane_disp` 以 `id(pane字典)` 为键**——不是 id(canvas)。曾因键不一致
   导致整个拖动逻辑静默失效（查字典得 None 直接 return）。
5. **配置自动存盘**：任何设置变更立即写 `config.json`（含文件列表），
   无保存按钮；清空列表 = 主动清除记忆。写文件在主线程做（小文件，量低）。
6. **同名去重**：`unique_path()` 在落盘前检查，`name(1).ext` 递增，永不覆盖。
7. **暗色一致性**：所有 ttk 控件统一 `style.configure('TFrame/TLabel', background=BG)`，
   禁止单控件指定 bootstyle 背景色（会和窗口底色形成色块）。
8. **任务栏身份**：`SetCurrentProcessExplicitAppUserModelID("Denjhang.PixelFactory.1")`
   让 exe 可独立固定任务栏；标题栏暗色用 DWMWA_USE_IMMERSIVE_DARK_MODE(20/19)。

## 已知限制

- tkinter 无 GPU 加速，预览帧率上限约 30-60fps（当前瓶颈不在算力）
- 系统消息框（messagebox）跟随系统主题，不可定制；仅保留"未添加图片"一处提示
- GIF 转换取第一帧；ICO 输出使用原图尺寸单一帧
- 输入源变化时输出目录自动重置为"跟随原目录"（`_input_root` 比较 dirname）

## 构建与发布

```bash
# 打包（单文件，约 37MB）
pyinstaller --noconfirm --onefile --windowed --name "PixelFactory" \
  --icon "$APPDATA/ImageConverter/icon.ico" \
  --collect-all tkinterdnd2 --collect-all ttkbootstrap pixelfactory.py

# 发布流程
git add -A && git commit -m "..." && git push
```

## 命令行模式

```bash
python pixelfactory.py -f png -w 1920 -o 输出目录 图片或文件夹...
```

## 测试方式

无自动化测试框架；改动的标准验证流程：
1. `python -c "import ast; ast.parse(...)"` 语法检查
2. 用模拟鼠标事件（构造 `class E: x,y`）驱动 `_crop_press/_crop_drag_motion/_crop_release`
   验证裁剪交互
3. 用 4000×3000 测试图计时拖动/角度事件，确认 UI 线程阻塞 <1ms
4. 全链路转换一次，核对输出格式、尺寸、透明压平
