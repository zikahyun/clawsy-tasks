# 🎀 Claw Machine To-Do

A cute desktop widget that turns your to-do list into a claw machine. Add your tasks, steer the claw, and grab a ball to find out what you should work on next. Nothing tells you which ball hides which task, so every pick is a surprise.

Built with Python and Tkinter. It can be resized, pinned on top of your other windows, and placed anywhere on your screen.

---

## ✨ Features

- **Play it like a real claw machine.** Hold the arrow keys or **A / D** to glide the claw. The joystick handle leans the way you move while its base stays put.
- **A natural ball pile.** Balls rest on each other in a heap, and the claw grabs the highest ball under it. When a ball is taken, the balls above it tumble down, and a fresh ball drops in when you finish the task.
- **Themed task reveal.** The claw drops the ball into the chute, then a popup shows your priority.
- **Widget mode.** Resizable, pinnable (always on top), draggable, with an optional borderless look.
- **Remembers your setup.** Window size, position, pin state and mode are saved between runs.

---

## 📦 Requirements

- Python 3.9 or newer
- Tkinter (included with most Python installs; on some Linux systems install `python3-tk`)
- [Pillow](https://pypi.org/project/pillow/) for the artwork and resizing

```bash
pip install pillow
```

> Without Pillow the app still runs, but it uses simple drawn shapes instead of your artwork.

---

## 🚀 Getting Started

1. Put `main.py` and your `assets` folder in the same folder.
2. Run it:

```bash
python main.py
```

3. Type a task and press **Enter** (or **ADD TASK**). Add as many as you like.
4. Move the claw above a ball and press the **red button** on the machine.
5. Watch the claw grab a ball and drop it in the chute. A popup reveals your priority.
6. Press **MARK AS DONE** when you finish. Then pick again.

---

## 🎮 Controls

| Action | How |
| --- | --- |
| Move the claw | Hold **A / D** or **← / →** |
| Pick a ball | Click the **red button** on the machine |
| Add a task | Type in the box, then **Enter** or **ADD TASK** |
| Remove a task | Select it in the list, then **REMOVE SELECTED** |
| Finish a task | **MARK AS DONE** (in the popup or the side panel) |
| Start over | **RESET ALL** |

> Click inside the window first so it receives your key presses.

---

## 🪟 Widget Controls

The pink bar along the top has these buttons:

| Button | What it does |
| --- | --- |
| 📌 Pin (left) | Keeps the widget on top of every other window. The popup stays on top too. |
| Panel icon | Hides or shows the side panel for a small, machine-only widget. |
| Frame icon | Switches between a **borderless widget** and a **normal window**. |
| ✕ (right) | Closes the app (borderless mode only). |

**In borderless mode:**

- Drag the **pink bar** to move the widget anywhere.
- Drag the **corner grip** at the bottom-right to resize it.

The whole machine scales with the window, including the artwork, balls, claw and joystick.

**Window size limits:** about 480 × 500 with the side panel showing, and about 250 × 360 with it hidden.

**Saved settings** are written to `widget_prefs.json` next to `main.py`. Delete that file to reset the window to its defaults. Tasks are not saved between runs.

---

## 🖼️ Assets

Put PNG files (transparent backgrounds work best) in an `assets` folder next to `main.py`:

```
claw-machine/
├── main.py
├── widget_prefs.json        (created automatically)
└── assets/
    ├── background.png       full-window background (optional)
    ├── claw_machine.png     the cabinet; the glass area should be transparent
    ├── claw.png             the claw
    ├── joystick.png         joystick with a handle on top and a round base below
    └── balls/
        ├── ball1.png        any number of ball images
        └── ball2.png
```

Every asset is optional. Anything missing is replaced with a simple drawn shape.

- **Balls:** several images in `assets/balls/` give you a mix of looks. The collision size is measured from each ball's visible (non-transparent) area, so padding in the PNG is fine.
- **Joystick:** the file is split into a handle and a base using the crop boxes `HANDLE_BOX` and `BASE_BOX` at the top of `main.py`. If you swap in different joystick art, adjust those two boxes.
- **Machine size:** the machine is designed on a 520 × 620 canvas and scaled from there.

---

## 🛠️ Customizing

The settings at the top of `main.py` are the ones you're most likely to want:

| Setting | What it changes |
| --- | --- |
| `BALL_COUNT` | How many balls are in the machine |
| `BALL_SIZE` | Size of the ball images |
| `FLOOR_Y` | Where the balls rest (raise or lower the pile) |
| `PILE_LEFT` / `PILE_RIGHT` | The left and right limits of the pile |
| `CARRY_OFFSET` | How deep the ball sits in the claw's fingers |
| `CLAW_SPEED` | How fast the claw glides |
| `JOYSTICK_MAX_TILT` | How far the joystick leans |
| `PANEL_W` | Width of the side panel |
| `DEFAULT_GEOMETRY` | The window size the first time you run it |

Colors are in the code as hex values such as `#ffdce8` and `#e9689a`. Search for them to change the theme.

---

## 🧰 Troubleshooting

**I can't type in the task box (especially on macOS).**
Borderless windows sometimes can't take keyboard focus. Click the **Frame** icon to switch to a normal window.

**The balls float above the floor or the pile looks off.**
Adjust `FLOOR_Y`, `PILE_LEFT` and `PILE_RIGHT` to match your `claw_machine.png`.

**The joystick looks cut off or part of the base spins.**
Adjust `HANDLE_BOX`, `BASE_BOX` or `HANDLE_PIVOT_INSET` to match your `joystick.png`.

**The artwork doesn't appear and everything looks like plain shapes.**
Install Pillow (`pip install pillow`) and check that your files are in `assets/` with the exact names above.

**The widget starts off-screen or at a strange size.**
Delete `widget_prefs.json` and restart.

**The pin doesn't keep the widget on top.**
Always-on-top depends on your window manager. It works on Windows, macOS and most Linux desktops.

---

## 📄 How It Works

- Each task is secretly assigned to one of the balls. Task names are never shown on the balls.
- The claw picks the highest ball under it, so you can't choose a specific task, only a spot.
- After a ball is picked, it is replaced when you mark the task done, so the machine stays full.

Have fun, and good luck with your priorities! 🎀
