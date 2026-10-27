#!/usr/bin/env python
# coding: utf-8

'''InputGhostをexe化して使うことを想定して、セッティングファイルを準備。
改行はWindowsね。'''

# テキストファイルの名前。
TEXT_FILE_NAME = 'inputGhost.txt'
# テキストファイルの文字コード。'auto' なら BOM・ASCII・UTF-8 と cp932 のどちらで読めるかで決めるよ。
# UTF-8 と cp932 のどっちでも読めちゃうときは止まるので、'utf-8' か 'cp932' を書いてね。
TEXT_ENCODING = 'auto'
# 一行何文字で区切る?
NUM_CHARA_IN_ROW = 18
# 対象アプリケーション。READY_TIME = False のとき shell を通さずに起動するよ。
# ('notepad.exe', 'memo.txt') みたいな tuple か、Windows のコマンドラインの文字列で書いてね。
# パス通ってなかったら絶対パス、空白があるならダブルクォーテで囲んでね。
TARGET_APPLICATION = 'notepad.exe'
# 行動の順番。
KEY_ORDER = ('0', 'return', 'copypaste', 'return')
# コピペ時の待機秒数。なんかねーノーウェイトで走らせるとヘンにコピペが失敗するときあって…。
WAIT_TIME = 1
# クリップボードが貼りたい文字列になるまで待つ最大秒数。過ぎたら Ctrl+V せずに止まるよ。
CLIPBOARD_TIMEOUT = 5
# Ctrl+V のあと、次の行をクリップボードに入れるまで空ける秒数。遅いアプリが前の行を読む前に変わらないように。
PASTE_SETTLE_TIME = 0.5
# 実行後の待機秒数。使わないならFalseにしてね (そのときは TARGET_APPLICATION を起動するよ)。
READY_TIME = 5
# 起動したアプリの window が前面に来るのを待つ最大秒数。来なかったら何も送らずに止まるよ。
LAUNCH_TIMEOUT = 10
