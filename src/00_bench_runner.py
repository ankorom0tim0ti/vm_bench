from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
import platform
import shutil
import statistics
import tempfile
import time
from concurrent.futures import ProcessPoolExecutor
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml


MASK64 = (1 << 64) - 1


@dataclass(frozen=True)
class CpuBenchConfig:
    worker_count: int
    iterations_per_worker: int
    rounds: int


@dataclass(frozen=True)
class FileBenchConfig:
    root_dir: str
    worker_count: int
    rounds: int
    files_per_worker: int
    file_size_bytes: int
    read_repeats: int
    fsync_each_file: bool
    cleanup: bool


@dataclass(frozen=True)
class BenchConfig:
    benchmark: str
    dram_limit_mb: int
    output_dir: str
    cpu: CpuBenchConfig
    file: FileBenchConfig


def load_config(path: Path) -> BenchConfig:
    with path.open("r", encoding="utf-8") as f:
        raw = yaml.safe_load(f) or {}

    cpu = raw.get("cpu", {})
    file_cfg = raw.get("file", {})
    return BenchConfig(
        benchmark=str(raw.get("benchmark", "all")),
        dram_limit_mb=int(raw.get("dram_limit_mb", 4096)),
        output_dir=str(raw.get("output_dir", "results")),
        cpu=CpuBenchConfig(
            worker_count=int(cpu.get("worker_count", os.cpu_count() or 1)),
            iterations_per_worker=int(cpu.get("iterations_per_worker", 40_000_000)),
            rounds=int(cpu.get("rounds", 3)),
        ),
        file=FileBenchConfig(
            root_dir=str(file_cfg.get("root_dir", "")),
            worker_count=int(file_cfg.get("worker_count", min(os.cpu_count() or 1, 8))),
            rounds=int(file_cfg.get("rounds", 3)),
            files_per_worker=int(file_cfg.get("files_per_worker", 2_000)),
            file_size_bytes=int(file_cfg.get("file_size_bytes", 4096)),
            read_repeats=int(file_cfg.get("read_repeats", 2)),
            fsync_each_file=bool(file_cfg.get("fsync_each_file", True)),
            cleanup=bool(file_cfg.get("cleanup", True)),
        ),
    )


def validate_config(config: BenchConfig) -> None:
    if config.benchmark not in {"all", "cpu", "file"}:
        raise ValueError("benchmark must be one of: all, cpu, file")
    if config.dram_limit_mb <= 0:
        raise ValueError("dram_limit_mb must be positive")
    if config.cpu.worker_count <= 0 or config.file.worker_count <= 0:
        raise ValueError("worker_count must be positive")
    if config.cpu.iterations_per_worker <= 0:
        raise ValueError("cpu.iterations_per_worker must be positive")
    if config.cpu.rounds <= 0 or config.file.rounds <= 0:
        raise ValueError("rounds must be positive")
    if config.file.files_per_worker <= 0:
        raise ValueError("file.files_per_worker must be positive")
    if config.file.file_size_bytes <= 0:
        raise ValueError("file.file_size_bytes must be positive")
    if config.file.read_repeats <= 0:
        raise ValueError("file.read_repeats must be positive")

    file_bytes = (
        config.file.worker_count
        * config.file.files_per_worker
        * config.file.file_size_bytes
    )
    if file_bytes > config.dram_limit_mb * 1024 * 1024:
        raise ValueError(
            "file benchmark writes more bytes than dram_limit_mb. "
            "Raise dram_limit_mb or reduce file.worker_count/files_per_worker/file_size_bytes."
        )


def cpu_worker(worker_index: int, iterations: int) -> int:
    x = (0x9E3779B97F4A7C15 + worker_index) & MASK64
    y = (0xBF58476D1CE4E5B9 ^ worker_index) & MASK64
    checksum = 0

    for i in range(iterations):
        x = (x * 6364136223846793005 + 1442695040888963407 + i) & MASK64
        y ^= ((x >> 23) | (x << 41)) & MASK64
        y = (y * 0x94D049BB133111EB + 0xD2B74407B1CE6E93) & MASK64
        checksum = (checksum + (x ^ y ^ i)) & MASK64

    return checksum


def run_cpu_round(config: CpuBenchConfig) -> dict[str, Any]:
    started = time.perf_counter()
    with ProcessPoolExecutor(max_workers=config.worker_count) as executor:
        checksums = list(
            executor.map(
                cpu_worker,
                range(config.worker_count),
                [config.iterations_per_worker] * config.worker_count,
            )
        )
    elapsed = time.perf_counter() - started
    total_iterations = config.worker_count * config.iterations_per_worker
    return {
        "elapsed_seconds": elapsed,
        "worker_count": config.worker_count,
        "iterations": total_iterations,
        "iterations_per_second": total_iterations / elapsed,
        "checksum": f"{sum(checksums) & MASK64:016x}",
    }


