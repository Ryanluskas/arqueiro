"""
gui.py — Bot Refinanciamento Consignado — Dark UI (v2, repaginada)
"""

from __future__ import annotations

import os
import queue
import subprocess
import sys
import threading
import tkinter as tk
from datetime import datetime
from tkinter import messagebox

import bot

# ═══════════════════════════ PALETA ═══════════════════════════════════════════
R      = "#EC0000"   # vermelho Santander (brand / acento)
R_HI   = "#ff2f2f"   # vermelho hover
R_DK   = "#5a0000"   # dot "rodando" apagado
GRN    = "#3ddc84"   # verde (com redução)
GRN_DK = "#0f3322"
ORG    = "#ffb01f"   # laranja (taxa)
ORG_DK = "#332407"
BLU    = "#5b8cff"   # azul info
ERR    = "#ff5b5b"   # erro
ERR_DK = "#331313"

WHT  = "#f4f4f7"     # texto principal
GRY  = "#9a9aa6"     # texto secundário
GRY2 = "#4a4a55"     # texto mudo / dot off
BDR  = "#272730"     # borda / linha

SB = "#0e0e13"       # sidebar bg
MN = "#141419"       # main bg
CD = "#1c1c25"       # card bg
CD2 = "#23232e"      # card hover
LG = "#0b0b0f"       # log bg
IP = "#101016"       # input bg

FONT      = "Segoe UI"
FONT_MONO = "Consolas"


def _now() -> str:
    return datetime.now().strftime("%H:%M")


def _br(v: float) -> str:
    """3411.0 → 'R$ 3.411'"""
    return f"R$ {int(v):,}".replace(",", ".")


def _round_rect(c: tk.Canvas, x1, y1, x2, y2, r, **kw):
    """Polígono suave = retângulo de cantos arredondados."""
    r = max(0, min(r, (x2 - x1) / 2, (y2 - y1) / 2))
    pts = [
        x1 + r, y1, x2 - r, y1, x2, y1, x2, y1 + r,
        x2, y2 - r, x2, y2, x2 - r, y2, x1 + r, y2,
        x1, y2, x1, y2 - r, x1, y1 + r, x1, y1,
    ]
    return c.create_polygon(pts, smooth=True, **kw)


def _open_path(path: str):
    try:
        if sys.platform.startswith("win"):
            os.startfile(path)  # type: ignore[attr-defined]
        elif sys.platform == "darwin":
            subprocess.Popen(["open", path])
        else:
            subprocess.Popen(["xdg-open", path])
    except Exception:
        pass


# ═══════════════════════════ WIDGETS BASE ═════════════════════════════════════
class RCard(tk.Canvas):
    """Superfície com cantos arredondados. Use `.body` (Frame) para o conteúdo."""

    def __init__(self, parent, bg=CD, radius=16, pad=14, parent_bg=None, **kw):
        super().__init__(parent, bd=0, highlightthickness=0,
                         bg=parent_bg or parent.cget("bg"), **kw)
        self._bg = bg
        self._radius = radius
        self._pad = pad
        self.body = tk.Frame(self, bg=bg)
        self._win = self.create_window(pad, pad, anchor="nw", window=self.body)
        self.bind("<Configure>", self._redraw)

    def _redraw(self, _ev=None):
        w, h = self.winfo_width(), self.winfo_height()
        self.delete("rc")
        _round_rect(self, 0, 0, w, h, self._radius,
                    fill=self._bg, outline="", tags="rc")
        self.tag_lower("rc")
        self.itemconfigure(self._win,
                           width=w - 2 * self._pad,
                           height=h - 2 * self._pad)


