#!/usr/bin/env python
# coding: utf-8

'''InputGhost

文章を別のアプリケーションに一行ずつコピペしていく
という限られた行動を自動実行してくれるツール。
windows専用。

========================================
バージョン1.1
    同じ文字列が連続で入力されてしまう問題に対応。
    Ctrl+Vのところでは、CtrlだけじゃなくVも一度離さないとダメ。
    だったらついでにと押したキーは全部離すよう明記した。
バージョン1.2
    コピー・ペースト間の待機秒数をセッティングファイルしか指定できるようにした。
    対象の人のPCでうまく動かなかったから……。
バージョン1.3(2017-08-21)
    自動入力実行前に待機することができるようにした。
バージョン1.4
    --dry-run で、入力せずに予定の操作を表示するだけにできるようにした。
    KEY_ORDER の誤りは入力を始める前に検出するようにした。
バージョン1.5
    クリップボードがいつまでも変わらないと無限に待っていたので、CLIPBOARD_TIMEOUT 秒で止めるようにした。
バージョン1.6
    前面の window を入力先として記録し、起動元のままだったり途中で変わったりしたら止めるようにした。
バージョン1.7
    Ctrl+V の直後に次の行をコピーすると、遅いアプリが次の行を貼っちゃうので、PASTE_SETTLE_TIME 秒あけるようにした。
バージョン1.8
    実行前のクリップボードの文字列を、終わったときも途中で止まったときも元に戻すようにした。
    文字列のないクリップボード(画像やファイル)は戻せないので、何も送らずに止まる。
バージョン1.9
    古い keybd_event をやめて、1 つの操作の key を SendInput でまとめて送るようにした。
    Windows が全部を受け付けなかったら、押したままの key を離して止まる。
バージョン1.10
    READY_TIME = False のとき、shell を通さずに起動して、起動したアプリの window が
    前面に来るまで LAUNCH_TIMEOUT 秒まで待つようにした (前は決め打ちで 1 秒)。
    前からある別の window は使わない。
バージョン1.11
    テキストファイルを cp932 決め打ちで読むのをやめた。BOM・ASCII・UTF-8 と cp932 の
    どちらで読めるかで決めて、どっちでも読めて中身が変わるときは決めつけずに止まる。
    TEXT_ENCODING で文字コードを指定できる。
'''


import argparse
import codecs
import ctypes
import ntpath
import subprocess
import sys
import time
import pyperclip
import InputGhostSetting
import begin_set


# SendInput に渡す構造体。union には一番大きい MOUSEINPUT も入れないと、
# INPUT の大きさが Windows の期待とずれて、SendInput が全部断ります。
class KEYBDINPUT(ctypes.Structure):
    _fields_ = [('wVk', ctypes.c_uint16), ('wScan', ctypes.c_uint16),
                ('dwFlags', ctypes.c_uint32), ('time', ctypes.c_uint32),
                ('dwExtraInfo', ctypes.c_size_t)]


class MOUSEINPUT(ctypes.Structure):
    _fields_ = [('dx', ctypes.c_int32), ('dy', ctypes.c_int32),
                ('mouseData', ctypes.c_uint32), ('dwFlags', ctypes.c_uint32),
                ('time', ctypes.c_uint32), ('dwExtraInfo', ctypes.c_size_t)]


class INPUTUNION(ctypes.Union):
    _fields_ = [('ki', KEYBDINPUT), ('mi', MOUSEINPUT)]


class INPUT(ctypes.Structure):
    _fields_ = [('type', ctypes.c_uint32), ('u', INPUTUNION)]


INPUT_KEYBOARD = 1
KEYEVENTF_KEYUP = 0x2


