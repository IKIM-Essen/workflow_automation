#!/usr/bin/env python3

import csv
import re
import subprocess
from pathlib import Path
from datetime import datetime
import tempfile
import textwrap


WORKFLOW_DIR = Path("workflows")


def load_workflow_config(csv_file: Path):
    with open(csv_file, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        configs = list(reader)

    if not configs:
        raise ValueError(f"{csv_file} contains no workflow definitions.")

    return configs


def write_sample_sheet(samples, workflow_path: Path):
    pep_dir = workflow_path / "config" / "pep"
    pep_dir.mkdir(parents=True, exist_ok=True)

    output_file = pep_dir / "samples.csv"

    with open(output_file, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=["sample_name", "fq1", "fq2"])
        writer.writeheader()
        writer.writerows(samples)

    return output_file


def submit_workflow(
    command: str,
    workflow_path: Path,
    workflow_name: str,
    job_name: str = "workflow_job",
):
    log_dir = workflow_path / "logs" / "slurm"
    log_dir.mkdir(parents=True, exist_ok=True)
    log_dir_str = str(log_dir.resolve())

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    job_name_ts = f"{job_name}_{timestamp}"

    slurm_script = textwrap.dedent(
        f"""\
        #!/bin/bash
        #SBATCH --job-name={job_name_ts}
        #SBATCH --output={log_dir_str}/%j.out
        #SBATCH --error={log_dir_str}/%j.out

        set -euo pipefail

        STATUS_DIR="{workflow_path}"
        WORKFLOW="{workflow_name}"

        cleanup_success() {{
            rm -f "$STATUS_DIR/${{WORKFLOW}}.run"
            touch "$STATUS_DIR/${{WORKFLOW}}.done"
        }}

        cleanup_fail() {{
            rm -f "$STATUS_DIR/${{WORKFLOW}}.run"
            touch "$STATUS_DIR/${{WORKFLOW}}.failed"
        }}

        trap cleanup_fail ERR
        trap cleanup_success EXIT

        eval "$(/opt/mambaforge/bin/conda shell.bash hook)"
        cd {workflow_path}
        conda activate /projects/envs/conda/jzander/envs/snakemake_9_slurm

        {command}
        """
    )
    with tempfile.NamedTemporaryFile(mode="w", delete=False, suffix=".sh") as f:
        f.write(slurm_script)
        script_path = Path(f.name)

    # Submit job
    result = subprocess.run(
        ["sbatch", script_path], capture_output=True, text=True, check=True
    )

    # Slurm returns  "Submitted batch job <JOBID>"
    stdout = result.stdout.strip()
    stderr = result.stderr.strip()
    print(stdout)
    if stderr:
        print("SBATCH STDERR:", stderr)

    # extract Job-ID
    match = re.search(r"Submitted batch job (\d+)", stdout)
    if match:
        job_id = match.group(1)
        return job_id
    else:
        return None


def update_run_date(workflow_path: Path, run_name: str):

    config_file = workflow_path / "config" / "config.yaml"

    if not config_file.exists():
        raise FileNotFoundError(f"{config_file} not found")

    timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    run_date_value = f"{timestamp}_{run_name}"

    new_lines = []

    with open(config_file, "r", encoding="utf-8") as f:
        for line in f:
            if line.strip().startswith("run-date:"):
                new_lines.append(f'run-date: "{run_date_value}"\n')
            else:
                new_lines.append(line)

    with open(config_file, "w", encoding="utf-8") as f:
        f.writelines(new_lines)

    return run_date_value


def get_run_status(run_dir: Path, workflow_name: str, input_data_path: Path):
    status_dir = run_dir / "workflow_status"
    run_flag = status_dir / f"{workflow_name}.run"
    done_flag = status_dir / f"{workflow_name}.done"

    if not status_dir.exists():
        return "READY", status_dir

    if done_flag.exists():
        return "DONE", status_dir

    if run_flag.exists():
        return "RUNNING", status_dir

    # Check if workflow is running in other folders
    for s in input_data_path.glob("*/workflow_status"):
        if s == status_dir:
            continue  # skip current run_dir
        if (s / f"{workflow_name}.run").exists():
            print(f"{workflow_name}: already running in {s.parent.resolve()}. Waiting.")
            return "BLOCKED", status_dir

    return "READY", status_dir


def prepare_samples(run_dir: Path, data_regex: str):
    pattern = re.compile(data_regex)
    files = [p for p in run_dir.glob("*.fastq.gz") if pattern.search(p.name)]

    if not files:
        return None, "no FASTQ files"

    samples = {}

    for f in files:
        name = f.name

        if "_R1" in name:
            sample = re.sub(r"_R1", "", name).replace(".fastq.gz", "")
            samples.setdefault(sample, {})["fq1"] = f

        elif "_R2" in name:
            sample = re.sub(r"_R2", "", name).replace(".fastq.gz", "")
            samples.setdefault(sample, {})["fq2"] = f

    # keep only complete pairs
    result = []
    for sample, reads in samples.items():
        if "fq1" in reads and "fq2" in reads:
            result.append(
                {
                    "sample_name": sample,
                    "fq1": str(reads["fq1"].resolve()),
                    "fq2": str(reads["fq2"].resolve()),
                }
            )

    samples = sorted(result, key=lambda x: x["sample_name"])

    if not samples:
        return None, "no R1/R2 pairs"

    return samples, None


def start_workflow(
    workflow_path: Path,
    workflow_name: str,
    command: str,
    status_dir: Path,
):
    status_dir.mkdir(exist_ok=True)

    run_flag = status_dir / f"{workflow_name}.run"
    run_flag.touch()

    job_id = submit_workflow(
        command,
        workflow_path,
        workflow_name,
        status_dir,
    )

    print(f"{workflow_name}: submitted as job {job_id}")


def process_workflow(csv_file: Path):
    print(f"\nProcessing workflow config: {csv_file}")

    configs = load_workflow_config(csv_file)

    for config in configs:
        workflow_name = config["name"]
        input_data_path = Path(config["input_data_path"])
        data_regex = config["data_regex"]
        workflow_path = Path(config["workflow_path"])
        command = config["command"]

        print(f"\nPipeline: {workflow_name}")
        print(f"Input directory: {input_data_path}")

        if not input_data_path.exists():
            print("Input directory does not exist, skipping.")
            continue

        for run_dir in sorted(p for p in input_data_path.rglob("*") if p.is_dir()):
            if run_dir.name == "workflow_status":
                continue

            print(f"\nChecking run folder: {run_dir.name}")

            status, status_dir = get_run_status(run_dir, workflow_name, input_data_path)

            if status == "DONE":
                print(f"{run_dir.name}: already DONE")
                continue

            if status == "RUNNING":
                print(f"{run_dir.name}: already RUNNING")
                continue

            if status == "BLOCKED":
                return

            samples, error = prepare_samples(run_dir, data_regex)

            if error:
                print(f"{run_dir.name}: {error}, skipping")
                continue

            sample_sheet = write_sample_sheet(samples, workflow_path)
            print(f"Sample sheet written to: {sample_sheet}")

            timestamp = update_run_date(workflow_path, run_dir.name)
            print(f"Updated run-date to {timestamp}")

            start_workflow(
                workflow_path,
                workflow_name,
                command,
                status_dir,
            )

            return


def main():
    workflow_csvs = sorted(WORKFLOW_DIR.glob("*.csv"))

    if not workflow_csvs:
        print("No workflow CSV files found.")
        return

    for csv_file in workflow_csvs:
        process_workflow(csv_file)


if __name__ == "__main__":
    main()
