#!/usr/bin/env python3
"""YouTube Shorts Generator - アコーディオン UI"""

import ctypes, json, shutil, subprocess, tempfile, threading, tkinter as tk
from tkinter import ttk, filedialog, messagebox, scrolledtext
from pathlib import Path

import requests
from PIL import Image, ImageTk

BASE_DIR  = Path(__file__).parent
INPUT_DIR = BASE_DIR / "input"
IMG_DIR   = INPUT_DIR / "images"
BGM_DIR   = INPUT_DIR / "bgm"
NARR_DIR  = INPUT_DIR / "narration"
CONFIG    = BASE_DIR / "config.json"
VV_URL    = "http://localhost:50021"

AUDIO_EXT    = {".mp3", ".wav", ".ogg", ".m4a"}
THUMB_W, THUMB_H = 88, 156
F_NORMAL = ("Yu Gothic UI", 11)
F_HINT   = ("Yu Gothic UI",  9)
F_STEP   = ("Yu Gothic UI", 10, "bold")
F_HEAD   = ("Yu Gothic UI", 12, "bold")
F_TEXT   = ("Yu Gothic UI", 11)
BG_BODY  = "#F4F4F6"
BG_PAGE  = "#DCDCE4"

# ── ディープトーン配色 ────────────────────────────────────
C_IMAGE  = "#1A3D5C"   # ① ディープ・スチールブルー
C_VOICE  = "#3D1A5C"   # ② ディープ・バイオレット
C_BGM    = "#1A5C3A"   # ③ ディープ・フォレストグリーン
C_INFO   = "#5C1A1A"   # ④ ディープ・バーガンディ
C_EDIT   = "#2A2A4A"   # ⑤ ディープ・インディゴ（動画編集）
C_DARK   = "#1C1C1C"   # ナビ・ボトムバー
COLORS   = [C_IMAGE, C_VOICE, C_BGM, C_INFO, C_EDIT]


# ── MCI 音声再生 ──────────────────────────────────────────

_winmm = ctypes.windll.winmm

def _mci(cmd):     _winmm.mciSendStringW(cmd, None, 0, None)
def play_file(p):  _mci("stop media"); _mci("close media"); _mci(f'open "{p}" alias media'); _mci("play media")
def stop_audio():  _mci("stop media"); _mci("close media")


# ── ツールチップ ──────────────────────────────────────────

class Tooltip:
    def __init__(self, w, text):
        self._w, self._t, self._job, self._win = w, text, None, None
        w.bind("<Enter>", self._sch); w.bind("<Leave>", self._cancel)
    def _sch(self, _=None):
        self._cancel(); self._job = self._w.after(500, self._show)
    def _cancel(self, _=None):
        if self._job: self._w.after_cancel(self._job); self._job = None
        if self._win: self._win.destroy(); self._win = None
    def _show(self):
        x = self._w.winfo_rootx() + 12; y = self._w.winfo_rooty() + self._w.winfo_height() + 4
        self._win = tw = tk.Toplevel(self._w); tw.wm_overrideredirect(True); tw.wm_geometry(f"+{x}+{y}")
        tk.Label(tw, text=self._t, justify="left", bg="#ffffd0", relief="solid",
                 borderwidth=1, font=F_HINT, wraplength=300, padx=6, pady=4).pack()

def tip(w, t): Tooltip(w, t)


# ── アコーディオンセクション ──────────────────────────────

