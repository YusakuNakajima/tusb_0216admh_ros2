# USB 通信のキャプチャ手順（Windows）

TUSB-0216ADMH の USB プロトコルは公開されていない。Linux ネイティブのドライバを作るため、
公式の Windows ドライバを動かしたときの USB 通信を記録し、各 `Tusbadmh_*` 呼び出しが
送受信するバイト列を特定する。

## 用意するもの

- 公式ドライバ（製品付属ディスクの `TUSBADMH\DRIVER`）をインストール済みの Windows PC
- Python 3（64bit。DLL が 64bit 版のため）
- ベンダの Python サンプル [ADMHSmplPy.zip](https://www.turtle-ind.co.jp/wp-content/uploads/ADMHSmplPy.zip)
  に含まれる `TUSBADMH.py`（再配布条件が不明なので、本リポジトリには含めていない）
- [Wireshark](https://www.wireshark.org/)。インストール時に **USBPcap** にチェックを入れる。
  入れたら再起動する。

## 手順

1. **DIGITAL I/O コネクタから配線を外す。** シナリオはディジタル出力 PO0–PO3 を
   0x0→0xF の順に切り替える。BNC 入力は開放のままでよい（波形の中身は使わない）。
   入力電圧の仕様（±5 V 以内）は守ること。
2. `windows/capture_session.py` と `TUSBADMH.py` を同じフォルダに置く。
3. Wireshark を管理者として起動し、TUSB-0216ADMH がつながっている `USBPcap1`〜`USBPcapN`
   を選ぶ。どれか分からなければ、各インタフェースのデバイス一覧（歯車アイコン）で
   `Turtle Industry` を探す。
   - **キャプチャ開始後に USB ケーブルを抜き差しする**と、デバイスディスクリプタも記録され、
     解析スクリプトがデバイスを自動で判別できる。
4. コマンドプロンプトでシナリオを実行する（ID スイッチが 0 の場合）:

   ```bat
   py -3 capture_session.py --id 0 --log calls.jsonl
   ```

   各呼び出しの間に 1 秒の間隔を空けるので、5 分ほどかかる。
5. 終わったら Wireshark を止め、`File > Save As` で **pcapng** として保存する
   （例: `tusb_session_id0.pcapng`）。
6. **ID スイッチを別の値（例: 3）に変えて**、手順 3〜5 をもう一度行う
   （`--id 3 --log calls_id3.jsonl`）。DLL が ID スイッチをどう読んでいるか
   （シリアル文字列か、コマンドの応答か）を見分けるため。
7. `*.pcapng` と `calls*.jsonl` を Linux 側に持ってくる。

## 解析（Linux 側）

```bash
ros2 run tusb_0216admh_ros2 analyze_usb_capture.py tusb_session_id0.pcapng \
  --markers calls.jsonl > session_id0.txt
```

各 `Tusbadmh_*` 呼び出しが `###` の行で入り、その直後の行がその呼び出しによる USB の
送受信になる。

```text
   +3.012345 ### Tusbadmh_Dio_Write(0, 5) -> 0
   +3.012901 OUT ep02 bulk      subm st=0x0 len=4 : .. .. .. ..
   +3.013402 IN  ep81 bulk      cmpl st=0x0 len=2 : .. ..
```

- 引数を1つずつ変えた呼び出しを並べてあるので、どのバイトがどの引数に対応するかを
  差分で特定する。
- デバイスが特定できない場合（ディスクリプタが記録されていない場合）は、表示される
  デバイス一覧から `--device <address>` で指定する。
- Windows と、キャプチャを取った PC の時計が別の場合は `--marker-offset-s` で揃える。

解析で分かったコマンドは `tusb_0216admh/usb_device.py` の `UsbTusbAdmhDevice` に実装し、
`NotImplementedError` を置き換える。

## 注意

- キャプチャは自分の装置の通信を観察するだけで、Windows ドライバのバイナリは解析しない。
  ドライバやベンダのファイルはリポジトリに入れない（`.gitignore` で `*.pcapng` / `*.jsonl`
  も除外してある）。
- 実装後に Linux から初めてコマンドを送るときは、DIGITAL I/O と BNC 入力に何もつながって
  いない状態で行う。
