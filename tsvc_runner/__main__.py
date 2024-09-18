import argparse
import multiprocessing as mp
import shutil
import subprocess
from collections import defaultdict
from collections.abc import Generator
from dataclasses import dataclass
from os import path

import yaml
from colorama import Fore, Style, just_fix_windows_console


def build_tsvc(tsvc_root: str, makefile_path: str, build_all: bool):
    shutil.copyfile(
        makefile_path, path.join(tsvc_root, "makefiles/Makefile.tsvc-runner")
    )
    if build_all:
        subprocess.run(["make", "clean"], cwd=tsvc_root)
    subprocess.run(["make", "COMPILER=tsvc-runner", "VEC_REPORT=1"], cwd=tsvc_root)


def parse_opt_record(file_path: str) -> list[dict]:
    class ClangOptRecordLoader(yaml.SafeLoader):
        pass

    for tag in ["!AnalysisFPCommute", "!Missed", "!Passed", "!Analysis"]:
        ClangOptRecordLoader.add_constructor(
            tag, ClangOptRecordLoader.construct_mapping
        )

    with open(file_path) as f:
        return list(yaml.load_all(f, ClangOptRecordLoader))


def check_vectorization_status(parsed_record: list[dict]) -> dict[str, bool]:
    vectorization_status = defaultdict(lambda: False)
    for entry in parsed_record:
        if "Function" not in entry:
            continue
        function_name = entry["Function"]

        if entry.get("Pass") not in ["loop-vectorize", "slp-vectorize"]:
            continue
        vectorization_status[function_name] |= entry.get("Name") == "Vectorized"

    return vectorization_status


@dataclass
class BenchmarkOutput:
    function_name: str
    duration: float
    checksum: str

    @classmethod
    def from_output_line(cls, line: bytes):
        line_stripped = line.decode().strip()
        line_split = line_stripped.split()
        return cls(line_split[0], float(line_split[1]), line_split[2])


def run_benchmark(binary_path: str, output_queue: mp.SimpleQueue):
    proc = subprocess.Popen(
        ["stdbuf", "-o0", binary_path], stdout=subprocess.PIPE, stderr=subprocess.STDOUT
    )
    for line in proc.stdout:  # type: ignore
        if line.startswith(b"Loop"):
            continue
        output_queue.put(BenchmarkOutput.from_output_line(line))
    output_queue.put(None)


def run_benchmarks(
    tsvc_root: str,
) -> Generator[tuple[BenchmarkOutput, BenchmarkOutput]]:
    binary_root = path.join(tsvc_root, "bin/tsvc-runner")
    novec_binary_path = path.join(binary_root, "tsvc_novec_default")
    vec_binary_path = path.join(binary_root, "tsvc_vec_default")

    novec_queue = mp.SimpleQueue()
    vec_queue = mp.SimpleQueue()
    novec_thread = mp.Process(
        target=run_benchmark, args=(novec_binary_path, novec_queue)
    )
    vec_thread = mp.Process(target=run_benchmark, args=(vec_binary_path, vec_queue))
    novec_thread.start()
    vec_thread.start()

    while True:
        novec_result = novec_queue.get()
        vec_result = vec_queue.get()
        if novec_result is None:
            break

        yield (novec_result, vec_result)

    novec_thread.join()
    vec_thread.join()


if __name__ == "__main__":
    just_fix_windows_console()
    parser = argparse.ArgumentParser(prog="tsvc_runner")
    parser.add_argument(
        "--tsvc-root",
        type=str,
        help="root directory for TSVC",
        default="./TSVC_2",
        dest="tsvc_root",
    )
    parser.add_argument(
        "-m",
        "--makefile",
        type=str,
        help="user-specified makefile for building TSVC",
        default="./Makefile",
        dest="makefile",
    )
    parser.add_argument(
        "-B", help="rebuild all", action="store_true", dest="rebuild_all"
    )
    parsed = parser.parse_args()
    build_tsvc(parsed.tsvc_root, parsed.makefile, parsed.rebuild_all)

    default_opt_record = parse_opt_record(
        path.join(parsed.tsvc_root, "src/tsvc_vec.o_default.opt.yml")
    )
    vectorization_status = check_vectorization_status(default_opt_record)
    for novec_result, vec_result in run_benchmarks(parsed.tsvc_root):
        assert novec_result.function_name == vec_result.function_name

        function_name = novec_result.function_name
        print(f"{function_name}:\t", end="")

        if novec_result.checksum == vec_result.checksum:
            print(f"OK\t", end="")
        else:
            print(f"{Fore.RED}MISMATCH\t{Style.RESET_ALL}", end="")

        if vectorization_status[function_name]:
            print(f"{Fore.GREEN}AUTOVEC\t{Style.RESET_ALL}", end="")
        else:
            print(f"{Fore.YELLOW}NOVEC\t{Style.RESET_ALL}", end="")

        speedup = novec_result.duration / vec_result.duration
        if speedup > 1:
            print(Fore.GREEN, end="")
        else:
            print(Fore.RED, end="")
        print(f"{speedup:1.3f}x SPEEDUP{Style.RESET_ALL}")
