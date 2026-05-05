import csv
import re
import subprocess
from datetime import datetime
from dataclasses import dataclass
from pathlib import Path
from enum import Enum, auto
import tempfile
import textwrap
import logging

LOG_DIR = Path(__file__).parent / "logs"
LOG_DIR.mkdir(exist_ok=True)

WORKFLOW_DIR = Path("workflows")
EXCLUDE_SAMPLE_NAME = "Undetermined"
STATUS_CSV = Path(__file__).parent / "sample_status.csv"
COPY_COMPLETE_NAME = "copycomplete.txt"
CONDA_ENV_PATH = "/projects/envs/conda/jzander/envs/snakemake_9_slurm"
CONDA_BASE = "/opt/mambaforge"


class RunStatus(Enum):
    READY = auto()
    DONE = auto()
    RUNNING = auto()
    FAILED = auto()
    BLOCKED = auto()


class DispatchAction(Enum):
    CONTINUE = auto()
    STOP = auto()
    PROCEED = auto()


@dataclass
class Sample:
    sample_name: str
    fq1: str
    fq2: str
    sample_path: str


# # ----------------------------------------------------------------------------

# Utilities
# ----------------------------------------------------------------------------


def is_copy_complete(run_dir: Path):

    for parent in run_dir.parents:
        try:
            for f in parent.iterdir():
                if f.is_file() and f.name.lower() == COPY_COMPLETE_NAME:
                    logging.debug("Found CopyComplete.txt in %s", parent)
                    return True
        except PermissionError:
            continue

    logging.debug("No CopyComplete.txt found for %s", run_dir)
    return False


def is_valid_fastq(file: Path, min_size_bytes: int = 100):
    try:
        return file.stat().st_size > min_size_bytes
    except OSError:
        return False


def setup_logging():
    log_file = LOG_DIR / "workflow.log"
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
        handlers=[
            logging.FileHandler(log_file, encoding="utf-8"),
            logging.StreamHandler(),
        ],
    )


# ----------------------------------------------------------------------------
# IO and Data Preperation
# ----------------------------------------------------------------------------


