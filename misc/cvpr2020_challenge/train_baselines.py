"""Simple baselines for the CVPR2020 video pentathlon challenge

%run -i misc/cvpr2020_challenge/train_baselines.py --mini_train --train_single_epoch
ipy misc/cvpr2020_challenge/train_baselines.py -- --mini_train --train_single_epoch --yaspify
"""

import sys
import json
import argparse
from typing import Dict, List
from pathlib import Path
from datetime import datetime
from subprocess import PIPE, Popen
from yaspi.yaspi import Yaspi

from typeguard import typechecked

from misc.cvpr2020_challenge.prepare_submission import generate_predictions


@typechecked
def filter_cmd_args(cmd_args: List[str], remove: List[str]) -> List[str]:
    drop = []
    for key in remove:
        if key not in cmd_args:
            continue
        pos = cmd_args.index(key)
        drop.append(pos)
        if len(cmd_args) > (pos + 1) and not cmd_args[pos + 1].startswith("--"):
            drop.append(pos + 1)
    for pos in reversed(drop):
        cmd_args.pop(pos)
    return cmd_args


@typechecked
def launch_and_monitor_cmd(cmd: str) -> List:
    lines = []
    with Popen(cmd.split(), stdout=PIPE, bufsize=1, universal_newlines=True) as proc:
        for line in proc.stdout:
            print(line, end='')
            lines.append(line)
    return lines


@typechecked
def parse_paths_from_logs(logs: List[str]) -> Dict[str, Path]:
    prefixes = {
        "predictions": "Saved similarity matrix predictions to",
        "ckpts": "The best performing ckpt can be found at",
    }
    paths = {}
    for key, prefix in prefixes.items():
        matches = [x.startswith(prefix) for x in logs]
        found = sum(matches)
        assert found == 1, f"Expected to find one match for `{prefix}`, found {found}"
        pos = matches.index(True)
        paths[key] = Path(logs[pos].rstrip().split(" ")[-1])
    return paths


@typechecked
def train_baselines(
        dest_dir: Path,
        challenge_config_dir: Path, 
        datasets: List[str],
        timestamp: str,
        mini_train: bool,
        train_single_epoch: bool,
        device: int,
        aggregate: bool = False,
):
    challenge_phase = "public_server_val"
    fname = f"baselines-{timestamp}-{challenge_phase}-{'-'.join(datasets)}.json"
    outputs = {key: {} for key in ("predictions", "ckpts")}
    dest_paths = {key: dest_dir / f"{key}-{fname}" for key in outputs}

    if aggregate:
        for dataset in datasets:
            fname = f"baselines-{timestamp}-{challenge_phase}-{dataset}.json"
            for key in outputs:
                with open(dest_dir / f"{key}-{fname}", "r") as f:
                    outputs[key].update(json.load(f))
    else:
        for dataset in datasets:
            folder = dataset.lower()
            dataset_key = {"activity-net": "ActivityNet"}.get(dataset, dataset)
            config_path = challenge_config_dir / folder / "baseline-public-trainval.json"
            flags = f" --config {config_path} --device {device}"
            if mini_train:
                flags += f" --mini_train"
            if train_single_epoch:
                flags += f" --train_single_epoch"
            cmd = f"python -u train.py {flags}"
            print(f"Launching baseline for {dataset} with command: {cmd}")
            logs = launch_and_monitor_cmd(cmd=cmd)
            exp_paths = parse_paths_from_logs(logs)
            for key in outputs:
                # We convert each path to a string to ensure it can be JSON serialized
                output_path = str(exp_paths[key])
                outputs[key][dataset_key] = {challenge_phase: output_path}

    for key, dest_path in dest_paths.items():
        print(f"Writing baseline {key} list to {dest_path}")
        with open(dest_path, "w") as f:
            json.dump(outputs[key], f)

        generate_predictions(
            refresh=True,
            validate=True,
            dest_dir=dest_dir,
            challenge_phase=challenge_phase,
            predictions_path=dest_paths["predictions"],
        )


def main():
    parser = argparse.ArgumentParser(description="train baselines")
    parser.add_argument("--debug", action="store_true", help="launch in debug mode")
    parser.add_argument("--timestamp")
    parser.add_argument("--yaspify", action="store_true", help="launch via slurm")
    parser.add_argument("--slurm", action="store_true")
    parser.add_argument("--device", type=int, default=0,
                        help="gpu device to use for training")
    parser.add_argument("--datasets", nargs="+",
                        default=["MSRVTT", "MSVD", "DiDeMo", "LSMDC", "activity-net"],
                        help="THe challenge datasets to train baselines for")
    parser.add_argument('--mini_train', action="store_true")
    parser.add_argument('--train_single_epoch', action="store_true")
    parser.add_argument('--dest_dir', type=Path,
                        default="data/cvpr2020-challenge-submissions")
    parser.add_argument('--challenge_config_dir', type=Path,
                        default="configs/cvpr2020-challenge")
    parser.add_argument("--yaspi_defaults_path", type=Path,
                        default="misc/yaspi_gpu_defaults.json")
    args = parser.parse_args()

    if args.timestamp:
        timestamp = args.timestamp
    else:
        timestamp = datetime.now().strftime(r"%Y-%m-%d_%H-%M-%S")

    common_kwargs = dict(
        device=args.device,
        timestamp=timestamp,
        dest_dir=args.dest_dir,
        datasets=args.datasets,
        mini_train=args.mini_train,
        train_single_epoch=args.train_single_epoch,
        challenge_config_dir=args.challenge_config_dir,
    )

    if args.yaspify:
        with open(args.yaspi_defaults_path, "r") as f:
            yaspi_defaults = json.load(f)
        cmd_args = sys.argv
        remove = ["--yaspify", "--datasets"]
        cmd_args = filter_cmd_args(cmd_args, remove=remove)
        cmd_args.extend(["--timestamp", timestamp])
        base_cmd = f"python {' '.join(cmd_args)}"
        job_name = f"baselines-{timestamp}"
        job_queue = [f'"--datasets {dataset}"' for dataset in args.datasets]
        job_queue = " ".join(job_queue)
        job = Yaspi(
            cmd=base_cmd,
            job_queue=job_queue,
            job_name=job_name,
            job_array_size=len(args.datasets),
            **yaspi_defaults,
        )
        job.submit(watch=True, conserve_resources=5)
        train_baselines(**common_kwargs, aggregate=True)
    else:
        train_baselines(**common_kwargs)


if __name__ == "__main__":
    main()