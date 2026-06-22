# Benchmark Specification

このドキュメントは、本プロジェクトで作成したベンチマークが何を実行し、どのような結果を出力するのかを説明するものです。

主な目的は、Windows Native 環境と Linux on VMware 環境で、同じ Python コードを使って CPU 処理とファイル I/O 処理の傾向を比較することです。

## 対象バージョン

現在の推奨版は次の組み合わせです。

```bash
python src/03_bench_runner_project_temp_affinity.py --config 03_bench_config_project_temp_affinity.yaml
```

`03_` 版は、以下の機能を含みます。

- CPUベンチマーク
- ファイル I/O ベンチマーク
- worker プロセスごとの CPU affinity 指定
- プロジェクト内の `temp_dir/` を使ったファイル作成、読み取り、削除
- 結果の JSON / CSV 出力

## 設定ファイル

ベンチマークの実行条件は、Python の起動引数ではなく YAML ファイルで指定します。

代表的な設定は次の通りです。

```yaml
benchmark: all
dram_limit_mb: 4096
output_dir: results

cpu_affinity: [0, 2, 4, 6, 8, 10, 12, 14]

cpu:
  worker_count: 8
  rounds: 3
  iterations_per_worker: 40000000

file:
  root_dir: temp_dir
  reject_memory_filesystems: true
  worker_count: 8
  rounds: 3
  files_per_worker: 2000
  file_size_bytes: 4096
  read_repeats: 2
  fsync_each_file: true
  cleanup: true
```

`benchmark` は、実行するベンチマークの種類を指定します。

- `all`: CPU と File I/O の両方を実行
- `cpu`: CPU ベンチマークのみ実行
- `file`: File I/O ベンチマークのみ実行

`cpu_affinity` は、worker プロセスを固定する論理 CPU ID の一覧です。Windows では Windows から見える論理 CPU ID、Linux VM ではゲスト OS から見える vCPU ID を指定します。

注意点として、CPU affinity は「このプロセスを指定 CPU 上で動かす」という指定であり、CPUを完全に占有するものではありません。他のプロセスが同じ CPU を使う可能性は残ります。

## 実行方式

このベンチマークでは、Python の `ProcessPoolExecutor` を使って複数の worker プロセスを起動します。

スレッドではなくプロセスを使う理由は、Python の GIL の影響を避けるためです。GIL は、1つの Python プロセス内で複数スレッドが同時に Python バイトコードを実行することを制限します。複数プロセスに分けることで、複数 CPU コアを使いやすくしています。

## CPU ベンチマーク

CPU ベンチマークでは、各 worker プロセスが大量の整数計算を行います。

### 処理の流れ

1. 設定された `worker_count` の数だけ worker プロセスを起動します。
2. 各 worker に CPU affinity を設定します。
3. 各 worker が `iterations_per_worker` 回のループを実行します。
4. ループ内で 64bit 相当の整数演算を繰り返します。
5. 各 worker が計算結果の checksum を返します。
6. 全 worker の完了までの経過時間を測定します。

### 実際に行う計算

各 worker は、次のような処理を大量に繰り返します。

- 整数の乗算
- 整数の加算
- XOR 演算
- ビットシフト
- 64bit 幅に収めるためのマスク処理

処理のイメージは次のようなものです。

```text
x = x * 大きな定数 + 別の定数 + ループ番号
y = y XOR ビットシフトした x
y = y * 大きな定数 + 別の定数
checksum = checksum + x と y を組み合わせた値
```

この処理は、行列計算や画像処理のような特定用途のアルゴリズムではありません。目的は、Python インタプリタ上で単純な CPU 計算を長時間走らせ、環境ごとの実行時間を比較することです。

### CPU ベンチマークが測っているもの

このベンチマークは、次の要素を含んだ実行時間を測っています。

- Python インタプリタの整数演算性能
- OS のプロセススケジューリング
- CPU affinity の効果
- CPU のクロック、ターボブースト、電力制御の影響
- VM 環境では、ゲスト OS とハイパーバイザのスケジューリングの影響

つまり、これは「CPU の理論性能」だけを測るものではありません。実際に Python プログラムを動かしたときの総合的な計算時間を測っています。

### CPU ベンチマークの結果項目

CPU ベンチマークの結果には、主に次の項目が出力されます。

- `elapsed_seconds`: その round にかかった秒数
- `worker_count`: 起動した worker プロセス数
- `iterations`: 全 worker の合計ループ回数
- `iterations_per_second`: 1秒あたりのループ回数
- `requested_cpu_affinity`: 設定ファイルで要求した CPU ID
- `actual_worker_cpu_affinity`: 実際に各 worker に設定された CPU affinity
- `checksum`: 計算結果の確認用ハッシュ値