class InputGhost:
    ''' ～(m´□｀)m < ｶﾀｶﾀｶﾀｶﾀ '''

    # テキストファイルの名前。
    _TEXT_FILE_NAME = InputGhostSetting.TEXT_FILE_NAME
    # テキストファイルの文字コード。'auto' か文字コードの名前。
    _TEXT_ENCODING = InputGhostSetting.TEXT_ENCODING
    # BOM と、そのとき使う文字コード・表示する名前。
    _BOMS = ((codecs.BOM_UTF8, 'utf-8-sig', 'utf-8 (BOM)'),
             (codecs.BOM_UTF16_LE, 'utf-16', 'utf-16 (BOM)'),
             (codecs.BOM_UTF16_BE, 'utf-16', 'utf-16 (BOM)'))
    # 一行何文字で区切る?
    _NUM_CHARA_IN_ROW = InputGhostSetting.NUM_CHARA_IN_ROW
    # 対象アプリケーションの名前。
    _TARGET_APPLICATION = InputGhostSetting.TARGET_APPLICATION
    # 行動の順番。
    _KEY_ORDER = InputGhostSetting.KEY_ORDER
    # コピペ時の待機秒数。
    _WAIT_TIME = InputGhostSetting.WAIT_TIME
    # クリップボード待ちの最大秒数と確認間隔。
    _CLIPBOARD_TIMEOUT = InputGhostSetting.CLIPBOARD_TIMEOUT
    _CLIPBOARD_INTERVAL = 0.1
    # Ctrl+V のあと、次にクリップボードを書き換えるまで空ける秒数。
    _PASTE_SETTLE_TIME = InputGhostSetting.PASTE_SETTLE_TIME
    # 実行後の待機秒数。
    _READY_TIME = InputGhostSetting.READY_TIME
    # 起動したアプリの window を待つ最大秒数と確認間隔。
    _LAUNCH_TIMEOUT = InputGhostSetting.LAUNCH_TIMEOUT
    _LAUNCH_INTERVAL = 0.1

    # 各キーコードの設定。
    _KEYCODE_0 = 48
    _KEYCODE_RETURN = 13
    _KEYCODE_CTRL = 17
    _KEYCODE_V = 86
    # 各操作で送る key (キーコード, flags)。押した key は必ず同じ操作の中で離します。
    _KEY_EVENTS = {
        '0': ((_KEYCODE_0, 0), (_KEYCODE_0, KEYEVENTF_KEYUP)),
        'return': ((_KEYCODE_RETURN, 0), (_KEYCODE_RETURN, KEYEVENTF_KEYUP)),
        'copypaste': ((_KEYCODE_CTRL, 0), (_KEYCODE_V, 0),
                      (_KEYCODE_CTRL, KEYEVENTF_KEYUP), (_KEYCODE_V, KEYEVENTF_KEYUP)),
    }
    # クリップボードの形式。
    _CF_UNICODETEXT = 13

    @classmethod
    def run(cls, dryRun=False):
        '''トップレベルメソッド。'''

        # いつもの前準備。
        begin_set.exec_all(__file__)

        # 入力する文字列を用意して、入力前に操作の一覧を作ります。
        text, encoding = cls.readInputText()
        actions = cls.buildActions(cls.splitRows(text))

        if dryRun:
            print(f'text file: {cls._TEXT_FILE_NAME} ({encoding})')
            for key, row in actions:
                print(f'paste {row}' if key == 'copypaste' else f'key {key}')
            print('dry-run: no input was sent.')
            return

        # 起動元(コンソールとか)の window を覚えておきます。
        # HWND は 32bit で比べても大丈夫なので、ctypes の既定の int のまま比べます。
        user32 = ctypes.windll.user32
        startWindow = user32.GetForegroundWindow()

        if cls._READY_TIME is False:
            # 対象アプリケーションを起動して、その window が前面に来るのを待ちます。
            targetWindow = cls.launchTargetApplication(user32, startWindow)
        else:
            for count in range(cls._READY_TIME):
                time.sleep(1)
                print(cls._READY_TIME - count)

            # このとき前面にある window を入力先にします。起動元のままなら入力しません。
            targetWindow = user32.GetForegroundWindow()
            if targetWindow in (0, startWindow):
                raise GreenException(
                    'The target window is not in front (focus is still on the '
                    'window that started InputGhost, or on no window). '
                    'Nothing was sent.')

        # 操作の一覧をぐるぐるしながら自動入力します。
        cls.inputAutomatically(actions, targetWindow)

    @classmethod
    def buildActions(cls, inputTextList):
        '''(キー, 文字列) の操作一覧を作ります。KEY_ORDER の誤りはここで弾きます。'''

        for key in cls._KEY_ORDER:
            if key not in cls._KEY_EVENTS:
                raise GreenException(f'Invalid KEY_ORDER:{key}')
        return [(key, row) for row in inputTextList for key in cls._KEY_ORDER]

    @classmethod
    def inputAutomatically(cls, actions, targetWindow):
        '''操作の一覧をぐるぐるしながら自動入力します。前面が targetWindow でなくなったら止めます。
        終わったときも止まったときも、クリップボードを元の文字列に戻します。'''

        user32 = ctypes.windll.user32
        savedClipboard = cls.saveClipboard(user32)
        lastPaste = None
        copied = False
        try:
            for index, (key, row) in enumerate(actions):
                if key in ['copypaste']:
                    # 貼り付けが終わったかは Windows では分からないので、前の Ctrl+V から
                    # PASTE_SETTLE_TIME 秒たつまでクリップボードを書き換えません。
                    cls.waitForPasteSettle(lastPaste)
                    copied = True
                    pyperclip.copy(row)
                    # 処理速度の問題(たぶん)でクリップボードに貼り付け終わるよりも前にCtrl+Vしてしまうことがある(ような気がする)。
                    # 対策として、貼ろうと意図してる文字列とクリップボードの内容をすり合わせます。
                    cls.waitForClipboard(row)
                    time.sleep(cls._WAIT_TIME)

                # キーを送る直前に、前面がまだ入力先か確かめます。1 つの操作の途中では止めません。
                if user32.GetForegroundWindow() != targetWindow:
                    raise GreenException(
                        'Foreground window changed, so InputGhost stopped before '
                        f'action {index + 1}/{len(actions)} ({key}). '
                        f'{index} actions already sent stay in the target window; '
                        'no key is left pressed.')

                # 1 つの操作の key は 1 回の SendInput でまとめて送ります。
                events = cls._KEY_EVENTS[key]
                sent = cls.sendKeys(user32, events)
                if key in ['copypaste'] and sent:
                    # 一部でも受け付けられたら、貼られたかもしれないものとして扱います。
                    lastPaste = time.monotonic()
                if sent != len(events):
                    released = cls.releaseKeys(user32, events, sent)
                    raise GreenException(
                        f'Windows accepted only {sent}/{len(events)} key events '
                        f'for action {index + 1}/{len(actions)} ({key}), so '
                        f'InputGhost stopped. {index} actions already sent stay '
                        'in the target window; '
                        + ('no key is left pressed.' if released
                           else 'some keys may still be pressed.'))
        except BaseException:
            # 元のエラーを優先します。戻せなかったら、そのことを表示するだけ。
            if copied:
                try:
                    cls.restoreClipboard(savedClipboard, lastPaste)
                except Exception as error:
                    print(f'InputGhost could not restore the clipboard: {error}',
                          file=sys.stderr)
            raise
        if copied:
            cls.restoreClipboard(savedClipboard, lastPaste)

    @classmethod
    def sendKeys(cls, user32, events):
        '''(キーコード, flags) の一覧を 1 回の SendInput で送り、受け付けられた数を返します。'''

        inputs = (INPUT * len(events))(*[
            INPUT(type=INPUT_KEYBOARD,
                  u=INPUTUNION(ki=KEYBDINPUT(wVk=keycode, dwFlags=flags)))
            for keycode, flags in events])
        return user32.SendInput(len(events), inputs, ctypes.sizeof(INPUT))

    @classmethod
    def releaseKeys(cls, user32, events, sent):
        '''受け付けられた sent 個のうち、押したまま離していない key を離します。できたら True。'''

        pressed = [keycode for keycode, flags in events[:sent]
                   if not flags & KEYEVENTF_KEYUP]
        released = [keycode for keycode, flags in events[:sent]
                    if flags & KEYEVENTF_KEYUP]
        releases = [(keycode, flags) for keycode, flags in events[sent:]
                    if flags & KEYEVENTF_KEYUP
                    and keycode in pressed and keycode not in released]
        return not releases or cls.sendKeys(user32, releases) == len(releases)

    @classmethod
    def saveClipboard(cls, user32):
        '''今のクリップボードの文字列を返します。空なら ''。文字列がなければ何も送らずに止めます。'''

        if user32.IsClipboardFormatAvailable(cls._CF_UNICODETEXT):
            return pyperclip.paste()
        if user32.CountClipboardFormats() == 0:
            return ''
        raise GreenException(
            'The clipboard holds non-text data (such as an image or files) '
            'that InputGhost cannot restore. Nothing was sent; copy some text '
            'or clear the clipboard first.')

    @classmethod
    def restoreClipboard(cls, savedClipboard, lastPaste):
        '''最後の Ctrl+V が読み終わるのを待ってから、クリップボードを戻します。'' なら空にします。'''

        cls.waitForPasteSettle(lastPaste)
        pyperclip.copy(savedClipboard)

    @classmethod
    def waitForPasteSettle(cls, lastPaste):
        '''前の Ctrl+V (lastPaste) から PASTE_SETTLE_TIME 秒たつまで待ちます。'''

        if lastPaste is not None:
            remaining = lastPaste + cls._PASTE_SETTLE_TIME - time.monotonic()
            if remaining > 0:
                time.sleep(remaining)

    @classmethod
    def waitForClipboard(cls, row):
        '''クリップボードが row になるまで待ちます。CLIPBOARD_TIMEOUT 秒を過ぎたら止めます。'''

        deadline = time.monotonic() + cls._CLIPBOARD_TIMEOUT
        while pyperclip.paste() != row:
            if time.monotonic() >= deadline:
                raise GreenException(
                    f'Clipboard did not become {row!r} within '
                    f'{cls._CLIPBOARD_TIMEOUT}s. Stopped before Ctrl+V; '
                    'input already sent stays in the target window.')
            time.sleep(cls._CLIPBOARD_INTERVAL)

    @classmethod
    def launchTargetApplication(cls, user32, startWindow):
        '''TARGET_APPLICATION を shell を通さずに起動し、その window が前面に来たら返します。
        LAUNCH_TIMEOUT 秒たっても来なければ、何も送らずに止めます。'''

        command = cls.targetCommand()
        program = ntpath.basename(command[0]).lower()
        if not ntpath.splitext(program)[1]:
            program += '.exe'
        launchTime = cls.currentFileTime()
        try:
            process = subprocess.Popen(command)
        except OSError as error:
            raise GreenException(
                f'Could not start TARGET_APPLICATION {command!r}: {error}. '
                'Nothing was sent.') from error

        deadline = time.monotonic() + cls._LAUNCH_TIMEOUT
        while True:
            window = user32.GetForegroundWindow()
            if window not in (0, startWindow) and cls.isLaunchedWindow(
                    user32, window, process.pid, program, launchTime):
                return window
            if time.monotonic() >= deadline:
                raise GreenException(
                    f'{program!r} did not come to the front within '
                    f'{cls._LAUNCH_TIMEOUT}s (the front window is not one the '
                    'launch opened). Nothing was sent.')
            time.sleep(cls._LAUNCH_INTERVAL)

    @classmethod
    def targetCommand(cls):
        '''TARGET_APPLICATION を引数の list にします。空なら止めます。'''

        setting = cls._TARGET_APPLICATION
        if isinstance(setting, str):
            # 空の文字列を CommandLineToArgvW に渡すと、自分 (python) のパスが返ってくる。
            command = cls.splitCommandLine(setting) if setting.strip() else []
        else:
            command = list(setting)
        if not command:
            raise GreenException('TARGET_APPLICATION is empty. Nothing was sent.')
        return command

    @classmethod
    def isLaunchedWindow(cls, user32, window, launchedPid, program, launchTime):
        '''起動した process の window か、起動後に始まった同じ実行ファイルの window なら True。'''

        owner = ctypes.c_ulong()
        user32.GetWindowThreadProcessId(window, ctypes.byref(owner))
        if owner.value == launchedPid:
            return True
        # Windows 11 の Notepad のように、別の process に引き継ぐアプリのため。
        details = cls.processDetails(owner.value)
        return (details is not None and details[0] == program
                and details[1] >= launchTime)

    @staticmethod
    def splitCommandLine(commandLine):
        '''Windows と同じ規則でコマンドラインを引数の list にします (Windows 専用)。'''

        shell32 = ctypes.WinDLL('shell32')
        kernel32 = ctypes.WinDLL('kernel32')
        shell32.CommandLineToArgvW.restype = ctypes.POINTER(ctypes.c_wchar_p)
        shell32.CommandLineToArgvW.argtypes = [
            ctypes.c_wchar_p, ctypes.POINTER(ctypes.c_int)]
        kernel32.LocalFree.argtypes = [ctypes.c_void_p]
        count = ctypes.c_int()
        argv = shell32.CommandLineToArgvW(commandLine, ctypes.byref(count))
        if not argv:
            raise GreenException(
                f'Could not read TARGET_APPLICATION {commandLine!r}. Nothing was sent.')
        try:
            return [argv[i] for i in range(count.value)]
        finally:
            kernel32.LocalFree(argv)

    @staticmethod
    def currentFileTime():
        '''今の時刻を、process の開始時刻と比べられる FILETIME で返します (Windows 専用)。'''

        now = ctypes.c_uint64()
        ctypes.WinDLL('kernel32').GetSystemTimeAsFileTime(ctypes.byref(now))
        return now.value

    @staticmethod
    def processDetails(pid):
        '''process の (実行ファイル名 (小文字), 始まった時刻) を返します。分からなければ None (Windows 専用)。'''

        kernel32 = ctypes.WinDLL('kernel32')
        kernel32.OpenProcess.restype = ctypes.c_void_p
        kernel32.OpenProcess.argtypes = [ctypes.c_uint32, ctypes.c_int, ctypes.c_uint32]
        kernel32.QueryFullProcessImageNameW.argtypes = [
            ctypes.c_void_p, ctypes.c_uint32, ctypes.c_wchar_p,
            ctypes.POINTER(ctypes.c_uint32)]
        kernel32.GetProcessTimes.argtypes = (
            [ctypes.c_void_p] + [ctypes.POINTER(ctypes.c_uint64)] * 4)
        kernel32.CloseHandle.argtypes = [ctypes.c_void_p]
        # PROCESS_QUERY_LIMITED_INFORMATION
        handle = kernel32.OpenProcess(0x1000, False, pid)
        if not handle:
            return None
        try:
            size = ctypes.c_uint32(32768)
            path = ctypes.create_unicode_buffer(size.value)
            times = [ctypes.c_uint64() for _ in range(4)]
            if not kernel32.QueryFullProcessImageNameW(
                    handle, 0, path, ctypes.byref(size)):
                return None
            if not kernel32.GetProcessTimes(handle, *map(ctypes.byref, times)):
                return None
            return ntpath.basename(path.value).lower(), times[0].value
        finally:
            kernel32.CloseHandle(handle)

    @classmethod
    def readInputText(cls):
        '''テキストファイルを読んで (文字列, 使った文字コード) を返します。
        文字コードを決められなければ、何も送らずに止めます。'''

        with open(cls._TEXT_FILE_NAME, 'rb') as f:
            data = f.read()
        text, encoding = cls.decodeInputText(data)
        if '\x00' in text:
            raise GreenException(
                f'{cls._TEXT_FILE_NAME} contains NUL characters (maybe UTF-16 '
                'without a BOM). Nothing was sent; save it as UTF-8 or cp932.')
        return text, encoding

    @classmethod
    def decodeInputText(cls, data):
        '''README の「入力ファイルの文字コード」の順に文字コードを決めて読みます。'''

        name = cls._TEXT_FILE_NAME
        bom = next(((codec, label) for mark, codec, label in cls._BOMS
                    if data.startswith(mark)), None)

        if cls._TEXT_ENCODING != 'auto':
            try:
                codec = codecs.lookup(cls._TEXT_ENCODING).name
            except LookupError:
                raise GreenException(
                    f'Unknown TEXT_ENCODING {cls._TEXT_ENCODING!r}. '
                    'Nothing was sent.') from None
            # UTF-8 なら BOM を外します (見えない文字を打たないように)。
            if codec == 'utf-8':
                codec = 'utf-8-sig'
            if bom and bom[0] != codec:
                raise GreenException(
                    f'{name} starts with a {bom[1].split()[0].upper()} BOM, but '
                    f'TEXT_ENCODING is {cls._TEXT_ENCODING!r}. Nothing was sent.')
            return cls.decodeStrictly(
                data, codec, f'{cls._TEXT_ENCODING} (TEXT_ENCODING)')

        if bom:
            return cls.decodeStrictly(data, *bom)
        if data.isascii():
            return data.decode('ascii'), 'ascii'

        decoded, errors = {}, {}
        for codec in ('utf-8', 'cp932'):
            try:
                decoded[codec] = data.decode(codec)
            except UnicodeDecodeError as error:
                errors[codec] = error
        if not decoded:
            raise GreenException(
                f'Could not read {name} as UTF-8 ({cls.describe(errors["utf-8"])}) '
                f'or cp932 ({cls.describe(errors["cp932"])}). Nothing was sent; '
                'save it as UTF-8 or cp932, or set TEXT_ENCODING.')
        if len(decoded) == 2 and decoded['utf-8'] != decoded['cp932']:
            # 0x0A はどちらでも改行で、2 byte 文字の途中には出てこないので、行がずれない。
            utf8, cp932 = next(
                (u, c) for u, c in zip(decoded['utf-8'].split('\n'),
                                        decoded['cp932'].split('\n')) if u != c)
            raise GreenException(
                f'{name} can be read both as UTF-8 and as cp932, and they differ '
                f'(UTF-8 {utf8[:20]!r}, cp932 {cp932[:20]!r}). Nothing was sent; '
                "set TEXT_ENCODING to 'utf-8' or 'cp932'.")
        codec = next(iter(decoded))
        return decoded[codec], codec

    @classmethod
    def decodeStrictly(cls, data, codec, label):
        try:
            return data.decode(codec), label
        except LookupError:
            # base64 などは codec ではあっても文字コードではありません。
            raise GreenException(
                f'Unknown TEXT_ENCODING {cls._TEXT_ENCODING!r} (not a text '
                'encoding). Nothing was sent.') from None
        except UnicodeDecodeError as error:
            raise GreenException(
                f'Could not read {cls._TEXT_FILE_NAME} as {label}: '
                f'{cls.describe(error)}. Nothing was sent.') from error

    @staticmethod
    def describe(error):
        return f'byte {error.object[error.start]:#04x} at position {error.start}'

    @classmethod
    def splitRows(cls, text):
        '''文字列を行に分けて、NUM_CHARA_IN_ROW 文字ずつに区切ります。'''

        # 改行は、前の universal newlines と同じく \r\n・\r・\n を区切りにします。
        rowList = text.replace('\r\n', '\n').replace('\r', '\n').split('\n')

        # 加工してリストにします。
        ret = []
        for row in rowList:
            row = row.strip().replace('　', ' ')
            for i in range(1000000):
                convertedRow = row[
                    cls._NUM_CHARA_IN_ROW*i:cls._NUM_CHARA_IN_ROW*(i+1)]
                if convertedRow:
                    ret.append(convertedRow)
                else:
                    break

        return ret


class GreenException(Exception):

    def __init__(self, error_message='エラーだよ。'):
        self.error_message = error_message

    def __str__(self):
        return self.error_message


def main(argv=None):
    parser = argparse.ArgumentParser(description='文章を別のアプリケーションに一行ずつコピペします。')
    parser.add_argument(
        '--dry-run', action='store_true',
        help='キー入力・クリップボード・アプリ起動をせず、予定の操作を表示するだけ。')
    args = parser.parse_args(argv)
    InputGhost.run(dryRun=args.dry_run)


if __name__ == '__main__':
    main()
