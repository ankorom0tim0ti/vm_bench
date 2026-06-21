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

## 調整の目安

Windows ネイティブの Core i9-14900K で 10-30 秒程度に寄せる初期値にしていますが、環境差が大きい場合は以下を調整してください。

- CPUが短すぎる場合: `cpu.iterations_per_worker` を増やす
- CPUが長すぎる場合: `cpu.iterations_per_worker` を減らす
- ファイル系が短すぎる場合: `file.files_per_worker` または `file.read_repeats` を増やす
- ファイル系が長すぎる場合: `file.files_per_worker` を減らす