`checksum` は、Windows と Linux で同じ計算が行われたことを確認するために使います。同じ条件で実行している場合、checksum は一致するはずです。

## File I/O ベンチマーク

File I/O ベンチマークでは、各 worker プロセスが多数の小さなファイルを作成し、書き込み、読み取り、ファイル情報取得を行います。

このベンチマークは、OS API やファイルシステムの処理性能を比較するためのものです。

### 作業ディレクトリ

`03_` 版では、ファイルベンチマークの作業場所としてプロジェクト内の `temp_dir/` を使います。

設定例:

```yaml
file:
  root_dir: temp_dir
```

この相対パスは、設定 YAML ファイルのあるディレクトリを基準に解決されます。

例えば、プロジェクトが次の場所にある場合:

```text
C:\Users\...\gcl_report
```

実際の作業場所は次のようになります。

```text
C:\Users\...\gcl_report\temp_dir
```

`temp_dir/` は `.gitignore` に登録されているため、ベンチマークで作成される一時ファイルは Git の管理対象になりません。

### 処理の流れ

1. `temp_dir/` を作成します。
2. round ごとの作業ディレクトリを作成します。
3. worker プロセスごとのサブディレクトリを作成します。
4. 各 worker が多数のファイルを作成します。
5. 各ファイルに一定サイズのバイナリデータを書き込みます。
6. 設定に応じて `fsync` を呼び出します。
7. 作成したファイルを読み取ります。
8. ファイルサイズなどの情報を `stat` で取得します。
9. round 終了後、設定に応じて作業ディレクトリを削除します。

### 作成されるファイル

各 worker は、自分専用のディレクトリを作ります。

例:

```text
temp_dir/
  round_1_20260621_222403/
    worker_000/
      file_000000.bin
      file_000001.bin
      ...
    worker_001/
      file_000000.bin
      file_000001.bin
      ...
```

デフォルト設定では、次の数のファイルを扱います。

```text
worker_count = 8
files_per_worker = 2000
合計ファイル数 = 8 * 2000 = 16000
```

各ファイルのサイズは `file_size_bytes` で指定します。デフォルトでは 4096 bytes です。

### 書き込み処理

各 worker は、ファイルごとに以下の処理を行います。

1. ファイルパスを作る
2. ファイルをバイナリ書き込みモードで開く
3. 決められたサイズのデータを書き込む
4. `fsync_each_file: true` の場合、`flush` と `os.fsync` を実行する
5. ファイルを閉じる

`fsync` は、OSに対して「このファイルの内容をストレージ側へ反映してほしい」と要求する処理です。通常の書き込みだけでは、データがOSのキャッシュに残ることがあります。`fsync` を呼ぶことで、より実ディスクに近い I/O コストを含めることを狙っています。

ただし、VMware などの仮想環境では、ゲスト OS の `fsync` がホスト OS や仮想ディスクのキャッシュによってどの程度物理ディスクまで反映されるかは、仮想化設定にも依存します。

### 読み取り処理

書き込みが終わったあと、各 worker は自分が作成したファイルを読み取ります。

読み取り回数は `read_repeats` で指定します。

デフォルトでは次の通りです。

```yaml
read_repeats: 2
```

つまり、各ファイルを2回読みます。読み取ったデータの一部は digest 計算に使われます。これは、読み取り処理が実際に行われたことを確認するためです。

### stat 処理

読み取り後、各 worker はすべてのファイルに対して `stat` を呼び出します。

`stat` は、ファイルサイズ、更新時刻、属性などのメタデータを取得するOS APIです。このベンチマークでは主にファイルサイズを読み取り、メタデータ取得のコストも測定に含めています。

大量の小さなファイルを扱う場合、データ本体の読み書きだけでなく、ファイル作成、ディレクトリエントリ更新、メタデータ取得のコストが大きくなります。

### 削除処理

`cleanup: true` の場合、各 round の最後に作業ディレクトリを削除します。

削除対象は round ごとのディレクトリです。

```text
temp_dir/round_...
```

`temp_dir/` 自体は残る場合がありますが、中のベンチマーク用ファイルは round ごとに削除されます。

### File I/O ベンチマークが測っているもの

このベンチマークは、次の要素を含んだ実行時間を測っています。

