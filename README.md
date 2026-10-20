# tusb_0216admh_ros2

タートル工業の USB AD コンバータ [TUSB-0216ADMH](https://www.turtle-ind.co.jp/products/ad-converters/tusb-0216admh/)
（16bit、2ch、最大 25 MHz）を ROS 2 Humble から読むドライバ。
Windows を使わず、Linux から libusb（pyusb）で直接デバイスを操作することを目指している。

## 現状

| 項目 | 状態 |
| --- | --- |
| USB の列挙・ディスクリプタ取得・インタフェースの claim | 実装済み（`tusb_probe.py`）。実機で確認済み（文字列ディスクリプタ、claim、IN の受信待ち。何も送らなければ IN には何も来ない） |
| USB コマンド（設定・取り込み開始・データ取得） | **未実装。** プロトコルが非公開のため、Windows でのキャプチャ解析待ち（[docs/CAPTURE_GUIDE.md](docs/CAPTURE_GUIDE.md)） |
| ROS ノード・メッセージ・launch | 実装済み。`backend:=mock`（模擬の正弦波）で確認できる |
| キャプチャ解析ツール | 実装済み（`analyze_usb_capture.py`、USBPcap / usbmon 対応） |

`backend:=usb` で起動すると、現状は最初のコマンドで `NotImplementedError` になって終了する。
推測したバイト列をデバイスに送ることはしない。

### なぜ Windows 専用なのか

メーカーが提供しているのは Windows 用のカーネルドライバと `TUSBADMH.DLL` だけで、
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

# ホスト側（初回のみ）: root 以外から libusb で開けるようにする
sudo cp udev/99-tusb-0216admh.rules /etc/udev/rules.d/
sudo udevadm control --reload-rules && sudo udevadm trigger
```

コンテナは `/dev` をマウントしているが、既定のデバイスノードは `root:root 0664` なので、
コンテナの `ros` ユーザーからは開けない（`Access denied` になる。2026-10-20 に確認）。
そのため udev ルールで `0666` にする。

## 使い方

```bash
# 接続確認（読み取り専用。デバイスへの書き込みは一切しない）
ros2 run tusb_0216admh_ros2 tusb_probe.py --claim

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
2. 記録したファイルを Linux 側の `analyze_usb_capture.py` に通し、API の呼び出しと通信を並べて表示する。
3. 特定したコマンドで、`usb_device.py` の `NotImplementedError` を置き換える。

## テスト

```bash
colcon build --packages-select tusb_0216admh_ros2 --cmake-args -DBUILD_TESTING=ON
colcon test --packages-select tusb_0216admh_ros2 && colcon test-result --verbose
```

## 出典

- 取扱説明書 TUSB0216ADMH_M2.pdf（第 8c 版、2025 年 5 月）: 定数、変換式、API の仕様
- ベンダ Python サンプル ADMHSmplPy（2024-06-05）: API の引数と戻り値
- USB ディスクリプタ: OnoLab の実機で `lsusb -v` を実行して確認（2026-10-20）
