'''E2E テスト専用の使い捨て入力先。InputGhost の CI でだけ使う。

python e2e_target.py <info_file> <text_file> [paste_delay_ms]

起動したら自分の window handle と PID を info_file に書き、
受け取った文字を text_file に書き続ける。60 秒たったら自分で終了する。
paste_delay_ms を渡すと、Ctrl+V を受けてから clipboard を読むまで UI thread を
その時間止める (処理の遅いアプリのまね)。'''

import json
import os
import sys
import time
import tkinter

LIFETIME_MS = 60000
SAVE_INTERVAL_MS = 100


def write_atomically(path, text):
    with open(path + '.tmp', 'w', encoding='utf-8') as f:
        f.write(text)
    os.replace(path + '.tmp', path)


def main(info_file, text_file, paste_delay_ms=0):
    root = tkinter.Tk()
    root.title('InputGhost E2E target')
    root.geometry('400x200')
    box = tkinter.Text(root)
    box.pack(fill='both', expand=True)
    box.focus_set()
    if paste_delay_ms:
        # class の <<Paste>> (clipboard を読む処理) より先に呼ばれる。
        box.bind('<<Paste>>', lambda event: time.sleep(paste_delay_ms / 1000))

    saved = [None]

    def save():
        text = box.get('1.0', 'end-1c')
        if text != saved[0]:
            try:
                write_atomically(text_file, text)
                saved[0] = text
            except PermissionError:
                # テスト側が読んでいる最中だと Windows では置き換えられない。次の回に書く。
                pass
        root.after(SAVE_INTERVAL_MS, save)

    root.update()
    save()
    # wm_frame() は GetForegroundWindow が返す top-level window の handle。
    write_atomically(info_file, json.dumps(
        {'hwnd': int(root.wm_frame(), 16), 'pid': os.getpid()}))
    root.after(LIFETIME_MS, root.destroy)
    root.mainloop()


if __name__ == '__main__':
    main(sys.argv[1], sys.argv[2], *map(int, sys.argv[3:]))
