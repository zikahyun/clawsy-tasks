import json
import math
from pathlib import Path
import random
import re
import sys
import tkinter as tk
from tkinter import messagebox


try:
    from PIL import Image, ImageTk
except ImportError:
    Image = None
    ImageTk = None


BASE_DIR = Path(__file__).resolve().parent
ASSETS_DIR = BASE_DIR / "assets"
PREFS_FILE = BASE_DIR / "widget_prefs.json"

# ---------- Tunable settings ----------
BALL_SIZE = 60            # drawn size of a ball image (px, at 100% scale)
BALL_COUNT = 20           # balls sitting in the machine
BACK_LANE_RAISE = 9       # back-row balls sit a little higher (looks like depth)

# The machine is designed on a 520 x 620 canvas; it is scaled to fit the window.
LOGICAL_W, LOGICAL_H = 520, 620

# Glass interior in logical coordinates.  FLOOR_Y is the floor the balls rest on.
FLOOR_Y = 432
PILE_LEFT = 76            # leftmost ball center (partly hidden by the frame)
PILE_RIGHT = 306          # rightmost ball center (stops before the prize chute)
SPAWN_Y = 150             # where a replacement ball drops in from

# Claw geometry.
CARRY_OFFSET = 36
CLAW_SPEED = 3.5          # logical px per frame while a move key is held
CLAW_MIN_X = 100
CLAW_MAX_X = 370

# Crop boxes (left, top, right, bottom) inside joystick.png.
HANDLE_BOX = (300, 0, 1010, 900)      # stick + knob
BASE_BOX = (180, 720, 1130, 1199)     # round base
HANDLE_PIVOT_INSET = 6                # px above the handle's bottom edge where it pivots
JOYSTICK_MAX_TILT = 22                # degrees the stick leans

# Widget window
PANEL_W = 230                         # side panel width
MIN_W_FULL, MIN_H_FULL = 480, 500
MIN_W_COMPACT, MIN_H_COMPACT = 250, 360
DEFAULT_GEOMETRY = "740x680"

PINK = "#ffdce8"
BAR_BG = "#f29bbb"
EDGE = "#e9689a"


def fit_image(img, target_w, target_h, resample):
    """Resize keeping aspect ratio so the image fits inside target_w x target_h."""
    factor = min(target_w / img.width, target_h / img.height)
    size = (max(1, round(img.width * factor)), max(1, round(img.height * factor)))
    return img.resize(size, resample)


class ScaledCanvas:
    """A canvas that draws in 520x620 logical units and scales to its real size."""

    def __init__(self, parent, **kw):
        self.raw = tk.Canvas(parent, **kw)
        self.s = 1.0
        self.ox = 0.0
        self.oy = 0.0

    def set_view(self, width, height):
        raw = min(width / LOGICAL_W, height / LOGICAL_H)
        self.s = max(0.3, min(3.0, round(raw / 0.02) * 0.02))
        self.ox = (width - LOGICAL_W * self.s) / 2
        self.oy = (height - LOGICAL_H * self.s) / 2

    def to_logical(self, x, y):
        return (x - self.ox) / self.s, (y - self.oy) / self.s

    def _map(self, coords):
        return [v * self.s + (self.ox if i % 2 == 0 else self.oy)
                for i, v in enumerate(coords)]

    def _kw(self, kw):
        if "width" in kw:
            kw["width"] = max(1, kw["width"] * self.s)
        if "font" in kw:
            family, size, *rest = kw["font"]
            kw["font"] = (family, max(6, round(size * self.s)), *rest)
        return kw

    def create_line(self, *c, **kw):
        return self.raw.create_line(*self._map(c), **self._kw(kw))

    def create_oval(self, *c, **kw):
        return self.raw.create_oval(*self._map(c), **self._kw(kw))

    def create_rectangle(self, *c, **kw):
        return self.raw.create_rectangle(*self._map(c), **self._kw(kw))

    def create_arc(self, *c, **kw):
        return self.raw.create_arc(*self._map(c), **self._kw(kw))

    def create_text(self, *c, **kw):
        return self.raw.create_text(*self._map(c), **self._kw(kw))

    def create_image(self, *c, **kw):
        return self.raw.create_image(*self._map(c), **kw)

    def coords(self, item, *args):
        if args:
            if len(args) == 1 and isinstance(args[0], (list, tuple)):
                args = tuple(args[0])
            self.raw.coords(item, *self._map(args))
            return None
        values = self.raw.coords(item)
        return [(v - (self.ox if i % 2 == 0 else self.oy)) / self.s
                for i, v in enumerate(values)]

    def __getattr__(self, name):          # delete, tag_lower, itemconfigure, ...
        return getattr(self.raw, name)


