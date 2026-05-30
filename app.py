#!/usr/bin/env python3
"""YouTube Shorts Generator - GUI アプリ"""

import ctypes, json, re, shutil, subprocess, tempfile, threading, tkinter as tk
from tkinter import ttk, filedialog, messagebox, scrolledtext
from pathlib import Path

import requests
from PIL import Image, ImageTk

# ── パス定数 ─────────────────────────────────────────────
BASE_DIR  = Path(__file__).parent
INPUT_DIR = BASE_DIR / "input"
IMG_DIR   = INPUT_DIR / "images"
BGM_DIR   = INPUT_DIR / "bgm"
NARR_DIR  = INPUT_DIR / "narration"
CONFIG    = BASE_DIR / "config.json"
VV_URL    = "http://localhost:50021"

# ── UI 定数 ───────────────────────────────────────────────
AUDIO_EXT        = {".mp3", ".wav", ".ogg", ".m4a"}
THUMB_W, THUMB_H = 88, 156
MAX_IMAGES       = 20

F_NORMAL = ("Yu Gothic UI", 11)
F_HINT   = ("Yu Gothic UI",  9)
F_STEP   = ("Yu Gothic UI", 10, "bold")
F_HEAD   = ("Yu Gothic UI", 12, "bold")
F_TEXT   = ("Yu Gothic UI", 11)

BG_BODY  = "#F4F4F6"
BG_PAGE  = "#DCDCE4"
C_IMAGE  = "#1A3D5C"
C_VOICE  = "#3D1A5C"
C_BGM    = "#1A5C3A"
C_INFO   = "#5C1A1A"
C_EDIT   = "#2A2A4A"
C_DARK   = "#1C1C1C"


# ── Windows MCI 音声再生 ──────────────────────────────────

_winmm = ctypes.windll.winmm

def _mci(cmd):     _winmm.mciSendStringW(cmd, None, 0, None)
def play_file(p):  _mci("stop media"); _mci("close media"); _mci(f'open "{p}" alias media'); _mci("play media")
def stop_audio():  _mci("stop media"); _mci("close media")


# ── ルビ除去 ──────────────────────────────────────────────

def strip_ruby(text: str) -> str:
    """{漢字|よみ} 記法を読み仮名のみに変換して返す"""
    return re.sub(r'\{([^|{}]+)\|([^|{}]+)\}', r'\2', text)


# ── クロップ（オフセット指定） ────────────────────────────

def crop_with_offset(img: Image.Image, w: int, h: int,
                     h_offset: int = 0, v_offset: int = 0) -> Image.Image:
    """
    縦横比を保ちながらクロップしてリサイズ。
    h_offset: -100〜+100（負=左寄り、正=右寄り）横長画像に有効
    v_offset: -100〜+100（負=上寄り、正=下寄り）縦長画像に有効
    """
    img = img.convert("RGB")
    sw, sh = img.size
    if sw / sh > w / h:
        # 横長：左右をクロップ
        nw     = int(sh * w / h)
        margin = (sw - nw) // 2
        shift  = int(margin * h_offset / 100)
        x0     = max(0, min(margin + shift, sw - nw))
        img    = img.crop((x0, 0, x0 + nw, sh))
    else:
        # 縦長：上下をクロップ
        nh     = int(sw * h / w)
        margin = (sh - nh) // 2
        shift  = int(margin * v_offset / 100)
        y0     = max(0, min(margin + shift, sh - nh))
        img    = img.crop((0, y0, sw, y0 + nh))
    return img.resize((w, h), Image.LANCZOS)


# ── ツールチップ ──────────────────────────────────────────

class Tooltip:
    """マウスオーバー時に説明テキストを表示するツールチップ"""

    def __init__(self, widget, text):
        self._widget = widget
        self._text   = text
        self._job    = None
        self._window = None
        widget.bind("<Enter>", self._schedule)
        widget.bind("<Leave>", self._cancel)

    def _schedule(self, _=None):
        self._cancel()
        self._job = self._widget.after(500, self._show)

    def _cancel(self, _=None):
        if self._job:
            self._widget.after_cancel(self._job)
            self._job = None
        if self._window:
            self._window.destroy()
            self._window = None

    def _show(self):
        x = self._widget.winfo_rootx() + 12
        y = self._widget.winfo_rooty() + self._widget.winfo_height() + 4
        self._window = tw = tk.Toplevel(self._widget)
        tw.wm_overrideredirect(True)
        tw.wm_geometry(f"+{x}+{y}")
        tk.Label(tw, text=self._text, justify="left", bg="#ffffd0",
                 relief="solid", borderwidth=1, font=F_HINT,
                 wraplength=300, padx=6, pady=4).pack()


def tip(widget, text):
    Tooltip(widget, text)


# ── アコーディオンセクション ──────────────────────────────