class AccordionSection(tk.Frame):
    """タイトルのみ表示→▼クリックで展開するセクション"""

    def __init__(self, master, title, subtitle, color, **kw):
        super().__init__(master, bg=BG_PAGE, **kw)
        self.columnconfigure(0, weight=1)
        self._color    = color
        self._expanded = False

        # ── ヘッダー（常時表示） ──────────────────────────
        hdr = tk.Frame(self, bg=color, padx=14, pady=0, cursor="hand2")
        hdr.grid(row=0, column=0, sticky="ew")
        hdr.columnconfigure(1, weight=1)

        # タイトル行
        title_row = tk.Frame(hdr, bg=color, pady=10)
        title_row.grid(row=0, column=0, columnspan=3, sticky="ew")
        title_row.columnconfigure(1, weight=1)

        tk.Label(title_row, text=title, bg=color, fg="white",
                 font=F_HEAD, anchor="w").grid(row=0, column=0, sticky="w")

        self._arrow = tk.Label(title_row, text="▼", bg=color, fg="white",
                               font=("Yu Gothic UI", 11), cursor="hand2")
        self._arrow.grid(row=0, column=2, sticky="e", padx=(8, 0))

        # サブテキスト行
        self._sub = tk.Label(hdr, text=subtitle, bg=color, fg="#F0C8A8",
                             font=F_HINT, anchor="w", justify="left", wraplength=1, pady=4)
        self._sub.grid(row=1, column=0, columnspan=3, sticky="ew")

        hdr.bind("<Configure>", self._wrap)
        hdr.bind("<Map>",       lambda e: hdr.after(60, self._wrap))

        for w in [hdr, title_row, self._arrow]:
            w.bind("<Button-1>", self.toggle)

        # ── ボディ（折りたたみ） ──────────────────────────
        self._body = tk.Frame(self, bg=BG_BODY, padx=14, pady=12)
        self._body.columnconfigure(0, weight=1)

    def _wrap(self, e=None):
        w = self._sub.master.winfo_width()
        if w > 30: self._sub.configure(wraplength=max(60, w - 28))

    def toggle(self, _=None):
        if self._expanded:
            self._body.grid_remove()
            self._arrow.config(text="▼")
        else:
            self._body.grid(row=2, column=0, sticky="nsew")
            self._arrow.config(text="▲")
        self._expanded = not self._expanded

    def expand(self):
        if not self._expanded: self.toggle()

    @property
    def body(self): return self._body


# ── ファイルリストパネル ──────────────────────────────────

class FileListPanel(ttk.Frame):
    def __init__(self, master, folder, height=6, **kw):
        super().__init__(master, **kw)
        self.folder = folder; self.paths: list[Path] = []
        self.columnconfigure(0, weight=1); self.rowconfigure(1, weight=1)

        bf = ttk.Frame(self); bf.grid(row=0, column=0, sticky="ew", pady=(0, 4))
        for txt, cmd, tooltip in [
            ("＋ 追加", self._add,   "音声ファイルを追加（自動でフォルダにコピー）"),
            ("▶ 再生",  self._play,  "選択中のファイルをプレビュー再生"),
            ("■ 停止",  stop_audio,  "再生を停止"),
            ("✕",       self._remove,"リストから削除（元ファイルは残ります）"),
        ]:
            b = ttk.Button(bf, text=txt, command=cmd, **({"width": 3} if len(txt)==1 else {}))
            b.pack(side="left", padx=2); tip(b, tooltip)

        lf = ttk.Frame(self); lf.grid(row=1, column=0, sticky="nsew")
        lf.columnconfigure(0, weight=1); lf.rowconfigure(0, weight=1)
        self._lb = tk.Listbox(lf, selectmode="single", font=F_NORMAL,
                              activestyle="none", cursor="hand2", height=height)
        sb = ttk.Scrollbar(lf, orient="vertical", command=self._lb.yview)
        self._lb.configure(yscrollcommand=sb.set)
        self._lb.grid(row=0, column=0, sticky="nsew"); sb.grid(row=0, column=1, sticky="ns")
        self._lb.bind("<Double-Button-1>", lambda e: self._play())
        self.scan()

    def scan(self):
        self.folder.mkdir(parents=True, exist_ok=True)
        self.paths = sorted(p for p in self.folder.iterdir() if p.suffix.lower() in AUDIO_EXT)
        self._lb.delete(0, "end")
        for p in self.paths: self._lb.insert("end", f"  {p.name}")

    def selected(self):
        sel = self._lb.curselection()
        return self.paths[sel[0]] if sel else None

    def select_by_path(self, path):
        p = Path(path)
        for i, q in enumerate(self.paths):
            if q.name == p.name or q == p:
                self._lb.selection_clear(0, "end"); self._lb.selection_set(i); self._lb.see(i); return

    def _add(self):
        files = filedialog.askopenfilenames(title="音声ファイルを追加",
            filetypes=[("音声", "*.mp3 *.wav *.ogg *.m4a"), ("すべて", "*.*")])
        for f in files:
            src, dst = Path(f), self.folder / Path(f).name
            if src != dst: shutil.copy2(src, dst)
        self.scan()

    def _remove(self):
        sel = self._lb.curselection()
        if sel: self.paths.pop(sel[0]); self._lb.delete(sel[0])

    def _play(self):
        p = self.selected()
        if p: play_file(str(p))
        else: messagebox.showinfo("再生", "ファイルを選択してください")


