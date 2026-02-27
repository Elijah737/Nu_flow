#!/usr/bin/env python3
"""
nu_flow_tty — focused single-line writer for the raw Linux console (TTY)

Designed to run directly on a virtual terminal (Ctrl+Alt+F2 etc.)
with no X11 or terminal emulator required. Uses only the 8 basic
colors that every Linux TTY supports.

One line of text is shown at a time, centered on screen.
All other lines are invisible — just you and the current sentence.

Controls:
  Arrow keys          move cursor / navigate paragraphs
  Home / End          start / end of line
  Enter               new paragraph
  Backspace / Delete  edit text
  Ctrl+N              new draft
  Ctrl+D              open draft picker
  Ctrl+S              save
  Ctrl+Q              save & quit

Shares ~/nu_drafts/ with nu_draft and nu_flow.
"""

import curses
import os
import argparse
import textwrap

DRAFTS_DIR = os.path.expanduser("~/nu_drafts")


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


# ── Word wrap ─────────────────────────────────────────────────────────────────

def wrap_paragraph(text, width):
    if not text:
        return [""]
    return textwrap.wrap(text, width,
                         drop_whitespace=False,
                         break_long_words=True,
                         break_on_hyphens=False) or [""]


# ── UI helpers ────────────────────────────────────────────────────────────────

def centered_prompt(stdscr, prompt, attr, max_len=60):
    """Simple centered input dialog using only basic attributes."""
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
            win.addstr(1, 2, prompt[:bw - 4], attr)
            win.addstr(2, 2, "-" * (bw - 4))
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


def pick_draft(stdscr, drafts, current, attr, hl_attr):
    """Floating draft picker using basic colors."""
    if not drafts:
        return None
    sh, sw = stdscr.getmaxyx()
    ov_w   = min(44, sw - 4)
    ov_h   = min(len(drafts) + 2, sh - 4, 18)
    ov_y   = (sh - ov_h) // 2
    ov_x   = (sw - ov_w) // 2
    sel    = drafts.index(current) if current in drafts else 0
    while True:
        ov = curses.newwin(ov_h, ov_w, ov_y, ov_x)
        ov.keypad(True)
        ov.erase()
        ov.border()
        try:
            ov.addstr(0, 2, " Drafts ", attr)
        except curses.error:
            pass
        inner  = ov_h - 2
        scroll = max(0, sel - inner + 1) if sel >= inner else 0
        for i in range(inner):
            idx = i + scroll
            if idx >= len(drafts):
                break
            name = drafts[idx]
            disp = name[:ov_w - 4]
            try:
                if idx == sel:
                    ov.addstr(i + 1, 1, f" {disp:<{ov_w-4}} ", hl_attr)
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


# ── Main ──────────────────────────────────────────────────────────────────────