class RButton(tk.Canvas):
    """Botão com cantos arredondados + hover."""

    def __init__(self, parent, text, command, bg, fg=WHT, hover=None,
                 radius=11, font=(FONT, 11, "bold"), height=42, parent_bg=None):
        super().__init__(parent, height=height, bd=0, highlightthickness=0,
                         bg=parent_bg or parent.cget("bg"), cursor="hand2")
        self._bg = bg
        self._hover = hover or bg
        self._fg = fg
        self._radius = radius
        self._text = text
        self._font = font
        self._command = command
        self._rect = None
        self._lbl = None
        self.bind("<Configure>", self._draw)
        self.bind("<Button-1>", lambda e: command() if command else None)
        self.bind("<Enter>", lambda e: self._paint(self._hover))
        self.bind("<Leave>", lambda e: self._paint(self._bg))

    def _draw(self, _ev=None):
        self.delete("all")
        w, h = self.winfo_width(), self.winfo_height()
        self._rect = _round_rect(self, 0, 0, w, h, self._radius,
                                 fill=self._bg, outline="")
        self._lbl = self.create_text(w // 2, h // 2, text=self._text,
                                     fill=self._fg, font=self._font)

    def _paint(self, color):
        if self._rect is not None:
            self.itemconfigure(self._rect, fill=color)

    def set(self, text=None, bg=None, hover=None, fg=None):
        if text is not None:
            self._text = text
            if self._lbl is not None:
                self.itemconfigure(self._lbl, text=text)
        if bg is not None:
            self._bg = bg
            if self._rect is not None:
                self.itemconfigure(self._rect, fill=bg)
        if hover is not None:
            self._hover = hover
        if fg is not None:
            self._fg = fg
            if self._lbl is not None:
                self.itemconfigure(self._lbl, fill=fg)


