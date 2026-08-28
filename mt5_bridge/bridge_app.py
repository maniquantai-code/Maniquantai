"""ManiQuantAI MT5 Bridge v2 — Tkinter GUI for Windows."""
from __future__ import annotations

import sys
import threading
import tkinter as tk
from tkinter import ttk, messagebox, scrolledtext
from datetime import datetime

# Support running as packaged exe (PyInstaller) or raw script
try:
    from agent_v2 import run_bridge, _account
except ImportError:
    from mt5_bridge.agent_v2 import run_bridge, _account

DARK_BG    = "#0D0D0F"
PANEL_BG   = "#13131A"
ACCENT     = "#7C6FFF"
GREEN      = "#22c55e"
RED        = "#ef4444"
TEXT       = "#E2E8F0"
TEXT_MUTED = "#64748B"
BORDER     = "#1E1E2E"


class BridgeApp(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("ManiQuantAI — MT5 Bridge")
        self.configure(bg=DARK_BG)
        self.geometry("640x720")
        self.resizable(True, True)
        self._bridge_thread: threading.Thread | None = None
        self._running = False
        self._build_ui()

    # ── UI ──────────────────────────────────────────────────────────────

    def _build_ui(self):
        # Header
        hdr = tk.Frame(self, bg=DARK_BG)
        hdr.pack(fill="x", padx=20, pady=(18, 4))
        tk.Label(hdr, text="ManiQuantAI", bg=DARK_BG, fg=ACCENT, font=("Segoe UI", 16, "bold")).pack(side="left")
        tk.Label(hdr, text=" MT5 Bridge v2", bg=DARK_BG, fg=TEXT_MUTED, font=("Segoe UI", 13)).pack(side="left")

        self._status_dot = tk.Label(hdr, text="●", bg=DARK_BG, fg=RED, font=("Segoe UI", 14))
        self._status_dot.pack(side="right", padx=(0, 4))
        self._status_lbl = tk.Label(hdr, text="Disconnected", bg=DARK_BG, fg=TEXT_MUTED, font=("Segoe UI", 10))
        self._status_lbl.pack(side="right")

        tk.Frame(self, bg=BORDER, height=1).pack(fill="x", padx=20, pady=6)

        # Config panel
        cfg = tk.Frame(self, bg=PANEL_BG, padx=16, pady=14)
        cfg.pack(fill="x", padx=20, pady=4)

        def row(label, row_idx, default="", show=""):
            tk.Label(cfg, text=label, bg=PANEL_BG, fg=TEXT_MUTED, font=("Segoe UI", 9),
                     anchor="w").grid(row=row_idx, column=0, sticky="w", pady=4, padx=(0, 12))
            e = tk.Entry(cfg, font=("Segoe UI", 10), bg="#1A1A2E", fg=TEXT, insertbackground=TEXT,
                         relief="flat", bd=4, show=show)
            e.insert(0, default)
            e.grid(row=row_idx, column=1, sticky="ew", pady=4)
            return e

        cfg.columnconfigure(1, weight=1)
        self._api_entry   = row("API URL",        0, "https://maniquantai.vercel.app")
        self._token_entry = row("Bridge Token",    1, "", show="•")
        self._poll_entry  = row("Poll (seconds)",  2, "2")
        self._scan_entry  = row("Agent scan (sec)", 3, "30")
        self._magic_entry = row("MT5 Magic",       4, "260821")

        # Account panel
        self._acct_frame = tk.Frame(self, bg=PANEL_BG, padx=16, pady=10)
        self._acct_frame.pack(fill="x", padx=20, pady=4)
        self._acct_lbl = tk.Label(self._acct_frame, text="Account: not connected",
                                   bg=PANEL_BG, fg=TEXT_MUTED, font=("Segoe UI", 9))
        self._acct_lbl.pack(anchor="w")

        # Buttons
        btn_row = tk.Frame(self, bg=DARK_BG)
        btn_row.pack(fill="x", padx=20, pady=8)
        self._start_btn = tk.Button(btn_row, text="▶  Connect", bg=ACCENT, fg="#fff", relief="flat",
                                    font=("Segoe UI", 10, "bold"), padx=18, pady=7,
                                    cursor="hand2", command=self._start)
        self._start_btn.pack(side="left", padx=(0, 8))
        self._stop_btn = tk.Button(btn_row, text="■  Disconnect", bg="#1E1E2E", fg=TEXT, relief="flat",
                                   font=("Segoe UI", 10), padx=14, pady=7, state="disabled",
                                   cursor="hand2", command=self._stop)
        self._stop_btn.pack(side="left")

        # Log
        log_hdr = tk.Frame(self, bg=DARK_BG)
        log_hdr.pack(fill="x", padx=20, pady=(10, 2))
        tk.Label(log_hdr, text="Live log", bg=DARK_BG, fg=TEXT_MUTED, font=("Segoe UI", 9)).pack(side="left")
        tk.Button(log_hdr, text="Clear", bg=DARK_BG, fg=TEXT_MUTED, relief="flat",
                  font=("Segoe UI", 8), command=self._clear_log, cursor="hand2").pack(side="right")

        self._log = scrolledtext.ScrolledText(self, bg=PANEL_BG, fg=TEXT, font=("Consolas", 9),
                                               relief="flat", state="disabled", height=14,
                                               insertbackground=TEXT)
        self._log.pack(fill="both", expand=True, padx=20, pady=(0, 16))

        self.protocol("WM_DELETE_WINDOW", self._on_close)

    # ── Log ─────────────────────────────────────────────────────────────

    def _append(self, msg: str):
        ts = datetime.now().strftime("%H:%M:%S")
        self._log.configure(state="normal")
        self._log.insert("end", f"[{ts}] {msg}\n")
        self._log.see("end")
        self._log.configure(state="disabled")

    def _clear_log(self):
        self._log.configure(state="normal")
        self._log.delete("1.0", "end")
        self._log.configure(state="disabled")

    # ── Status ──────────────────────────────────────────────────────────

    def _set_status(self, label: str, color: str, acct: dict | None = None):
        self._status_dot.configure(fg=color)
        self._status_lbl.configure(fg=color, text=label)
        if acct:
            bal = acct.get("balance")
            eq  = acct.get("equity")
            srv = acct.get("server", "")
            cur = acct.get("currency", "")
            txt = (f"Login: {acct.get('login')}  |  {srv}  |  "
                   f"Balance: {bal:,.2f} {cur}  |  Equity: {eq:,.2f} {cur}" if bal is not None
                   else "Connected — account info loading…")
            self._acct_lbl.configure(text=txt, fg=GREEN)

    def _on_status(self, status: str, acct: dict | None):
        color = GREEN if "online" in status.lower() or "connected" in status.lower() else RED
        self.after(0, self._set_status, status, color, acct)
        self.after(0, self._append, f"{'✓' if color==GREEN else '✗'} {status}"
                   + (f"  equity={acct.get('equity'):,.2f}" if acct and acct.get("equity") else ""))

    # ── Bridge control ───────────────────────────────────────────────────

    def _start(self):
        api   = self._api_entry.get().strip().rstrip("/")
        token = self._token_entry.get().strip()
        if not api or not token:
            messagebox.showerror("Missing config", "API URL and Bridge Token are required.")
            return
        try:
            poll = float(self._poll_entry.get().strip() or "2")
            scan = float(self._scan_entry.get().strip() or "30")
            magic = int(self._magic_entry.get().strip() or "260821")
        except ValueError:
            messagebox.showerror("Invalid config", "Poll, Scan, and Magic must be numbers.")
            return

        self._running = True
        self._start_btn.configure(state="disabled")
        self._stop_btn.configure(state="normal")
        self._append(f"Connecting to {api} …")
        self._append(f"Agent scan every {scan}s  |  Magic {magic}")

        def _run():
            try:
                run_bridge(api, token, poll=poll, agent_scan_interval=scan,
                           magic=magic, on_status=self._on_status)
            except Exception as exc:
                self.after(0, self._append, f"✗ Bridge error: {exc}")
                self.after(0, self._set_status, f"Error: {exc}", RED, None)
            finally:
                self._running = False
                self.after(0, self._start_btn.configure, {"state": "normal"})
                self.after(0, self._stop_btn.configure, {"state": "disabled"})

        self._bridge_thread = threading.Thread(target=_run, daemon=True)
        self._bridge_thread.start()

    def _stop(self):
        self._running = False
        self._set_status("Disconnecting…", TEXT_MUTED, None)
        self._append("Disconnecting…")
        # The thread will stop on next poll
        self._start_btn.configure(state="normal")
        self._stop_btn.configure(state="disabled")

    def _on_close(self):
        if self._running:
            if messagebox.askyesno("Quit", "The MT5 bridge is running. Disconnect and quit?"):
                self._stop()
                self.after(800, self.destroy)
        else:
            self.destroy()


def main():
    app = BridgeApp()
    app.mainloop()


if __name__ == "__main__":
    main()
