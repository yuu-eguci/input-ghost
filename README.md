
InputGhost
===

It automatically pastes text lines to other application. Only available for Windows.

![](media/media.png)

## 仕組み

- `inputGhost.txt` (cp932) を読み、各行を `NUM_CHARA_IN_ROW` 文字ずつに分割します。
- 分割した文字列ごとに、focus されている window へ clipboard と `SendInput` を使って `KEY_ORDER` (`'0'`・`'return'`・`'copypaste'`) を実行します。
- 設定は `InputGhostSetting.py` に書きます。不正な `KEY_ORDER` は、入力を始める前に検出します。
- 1 つの操作の key (Ctrl+V なら Ctrl・V を押して離す 4 つ) は、`SendInput` で 1 回にまとめて送り、Windows が受け付けた数を確認します。全部を受け付けなかった場合は、押したままの key を離してから `GreenException` で停止し、clipboard を戻します。ただし、管理者権限のアプリに UIPI で止められた入力や、別のプログラムが `BlockInput` で止めた入力は、受け付けた数に表れないため検出できません (`BlockInput` は GitHub の Windows runner で確認しました)。
- `copypaste` では、clipboard が貼り付けたい文字列になるまで 0.1 秒ごとに確認します。`CLIPBOARD_TIMEOUT` 秒 (既定 5 秒) 待っても変わらない場合は、Ctrl+V を送らずに `GreenException` で停止します。それまでに送った入力は入力先に残ります。押しっぱなしの key はありません。
- 次の行を clipboard に入れるのは、前の Ctrl+V から `PASTE_SETTLE_TIME` 秒 (既定 0.5 秒) たってからです。Windows には貼り付けが終わったことを知る方法がないため、処理の遅いアプリが前の行を読む前に clipboard が次の行に変わり、同じ行が 2 回貼られるのを防ぐ待ち時間です。clipboard を元に戻す前にも、同じだけ待ちます。重いアプリで行がずれる場合は値を増やしてください (行ごとに最大でその秒数だけ遅くなります)。
- 通常実行では、入力を始める前に clipboard の文字列を覚えておきます。終わったとき・途中で止まったとき (タイムアウト・前面の変化・エラー・Ctrl+C) は、最後の Ctrl+V から `PASTE_SETTLE_TIME` 秒待ってから元に戻します。clipboard を一度も書き換えていなければ、何もしません。
- 戻せるのは文字列だけです。HTML・RTF などの書式は消え、文字列だけが戻ります。空の clipboard は空に戻します。画像やファイルなど文字列のない clipboard は戻せないため、clipboard に触らず、何も送らずに停止します。
- clipboard を戻せなかった場合、元のエラーで止まったときはそのエラーのまま終了し、戻せなかったことを stderr に表示します。正常に終わったあとに戻せなかった場合は、そのエラーで終了します。

## 入力先の確認と停止

- 通常実行では、カウントダウン後に前面にある window を入力先として記録します。前面が InputGhost を起動した window のまま、または前面に window がない場合は、何も送らずに停止します。
- `READY_TIME = False` のときは、カウントダウンの代わりに `TARGET_APPLICATION` を shell を通さずに起動し、最大 `LAUNCH_TIMEOUT` 秒 (既定 10 秒) 待って、起動したアプリの window が前面に来たらそれを入力先にします。入力先にするのは、起動した process の window か、起動後に始まった同じ名前の実行ファイルの window (Windows 11 の Notepad のように別の process に引き継ぐアプリのため) だけです。前から動いている同じアプリの window や、別のアプリの window は使いません。
- 起動できない場合や、時間内に起動したアプリの window が前面に来ない場合は、key を送らず、clipboard にも触らずに停止します。起動したアプリは閉じずに残ります。すでに開いている同じアプリに引き継がれて新しい window ができない場合 (Windows 11 の Notepad のタブなど) も停止するので、そのときは `READY_TIME` に秒数を書いてカウントダウンを使ってください。
- `TARGET_APPLICATION` は、実行ファイルと引数の tuple (例: `('notepad.exe', 'memo.txt')`) か、Windows のコマンドラインの書き方の文字列 (例: `'"C:\\Program Files\\App\\app.exe" memo.txt'`) で書きます。shell を通さないので、`.bat` や文書ファイルを直接指定したり、`&` などの shell の記号を使ったりはできません。
- 各操作の key を送る直前に、前面の window が入力先のままか確認します。変わっていたら次の key を送らずに `GreenException` で停止し、何番目の操作で止まったかを表示します。それまでに送った入力は入力先に残ります。
- 止めたいときは、別の window をクリックするか Alt+Tab してください (Win+L でも止まります)。入力先のアプリが dialog を開いた場合も停止します。
- 制限: 1 つの操作 (Ctrl+V など) の key の途中では確認しないため、押しっぱなしの key は残りません。管理者権限で動くアプリには、Windows の UIPI の制限で入力が届かないことがあり、これは検出できません。

## 実行環境

- Windows + Python 3 (CI は `windows-latest` 上の 3.13 を使います)
- Dependency: `pyperclip` (`requirements.txt`)
- Docker: 非対応です。Windows desktop の focus・clipboard・key event を操作するため、container では動作を再現できません。

## パッと安全に試したい

```bat
py -m venv .venv
.venv\Scripts\python -m pip install -r requirements.txt
.venv\Scripts\python InputGhost.py --dry-run
```

`--dry-run` は実行予定だけを表示します。key を送らず、clipboard を変更せず、入力先の application も起動しません。

通常実行 (`--dry-run` なし) は、focus されている window へ入力して clipboard を上書きします。空の Notepad とテスト用の文章だけで試してください。

## 開発

```bat
.venv\Scripts\python -m pip install -r requirements-dev.txt
.venv\Scripts\ruff check .
.venv\Scripts\python -m pytest
```

- Linter: ruff (`pyproject.toml` に rule を書いています)
- Tests: pytest (`tests/`)。Windows 入力を fake に置き換えるため、実際の key は送りません。
- E2E (`tests/test_e2e_windows.py`): GitHub-hosted の Windows runner 上で `INPUTGHOST_E2E=1` のときだけ実行し、それ以外の環境では skip します (`INPUTGHOST_E2E=1` なのに GitHub-hosted runner でない場合は、key を送らずに失敗します)。repo 内の使い捨て入力先 (`tests/e2e_target.py`、tkinter) を 2 つ起動し、本物の key で「起動元から入力先への切り替え」「複数行の入力 (貼り付けを 0.2 秒遅らせる入力先でも行がずれないこと)」「前面が変わったら次の操作の前で停止」「終了後・停止後に元の clipboard の文字列が戻ること」「`READY_TIME = False` で起動した入力先を待って使い、前からある別の window には打たないこと」を確認します。入力先を前面にできない場合は、何も送らずに失敗します。入力する文字列は `#` で始まる、command として実行されないテスト用の文章だけです。
- CI (`.github/workflows/ci.yml`) は `windows-latest` 上で lint・test・`--dry-run` smoke check・E2E を実行します。deploy は行いません。
