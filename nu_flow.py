#!/usr/bin/env python3
"""
nu_flow — a focused single-line drafting mode for nu_draft
Phosphor green. One line at a time. Previous lines fade into darkness.

Best run via the launcher:    python3 nu_flow.py --launch
Or directly in Kitty:         python3 nu_flow.py

Font size controls:
  Ctrl+Shift+Equal    increase font size  (Kitty native — always works)
  Ctrl+Shift+Minus    decrease font size
  Ctrl+Shift+0        reset font size
  Ctrl+Q              save & quit
  Ctrl+S              save
  Esc                 quit without saving

Saves to ~/nu_drafts/ — same files as nu_draft.
Requires Kitty terminal with allow_remote_control yes in kitty.conf
"""

import curses
import subprocess
import os
import sys
import argparse
import textwrap

DRAFTS_DIR  = os.path.expanduser("~/nu_drafts")
CONFIG_FILE = os.path.expanduser("~/.nu_flow_font")
DEFAULT_FONT_SIZE = 24

# ── 256-color phosphor fade palette ──────────────────────────────────────────
# We'll define N fade levels from bright phosphor down to near-black.
# In xterm-256 color space the greens we want are approximately:
#   level 0 (current line) : 46  (#00ff00 — brightest green)
#   level 1                : 40  (#00d700)
#   level 2                : 34  (#00af00)
#   level 3                : 28  (#008700)
#   level 4 (oldest)       : 22  (#005f00)  barely visible
# Background stays terminal default (black).

FADE_COLORS = [46, 34, 28, 22, 16]   # index 0 = current line (brightest)
FADE_LEVELS = len(FADE_COLORS)        # 5: current + 4 fading lines


# ── Filesystem ────────────────────────────────────────────────────────────────

def ensure_dir(p):
    os.makedirs(p, exist_ok=True)

def get_drafts():
    try:
        return sorted(f[:-4] for f in os.listdir(DRAFTS_DIR)
                      if f.endswith(".txt") and
                      os.path.isfile(os.path.join(DRAFTS_DIR, f)))
    except OSError:
        return []

def draft_path(name):
    return os.path.join(DRAFTS_DIR, name + ".txt")

def read_draft(name):
    try:
        with open(draft_path(name), "r") as f:
            return f.read()
    except OSError:
        return ""

def write_draft(name, content):
    with open(draft_path(name), "w") as f:
        f.write(content)

def safe_name(s):
    return s.replace("/", "_").replace("\\", "_").strip()


# ── Font size persistence ─────────────────────────────────────────────────────

def load_font_size():
    try:
        return int(open(CONFIG_FILE).read().strip())
    except Exception:
        return DEFAULT_FONT_SIZE

def save_font_size(size):
    try:
        with open(CONFIG_FILE, "w") as f:
            f.write(str(size))
    except Exception:
        pass

# Font resizing is handled entirely by Kitty's own keyboard shortcuts:
#   Ctrl+Shift+Equal   → increase
#   Ctrl+Shift+Minus   → decrease
#   Ctrl+Shift+0       → reset to kitty.conf default
# No in-app font code needed — Kitty reflows the terminal automatically.


def launch_in_kitty(font_size, draft_name):
    """
    Open a dedicated Kitty window running nu_flow at the given font size.
    Font resizing inside the session is done with Kitty native shortcuts.
    """
    script = os.path.abspath(__file__)
    cmd = [
        "kitty",
        "--title=nu_flow",
        "--override=hide_window_decorations=yes",
        "--override=background=#000000",
        f"--override=font_size={font_size}",
        "--",
        "python3", script,
        "--font", str(font_size),
    ]
    if draft_name:
        cmd += ["--draft", draft_name]
    try:
        subprocess.Popen(cmd)
    except FileNotFoundError:
        print("kitty not found. Install with: sudo apt install kitty")
        sys.exit(1)


# ── Word wrap helper ──────────────────────────────────────────────────────────