class ClawMachineApp:
    def __init__(self, root):
        self.root = root
        self.root.title("Claw Machine To-Do List")
        self.root.configure(bg=EDGE)

        prefs = self._load_prefs()
        self.pinned = bool(prefs.get("pinned", False))
        self.borderless = bool(prefs.get("borderless", sys.platform != "darwin"))
        self.compact = bool(prefs.get("compact", False))
        self._drag_off = (0, 0)
        self._resize_start = (0, 0, 0, 0)
        self._resize_job = None

        self.tasks = []
        self.completed_tasks = []
        self.active_task = None
        self.animating = False
        self.target_task = None
        self.target_ball = None
        self.target_ball_index = None
        self.carry_ball_item = None
        self.carry_pos = (0, 0)
        self.ball_in_chute = False
        self.chute_center = (390, 400)
        self.chute_x = 390
        self.chute_y = 360
        self.ball_slots = [None] * BALL_COUNT
        self.ball_pos = []           # (x, y) per ball
        self.ball_lane = []          # 0 = back row, 1 = front row
        self.ball_alive = [True] * BALL_COUNT
        self.ball_radius = BALL_SIZE * 0.45
        self.dead_ball_index = None  # ball currently taken out of the machine
        self.chute_ball_index = 0
        self.settling = False
        self.task_popup = None
        self.popup_ball_image = None
        self.keys_down = set()
        self.key_release_jobs = {}
        self.move_loop_running = False
        self.claw_x = 250
        self.claw_y = 175
        self.joystick_center = (318, 488)
        self.joystick_pivot = (318, 497)   # where the stick enters the base
        self.red_button_center = (385, 475)
        self.ball_items = {}
        self.ball_images = []
        self.image_refs = []
        self.machine_image = None
        self.claw_image = None
        self.joystick_base_image = None
        self.joystick_handle_source = None   # padded so the pivot is the image center
        self.joystick_handle_cache = {}
        self.background_image = None

        # Original artwork (PIL) kept so it can be re-rendered at any size.
        self.src_bg = self.src_machine = self.src_claw = None
        self.src_handle = self.src_base = None
        self.src_balls = []

        # Joystick animation state (degrees, positive = leaning right)
        self.joystick_angle = 0.0
        self.joystick_target = 0.0
        self.joystick_loop_running = False
        self.joystick_reset_job = None

        self._build_interface()
        self._apply_geometry(prefs.get("geometry"))
        self._load_assets()
        self._rebuild_images()
        self._build_pile()
        self.root.bind_all("<KeyPress>", self._key_press)
        self.root.bind_all("<KeyRelease>", self._key_release)
        self.root.bind_all("<ButtonPress-1>", self._grab_focus, add="+")
        self.root.protocol("WM_DELETE_WINDOW", self.quit_app)
        self._apply_window_mode(first=True)
        self._draw_machine()
        self._update_counters()

    # ---------- Preferences ----------
    def _load_prefs(self):
        try:
            return json.loads(PREFS_FILE.read_text())
        except Exception:
            return {}

    def _save_prefs(self):
        try:
            PREFS_FILE.write_text(json.dumps({
                "geometry": self.root.geometry(),
                "pinned": self.pinned,
                "borderless": self.borderless,
                "compact": self.compact,
            }))
        except Exception:
            pass

    def _min_size(self):
        return (MIN_W_COMPACT, MIN_H_COMPACT) if self.compact else (MIN_W_FULL, MIN_H_FULL)

    def _apply_geometry(self, saved):
        min_w, min_h = self._min_size()
        w, h, x, y = None, None, None, None
        match = re.match(r"^(\d+)x(\d+)\+(-?\d+)\+(-?\d+)$", saved or "")
        if match:
            w, h, x, y = map(int, match.groups())
        else:
            w, h = map(int, DEFAULT_GEOMETRY.split("x"))
        sw, sh = self.root.winfo_screenwidth(), self.root.winfo_screenheight()
        w = max(min_w, min(w, sw))
        h = max(min_h, min(h, sh))
        self.root.minsize(min_w, min_h)
        if x is None:
            self.root.geometry(f"{w}x{h}")
        else:
            x = max(0, min(x, sw - 120))
            y = max(0, min(y, sh - 80))
            self.root.geometry(f"{w}x{h}+{x}+{y}")

    # ---------- Widget window controls ----------
    def _grab_focus(self, event):
        """Borderless windows don't always get keyboard focus; claim it on click."""
        if self.borderless:
            try:
                if self.root.focus_displayof() is None:
                    event.widget.focus_force()
            except (tk.TclError, KeyError):
                pass

    def _apply_window_mode(self, first=False):
        if self.borderless:
            if not first:
                self.root.withdraw()
            self.root.overrideredirect(True)
            if not first:
                self.root.deiconify()
            self.close_icon.pack(side="right", padx=(0, 4))
            self.grip.place(relx=1.0, rely=1.0, x=-4, y=-4, anchor="se")
            tk.Misc.lift(self.grip)
        else:
            if not first:
                self.root.withdraw()
            self.root.overrideredirect(False)
            if not first:
                self.root.deiconify()
            self.close_icon.pack_forget()
            self.grip.place_forget()
        try:
            self.root.attributes("-topmost", self.pinned)
        except tk.TclError:
            pass
        self._redraw_icons()

    def _toggle_pin(self):
        self.pinned = not self.pinned
        try:
            self.root.attributes("-topmost", self.pinned)
            if self.task_popup is not None:
                self.task_popup.attributes("-topmost", self.pinned)
        except tk.TclError:
            pass
        self._redraw_icons()
        self._save_prefs()

    def _toggle_frame(self):
        self.borderless = not self.borderless
        geometry = self.root.geometry()
        self._apply_window_mode()
        self.root.geometry(geometry)
        self._redraw_icons()
        self._save_prefs()

    def _toggle_compact(self):
        self.compact = not self.compact
        width, height = self.root.winfo_width(), self.root.winfo_height()
        if self.compact:
            self.side.grid_remove()
            width = width - PANEL_W - 10
        else:
            self.side.grid()
            width = width + PANEL_W + 10
        min_w, min_h = self._min_size()
        self.root.minsize(min_w, min_h)
        self.root.geometry(f"{max(min_w, width)}x{max(min_h, height)}")
        self._redraw_icons()
        self._save_prefs()

    def quit_app(self):
        self._save_prefs()
        self.root.destroy()

    def _bar_press(self, event):
        if self.borderless:
            self._drag_off = (event.x_root - self.root.winfo_x(),
                              event.y_root - self.root.winfo_y())

    def _bar_move(self, event):
        if self.borderless:
            ox, oy = self._drag_off
            self.root.geometry(f"+{event.x_root - ox}+{event.y_root - oy}")

    def _bar_release(self, event):
        if self.borderless:
            self._save_prefs()

    def _grip_press(self, event):
        self._resize_start = (event.x_root, event.y_root,
                              self.root.winfo_width(), self.root.winfo_height())

    def _grip_move(self, event):
        x0, y0, w0, h0 = self._resize_start
        min_w, min_h = self._min_size()
        w = max(min_w, w0 + event.x_root - x0)
        h = max(min_h, h0 + event.y_root - y0)
        self.root.geometry(f"{w}x{h}")

    def _grip_release(self, event):
        self._save_prefs()

    # ---------- Interface ----------
    def _make_icon(self, parent, draw, command, hint):
        icon = tk.Canvas(parent, width=28, height=26, bg=BAR_BG,
                         highlightthickness=0, cursor="hand2")
        icon.draw = draw
        icon.bind("<Button-1>", lambda e: command())
        icon.bind("<Enter>", lambda e: self.bar_title.config(text=hint))
        icon.bind("<Leave>", lambda e: self.bar_title.config(text="\u2605 CLAWSY TASKS \u2605"))
        draw(icon)
        return icon

    def _draw_pin_icon(self, c):
        c.delete("all")
        if self.pinned:   # pushed straight in, with a little shadow
            c.create_oval(8, 15, 22, 23, fill="#d97a9c", outline="")
            c.create_oval(8, 4, 22, 18, fill="#e53e5c", outline="#a82040", width=2)
            c.create_oval(11, 7, 15, 11, fill="#ffd0da", outline="")
        else:             # lying loose, tilted
            c.create_line(7, 22, 16, 11, fill="#ffe3ee", width=2)
            c.create_oval(13, 4, 25, 16, fill=BAR_BG, outline="white", width=2)

    def _draw_panel_icon(self, c):
        c.delete("all")
        c.create_rectangle(5, 5, 23, 21, outline="white", width=2)
        if self.compact:
            c.create_line(16, 5, 16, 21, fill="white", width=1)
        else:
            c.create_rectangle(16, 5, 23, 21, fill="white", outline="white")

    def _draw_frame_icon(self, c):
        c.delete("all")
        c.create_rectangle(5, 5, 23, 21, outline="white", width=2)
        if not self.borderless:   # normal window = has a title bar
            c.create_rectangle(5, 5, 23, 10, fill="white", outline="white")

    def _draw_close_icon(self, c):
        c.delete("all")
        c.create_line(8, 7, 20, 19, fill="white", width=3)
        c.create_line(20, 7, 8, 19, fill="white", width=3)

    def _redraw_icons(self):
        for icon in (self.pin_icon, self.panel_icon, self.frame_icon, self.close_icon):
            icon.draw(icon)

    def _build_interface(self):
        shell = tk.Frame(self.root, bg=EDGE, padx=2, pady=2)
        shell.pack(fill="both", expand=True)
        self.shell = shell
        inner = tk.Frame(shell, bg=PINK)
        inner.pack(fill="both", expand=True)

        # --- top bar: drag handle + widget buttons ---
        bar = tk.Frame(inner, bg=BAR_BG, height=30)
        bar.pack(fill="x")
        bar.pack_propagate(False)
        self.bar_title = tk.Label(bar, text="\u2605 CLAW TO-DO \u2605", bg=BAR_BG,
                                  fg="white", font=("Arial", 11, "bold"))
        self.pin_icon = self._make_icon(bar, self._draw_pin_icon, self._toggle_pin,
                                        "Pin on top of all windows")
        self.panel_icon = self._make_icon(bar, self._draw_panel_icon, self._toggle_compact,
                                          "Show / hide side panel")
        self.frame_icon = self._make_icon(bar, self._draw_frame_icon, self._toggle_frame,
                                          "Borderless widget / normal window")
        self.close_icon = self._make_icon(bar, self._draw_close_icon, self.quit_app, "Close")
        self.pin_icon.pack(side="left", padx=(6, 0))
        self.panel_icon.pack(side="left")
        self.frame_icon.pack(side="left")
        self.bar_title.pack(side="left", expand=True, fill="both")
        for widget in (bar, self.bar_title):
            widget.bind("<ButtonPress-1>", self._bar_press)
            widget.bind("<B1-Motion>", self._bar_move)
            widget.bind("<ButtonRelease-1>", self._bar_release)

        # --- status line along the bottom ---
        self.status_label = tk.Label(
            inner, text="Add tasks, move the claw above a ball, then press the red button.",
            font=("Arial", 11, "bold"), fg="#e9689a", bg=PINK, justify="center"
        )
        self.status_label.pack(side="bottom", fill="x", pady=(2, 8), padx=(8, 26))
        inner.bind("<Configure>",
                   lambda e: self.status_label.config(wraplength=max(120, e.width - 50)))

        main = tk.Frame(inner, bg=PINK)
        main.pack(fill="both", expand=True, padx=8, pady=(6, 0))
        main.columnconfigure(0, weight=1)
        main.columnconfigure(1, weight=0)
        main.rowconfigure(0, weight=1)

        self.canvas = ScaledCanvas(main, width=200, height=240, bg=PINK, highlightthickness=0)
        self.canvas.raw.grid(row=0, column=0, sticky="nsew", padx=(0, 10))
        self.canvas.raw.bind("<Button-1>", self._canvas_click)
        self.canvas.raw.bind("<ButtonRelease-1>", self._canvas_click)
        self.canvas.raw.bind("<Configure>", self._on_canvas_configure)

        side = tk.Frame(main, bg="#fff0f5", padx=14, pady=14, width=PANEL_W,
                        highlightbackground="#f29bbb", highlightthickness=2)
        side.grid(row=0, column=1, sticky="nsew")
        side.pack_propagate(False)
        self.side = side

        tk.Label(
            side, text="ADD A TASK", font=("Arial", 13, "bold"),
            fg="#e9689a", bg="#fff0f5"
        ).pack(anchor="w")

        self.task_entry = tk.Entry(
            side, font=("Arial", 11), bg="white", relief="flat"
        )
        self.task_entry.pack(fill="x", pady=(8, 6))
        self.task_entry.bind("<Return>", lambda event: self.add_task())

        self.add_button = tk.Button(
            side, text="ADD TASK", command=self.add_task,
            bg="#a9d8f5", fg="#334c85", activebackground="#cbeaff",
            font=("Arial", 10, "bold"), relief="flat", cursor="hand2"
        )
        self.add_button.pack(fill="x", pady=(0, 12))

        self.remaining_label = tk.Label(
            side, font=("Arial", 11, "bold"), fg="#6072b8", bg="#fff0f5"
        )
        self.remaining_label.pack(anchor="w")
        self.completed_label = tk.Label(
            side, font=("Arial", 11, "bold"), fg="#e9689a", bg="#fff0f5"
        )
        self.completed_label.pack(anchor="w", pady=(2, 10))

        tk.Label(
            side, text="TASKS IN MACHINE", font=("Arial", 10, "bold"),
            fg="#697ac4", bg="#fff0f5"
        ).pack(anchor="w")

        # Bottom controls are packed first so the task list is what shrinks.
        bottom = tk.Frame(side, bg="#fff0f5")
        bottom.pack(side="bottom", fill="x")

        self.reset_button = tk.Button(
            bottom, text="RESET ALL", command=self.reset_all,
            bg="#c9c6f5", fg="#4d4b88", activebackground="#dfddff",
            font=("Arial", 10, "bold"), relief="flat", cursor="hand2"
        )
        self.reset_button.pack(side="bottom", fill="x")

        self.done_button = tk.Button(
            bottom, text="MARK AS DONE", command=self.mark_done,
            bg="#a8e2d1", fg="#315c67", activebackground="#cdf5e8",
            font=("Arial", 10, "bold"), relief="flat", cursor="hand2",
            state="disabled"
        )
        self.done_button.pack(side="bottom", fill="x", pady=(0, 8))

        tk.Label(
            bottom, text="Hold A/D or \u2190/\u2192 to move the claw.\nPress the red button to pick.",
            font=("Arial", 9, "bold"), fg="#e9689a", bg="#fff0f5",
            wraplength=190, justify="center"
        ).pack(side="bottom", fill="x", pady=(2, 8))

        self.play_button = tk.Button(
            bottom, text="PUSH TO PICK", command=self.pick_task,
            bg="#f7a0b8", fg="#6b3152", activebackground="#ffc5d5",
            font=("Arial", 12, "bold"), relief="flat", cursor="hand2"
        )

        self.remove_button = tk.Button(
            bottom, text="REMOVE SELECTED", command=self.remove_task,
            bg="#f6a8bd", fg="#6b3152", activebackground="#ffc8d8",
            font=("Arial", 9, "bold"), relief="flat", cursor="hand2"
        )
        self.remove_button.pack(side="bottom", fill="x", pady=(6, 0))

        list_frame = tk.Frame(side, bg="#fff0f5")
        list_frame.pack(fill="both", expand=True, pady=(6, 0))
        self.task_list = tk.Listbox(
            list_frame, height=3, font=("Arial", 10),
            bg="#fffafd", fg="#5b639b", selectbackground="#f7b4d0",
            activestyle="none", relief="flat"
        )
        self.task_list.pack(side="left", fill="both", expand=True)
        scrollbar = tk.Scrollbar(list_frame, command=self.task_list.yview)
        scrollbar.pack(side="right", fill="y")
        self.task_list.config(yscrollcommand=scrollbar.set)

        if self.compact:
            side.grid_remove()

        # Resize grip (only shown when the window is borderless).
        self.grip = tk.Canvas(shell, width=18, height=18, bg=PINK, highlightthickness=0,
                              cursor="bottom_right_corner" if sys.platform.startswith("linux")
                              else "size_nw_se" if sys.platform == "win32" else "arrow")
        for i in (5, 10, 15):
            self.grip.create_line(17, i, i, 17, fill=EDGE, width=2)
        self.grip.bind("<ButtonPress-1>", self._grip_press)
        self.grip.bind("<B1-Motion>", self._grip_move)
        self.grip.bind("<ButtonRelease-1>", self._grip_release)

    # ---------- Scaling ----------
    def _on_canvas_configure(self, event):
        if self._resize_job:
            self.root.after_cancel(self._resize_job)
        self._resize_job = self.root.after(60, self._apply_canvas_size)

    def _apply_canvas_size(self):
        self._resize_job = None
        w, h = self.canvas.raw.winfo_width(), self.canvas.raw.winfo_height()
        if w < 50 or h < 50:
            return
        old_scale = self.canvas.s
        self.canvas.set_view(w, h)
        if abs(self.canvas.s - old_scale) > 1e-6:
            self._rebuild_images()
        self._draw_machine()

    # ---------- Assets and drawing ----------
    def _open_image(self, path):
        if not (Image and path.exists()):
            return None
        try:
            return Image.open(path).convert("RGBA")
        except Exception:
            return None

    def _load_assets(self):
        """Load the original artwork once; it is re-rendered whenever the size changes."""
        self.src_bg = self._open_image(ASSETS_DIR / "background.png")
        self.src_machine = self._open_image(ASSETS_DIR / "claw_machine.png")
        self.src_claw = self._open_image(ASSETS_DIR / "claw.png")
        joystick = self._open_image(ASSETS_DIR / "joystick.png")
        if joystick:
            self.src_handle = joystick.crop(HANDLE_BOX)
            self.src_base = joystick.crop(BASE_BOX)
        balls_dir = ASSETS_DIR / "balls"
        if Image and balls_dir.exists():
            for path in sorted(balls_dir.glob("*.png")):
                image = self._open_image(path)
                if image:
                    self.src_balls.append(image)
        self._measure_ball_radius()

    def _measure_ball_radius(self):
        """Use the ball's visible (non-transparent) size for collisions."""
        if not self.src_balls:
            return
        try:
            img = fit_image(self.src_balls[0], BALL_SIZE, BALL_SIZE, Image.Resampling.LANCZOS)
            box = img.getchannel("A").getbbox()
            if box:
                # 0.9 lets neighbours overlap a touch, like balls in 3D.
                self.ball_radius = (box[2] - box[0]) / 2 * 0.9
        except Exception:
            pass

    def _rebuild_images(self):
        """Render every image at the current window scale."""
        if not (Image and ImageTk):
            return
        s = self.canvas.s
        lanczos = Image.Resampling.LANCZOS
        nearest = Image.Resampling.NEAREST
        refs = []

        def photo(img):
            tk_image = ImageTk.PhotoImage(img)
            refs.append(tk_image)
            return tk_image

        self.background_image = photo(fit_image(self.src_bg, LOGICAL_W * s, LOGICAL_H * s, lanczos)) if self.src_bg else None
        self.machine_image = photo(fit_image(self.src_machine, LOGICAL_W * s, LOGICAL_H * s, lanczos)) if self.src_machine else None
        self.claw_image = photo(fit_image(self.src_claw, 92 * s, 105 * s, lanczos)) if self.src_claw else None
        self.ball_images = [photo(fit_image(b, BALL_SIZE * s, BALL_SIZE * s, lanczos)) for b in self.src_balls]

        self.joystick_base_image = None
        self.joystick_handle_source = None
        self.joystick_handle_cache = {}
        if self.src_handle and self.src_base:
            handle = fit_image(self.src_handle, 55 * s, 62 * s, nearest)
            base = fit_image(self.src_base, 78 * s, 48 * s, nearest)
            # Pad the handle so its pivot (bottom-center) is the exact middle of the
            # image; rotating about the center then swings the stick like a joystick.
            w, h = handle.size
            radius = max(w, h) + 4
            inset = max(1, round(HANDLE_PIVOT_INSET * s))
            padded = Image.new("RGBA", (radius * 2, radius * 2), (0, 0, 0, 0))
            padded.paste(handle, (radius - w // 2, radius - h + inset))
            self.joystick_handle_source = padded
            self.joystick_base_image = photo(base)
        self.image_refs = refs

    def _draw_machine(self):
        self.canvas.delete("all")
        self.canvas.create_rectangle(0, 0, LOGICAL_W, LOGICAL_H, fill=PINK, outline="")
        if self.background_image:
            self.canvas.create_image(260, 310, image=self.background_image)
        if not self.machine_image:
            self.canvas.create_rectangle(35, 45, 485, 550, fill="#211c40", outline="#f9a8d4", width=5)
            self.canvas.create_text(260, 25, text="WIN YOUR PRIORITY!", fill="#ffe66d", font=("Arial", 15, "bold"))

        # Back row first, then front row; within a row, higher balls first.
        self.ball_items = {}
        order = sorted(
            (i for i in range(BALL_COUNT) if self.ball_alive[i]),
            key=lambda i: (self.ball_lane[i], self.ball_pos[i][1]),
        )
        for index in order:
            self._draw_ball(index)

        # Draw the cabinet over the balls so its walls stay visually on top.
        if self.machine_image:
            self.canvas.create_image(260, 310, image=self.machine_image, tags="machine")

        if self.ball_in_chute and self.ball_images and self.carry_ball_item is None:
            self.canvas.create_image(
                self.chute_center[0], self.chute_center[1],
                image=self.ball_images[self.chute_ball_index % len(self.ball_images)],
                tags="chute_ball"
            )

        self.canvas.create_line(self.claw_x, 135, self.claw_x, self.claw_y - 10, fill="#8c8fd5", width=3, tags="claw_line")
        if self.claw_image:
            self.canvas.create_image(self.claw_x, self.claw_y, image=self.claw_image, tags="claw")
        else:
            self._draw_claw(self.claw_x, self.claw_y)

        if self.carry_ball_item is not None:      # redraw mid-carry (window resized)
            self.carry_ball_item = self._create_carried_ball(*self.carry_pos)

        self._place_joystick()

    def _draw_claw(self, x, y):
        self.canvas.delete("claw_shape", "claw_line")
        self.canvas.create_line(x, 135, x, y - 10, fill="#8c8fd5", width=3, tags="claw_shape")
        self.canvas.create_line(x, y, x - 18, y + 28, fill="#e5e7eb", width=5, tags="claw_shape")
        self.canvas.create_line(x, y, x + 18, y + 28, fill="#e5e7eb", width=5, tags="claw_shape")
        self.canvas.create_arc(x - 20, y + 16, x, y + 44, start=180, extent=100, style="arc", outline="#e5e7eb", width=5, tags="claw_shape")
        self.canvas.create_arc(x, y + 16, x + 20, y + 44, start=260, extent=100, style="arc", outline="#e5e7eb", width=5, tags="claw_shape")

    def _ball_position(self, index):
        return self.ball_pos[index]

    def _draw_ball(self, index):
        x, y = self.ball_pos[index]
        tag = f"ball_{index}"
        if self.ball_images:
            image = self.ball_images[index % len(self.ball_images)]
            item = self.canvas.create_image(x, y, image=image, tags=tag)
        else:
            colors = ["#fb7185", "#60a5fa", "#facc15", "#a78bfa", "#34d399", "#fb923c"]
            r = self.ball_radius
            item = self.canvas.create_oval(x - r, y - r, x + r, y + r, fill=colors[index % len(colors)], outline="white", width=2, tags=tag)
        # Task names are intentionally hidden from the user.
        self.ball_items[index] = item
        return item

    def _place_ball_item(self, index, x, y):
        item = self.ball_items.get(index)
        if item is None:
            return
        if self.ball_images:
            self.canvas.coords(item, x, y)
        else:
            r = self.ball_radius
            self.canvas.coords(item, x - r, y - r, x + r, y + r)

    # ---------- Ball pile physics ----------
    def _rest_y(self, x, lane, placed):
        """Height a ball dropped at x comes to rest, given balls already placed."""
        r = self.ball_radius
        y = FLOOR_Y - r - (BACK_LANE_RAISE if lane == 0 else 0)
        for ox, oy, olane in placed:
            if olane != lane:
                continue
            dx = abs(x - ox)
            if dx < 2 * r:
                y = min(y, oy - math.sqrt(4 * r * r - dx * dx))
        return y

    def _build_pile(self):
        """Drop balls one at a time so they heap up naturally on the floor."""
        span = PILE_RIGHT - PILE_LEFT
        offset = random.random()
        self.ball_pos = []
        self.ball_lane = []
        placed = []
        for i in range(BALL_COUNT):
            lane = i % 2
            k = i // 2
            frac = (k * 0.618034 + lane * 0.31 + offset) % 1
            x = PILE_LEFT + frac * span + random.uniform(-6, 6)
            x = max(PILE_LEFT, min(PILE_RIGHT, x))
            y = self._rest_y(x, lane, placed)
            placed.append((x, y, lane))
            self.ball_pos.append((x, y))
            self.ball_lane.append(lane)

    def _resting_positions(self):
        """Where every remaining ball would settle (lowest balls first)."""
        alive = [i for i in range(BALL_COUNT) if self.ball_alive[i]]
        alive.sort(key=lambda i: -self.ball_pos[i][1])
        placed, result = [], {}
        for i in alive:
            x, _ = self.ball_pos[i]
            lane = self.ball_lane[i]
            y = self._rest_y(x, lane, placed)
            placed.append((x, y, lane))
            result[i] = (x, y)
        return result

    def _settle_balls(self):
        """Let balls above a removed one fall into the gap."""
        targets = self._resting_positions()
        self.settling = True
        self._settle_step(targets, {})

    def _settle_step(self, targets, velocity):
        moving = False
        for i, (tx, ty) in targets.items():
            x, y = self.ball_pos[i]
            if y < ty - 0.5:
                velocity[i] = velocity.get(i, 0) + 1.5
                y = min(y + velocity[i], ty)
                self.ball_pos[i] = (x, y)
                self._place_ball_item(i, x, y)
                moving = True
            elif y != ty:
                self.ball_pos[i] = (x, ty)
                self._place_ball_item(i, x, ty)
        if moving:
            self.root.after(20, lambda: self._settle_step(targets, velocity))
        else:
            self.settling = False

    def _respawn_ball(self, animate=True):
        """Put a fresh ball back into the machine, dropping in from the top."""
        index = self.dead_ball_index
        if index is None:
            return
        self.dead_ball_index = None
        placed = [
            (self.ball_pos[i][0], self.ball_pos[i][1], self.ball_lane[i])
            for i in range(BALL_COUNT) if self.ball_alive[i]
        ]
        x = random.uniform(PILE_LEFT + 10, PILE_RIGHT - 10)
        rest = self._rest_y(x, 1, placed)
        self.ball_alive[index] = True
        self.ball_lane[index] = 1
        if not animate:
            self.ball_pos[index] = (x, rest)
            return
        self.ball_pos[index] = (x, SPAWN_Y)
        item = self._draw_ball(index)
        if self.machine_image:
            self.canvas.tag_lower(item, "machine")
        self.settling = True
        self._settle_step({index: (x, rest)}, {})

    def _assign_tasks_to_balls(self):
        """Distribute tasks evenly across the hidden, pre-existing balls."""
        if not self.tasks:
            self.ball_slots = [None] * BALL_COUNT
            return
        self.ball_slots = [self.tasks[index % len(self.tasks)] for index in range(BALL_COUNT)]
        random.shuffle(self.ball_slots)

    # ---------- Joystick ----------
    def _tilt_joystick(self, direction):
        """Lean the stick left (-1) or right (+1); it springs back to center."""
        self._set_joystick_target(direction * JOYSTICK_MAX_TILT)

    def _set_joystick_target(self, angle):
        self.joystick_target = angle
        if self.joystick_reset_job:
            self.root.after_cancel(self.joystick_reset_job)
            self.joystick_reset_job = None
        if angle != 0:
            # Spring back to neutral shortly after the input stops.
            self.joystick_reset_job = self.root.after(
                140, lambda: self._set_joystick_target(0)
            )
        if not self.joystick_loop_running:
            self.joystick_loop_running = True
            self._joystick_step()

    def _joystick_step(self):
        diff = self.joystick_target - self.joystick_angle
        if abs(diff) < 0.5:
            self.joystick_angle = self.joystick_target
            self.joystick_loop_running = False
            self._place_joystick()
            return
        self.joystick_angle += diff * 0.4
        self._place_joystick()
        self.root.after(20, self._joystick_step)

    def _draw_joystick(self):
        """Vector fallback: fixed base, stick pivots from the base center."""
        pivot_x, pivot_y = self.joystick_pivot
        length = 36
        rad = math.radians(self.joystick_angle)
        knob_x = pivot_x + length * math.sin(rad)
        knob_y = pivot_y - length * math.cos(rad)
        self.canvas.create_line(
            pivot_x, pivot_y, knob_x, knob_y,
            fill="#7186d0", width=8, capstyle="round", tags="joystick"
        )
        self.canvas.create_oval(
            knob_x - 17, knob_y - 17, knob_x + 17, knob_y + 17,
            fill="#f49bb5", outline="#7186d0", width=3, tags="joystick"
        )
        self.canvas.create_oval(
            knob_x - 8, knob_y - 10, knob_x - 1, knob_y - 3,
            fill="#ffdce8", outline="", tags="joystick"
        )
        # Base drawn last so it covers the bottom of the stick and never moves.
        self.canvas.create_oval(
            pivot_x - 34, pivot_y - 10, pivot_x + 34, pivot_y + 18,
            fill="#a9d8f5", outline="#7186d0", width=3, tags="joystick"
        )

    def _handle_photo(self, angle):
        """Rotated handle image, cached per whole degree."""
        key = int(round(angle))
        photo = self.joystick_handle_cache.get(key)
        if photo is None:
            # PIL rotates counter-clockwise, so negate to lean right for +angle.
            rotated = self.joystick_handle_source.rotate(
                -key, resample=Image.Resampling.NEAREST, expand=False
            )
            photo = ImageTk.PhotoImage(rotated)
            self.joystick_handle_cache[key] = photo
        return photo

    def _place_joystick(self, claw_x=None):
        """The base stays fixed; only the handle swings around its pivot."""
        self.canvas.delete("joystick")
        if not (self.joystick_base_image and self.joystick_handle_source):
            self._draw_joystick()
            return
        base_x, base_y = self.joystick_center
        pivot_x, pivot_y = self.joystick_pivot
        # Handle first, then base on top so the stick's foot is hidden inside it.
        self.canvas.create_image(
            pivot_x, pivot_y,
            image=self._handle_photo(self.joystick_angle),
            tags="joystick"
        )
        self.canvas.create_image(
            base_x, base_y + 12,
            image=self.joystick_base_image,
            tags="joystick"
        )

    def _canvas_click(self, event):
        # Broad hit area around the red button in the cabinet artwork (logical units).
        x, y = self.canvas.to_logical(event.x, event.y)
        if 325 <= x <= 455 and 420 <= y <= 535:
            self.pick_task()

    def _key_press(self, event):
        if isinstance(event.widget, (tk.Entry, tk.Text)):
            return
        key = event.keysym.lower()
        if key not in ("left", "right", "a", "d"):
            return
        if self.animating or self.active_task:
            return
        # Ignore the brief release/press pairs that key auto-repeat produces.
        job = self.key_release_jobs.pop(key, None)
        if job:
            self.root.after_cancel(job)
        self.keys_down.add(key)
        if not self.move_loop_running:
            self.move_loop_running = True
            self._move_loop()

    def _key_release(self, event):
        key = event.keysym.lower()
        if key in self.keys_down and key not in self.key_release_jobs:
            self.key_release_jobs[key] = self.root.after(
                40, lambda: self._drop_key(key)
            )

    def _drop_key(self, key):
        self.key_release_jobs.pop(key, None)
        self.keys_down.discard(key)

    def _move_loop(self):
        """Glide the claw while a move key is held, like holding a joystick."""
        if self.animating or self.active_task:
            self.keys_down.clear()
            self.move_loop_running = False
            return
        direction = (
            (1 if self.keys_down & {"right", "d"} else 0)
            - (1 if self.keys_down & {"left", "a"} else 0)
        )
        if not self.keys_down:
            self.move_loop_running = False
            return
        if direction:
            self._tilt_joystick(direction)
            new_x = max(CLAW_MIN_X, min(CLAW_MAX_X, self.claw_x + direction * CLAW_SPEED))
            self._move_claw(self.claw_y, new_x)
        self.root.after(16, self._move_loop)

    # ---------- Task actions ----------
    def add_task(self):
        task = self.task_entry.get().strip()
        if not task:
            self.status_label.config(text="Please type a task first.", fg="#fda4af")
            return
        if task in self.tasks or task in self.completed_tasks:
            self.status_label.config(text="That task is already on your list.", fg="#fda4af")
            return
        self.tasks.append(task)
        self._assign_tasks_to_balls()
        self.task_entry.delete(0, tk.END)
        self._refresh_task_list()
        self._draw_machine()
        self._update_counters()
        self.status_label.config(text=f'Added: "{task}"', fg="#ffe66d")

    def remove_task(self):
        selection = self.task_list.curselection()
        if not selection:
            self.status_label.config(text="Select a task to remove.", fg="#fda4af")
            return
        task = self.tasks[selection[0]]
        if task == self.active_task:
            self.status_label.config(text="Finish the active task before removing it.", fg="#fda4af")
            return
        self.tasks.remove(task)
        self._assign_tasks_to_balls()
        self._refresh_task_list()
        self._draw_machine()
        self._update_counters()
        self.status_label.config(text=f'Removed: "{task}"', fg="#ffe66d")

    def pick_task(self):
        if self.animating:
            return
        if self.active_task:
            self.status_label.config(text="Finish your current task before picking another.", fg="#fda4af")
            return
        if self.settling:
            self.status_label.config(text="Wait for the balls to settle...", fg="#fda4af")
            return
        if not self.tasks:
            self.status_label.config(text="There are no tasks available. Add one first!", fg="#fda4af")
            return

        # The claw lands on the highest ball under it, like the real thing.
        reach = self.ball_radius + 12
        candidates = []
        for index, ball_task in enumerate(self.ball_slots):
            if ball_task is None or not self.ball_alive[index]:
                continue
            ball_x, ball_y = self.ball_pos[index]
            dx = abs(self.claw_x - ball_x)
            if dx <= reach:
                candidates.append((ball_y, dx, index, ball_task))
        if not candidates:
            self.status_label.config(text="Move the claw above a ball before pushing to pick.", fg="#fda4af")
            return

        self.keys_down.clear()
        self.animating = True
        self.play_button.config(state="disabled")
        self.add_button.config(state="disabled")
        self.remove_button.config(state="disabled")
        self.reset_button.config(state="disabled")
        _, _, ball_index, self.target_task = min(candidates)
        self.target_ball_index = ball_index
        self.target_ball = self.ball_pos[ball_index]
        self.status_label.config(text="The claw is grabbing...", fg="#ffe66d")
        self._pick_origin_x = self.claw_x
        self._pick_return_y = self.claw_y
        # Center the claw over the ball so it drops straight down onto it.
        self.root.after(0, self._align_then_descend)

    def _align_then_descend(self):
        ball_x, ball_y = self.target_ball
        if abs(self.claw_x - ball_x) > 1.5:
            step = max(-3, min(3, ball_x - self.claw_x))
            self._move_claw(self.claw_y, self.claw_x + step)
            self.root.after(16, self._align_then_descend)
            return
        self._pick_origin_x = self.claw_x
        self._animate_claw(self.claw_y, ball_y - CARRY_OFFSET, 1)

    def _animate_claw(self, current_y, target_y, direction):
        """Move the claw vertically, then continue the visible pickup sequence."""
        if direction == 1 and current_y < target_y:
            next_y = min(current_y + 10, target_y)
            self._move_claw(next_y)
            self.root.after(25, lambda: self._animate_claw(next_y, target_y, 1))
        elif direction == 1:
            self.root.after(350, self._attach_ball)
        elif current_y > target_y:
            next_y = max(current_y - 10, target_y)
            self._move_claw(next_y)
            self.root.after(25, lambda: self._animate_claw(next_y, target_y, -1))
        else:
            if self.ball_in_chute:
                self.root.after(250, self._reveal_task)
            else:
                self.root.after(250, self._move_to_chute)

    def _create_carried_ball(self, x, y):
        """Create the ball held by the claw (image, or a fallback circle)."""
        self.carry_pos = (x, y)
        if self.ball_images:
            image = self.ball_images[self.chute_ball_index % len(self.ball_images)]
            return self.canvas.create_image(x, y, image=image, tags="carried_ball")
        r = self.ball_radius
        return self.canvas.create_oval(
            x - r, y - r, x + r, y + r,
            fill="#fb7185", outline="white", width=2, tags="carried_ball"
        )

    def _attach_ball(self):
        """Take the ball out of the pile and show it held by the claw."""
        index = self.target_ball_index
        self.canvas.delete(self.ball_items[index])
        self.ball_alive[index] = False
        self.dead_ball_index = index
        self.chute_ball_index = index
        self.carry_ball_item = self._create_carried_ball(self.claw_x, self.claw_y + CARRY_OFFSET)
        self._settle_balls()   # balls that rested on it tumble down
        self.status_label.config(text="Ball secured! Taking it to the chute...", fg="#e9689a")
        self.root.after(250, lambda: self._animate_claw(self.claw_y, self._pick_return_y, -1))

    def _move_to_chute(self):
        """Carry the ball horizontally to the side chute."""
        if self.claw_x < self.chute_x:
            next_x = min(self.claw_x + 10, self.chute_x)
        elif self.claw_x > self.chute_x:
            next_x = max(self.claw_x - 10, self.chute_x)
        else:
            self.root.after(250, self._drop_ball_in_chute)
            return
        self._move_claw(self.claw_y, next_x)
        self.root.after(25, self._move_to_chute)

    def _drop_ball_in_chute(self):
        """Drop only the ball into the chute while the claw stays above it."""
        self.status_label.config(text="Dropping the ball into the chute...", fg="#e9689a")
        self._animate_ball_drop()

    def _animate_ball_drop(self):
        if not self.carry_ball_item:
            return
        current_x, current_y = self.carry_pos
        target_x, target_y = self.chute_center
        distance = ((target_x - current_x) ** 2 + (target_y - current_y) ** 2) ** 0.5
        if distance > 8:
            next_x = current_x + (target_x - current_x) * 0.18
            next_y = current_y + (target_y - current_y) * 0.18
            self._set_carried_ball(next_x, next_y)
            self.root.after(25, self._animate_ball_drop)
            return
        self._set_carried_ball(target_x, target_y)
        self.canvas.addtag_withtag("chute_ball", self.carry_ball_item)
        self.carry_ball_item = None
        self.ball_in_chute = True
        self.status_label.config(text="Ball delivered! Returning the claw...", fg="#e9689a")
        self.root.after(300, self._return_claw_home)

    def _set_carried_ball(self, x, y):
        """Position the carried ball whether it is an image or a fallback oval."""
        self.carry_pos = (x, y)
        if self.ball_images:
            self.canvas.coords(self.carry_ball_item, x, y)
        else:
            r = self.ball_radius
            self.canvas.coords(self.carry_ball_item, x - r, y - r, x + r, y + r)

    def _return_claw_home(self):
        if self.claw_x == self._pick_origin_x:
            self.root.after(250, self._reveal_task)
            return
        direction = -10 if self.claw_x > self._pick_origin_x else 10
        next_x = self.claw_x + direction
        if (direction < 0 and next_x < self._pick_origin_x) or (direction > 0 and next_x > self._pick_origin_x):
            next_x = self._pick_origin_x
        self._move_claw(self.claw_y, next_x)
        self.root.after(25, self._return_claw_home)

    def _move_claw(self, y, x=None):
        if x is None:
            x = self.claw_x
        dx = x - self.claw_x
        self.claw_x = x
        self.claw_y = y
        if self.claw_image:
            self.canvas.coords("claw", x, y)
            self.canvas.coords("claw_line", x, 135, x, y - 32)
        else:
            self._draw_claw(x, y)
        if dx:
            # Lean the joystick the way the claw is travelling.
            self._tilt_joystick(1 if dx > 0 else -1)
        if self.carry_ball_item:
            self._set_carried_ball(x, y + CARRY_OFFSET)

    def _reveal_task(self):
        self.active_task = self.target_task
        self.animating = False
        self.target_task = None
        self.target_ball = None
        self.target_ball_index = None
        self.done_button.config(state="normal")
        self.status_label.config(text=f"YOUR PRIORITY: {self.active_task}", fg="#86efac")
        self._update_counters()
        self._refresh_task_list()
        self._enable_normal_controls()
        self.root.after(200, self._show_task_popup)

    # ---------- Themed popup ----------
    def _close_popup(self):
        if self.task_popup is not None:
            try:
                self.task_popup.destroy()
            except tk.TclError:
                pass
            self.task_popup = None

    def _show_task_popup(self):
        """Pop up the picked task in the middle of the window, in theme."""
        if not self.active_task:
            return
        self._close_popup()
        pink, blue, bg = "#e9689a", "#697ac4", "#fff0f5"

        win = tk.Toplevel(self.root)
        self.task_popup = win
        win.title("You won a task!")
        win.configure(bg=pink)
        win.resizable(False, False)
        win.transient(self.root)
        win.protocol("WM_DELETE_WINDOW", self._close_popup)
        try:
            win.attributes("-topmost", self.pinned)   # stay visible over a pinned widget
        except tk.TclError:
            pass

        card = tk.Frame(win, bg=bg, padx=28, pady=22,
                        highlightbackground="#f29bbb", highlightthickness=3)
        card.pack(padx=6, pady=6)

        tk.Label(card, text="\u2605  YOU WON A TASK!  \u2605",
                 font=("Arial", 18, "bold"), fg=pink, bg=bg).pack()

        # The ball you just picked, drawn at a fixed size whatever the widget size.
        ball = tk.Canvas(card, width=90, height=84, bg=bg, highlightthickness=0)
        ball.pack(pady=(10, 4))
        if self.src_balls and ImageTk:
            source = self.src_balls[self.chute_ball_index % len(self.src_balls)]
            self.popup_ball_image = ImageTk.PhotoImage(
                fit_image(source, BALL_SIZE, BALL_SIZE, Image.Resampling.LANCZOS))
            ball.create_image(45, 42, image=self.popup_ball_image)
        else:
            ball.create_oval(15, 12, 75, 72, fill="#f49bb5", outline="#7186d0", width=3)
            ball.create_text(45, 42, text="\u2605", fill="#ffe66d", font=("Arial", 22, "bold"))

        tk.Label(card, text="YOUR PRIORITY", font=("Arial", 10, "bold"),
                 fg=blue, bg=bg).pack()

        task_box = tk.Frame(card, bg="white", padx=16, pady=12,
                            highlightbackground="#a9d8f5", highlightthickness=2)
        task_box.pack(pady=(6, 14), fill="x")
        tk.Label(task_box, text=self.active_task, font=("Arial", 16, "bold"),
                 fg="#5b639b", bg="white", wraplength=300, justify="center").pack()

        buttons = tk.Frame(card, bg=bg)
        buttons.pack(fill="x")
        tk.Button(buttons, text="LET'S DO IT!", command=self._close_popup,
                  bg="#a9d8f5", fg="#334c85", activebackground="#cbeaff",
                  font=("Arial", 11, "bold"), relief="flat", cursor="hand2",
                  padx=14, pady=6).pack(side="left", expand=True, fill="x", padx=(0, 6))
        tk.Button(buttons, text="MARK AS DONE", command=self._popup_done,
                  bg="#a8e2d1", fg="#315c67", activebackground="#cdf5e8",
                  font=("Arial", 11, "bold"), relief="flat", cursor="hand2",
                  padx=14, pady=6).pack(side="left", expand=True, fill="x", padx=(6, 0))

        # Center over the widget.
        win.update_idletasks()
        w, h = win.winfo_reqwidth(), win.winfo_reqheight()
        x = self.root.winfo_rootx() + (self.root.winfo_width() - w) // 2
        y = self.root.winfo_rooty() + (self.root.winfo_height() - h) // 2
        win.geometry(f"+{max(0, x)}+{max(0, y)}")
        win.lift()
        win.focus_set()

    def _popup_done(self):
        self._close_popup()
        self.mark_done()

    def mark_done(self):
        if not self.active_task:
            return
        self._close_popup()
        finished = self.active_task
        self.completed_tasks.append(finished)
        self.tasks.remove(finished)
        self._assign_tasks_to_balls()
        self.active_task = None
        self.ball_in_chute = False
        self.canvas.delete("chute_ball", "carried_ball")
        self.done_button.config(state="disabled")
        self.play_button.config(state="normal")
        self._refresh_task_list()
        self._draw_machine()
        self._respawn_ball(animate=True)
        self._update_counters()
        self.status_label.config(text=f'Great job! Completed: "{finished}"', fg="#86efac")

    def reset_all(self):
        if self.animating:
            self.status_label.config(text="Please wait for the claw to finish.", fg="#fda4af")
            return
        if not (self.tasks or self.completed_tasks or self.active_task):
            return
        if messagebox.askyesno("Reset everything?", "Clear all current and completed tasks?"):
            self._close_popup()
            self.tasks.clear()
            self.completed_tasks.clear()
            self.active_task = None
            self.ball_in_chute = False
            self.canvas.delete("chute_ball", "carried_ball")
            self._assign_tasks_to_balls()
            self._respawn_ball(animate=False)
            self.done_button.config(state="disabled")
            self._refresh_task_list()
            self._draw_machine()
            self._update_counters()
            self.status_label.config(text="Everything has been reset.", fg="#ffe66d")

    def _enable_normal_controls(self):
        self.add_button.config(state="normal")
        self.remove_button.config(state="normal")
        self.reset_button.config(state="normal")

    def _refresh_task_list(self):
        self.task_list.delete(0, tk.END)
        for task in self.tasks:
            prefix = "★ " if task == self.active_task else "○ "
            self.task_list.insert(tk.END, prefix + task)

    def _update_counters(self):
        self.remaining_label.config(text=f"Remaining: {len(self.tasks)}")
        self.completed_label.config(text=f"Completed: {len(self.completed_tasks)}")


if __name__ == "__main__":
    root = tk.Tk()
    app = ClawMachineApp(root)
    root.mainloop()