# ═══════════════════════════ MAIN CLASS ═══════════════════════════════════════
class BotGUI:
    def __init__(self, root: tk.Tk):
        self.root = root
        self.root.title("Bot Refinanciamento — Parceiro Santander")
        self.root.configure(bg=MN)
        self.root.geometry("1000x660")
        self.root.minsize(880, 580)

        self._running    = False
        self._paused     = False
        self._dot_on     = True
        self._total      = 0
        self._bot_thread = None

        self._otp_vars:    list[tk.StringVar] = [tk.StringVar() for _ in range(6)]
        self._otp_entries: list[tk.Entry]     = []

        self._build()
        self._tick_dot()
        self._poll()

    # ═══════════════════════════ BUILD ════════════════════════════════════════
    def _build(self):
        sb = tk.Frame(self.root, bg=SB, width=272)
        sb.pack(side="left", fill="y")
        sb.pack_propagate(False)
        self._sb = sb

        # filete sutil separando sidebar / main
        tk.Frame(self.root, bg=BDR, width=1).pack(side="left", fill="y")

        mn = tk.Frame(self.root, bg=MN)
        mn.pack(side="right", fill="both", expand=True)
        self._mn = mn

        self._build_sidebar()
        self._build_main()

    # ─────────────────────────── SIDEBAR ──────────────────────────────────────
    def _build_sidebar(self):
        s = self._sb

        # ── Logo ──────────────────────────────────────────────────────────────
        hdr = tk.Frame(s, bg=SB)
        hdr.pack(fill="x", padx=18, pady=(22, 4))

        badge = tk.Canvas(hdr, width=40, height=40, bg=SB, bd=0,
                          highlightthickness=0)
        badge.pack(side="left", padx=(0, 12))
        _round_rect(badge, 0, 0, 40, 40, 12, fill=R, outline="")
        badge.create_text(20, 20, text="⚡", font=(FONT + " Emoji", 17),
                          fill="white")

        col = tk.Frame(hdr, bg=SB)
        col.pack(side="left", fill="y")
        tk.Label(col, text="Refinanciamento", bg=SB, fg=WHT,
                 font=(FONT, 12, "bold")).pack(anchor="w")
        tk.Label(col, text="Parceiro Santander", bg=SB, fg=GRY,
                 font=(FONT, 9)).pack(anchor="w")

        self._sep(s)

        # ── Status ────────────────────────────────────────────────────────────
        self._slabel(s, "STATUS")

        pill = RCard(s, bg=CD, radius=12, pad=10, height=40, parent_bg=SB)
        pill.pack(fill="x", padx=18, pady=(2, 0))
        pb = pill.body

        self._dot = tk.Label(pb, text="●", bg=CD, fg=GRY2,
                             font=(FONT, 10))
        self._dot.pack(side="left", padx=(2, 6))

        self._status_txt = tk.Label(pb, text="Parado", bg=CD, fg=GRY,
                                     font=(FONT, 10, "bold"))
        self._status_txt.pack(side="left")

        self._sep(s)

        # ── Métricas sidebar ──────────────────────────────────────────────────
        self._slabel(s, "PROGRESSO")

        prog = RCard(s, bg=CD, radius=14, pad=12, height=176, parent_bg=SB)
        prog.pack(fill="x", padx=18, pady=(2, 0))

        self._m: dict[str, tk.Label] = {}
        for lbl, color in [("Total", WHT), ("Processados", WHT),
                           ("Com redução", GRN), ("Sem redução", GRY),
                           ("Erros", ERR)]:
            self._m[lbl] = self._mrow(prog.body, lbl, "0", color)

        self._sep(s)

        # ── Botões ────────────────────────────────────────────────────────────
        self.btn_main = RButton(
            s, text="▶   Iniciar bot", command=self._primary,
            bg=R, hover=R_HI, fg=WHT, parent_bg=SB,
        )
        self.btn_main.pack(fill="x", padx=18, pady=(0, 9))

        self.btn_stop = RButton(
            s, text="■   Parar", command=self._stop,
            bg=CD, hover=CD2, fg=GRY, parent_bg=SB,
        )
        self.btn_stop.pack(fill="x", padx=18)

        self._sep(s)

        # ── OTP ───────────────────────────────────────────────────────────────
        self._build_otp(s)

    def _sep(self, p):
        tk.Frame(p, bg=BDR, height=1).pack(fill="x", padx=18, pady=15)

    def _slabel(self, p, text: str):
        tk.Label(p, text=text, bg=SB, fg=GRY2,
                 font=(FONT, 8, "bold"),
                 anchor="w").pack(fill="x", padx=18, pady=(0, 7))

    def _mrow(self, p, label: str, val: str, color: str) -> tk.Label:
        row = tk.Frame(p, bg=CD)
        row.pack(fill="x", pady=3)
        tk.Label(row, text=label, bg=CD, fg=GRY,
                 font=(FONT, 10),
                 anchor="w").pack(side="left")
        lbl = tk.Label(row, text=val, bg=CD, fg=color,
                       font=(FONT_MONO, 12, "bold"))
        lbl.pack(side="right")
        return lbl

    def _build_otp(self, p):
        self._slabel(p, "CÓDIGO OTP")

        box = RCard(p, bg=CD, radius=14, pad=12, height=118, parent_bg=SB)
        box.pack(fill="x", padx=18)
        b = box.body

        row = tk.Frame(b, bg=CD)
        row.pack()

        vcmd = (self.root.register(lambda s: len(s) <= 1), "%P")
        for i in range(6):
            e = tk.Entry(row,
                         textvariable=self._otp_vars[i],
                         width=2, font=(FONT_MONO, 17),
                         bg=IP, fg=WHT,
                         insertbackground=R,
                         relief="flat", bd=0,
                         justify="center",
                         highlightthickness=2,
                         highlightbackground=BDR,
                         highlightcolor=R,
                         validate="key", validatecommand=vcmd)
            e.pack(side="left", padx=3, pady=(2, 10), ipady=7)
            e.bind("<KeyRelease>", lambda ev, i=i: self._otp_key(ev, i))
            e.bind("<BackSpace>",  lambda ev, i=i: self._otp_back(ev, i))
            self._otp_entries.append(e)

        RButton(b, text="Confirmar OTP", command=self._send_otp,
                bg=R, hover=R_HI, fg=WHT, height=36,
                font=(FONT, 10, "bold"), parent_bg=CD).pack(fill="x")

    # ─────────────────────────── MAIN ─────────────────────────────────────────
    def _build_main(self):
        m = self._mn

        # ── Tab bar ───────────────────────────────────────────────────────────
        tb = tk.Frame(m, bg=MN)
        tb.pack(fill="x", padx=8, pady=(4, 0))
        tk.Frame(m, bg=BDR, height=1).pack(fill="x")

        self._tab_lbls: dict[str, tk.Label] = {}
        self._tab_inds: dict[str, tk.Frame] = {}
        self._cur_tab  = "Painel"

        for name in ("Painel", "Resultados", "Configurações"):
            c = tk.Frame(tb, bg=MN)
            c.pack(side="left")
            lbl = tk.Label(c, text=name, bg=MN,
                           fg=R if name == "Painel" else GRY,
                           font=(FONT, 11, "bold" if name == "Painel" else "normal"),
                           padx=18, pady=12, cursor="hand2")
            lbl.pack()
            lbl.bind("<Button-1>", lambda ev, n=name: self._tab(n))
            lbl.bind("<Enter>", lambda ev, n=name: self._tab_hover(n, True))
            lbl.bind("<Leave>", lambda ev, n=name: self._tab_hover(n, False))
            ind = tk.Frame(c, bg=R if name == "Painel" else MN, height=2)
            ind.pack(fill="x")
            self._tab_lbls[name] = lbl
            self._tab_inds[name] = ind

        # ── Content ───────────────────────────────────────────────────────────
        self._content = tk.Frame(m, bg=MN)
        self._content.pack(fill="both", expand=True)
        self._build_painel()
        self._build_resultados()
        self._build_config()
        self._painel.pack(fill="both", expand=True)

    def _tab_hover(self, name: str, on: bool):
        if name == self._cur_tab:
            return
        self._tab_lbls[name].config(fg=WHT if on else GRY)

    def _tab(self, name: str):
        for n in ("Painel", "Resultados", "Configurações"):
            active = n == name
            self._tab_lbls[n].config(
                fg=R if active else GRY,
                font=(FONT, 11, "bold" if active else "normal"))
            self._tab_inds[n].config(bg=R if active else MN)
        self._painel.pack_forget()
        self._resultados.pack_forget()
        self._config_tab.pack_forget()
        self._cur_tab = name
        {"Painel": self._painel,
         "Resultados": self._resultados,
         "Configurações": self._config_tab}[name].pack(fill="both", expand=True)

    def _build_painel(self):
        f = tk.Frame(self._content, bg=MN)
        self._painel = f

        # ── 4 metric cards ────────────────────────────────────────────────────
        cr = tk.Frame(f, bg=MN)
        cr.pack(fill="x", padx=16, pady=(16, 0))

        self.cc_sim  = self._bigcard(cr, "Com redução",      "0",  GRN, first=True)
        self.cc_nao  = self._bigcard(cr, "Sem redução",      "0",  WHT)
        self.cc_err  = self._bigcard(cr, "Erros / inválidos", "0",  ERR)
        self.cc_taxa = self._bigcard(cr, "Taxa de sucesso",  "—%", ORG, last=True)

        # ── Progress ──────────────────────────────────────────────────────────
        pg = RCard(f, bg=CD, radius=16, pad=16, height=104, parent_bg=MN)
        pg.pack(fill="x", padx=16, pady=16)
        body = pg.body

        pg_top = tk.Frame(body, bg=CD)
        pg_top.pack(fill="x")
        tk.Label(pg_top, text="Processando clientes", bg=CD, fg=GRY,
                 font=(FONT, 10, "bold")).pack(side="left")
        self.lbl_pct = tk.Label(pg_top, text="0 / 0  —  0%",
                                 bg=CD, fg=WHT,
                                 font=(FONT_MONO, 10, "bold"))
        self.lbl_pct.pack(side="right")

        # canvas progress bar (track + fill arredondados)
        self._pb = tk.Canvas(body, height=8, bg=CD, bd=0, highlightthickness=0)
        self._pb.pack(fill="x", pady=(12, 0))
        self._pb.bind("<Configure>", self._pb_track)

        self.lbl_cur = tk.Label(body, text="Atual: aguardando início...",
                                 bg=CD, fg=GRY,
                                 font=(FONT, 9), anchor="w")
        self.lbl_cur.pack(fill="x", pady=(10, 0))

        # ── Log ───────────────────────────────────────────────────────────────
        lo = RCard(f, bg=LG, radius=16, pad=14, parent_bg=MN)
        lo.pack(fill="both", expand=True, padx=16, pady=(0, 16))
        lb = lo.body

        lh = tk.Frame(lb, bg=LG)
        lh.pack(fill="x", pady=(0, 6))
        tk.Label(lh, text="LOG DE EXECUÇÃO", bg=LG, fg=GRY2,
                 font=(FONT, 8, "bold")).pack(side="left")
        clr = tk.Label(lh, text="LIMPAR", bg=LG, fg=GRY2,
                       font=(FONT, 8, "bold"), cursor="hand2")
        clr.pack(side="right")
        clr.bind("<Button-1>", lambda e: self._clear_log())
        clr.bind("<Enter>", lambda e: clr.config(fg=R))
        clr.bind("<Leave>", lambda e: clr.config(fg=GRY2))

        wrap = tk.Frame(lb, bg=LG)
        wrap.pack(fill="both", expand=True)

        self.log = tk.Text(wrap, bg=LG, fg=GRY,
                           font=(FONT_MONO, 10),
                           relief="flat", bd=0, highlightthickness=0,
                           insertbackground=GRY,
                           state="disabled", wrap="none",
                           padx=2, pady=2, spacing1=2)
        vsb = tk.Scrollbar(wrap, command=self.log.yview,
                           width=10, bg=LG, troughcolor=LG,
                           activebackground=BDR, relief="flat", bd=0,
                           highlightthickness=0)
        self.log.configure(yscrollcommand=vsb.set)
        vsb.pack(side="right", fill="y")
        self.log.pack(fill="both", expand=True)

        self.log.tag_configure("ts",   foreground=GRY2)
        self.log.tag_configure("ok",   foreground=GRN)
        self.log.tag_configure("err",  foreground=ERR)
        self.log.tag_configure("info", foreground=GRY)
        self.log.tag_configure("red",  foreground=R)
        self.log.tag_configure("nome", foreground="#d6d6de")
        self.log.tag_configure("mute", foreground="#55555f")

    def _bigcard(self, parent, label: str, val: str, color: str,
                 first=False, last=False) -> tk.Label:
        padx = (0, 6) if first else (6, 0) if last else 6
        card = RCard(parent, bg=CD, radius=16, pad=14,
                     width=10, height=96, parent_bg=MN)
        card.pack(side="left", fill="both", expand=True, padx=padx)
        b = card.body

        # acento colorido no topo
        bar = tk.Frame(b, bg=color, height=3, width=26)
        bar.pack(anchor="w")
        tk.Label(b, text=label.upper(), bg=CD, fg=GRY,
                 font=(FONT, 8, "bold"),
                 anchor="w").pack(anchor="w", pady=(8, 0))
        lbl = tk.Label(b, text=val, bg=CD, fg=color,
                       font=(FONT, 24, "bold"), anchor="w")
        lbl.pack(anchor="w", pady=(2, 0))
        return lbl

    def _build_resultados(self):
        f = tk.Frame(self._content, bg=MN)
        self._resultados = f

        wrap = tk.Frame(f, bg=MN)
        wrap.pack(expand=True)

        tk.Label(wrap, text="📄", bg=MN, fg=GRY,
                 font=(FONT + " Emoji", 32)).pack(pady=(0, 8))
        tk.Label(wrap, text="Resultados exportados",
                 bg=MN, fg=WHT, font=(FONT, 13, "bold")).pack()
        tk.Label(wrap,
                 text="Os arquivos .xlsx são gerados na pasta do bot ao final.",
                 bg=MN, fg=GRY, font=(FONT, 10)).pack(pady=(4, 16))

        RButton(wrap, text="Abrir pasta de resultados",
                command=lambda: _open_path(os.getcwd()),
                bg=CD, hover=CD2, fg=WHT, height=40,
                radius=10, parent_bg=MN).pack(ipadx=40)

    def _build_config(self):
        f = tk.Frame(self._content, bg=MN)
        self._config_tab = f

        wrap = tk.Frame(f, bg=MN)
        wrap.pack(expand=True)
        tk.Label(wrap, text="⚙", bg=MN, fg=GRY,
                 font=(FONT + " Emoji", 32)).pack(pady=(0, 8))
        tk.Label(wrap, text="Configurações",
                 bg=MN, fg=WHT, font=(FONT, 13, "bold")).pack()
        tk.Label(wrap,
                 text="Defina BASE_URL e CLIENTES_CSV no arquivo bot.py",
                 bg=MN, fg=GRY, font=(FONT, 10)).pack(pady=(4, 0))

    # ═══════════════════════════ AÇÕES ════════════════════════════════════════
    def _primary(self):
        if not self._running:
            self._do_start()
        elif self._paused:
            self._do_resume()
        else:
            self._do_pause()

    def _do_start(self):
        if self._bot_thread and self._bot_thread.is_alive():
            return
        bot.python_stop_event.clear()
        bot._start_event.clear()
        bot._otp_queue.queue.clear()
        if hasattr(bot, "_pause_event"):
            bot._pause_event.clear()

        self._bot_thread = threading.Thread(target=bot.main_gui, daemon=True)
        self._bot_thread.start()
        self._running = True
        self._paused  = False
        self._upd_btns()
        self._set_status("Iniciando...", True)
        self._ilog("Bot iniciado.")

    def _do_pause(self):
        if hasattr(bot, "_pause_event"):
            bot._pause_event.set()
        self._paused = True
        self._upd_btns()
        self._set_status("Pausado", False)
        self._ilog("Bot pausado após cliente atual.")

    def _do_resume(self):
        if hasattr(bot, "_pause_event"):
            bot._pause_event.clear()
        self._paused = False
        self._upd_btns()
        self._set_status("Rodando", True)
        self._ilog("Bot retomado.")

    def _stop(self):
        bot.python_stop_event.set()
        if hasattr(bot, "_pause_event"):
            bot._pause_event.clear()
        self._running = False
        self._paused  = False
        self._upd_btns()
        self._set_status("Parando...", False)
        self._ilog("Sinal de parada enviado.")

    def _upd_btns(self):
        if not self._running:
            self.btn_main.set(text="▶   Iniciar bot", bg=R, hover=R_HI)
        elif self._paused:
            self.btn_main.set(text="▶   Retomar", bg="#2e7d32", hover="#388e3c")
        else:
            self.btn_main.set(text="⏸   Pausar bot", bg="#d35400", hover="#e65100")

    def _send_otp(self):
        code = "".join(v.get() for v in self._otp_vars).strip()
        if not code:
            return
        bot._otp_queue.put(code)
        for v in self._otp_vars:
            v.set("")
        self._ilog(f"OTP enviado: {code}")

    def _otp_key(self, ev, i: int):
        if self._otp_vars[i].get() and i < 5:
            self._otp_entries[i + 1].focus()

    def _otp_back(self, ev, i: int):
        if not self._otp_vars[i].get() and i > 0:
            self._otp_entries[i - 1].focus()

    def _clear_log(self):
        self.log.config(state="normal")
        self.log.delete("1.0", "end")
        self.log.config(state="disabled")

    # ═══════════════════════════ STATUS / DOT ═════════════════════════════════
    def _set_status(self, text: str, running: bool):
        self._status_txt.config(text=text, fg=WHT if running else GRY)
        if not running:
            self._dot.config(fg=GRY2)

    def _tick_dot(self):
        if self._running and not self._paused:
            self._dot_on = not self._dot_on
            self._dot.config(fg=R if self._dot_on else R_DK)
        self.root.after(600, self._tick_dot)

    # ═══════════════════════════ LOG ══════════════════════════════════════════
    def _write(self, *parts):
        """parts: (text, tag) pairs"""
        self.log.config(state="normal")
        for text, tag in parts:
            self.log.insert("end", text, tag)
        self.log.insert("end", "\n")
        self.log.see("end")
        self.log.config(state="disabled")

    def _ilog(self, msg: str):
        self._write((f"{_now()}  · ", "mute"), (msg, "mute"))

    def _log_client(self, icon: str, icon_tag: str,
                    nome: str, extra: str, extra_tag: str):
        self._write(
            (f"{_now()}  ", "ts"),
            (f"{icon}  ",   icon_tag),
            (nome,           "nome"),
            (f"  {extra}",   extra_tag),
        )

    # ═══════════════════════════ QUEUE ════════════════════════════════════════
    def _poll(self):
        try:
            while True:
                self._handle(bot._status_queue.get_nowait())
        except queue.Empty:
            pass
        self.root.after(100, self._poll)

    def _handle(self, msg: dict):
        t = msg.get("type", "")

        # ── init_stats ─────────────────────────────────────────────────────
        if t == "init_stats":
            self._total = msg.get("total", 0)
            feitos = msg.get("feitos", 0)
            sim    = msg.get("sim",    0)
            nao    = msg.get("nao",    0)
            erros  = msg.get("erros",  0)
            self._m["Total"]      .config(text=str(self._total))
            self._m["Processados"].config(text=str(feitos))
            self._m["Com redução"].config(text=str(sim))
            self._m["Sem redução"].config(text=str(nao))
            self._m["Erros"]      .config(text=str(erros))
            self.cc_sim .config(text=str(sim))
            self.cc_nao .config(text=str(nao))
            self.cc_err .config(text=str(erros))
            self._taxa(sim, nao)
            self._pb_set(feitos, self._total)

        # ── login ──────────────────────────────────────────────────────────
        elif t == "aguardando_login":
            self._set_status("Aguardando login", True)
            self._log_client("⚠", "err", "Login manual necessário.", "", "info")

        elif t == "otp_needed":
            self._set_status("Aguardando OTP", True)
            self._log_client("!", "err", "OTP solicitado — insira ao lado.", "", "info")
            if self._otp_entries:
                self._otp_entries[0].focus()

        elif t == "login_ok":
            bot._start_event.set()
            self._set_status("Rodando", True)
            self._log_client("✓", "ok", "Login realizado.", "", "info")

        elif t == "sessao_expirada":
            self._set_status("Sessão expirada", True)
            self._log_client("!", "err", "Sessão expirada — relogando...", "", "info")

        elif t == "rodando":
            self._set_status("Rodando", True)

        # ── progress ───────────────────────────────────────────────────────
        elif t == "progress":
            idx     = msg.get("idx",    0)
            total   = msg.get("total",  1)
            nome    = msg.get("nome",   "")
            cpf     = msg.get("cpf",    "")
            status  = msg.get("status", "")
            reducao = msg.get("reducao", 0.0)
            sim     = msg.get("sim",    0)
            nao     = msg.get("nao",    0)
            erros   = msg.get("erros",  0)

            feitos = sim + nao + erros   # total REAL concluído (não a posição no loop)
            self._m["Processados"].config(text=str(feitos))
            self._m["Com redução"].config(text=str(sim))
            self._m["Sem redução"].config(text=str(nao))
            self._m["Erros"]      .config(text=str(erros))
            self.cc_sim.config(text=str(sim))
            self.cc_nao.config(text=str(nao))
            self.cc_err.config(text=str(erros))
            self._taxa(sim, nao)
            self._pb_set(feitos, total)
            self.lbl_pct.config(
                text=f"{feitos} / {total}  —  {int(feitos / max(total, 1) * 100)}%"
            )

            if status == "Processando...":
                self.lbl_cur.config(
                    text=f"Atual:  {nome}  —  CPF {cpf}  —  consultando refinanciamento..."
                )
                self._log_client("→", "info", nome.upper(), "processando...", "info")

            elif status == "Sim":
                red_txt = f"Sim — {_br(reducao)} redução" if reducao else "Sim"
                self.lbl_cur.config(text=f"Último:  {nome}  —  ✓ {red_txt}")
                self._log_client("✓", "ok", nome.upper(), red_txt, "red")

            elif status == "Não":
                self.lbl_cur.config(text=f"Último:  {nome}  —  Não")
                self._log_client("–", "info", nome.upper(), "Não", "info")

            else:
                self.lbl_cur.config(text=f"Último:  {nome}  —  {status}")
                self._log_client("✗", "err", nome.upper(), status, "err")

        # ── log genérico ───────────────────────────────────────────────────
        elif t == "log":
            self._ilog(msg.get("msg", ""))

        # ── stopped ────────────────────────────────────────────────────────
        elif t == "stopped":
            self._running = False
            self._paused  = False
            self._upd_btns()
            self._set_status("Parado", False)
            self._log_client("■", "info", "Bot finalizado.", "", "info")
            self._summary()

    # ═══════════════════════════ HELPERS ══════════════════════════════════════
    def _taxa(self, sim: int, nao: int):
        den = sim + nao
        self.cc_taxa.config(text=f"{int(sim/den*100)}%" if den else "—%")

    def _pb_track(self, _ev=None):
        """Desenha o trilho de fundo arredondado (atrás do fill)."""
        w, h = self._pb.winfo_width(), self._pb.winfo_height()
        self._pb.delete("track")
        if w > 4:
            _round_rect(self._pb, 0, 0, w, h, h / 2,
                        fill=BDR, outline="", tags="track")
            self._pb.tag_lower("track")

    def _pb_set(self, done: int, total: int):
        self._pb.update_idletasks()
        w, h = self._pb.winfo_width(), self._pb.winfo_height()
        self._pb.delete("fill")
        if w > 10 and total > 0 and done > 0:
            fw = max(h, int(w * min(done / total, 1.0)))
            _round_rect(self._pb, 0, 0, fw, h, h / 2,
                        fill=R, outline="", tags="fill")

    def _summary(self):
        sim   = self.cc_sim .cget("text")
        nao   = self.cc_nao .cget("text")
        erros = self.cc_err .cget("text")
        files = "\n".join(
            f"  • {os.path.abspath(f)}"
            for f in [bot.RESULTADO_XLSX, bot.COM_REFIN_XLSX]
            if os.path.exists(f)
        )
        messagebox.showinfo(
            "Concluído — Bot Refinanciamento",
            f"Processamento finalizado!\n\n"
            f"  Com redução:   {sim}\n"
            f"  Sem redução:   {nao}\n"
            f"  Erros:         {erros}\n\n"
            + (f"Arquivos gerados:\n{files}" if files else ""),
        )


# ═══════════════════════════ ENTRY ════════════════════════════════════════════
def main():
    root = tk.Tk()
    BotGUI(root)
    root.mainloop()


if __name__ == "__main__":
    main()
