# -*- coding: utf-8 -*-
"""万能图片格式转换工具（ttkbootstrap 暗色界面 + Pillow + 拖拽支持）"""
import json
import os
import queue
import sys
import threading
import tkinter as tk
import tkinter.font as tkfont
from tkinter import filedialog, messagebox

import ttkbootstrap as ttkb
from ttkbootstrap.constants import BOTH, LEFT, RIGHT, X, Y, END, W, NW

from PIL import Image, ImageTk

try:
    from tkinterdnd2 import TkinterDnD
    HAS_DND = True
except ImportError:
    HAS_DND = False

Image.MAX_IMAGE_PIXELS = None

BG = "#1a1c24"
PANEL = "#22252f"
FG = "#f2f4f8"
FG_DIM = "#c6cbd8"
ACCENT = "#4dd8a3"

# 输出格式: (显示名, 扩展名, Pillow格式名, 是否支持透明)
OUT_FORMATS = [
    ("JPG", ".jpg", "JPEG", False),
    ("PNG", ".png", "PNG", True),
    ("WEBP", ".webp", "WEBP", True),
    ("BMP", ".bmp", "BMP", False),
    ("TIFF", ".tiff", "TIFF", True),
    ("ICO", ".ico", "ICO", False),
]
# 可接受的输入扩展名（Pillow 常见可读格式）
IN_EXTS = {".webp", ".jpg", ".jpeg", ".png", ".bmp", ".gif", ".tiff", ".tif",
           ".ico", ".tga", ".ppm", ".pgm", ".pbm", ".jfif"}

# ── 配置持久化：设置与文件列表自动存盘，无需手动保存 ──
CONFIG_DIR = os.path.join(os.environ.get("APPDATA", os.path.expanduser("~")),
                          "ImageConverter")
CONFIG_PATH = os.path.join(CONFIG_DIR, "config.json")


def build_output_image(src: str, fmt_name: str, quality: int,
                       resize_mode: str, target_w: int, target_h: int) -> Image.Image:
    """按当前设置生成输出图像（内存中，供保存与预览共用）"""
    with Image.open(src) as im:
        first = im.convert("RGBA") if im.mode != "RGBA" else im.copy()

        # ── 缩放（均保持宽高比例） ──
        w, h = first.size
        tw, th = target_w, target_h
        if resize_mode == "w" and tw > 0:
            th = max(1, round(h * tw / w))
            first = first.resize((tw, th), Image.LANCZOS)
        elif resize_mode == "h" and th > 0:
            tw = max(1, round(w * th / h))
            first = first.resize((tw, th), Image.LANCZOS)
        elif resize_mode == "fit" and (tw > 0 or th > 0):
            tw = tw or th * w // h
            th = th or tw * h // w
            ratio = min(tw / w, th / h)
            first = first.resize((max(1, round(w * ratio)), max(1, round(h * ratio))), Image.LANCZOS)
        elif resize_mode == "min" and tw > 0 and th > 0:
            # 短边也要达到目标，保证结果宽高同时 ≥ 指定值，可能超出但绝不小于
            ratio = max(tw / w, th / h)
            first = first.resize((max(1, round(w * ratio)), max(1, round(h * ratio))), Image.LANCZOS)

        # ── 透明通道处理 ──
        if not _supports_alpha(fmt_name) and first.mode == "RGBA":
            bg = Image.new("RGB", first.size, (255, 255, 255))
            bg.paste(first, mask=first.split()[-1])
            return bg
        return first


def convert_one(src: str, dst: str, fmt_name: str, quality: int,
                resize_mode: str, target_w: int, target_h: int) -> None:
    out = build_output_image(src, fmt_name, quality, resize_mode, target_w, target_h)
    save_kwargs = {}
    if fmt_name == "JPEG":
        save_kwargs = {"quality": quality, "subsampling": 0 if quality >= 92 else 2}
    elif fmt_name == "WEBP":
        save_kwargs = {"quality": quality}
    elif fmt_name == "ICO":
        save_kwargs = {"sizes": [out.size]}
    out.save(dst, fmt_name, **save_kwargs)


def _supports_alpha(fmt_name: str) -> bool:
    for _n, _e, f, alpha in OUT_FORMATS:
        if f == fmt_name:
            return alpha
    return False