def run_app(stdscr, draft_name):
    ensure_dir(DRAFTS_DIR)

    curses.raw()
    curses.noecho()
    stdscr.keypad(True)
    curses.curs_set(0)
    curses.start_color()
    curses.use_default_colors()

    # Basic 8-color setup — works on every Linux TTY
    # Pair 1: bright green on black  — active line
    # Pair 2: black on green         — cursor / highlight
    # Pair 3: dim white on black     — status bar
    curses.init_pair(1, curses.COLOR_GREEN, -1)
    curses.init_pair(2, curses.COLOR_BLACK, curses.COLOR_GREEN)
    curses.init_pair(3, curses.COLOR_WHITE, -1)

    ATTR_ACTIVE = curses.color_pair(1) | curses.A_BOLD
    ATTR_CURSOR = curses.color_pair(2) | curses.A_BOLD
    ATTR_STATUS = curses.color_pair(3) | curses.A_DIM
    ATTR_LABEL  = curses.color_pair(1) | curses.A_BOLD
    ATTR_HL     = curses.color_pair(2) | curses.A_BOLD

    # ── State ─────────────────────────────────────────────────────────────
    current_draft = draft_name
    content       = read_draft(current_draft) if current_draft else ""
    paragraphs    = content.split("\n") if content else [""]
    paragraphs    = paragraphs or [""]
    cur_para      = len(paragraphs) - 1
    cur_col       = len(paragraphs[cur_para])

    def autosave():
        if current_draft:
            write_draft(current_draft, "\n".join(paragraphs))

    def switch_to(name):
        nonlocal current_draft, content, paragraphs, cur_para, cur_col
        autosave()
        current_draft = name
        content       = read_draft(name)
        paragraphs    = content.split("\n") if content else [""]
        paragraphs    = paragraphs or [""]
        cur_para      = len(paragraphs) - 1
        cur_col       = len(paragraphs[cur_para])

    # ── Main loop ─────────────────────────────────────────────────────────
    while True:
        sh, sw = stdscr.getmaxyx()

        # Text width: leave generous margins on each side
        text_w  = min(70, sw - 8)
        text_x  = (sw - text_w) // 2
        center_y = sh // 2

        # Wrap current paragraph
        cur_text    = paragraphs[cur_para]
        cur_wrapped = wrap_paragraph(cur_text, text_w)

        # Find which visual line and x offset the cursor is on
        cur_vis_line = 0
        col_remaining = cur_col
        for vi, seg in enumerate(cur_wrapped):
            if col_remaining <= len(seg):
                cur_vis_line = vi
                break
            col_remaining -= len(seg)
        else:
            cur_vis_line = len(cur_wrapped) - 1

        cur_vis_col = cur_col - sum(len(cur_wrapped[i])
                                    for i in range(cur_vis_line))

        # ── Draw ──────────────────────────────────────────────────────────
        stdscr.erase()

        # Active line — centered horizontally and vertically
        active_seg = cur_wrapped[cur_vis_line]
        disp       = active_seg[:text_w]
        x          = text_x + (text_w - max(len(disp), 1)) // 2
        try:
            stdscr.addstr(center_y, x, disp if disp else " ", ATTR_ACTIVE)
        except curses.error:
            pass

        # Cursor cell
        cursor_x    = x + cur_vis_col
        cursor_char = (active_seg[cur_vis_col]
                       if cur_vis_col < len(active_seg) else " ")
        curses.curs_set(2)
        try:
            stdscr.addstr(center_y, cursor_x, cursor_char, ATTR_CURSOR)
            stdscr.move(center_y, cursor_x)
        except curses.error:
            pass

        # Status bar — very dim, bottom of screen
        words  = len(" ".join(paragraphs).split()) if any(paragraphs) else 0
        chars  = sum(len(p) for p in paragraphs)
        label  = current_draft or "(no draft)"
        status = f" {label}  |  {words}w  {chars}c  |  Ctrl+N: new  Ctrl+D: drafts  Ctrl+Q: quit "
        try:
            stdscr.addstr(sh - 1,
                          max(0, (sw - len(status)) // 2),
                          status[:sw - 1],
                          ATTR_STATUS)
        except curses.error:
            pass

        stdscr.refresh()

        # ── Input ─────────────────────────────────────────────────────────
        ch = stdscr.getch()

        if ch == 17:                    # Ctrl+Q — save & quit
            autosave()
            break

        elif ch == 19:                  # Ctrl+S — save
            autosave()

        elif ch == 4:                   # Ctrl+D — draft picker
            drafts = get_drafts()
            choice = pick_draft(stdscr, drafts, current_draft,
                                ATTR_LABEL, ATTR_HL)
            if choice and choice != current_draft:
                switch_to(choice)

        elif ch == 14:                  # Ctrl+N — new draft
            name = centered_prompt(stdscr, "New draft name:", ATTR_LABEL)
            if name:
                s = safe_name(name)
                if not os.path.exists(draft_path(s)):
                    write_draft(s, "")
                switch_to(s)

        # ── Cursor movement ───────────────────────────────────────────────

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
                target_vi  = cur_vis_line - 1
                col_before = sum(len(cur_wrapped[i]) for i in range(target_vi))
                seg_len    = len(cur_wrapped[target_vi])
                cur_col    = col_before + min(cur_vis_col, seg_len)
            elif cur_para > 0:
                cur_para  -= 1
                prev_wrap  = wrap_paragraph(paragraphs[cur_para], text_w)
                last_vi    = len(prev_wrap) - 1
                col_before = sum(len(prev_wrap[i]) for i in range(last_vi))
                seg_len    = len(prev_wrap[last_vi])
                cur_col    = col_before + min(cur_vis_col, seg_len)

        elif ch == curses.KEY_DOWN:
            if cur_vis_line < len(cur_wrapped) - 1:
                target_vi  = cur_vis_line + 1
                col_before = sum(len(cur_wrapped[i]) for i in range(target_vi))
                seg_len    = len(cur_wrapped[target_vi])
                cur_col    = col_before + min(cur_vis_col, seg_len)
            elif cur_para < len(paragraphs) - 1:
                cur_para  += 1
                next_wrap  = wrap_paragraph(paragraphs[cur_para], text_w)
                seg_len    = len(next_wrap[0])
                cur_col    = min(cur_vis_col, seg_len)

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
                prev     = paragraphs[cur_para - 1]
                cur_col  = len(prev)
                paragraphs[cur_para - 1] = prev + p
                paragraphs.pop(cur_para)
                cur_para -= 1
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
    parser = argparse.ArgumentParser(
        description="nu_flow_tty — focused writer for the Linux console")
    parser.add_argument("--draft", type=str, default=None,
                        help="Draft name to open")
    args = parser.parse_args()

    ensure_dir(DRAFTS_DIR)

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

    try:
        curses.wrapper(run_app, draft_name)
    except KeyboardInterrupt:
        pass

    print(f"nu_flow_tty closed. Draft saved to ~/nu_drafts/{draft_name}.txt")


if __name__ == "__main__":
    main()
