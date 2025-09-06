import os
import sys
import threading
import queue
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Optional, Tuple

import tkinter as tk
from tkinter import ttk, filedialog, messagebox

from yt_dlp import YoutubeDL


# =========================
# Utils & Types
# =========================

Event = Tuple[str, str]          # ("progress"|"status"|"log"|"done"|"error", payload)
EventQueue = "queue.Queue[Event]"


def human_size(n: int) -> str:
    """Превращает байты в читабельный размер."""
    step = 1024.0
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if n < step:
            return f"{n:.0f} {unit}"
        n /= step
    return f"{n:.0f} PB"


def sanitize_filename(name: str) -> str:
    """Удаляет недопустимые символы в имени файла и подчищает пробелы."""
    cleaned = re.sub(r'[\\/*?:"<>|]+', "_", name).strip()
    return cleaned or "video"


def force_mp4_name(base: str) -> str:
    """
    Возвращает корректное имя с расширением .mp4.
    Если пользователь ввёл имя с другим расширением — заменим на .mp4.
    """
    base = sanitize_filename(base)
    stem, _ext = os.path.splitext(base)
    return f"{stem}.mp4"


# =========================
# Downloader
# =========================

@dataclass(frozen=True)
class DownloadRequest:
    """Параметры запроса на загрузку."""
    url: str
    outdir: Path
    output_name: Optional[str]  # уже в финальном виде (если задано) — с .mp4


class Downloader:
    """
    Обёртка над yt-dlp с прогресс-хуком.
    Отправляет события в GUI через переданную функцию put(event).
    """

    def __init__(self, put: Callable[[Event], None]) -> None:
        self.put = put

    def _hook(self, d: dict) -> None:
        """Хук прогресса yt-dlp."""
        status = d.get("status")
        if status == "downloading":
            percent_str = (d.get("_percent_str") or "0%").strip()
            try:
                percent = int(float(percent_str.strip("%")))
                self.put(("progress", str(max(0, min(100, percent)))))
            except Exception:
                pass
            downloaded = int(d.get("downloaded_bytes") or 0)
            total = int(d.get("total_bytes") or d.get("total_bytes_estimate") or 0)
            msg = human_size(downloaded)
            if total:
                msg += f" / {human_size(total)}"
            self.put(("log", msg))
        elif status == "finished":
            self.put(("progress", "100"))
            self.put(("log", "Постобработка (mp4)…"))

    def download(self, req: DownloadRequest) -> Path:
        """
        Запускает загрузку. Возвращает путь к итоговому файлу.
        Может поднимать исключения — GUI их перехватывает и показывает пользователю.
        """
        req.outdir.mkdir(parents=True, exist_ok=True)

        # Шаблон имени: если имя задано — используем фикс, иначе используем шаблон yt-dlp
        outtmpl = str(req.outdir / (req.output_name or "%(title)s.%(ext)s"))

        ydl_opts = {
            "outtmpl": outtmpl,
            "quiet": True,
            "noprogress": True,
            "merge_output_format": "mp4",
            # NB: ключ "preferedformat" — именно так его ждёт yt-dlp для FFmpegVideoRemuxer
            "postprocessors": [{"key": "FFmpegVideoRemuxer", "preferedformat": "mp4"}],
            "progress_hooks": [self._hook],
        }

        self.put(("status", "Подготовка…"))

        with YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(req.url, download=True)
            if info is None:
                raise RuntimeError("yt-dlp не вернул метаданные.")

            # Попытка определить итоговый путь
            path: Optional[str] = None
            if isinstance(info, dict) and info.get("requested_downloads"):
                path = info["requested_downloads"][0].get("filepath")
            if not path and isinstance(info, dict):
                path = info.get("_filename")
            if not path:
                path = ydl.prepare_filename(info)

        # Если был ремультиплекс в mp4 — целимся в mp4; иначе оставляем исходное
        base, _ext = os.path.splitext(path)
        mp4 = Path(base + ".mp4")
        return mp4 if mp4.exists() else Path(path)


# =========================
# Worker thread
# =========================

def worker(req: DownloadRequest, q: EventQueue) -> None:
    """Фоновая задача загрузки; все сообщения — в очередь для GUI."""
    def put(ev: Event) -> None:
        q.put(ev)

    try:
        dl = Downloader(put)
        result = dl.download(req)
        put(("done", str(result)))
    except Exception as e:
        put(("error", str(e)))


# =========================
# GUI
# =========================

