'''E2E テストの道具。本物の Win32 を触るのは GitHub-hosted の Windows runner の中だけ。'''

import contextlib
import ctypes
import json
import os
import pathlib
import signal
import subprocess
import sys
import time

REPO = pathlib.Path(__file__).resolve().parent.parent
TARGET_SCRIPT = pathlib.Path(__file__).resolve().parent / 'e2e_target.py'
SLEEPER_SCRIPT = pathlib.Path(__file__).resolve().parent / 'e2e_sleeper.py'
LAUNCHER_SCRIPT = pathlib.Path(__file__).resolve().parent / 'e2e_launcher.py'
# 使い捨ての process は console を作らない pythonw で動かす (余計な window が前面に来ない)。
PYTHONW = pathlib.Path(sys.executable).with_name('pythonw.exe')

# InputGhost を別 process で動かす。止められなかったら kill できるように。
DRIVER = '''
import sys
import InputGhost
ghost = InputGhost.InputGhost
ghost._TEXT_FILE_NAME = sys.argv[1]
ghost._KEY_ORDER = tuple(sys.argv[2].split(','))
ghost._WAIT_TIME = float(sys.argv[3])
ghost._READY_TIME = 3
if len(sys.argv) > 4:
    # 起動 mode: カウントダウンの代わりに入力先を起動して待つ。
    ghost._READY_TIME = False
    ghost._TARGET_APPLICATION = sys.argv[4]
    ghost._LAUNCH_TIMEOUT = float(sys.argv[5])
sys.exit(InputGhost.main([]))
'''


def e2e_enabled(platform, environ):
    '''GitHub-hosted の Windows runner で INPUTGHOST_E2E=1 のときだけ True。'''

    return (platform == 'win32'
            and environ.get('INPUTGHOST_E2E') == '1'
            and environ.get('GITHUB_ACTIONS') == 'true'
            and environ.get('RUNNER_ENVIRONMENT') == 'github-hosted')


def wait_until(condition, seconds):
    deadline = time.monotonic() + seconds
    while not condition():
        if time.monotonic() >= deadline:
            return False
        time.sleep(0.05)
    return True


def killPid(pid):
    try:
        os.kill(pid, signal.SIGTERM)
    except OSError:
        pass


class Target:
    '''使い捨ての入力先 window。with を抜けたら必ず終了させる。

    launch=False なら自分では起動せず、ほかの process (InputGhost) が commandLine()
    で起動したものが info_file を書くのを待って使う。'''

    def __init__(self, directory, name, pasteDelayMs=0, launch=True):
        self.pasteDelayMs = pasteDelayMs
        self.launch = launch
        self.infoFile = directory / f'{name}.json'
        self.textFile = directory / f'{name}.txt'
        self.process = None
        self.hwnd = None
        self.pid = None

    def command(self):
        return [str(PYTHONW), str(TARGET_SCRIPT),
                str(self.infoFile), str(self.textFile), str(self.pasteDelayMs)]

    def commandLine(self):
        return subprocess.list2cmdline(self.command())

    def __enter__(self):
        if self.launch:
            self.process = subprocess.Popen(self.command())
        try:
            return self._identify()
        except BaseException:
            self.__exit__()
            raise

    def _identify(self):
        if not wait_until(self.infoFile.exists, 20):
            raise RuntimeError('E2E target did not start; nothing was sent.')
        info = json.loads(self.infoFile.read_text(encoding='utf-8'))
        self.hwnd, self.pid = info['hwnd'], info['pid']

        # handle が本当にこの target の window か、title ではなく PID で確かめる。
        owner = ctypes.c_ulong()
        ctypes.windll.user32.GetWindowThreadProcessId(
            self.hwnd, ctypes.byref(owner))
        if owner.value != self.pid:
            raise RuntimeError('E2E target window could not be identified.')
        return self

    def __exit__(self, *exc):
        # 自分で 60 秒後に終了もするけど、ここで必ず止める。
        if self.pid is not None:
            killPid(self.pid)
        if self.process is not None:
            self.process.kill()
            self.process.wait(timeout=10)

    def text(self):
        # target は 100ms ごとに保存するので、少し待ってから読む。
        time.sleep(0.5)
        return self.textFile.read_text(encoding='utf-8')

    def bringToFront(self):
        '''1 秒以内に前面にできなければ False。そのときは何も入力させないこと。'''

        # 前面でない process の SetForegroundWindow は foreground lock で断られるので、
        # 今の前面の thread に一時的に入力 queue をつないでから呼ぶ。key は送らない。
        user32 = ctypes.windll.user32
        me = ctypes.windll.kernel32.GetCurrentThreadId()
        front = user32.GetWindowThreadProcessId(user32.GetForegroundWindow(), None)
        attached = front not in (0, me) and user32.AttachThreadInput(me, front, True)
        try:
            user32.BringWindowToTop(self.hwnd)
            user32.SetForegroundWindow(self.hwnd)
        finally:
            if attached:
                user32.AttachThreadInput(me, front, False)
        return wait_until(lambda: user32.GetForegroundWindow() == self.hwnd, 1)


# runner の clipboard に置く、文字列ではない独自の形式の名前。
NON_TEXT_FORMAT_NAME = 'InputGhost.E2E.SyntheticNonText'


