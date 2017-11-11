#!/usr/bin/env python
# coding: utf-8

'''InputGhostをexe化して使うことを想定して、セッティングファイルを準備。
改行はWindowsね。'''

# テキストファイルの名前。
TEXT_FILE_NAME = 'inputGhost.txt'
# 一行何文字で区切る?
NUM_CHARA_IN_ROW = 18
# 対象アプリケーションの名前。もしパス通ってなかったら絶対パスを書いてね。ダブルクォーテ書いたほうがいいかも。
TARGET_APPLICATION = 'notepad.exe'
# 行動の順番。
KEY_ORDER = ('0', 'return', 'copypaste', 'return')
# コピペ時の待機秒数。なんかねーノーウェイトで走らせるとヘンにコピペが失敗するときあって…。
WAIT_TIME = 1
# 実行後の待機秒数。使わないならFalseにしてね。
READY_TIME = 5
