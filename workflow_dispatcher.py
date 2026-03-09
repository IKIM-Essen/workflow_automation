#!/usr/bin/env python3

import csv
import re
import subprocess
from pathlib import Path
from datetime import datetime
import tempfile
import re
import textwrap


WORKFLOW_DIR = Path("workflows")


def load_workflow_config(csv_file: Path):
    """Load workflow configuration from CSV."""
    with open(csv_file, newline="") as f:
        reader = csv.DictReader(f)
        configs = list(reader)

    if len(configs) != 1:
        raise ValueError(f"{csv_file} must contain exactly one row.")

    return configs[0]


def find_matching_fastqs(input_dir: Path, regex_pattern: str):
    """Return all FASTQ files matching the regex."""
    pattern = re.compile(regex_pattern)
    files = [p for p in input_dir.glob("*.fastq.gz") if pattern.search(p.name)]
    return sorted(files)


def build_sample_table(files):
    """
    Create mapping:
    sample -> fq1,fq2
    """
    samples = {}

    for f in files:
        name = f.name

        r1_match = re.match(r"(.+)_R1\.fastq\.gz$", name)
        r2_match = re.match(r"(.+)_R2\.fastq\.gz$", name)

        if r1_match:
            sample = r1_match.group(1)
            samples.setdefault(sample, {})["fq1"] = f
        elif r2_match:
            sample = r2_match.group(1)
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

    return sorted(result, key=lambda x: x["sample_name"])


def write_sample_sheet(samples, workflow_path: Path):
    """Write samples CSV into workflow config/pep directory."""
    pep_dir = workflow_path / "config" / "pep"
    pep_dir.mkdir(parents=True, exist_ok=True)

    # timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    # output_file = pep_dir / f"samples_{timestamp}.csv"
    output_file = pep_dir / f"samples.csv"

    with open(output_file, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=["sample_name", "fq1", "fq2"])
        writer.writeheader()
        writer.writerows(samples)

    return output_file


def submit_workflow(
    command: str,
    workflow_path: Path,
    workflow_name: str,
    status_dir: Path,
    job_name: str = "workflow_job",
):
    """
    Dynamically create a Slurm script and submit it via sbatch.
    Returns the Slurm job ID.
    """

    log_dir = workflow_path / "logs" / "slurm"
    log_dir.mkdir(parents=True, exist_ok=True)
    log_dir_str = str(log_dir.resolve())

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    job_name_ts = f"{job_name}_{timestamp}"
    # Dynamisches Slurm-Skript als Text
    slurm_script = textwrap.dedent(
        f"""\
        #!/bin/bash
        #SBATCH --job-name={job_name_ts}
        #SBATCH --output={log_dir_str}/{job_name_ts}_%j.out
        #SBATCH --error={log_dir_str}/{job_name_ts}_%j.out

        set -euo pipefail

        STATUS_DIR="{status_dir}"
        WORKFLOW="{workflow_name}"

        cleanup_success() {{
            rm -f "$STATUS_DIR/${{WORKFLOW}}.running"
            touch "$STATUS_DIR/${{WORKFLOW}}.done"
        }}

        cleanup_fail() {{
            rm -f "$STATUS_DIR/${{WORKFLOW}}.running"
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
    # Temporäre Datei für sbatch
    with tempfile.NamedTemporaryFile(mode="w", delete=False, suffix=".sh") as f:
        f.write(slurm_script)
        script_path = Path(f.name)

    # Job einreichen
    result = subprocess.run(["sbatch", script_path], capture_output=True, text=True)

    # Slurm gibt typischerweise "Submitted batch job <JOBID>" zurück
    stdout = result.stdout.strip()
    stderr = result.stderr.strip()
    print(stdout)
    if stderr:
        print("SBATCH STDERR:", stderr)

    # Job-ID extrahieren

    match = re.search(r"Submitted batch job (\d+)", stdout)
    if match:
        job_id = match.group(1)
        return job_id
    else:
        return None


def process_workflow(csv_file: Path):
    """Process one workflow configuration."""
    print(f"\nProcessing workflow config: {csv_file}")

    config = load_workflow_config(csv_file)

    name = config["name"]
    input_data_path = Path(config["input_data_path"])
    data_regex = config["data_regex"]
    workflow_path = Path(config["workflow_path"])
    command = config["command"]

    print(f"Pipeline: {name}")
    print(f"Input directory: {input_data_path}")

    if not input_data_path.exists():
        # TODO: log Warning
        print("Input directory does not exist, skipping.")
        return

    files = find_matching_fastqs(input_data_path, data_regex)

    if not files:
        print("No matching FASTQ files found.")
        return

    samples = build_sample_table(files)

    if not samples:
        print("No complete R1/R2 pairs detected.")
        return

    sample_sheet = write_sample_sheet(samples, workflow_path)
    # TODO: Write Config here

    print(f"Sample sheet written to: {sample_sheet}")
    print(f"Samples detected: {len(samples)}")

    # run_workflow(command, workflow_path)
    # job_id = submit_workflow(command, workflow_path, name, job_name=config["name"])
    process_sample(workflow_path, input_data_path, name, command)

    # print(f"Workflow {config['name']} submitted as job {job_id}")


def process_sample(
    workflow_path: Path, input_data_path: Path, workflow_name: str, command: str
):
    """
    Handles workflow status and dispatching.
    """

    status_dir = input_data_path / "status"
    status_dir.mkdir(parents=True, exist_ok=True)

    print("status_dir")
    print(status_dir)

    run_flag = status_dir / f"{workflow_name}.run"
    done_flag = status_dir / f"{workflow_name}.done"
    failed_flag = status_dir / f"{workflow_name}.failed"

    if done_flag.exists():
        print(f"{workflow_name}: already DONE")
        return

    if run_flag.exists():
        print(f"{workflow_name}: already RUNNING")
        return

    if failed_flag.exists():
        print(f"{workflow_name}: already FAILED. Trying again.")

    print(f"{workflow_name}: starting workflow")

    run_flag.touch()

    job_id = submit_workflow(
        command, workflow_path, workflow_name, status_dir, job_name=workflow_name
    )

    print(f"{workflow_name}: submitted as job {job_id}")


def main():
    workflow_csvs = sorted(WORKFLOW_DIR.glob("*.csv"))

    if not workflow_csvs:
        print("No workflow CSV files found.")
        return

    for csv_file in workflow_csvs:
        process_workflow(csv_file)


if __name__ == "__main__":
    main()