class App(tk.Tk):
    """GUI с очередью событий."""

    POLL_MS = 100

    def __init__(self) -> None:
        super().__init__()
        self.title("Fetch Media — на yt-dlp")
        self.geometry("760x460")

        # === URL ===
        frm1 = ttk.Frame(self); frm1.pack(fill="x", padx=12, pady=(12, 6))
        ttk.Label(frm1, text="Ссылка (YouTube / RuTube / Яндекс.Диск / др.):").pack(anchor="w")
        self.ent_url = ttk.Entry(frm1)
        self.ent_url.pack(fill="x")

        # === Папка ===
        frm2 = ttk.Frame(self); frm2.pack(fill="x", padx=12, pady=6)
        ttk.Label(frm2, text="Папка сохранения:").grid(row=0, column=0, sticky="w")
        self.ent_out = ttk.Entry(frm2)
        self.ent_out.insert(0, "downloads")
        self.ent_out.grid(row=0, column=1, sticky="ew", padx=6)
        ttk.Button(frm2, text="Обзор…", command=self._choose_dir).grid(row=0, column=2)
        frm2.columnconfigure(1, weight=1)

        # === Имя файла ===
        frm3 = ttk.Frame(self); frm3.pack(fill="x", padx=12, pady=6)
        ttk.Label(frm3, text="Имя файла (без расширения, опционально):").grid(row=0, column=0, sticky="w")
        self.ent_name = ttk.Entry(frm3)
        self.ent_name.grid(row=0, column=1, sticky="ew", padx=6)
        frm3.columnconfigure(1, weight=1)

        # === Прогресс ===
        frm4 = ttk.Frame(self); frm4.pack(fill="x", padx=12, pady=6)
        self.pb = ttk.Progressbar(frm4, maximum=100)
        self.pb.pack(fill="x")

        # === Лог ===
        frm5 = ttk.Frame(self); frm5.pack(fill="both", expand=True, padx=12, pady=6)
        self.txt = tk.Text(frm5, height=10)
        self.txt.pack(fill="both", expand=True)
        self.txt.configure(state="disabled")

        # === Кнопки ===
        frm6 = ttk.Frame(self); frm6.pack(fill="x", padx=12, pady=(0, 12))
        ttk.Button(frm6, text="Скачать", command=self._start_download).pack(side="left")
        ttk.Button(frm6, text="Открыть папку", command=self._open_outdir).pack(side="left")
        ttk.Button(frm6, text="Выход", command=self.destroy).pack(side="right")

        self._events: EventQueue = queue.Queue()
        self._downloading = False
        self.after(self.POLL_MS, self._poll_queue)

    # ----- UI helpers -----

    def _choose_dir(self) -> None:
        d = filedialog.askdirectory()
        if d:
            self.ent_out.delete(0, tk.END)
            self.ent_out.insert(0, d)

    def _log(self, msg: str) -> None:
        self.txt.configure(state="normal")
        self.txt.insert(tk.END, msg + "\n")
        self.txt.see(tk.END)
        self.txt.configure(state="disabled")

    def _set_status(self, s: str) -> None:
        self.title(f"Fetch Media — {s}")
        self._log(s)

    # ----- Actions -----

    def _start_download(self) -> None:
        if self._downloading:
            messagebox.showinfo("Идёт загрузка", "Подождите, текущая загрузка ещё не закончилась.")
            return

        url = self.ent_url.get().strip()
        if not url:
            messagebox.showerror("Ошибка", "Укажите ссылку.")
            return

        outdir_text = (self.ent_out.get().strip() or "downloads")
        outdir = Path(outdir_text)

        raw_name = self.ent_name.get().strip()
        output_name = force_mp4_name(raw_name) if raw_name else None

        # подготовка UI
        outdir.mkdir(parents=True, exist_ok=True)
        self.pb["value"] = 0
        self.txt.configure(state="normal"); self.txt.delete("1.0", tk.END); self.txt.configure(state="disabled")
        self._downloading = True

        req = DownloadRequest(url=url, outdir=outdir, output_name=output_name)
        threading.Thread(target=worker, args=(req, self._events), daemon=True).start()

    def _open_outdir(self) -> None:
        outdir = self.ent_out.get().strip() or "."
        Path(outdir).mkdir(parents=True, exist_ok=True)
        if sys.platform.startswith("win"):
            os.startfile(outdir)  # type: ignore[attr-defined]
        elif sys.platform == "darwin":
            os.system(f'open "{outdir}"')
        else:
            os.system(f'xdg-open "{outdir}"')

    # ----- Event loop -----

    def _poll_queue(self) -> None:
        try:
            while True:
                kind, payload = self._events.get_nowait()
                if kind == "status":
                    self._set_status(payload)
                elif kind == "progress":
                    try:
                        self.pb["value"] = max(0, min(100, int(payload)))
                    except Exception:
                        pass
                elif kind == "log":
                    self._log(payload)
                elif kind == "done":
                    self.pb["value"] = 100
                    self._log(f"✅ Готово: {payload}")
                    messagebox.showinfo("Готово", f"Файл сохранён:\n{payload}")
                    self._downloading = False
                    self.title("Fetch Media — на yt-dlp")
                elif kind == "error":
                    self._log(f"❌ Ошибка: {payload}")
                    messagebox.showerror("Ошибка", payload)
                    self._downloading = False
                    self.title("Fetch Media — на yt-dlp")
        except queue.Empty:
            pass
        finally:
            self.after(self.POLL_MS, self._poll_queue)


# =========================
# Точка входа
# =========================

def main() -> None:
    """Точка входа приложения."""
    # На macOS желательно иметь Tcl/Tk >= 8.6
    try:
        import tkinter as _t  # noqa
        if float(_t.TkVersion) < 8.6:  # type: ignore[attr-defined]
            print(f"Внимание: требуется Tcl/Tk 8.6+. У вас: {_t.TkVersion}", file=sys.stderr)  # type: ignore[attr-defined]
    except Exception:
        pass

    App().mainloop()


if __name__ == "__main__":
    main()
