# tusb_0216admh_ros2

タートル工業の USB AD コンバータ [TUSB-0216ADMH](https://www.turtle-ind.co.jp/products/ad-converters/tusb-0216admh/)
（16bit、2ch、最大 25 MHz）を ROS 2 Humble から読むドライバ。
Windows を使わず、Linux から libusb（pyusb）で直接デバイスを操作する。

## 現状

| 項目 | 状態 |
| --- | --- |
| USB の列挙・ディスクリプタ取得・インタフェースの claim | 実装済み（`tusb_probe.py`）。実機で確認済み（文字列ディスクリプタ、claim、IN の受信待ち。何も送らなければ IN には何も来ない） |
| USB コマンド（設定・取り込み開始・データ取得） | 実装済み（`usb_device.py`）。公式ドライバの通信をキャプチャして特定した（[docs/PROTOCOL.md](docs/PROTOCOL.md)）。Windows 上の pyusb と Ubuntu（コンテナ）の両方で、実機での取り込みを確認済み（2026-10-20） |
| ID スイッチと USB デバイスの対応 | 実装済み。DLL と同じく、各機器に ID スイッチの値を問い合わせ、`device_id` と一致する機器を開く |
| ROS ノード・メッセージ・launch | 実装済み。`backend:=usb` で実機から 3906.25 Hz 2ch を 5 秒間配信し、欠損・オーバーフローなしを確認済み。実機がなくても `backend:=mock`（模擬の正弦波）で動かせる |
| キャプチャ解析ツール | 実装済み（`analyze_usb_capture.py`、`summarize_usb_capture.py`、USBPcap / usbmon 対応） |

送るバイト列は、すべてキャプチャで公式ドライバが送ったものと同じ形式に限っている。
確認の手順と残課題は [docs/HANDOFF.md](docs/HANDOFF.md) を参照。

### なぜ Windows 専用なのか

メーカーが提供しているのは Windows 用のドライバ（WinUSB を使う INF）と `TUSBADMH.DLL` だけで、
Python サンプルもこの DLL を ctypes で呼んでいるだけである（readme に「Windowsのみの対応」と明記）。
取扱説明書（TUSB0216ADMH_M2.pdf）に書かれているのも DLL の API だけで、USB の通信仕様は載っていない。

一方、デバイス自体は Vendor 固有クラスの単純な構成で、特別なクラスドライバを必要としない。
そのため、通信内容さえ分かれば Linux から libusb で操作できる。

| 項目 | 値（`lsusb -v` で実測） |
| --- | --- |
| VID:PID | `0ba0:0024`（製品文字列は `TUSB-0212ADMx`。ADM 系で共通の PID と思われる） |
| 速度 | Full Speed（USB 1.1、12 Mbps） |
| インタフェース | 1 個、class 0（vendor） |
| エンドポイント | Bulk OUT `0x02` / Bulk IN `0x81`、どちらも 64 B |

帯域にも問題はない。マニュアルが想定する連続取り込みは 2ch で 100 kS/s（約 400 kB/s）なので、
Full Speed の Bulk 転送で足りる。

## セットアップ

```bash
# pyusb（コンテナの venv に入れる）
pip install pyusb

# ホスト側（初回のみ。コンテナの外で、普通のユーザーとして実行する）
./udev/setup_udev.sh
```

`setup_udev.sh` は、udev ルールの設置（または更新）、udev の再読み込み、接続中のユニットが root 以外から
開けるかの確認までを行う。`sudo` が必要な手順ではパスワードを聞かれる。
最後に `OK /dev/bus/usb/...` と出れば完了で、`FAIL` が出たら USB を抜き差ししてもう一度実行する。
外すときは `./udev/setup_udev.sh --uninstall`。

コンテナは `/dev` をマウントしているが、既定のデバイスノードは `root:root 0664` なので、
コンテナの `ros` ユーザーからは開けない（`Access denied` になる。2026-10-20 に確認）。
そのため udev ルールで `0666` にする。

## 使い方

```bash
# 接続確認（読み取り専用。デバイスへの書き込みは一切しない）
ros2 run tusb_0216admh_ros2 tusb_probe.py --claim

# 実機で2秒取り込んで確認する（DIO 出力は触らない）
ros2 run tusb_0216admh_ros2 tusb_selftest.py --id 0

# 実機でノードを動かす（device_id は背面の ID スイッチに合わせる）
ros2 launch tusb_0216admh_ros2 tusb_0216admh.launch.py backend:=usb

# 模擬デバイスでノードを動かす
ros2 launch tusb_0216admh_ros2 tusb_0216admh.launch.py backend:=mock
ros2 topic echo /tusb_0216admh/adc_block --field sample_rate_hz
```

### トピック

`~/adc_block`（`tusb_0216admh_ros2/msg/AdcBlock`）: 連続したサンプルのブロック。

- `ch1_v` / `ch2_v` は電圧（V）。生のカウント値からの変換は `conversion.py` の1か所だけで行う。
  変換式は `V = raw × 2 V / 65536 + offset`（offset はバイポーラで −1 V、ユニポーラで 0 V）。
- `first_sample_index` はトリガからのサンプル番号。抜けなく連番で配信する。
- `header.stamp` は先頭サンプルの推定時刻。トリガ時刻をホストの時計で測っているため、
  絶対時刻には約1ポーリング周期の誤差がある。サンプル間隔は正確。
- FIFO がオーバーフローしたら、欠損したデータを配信しないように取り込みを止めてノードを終了する。

### パラメータ

[config/tusb_0216admh.yaml](config/tusb_0216admh.yaml) を参照。サンプルレートは次の式で決まる。

```text
1ch あたりのサンプルレート = クロック源 / (clock_divider + 1) / 2^averaging_exponent
```

ここで `クロック源 / (clock_divider + 1)` は 1〜25 MHz の範囲に収める必要がある。

既定値は 1 MHz / 256 = 3906.25 Hz。立ち上げ用の暫定値で、実験向けに調整したものではない。
2ch で 100 kHz（ch1 だけなら 200 kHz）を超えると、連続取り込みが間に合わずに FIFO がオーバーフローする
可能性がある（マニュアル 5.6 による）。

## プロトコル解析の進め方

[docs/CAPTURE_GUIDE.md](docs/CAPTURE_GUIDE.md) を参照。

1. Windows PC で `windows/capture_session.py` を実行し、そのあいだの通信を USBPcap で記録する。
2. 記録したファイルを `analyze_usb_capture.py` に通し、API の呼び出しと通信を並べて表示する。
3. 特定したコマンドを `usb_device.py` に実装する。結果は [docs/PROTOCOL.md](docs/PROTOCOL.md) にまとめてある。

## テスト

```bash
colcon build --packages-select tusb_0216admh_ros2 --cmake-args -DBUILD_TESTING=ON
colcon test --packages-select tusb_0216admh_ros2 && colcon test-result --verbose
```

## 出典

- 取扱説明書 TUSB0216ADMH_M2.pdf（第 8c 版、2025 年 5 月）: 定数、変換式、API の仕様
- ベンダ Python サンプル ADMHSmplPy（2024-06-05）: API の引数と戻り値
- USB ディスクリプタ: OnoLab の実機で `lsusb -v` を実行して確認（2026-10-20）