def file_worker(
    worker_index: int,
    root_dir: str,
    files_per_worker: int,
    file_size_bytes: int,
    read_repeats: int,
    fsync_each_file: bool,
) -> dict[str, Any]:
    worker_dir = Path(root_dir) / f"worker_{worker_index:03d}"
    worker_dir.mkdir(parents=True, exist_ok=True)
    payload_seed = hashlib.blake2b(str(worker_index).encode("ascii"), digest_size=32).digest()
    bytes_written = 0
    digest = hashlib.blake2b(digest_size=16)

    write_started = time.perf_counter()
    for i in range(files_per_worker):
        payload = (payload_seed + i.to_bytes(8, "little")) * (
            file_size_bytes // 40 + 1
        )
        data = payload[:file_size_bytes]
        path = worker_dir / f"file_{i:06d}.bin"
        with path.open("wb") as f:
            f.write(data)
            if fsync_each_file:
                f.flush()
                os.fsync(f.fileno())
        bytes_written += len(data)
    write_elapsed = time.perf_counter() - write_started

    read_started = time.perf_counter()
    bytes_read = 0
    for _ in range(read_repeats):
        for i in range(files_per_worker):
            path = worker_dir / f"file_{i:06d}.bin"
            data = path.read_bytes()
            digest.update(data[:64])
            digest.update(data[-64:])
            bytes_read += len(data)
    read_elapsed = time.perf_counter() - read_started

    stat_started = time.perf_counter()
    stat_count = 0
    for i in range(files_per_worker):
        path = worker_dir / f"file_{i:06d}.bin"
        stat_count += path.stat().st_size
    stat_elapsed = time.perf_counter() - stat_started

    return {
        "bytes_written": bytes_written,
        "bytes_read": bytes_read,
        "write_seconds": write_elapsed,
        "read_seconds": read_elapsed,
        "stat_seconds": stat_elapsed,
        "stat_count": stat_count,
        "digest": digest.hexdigest(),
    }


def run_file_round(config: FileBenchConfig, round_index: int) -> dict[str, Any]:
    base_dir = (
        Path(config.root_dir)
        if config.root_dir
        else Path(tempfile.gettempdir()) / "python_cross_os_bench"
    )
    root_dir = base_dir / f"round_{round_index}_{time.strftime('%Y%m%d_%H%M%S')}"
    root_dir.mkdir(parents=True, exist_ok=True)

    started = time.perf_counter()
    try:
        with ProcessPoolExecutor(max_workers=config.worker_count) as executor:
            results = list(
                executor.map(
                    file_worker,
                    range(config.worker_count),
                    [str(root_dir)] * config.worker_count,
                    [config.files_per_worker] * config.worker_count,
                    [config.file_size_bytes] * config.worker_count,
                    [config.read_repeats] * config.worker_count,
                    [config.fsync_each_file] * config.worker_count,
                )
            )
    finally:
        if config.cleanup:
            shutil.rmtree(root_dir, ignore_errors=True)

    elapsed = time.perf_counter() - started
    bytes_written = sum(r["bytes_written"] for r in results)
    bytes_read = sum(r["bytes_read"] for r in results)
    return {
        "elapsed_seconds": elapsed,
        "worker_count": config.worker_count,
        "file_count": config.worker_count * config.files_per_worker,
        "bytes_written": bytes_written,
        "bytes_read": bytes_read,
        "write_seconds_max": max(r["write_seconds"] for r in results),
        "read_seconds_max": max(r["read_seconds"] for r in results),
        "stat_seconds_max": max(r["stat_seconds"] for r in results),
        "write_mib_per_second": bytes_written / 1024 / 1024 / elapsed,
        "read_mib_per_second": bytes_read / 1024 / 1024 / elapsed,
        "digest": hashlib.blake2b(
            "".join(r["digest"] for r in results).encode("ascii"), digest_size=16
        ).hexdigest(),
    }


def summarize(name: str, rounds: list[dict[str, Any]]) -> dict[str, Any]:
    elapsed = [r["elapsed_seconds"] for r in rounds]
    return {
        "benchmark": name,
        "rounds": len(rounds),
        "elapsed_seconds_min": min(elapsed),
        "elapsed_seconds_mean": statistics.fmean(elapsed),
        "elapsed_seconds_median": statistics.median(elapsed),
        "elapsed_seconds_max": max(elapsed),
    }


def write_results(output_dir: Path, rows: list[dict[str, Any]], summary: list[dict[str, Any]]) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    timestamp = time.strftime("%Y%m%d_%H%M%S")
    json_path = output_dir / f"bench_results_{timestamp}.json"
    csv_path = output_dir / f"bench_results_{timestamp}.csv"

    with json_path.open("w", encoding="utf-8") as f:
        json.dump({"rounds": rows, "summary": summary}, f, indent=2)

    fieldnames = sorted({key for row in rows for key in row.keys()})
    with csv_path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)

    print(f"wrote {json_path}")
    print(f"wrote {csv_path}")


def system_info() -> dict[str, Any]:
    return {
        "platform": platform.platform(),
        "python": platform.python_version(),
        "processor": platform.processor(),
        "cpu_count": os.cpu_count(),
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", default="bench_config.yaml")
    args = parser.parse_args()

    config = load_config(Path(args.config))
    validate_config(config)

    rows: list[dict[str, Any]] = []
    summaries: list[dict[str, Any]] = []
    info = system_info()

    if config.benchmark in {"all", "cpu"}:
        cpu_rounds = []
        for round_index in range(config.cpu.rounds):
            result = run_cpu_round(config.cpu)
            result.update(info)
            result.update({"benchmark": "cpu", "round": round_index + 1})
            cpu_rounds.append(result)
            rows.append(result)
            print(
                f"cpu round {round_index + 1}/{config.cpu.rounds}: "
                f"{result['elapsed_seconds']:.3f}s, checksum={result['checksum']}"
            )
        summaries.append(summarize("cpu", cpu_rounds))

    if config.benchmark in {"all", "file"}:
        file_rounds = []
        for round_index in range(config.file.rounds):
            result = run_file_round(config.file, round_index + 1)
            result.update(info)
            result.update({"benchmark": "file", "round": round_index + 1})
            file_rounds.append(result)
            rows.append(result)
            print(
                f"file round {round_index + 1}/{config.file.rounds}: "
                f"{result['elapsed_seconds']:.3f}s, files={result['file_count']}"
            )
        summaries.append(summarize("file", file_rounds))

    print(json.dumps(summaries, indent=2))
    write_results(Path(config.output_dir), rows, summaries)


if __name__ == "__main__":
    main()
