"""Small Windows GUI for connecting the ManiQuantAI MT5 bridge.

No broker credentials are collected. The user pastes a ManiQuantAI bridge token
created in Settings. The token stays in memory for this process only.
"""
from __future__ import annotations

import os
import threading
import tkinter as tk
from tkinter import messagebox

import requests

from agent import run_bridge

DEFAULT_API = os.getenv("MANIQUANT_API_URL", "")


class BridgeApp:
    def __init__(self, root: tk.Tk):
        self.root = root
        root.title("ManiQuantAI MT5 Bridge")
        root.geometry("520x430")
        root.resizable(False, False)
        self.running = False
        self.worker = None

        frame = tk.Frame(root, padx=28, pady=24)
        frame.pack(fill="both", expand=True)
        tk.Label(frame, text="ManiQuantAI", font=("Segoe UI", 20, "bold")).pack(anchor="w")
        tk.Label(frame, text="MetaTrader 5 Bridge", font=("Segoe UI", 11)).pack(anchor="w", pady=(0, 18))

        tk.Label(frame, text="ManiQuantAI API", font=("Segoe UI", 9, "bold")).pack(anchor="w")
        self.api = tk.Entry(frame, font=("Segoe UI", 10))
        if DEFAULT_API: self.api.insert(0, DEFAULT_API)
        self.api.pack(fill="x", pady=(4, 12), ipady=6)

        tk.Label(frame, text="Bridge token", font=("Segoe UI", 9, "bold")).pack(anchor="w")
        self.token = tk.Entry(frame, show="•", font=("Consolas", 10))
        self.token.pack(fill="x", pady=(4, 6), ipady=7)
        tk.Label(frame, text="Create this token in ManiQuantAI → Settings → Connect MT5. It is never your broker password.", fg="#666", wraplength=455, justify="left").pack(anchor="w")

        self.status = tk.Label(frame, text="● Not connected", fg="#b42318", font=("Segoe UI", 10, "bold"))
        self.status.pack(anchor="w", pady=(22, 4))
        self.account_label = tk.Label(frame, text="", fg="#666", justify="left")
        self.account_label.pack(anchor="w")

        buttons = tk.Frame(frame); buttons.pack(fill="x", pady=(22, 0))
        self.connect_btn = tk.Button(buttons, text="Connect to MT5", command=self.connect, bg="#111", fg="white", relief="flat", padx=16, pady=8)
        self.connect_btn.pack(side="left")
        tk.Button(buttons, text="Clear token", command=lambda: self.token.delete(0, tk.END), padx=12, pady=8).pack(side="left", padx=8)
        tk.Button(buttons, text="Exit", command=root.destroy, padx=12, pady=8).pack(side="right")
        tk.Label(frame, text="Keep MetaTrader 5, AutoTrading, and this bridge running while automatic trading is enabled.", fg="#666", wraplength=455, justify="left").pack(anchor="w", pady=(24, 0))

    def set_status(self, text: str, color: str, account=None):
        self.root.after(0, lambda: self._set_status(text, color, account))

    def _set_status(self, text, color, account):
        self.status.config(text=f"● {text}", fg=color)
        if account:
            self.account_label.config(text=f"MT5 account: {account.get('login')}\nBroker server: {account.get('server')}\nEquity: {account.get('equity')}")

    def connect(self):
        if self.running: return
        api = self.api.get().strip().rstrip("/"); token = self.token.get().strip()
        if not api or not token:
            messagebox.showerror("Missing information", "Enter the ManiQuantAI API URL and bridge token."); return
        self.connect_btn.config(state="disabled", text="Connecting…")
        try:
            response = requests.get(f"{api}/api/mt5-bridge/jobs", params={"token": token}, timeout=10); response.raise_for_status()
        except Exception as exc:
            self.connect_btn.config(state="normal", text="Connect to MT5"); self.set_status("Authentication failed", "#b42318")
            messagebox.showerror("Could not connect", f"The bridge token was rejected or the API is unreachable.\n\n{exc}"); return
        self.running = True; self.connect_btn.config(text="Bridge running"); self.set_status("Authenticated — starting MT5…", "#b54708")
        self.worker = threading.Thread(target=self._run, args=(api, token), daemon=True); self.worker.start()

    def _run(self, api, token):
        try:
            run_bridge(api, token, 2.0, lambda text, account: self.set_status(text, "#067647" if text in {"Online", "Connected to MT5"} else "#b54708", account))
        except Exception as exc:
            self.running = False; self.root.after(0, lambda: self.connect_btn.config(state="normal", text="Connect to MT5")); self.set_status("Stopped", "#b42318")
            self.root.after(0, lambda: messagebox.showerror("MT5 bridge stopped", str(exc)))


def main():
    root = tk.Tk(); BridgeApp(root); root.mainloop()

if __name__ == "__main__": main()