def clipboardApi():
    '''clipboard を直接触るための user32・kernel32。handle は pointer の大きさで受け取る。'''

    user32 = ctypes.WinDLL('user32')
    kernel32 = ctypes.WinDLL('kernel32')
    handle = ctypes.c_void_p
    user32.CreateWindowExW.restype = handle
    user32.CreateWindowExW.argtypes = (
        [ctypes.c_uint32, ctypes.c_wchar_p, ctypes.c_wchar_p, ctypes.c_uint32]
        + [ctypes.c_int] * 4 + [handle] * 4)
    user32.DestroyWindow.argtypes = [handle]
    user32.OpenClipboard.argtypes = [handle]
    user32.RegisterClipboardFormatW.argtypes = [ctypes.c_wchar_p]
    user32.RegisterClipboardFormatW.restype = ctypes.c_uint32
    user32.SetClipboardData.argtypes = [ctypes.c_uint32, handle]
    user32.SetClipboardData.restype = handle
    user32.GetClipboardData.argtypes = [ctypes.c_uint32]
    user32.GetClipboardData.restype = handle
    user32.EnumClipboardFormats.argtypes = [ctypes.c_uint32]
    user32.EnumClipboardFormats.restype = ctypes.c_uint32
    user32.GetClipboardSequenceNumber.restype = ctypes.c_uint32
    kernel32.GlobalAlloc.argtypes = [ctypes.c_uint32, ctypes.c_size_t]
    kernel32.GlobalAlloc.restype = handle
    kernel32.GlobalLock.argtypes = [handle]
    kernel32.GlobalLock.restype = handle
    kernel32.GlobalUnlock.argtypes = [handle]
    kernel32.GlobalSize.argtypes = [handle]
    kernel32.GlobalSize.restype = ctypes.c_size_t
    kernel32.GlobalFree.argtypes = [handle]
    return user32, kernel32


@contextlib.contextmanager
def openClipboard(user32, owner=None):
    # ほかの process が開いていることもあるので、少しだけ待つ。
    if not wait_until(lambda: user32.OpenClipboard(owner), 2):
        raise RuntimeError('Could not open the clipboard.')
    try:
        yield
    finally:
        user32.CloseClipboard()


def putNonTextClipboard(payload):
    '''runner の clipboard を、独自の形式 1 つ (中身は payload) だけにする。形式の番号を返す。'''

    user32, kernel32 = clipboardApi()
    clipboardFormat = user32.RegisterClipboardFormatW(NON_TEXT_FORMAT_NAME)
    # SetClipboardData には持ち主の window が要るので、見えない window を作る。
    owner = user32.CreateWindowExW(0, 'STATIC', None, 0, 0, 0, 0, 0, None, None, None, None)
    if not clipboardFormat or not owner:
        raise RuntimeError('Could not prepare the non-text clipboard.')
    try:
        with openClipboard(user32, owner):
            user32.EmptyClipboard()
            memory = kernel32.GlobalAlloc(0x0002, len(payload))  # GMEM_MOVEABLE
            ctypes.memmove(kernel32.GlobalLock(memory), payload, len(payload))
            kernel32.GlobalUnlock(memory)
            if not user32.SetClipboardData(clipboardFormat, memory):
                kernel32.GlobalFree(memory)
                raise RuntimeError('SetClipboardData failed.')
    finally:
        user32.DestroyWindow(owner)
    return clipboardFormat


def readClipboard(clipboardFormat):
    '''(clipboard にある形式の一覧, clipboardFormat の中身の byte) を返す。'''

    user32, kernel32 = clipboardApi()
    with openClipboard(user32):
        formats = []
        current = user32.EnumClipboardFormats(0)
        while current:
            formats.append(current)
            current = user32.EnumClipboardFormats(current)
        data = None
        memory = user32.GetClipboardData(clipboardFormat)
        if memory:
            data = ctypes.string_at(kernel32.GlobalLock(memory), kernel32.GlobalSize(memory))
            kernel32.GlobalUnlock(memory)
    return formats, data


def clipboardSequence():
    '''clipboard が書き換えられるたびに増える番号 (同じ中身を書き直しても増える)。'''

    return clipboardApi()[0].GetClipboardSequenceNumber()


def startInputGhost(textFile, keyOrder, waitTime, launch=None):
    '''InputGhost を READY_TIME=3 で起動し、起動元 window を記録した後 (最初の表示) まで待つ。

    launch=(コマンドライン, LAUNCH_TIMEOUT) なら、カウントダウンの代わりにそれを起動させる。'''

    env = {**os.environ, 'PYTHONIOENCODING': 'utf-8'}
    extra = [launch[0], str(launch[1])] if launch else []
    process = subprocess.Popen(
        [sys.executable, '-u', '-c', DRIVER,
         str(textFile), ','.join(keyOrder), str(waitTime), *extra],
        cwd=REPO, env=env, text=True, encoding='utf-8',
        stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    # 最初のカウントダウン表示は、起動元 window を記録した 1 秒後に出る。
    # 起動 mode では、起動したものが書くファイルで待ち合わせる。
    if not launch and process.stdout.readline().strip() != '3':
        process.kill()
        raise RuntimeError('InputGhost did not start its countdown.')
    return process
