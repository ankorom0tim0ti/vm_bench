# Cross OS Python Benchmarks

Linux on VMware と Windows ネイティブ環境を、同じ Python コードで比較するためのベンチマークです。

## セットアップ

```bash
python -m pip install -r requirements.txt
```

## 実行

```bash
python src/bench_runner.py --config bench_config.yaml
```

ベンチ条件は `bench_config.yaml` に定義します。CPUコア数、DRAM使用量の仕様上限、ループ回数、ファイル数なども YAML 側で変更してください。

## ベンチマーク内容

- `cpu`: 複数プロセスで64bit整数演算を大量に実行します。
- `file`: 複数プロセスで小さいファイルの作成、書き込み、`fsync`、読み取り、`stat` を大量に実行します。

結果は `results/` に JSON と CSV で出力されます。

## 番号付きバージョン

- `src/00_bench_runner.py` / `00_bench_config.yaml`: 最初の版です。`file.root_dir` が空の場合はOS既定の一時ディレクトリを使います。
- `src/01_bench_runner_disk.py` / `01_bench_config_disk.yaml`: ファイル系ベンチで実ディスク上のディレクトリ指定を必須にした版です。Linuxで `tmpfs` / `ramfs` / `devtmpfs` などのメモリ上ファイルシステムを検出した場合は実行を拒否します。
- `src/02_bench_runner_disk_affinity.py` / `02_bench_config_disk_affinity.yaml`: `01_` 版にCPU affinity指定を追加した版です。workerごとに指定した論理CPU/vCPUへ固定します。
- `src/03_bench_runner_project_temp_affinity.py` / `03_bench_config_project_temp_affinity.yaml`: `02_` 版のCPU affinity機能を残しつつ、ファイル系ベンチの作業場所をプロジェクト内の `temp_dir/` にした版です。`temp_dir/` は `.gitignore` 対象です。

実ディスク比較では `01_` 版を使ってください。

```bash
python src/01_bench_runner_disk.py --config 01_bench_config_disk.yaml
```

Linux VM では、`01_bench_config_disk.yaml` の `file.root_dir` を `/var/tmp/gcl_disk_bench` やホームディレクトリ配下など、仮想ディスク上のパスに変更してください。`/tmp` が `tmpfs` の環境では使わないでください。

CPUを固定して比較する場合は `02_` 版を使います。

```bash
python src/02_bench_runner_disk_affinity.py --config 02_bench_config_disk_affinity.yaml
```

`cpu_affinity` には使用する論理CPU IDを指定します。Linux VMではゲストから見える vCPU ID、Windows NativeではWindowsから見える論理CPU IDです。これはCPU affinityの指定であり、OSからCPUを完全に占有するものではありません。

プロジェクト内の `temp_dir/` を使ってファイル系を比較する場合は `03_` 版を使います。

```bash
python src/03_bench_runner_project_temp_affinity.py --config 03_bench_config_project_temp_affinity.yaml
```

## 調整の目安

Windows ネイティブの Core i9-14900K で 10-30 秒程度に寄せる初期値にしていますが、環境差が大きい場合は以下を調整してください。

- CPUが短すぎる場合: `cpu.iterations_per_worker` を増やす
- CPUが長すぎる場合: `cpu.iterations_per_worker` を減らす
- ファイル系が短すぎる場合: `file.files_per_worker` または `file.read_repeats` を増やす
- ファイル系が長すぎる場合: `file.files_per_worker` を減らす