# ── メインアプリ ──────────────────────────────────────────

class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("YouTube Shorts Generator")
        self.geometry("780x700")
        self.minsize(620, 500)
        self.columnconfigure(0, weight=1)
        self.rowconfigure(1, weight=1)

        self.image_paths:        list[Path]  = []
        self._thumbs:            list        = []
        self._sel_img:           int         = -1
        self.speakers:           list        = []
        self._current_config_path: Path|None = None

        self._build_ui()
        self._load_config()
        self._fetch_speakers()

    # ── UI構築 ────────────────────────────────────────────

    def _build_ui(self):
        self._build_step_guide()
        self._build_accordion()
        self._build_bottom()

    # ── ステップガイド ────────────────────────────────────

    def _build_step_guide(self):
        bg = "#1C1C1C"
        sf = tk.Frame(self, bg=bg, pady=8)
        sf.grid(row=0, column=0, sticky="ew")
        tk.Label(sf, text="使い方：", bg=bg, fg="#AAAACC", font=F_STEP).pack(side="left", padx=(14, 8))
        chips = [("①","画像を追加"), ("②","ボイス設定"), ("③","BGM選択"), ("④","情報入力"), ("⑤","💾保存→🎬生成")]
        chip_colors = [C_IMAGE, C_VOICE, C_BGM, C_INFO, "#2A2A4A"]
        for i, ((num, lbl), c) in enumerate(zip(chips, chip_colors)):
            if i: tk.Label(sf, text="→", bg=bg, fg="#555577", font=("Yu Gothic UI", 12)).pack(side="left", padx=2)
            chip = tk.Frame(sf, bg=c, padx=10, pady=4); chip.pack(side="left", padx=2)
            tk.Label(chip, text=num, bg=c, fg="#B0C8E8", font=("Yu Gothic UI", 10, "bold")).pack(side="left")
            tk.Label(chip, text=f" {lbl}", bg=c, fg="white", font=("Yu Gothic UI", 10)).pack(side="left")

    # ── アコーディオン本体 ────────────────────────────────

    def _build_accordion(self):
        # スクロール可能なキャンバス
        self._cv = tk.Canvas(self, bg=BG_PAGE, highlightthickness=0)
        sb = ttk.Scrollbar(self, orient="vertical", command=self._cv.yview)
        self._cv.configure(yscrollcommand=sb.set)
        self._cv.grid(row=1, column=0, sticky="nsew")
        sb.grid(row=1, column=1, sticky="ns")

        inner = tk.Frame(self._cv, bg=BG_PAGE); inner.columnconfigure(0, weight=1)
        self._win_id = self._cv.create_window((0, 0), window=inner, anchor="nw")

        inner.bind("<Configure>", lambda e: self._cv.configure(scrollregion=self._cv.bbox("all")))
        self._cv.bind("<Configure>", lambda e: self._cv.itemconfig(self._win_id, width=e.width))
        self.bind_all("<MouseWheel>", lambda e: self._cv.yview_scroll(-1*(e.delta//120), "units"))

        # セクション生成
        sec_defs = [
            ("📷  使用画像",      "AI生成画像を追加して ↑↓ で表示順を調整します（最大5枚推奨）", C_IMAGE),
            ("🎙  ボイス設定",    "VOICEVOX合成音声 または 録音ファイルを設定します", C_VOICE),
            ("🎵  BGMライブラリ", "クリックでBGMを選択し ▶ でテスト再生できます", C_BGM),
            ("📝  動画情報＆音量","タイトル・説明文・音量バランスと保存先を設定します", C_INFO),
        ]
        secs = [AccordionSection(inner, t, s, c) for t, s, c in sec_defs]
        for i, sec in enumerate(secs):
            sec.grid(row=i, column=0, sticky="ew", padx=8, pady=(8 if i==0 else 4, 4))

        self._sec_img, self._sec_voice, self._sec_bgm, self._sec_info = secs
        self._build_image_content(self._sec_img.body)
        self._build_voice_content(self._sec_voice.body)
        self._build_bgm_content(self._sec_bgm.body)
        self._build_info_content(self._sec_info.body)

    # ── セクション①：使用画像 ────────────────────────────

    def _build_image_content(self, body):
        body.columnconfigure(0, weight=1)

        bf = tk.Frame(body, bg=BG_BODY); bf.grid(row=0, column=0, sticky="ew", pady=(0, 8))
        for txt, cmd, tooltip in [
            ("＋ 追加", self._add_images,   "画像ファイルを選択して追加（PNG・JPG・WEBP対応）"),
            ("↑",       self._move_up,      "選択した画像を1つ前に移動"),
            ("↓",       self._move_down,    "選択した画像を1つ後ろに移動"),
            ("✕",       self._remove_image, "リストから削除（元ファイルは残ります）"),
        ]:
            b = ttk.Button(bf, text=txt, command=cmd, **({"width": 3} if len(txt)==1 else {}))
            b.pack(side="left", padx=2); tip(b, tooltip)

        self._img_list_frame = tk.Frame(body, bg=BG_BODY)
        self._img_list_frame.grid(row=1, column=0, sticky="ew")
        self._img_list_frame.columnconfigure(0, weight=1)

    # ── セクション②：ボイス設定 ──────────────────────────

    def _build_voice_content(self, body):
        body.columnconfigure(1, weight=1)

        # 入力方式
        tk.Label(body, text="入力方式", font=F_NORMAL, bg=BG_BODY).grid(
            row=0, column=0, sticky="w", pady=4)
        self._voice_mode = tk.StringVar(value="voicevox")
        mf = tk.Frame(body, bg=BG_BODY); mf.grid(row=0, column=1, columnspan=2, sticky="w", padx=(8,0))
        rb1 = ttk.Radiobutton(mf, text="VOICEVOX（合成音声）",
                               variable=self._voice_mode, value="voicevox", command=self._toggle_voice)
        rb1.pack(side="left")
        tip(rb1, "テキストを入力するとAIが自動で読み上げます\n※ VOICEVOXを先に起動してください")
        rb2 = ttk.Radiobutton(mf, text="録音ファイル",
                               variable=self._voice_mode, value="file", command=self._toggle_voice)
        rb2.pack(side="left", padx=(16, 0))
        tip(rb2, "自分でマイク録音したWAVファイルを使います")

        ttk.Separator(body, orient="horizontal").grid(
            row=1, column=0, columnspan=3, sticky="ew", pady=8)

        # VOICEVOX フレーム
        self._vv_frame = tk.Frame(body, bg=BG_BODY); self._vv_frame.grid(row=2, column=0, columnspan=3, sticky="ew")
        self._vv_frame.columnconfigure(1, weight=1)
        self._build_vv_settings(self._vv_frame)

        # 録音ファイルフレーム
        self._narr_frame = tk.Frame(body, bg=BG_BODY); self._narr_frame.grid(row=2, column=0, columnspan=3, sticky="nsew")
        self._narr_frame.columnconfigure(0, weight=1); self._narr_frame.rowconfigure(1, weight=1)
        body.rowconfigure(2, weight=1)
        tk.Label(self._narr_frame, text="録音したWAVファイルを追加して選択してください",
                 font=F_HINT, fg="#777", bg=BG_BODY).grid(row=0, column=0, sticky="w", pady=(0,4))
        self._narr_panel = FileListPanel(self._narr_frame, NARR_DIR, height=5)
        self._narr_panel.grid(row=1, column=0, sticky="nsew")

        self._toggle_voice()

    def _build_vv_settings(self, parent):
        tk.Label(parent, text="キャラクター", font=F_NORMAL, bg=BG_BODY).grid(row=0, column=0, sticky="w", pady=4)
        self._speaker_var = tk.StringVar()
        self._speaker_cb  = ttk.Combobox(parent, textvariable=self._speaker_var,
                                          state="readonly", font=F_NORMAL)
        self._speaker_cb.grid(row=0, column=1, columnspan=2, sticky="ew", padx=(8,0))
        tip(self._speaker_cb, "読み上げキャラを選択\n例）ずんだもん、四国めたん など")

        tk.Label(parent, text="速度", font=F_NORMAL, bg=BG_BODY).grid(row=1, column=0, sticky="w", pady=4)
        self._speed_var = tk.DoubleVar(value=1.1)
        self._slider(parent, self._speed_var, 0.5, 2.0, 1, ".1f",
                     "読み上げ速度（1.0=標準）ショート動画には 1.1〜1.3 がおすすめ")

        tk.Label(parent, text="ピッチ", font=F_NORMAL, bg=BG_BODY).grid(row=2, column=0, sticky="w", pady=4)
        self._pitch_var = tk.DoubleVar(value=0.0)
        self._slider(parent, self._pitch_var, -0.15, 0.15, 2, ".2f",
                     "声の高さ（0.0=標準、＋で高く、−で低く）")

        tk.Label(parent, text="台本", font=F_NORMAL, bg=BG_BODY).grid(row=3, column=0, sticky="nw", pady=4)
        self._narr_text = tk.Text(parent, height=6, wrap="word", font=F_TEXT)
        self._narr_text.grid(row=3, column=1, columnspan=2, sticky="ew", padx=(8,0))
        tip(self._narr_text, "動画で読み上げるテキストを入力\n目安：1分以内（200〜400文字程度）\n▶テスト再生は最初の80文字のみ再生されます")

        pb = tk.Frame(parent, bg=BG_BODY)
        pb.grid(row=4, column=1, columnspan=2, sticky="e", padx=(8,0), pady=(8,0))
        b = ttk.Button(pb, text="▶  テスト再生", command=self._preview_voice)
        b.pack(side="left", padx=2); tip(b, "台本の冒頭80文字をキャラクターの声でプレビューします")
        b = ttk.Button(pb, text="■  停止", command=stop_audio)
        b.pack(side="left", padx=2); tip(b, "再生を停止します")

    def _toggle_voice(self):
        if self._voice_mode.get() == "voicevox":
            self._narr_frame.grid_remove(); self._vv_frame.grid()
        else:
            self._vv_frame.grid_remove(); self._narr_frame.grid()

    # ── セクション③：BGM ─────────────────────────────────

    def _build_bgm_content(self, body):
        body.columnconfigure(0, weight=1); body.rowconfigure(0, weight=1)
        self._bgm_panel = FileListPanel(body, BGM_DIR, height=6)
        self._bgm_panel.grid(row=0, column=0, sticky="nsew")

    # ── セクション④：動画情報＆音量 ──────────────────────

    def _build_info_content(self, body):
        body.columnconfigure(1, weight=1)

        for row, (lbl, var_attr, tooltip) in enumerate([
            ("タイトル", "_title_var", "動画下部に大きく表示されるタイトルテキスト"),
            ("説明文",   "_desc_var",  "タイトルの下に小さく表示される補足テキスト"),
        ]):
            tk.Label(body, text=lbl, font=F_NORMAL, bg=BG_BODY).grid(row=row, column=0, sticky="w", pady=4)
            setattr(self, var_attr, tk.StringVar())
            e = ttk.Entry(body, textvariable=getattr(self, var_attr), font=F_NORMAL)
            e.grid(row=row, column=1, columnspan=2, sticky="ew", padx=(8,0))
            tip(e, tooltip)

        ttk.Separator(body, orient="horizontal").grid(row=2, column=0, columnspan=3, sticky="ew", pady=8)

        tk.Label(body, text="BGM音量", font=F_NORMAL, bg=BG_BODY).grid(row=3, column=0, sticky="w", pady=4)
        self._bgm_vol_var = tk.DoubleVar(value=0.18)
        self._slider(body, self._bgm_vol_var, 0.0, 1.0, 3, ".2f",
                     "BGMの音量（0.0=無音、1.0=最大）\n0.15〜0.25 程度が聞き取りやすい")

        tk.Label(body, text="ナレーション音量", font=F_NORMAL, bg=BG_BODY).grid(row=4, column=0, sticky="w", pady=4)
        self._narr_vol_var = tk.DoubleVar(value=2.0)
        self._slider(body, self._narr_vol_var, 0.5, 4.0, 4, ".1f",
                     "ナレーションの音量倍率（2.0=元の2倍）")

        ttk.Separator(body, orient="horizontal").grid(row=5, column=0, columnspan=3, sticky="ew", pady=8)

        # 動画の保存先
        tk.Label(body, text="動画の保存先", font=F_NORMAL, bg=BG_BODY).grid(row=6, column=0, sticky="w", pady=4)
        self._output_var = tk.StringVar(value=str(BASE_DIR / "output" / "video.mp4"))
        out_f = tk.Frame(body, bg=BG_BODY); out_f.grid(row=6, column=1, columnspan=2, sticky="ew", padx=(8,0))
        out_f.columnconfigure(0, weight=1)
        e = ttk.Entry(out_f, textvariable=self._output_var, font=F_NORMAL)
        e.grid(row=0, column=0, sticky="ew")
        tip(e, "生成した動画の保存先パスを指定します")
        b = ttk.Button(out_f, text="参照", command=self._browse_output)
        b.grid(row=0, column=1, padx=(4,0))
        tip(b, "保存先をダイアログで選択します")

    # ── 下部ボタンバー ────────────────────────────────────

    def _build_bottom(self):
        bf = tk.Frame(self, bg=C_DARK, pady=8)
        bf.grid(row=2, column=0, columnspan=2, sticky="ew")
        bf.columnconfigure(2, weight=1)

        self._status = tk.StringVar(value="準備完了")
        tk.Label(bf, textvariable=self._status, fg="#AAAACC",
                 bg=C_DARK, font=F_NORMAL).grid(row=0, column=3, padx=12, sticky="w")

        b_load = ttk.Button(bf, text="📂  設定を読み込む", command=self._load_config_dialog)
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

        b_save = ttk.Button(bf, text="💾  設定を保存", command=self._save_config_dialog)
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

        b_gen = tk.Button(bf, text="  🎬  動画を生成する  ", command=self._generate,
                          bg=C_IMAGE, fg="white", font=("Yu Gothic UI", 12, "bold"),
                          relief="flat", padx=8, pady=6, cursor="hand2",
                          activebackground="#0E2A3F", activeforeground="white")
        b_gen.grid(row=0, column=4, padx=(4, 12))
        tip(b_gen, "現在の設定を保存してから動画を生成します\n完了まで1〜2分かかります")

    # ── スライダーヘルパー ────────────────────────────────

    def _slider(self, parent, var, from_, to, row, fmt, tooltip=""):
        frame = tk.Frame(parent, bg=BG_BODY)
        frame.grid(row=row, column=1, columnspan=2, sticky="ew", padx=(8,0), pady=4)
        frame.columnconfigure(0, weight=1)
        lbl = tk.Label(frame, text=f"{var.get():{fmt}}", width=6, font=F_NORMAL, bg=BG_BODY)
        s = ttk.Scale(frame, from_=from_, to=to, variable=var, orient="horizontal")
        s.grid(row=0, column=0, sticky="ew"); lbl.grid(row=0, column=1, padx=(6,0))
        var.trace_add("write", lambda *_: lbl.config(text=f"{var.get():{fmt}}"))
        if tooltip: tip(s, tooltip); tip(lbl, tooltip)

    # ── 画像操作 ──────────────────────────────────────────

    def _add_images(self):
        files = filedialog.askopenfilenames(title="画像を選択（複数可）",
            filetypes=[("画像", "*.png *.jpg *.jpeg *.webp"), ("すべて", "*.*")])
        IMG_DIR.mkdir(parents=True, exist_ok=True)
        for f in files:
            src, dst = Path(f), IMG_DIR / Path(f).name
            if src != dst: shutil.copy2(src, dst)
            if dst not in self.image_paths: self.image_paths.append(dst)
        self._refresh_images()

    def _remove_image(self):
        if self._sel_img >= 0:
            self.image_paths.pop(self._sel_img)
            self._sel_img = min(self._sel_img, len(self.image_paths)-1)
            self._refresh_images()

    def _move_up(self):
        i = self._sel_img
        if i > 0:
            self.image_paths[i-1], self.image_paths[i] = self.image_paths[i], self.image_paths[i-1]
            self._sel_img = i-1; self._refresh_images()

    def _move_down(self):
        i = self._sel_img
        if 0 <= i < len(self.image_paths)-1:
            self.image_paths[i], self.image_paths[i+1] = self.image_paths[i+1], self.image_paths[i]
            self._sel_img = i+1; self._refresh_images()

    def _refresh_images(self):
        for w in self._img_list_frame.winfo_children(): w.destroy()
        self._thumbs.clear()
        for i, p in enumerate(self.image_paths):
            bg = "#CCE4FF" if i == self._sel_img else BG_BODY
            row = tk.Frame(self._img_list_frame, bg=bg, cursor="hand2")
            row.pack(fill="x", pady=2)
            try:
                img = Image.open(p); img.thumbnail((THUMB_W, THUMB_H))
                photo = ImageTk.PhotoImage(img); self._thumbs.append(photo)
                tk.Label(row, image=photo, bg=bg).pack(side="left", padx=4, pady=4)
            except Exception:
                tk.Label(row, text="?", width=6, bg=bg, font=F_NORMAL).pack(side="left")
            tk.Label(row, text=f"{i+1}.  {p.name}", anchor="w",
                     bg=bg, font=F_NORMAL).pack(side="left", fill="x", expand=True)
            for w in [row] + list(row.winfo_children()):
                w.bind("<Button-1>", lambda e, idx=i: self._sel_image(idx))

    def _sel_image(self, idx): self._sel_img = idx; self._refresh_images()

    # ── スピーカー ────────────────────────────────────────

    def _fetch_speakers(self):
        def run():
            try:
                r = requests.get(f"{VV_URL}/speakers", timeout=3)
                self.speakers = [(f"{sp['name']}  [{st['name']}]", st["id"])
                                 for sp in r.json() for st in sp["styles"]]
                self.after(0, self._apply_speakers)
            except Exception:
                self.after(0, lambda: self._speaker_cb.configure(values=["← VOICEVOXを起動してください"]))
        threading.Thread(target=run, daemon=True).start()

    def _apply_speakers(self):
        vals = [n for n, _ in self.speakers]
        self._speaker_cb.configure(values=vals)
        if vals:
            self._speaker_cb.current(0)
            for i, (_, sid) in enumerate(self.speakers):
                if sid == 3: self._speaker_cb.current(i); break

    def _speaker_id(self):
        idx = self._speaker_cb.current()
        return self.speakers[idx][1] if 0 <= idx < len(self.speakers) else 3

    # ── ボイスプレビュー ──────────────────────────────────

    def _preview_voice(self):
        def run():
            try:
                text = self._narr_text.get("1.0", "end").strip()[:80] or "テスト再生です"
                q = requests.post(f"{VV_URL}/audio_query", params={"text": text, "speaker": self._speaker_id()})
                q.raise_for_status()
                query = q.json()
                query["speedScale"] = round(self._speed_var.get(), 2)
                query["pitchScale"] = round(self._pitch_var.get(), 2)
                query["outputSamplingRate"] = 44100
                r = requests.post(f"{VV_URL}/synthesis", headers={"Content-Type": "application/json"},
                                  params={"speaker": self._speaker_id()}, data=json.dumps(query))
                r.raise_for_status()
                tmp = tempfile.NamedTemporaryFile(suffix=".wav", delete=False)
                tmp.write(r.content); tmp.close()
                self.after(0, lambda: play_file(tmp.name))
            except Exception as e:
                self.after(0, lambda: messagebox.showerror("エラー",
                    f"VOICEVOX接続失敗\n\n{e}\n\nVOICEVOXが起動しているか確認してください"))
        threading.Thread(target=run, daemon=True).start()

    # ── config 読み書き ───────────────────────────────────

    def _load_config(self):
        if not CONFIG.exists(): return
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
        self._voice_mode.set(mode); self._toggle_voice()
        tts = cfg.get("tts", {})
        self._narr_text.delete("1.0", "end"); self._narr_text.insert("1.0", tts.get("text", ""))
        self._speed_var.set(tts.get("speed", 1.1)); self._pitch_var.set(tts.get("pitch", 0.0))
        if cfg.get("bgm"): self._bgm_panel.select_by_path(cfg["bgm"])
        if cfg.get("narration") and mode == "file": self._narr_panel.select_by_path(cfg["narration"])
        self.image_paths = [Path(p) for p in cfg.get("images", []) if Path(p).exists()]
        self._refresh_images()

    def _build_config(self):
        def rel(p):
            try: return str(p.relative_to(BASE_DIR)).replace("\\", "/")
            except ValueError: return str(p).replace("\\", "/")
        cfg = {
            "title": self._title_var.get(), "description": self._desc_var.get(),
            "voice_mode": self._voice_mode.get(),
            "bgm_volume": round(self._bgm_vol_var.get(), 2),
            "narration_volume": round(self._narr_vol_var.get(), 1),
            "images": [rel(p) for p in self.image_paths],
            "output": self._output_var.get(),
        }
        bgm = self._bgm_panel.selected()
        if bgm: cfg["bgm"] = rel(bgm)
        if self._voice_mode.get() == "voicevox":
            cfg["tts"] = {"engine": "voicevox", "speaker_id": self._speaker_id(),
                          "speed": round(self._speed_var.get(), 2),
                          "pitch": round(self._pitch_var.get(), 2),
                          "text": self._narr_text.get("1.0", "end").strip()}
        else:
            narr = self._narr_panel.selected()
            if narr: cfg["narration"] = rel(narr)
            else: messagebox.showwarning("警告", "録音ファイルが選択されていません")
        return cfg

    def _browse_output(self):
        path = filedialog.asksaveasfilename(
            title="動画の保存先を選択",
            defaultextension=".mp4",
            filetypes=[("MP4動画", "*.mp4"), ("すべて", "*.*")],
            initialfile="video.mp4",
            initialdir=str(BASE_DIR / "output"),
        )
        if path: self._output_var.set(path)

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
            if not path: return
            target = Path(path)

        cfg = self._build_config()
        with open(target, "w", encoding="utf-8") as f:
            json.dump(cfg, f, ensure_ascii=False, indent=2)
        if target != CONFIG:
            with open(CONFIG, "w", encoding="utf-8") as f:
                json.dump(cfg, f, ensure_ascii=False, indent=2)
        self._current_config_path = target
        self._status.set(f"✓  保存: {target.name}")

    def _save_config(self):
        with open(CONFIG, "w", encoding="utf-8") as f:
            json.dump(self._build_config(), f, ensure_ascii=False, indent=2)
        self._status.set("✓  設定を保存しました")

    def _load_config_dialog(self):
        path = filedialog.askopenfilename(
            title="設定を読み込む",
            filetypes=[("JSON設定ファイル", "*.json"), ("すべて", "*.*")],
            initialdir=str(BASE_DIR),
        )
        if not path: return
        with open(path, encoding="utf-8") as f:
            cfg = json.load(f)
        self._apply_config(cfg)
        self._current_config_path = Path(path)
        self._status.set(f"✓  読み込み: {Path(path).name}")

    # ── 動画生成 ──────────────────────────────────────────

    def _generate(self):
        if not self.image_paths:
            messagebox.showwarning("警告", "画像を1枚以上追加してください"); return
        stop_audio(); self._save_config()

        win = tk.Toplevel(self); win.title("動画生成中..."); win.geometry("660x380"); win.grab_set()
        tk.Label(win, text="動画を生成しています。完了まで1〜2分かかります...",
                 font=F_NORMAL, pady=8).pack()
        log = scrolledtext.ScrolledText(win, state="disabled",
                                        font=("Consolas", 9), bg="#1e1e1e", fg="#d4d4d4")
        log.pack(fill="both", expand=True, padx=8, pady=(0,8))

        def append(text):
            log.configure(state="normal"); log.insert("end", text); log.see("end"); log.configure(state="disabled")

        def run():
            proc = subprocess.Popen(["python", "generate_video.py"], cwd=BASE_DIR,
                stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                text=True, encoding="utf-8", errors="replace")
            for line in proc.stdout: self.after(0, append, line)
            proc.wait()
            if proc.returncode == 0:
                self.after(0, win.destroy)
                self.after(0, lambda: messagebox.showinfo("完了 🎉",
                    f"動画を生成しました！\n\n{(BASE_DIR/'output'/'video.mp4').resolve()}"))
                self.after(0, lambda: self._status.set("✓  動画生成完了"))
            else:
                self.after(0, lambda: messagebox.showerror("エラー", "動画生成に失敗しました。ログを確認してください。"))
                self.after(0, lambda: self._status.set("✗  エラーが発生しました"))

        threading.Thread(target=run, daemon=True).start()
        self._status.set("動画を生成中...")


if __name__ == "__main__":
    App().mainloop()
