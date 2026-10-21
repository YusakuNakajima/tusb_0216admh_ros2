# 引き継ぎメモ（2026-10-20 時点）

Windows PC でのプロトコル解析と、Ubuntu での実機確認が終わった段階のメモ。

## Ubuntu での実機確認（2026-10-20）

`onolab_ros2_humble` コンテナ（root、`/dev/bus/usb` をマウント）で、ID スイッチ 0 の1台を使って確認した。
BNC 入力は開放、DIGITAL I/O は未接続。

- `colcon test`: 55 件 PASS（lint を含む）
- `tusb_probe.py --claim`: claim と文字列ディスクリプタの読み取りができた（serial は ID スイッチと無関係に `'0001'`）
- `tusb_selftest.py --id 0`: 全項目 PASS。3900 Hz、ch1 +0.17 mV / ch2 −0.14 mV、標準偏差 0.03 mV
  （Windows での値と同程度）。`--id 3` ではエラー 6 になる
- ノード（`backend:=usb`）: 5 秒間で 251 メッセージ。連番の欠損なし、オーバーフローなし。
  受信側で測ったレートは 3922 Hz
- Linux で直したこと:
  - **前のプロセスが読まなかった応答が残ると、次の open 以降の応答が1つずつずれる**現象を再現した。
    同じ状態はそのあとの open にも連鎖する（HANDOFF の旧版にあった「エラー 9 は抜き差しで直す」の原因）。
    `open()` で IN エンドポイントを空読みしてから `0xF0` を送るように直し、実機で直ったことを確認した。
  - `ros2 launch` で Ctrl-C を押すと SIGINT が2回届き、2回目が終了処理に割り込んでいた。
    終了処理の間は SIGINT を無視するようにした（`process has finished cleanly` を確認）。
  - 停止中に Adc_Stop を送っても正常に応答する（`40`）。
- 2026-10-21: ホストに `udev/setup_udev.sh` でルールを入れ、コンテナの `ros` ユーザー（root ではない）
  から `tusb_selftest.py --id 0` が全項目 PASS（3901 Hz）。`--privileged` なしのコンテナでは
  `Input/Output Error` になる。

## 終わったこと

- 公式ドライバの USB 通信をキャプチャし、全コマンドを特定した → [PROTOCOL.md](PROTOCOL.md)
- `tusb_0216admh/usb_device.py` に全コマンドを実装した（`NotImplementedError` は残っていない）。
  ID スイッチによる機器の選択も DLL と同じ方式で実装した（`usb_index` パラメータは廃止）。
- キャプチャのバイト列を再生するテスト `test/test_usb_device.py` を追加した。
- **Windows 上で** pyusb（libusb + WinUSB）から実機を動かし、確認した:
  - Open（ID 0 / 3 の選択、違う ID ではエラー 6）、DIO 読み取り、入力レンジ、状態取得
  - 3906.25 Hz 2ch のソフトウェアトリガ取り込み。値は DLL と一致
    （開放入力で ch1 ≈ +0.20 mV、ch2 ≈ −0.08 mV、ノイズ約 0.02 mV）
  - `scripts/tusb_selftest.py` が全項目 PASS

## まだやっていないこと

- 長時間（数時間）の連続取り込み。レートの上限は 2026-10-21 に測った（2ch 100 kHz で 30 秒安定、
  それより上は約 124 kS/s で頭打ち。README の「取り込みレートの上限」）。
- 繰り返しモード（Mode=1）、外部トリガ、アナログトリガ、外部クロックでの実際の取り込み。
  コマンドの形式はキャプチャで確認済みだが、取り込みはしていない。
- 1回の `0x60` で要求できる最大サンプル数（いまは観測範囲内の 512 に抑えている）。

## Ubuntu でやること

ID スイッチは最後に **0** に戻した状態（違う場合は `--id` / `device_id` を合わせる）。
BNC 入力は開放か ±1 V 以内、DIGITAL I/O は未接続で始める。

```bash
# 1. 依存（pyusb は package.xml にも python3-usb として追加済み）
pip install pyusb            # または sudo apt install python3-usb

# 2. ホスト側（初回のみ）: root 以外から libusb で開けるようにする
./udev/setup_udev.sh   # sudo のパスワードを聞かれる。最後に OK と出れば完了

# 3. ビルドとテスト
colcon build --packages-select tusb_0216admh_ros2 --cmake-args -DBUILD_TESTING=ON
source install/setup.bash
colcon test --packages-select tusb_0216admh_ros2 && colcon test-result --verbose

# 4. 接続確認（書き込みなし）
ros2 run tusb_0216admh_ros2 tusb_probe.py --claim

# 5. 実機テスト（2 秒の取り込み。DIO 出力は触らない）
ros2 run tusb_0216admh_ros2 tusb_selftest.py --id 0

# 6. ノード
ros2 launch tusb_0216admh_ros2 tusb_0216admh.launch.py backend:=usb
ros2 topic echo /tusb_0216admh/adc_block --field sample_rate_hz
```

`tusb_selftest.py` の期待値は Windows での結果と同じ（全項目 PASS、サンプルレート 3906 Hz 付近）。
`colcon test` は Windows では回していない（同じテストを pytest と flake8 で直接実行し、50 件 PASS）。

## うまくいかないとき

- `Access denied` / エラー 5: udev ルールが効いていない（`Input/Output Error` ならコンテナが `privileged` でない）。コンテナ内なら、ホスト側に入れてから
  抜き差しする。
- エラー 6 `no unit with ID switch N; attached: ['ID M']`: ID スイッチと `--id` / `device_id` が違う。
- エラー 9（応答が合わない）: 前のプロセスが残した応答は open で捨てるようにしたので、通常は起きない。
  取り込みの最中に起きる場合は、そのときのやり取りを記録して比べる。
- 一度だけ、ノイズが 34 mV に増えた回があった（Windows、ID スイッチを戻した直後）。
  その後は再現していない。同じことが続くなら、外れ値の位置とデータ長を記録する。

## Windows PC に残っているもの

Ubuntu では使わないが、追加のキャプチャが必要になったときのために残してある。

- 公式ドライバ（TUSBADMH_261、WinUSB）、USBPcap、Wireshark をインストール済み。
- `C:\Users\user\tusb_capture\`
  - キャプチャ: `tusb_session_id0.pcap`（basic, ID 0）、`tusb_start_id0.pcap`（start, ID 0）、
    `tusb_basic_id3.pcap`（basic, ID 3）と、それぞれの `calls_*.jsonl`
  - 要約: `summary_id0.txt`、`summary_start_id0.txt`、`summary_basic_id3.txt`
  - ベンダの `TUSBADMH.py`（再配布不可なのでリポジトリには入れていない）

追加でキャプチャするときは、`windows/capture_session.py` にシナリオを足し、
`windows/run_capture.ps1 -Id 0 -Scenario <名前>` を Windows で実行する（UAC の確認が1回出る）。
要約は `scripts/summarize_usb_capture.py <pcap> <jsonl>` で作れる（Linux でも動く）。