class AccordionSection(tk.Frame):
    """クリックで展開・折りたたみできるセクション"""

    def __init__(self, master, title, subtitle, color, **kw):
        super().__init__(master, bg=BG_PAGE, **kw)
        self.columnconfigure(0, weight=1)
        self._expanded = False

        # ヘッダー（常時表示）
        hdr = tk.Frame(self, bg=color, padx=14, cursor="hand2")
        hdr.grid(row=0, column=0, sticky="ew")
        hdr.columnconfigure(1, weight=1)

        title_row = tk.Frame(hdr, bg=color, pady=10)
        title_row.grid(row=0, column=0, columnspan=3, sticky="ew")
        title_row.columnconfigure(1, weight=1)

        tk.Label(title_row, text=title, bg=color, fg="white",
                 font=F_HEAD, anchor="w").grid(row=0, column=0, sticky="w")

        self._arrow = tk.Label(title_row, text="▼", bg=color, fg="white",
                               font=("Yu Gothic UI", 11), cursor="hand2")
        self._arrow.grid(row=0, column=2, sticky="e", padx=(8, 0))

        self._sub = tk.Label(hdr, text=subtitle, bg=color, fg="#F0C8A8",
                             font=F_HINT, anchor="w", justify="left",
                             wraplength=1, pady=4)
        self._sub.grid(row=1, column=0, columnspan=3, sticky="ew")

        hdr.bind("<Configure>", self._update_wrap)
        hdr.bind("<Map>", lambda e: hdr.after(60, self._update_wrap))
        for w in [hdr, title_row, self._arrow]:
            w.bind("<Button-1>", self.toggle)

        # ボディ（折りたたみ部分）
        self._body = tk.Frame(self, bg=BG_BODY, padx=14, pady=12)
        self._body.columnconfigure(0, weight=1)

    def _update_wrap(self, _=None):
        w = self._sub.master.winfo_width()
        if w > 30:
            self._sub.configure(wraplength=max(60, w - 28))

    def toggle(self, _=None):
        if self._expanded:
            self._body.grid_remove()
            self._arrow.config(text="▼")
        else:
            self._body.grid(row=2, column=0, sticky="nsew")
            self._arrow.config(text="▲")
        self._expanded = not self._expanded

    def expand(self):
        if not self._expanded:
            self.toggle()

    @property
    def body(self):
        return self._body


# ── ファイルリストパネル ──────────────────────────────────

class FileListPanel(ttk.Frame):
    """フォルダ内の音声ファイルを一覧表示・操作するパネル"""

    def __init__(self, master, folder, height=6, on_change=None, **kw):
        super().__init__(master, **kw)
        self.folder     = folder
        self.paths:     list[Path] = []
        self._on_change = on_change
        self.columnconfigure(0, weight=1)
        self.rowconfigure(1, weight=1)

        # ボタンバー
        btn_frame = ttk.Frame(self)
        btn_frame.grid(row=0, column=0, sticky="ew", pady=(0, 4))
        for label, cmd, tooltip in [
            ("＋ 追加", self._add,    "音声ファイルを追加（自動でフォルダにコピー）"),
            ("▶ 再生",  self._play,   "選択中のファイルをプレビュー再生"),
            ("■ 停止",  stop_audio,   "再生を停止"),
            ("✕",       self._remove, "リストから削除（元ファイルは残ります）"),
        ]:
            b = ttk.Button(btn_frame, text=label, command=cmd,
                           **({"width": 3} if len(label) == 1 else {}))
            b.pack(side="left", padx=2)
            tip(b, tooltip)

        # リスト
        list_frame = ttk.Frame(self)
        list_frame.grid(row=1, column=0, sticky="nsew")
        list_frame.columnconfigure(0, weight=1)
        list_frame.rowconfigure(0, weight=1)

        self._listbox = tk.Listbox(list_frame, selectmode="single", font=F_NORMAL,
                                   activestyle="none", cursor="hand2", height=height,
                                   selectbackground="#1A5C3A", selectforeground="white")
        scrollbar = ttk.Scrollbar(list_frame, orient="vertical", command=self._listbox.yview)
        self._listbox.configure(yscrollcommand=scrollbar.set)
        self._listbox.grid(row=0, column=0, sticky="nsew")
        scrollbar.grid(row=0, column=1, sticky="ns")
        self._listbox.bind("<Double-Button-1>", lambda e: self._play())
        self._listbox.bind("<<ListboxSelect>>", self._on_select)

        self.scan()

    def _on_select(self, _=None):
        if self._on_change:
            self._on_change(self.selected())

    def scan(self):
        self.folder.mkdir(parents=True, exist_ok=True)
        self.paths = sorted(
            p for p in self.folder.iterdir() if p.suffix.lower() in AUDIO_EXT
        )
        self._listbox.delete(0, "end")
        for p in self.paths:
            self._listbox.insert("end", f"  {p.name}")

    def selected(self) -> Path | None:
        sel = self._listbox.curselection()
        return self.paths[sel[0]] if sel else None

    def select_by_path(self, path):
        target = Path(path)
        for i, p in enumerate(self.paths):
            if p.name == target.name or p == target:
                self._listbox.selection_clear(0, "end")
                self._listbox.selection_set(i)
                self._listbox.see(i)
                if self._on_change:
                    self._on_change(p)
                return

    def _add(self):
        files = filedialog.askopenfilenames(
            title="音声ファイルを追加",
            filetypes=[("音声", "*.mp3 *.wav *.ogg *.m4a"), ("すべて", "*.*")],
        )
        for f in files:
            src, dst = Path(f), self.folder / Path(f).name
            if src != dst:
                shutil.copy2(src, dst)
        self.scan()

    def _remove(self):
        sel = self._listbox.curselection()
        if sel:
            self.paths.pop(sel[0])
            self._listbox.delete(sel[0])

    def _play(self):
        p = self.selected()
        if p:
            play_file(str(p))
        else:
            messagebox.showinfo("再生", "ファイルを選択してください")


# ── メインアプリ ──────────────────────────────────────────