class App:
    def __init__(self, root: ttkb.Window):
        self.root = root
        self.files: list[str] = []
        self.out_dir: str | None = None
        self.running = False
        self._build_ui()
        if HAS_DND:
            self._setup_dnd()
        self._restore_config()  # 在所有控件创建完成后恢复上次的配置

    # ────────────────── 界面 ──────────────────
    def _build_ui(self):
        r = self.root
        r.configure(bg=BG)
        # 所有 ttk 控件统一继承窗口背景色，避免文字底下出现异色块
        style = ttkb.Style()
        style.configure('TFrame', background=BG)
        style.configure('TLabel', background=BG, foreground=FG)

        # 标题
        header = ttkb.Frame(r, padding=(24, 18, 24, 6))
        header.pack(fill=X)
        ttkb.Label(header, text="图片格式转换", font=("Segoe UI Semibold", 20),
                   foreground=FG).pack(side=LEFT)
        ttkb.Label(header, text="  WebP / JPG / PNG / GIF / BMP / TIFF 互转",
                   font=("Segoe UI", 10), foreground=FG_DIM,
).pack(side=LEFT, pady=(8, 0))

        # ── 三栏主区：文件列表 | 原图预览 | 转换后预览 ──
        main = ttkb.Frame(r)
        main.pack(fill=BOTH, expand=True, padx=24, pady=(0, 0))

        # 左栏：操作按钮 + 文件列表
        left = ttkb.Frame(main, width=300)
        left.pack(side=LEFT, fill=Y, padx=(0, 12))
        left.pack_propagate(False)
        btns = ttkb.Frame(left)
        btns.pack(fill=X, pady=(0, 8))
        ttkb.Button(btns, text="＋ 图片", bootstyle="primary", width=8,
                    command=self.pick_files).pack(side=LEFT, padx=(0, 6))
        ttkb.Button(btns, text="📁 文件夹", bootstyle="primary-outline", width=9,
                    command=self.pick_folder).pack(side=LEFT, padx=(0, 6))
        ttkb.Button(btns, text="🗑", bootstyle="secondary-outline", width=3,
                    command=self.clear_list).pack(side=LEFT)
        list_card = tk.Frame(left, bg=PANEL, highlightthickness=1,
                             highlightbackground="#31354a")
        list_card.pack(fill=BOTH, expand=True)
        # 可滚动缩略图列表：每行 = 缩略图 + 文件名 + 多行路径
        self.canvas = tk.Canvas(list_card, bg=PANEL, highlightthickness=0, bd=0)
        sb = ttkb.Scrollbar(list_card, orient="vertical", command=self.canvas.yview,
                            bootstyle="dark-round")
        self.list_inner = tk.Frame(self.canvas, bg=PANEL)
        self.canvas.create_window((0, 0), window=self.list_inner, anchor=NW,
                                  tags="inner")
        self.list_inner.bind("<Configure>",
                             lambda _e: self.canvas.configure(
                                 scrollregion=self.canvas.bbox("all")))
        self.canvas.bind("<Configure>", self._on_list_resize)
        self.canvas.configure(yscrollcommand=sb.set)
        self.canvas.pack(side=LEFT, fill=BOTH, expand=True, padx=1, pady=1)
        sb.pack(side=RIGHT, fill=Y)
        self.canvas.bind("<MouseWheel>", self._on_mousewheel)
        self.canvas.bind("<Button-4>", self._on_mousewheel)
        self.canvas.bind("<Button-5>", self._on_mousewheel)
        self.empty_hint = tk.Label(list_card, text="拖入图片\n或点击上方按钮添加",
                                   font=("Segoe UI", 10), fg=FG_DIM,
                                   bg=PANEL, bd=0, justify="center")
        self.empty_hint.place(relx=0.5, rely=0.35, anchor="center")
        self._rows = {}         # 路径 -> 行控件
        self._thumb_cache = {}  # 路径 -> 缩略图 PhotoImage
        # 透明占位图，保证行高固定为像素单位
        self._thumb_ph = ImageTk.PhotoImage(
            Image.new("RGBA", (self.THUMB, self.THUMB), (0, 0, 0, 0)))
        self.selected = None    # 当前选中索引
        self._wrap = 160        # 路径换行宽度
        self._thumb_queue = queue.Queue()
        self.root.after(80, self._poll_thumbs)  # 主线程轮询缩略图结果
        self.count_var = ttkb.StringVar(value="0 个文件")
        ttkb.Label(left, textvariable=self.count_var, font=("Segoe UI", 9),
                   foreground=FG_DIM).pack(anchor="e", pady=(4, 0))

        # 中栏：原图预览
        self.preview_original = self._make_preview_pane(main, "原图预览")
        ttkb.Separator(main, orient="vertical", bootstyle="secondary").pack(
            side=LEFT, fill=Y, padx=6, pady=8)
        # 右栏：转换后预览
        self.preview_converted = self._make_preview_pane(main, "转换后预览")

        self._preview_imgs = {}  # 防止 PhotoImage 被回收
        self._pane_src = {}      # 各面板当前完整图像（供重绘）
        self._src_size = None    # 当前选中原图尺寸

        # 选项区：输出格式 / 尺寸 / 质量 / 输出目录
        opts = ttkb.Frame(r, padding=(24, 8, 24, 0))
        opts.pack(fill=X)

        g1 = ttkb.Frame(opts)
        g1.pack(side=LEFT, padx=(0, 28))
        ttkb.Label(g1, text="输出格式", font=("Segoe UI", 9), foreground=FG_DIM,
).pack(anchor=W)
        self.fmt_var = ttkb.StringVar(value="JPG")
        self.fmt_combo = ttkb.Combobox(g1, textvariable=self.fmt_var, state="readonly",
                                       values=[f[0] for f in OUT_FORMATS], width=8,
                                       font=("Segoe UI", 10))
        self.fmt_combo.pack(pady=(2, 0))
        self.fmt_combo.bind("<<ComboboxSelected>>", lambda _e: self._fmt_changed())

        g2 = ttkb.Frame(opts)
        g2.pack(side=LEFT, padx=(0, 28))
        ttkb.Label(g2, text="尺寸调整", font=("Segoe UI", 9), foreground=FG_DIM,
).pack(anchor=W)
        self.resize_mode_var = ttkb.StringVar(value="不缩放")
        rc = ttkb.Combobox(g2, textvariable=self.resize_mode_var, state="readonly",
                           values=["不缩放", "指定宽度", "指定高度", "适配框(不超过)", "保证不小于宽×高"],
                           width=15, font=("Segoe UI", 10))
        rc.pack(pady=(2, 0))
        rc.bind("<<ComboboxSelected>>",
                lambda _e: (self._update_converted_preview(), self._save_config()))

        g3 = ttkb.Frame(opts)
        g3.pack(side=LEFT, padx=(0, 28))
        ttkb.Label(g3, text="宽 × 高 (像素)", font=("Segoe UI", 9), foreground=FG_DIM,
).pack(anchor=W)
        srow = ttkb.Frame(g3)
        srow.pack(pady=(2, 0))
        self.w_var = ttkb.StringVar(value="1920")
        self.h_var = ttkb.StringVar(value="1080")
        for var in (self.w_var, self.h_var):
            e = ttkb.Entry(srow, textvariable=var, width=6, font=("Segoe UI", 10))
            e.pack(side=LEFT)
            e.bind("<Return>", lambda _e: (self._update_converted_preview(), self._save_config()))
            e.bind("<FocusOut>", lambda _e: (self._update_converted_preview(), self._save_config()))
        ttkb.Label(srow, text=" × ", foreground=FG_DIM).pack(side=LEFT)

        g4 = ttkb.Frame(opts)
        g4.pack(side=LEFT, padx=(0, 28))
        ttkb.Label(g4, text="质量", font=("Segoe UI", 9), foreground=FG_DIM,
).pack(anchor=W)
        qrow = ttkb.Frame(g4)
        qrow.pack(pady=(2, 0))
        self.scale = ttkb.Scale(qrow, from_=50, to=100, value=90,
                                bootstyle="success", length=120,
                                command=self._on_quality)
        self.scale.pack(side=LEFT)
        self.q_label = ttkb.Label(qrow, text="90", font=("Segoe UI Semibold", 11),
                                  foreground=ACCENT, width=3)
        self.q_label.pack(side=LEFT, padx=(8, 0))

        # 更改输出目录按钮放在质量右侧的空白区
        ttkb.Button(opts, text="更改输出目录…", bootstyle="secondary-outline",
                    command=self.pick_out_dir).pack(side=RIGHT, padx=(0, 8), pady=(10, 0))
        ttkb.Button(opts, text="✕ 清除输出目录", bootstyle="danger-outline",
                    command=self.clear_out_dir).pack(side=RIGHT, pady=(10, 0))

        # 输出目录路径独占一行，与按钮互不挤占
        opts2 = ttkb.Frame(r, padding=(24, 8, 24, 0))
        opts2.pack(fill=X)
        g5 = ttkb.Frame(opts2)
        g5.pack(fill=X)
        ttkb.Label(g5, text="输出目录:", font=("Segoe UI", 10), foreground=FG_DIM,
).pack(side=LEFT, padx=(0, 6))
        self.out_full = "默认：与原文件同目录"
        self.out_var = ttkb.StringVar(value=self.out_full)
        self.out_label = ttkb.Label(g5, textvariable=self.out_var,
                                    font=("Segoe UI", 10), foreground=FG,
                                    anchor=W)
        self.out_label.pack(fill=X, expand=True)
        g5.bind("<Configure>", lambda _e: self._update_out_text())

        # 底部
        bottom = ttkb.Frame(r, padding=(24, 10, 24, 20))
        bottom.pack(fill=X)
        self.convert_btn = ttkb.Button(bottom, text="⚡ 一键转换", bootstyle="success",
                                       command=self.start_convert)
        self.convert_btn.pack(side=LEFT, padx=(0, 16), ipadx=14, ipady=2)
        self.progress = ttkb.Progressbar(bottom, mode="determinate",
                                         bootstyle="success-striped")
        self.progress.pack(side=LEFT, fill=X, expand=True, pady=(6, 0))
        self.status_var = ttkb.StringVar(value="就绪")
        ttkb.Label(bottom, textvariable=self.status_var, font=("Segoe UI", 9),
                   foreground=FG_DIM, width=30, anchor="e",
).pack(side=RIGHT, padx=(12, 0))

    # ────────────────── 拖拽 ──────────────────
    def _setup_dnd(self):
        try:
            TkinterDnD._require(self.root)
            self.root.drop_target_register("DND_Files", "DND_Folder")
            self.root.dnd_bind("<<Drop>>", self._on_drop)
        except Exception as e:
            print("拖拽初始化失败:", e, file=sys.stderr)

    def _on_drop(self, event):
        paths = self.root.tk.splitlist(event.data)
        files = []
        for p in paths:
            if os.path.isdir(p):
                for dp, _d, ns in os.walk(p):
                    files += [os.path.join(dp, n) for n in ns
                              if os.path.splitext(n)[1].lower() in IN_EXTS]
            elif os.path.splitext(p)[1].lower() in IN_EXTS:
                files.append(p)
        self.add_files(files)

    # ────────────────── 交互 ──────────────────
    def _on_quality(self, _=None):
        self.q_label.config(text=str(int(float(self.scale.get()))))
        self._update_converted_preview()
        self._save_config()

    # ────────────────── 缩略图列表 ──────────────────
    THUMB = 48  # 缩略图边长（像素）

    def _selected_index(self):
        if self.selected is not None and 0 <= self.selected < len(self.files):
            return self.selected
        return None

    def _on_list_resize(self, event):
        self._wrap = max(event.width - 84, 60)
        for p, row in self._rows.items():
            row["path"].config(wraplength=self._wrap)

    def _on_mousewheel(self, event):
        delta = -1 if getattr(event, "delta", 0) > 0 or event.num == 4 else 1
        self.canvas.yview_scroll(delta, "units")

    def _render_list(self):
        # 移除已删除的行
        for p in list(self._rows):
            if p not in self.files:
                self._rows[p]["frame"].destroy()
                del self._rows[p]
        # 按当前顺序重建（行数少，直接全量重排）
        for w in self.list_inner.winfo_children():
            w.pack_forget()
        for i, p in enumerate(self.files):
            row = self._rows.get(p)
            if row is None:
                row = self._make_row(p)
                self._rows[p] = row
            row["frame"].pack(fill=X, pady=(1, 0))
            self._apply_row_style(row, i == self.selected)
        self._update_count()
        if not self.files:
            self.empty_hint.place(relx=0.5, rely=0.35, anchor="center")
        else:
            self.empty_hint.place_forget()

    def _make_row(self, path: str):
        frame = tk.Frame(self.list_inner, bg=PANEL, cursor="hand2")
        thumb = tk.Label(frame, image=self._thumb_ph, bg=PANEL, bd=0)
        thumb.pack(side=LEFT, padx=(5, 7), pady=5)
        texts = tk.Frame(frame, bg=PANEL)
        texts.pack(side=LEFT, fill=X, expand=True, pady=4)
        name = tk.Label(texts, text=os.path.basename(path), anchor=W,
                        font=("Segoe UI Semibold", 9), fg=FG, bg=PANEL)
        name.pack(fill=X)
        pathl = tk.Label(texts, text=os.path.dirname(path), anchor=NW,
                         font=("Segoe UI", 7), fg=FG_DIM, bg=PANEL,
                         wraplength=self._wrap, justify=LEFT)
        pathl.pack(fill=X)
        row = {"frame": frame, "thumb": thumb, "name": name, "path": pathl}
        for w in (frame, thumb, texts, name, pathl):
            w.bind("<Button-1>", lambda _e, p=path: self._select_by_path(p))
        if path not in self._thumb_cache:
            self._load_thumb(path)
        return row

    def _apply_row_style(self, row, is_sel):
        bg = "#33406b" if is_sel else PANEL
        for w in (row["frame"], row["thumb"], row["name"], row["path"]):
            w.configure(bg=bg)
        row["frame"].winfo_children()[1].configure(bg=bg)  # texts 容器

    def _select_by_path(self, path):
        if path in self.files:
            self.selected = self.files.index(path)
            self._render_list()
            self.status_var.set(path)
            self._update_preview()

    def _load_thumb(self, path):
        def work():
            try:
                with Image.open(path) as im:
                    im = im.convert("RGBA")
                    im.thumbnail((self.THUMB, self.THUMB), Image.LANCZOS)
                    im = im.copy()
                self._thumb_queue.put((path, im))
            except Exception as e:
                print("缩略图失败:", path, e, file=sys.stderr)
        threading.Thread(target=work, daemon=True).start()

    def _poll_thumbs(self):
        """主线程消费缩略图队列（工作线程只生产，不碰 UI）"""
        try:
            while True:
                path, im = self._thumb_queue.get_nowait()
                photo = ImageTk.PhotoImage(im)
                self._thumb_cache[path] = photo
                row = self._rows.get(path)
                if row:
                    row["thumb"].config(image=photo)
        except queue.Empty:
            pass
        self.root.after(80, self._poll_thumbs)

    # ────────────────── 预览面板 ──────────────────
    def _make_preview_pane(self, parent, title: str):
        pane = ttkb.Frame(parent)
        pane.pack(side=LEFT, fill=BOTH, expand=True, padx=(0, 12))
        ttkb.Label(pane, text=title, font=("Segoe UI Semibold", 11),
                   foreground=FG_DIM).pack(anchor=W, pady=(0, 6))
        # 棋盘格底，便于观察透明区域
        holder = tk.Frame(pane, bg="#2a2d3a", highlightthickness=1,
                          highlightbackground="#31354a")
        holder.pack(fill=BOTH, expand=True)
        img_label = tk.Label(holder, bg="#2a2d3a", bd=0,
                             text="（未选择）", fg=FG_DIM,
                             font=("Segoe UI", 10))
        img_label.place(relx=0.5, rely=0.5, anchor="center")
        info_var = ttkb.StringVar(value="—")
        ttkb.Label(pane, textvariable=info_var, font=("Consolas", 10),
                   foreground=ACCENT).pack(anchor=W, pady=(6, 0))
        p = {"holder": holder, "label": img_label, "info": info_var}
        holder.bind("<Configure>", lambda _e, p=p: self._render_pane(p))
        return p

    PREVIEW_MAX = 560

    def _show_image(self, pane, im: Image.Image | None, caption: str):
        key = id(pane)
        if im is None:
            self._pane_src.pop(key, None)
            pane["label"].config(image="", text="（未选择）")
            pane["info"].set(caption or "—")
            return
        self._pane_src[key] = im.convert("RGBA")
        self._render_pane(pane)
        pane["info"].set(caption)

    def _render_pane(self, pane):
        im = self._pane_src.get(id(pane))
        label = pane["label"]
        if im is None:
            return
        # 跟随面板实际大小缩放，窗口再小也不会撑爆布局
        max_w = max(label.master.winfo_width() - 12, 60)
        max_h = max(label.master.winfo_height() - 12, 60)
        disp = im.copy()
        disp.thumbnail((min(self.PREVIEW_MAX, max_w), min(self.PREVIEW_MAX, max_h)),
                       Image.LANCZOS)
        photo = ImageTk.PhotoImage(disp)
        self._preview_imgs[id(pane)] = photo
        label.config(image=photo, text="")

    def _update_preview(self):
        sel = self._selected_index()
        if sel is None:
            self._show_image(self.preview_original, None, "")
            self._show_image(self.preview_converted, None, "")
            return
        src = self.files[sel]
        try:
            with Image.open(src) as im:
                self._src_size = im.size
                self._show_image(self.preview_original, im,
                                 f"{im.size[0]} × {im.size[1]} px")
        except Exception as e:
            self._src_size = None
            self._show_image(self.preview_original, None, "")
            self.preview_original["info"].set(f"无法预览: {e}")
        self._update_converted_preview()

    def _update_converted_preview(self):
        sel = self._selected_index()
        if sel is None or self._src_size is None:
            self._show_image(self.preview_converted, None, "")
            return
        src = self.files[sel]
        fmt = self._fmt_name()
        try:
            tw = int(self.w_var.get()) if self.w_var.get().strip().isdigit() else 0
            th = int(self.h_var.get()) if self.h_var.get().strip().isdigit() else 0
        except ValueError:
            tw = th = 0
        mode_text = self.resize_mode_var.get()
        mode = {"不缩放": "", "指定宽度": "w", "指定高度": "h",
                "适配框(不超过)": "fit", "保证不小于宽×高": "min"}.get(mode_text, "")
        try:
            out = build_output_image(src, fmt, int(float(self.scale.get())),
                                     mode, tw, th)
            self._show_image(self.preview_converted, out,
                             f"{out.size[0]} × {out.size[1]} px  →  {fmt}")
        except Exception as e:
            self._show_image(self.preview_converted, None, "")
            self.preview_converted["info"].set(f"预览失败: {e}")

    def _on_select(self, _event=None):
        sel = self._selected_index()
        if sel is not None:
            self.status_var.set(self.files[sel])
        self._update_preview()

    def _fmt_changed(self):
        alpha = _supports_alpha(self._fmt_name())
        self.status_var.set("支持透明通道" if alpha else "该格式不支持透明，将填充白底")
        self._update_converted_preview()
        self._save_config()

    def _fmt_name(self) -> str:
        v = self.fmt_var.get()
        for _n, _e, f, _a in OUT_FORMATS:
            if f == v or _n == v:
                return f
        return "JPEG"

    # ────────────────── 配置自动存盘 / 恢复 ──────────────────
    def _save_config(self):
        try:
            os.makedirs(CONFIG_DIR, exist_ok=True)
            cfg = {
                "format": self.fmt_var.get(),
                "quality": int(float(self.scale.get())),
                "resize_mode": self.resize_mode_var.get(),
                "target_w": self.w_var.get(),
                "target_h": self.h_var.get(),
                "out_dir": self.out_dir or "",
                "last_dir": getattr(self, "last_dir", ""),
                "files": self.files,
            }
            with open(CONFIG_PATH, "w", encoding="utf-8") as f:
                json.dump(cfg, f, ensure_ascii=False)
        except Exception as e:
            print("配置保存失败:", e, file=sys.stderr)

    def _restore_config(self):
        try:
            with open(CONFIG_PATH, encoding="utf-8") as f:
                cfg = json.load(f)
        except Exception:
            cfg = {}
        if cfg.get("format") in [n for n, *_ in OUT_FORMATS]:
            self.fmt_var.set(cfg["format"])
        self.scale.set(cfg.get("quality", 90))
        self.q_label.config(text=str(int(float(self.scale.get()))))
        self.resize_mode_var.set(cfg.get("resize_mode", "不缩放"))
        self.w_var.set(str(cfg.get("target_w", "1920")))
        self.h_var.set(str(cfg.get("target_h", "1080")))
        self.last_dir = cfg.get("last_dir", "")
        if cfg.get("out_dir"):
            self.out_dir = cfg["out_dir"]
            self.out_full = cfg["out_dir"]
            self._update_out_text()
        # 恢复上一次的图片列表（存在才恢复；清空列表即主动清除）
        files = [f for f in cfg.get("files", []) if os.path.exists(f)]
        if files:
            self.add_files(files)

    def pick_files(self):
        paths = filedialog.askopenfilenames(
            title="选择图片文件",
            initialdir=self.last_dir or None,
            filetypes=[("图片文件", " ".join("*" + e for e in sorted(IN_EXTS))),
                       ("所有文件", "*.*")])
        if paths:
            self.last_dir = os.path.dirname(paths[0])
            self.add_files(paths)
            self._save_config()

    def pick_folder(self):
        d = filedialog.askdirectory(title="选择包含图片的文件夹",
                                    initialdir=self.last_dir or None)
        if not d:
            return
        self.last_dir = d
        files = []
        for dp, _dirs, ns in os.walk(d):
            files += [os.path.join(dp, n) for n in ns
                      if os.path.splitext(n)[1].lower() in IN_EXTS]
        self.add_files(files)
        self._save_config()

    def add_files(self, paths):
        known = set(self.files)
        for p in paths:
            p = os.path.normpath(p)
            if os.path.splitext(p)[1].lower() in IN_EXTS and p not in known:
                self.files.append(p)
                known.add(p)
        self._render_list()
        # 输入源变化联动：换了不同文件夹的输入文件，输出目录不再沿用旧的
        if paths:
            new_root = os.path.dirname(os.path.normpath(paths[0]))
            if getattr(self, "_input_root", None) and new_root != self._input_root:
                self._reset_out_dir()
            self._input_root = new_root
        self._save_config()

    def _reset_out_dir(self):
        self.out_dir = None
        self.out_full = "默认：与原文件同目录"
        self._update_out_text()

    def clear_out_dir(self):
        self._reset_out_dir()
        self._save_config()

    def clear_list(self):
        self.files.clear()
        self._input_root = None
        self.selected = None
        self._render_list()
        self._show_image(self.preview_original, None, "")
        self._show_image(self.preview_converted, None, "")
        self._save_config()  # 主动清空 = 主动清除记忆

    def _update_count(self):
        n = len(self.files)
        self.count_var.set(f"{n} 个文件")
        if n:
            self.empty_hint.place_forget()
        else:
            self.empty_hint.place(relx=0.5, rely=0.42, anchor="center")

    def pick_out_dir(self):
        d = filedialog.askdirectory(title="选择输出目录",
                                    initialdir=self.out_dir or self.last_dir or None)
        if d:
            self.out_dir = d
            self.out_full = d
            self._update_out_text()
            self._save_config()

    def _update_out_text(self):
        """路径超长时中间截断，独占一整行显示"""
        prow = self.out_label.master
        avail = prow.winfo_width() - 90  # 减去「输出目录:」前缀宽度
        font = tkfont.Font(font=self.out_label.cget("font"))
        text = self.out_full
        if avail > 40 and font.measure(text) > avail:
            keep = len(text) // 2
            while keep > 4 and font.measure(text[:keep] + " … " + text[-keep:]) > avail:
                keep -= 4
            text = text[:keep] + " … " + text[-keep:]
        self.out_var.set(text)

    def _resize_params(self):
        mode_text = self.resize_mode_var.get()
        try:
            tw = int(self.w_var.get())
        except ValueError:
            tw = 0
        try:
            th = int(self.h_var.get())
        except ValueError:
            th = 0
        mode = {"不缩放": "", "指定宽度": "w", "指定高度": "h",
                "适配框(不超过)": "fit", "保证不小于宽×高": "min"}.get(mode_text, "")
        if mode == "w" and tw <= 0:
            messagebox.showwarning("提示", "请填写有效的目标宽度。")
            return None
        if mode == "h" and th <= 0:
            messagebox.showwarning("提示", "请填写有效的目标高度。")
            return None
        if mode in ("fit", "min") and (tw <= 0 or th <= 0):
            messagebox.showwarning("提示", "该模式需要同时填写目标宽和高。")
            return None
        return mode, max(tw, 0), max(th, 0)

    # ────────────────── 转换 ──────────────────
    def start_convert(self):
        if self.running:
            return
        if not self.files:
            messagebox.showinfo("提示", "请先添加图片文件。")
            return
        params = self._resize_params()
        if params is None:
            return
        self.running = True
        self.convert_btn.config(state="disabled")
        self.progress.config(maximum=len(self.files), value=0)
        quality = int(float(self.scale.get()))
        fmt = self._fmt_name()
        ext = next(e for _n, e, f, _a in OUT_FORMATS if f == fmt)
        threading.Thread(target=self._worker, daemon=True,
                         args=(fmt, ext, quality, params)).start()

    def _worker(self, fmt, ext, quality, params):
        resize_mode, tw, th = params
        ok = fail = skip = 0
        if self.out_dir:
            os.makedirs(self.out_dir, exist_ok=True)
        for i, src in enumerate(self.files, 1):
            name = os.path.splitext(os.path.basename(src))[0] + ext
            dst = os.path.join(self.out_dir or os.path.dirname(src), name)
            try:
                if (os.path.abspath(src) == os.path.abspath(dst)
                        and os.path.splitext(src)[1].lower() == ext):
                    skip += 1
                else:
                    convert_one(src, dst, fmt, quality, resize_mode, tw, th)
                    ok += 1
            except Exception as e:
                print(f"失败: {src} -> {e}", file=sys.stderr)
                fail += 1
            self.root.after(0, self._progress_update, i, ok, fail, skip)
        self.root.after(0, self._finished, ok, fail, skip)

    def _progress_update(self, done, ok, fail, skip):
        self.progress["value"] = done
        self.status_var.set(f"✓{ok}  ✗{fail}  跳过{skip}")

    def _finished(self, ok, fail, skip):
        self.running = False
        self.convert_btn.config(state="normal")
        self.status_var.set(f"完成  ✓{ok}  ✗{fail}  跳过{skip}")
        messagebox.showinfo("完成", f"转换结束！\n成功 {ok} 个\n失败 {fail} 个\n跳过 {skip} 个")


