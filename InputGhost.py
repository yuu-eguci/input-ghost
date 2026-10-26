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
'''


import argparse
import ctypes
import subprocess
import time
import pyperclip
import InputGhostSetting
import begin_set


class InputGhost:
    ''' ～(m´□｀)m < ｶﾀｶﾀｶﾀｶﾀ '''

    # テキストファイルの名前。
    _TEXT_FILE_NAME = InputGhostSetting.TEXT_FILE_NAME
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
    # 実行後の待機秒数。
    _READY_TIME = InputGhostSetting.READY_TIME

    # 各キーコードの設定。
    _KEYCODE_0 = 48
    _KEYCODE_RETURN = 13
    _KEYCODE_CTRL = 17
    _KEYCODE_V = 86

    @classmethod
    def run(cls, dryRun=False):
        '''トップレベルメソッド。'''

        # いつもの前準備。
        begin_set.exec_all(__file__)

        # 入力する文字列を用意して、入力前に操作の一覧を作ります。
        actions = cls.buildActions(cls.getInputTextList())

        if dryRun:
            for key, row in actions:
                print(f'paste {row}' if key == 'copypaste' else f'key {key}')
            print('dry-run: no input was sent.')
            return

        # 起動元(コンソールとか)の window を覚えておきます。
        # HWND は 32bit で比べても大丈夫なので、ctypes の既定の int のまま比べます。
        user32 = ctypes.windll.user32
        startWindow = user32.GetForegroundWindow()

        if cls._READY_TIME is False:
            # 対象アプリケーションを引っ張り出します。
            cls.bringTargetApplication()
            time.sleep(1)
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
            if key not in ('0', 'return', 'copypaste'):
                raise GreenException(f'Invalid KEY_ORDER:{key}')
        return [(key, row) for row in inputTextList for key in cls._KEY_ORDER]

    @classmethod
    def inputAutomatically(cls, actions, targetWindow):
        '''操作の一覧をぐるぐるしながら自動入力します。前面が targetWindow でなくなったら止めます。'''

        user32 = ctypes.windll.user32
        for index, (key, row) in enumerate(actions):
            if key in ['copypaste']:
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

            if key in ['0']:
                user32.keybd_event(cls._KEYCODE_0, 0, 0, 0)
                user32.keybd_event(cls._KEYCODE_0, 0, 0x2, 0)
            elif key in ['return']:
                user32.keybd_event(cls._KEYCODE_RETURN, 0, 0, 0)
                user32.keybd_event(cls._KEYCODE_RETURN, 0, 0x2, 0)
            elif key in ['copypaste']:
                user32.keybd_event(cls._KEYCODE_CTRL, 0, 0, 0)
                user32.keybd_event(cls._KEYCODE_V, 0, 0, 0)
                user32.keybd_event(cls._KEYCODE_CTRL, 0, 0x2, 0)
                user32.keybd_event(cls._KEYCODE_V, 0, 0x2, 0)

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
    def bringTargetApplication(cls):
        '''対象アプリケーションを引っ張り出します。'''

        subprocess.Popen('call '+cls._TARGET_APPLICATION, shell=True)

    @classmethod
    def getInputTextList(cls):
        '''テキストファイルを読み込んで加工します。'''

        # ファイル読み込みます。
        with open(cls._TEXT_FILE_NAME, 'r', encoding='cp932') as f:
            rowList = f.readlines()

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
