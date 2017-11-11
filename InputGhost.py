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
'''


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
    # 実行後の待機秒数。
    _READY_TIME = InputGhostSetting.READY_TIME

    # 各キーコードの設定。
    _KEYCODE_0 = 48
    _KEYCODE_RETURN = 13
    _KEYCODE_CTRL = 17
    _KEYCODE_V = 86

    @classmethod
    def run(cls):
        '''トップレベルメソッド。'''

        # いつもの前準備。
        begin_set.exec_all(__file__)

        # 入力する文字列を用意します。
        inputTextList = cls.getInputTextList()

        if cls._READY_TIME is False:
            # 対象アプリケーションを引っ張り出します。
            cls.bringTargetApplication()
            time.sleep(1)
        else:
            for count in range(cls._READY_TIME):
                time.sleep(1)
                print(cls._READY_TIME - count)

        # 文字列リストをぐるぐるしながら自動入力します。
        cls.inputAutomatically(inputTextList)

    @classmethod
    def inputAutomatically(cls, inputTextList):
        '''文字列リストをぐるぐるしながら自動入力します。'''

        user32 = ctypes.windll.user32
        for row in inputTextList:
            for key in cls._KEY_ORDER:
                if key in ['0']:
                    user32.keybd_event(cls._KEYCODE_0, 0, 0, 0)
                    user32.keybd_event(cls._KEYCODE_0, 0, 0x2, 0)
                elif key in ['return']:
                    user32.keybd_event(cls._KEYCODE_RETURN, 0, 0, 0)
                    user32.keybd_event(cls._KEYCODE_RETURN, 0, 0x2, 0)
                elif key in ['copypaste']:
                    pyperclip.copy(row)
                    # 処理速度の問題(たぶん)でクリップボードに貼り付け終わるよりも前にCtrl+Vしてしまうことがある(ような気がする)。
                    # 対策として、貼ろうと意図してる文字列とクリップボードの内容をすり合わせます。
                    while True:
                        if pyperclip.paste() == row:
                            break
                        time.sleep(0.1)
                    time.sleep(cls._WAIT_TIME)
                    user32.keybd_event(cls._KEYCODE_CTRL, 0, 0, 0)
                    user32.keybd_event(cls._KEYCODE_V, 0, 0, 0)
                    user32.keybd_event(cls._KEYCODE_CTRL, 0, 0x2, 0)
                    user32.keybd_event(cls._KEYCODE_V, 0, 0x2, 0)
                else:
                    raise GreenException(f'Invalid KEY_ORDER:{key}')

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


if __name__ == '__main__':
    InputGhost.run()