- ファイル作成のコスト
- 小さいファイルへの書き込みコスト
- `fsync` のコスト
- ファイル読み取りのコスト
- `stat` によるメタデータ取得コスト
- 多数のファイルを扱うときのディレクトリ操作コスト
- OS のファイルシステム実装の違い
- ウイルス対策ソフトやリアルタイムスキャンの影響
- VM 環境では、仮想ディスクとホストOSキャッシュの影響

### File I/O ベンチマークの結果項目

File I/O ベンチマークの結果には、主に次の項目が出力されます。

- `elapsed_seconds`: その round 全体にかかった秒数
- `worker_count`: 起動した worker プロセス数
- `file_base_dir`: ベンチマークが使用した作業ディレクトリ
- `file_filesystem_type`: Linux で検出できたファイルシステム種別
- `file_count`: 作成したファイル数
- `bytes_written`: 書き込んだ合計バイト数
- `bytes_read`: 読み取った合計バイト数
- `write_seconds_max`: 最も遅かった worker の書き込み時間
- `read_seconds_max`: 最も遅かった worker の読み取り時間
- `stat_seconds_max`: 最も遅かった worker の stat 時間
- `write_mib_per_second`: 全体時間に対する書き込み MiB/s
- `read_mib_per_second`: 全体時間に対する読み取り MiB/s
- `digest`: 読み取った内容の確認用ハッシュ値

`file_filesystem_type` は、Linux では `/proc/mounts` を使って検出します。Windows では同じ仕組みがないため、通常は `unknown` になります。

## メモリ上ファイルシステムの検出

Linux では `/tmp` が `tmpfs` になっている場合があります。`tmpfs` はメモリ上のファイルシステムであり、実ディスクへの I/O とは性質が大きく異なります。

このベンチマークでは、`reject_memory_filesystems: true` の場合、次のようなファイルシステムを検出すると実行を停止します。

- `tmpfs`
- `ramfs`
- `devtmpfs`
- `zram`

これにより、意図せずRAM上のファイルシステムを測定してしまうことを避けます。

## 結果ファイル

実行結果は `results/` に出力されます。

出力形式は2種類です。

- JSON
- CSV

ファイル名には実行時刻が含まれます。

例:

```text
results/bench_results_20260621_222403.json
results/bench_results_20260621_222403.csv
```

JSON には、各 round の詳細結果と summary が含まれます。

summary には、各ベンチマークの最小値、平均値、中央値、最大値が記録されます。

## 比較時の注意点

このベンチマークは、Windows Native と Linux on VMware の傾向を比較するためのものですが、結果を解釈するときには注意が必要です。

CPU ベンチマークでは、次の要素が結果に影響します。

- CPU affinity の指定
- P-core / E-core / SMT の割り当て
- CPU の電力設定
- Python の Windows ビルドと Linux ビルドの違い
- VM の vCPU がホスト側でどの物理CPUに割り当てられるか

File I/O ベンチマークでは、次の要素が結果に影響します。

- NTFS、ext4 などのファイルシステム差
- 実ディスク、仮想ディスク、ホストOSキャッシュの違い
- Windows Defender などのリアルタイムスキャン
- VMware の仮想ディスク設定
- `fsync` がどこまで実際の物理ディスク反映を待つか

そのため、結果は「CPU単体の理論性能」や「SSD単体の理論性能」ではありません。実際のOS、Python、ファイルシステム、仮想化環境を含めた総合的な実行時間として扱ってください。

## 再現性を上げるための推奨事項

比較の再現性を上げるには、次の点を揃えることを推奨します。

- 同じ Python バージョンを使う
- 同じ `iterations_per_worker` を使う
- 同じ `worker_count` を使う
- CPU affinity を明示する
- Windows ではP-coreの片方のSMTスレッドだけを使う
- Linux VM では vCPU 数を明示する
- ファイルベンチでは同じプロジェクト内の `temp_dir/` を使う
- 他の重いアプリケーションを停止する
- Windows Defender などのリアルタイムスキャンの影響を考慮する
- ノートPCではなく、電源設定が安定した状態で実行する

## このベンチマークで確認したいこと

このベンチマークで確認したい主な観点は、次の2つです。

1. Python の単純なCPU計算が、Windows Native と Linux on VMware でどの程度違うか
2. 多数の小さなファイルを扱う File I/O が、Windows Native と Linux on VMware でどの程度違うか

特に File I/O ベンチマークは、大きな1ファイルを連続読み書きするベンチマークではありません。小さなファイルを大量に扱うため、OS API、ファイルシステム、メタデータ操作の差が出やすい内容になっています。