class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("YouTube Shorts Generator")
        self.geometry("780x700")
        self.minsize(620, 500)
        self.columnconfigure(0, weight=1)
        self.rowconfigure(1, weight=1)

        self.image_paths: list[Path]  = []
        self._thumbs:     list        = []
        self._sel_img:    int         = -1
        self.speakers:    list        = []
        self._current_config_path: Path | None = None
        self._duration_mode  = tk.StringVar(value="auto")
        self._duration_var   = tk.IntVar(value=30)
        self._crop_h_offset  = tk.IntVar(value=0)
        self._crop_v_offset  = tk.IntVar(value=0)

        self._build_ui()
        self._load_config()
        self._fetch_speakers()

    # ── UI 構築 ───────────────────────────────────────────

    def _build_ui(self):
        self._build_step_guide()
        self._build_accordion()
        self._build_bottom_bar()

    def _build_step_guide(self):
        sf = tk.Frame(self, bg=C_DARK, pady=8)
        sf.grid(row=0, column=0, sticky="ew")
        tk.Label(sf, text="使い方：", bg=C_DARK, fg="#AAAACC", font=F_STEP).pack(side="left", padx=(14, 8))

        steps = [
            ("①", "画像を追加", C_IMAGE),
            ("②", "ボイス設定", C_VOICE),
            ("③", "BGM選択",   C_BGM),
            ("④", "情報入力",  C_INFO),
            ("⑤", "💾保存→🎬生成", C_EDIT),
        ]
        for i, (num, label, color) in enumerate(steps):
            if i:
                tk.Label(sf, text="→", bg=C_DARK, fg="#555577",
                         font=("Yu Gothic UI", 12)).pack(side="left", padx=2)
            chip = tk.Frame(sf, bg=color, padx=10, pady=4)
            chip.pack(side="left", padx=2)
            tk.Label(chip, text=num,   bg=color, fg="#B0C8E8", font=("Yu Gothic UI", 10, "bold")).pack(side="left")
            tk.Label(chip, text=f" {label}", bg=color, fg="white", font=("Yu Gothic UI", 10)).pack(side="left")

    def _build_accordion(self):
        self._canvas = tk.Canvas(self, bg=BG_PAGE, highlightthickness=0)
        scrollbar = ttk.Scrollbar(self, orient="vertical", command=self._canvas.yview)
        self._canvas.configure(yscrollcommand=scrollbar.set)
        self._canvas.grid(row=1, column=0, sticky="nsew")
        scrollbar.grid(row=1, column=1, sticky="ns")

        inner = tk.Frame(self._canvas, bg=BG_PAGE)
        inner.columnconfigure(0, weight=1)
        win_id = self._canvas.create_window((0, 0), window=inner, anchor="nw")

        inner.bind("<Configure>", lambda e: self._canvas.configure(scrollregion=self._canvas.bbox("all")))
        self._canvas.bind("<Configure>", lambda e: self._canvas.itemconfig(win_id, width=e.width))
        self.bind_all("<MouseWheel>", lambda e: self._canvas.yview_scroll(-1 * (e.delta // 120), "units"))

        sections = [
            ("📷  使用画像",       f"AI生成画像を追加して ↑↓ で表示順を調整します（最大{MAX_IMAGES}枚）", C_IMAGE),
            ("🎙  ボイス設定",     "VOICEVOX合成音声 または 録音ファイルを設定します",                   C_VOICE),
            ("🎵  BGMライブラリ",  "クリックでBGMを選択し ▶ でテスト再生できます",                      C_BGM),
            ("📝  動画情報＆音量", "タイトル・説明文・音量バランスと保存先を設定します",                   C_INFO),
        ]
        secs = [AccordionSection(inner, t, s, c) for t, s, c in sections]
        for i, sec in enumerate(secs):
            sec.grid(row=i, column=0, sticky="ew", padx=8, pady=(8 if i == 0 else 4, 4))

        self._sec_img, self._sec_voice, self._sec_bgm, self._sec_info = secs
        self._build_image_section(self._sec_img.body)
        self._build_voice_section(self._sec_voice.body)
        self._build_bgm_section(self._sec_bgm.body)
        self._build_info_section(self._sec_info.body)

    # ── セクション①：使用画像 ────────────────────────────

    _PREV_W = 270   # プレビューポップアップ幅
    _PREV_H = 480   # プレビューポップアップ高

    def _build_image_section(self, body):
        body.columnconfigure(0, weight=1)

        # ボタンバー
        btn_frame = tk.Frame(body, bg=BG_BODY)
        btn_frame.grid(row=0, column=0, sticky="ew", pady=(0, 8))
        for label, cmd, tooltip in [
            ("＋ 追加",     self._add_images,         "画像ファイルを選択して追加（PNG・JPG・WEBP対応）"),
            ("↑",           self._move_up,             "選択した画像を1つ前に移動"),
            ("↓",           self._move_down,           "選択した画像を1つ後ろに移動"),
            ("✕",           self._remove_image,        "リストから削除（元ファイルは残ります）"),
            ("🔍 プレビュー", self._show_image_preview, "選択中の画像を動画内(9:16)での見え方でプレビュー"),
        ]:
            b = ttk.Button(btn_frame, text=label, command=cmd,
                           **({"width": 3} if len(label) == 1 else {}))
            b.pack(side="left", padx=2)
            tip(b, tooltip)

        self._img_list_frame = tk.Frame(body, bg=BG_BODY)
        self._img_list_frame.grid(row=1, column=0, sticky="ew")
        self._img_list_frame.columnconfigure(0, weight=1)

        # 表示位置スライダー
        offset_frame = tk.Frame(body, bg=BG_BODY)
        offset_frame.grid(row=2, column=0, sticky="ew", pady=(10, 0))
        offset_frame.columnconfigure(1, weight=1)

        tk.Label(offset_frame, text="左右の表示位置", font=F_NORMAL, bg=BG_BODY).grid(
            row=0, column=0, sticky="w", pady=2)
        self._make_offset_slider(offset_frame, self._crop_h_offset, row=0,
                                  left_label="← 左", right_label="右 →",
                                  tooltip="横長・正方形画像のクロップ位置を左右にずらします")

        tk.Label(offset_frame, text="上下の表示位置", font=F_NORMAL, bg=BG_BODY).grid(
            row=1, column=0, sticky="w", pady=2)
        self._make_offset_slider(offset_frame, self._crop_v_offset, row=1,
                                  left_label="↑ 上", right_label="下 ↓",
                                  tooltip="縦長画像のクロップ位置を上下にずらします")

    # ── セクション②：ボイス設定 ──────────────────────────

    def _build_voice_section(self, body):
        body.columnconfigure(1, weight=1)

        tk.Label(body, text="入力方式", font=F_NORMAL, bg=BG_BODY).grid(
            row=0, column=0, sticky="w", pady=4)
        self._voice_mode = tk.StringVar(value="voicevox")
        mode_frame = tk.Frame(body, bg=BG_BODY)
        mode_frame.grid(row=0, column=1, columnspan=2, sticky="w", padx=(8, 0))

        rb1 = ttk.Radiobutton(mode_frame, text="VOICEVOX（合成音声）",
                               variable=self._voice_mode, value="voicevox",
                               command=self._toggle_voice)
        rb1.pack(side="left")
        tip(rb1, "テキストを入力するとAIが自動で読み上げます\n※ VOICEVOXを先に起動してください")

        rb2 = ttk.Radiobutton(mode_frame, text="録音ファイル",
                               variable=self._voice_mode, value="file",
                               command=self._toggle_voice)
        rb2.pack(side="left", padx=(16, 0))
        tip(rb2, "自分でマイク録音したWAVファイルを使います")

        ttk.Separator(body, orient="horizontal").grid(
            row=1, column=0, columnspan=3, sticky="ew", pady=8)

        self._vv_frame = tk.Frame(body, bg=BG_BODY)
        self._vv_frame.grid(row=2, column=0, columnspan=3, sticky="ew")
        self._vv_frame.columnconfigure(1, weight=1)
        self._build_voicevox_settings(self._vv_frame)

        self._narr_frame = tk.Frame(body, bg=BG_BODY)
        self._narr_frame.grid(row=2, column=0, columnspan=3, sticky="nsew")
        self._narr_frame.columnconfigure(0, weight=1)
        self._narr_frame.rowconfigure(1, weight=1)
        body.rowconfigure(2, weight=1)
        tk.Label(self._narr_frame, text="録音したWAVファイルを追加して選択してください",
                 font=F_HINT, fg="#777", bg=BG_BODY).grid(row=0, column=0, sticky="w", pady=(0, 4))
        self._narr_panel = FileListPanel(self._narr_frame, NARR_DIR, height=5)
        self._narr_panel.grid(row=1, column=0, sticky="nsew")

        self._toggle_voice()

    def _build_voicevox_settings(self, parent):
        tk.Label(parent, text="キャラクター", font=F_NORMAL, bg=BG_BODY).grid(
            row=0, column=0, sticky="w", pady=4)
        self._speaker_var = tk.StringVar()
        self._speaker_cb  = ttk.Combobox(parent, textvariable=self._speaker_var,
                                          state="readonly", font=F_NORMAL)
        self._speaker_cb.grid(row=0, column=1, columnspan=2, sticky="ew", padx=(8, 0))
        tip(self._speaker_cb, "読み上げキャラを選択\n例）ずんだもん、四国めたん など")

        tk.Label(parent, text="速度", font=F_NORMAL, bg=BG_BODY).grid(row=1, column=0, sticky="w", pady=4)
        self._speed_var = tk.DoubleVar(value=1.1)
        self._make_slider(parent, self._speed_var, 0.5, 2.0, 1, ".1f",
                          "読み上げ速度（1.0=標準）ショート動画には 1.1〜1.3 がおすすめ")

        tk.Label(parent, text="ピッチ", font=F_NORMAL, bg=BG_BODY).grid(row=2, column=0, sticky="w", pady=4)
        self._pitch_var = tk.DoubleVar(value=0.0)
        self._make_slider(parent, self._pitch_var, -0.15, 0.15, 2, ".2f",
                          "声の高さ（0.0=標準、＋で高く、−で低く）")

        tk.Label(parent, text="台本", font=F_NORMAL, bg=BG_BODY).grid(row=3, column=0, sticky="nw", pady=4)
        self._narr_text = tk.Text(parent, height=6, wrap="word", font=F_TEXT)
        self._narr_text.grid(row=3, column=1, columnspan=2, sticky="ew", padx=(8, 0))
        tip(self._narr_text, "動画で読み上げるテキストを入力\n"
                             "目安：1分以内（200〜400文字程度）\n"
                             "▶テスト再生は最初の80文字のみ再生されます\n\n"
                             "読み仮名の修正：{漢字|よみ} と書くと\n"
                             "その漢字を指定した読み仮名で読み上げます\n"
                             "例）{今日|きょう}は{晴れ|はれ}です")

        tk.Label(parent, text="読み修正：{漢字|よみ}　例）{今日|きょう}は{晴れ|はれ}です",
                 font=F_HINT, fg="#888", bg=BG_BODY).grid(
            row=4, column=1, columnspan=2, sticky="w", padx=(8, 0), pady=(2, 0))

        pb = tk.Frame(parent, bg=BG_BODY)
        pb.grid(row=5, column=1, columnspan=2, sticky="e", padx=(8, 0), pady=(8, 0))
        b = ttk.Button(pb, text="▶  テスト再生", command=self._preview_voice)
        b.pack(side="left", padx=2)
        tip(b, "台本の冒頭80文字をキャラクターの声でプレビューします")
        b = ttk.Button(pb, text="■  停止", command=stop_audio)
        b.pack(side="left", padx=2)
        tip(b, "再生を停止します")

    def _toggle_voice(self):
        if self._voice_mode.get() == "voicevox":
            self._narr_frame.grid_remove()
            self._vv_frame.grid()
        else:
            self._vv_frame.grid_remove()
            self._narr_frame.grid()

    def _toggle_duration(self):
        state = "normal" if self._duration_mode.get() == "manual" else "disabled"
        self._duration_spin.configure(state=state)

    # ── セクション③：BGM ─────────────────────────────────

    def _build_bgm_section(self, body):
        body.columnconfigure(0, weight=1)
        body.rowconfigure(0, weight=1)

        self._bgm_status_label = tk.Label(body, text="未選択",
                                            font=F_HINT, fg="#AAAAAA", bg=BG_BODY, anchor="w")
        self._bgm_status_label.grid(row=1, column=0, sticky="ew", pady=(6, 0))

        self._bgm_panel = FileListPanel(body, BGM_DIR, height=6,
                                         on_change=self._on_bgm_change)
        self._bgm_panel.grid(row=0, column=0, sticky="nsew")

    def _on_bgm_change(self, path: Path | None):
        if path:
            self._bgm_status_label.configure(text=f"▶ 選択中：{path.name}", fg="#1A5C3A")
        else:
            self._bgm_status_label.configure(text="未選択", fg="#AAAAAA")

    # ── セクション④：動画情報＆音量 ──────────────────────

    def _build_info_section(self, body):
        body.columnconfigure(1, weight=1)

        for row, (label, attr, tooltip) in enumerate([
            ("タイトル", "_title_var", "動画下部に大きく表示されるタイトルテキスト"),
            ("説明文",   "_desc_var",  "タイトルの下に小さく表示される補足テキスト"),
        ]):
            tk.Label(body, text=label, font=F_NORMAL, bg=BG_BODY).grid(
                row=row, column=0, sticky="w", pady=4)
            setattr(self, attr, tk.StringVar())
            e = ttk.Entry(body, textvariable=getattr(self, attr), font=F_NORMAL)
            e.grid(row=row, column=1, columnspan=2, sticky="ew", padx=(8, 0))
            tip(e, tooltip)

        ttk.Separator(body, orient="horizontal").grid(
            row=2, column=0, columnspan=3, sticky="ew", pady=8)

        tk.Label(body, text="BGM音量", font=F_NORMAL, bg=BG_BODY).grid(row=3, column=0, sticky="w", pady=4)
        self._bgm_vol_var = tk.DoubleVar(value=0.18)
        self._make_slider(body, self._bgm_vol_var, 0.0, 1.0, 3, ".2f",
                          "BGMの音量（0.0=無音、1.0=最大）\n0.15〜0.25 程度が聞き取りやすい")

        tk.Label(body, text="ナレーション音量", font=F_NORMAL, bg=BG_BODY).grid(row=4, column=0, sticky="w", pady=4)
        self._narr_vol_var = tk.DoubleVar(value=2.0)
        self._make_slider(body, self._narr_vol_var, 0.5, 4.0, 4, ".1f",
                          "ナレーションの音量倍率（2.0=元の2倍）")

        ttk.Separator(body, orient="horizontal").grid(
            row=5, column=0, columnspan=3, sticky="ew", pady=8)

        tk.Label(body, text="動画の保存先", font=F_NORMAL, bg=BG_BODY).grid(row=6, column=0, sticky="w", pady=4)
        self._output_var = tk.StringVar(value=str(BASE_DIR / "output" / "video.mp4"))
        out_frame = tk.Frame(body, bg=BG_BODY)
        out_frame.grid(row=6, column=1, columnspan=2, sticky="ew", padx=(8, 0))
        out_frame.columnconfigure(0, weight=1)
        e = ttk.Entry(out_frame, textvariable=self._output_var, font=F_NORMAL)
        e.grid(row=0, column=0, sticky="ew")
        tip(e, "生成した動画の保存先パスを指定します")
        b = ttk.Button(out_frame, text="参照", command=self._browse_output)
        b.grid(row=0, column=1, padx=(4, 0))
        tip(b, "保存先をダイアログで選択します")

        ttk.Separator(body, orient="horizontal").grid(
            row=7, column=0, columnspan=3, sticky="ew", pady=8)

        tk.Label(body, text="再生時間", font=F_NORMAL, bg=BG_BODY).grid(row=8, column=0, sticky="w", pady=4)
        dur_frame = tk.Frame(body, bg=BG_BODY)
        dur_frame.grid(row=8, column=1, columnspan=2, sticky="w", padx=(8, 0))

        rb_auto = ttk.Radiobutton(dur_frame, text="自動（ナレーション尺に合わせる）",
                                   variable=self._duration_mode, value="auto",
                                   command=self._toggle_duration)
        rb_auto.pack(side="left")
        tip(rb_auto, "ナレーションの長さに合わせて動画の長さを決定します")

        rb_manual = ttk.Radiobutton(dur_frame, text="手動で設定する",
                                     variable=self._duration_mode, value="manual",
                                     command=self._toggle_duration)
        rb_manual.pack(side="left", padx=(16, 0))
        tip(rb_manual, "再生時間を秒単位で手動指定します（5〜59秒）\n"
                        "ナレーションより長い場合：ナレーション終了後BGMのみ継続\n"
                        "ナレーションより短い場合：指定秒数でカット")

        self._duration_spin = ttk.Spinbox(dur_frame, from_=5, to=59, increment=1,
                                           textvariable=self._duration_var, width=5)
        self._duration_spin.pack(side="left", padx=(8, 0))
        tk.Label(dur_frame, text="秒（5〜59秒）", font=F_NORMAL, bg=BG_BODY).pack(side="left", padx=(4, 0))
        tip(self._duration_spin, "動画の再生時間を秒単位で指定します（5〜59秒）")

        self._toggle_duration()

    # ── 下部ボタンバー ────────────────────────────────────

    def _build_bottom_bar(self):
        bar = tk.Frame(self, bg=C_DARK, pady=8)
        bar.grid(row=2, column=0, columnspan=2, sticky="ew")
        bar.columnconfigure(2, weight=1)

        self._status = tk.StringVar(value="準備完了")
        tk.Label(bar, textvariable=self._status, fg="#AAAACC",
                 bg=C_DARK, font=F_NORMAL).grid(row=0, column=3, padx=12, sticky="w")

        b_load = ttk.Button(bar, text="📂  設定を読み込む", command=self._load_config_dialog)
        b_load.grid(row=0, column=0, padx=(12, 4))
        tip(b_load, "保存済みの設定ファイルを読み込みます\n\n"
                    "読み込まれる内容：\n"
                    "  • 使用画像リストと表示順\n"
                    "  • ボイス設定（キャラクター・速度・ピッチ・台本）\n"
                    "  • BGM ファイルの選択\n"
                    "  • タイトル・説明文・音量バランス\n"
                    "  • 動画の保存先パス\n\n"
                    "読み込み後に内容を編集して別の設定として保存することもできます\n"
                    "複数のプロジェクト設定をファイルで使い分けられます")

        b_save = ttk.Button(bar, text="💾  設定を保存", command=self._save_config_dialog)
        b_save.grid(row=0, column=1, padx=4)
        tip(b_save, "現在の設定をファイルとして保存します\n\n"
                    "保存される内容：\n"
                    "  • 使用画像リストと表示順\n"
                    "  • ボイス設定（キャラクター・速度・ピッチ・台本）\n"
                    "  • BGM ファイルの選択\n"
                    "  • タイトル・説明文・音量バランス\n"
                    "  • 動画の保存先パス\n\n"
                    "保存先とファイル名はダイアログで指定できます\n"
                    "動画生成前に必ず保存してください")

        b_gen = tk.Button(bar, text="  🎬  動画を生成する  ", command=self._generate,
                          bg=C_IMAGE, fg="white", font=("Yu Gothic UI", 12, "bold"),
                          relief="flat", padx=8, pady=6, cursor="hand2",
                          activebackground="#0E2A3F", activeforeground="white")
        b_gen.grid(row=0, column=4, padx=(4, 12))
        tip(b_gen, "現在の設定を保存してから動画を生成します\n完了まで1〜2分かかります")

    # ── スライダーヘルパー ────────────────────────────────

    def _make_slider(self, parent, var, from_, to, row, fmt, tooltip=""):
        frame = tk.Frame(parent, bg=BG_BODY)
        frame.grid(row=row, column=1, columnspan=2, sticky="ew", padx=(8, 0), pady=4)
        frame.columnconfigure(0, weight=1)

        value_label = tk.Label(frame, text=f"{var.get():{fmt}}", width=6, font=F_NORMAL, bg=BG_BODY)
        slider = ttk.Scale(frame, from_=from_, to=to, variable=var, orient="horizontal")
        slider.grid(row=0, column=0, sticky="ew")
        value_label.grid(row=0, column=1, padx=(6, 0))
        var.trace_add("write", lambda *_: value_label.config(text=f"{var.get():{fmt}}"))

        if tooltip:
            tip(slider, tooltip)
            tip(value_label, tooltip)

    # ── 画像操作 ──────────────────────────────────────────

    def _add_images(self):
        remaining = MAX_IMAGES - len(self.image_paths)
        if remaining <= 0:
            messagebox.showwarning("上限到達", f"画像は最大{MAX_IMAGES}枚までです")
            return

        IMG_DIR.mkdir(parents=True, exist_ok=True)
        files = filedialog.askopenfilenames(
            title="画像を選択（複数可）",
            filetypes=[("画像", "*.png *.jpg *.jpeg *.webp"), ("すべて", "*.*")],
            initialdir=str(IMG_DIR),
        )
        added = 0
        for f in files:
            if added >= remaining:
                break
            src, dst = Path(f), IMG_DIR / Path(f).name
            if src != dst:
                shutil.copy2(src, dst)
            if dst not in self.image_paths:
                self.image_paths.append(dst)
                added += 1

        if len(files) > remaining:
            messagebox.showinfo("追加制限", f"{remaining}枚を追加しました（最大{MAX_IMAGES}枚のため残りは追加されませんでした）")
        self._refresh_images()

    def _remove_image(self):
        if self._sel_img >= 0:
            self.image_paths.pop(self._sel_img)
            self._sel_img = min(self._sel_img, len(self.image_paths) - 1)
            self._refresh_images()

    def _move_up(self):
        i = self._sel_img
        if i > 0:
            self.image_paths[i - 1], self.image_paths[i] = self.image_paths[i], self.image_paths[i - 1]
            self._sel_img = i - 1
            self._refresh_images()

    def _move_down(self):
        i = self._sel_img
        if 0 <= i < len(self.image_paths) - 1:
            self.image_paths[i], self.image_paths[i + 1] = self.image_paths[i + 1], self.image_paths[i]
            self._sel_img = i + 1
            self._refresh_images()

    def _refresh_images(self):
        for w in self._img_list_frame.winfo_children():
            w.destroy()
        self._thumbs.clear()

        for i, path in enumerate(self.image_paths):
            bg  = "#CCE4FF" if i == self._sel_img else BG_BODY
            row = tk.Frame(self._img_list_frame, bg=bg, cursor="hand2")
            row.pack(fill="x", pady=2)

            try:
                img = Image.open(path)
                img.thumbnail((THUMB_W, THUMB_H))
                photo = ImageTk.PhotoImage(img)
                self._thumbs.append(photo)
                tk.Label(row, image=photo, bg=bg).pack(side="left", padx=4, pady=4)
            except Exception:
                tk.Label(row, text="?", width=6, bg=bg, font=F_NORMAL).pack(side="left")

            tk.Label(row, text=f"{i + 1}.  {path.name}", anchor="w",
                     bg=bg, font=F_NORMAL).pack(side="left", fill="x", expand=True)

            for w in [row] + list(row.winfo_children()):
                w.bind("<Button-1>", lambda e, idx=i: self._select_image(idx))

    def _make_offset_slider(self, parent, var, row, left_label, right_label, tooltip=""):
        tk.Label(parent, text=left_label, font=F_HINT, fg="#888", bg=BG_BODY).grid(
            row=row, column=1, sticky="w", padx=(8, 0))
        s = ttk.Scale(parent, from_=-100, to=100, variable=var, orient="horizontal")
        s.grid(row=row, column=2, sticky="ew", padx=4)
        b = ttk.Button(parent, text="中央", width=4,
                       command=lambda v=var: v.set(0))
        b.grid(row=row, column=3, padx=(0, 4))
        tk.Label(parent, text=right_label, font=F_HINT, fg="#888", bg=BG_BODY).grid(
            row=row, column=4, sticky="e")
        if tooltip:
            tip(s, tooltip)

    def _select_image(self, idx):
        self._sel_img = idx
        self._refresh_images()

    def _show_image_preview(self):
        if self._sel_img < 0 or self._sel_img >= len(self.image_paths):
            messagebox.showinfo("プレビュー", "画像を選択してください")
            return
        path = self.image_paths[self._sel_img]
        try:
            img   = Image.open(path)
            img   = crop_with_offset(img, self._PREV_W, self._PREV_H,
                                      self._crop_h_offset.get(), self._crop_v_offset.get())
            photo = ImageTk.PhotoImage(img)

            win = tk.Toplevel(self)
            win.title(f"プレビュー：{path.name}")
            win.resizable(False, False)
            win.configure(bg="#1C1C1C")
            lbl = tk.Label(win, image=photo, bg="#1C1C1C")
            lbl.image = photo
            lbl.pack()
            tk.Label(win, text=f"9:16（{self._PREV_W}×{self._PREV_H}）",
                     font=F_HINT, fg="#888", bg="#1C1C1C").pack(pady=(0, 4))
        except Exception as e:
            messagebox.showerror("プレビューエラー", str(e))

    # ── VOICEVOX スピーカー ───────────────────────────────

    def _fetch_speakers(self):
        def run():
            try:
                r = requests.get(f"{VV_URL}/speakers", timeout=3)
                self.speakers = [
                    (f"{sp['name']}  [{st['name']}]", st["id"])
                    for sp in r.json()
                    for st in sp["styles"]
                ]
                self.after(0, self._apply_speakers)
            except Exception:
                self.after(0, lambda: self._speaker_cb.configure(
                    values=["← VOICEVOXを起動してください"]))
        threading.Thread(target=run, daemon=True).start()

    def _apply_speakers(self):
        names = [name for name, _ in self.speakers]
        self._speaker_cb.configure(values=names)
        if names:
            self._speaker_cb.current(0)
            for i, (_, sid) in enumerate(self.speakers):
                if sid == 3:
                    self._speaker_cb.current(i)
                    break

    def _speaker_id(self) -> int:
        idx = self._speaker_cb.current()
        return self.speakers[idx][1] if 0 <= idx < len(self.speakers) else 3

    # ── ボイスプレビュー ──────────────────────────────────

    def _preview_voice(self):
        def run():
            try:
                text = strip_ruby(self._narr_text.get("1.0", "end").strip()[:80]) or "テスト再生です"
                q = requests.post(f"{VV_URL}/audio_query",
                                  params={"text": text, "speaker": self._speaker_id()})
                q.raise_for_status()
                query = q.json()
                query["speedScale"]          = round(self._speed_var.get(), 2)
                query["pitchScale"]          = round(self._pitch_var.get(), 2)
                query["outputSamplingRate"]  = 44100
                r = requests.post(f"{VV_URL}/synthesis",
                                  headers={"Content-Type": "application/json"},
                                  params={"speaker": self._speaker_id()},
                                  data=json.dumps(query))
                r.raise_for_status()
                tmp = tempfile.NamedTemporaryFile(suffix=".wav", delete=False)
                tmp.write(r.content)
                tmp.close()
                self.after(0, lambda: play_file(tmp.name))
            except Exception as e:
                self.after(0, lambda: messagebox.showerror(
                    "エラー", f"VOICEVOX接続失敗\n\n{e}\n\nVOICEVOXが起動しているか確認してください"))
        threading.Thread(target=run, daemon=True).start()

    # ── 設定の読み書き ────────────────────────────────────

    def _load_config(self):
        if not CONFIG.exists():
            return
        with open(CONFIG, encoding="utf-8") as f:
            self._apply_config(json.load(f))
        self._current_config_path = CONFIG

    def _apply_config(self, cfg: dict):
        self._title_var.set(cfg.get("title", ""))
        self._desc_var.set(cfg.get("description", ""))
        self._bgm_vol_var.set(cfg.get("bgm_volume", 0.18))
        self._narr_vol_var.set(cfg.get("narration_volume", 2.0))

        out = cfg.get("output", str(BASE_DIR / "output" / "video.mp4"))
        self._output_var.set(str(BASE_DIR / out) if not Path(out).is_absolute() else out)

        mode = cfg.get("voice_mode", "voicevox")
        self._voice_mode.set(mode)
        self._toggle_voice()

        tts = cfg.get("tts", {})
        self._narr_text.delete("1.0", "end")
        self._narr_text.insert("1.0", tts.get("text", ""))
        self._speed_var.set(tts.get("speed", 1.1))
        self._pitch_var.set(tts.get("pitch", 0.0))

        if cfg.get("bgm"):
            self._bgm_panel.select_by_path(cfg["bgm"])
        if cfg.get("narration") and mode == "file":
            self._narr_panel.select_by_path(cfg["narration"])

        dur = cfg.get("duration")
        if dur is None:
            self._duration_mode.set("auto")
        else:
            self._duration_mode.set("manual")
            self._duration_var.set(int(dur))
        self._toggle_duration()

        self._crop_h_offset.set(cfg.get("crop_h_offset", 0))
        self._crop_v_offset.set(cfg.get("crop_v_offset", 0))

        self.image_paths = [Path(p) for p in cfg.get("images", []) if Path(p).exists()]
        self._refresh_images()

    def _build_config(self) -> dict:
        def to_relative(p: Path) -> str:
            try:
                return str(p.relative_to(BASE_DIR)).replace("\\", "/")
            except ValueError:
                return str(p).replace("\\", "/")

        cfg = {
            "title":              self._title_var.get(),
            "description":        self._desc_var.get(),
            "voice_mode":         self._voice_mode.get(),
            "bgm_volume":         round(self._bgm_vol_var.get(), 2),
            "narration_volume":   round(self._narr_vol_var.get(), 1),
            "duration":           None if self._duration_mode.get() == "auto" else int(self._duration_var.get()),
            "crop_h_offset":      int(self._crop_h_offset.get()),
            "crop_v_offset":      int(self._crop_v_offset.get()),
            "images":             [to_relative(p) for p in self.image_paths],
            "output":             self._output_var.get(),
        }

        bgm = self._bgm_panel.selected()
        if bgm:
            cfg["bgm"] = to_relative(bgm)

        if self._voice_mode.get() == "voicevox":
            cfg["tts"] = {
                "engine":     "voicevox",
                "speaker_id": self._speaker_id(),
                "speed":      round(self._speed_var.get(), 2),
                "pitch":      round(self._pitch_var.get(), 2),
                "text":       self._narr_text.get("1.0", "end").strip(),
            }
        else:
            narr = self._narr_panel.selected()
            if narr:
                cfg["narration"] = to_relative(narr)
            else:
                messagebox.showwarning("警告", "録音ファイルが選択されていません")

        return cfg

    def _write_config(self, path: Path, cfg: dict):
        with open(path, "w", encoding="utf-8") as f:
            json.dump(cfg, f, ensure_ascii=False, indent=2)

    def _browse_output(self):
        path = filedialog.asksaveasfilename(
            title="動画の保存先を選択",
            defaultextension=".mp4",
            filetypes=[("MP4動画", "*.mp4"), ("すべて", "*.*")],
            initialfile="video.mp4",
            initialdir=str(BASE_DIR / "output"),
        )
        if path:
            self._output_var.set(path)

    def _save_config_dialog(self):
        target = None

        if self._current_config_path:
            choice = messagebox.askyesnocancel(
                "保存方法を選択",
                "上書き保存しますか？\n\n"
                "「はい」  → 同じファイルに上書き\n"
                "「いいえ」→ 別名で保存\n"
                "「キャンセル」→ 中止",
            )
            if choice is None:
                return
            if choice:
                target = self._current_config_path

        if target is None:
            path = filedialog.asksaveasfilename(
                title="設定を保存",
                defaultextension=".json",
                filetypes=[("設定ファイル", "*.json"), ("すべて", "*.*")],
                initialfile=self._current_config_path.name if self._current_config_path else "config.json",
                initialdir=str(self._current_config_path.parent if self._current_config_path else BASE_DIR),
            )
            if not path:
                return
            target = Path(path)

        cfg = self._build_config()
        self._write_config(target, cfg)
        if target != CONFIG:
            self._write_config(CONFIG, cfg)

        self._current_config_path = target
        self._status.set(f"✓  保存: {target.name}")

    def _save_config(self):
        self._write_config(CONFIG, self._build_config())
        self._status.set("✓  設定を保存しました")

    def _load_config_dialog(self):
        path = filedialog.askopenfilename(
            title="設定を読み込む",
            filetypes=[("設定ファイル", "*.json"), ("すべて", "*.*")],
            initialdir=str(BASE_DIR),
        )
        if not path:
            return
        with open(path, encoding="utf-8") as f:
            cfg = json.load(f)
        self._apply_config(cfg)
        self._current_config_path = Path(path)
        self._status.set(f"✓  読み込み: {Path(path).name}")

    # ── 動画生成 ──────────────────────────────────────────

    def _generate(self):
        if not self.image_paths:
            messagebox.showwarning("警告", "画像を1枚以上追加してください")
            return

        stop_audio()
        self._save_config()

        win = tk.Toplevel(self)
        win.title("動画生成中...")
        win.geometry("660x380")
        win.grab_set()
        tk.Label(win, text="動画を生成しています。完了まで1〜2分かかります...",
                 font=F_NORMAL, pady=8).pack()
        log = scrolledtext.ScrolledText(win, state="disabled",
                                        font=("Consolas", 9), bg="#1e1e1e", fg="#d4d4d4")
        log.pack(fill="both", expand=True, padx=8, pady=(0, 8))

        def append(text):
            log.configure(state="normal")
            log.insert("end", text)
            log.see("end")
            log.configure(state="disabled")

        output_path = Path(self._output_var.get()).resolve()

        def run():
            proc = subprocess.Popen(
                ["python", "generate_video.py"], cwd=BASE_DIR,
                stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                text=True, encoding="utf-8", errors="replace",
            )
            for line in proc.stdout:
                self.after(0, append, line)
            proc.wait()

            if proc.returncode == 0:
                self.after(0, win.destroy)
                self.after(0, lambda: messagebox.showinfo(
                    "完了 🎉", f"動画を生成しました！\n\n{output_path}"))
                self.after(0, lambda: self._status.set("✓  動画生成完了"))
            else:
                self.after(0, lambda: messagebox.showerror(
                    "エラー", "動画生成に失敗しました。ログを確認してください。"))
                self.after(0, lambda: self._status.set("✗  エラーが発生しました"))

        threading.Thread(target=run, daemon=True).start()
        self._status.set("動画を生成中...")


if __name__ == "__main__":
    App().mainloop()