def wrap_paragraph(text, width):
    """Wrap a single paragraph string into a list of display lines."""
    if not text:
        return [""]
    return textwrap.wrap(text, width,
                         drop_whitespace=False,
                         break_long_words=True,
                         break_on_hyphens=False) or [""]


# ── Prompt helpers ────────────────────────────────────────────────────────────

def centered_prompt(stdscr, prompt, pair_bright, max_len=60):
    sh, sw = stdscr.getmaxyx()
    bw = min(max(len(prompt) + 6, 34), sw - 4)
    bh = 5
    win = curses.newwin(bh, bw, (sh - bh) // 2, (sw - bw) // 2)
    win.keypad(True)
    curses.curs_set(1)
    text = ""
    while True:
        win.erase()
        win.border()
        try:
            win.addstr(1, 2, prompt[:bw - 4], curses.color_pair(pair_bright))
            win.addstr(2, 2, "─" * (bw - 4))
            disp = text[-(bw - 6):]
            win.addstr(3, 2, disp)
            win.move(3, 2 + len(disp))
        except curses.error:
            pass
        win.refresh()
        ch = win.getch()
        if ch in (curses.KEY_ENTER, 10, 13):
            curses.curs_set(0)
            return text.strip() or None
        elif ch in (27, 17):
            curses.curs_set(0)
            return None
        elif ch in (curses.KEY_BACKSPACE, 127, 8):
            text = text[:-1]
        elif 32 <= ch <= 126 and len(text) < max_len:
            text += chr(ch)


def pick_draft(stdscr, drafts, current, pair_bright, pair_hl):
    """Floating draft picker. Returns chosen name or None."""
    if not drafts:
        return None
    sh, sw   = stdscr.getmaxyx()
    ov_w     = min(44, sw - 4)
    ov_h     = min(len(drafts) + 2, sh - 4, 18)
    ov_y     = (sh - ov_h) // 2
    ov_x     = (sw - ov_w) // 2
    sel      = drafts.index(current) if current in drafts else 0
    while True:
        ov = curses.newwin(ov_h, ov_w, ov_y, ov_x)
        ov.keypad(True)
        ov.erase()
        ov.border()
        try:
            ov.addstr(0, 2, " Drafts ", curses.color_pair(pair_bright))
        except curses.error:
            pass
        inner = ov_h - 2
        scroll = max(0, sel - inner + 1) if sel >= inner else 0
        for i in range(inner):
            idx = i + scroll
            if idx >= len(drafts):
                break
            name = drafts[idx]
            disp = name[:ov_w - 4]
            try:
                if idx == sel:
                    ov.addstr(i + 1, 1, f" {disp:<{ov_w-4}} ", curses.color_pair(pair_hl))
                else:
                    ov.addstr(i + 1, 1, f" {disp:<{ov_w-4}} ")
            except curses.error:
                pass
        ov.refresh()
        ch = ov.getch()
        if ch == curses.KEY_UP:
            sel = max(0, sel - 1)
        elif ch == curses.KEY_DOWN:
            sel = min(len(drafts) - 1, sel + 1)
        elif ch in (curses.KEY_ENTER, 10, 13):
            return drafts[sel]
        elif ch in (27, 17):
            return None


# ── Main curses app ───────────────────────────────────────────────────────────

def run_app(stdscr, draft_name, font_size):
    ensure_dir(DRAFTS_DIR)

    curses.raw()
    curses.noecho()
    stdscr.keypad(True)
    curses.curs_set(0)
    curses.start_color()
    curses.use_default_colors()

    # Register 256-color pairs for each fade level (pairs 1..FADE_LEVELS)
    # Pair index 1 = current line (brightest), pair FADE_LEVELS = oldest (darkest)
    for i, color_num in enumerate(FADE_COLORS):
        try:
            curses.init_pair(i + 1, color_num, -1)
        except curses.error:
            # Fall back to COLOR_GREEN if 256 colors unavailable
            curses.init_pair(i + 1, curses.COLOR_GREEN, -1)

    PAIR_BRIGHT = 1                                    # current line
    PAIR_HL     = curses.color_pair(1) | curses.A_REVERSE   # highlight/selected

    # ── State ─────────────────────────────────────────────────────────────
    current_draft = draft_name
    content       = read_draft(current_draft) if current_draft else ""

    # Split content into a list of paragraphs (logical lines).
    # Each Enter = new paragraph.
    paragraphs    = content.split("\n") if content else [""]
    paragraphs    = paragraphs or [""]

    # cursor is always on the LAST paragraph while typing;
    # col = position within that paragraph
    cur_para      = len(paragraphs) - 1
    cur_col       = len(paragraphs[cur_para])

    def autosave():
        if current_draft:
            write_draft(current_draft, "\n".join(paragraphs))

    # ── Main draw loop ────────────────────────────────────────────────────
    while True:
        sh, sw = stdscr.getmaxyx()

        # Text column: centered, max 70 chars wide
        text_w  = min(70, sw - 8)
        text_x  = (sw - text_w) // 2

        # Vertical center row for the current (active) line
        center_y = sh // 2

        stdscr.erase()

        # ── Build the display lines ───────────────────────────────────────
        # We need to show the current paragraph being typed, and up to
        # FADE_LEVELS-1 previous visual lines fading upward.

        # Wrap the current paragraph to get all its visual lines
        cur_text        = paragraphs[cur_para]
        cur_wrapped     = wrap_paragraph(cur_text, text_w)

        # Which visual line within cur_wrapped is the cursor on?
        # Find it by col position
        cur_vis_line    = 0
        col_remaining   = cur_col
        for vi, seg in enumerate(cur_wrapped):
            if col_remaining <= len(seg):
                cur_vis_line = vi
                break
            col_remaining -= len(seg)
        else:
            cur_vis_line = len(cur_wrapped) - 1

        cur_vis_col = cur_col - sum(len(cur_wrapped[i])
                                    for i in range(cur_vis_line))

        # Collect all visual lines that will be shown above the cursor line,
        # going backward through paragraphs.
        # We want FADE_LEVELS-1 lines above (indices 1..FADE_LEVELS-1 in fade).
        needed_above = FADE_LEVELS - 1   # 4 lines
        above_lines  = []                # list of (text, fade_index) bottom-to-top

        # First: visual lines in current paragraph above cur_vis_line
        for vi in range(cur_vis_line - 1, -1, -1):
            above_lines.append(cur_wrapped[vi])
            if len(above_lines) >= needed_above:
                break

        # Then: previous paragraphs
        if len(above_lines) < needed_above:
            for pi in range(cur_para - 1, -1, -1):
                wrapped = wrap_paragraph(paragraphs[pi], text_w)
                for vi in range(len(wrapped) - 1, -1, -1):
                    above_lines.append(wrapped[vi])
                    if len(above_lines) >= needed_above:
                        break
                if len(above_lines) >= needed_above:
                    break

        # above_lines[0] = line immediately above cursor, [1] = two above, etc.
        # Draw them fading upward from center_y - 1
        for i, line in enumerate(above_lines):
            y = center_y - 1 - i
            if y < 0:
                break
            fade_idx = i + 1   # fade pair index (1=bright..FADE_LEVELS=dark)
            fade_idx = min(fade_idx, FADE_LEVELS)
            attr = curses.color_pair(fade_idx)
            if fade_idx >= FADE_LEVELS:
                attr |= curses.A_DIM
            disp = line[:text_w]
            x    = text_x + (text_w - len(disp)) // 2  # center the text
            try:
                stdscr.addstr(y, x, disp, attr)
            except curses.error:
                pass

        # ── Current (active) line ─────────────────────────────────────────
        active_seg  = cur_wrapped[cur_vis_line]
        active_attr = curses.color_pair(PAIR_BRIGHT) | curses.A_BOLD
        disp        = active_seg[:text_w]
        x           = text_x + (text_w - max(len(disp), 1)) // 2

        try:
            stdscr.addstr(center_y, x, disp if disp else " ", active_attr)
        except curses.error:
            pass

        # ── Cursor cell ───────────────────────────────────────────────────
        cursor_x    = x + cur_vis_col
        cursor_char = (active_seg[cur_vis_col]
                       if cur_vis_col < len(active_seg) else " ")
        curses.curs_set(2)
        try:
            stdscr.addstr(center_y, cursor_x, cursor_char,
                          curses.color_pair(1) | curses.A_REVERSE | curses.A_BOLD)
            stdscr.move(center_y, cursor_x)
        except curses.error:
            pass

        # ── Status line (very dim, bottom of screen) ──────────────────────
        words = len(" ".join(paragraphs).split()) if any(paragraphs) else 0
        chars = sum(len(p) for p in paragraphs)
        draft_label = current_draft or "(no draft)"
        status = f" {draft_label}  |  {words}w  {chars}c  |  Ctrl+N: new  Ctrl+D: drafts  Ctrl+Q: quit "
        try:
            stdscr.addstr(sh - 1, max(0, (sw - len(status)) // 2),
                          status[:sw - 1],
                          curses.color_pair(3) | curses.A_DIM)
        except curses.error:
            pass

        stdscr.refresh()

        # ── Input ─────────────────────────────────────────────────────────
        ch = stdscr.getch()

        if ch == 17:            # Ctrl+Q — save & quit
            autosave()
            break

        elif ch == 19:          # Ctrl+S — save
            autosave()


        elif ch == 4:           # Ctrl+D — draft picker
            drafts = get_drafts()
            choice = pick_draft(stdscr, drafts, current_draft,
                                PAIR_BRIGHT, PAIR_BRIGHT)
            if choice and choice != current_draft:
                autosave()
                current_draft = choice
                content       = read_draft(current_draft)
                paragraphs    = content.split("\n") if content else [""]
                paragraphs    = paragraphs or [""]
                cur_para      = len(paragraphs) - 1
                cur_col       = len(paragraphs[cur_para])

        elif ch == 14:          # Ctrl+N — new draft
            name = centered_prompt(stdscr, "New draft name:", PAIR_BRIGHT)
            if name:
                s = safe_name(name)
                if not os.path.exists(draft_path(s)):
                    write_draft(s, "")
                autosave()
                current_draft = s
                content       = read_draft(s)
                paragraphs    = content.split("\n") if content else [""]
                paragraphs    = paragraphs or [""]
                cur_para      = len(paragraphs) - 1
                cur_col       = len(paragraphs[cur_para])

        # ── Cursor movement ───────────────────────────────────────────────
        # Font resizing: use Kitty shortcuts Ctrl+Shift+Equal / Ctrl+Shift+Minus

        elif ch == curses.KEY_LEFT:
            if cur_col > 0:
                cur_col -= 1
            elif cur_para > 0:
                cur_para -= 1
                cur_col   = len(paragraphs[cur_para])

        elif ch == curses.KEY_RIGHT:
            if cur_col < len(paragraphs[cur_para]):
                cur_col += 1
            elif cur_para < len(paragraphs) - 1:
                cur_para += 1
                cur_col   = 0

        elif ch == curses.KEY_UP:
            if cur_vis_line > 0:
                # Move up within current paragraph's visual lines
                target_vi   = cur_vis_line - 1
                col_before  = sum(len(cur_wrapped[i]) for i in range(target_vi))
                seg_len     = len(cur_wrapped[target_vi])
                cur_col     = col_before + min(cur_vis_col, seg_len)
            elif cur_para > 0:
                cur_para   -= 1
                prev_wrap   = wrap_paragraph(paragraphs[cur_para], text_w)
                last_vi     = len(prev_wrap) - 1
                col_before  = sum(len(prev_wrap[i]) for i in range(last_vi))
                seg_len     = len(prev_wrap[last_vi])
                cur_col     = col_before + min(cur_vis_col, seg_len)

        elif ch == curses.KEY_DOWN:
            if cur_vis_line < len(cur_wrapped) - 1:
                target_vi   = cur_vis_line + 1
                col_before  = sum(len(cur_wrapped[i]) for i in range(target_vi))
                seg_len     = len(cur_wrapped[target_vi])
                cur_col     = col_before + min(cur_vis_col, seg_len)
            elif cur_para < len(paragraphs) - 1:
                cur_para   += 1
                next_wrap   = wrap_paragraph(paragraphs[cur_para], text_w)
                seg_len     = len(next_wrap[0])
                cur_col     = min(cur_vis_col, seg_len)

        elif ch == curses.KEY_HOME:
            col_before = sum(len(cur_wrapped[i]) for i in range(cur_vis_line))
            cur_col    = col_before

        elif ch == curses.KEY_END:
            col_before = sum(len(cur_wrapped[i]) for i in range(cur_vis_line))
            cur_col    = col_before + len(cur_wrapped[cur_vis_line])

        # ── Editing ───────────────────────────────────────────────────────

        elif ch in (curses.KEY_BACKSPACE, 127, 8):
            p = paragraphs[cur_para]
            if cur_col > 0:
                paragraphs[cur_para] = p[:cur_col - 1] + p[cur_col:]
                cur_col -= 1
            elif cur_para > 0:
                prev        = paragraphs[cur_para - 1]
                cur_col     = len(prev)
                paragraphs[cur_para - 1] = prev + p
                paragraphs.pop(cur_para)
                cur_para   -= 1
            autosave()

        elif ch == curses.KEY_DC:
            p = paragraphs[cur_para]
            if cur_col < len(p):
                paragraphs[cur_para] = p[:cur_col] + p[cur_col + 1:]
            elif cur_para < len(paragraphs) - 1:
                paragraphs[cur_para] = p + paragraphs[cur_para + 1]
                paragraphs.pop(cur_para + 1)
            autosave()

        elif ch in (curses.KEY_ENTER, 10, 13):
            p    = paragraphs[cur_para]
            tail = p[cur_col:]
            paragraphs[cur_para] = p[:cur_col]
            cur_para += 1
            paragraphs.insert(cur_para, tail)
            cur_col = 0
            autosave()

        elif 32 <= ch <= 126:
            p = paragraphs[cur_para]
            paragraphs[cur_para] = p[:cur_col] + chr(ch) + p[cur_col:]
            cur_col += 1
            autosave()


# ── Entry point ───────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="nu_flow — focused writing mode")
    parser.add_argument("--font",   type=int, default=None,
                        help="Font size")
    parser.add_argument("--draft",  type=str, default=None,
                        help="Draft name to open")
    parser.add_argument("--launch", action="store_true",
                        help="Open a dedicated Kitty window and exit")
    args = parser.parse_args()

    ensure_dir(DRAFTS_DIR)

    font_size = args.font if args.font else load_font_size()

    # Pick a draft to open
    if args.draft:
        draft_name = args.draft
        if not os.path.exists(draft_path(draft_name)):
            write_draft(draft_name, "")
    else:
        drafts = get_drafts()
        if drafts:
            draft_name = drafts[0]
        else:
            draft_name = "draft"
            write_draft(draft_name, "")

    # --launch: spawn a dedicated Kitty window and exit this process
    if args.launch:
        launch_in_kitty(font_size, draft_name)
        return

    try:
        curses.wrapper(run_app, draft_name, font_size)
    except KeyboardInterrupt:
        pass

    print(f"nu_flow closed. Draft saved to ~/nu_drafts/{draft_name}.txt")


if __name__ == "__main__":
    main()