def _dark_title_bar(root):
    """调用 Windows DWM API 让标题栏跟随暗色主题"""
    import ctypes
    try:
        root.update_idletasks()
        hwnd = ctypes.windll.user32.GetParent(root.winfo_id())
        for attr in (20, 19):  # DWMWA_USE_IMMERSIVE_DARK_MODE（Win20H1 前后属性号不同）
            value = ctypes.c_int(1)
            if ctypes.windll.dwmapi.DwmSetWindowAttribute(
                    hwnd, attr, ctypes.byref(value), ctypes.sizeof(value)) == 0:
                return True
    except Exception as e:
        print("暗色标题栏设置失败:", e, file=sys.stderr)
    return False


MIN_SIZE = (1060, 680)  # 保证三栏与底部选项完整可见的最小窗口尺寸


def _app_icon():
    """生成应用图标（绿色箭头风格），缓存到配置目录"""
    import math
    path = os.path.join(CONFIG_DIR, "icon.ico")
    if os.path.exists(path):
        return path
    try:
        os.makedirs(CONFIG_DIR, exist_ok=True)
        size = 256
        im = Image.new("RGBA", (size, size), (0, 0, 0, 0))
        from PIL import ImageDraw
        d = ImageDraw.Draw(im)
        d.rounded_rectangle([8, 8, 248, 248], radius=48, fill="#22252f")
        d.rounded_rectangle([8, 8, 248, 248], radius=48, outline="#4dd8a3", width=8)
        # 两个圆角块表示 转换前 → 转换后
        d.rounded_rectangle([40, 100, 118, 156], radius=14, fill="#8b93ad")
        d.polygon([(196, 128), (140, 92), (140, 164)], fill="#4dd8a3")
        d.line([(100, 128), (150, 128)], fill="#4dd8a3", width=16)
        im.save(path, sizes=[(256, 256), (64, 64), (32, 32), (16, 16)])
        return path
    except Exception as e:
        print("图标生成失败:", e, file=sys.stderr)
        return None