def load_workflow_config(csv_file_input: Path):
    with open(csv_file_input, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        configs = list(reader)

    if not configs:
        raise ValueError(f"{csv_file_input} contains no workflow definitions.")

    return configs


def prepare_samples(run_dir: Path, data_regex: str):
    pattern = re.compile(data_regex)
    files = [p for p in run_dir.glob("*.fastq.gz") if pattern.search(p.name)]

    if not files:
        return []

    samples = {}

    for f in files:
        name = f.name
        if name.startswith(EXCLUDE_SAMPLE_NAME):
            logging.warning("Skipping %s: Starts with <%s>", name, EXCLUDE_SAMPLE_NAME)
            continue

        if "_R1" in name:
            sample = re.sub(r"_R1", "", name).replace(".fastq.gz", "")
            samples.setdefault(sample, {})["fq1"] = f
        elif "_R2" in name:
            sample = re.sub(r"_R2", "", name).replace(".fastq.gz", "")
            samples.setdefault(sample, {})["fq2"] = f

    result = []
    for sample, reads in samples.items():
        if "fq1" in reads and "fq2" in reads:
            fq1 = reads["fq1"]
            fq2 = reads["fq2"]

            if not is_valid_fastq(fq1):
                logging.warning("Skipping %s: fq1 is empty (%s)", sample, fq1)
                continue

            if not is_valid_fastq(fq2):
                logging.warning("Skipping %s: fq2 is empty (%s)", sample, fq2)
                continue

            fq1 = fq1.resolve()
            fq2 = fq2.resolve()

            result.append(
                Sample(
                    sample_name=sample,
                    fq1=str(fq1),
                    fq2=str(fq2),
                    sample_path=str(fq1.parent),
                )
            )

    samples = sorted(result, key=lambda x: x.sample_name)

    return samples


def write_sample_sheet(samples: list[Sample], workflow_path: Path):
    pep_dir = workflow_path / "config" / "pep"
    pep_dir.mkdir(parents=True, exist_ok=True)

    output_file = pep_dir / "samples.csv"

    with open(output_file, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=["sample_name", "fq1", "fq2"])
        writer.writeheader()

        writer.writerows(
            {
                "sample_name": s.sample_name,
                "fq1": s.fq1,
                "fq2": s.fq2,
            }
            for s in samples
        )

    return output_file


def update_sample_status_csv(
    samples: list[Sample],
    workflow_name: str,
    status: RunStatus,
):
    if not samples:
        return

    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    STATUS_CSV.parent.mkdir(parents=True, exist_ok=True)

    # Load existing file
    rows = {}
    if STATUS_CSV.exists():
        with open(STATUS_CSV, newline="", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for r in reader:
                key = (r["sample_name"], r["workflow_name"])
                rows[key] = r

    # Update / Insert
    for s in samples:
        key = (s.sample_name, workflow_name)
        rows[key] = {
            "sample_name": s.sample_name,
            "workflow_name": workflow_name,
            "sample_path": s.sample_path,
            "status": status.name,
            "last_updated": timestamp,
        }

    # Write
    with open(STATUS_CSV, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(
            f,
            fieldnames=[
                "sample_name",
                "workflow_name",
                "sample_path",
                "status",
                "last_updated",
            ],
        )
        writer.writeheader()
        writer.writerows(rows.values())


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


# ----------------------------------------------------------------------------
# Status Logic
# ----------------------------------------------------------------------------


def get_status(run_dir: Path, workflow_name: str, input_data_path: Path):
    status_dir = run_dir / "workflow_status"

    run_flag = status_dir / f"{workflow_name}.{RunStatus.RUNNING.name}"
    done_flag = status_dir / f"{workflow_name}.{RunStatus.DONE.name}"
    failed_flag = status_dir / f"{workflow_name}.{RunStatus.FAILED.name}"

    for s in input_data_path.rglob("workflow_status"):
        if s == status_dir:
            continue

        other_run_flag = s / f"{workflow_name}.{RunStatus.RUNNING.name}"
        if other_run_flag.exists():
            logging.info(
                "%s: already running in %s. Waiting.",
                workflow_name,
                s.parent.resolve(),
            )
            return RunStatus.BLOCKED, status_dir

    if not status_dir.exists():
        return RunStatus.READY, status_dir

    if done_flag.exists():
        return RunStatus.DONE, status_dir

    if failed_flag.exists():
        return RunStatus.FAILED, status_dir

    if run_flag.exists():
        return RunStatus.RUNNING, status_dir

    return RunStatus.READY, status_dir


def handle_status(
    status: RunStatus,
    run_dir: Path,
    samples: list[Sample],
    workflow_name: str,
):
    match status:
        case RunStatus.DONE:
            logging.info("%s: already DONE", run_dir.name)
            update_sample_status_csv(samples, workflow_name, RunStatus.DONE)
            return DispatchAction.CONTINUE

        case RunStatus.RUNNING:
            logging.info("%s: already RUNNING", run_dir.name)
            return DispatchAction.STOP

        case RunStatus.BLOCKED:
            return DispatchAction.STOP

        case RunStatus.FAILED:
            update_sample_status_csv(samples, workflow_name, RunStatus.FAILED)
            return DispatchAction.PROCEED

        case RunStatus.READY:
            update_sample_status_csv(samples, workflow_name, RunStatus.READY)
            return DispatchAction.PROCEED


# ----------------------------------------------------------------------------
# Execution
# ----------------------------------------------------------------------------


def submit_workflow(
    command: str, workflow_path: Path, workflow_name: str, status_dir: Path
):
    log_dir = workflow_path / "logs" / "slurm"
    log_dir.mkdir(parents=True, exist_ok=True)
    log_dir_str = str(log_dir.resolve())

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    job_name_ts = "workflow_job_" + str(timestamp)
    running = RunStatus.RUNNING.name
    done = RunStatus.DONE.name
    failed = RunStatus.FAILED.name

    slurm_script = textwrap.dedent(f"""\
    #!/bin/bash
    #SBATCH --job-name={job_name_ts}
    #SBATCH --output={log_dir_str}/%j.out
    #SBATCH --error={log_dir_str}/%j.out

    set -euo pipefail

    STATUS_DIR="{status_dir}"
    WORKFLOW="{workflow_name}"

    cleanup() {{
        rm -f "$STATUS_DIR/${{WORKFLOW}}.{running}"
        if [ "$SUCCESS" = true ]; then
            touch "$STATUS_DIR/${{WORKFLOW}}.{done}"
        else
            touch "$STATUS_DIR/${{WORKFLOW}}.{failed}"
        fi
    }}

    SUCCESS=true
    trap 'SUCCESS=false' ERR
    trap cleanup EXIT

    eval "$({CONDA_BASE}/bin/conda shell.bash hook)"
    cd {workflow_path}
    conda activate {CONDA_ENV_PATH}

    {command}
    """)
    with tempfile.NamedTemporaryFile(mode="w", delete=False, suffix=".sh") as f:
        f.write(slurm_script)
        script_path = Path(f.name)

    # Submit job
    result = subprocess.run(
        ["sbatch", script_path], capture_output=True, text=True, check=True
    )

    stdout = result.stdout.strip()
    stderr = result.stderr.strip()
    if stderr:
        logging.warning("SBATCH STDERR: %s", stderr)

    match = re.search(r"Submitted batch job (\d+)", stdout)
    if match:
        job_id = match.group(1)
        return job_id
    else:
        return None


def start_workflow(
    workflow_path: Path, workflow_name: str, command: str, status_dir: Path
):
    status_dir.mkdir(exist_ok=True)
    run_flag = status_dir / f"{workflow_name}.{RunStatus.RUNNING.name}"
    run_flag.touch()
    job_id = submit_workflow(command, workflow_path, workflow_name, status_dir)
    logging.info("%s: submitted as job %s", workflow_name, job_id)


# ----------------------------------------------------------------------------
# Main Processing
# ----------------------------------------------------------------------------


def process_workflow(csv_file_input: Path):
    logging.info("Processing workflow config: %s", csv_file_input)

    configs = load_workflow_config(csv_file_input)

    for config in configs:
        workflow_name = config["name"]
        input_data_path = Path(config["input_data_path"])
        data_regex = config["data_regex"]
        workflow_path = Path(config["workflow_path"])
        command = config["command"]

        logging.info("Pipeline: %s", workflow_name)
        logging.info("Input directory: %s", input_data_path)

        if not input_data_path.exists():
            logging.warning("Input directory does not exist, skipping.")
            continue

        run_dirs = set(p.parent for p in input_data_path.rglob("*.fastq.gz"))
        for run_dir in sorted(run_dirs):
            if run_dir.name == "workflow_status":
                continue

            logging.info("Checking run folder: %s", run_dir.name)

            if not is_copy_complete(run_dir):
                logging.info(
                    "%s: copy not finished yet (CopyComplete.txt missing)", run_dir.name
                )
                continue

            status, status_dir = get_status(run_dir, workflow_name, input_data_path)

            samples = prepare_samples(run_dir, data_regex)
            if not samples:
                continue

            action = handle_status(status, run_dir, samples, workflow_name)
            if action == DispatchAction.CONTINUE:
                continue
            if action == DispatchAction.STOP:
                return

            sample_sheet = write_sample_sheet(samples, workflow_path)
            logging.info("Sample sheet written to: %s", sample_sheet)

            timestamp = update_run_date(workflow_path, run_dir.name)
            logging.info("Updated run-date to %s", timestamp)

            start_workflow(workflow_path, workflow_name, command, status_dir)

            update_sample_status_csv(
                samples,
                workflow_name,
                RunStatus.RUNNING,
            )

            return


if __name__ == "__main__":
    setup_logging()
    workflow_csvs = sorted(WORKFLOW_DIR.glob("*.csv"))

    if not workflow_csvs:
        logging.warning("No workflow CSV files found.")

    else:
        for csv_file in workflow_csvs:
            process_workflow(csv_file)
