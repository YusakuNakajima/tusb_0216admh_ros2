# TUSB-0216ADMH の USB プロトコル

公式ドライバ（TUSBADMH_261、`TUSBADMH.DLL` + WinUSB）を `windows/capture_session.py` で動かし、
USBPcap で記録した通信から読み取った（2026-10-20、1台を ID スイッチ 0 と 3 で記録）。
ドライバのバイナリは解析していない。実装は `tusb_0216admh/usb_device.py`。

## 形式

- コマンドは Bulk OUT `0x02` への1回の書き込み。1バイト目がコマンド番号。
- 応答は Bulk IN `0x81` に返り、1バイト目は同じコマンド番号（データ取得だけは例外で、サンプルだけが返る）。
- 2バイト以上の値はすべて big endian。`u24` は3バイト。

## コマンド

| 番号 | DLL の関数 | 送信 | 応答 |
| --- | --- | --- | --- |
| `0xF0` | Device_Open | `f0` | `f0 id`（背面の ID スイッチの値） |
| `0x10` | Dio_Read | `10` | `10 bits`（bit0–3 入力、bit4–7 出力の現在値） |
| `0x20` | Dio_Write | `20 bits` | `20` |
| `0x90` | InputType | `90 ch1 ch2` | `90` |
| `0xB0` | CheckInputType | `b0 00 00` | `b0 ch1 ch2` |
| `0x70` | Clock_Select | `70 (1<<ClkSel) Div Ave` | `70`（ClkSel 5 = 外部は `0x20`） |
| `0x80` | ThLevel_Set | `80 level(u16) noise(u16)` | `80` |
| `0x30` | Adc_Start | `30 CycLen(u24) PreLen(u24) TrgSel Mode` | `30` |
| `0xA0` | Trigger | `a0` | `a0` |
| `0x40` | Adc_Stop | `40` | `40` |
| `0x50` | （Status_Get / Length の元） | `50` | `50 state ch1数(u24) ch2数(u24)` |
| `0x60` | （Data_Get の元） | `60 数(u24) ch` | u16 のサンプル × 数（64 B ごとのパケットに分かれる） |

- **TransLimit** は USB に何も送らない。DLL が1回に読む量の上限にすぎない。
- **Adc_Start の CycLen** は Mode=1（繰り返し）のときだけ値が入り、Mode=0 では 0 が送られる。
- **Ch1Only** はデバイスに送られない。デバイスは ch2 の FIFO にも溜め続けるので、
  `usb_device.py` では ch2 を読み捨てている（放置すると約 1 Mi サンプルで ch2 がオーバーフローする）。

## `0x50` の state バイト

| bit | 意味 |
| --- | --- |
| 0 | 取り込み中（Adc_Start から Adc_Stop まで） |
| 1 | トリガ済み |
| 2 | ch1 FIFO オーバーフロー |
| 3 | ch2 FIFO オーバーフロー |

- DLL の Status は bit0=0 → 0（停止）、bit0 のみ → 1（トリガ待ち）、bit0+bit1 → 2（取り込み中）。
  OvfSt は bit2–3 をそのまま返す。
- オーバーフローすると新しいサンプルは入らなくなる（FIFO の数は読み出しで減るだけ）。
- ch1数 / ch2数はデバイス FIFO に溜まっているサンプル数。上限は約 2^20（観測値 0x100004）。

## DLL の動き

ほかのコマンドに ID は含まれない。DLL は Device_Open で各機器に `0xF0` を送り、ID スイッチの値が
引数と一致する機器を開いていると考えられる（ID 0 と 3 で、`0xF0` の応答以外のやり取りは同一だった）。

DLL は Adc_Start のあと裏のスレッドで約 15 ms ごとに `0x50` を送り、溜まっている分を `0x60` で
PC 側のバッファに移す。`Tusbadmh_Length` と `Tusbadmh_Data_Get` はこの PC 側バッファを見ている。
観測した1回の要求は最大 896 サンプル。`usb_device.py` はバッファを持たず、デバイス FIFO を
直接読む（1回 512 サンプルまで）。

## 未確認

- Mode=1（繰り返し）と外部トリガ・アナログトリガでの実際の取り込み（コマンドの形式だけ確認済み）。
- 1回の `0x60` で要求できる最大数。