def create_window():
    if HAS_DND:
        # 让 ttkbootstrap 窗口具备 TkDnD 拖拽能力
        class DndWindow(ttkb.Window, TkinterDnD.Tk):
            pass
        root = DndWindow(title="PixelFactory · 图片快速处理与格式转换", themename="darkly",
                         size=(1120, 720), minsize=MIN_SIZE)
    else:
        root = ttkb.Window(title="PixelFactory · 图片快速处理与格式转换", themename="darkly",
                           size=(1120, 720), minsize=MIN_SIZE)
    _dark_title_bar(root)
    # 任务栏归属：让程序以自己的身份固定在任务栏，而不是挂在 pythonw 下
    try:
        import ctypes
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("Denjhang.PixelFactory.1")
    except Exception:
        pass
    icon = _app_icon()
    if icon:
        try:
            root.iconphoto(True, ImageTk.PhotoImage(Image.open(icon)))
        except Exception:
            pass
    return root


def main():
    root = create_window()
    App(root)
    root.mainloop()


def run_cli(argv):
    """python webp2jpg.py [-o 输出目录] [-f jpg|png|webp|...] [-w 宽|-h 高] 文件/文件夹..."""
    out_dir = fmt = "JPEG"
    ext = ".jpg"
    tw = th = 0
    mode = ""
    rest = []
    it = iter(argv)
    for a in it:
        if a in ("-o", "--out"):
            out_dir = next(it)
        elif a in ("-f", "--format"):
            fmt = next(it).upper()
            ext = next((e for _n, e, f, _x in OUT_FORMATS if f == fmt), ".jpg")
            fmt = next((f for _n, _e, f, _x in OUT_FORMATS if f == fmt), "JPEG")
        elif a in ("-w", "--width"):
            tw = int(next(it)); mode = "w"
        elif a in ("-h", "--height"):
            th = int(next(it)); mode = "h"
        else:
            rest.append(a)
    files = []
    for a in rest:
        if os.path.isdir(a):
            for dp, _d, ns in os.walk(a):
                files += [os.path.join(dp, n) for n in ns
                          if os.path.splitext(n)[1].lower() in IN_EXTS]
        elif os.path.splitext(a)[1].lower() in IN_EXTS:
            files.append(a)
    ok = fail = 0
    if out_dir:
        os.makedirs(out_dir, exist_ok=True)
    for f in files:
        name = os.path.splitext(os.path.basename(f))[0] + ext
        dst = os.path.join(out_dir if out_dir else os.path.dirname(f), name)
        try:
            convert_one(f, dst, fmt, 90, mode, tw, th)
            ok += 1
        except Exception as e:
            print(f"失败: {f} -> {e}", file=sys.stderr)
            fail += 1
    print(f"完成：成功 {ok}，失败 {fail}")


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] not in ("--gui",):
        run_cli(sys.argv[1:])
    else:
        main()
