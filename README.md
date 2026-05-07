# workflow_automation

## How to Run

Run on a Slurm-enabled system:

1. Clone the repository
2. Add your workflow configuration CSV file to the `workflows/` directory
3. Create the conda environment:
```bash
conda env create --file=Environment.yaml
```
4. Activate the environment:
```bash
conda activate workflow_dispatcher
```
5. Run the dispatcher:
```bash
python workflow_dispatcher.py
```
The dispatcher is intended to be executed periodically (e.g. every 15 minutes via cron or Slurm).

## Add your workflow to the running automation

- Create a .csv in the `workflows` folder
- The csv has to contain: `name,input_data_path,data_regex,workflow_path,command`
    - `name`: Name of your workflow
    - `input_data_path`: folder that shall be monitored for new fasta files
    - `data_regex`: regex that all files that shall be processed match
    - `workflow_path`: Path to the snakemake worfklow version that shall be executed
    - `command`: Terminal command that has to be executed from the `workflow_path` to start the workflow -> Do not use `--cores all` because slurm struggles to allocate recources that way
- Each csv file can contain multiple lines with different regex and commands for the same workflow
- Example: `workflows/qc_test.csv`

## Containerise your workflow
See `containerise/README.md`


## Workflow logic (summary)
Workflow configurations are loaded from CSV files in `workflows/`
### Configuration:
Workflow configurations are loaded from CSV files in `workflows/` and specifiy:
- input_data_path → root folder containing runs
- data_regex → pattern to match FASTQ files
- workflow_path → location of workflow scripts/config
- command → command to execute the workflow

### Run detection:
- The dispatcher recursively scans all subdirectories below `input_data_path`
- Run directories are automatically detected based on the presence of `.fastq.gz` files
- Directories named `workflow_status` are ignored

### Copy complete detection:
- To avoid processing incomplete sequencing runs, workflows are only started after the sequencing data transfer has completed.
- The dispatcher searches parent directories of each run folder for a file named `CopyComplete.txt`

### FASTQ pairing:
- FASTQ files matching `data_regex` are collected
- Files beginning with `Undetermined` are ignored
- `_R1` and `_R2` are used to identify read pairs
- Only complete R1/R2 pairs are accepted
- Empty or corrupted FASTQ files are ignored automatically
- Sample names are derived from FASTQ filenames by removing:
`_R1.fastq.gz`
`_R2.fastq.gz`

### Sample sheet creation:
- For each run, a CSV file samples.csv is written in workflow_path/config/pep.

### Workflow status handling:
| Status | Description |
|---|---|
| `READY` | Workflow is ready to start |
| `RUNNING` | Workflow is currently running |
| `DONE` | Workflow completed successfully |
| `FAILED` | Workflow execution failed |
| `BLOCKED` | Another run of the same workflow is already running |

Status files are stored as:

```text
<workflow_name>.RUNNING
<workflow_name>.DONE
<workflow_name>.FAILED
```

Example:
```text
workflow_status/amr_prediction.RUNNING
```

### Blocking behavior:
Only one instance of the same workflow is allowed to run at a time.
If another run directory already contains:
```text
<workflow_name>.RUNNING
```
the dispatcher stops processing additional runs for this workflow until the running job has finished.

### Workflow submission:
Workflows are executed as Slurm jobs using `sbatch`.
For each workflow submission:
- A temporary Slurm submission script is generated automatically
- The configured conda environment is activated
- The workflow command is executed inside the workflow directory
- Execution order:
    - Only one workflow is submitted at a time per configuration.
    - Subfolders are treated as separate runs, independent from each other.

- Slurm Logs:

    Slurm stdout/stderr logs are written to:
    ```text
    <workflow_path>/logs/slurm/
    ```
    Example:
    ```text
    my_workflow/logs/slurm/123456.out
    ```
## Sample Status Tracking

A global sample tracking file is maintained at:
```text
sample_status.csv
```
This file contains the latest workflow status for every processed sample across all workflows.

### Columns
| Column | Description |
|---|---|
| `sample_name` | Sample identifier |
| `workflow_name` | Workflow name |
| `sample_path` | Directory containing the FASTQ files |
| `status` | Current workflow status |
| `last_updated` | Timestamp of latest status update |
The CSV file is automatically updated whenever sample states change.

---

## Execution Order
- Only one workflow job is submitted per dispatcher execution
- Run folders are processed sequentially
- Subdirectories are treated as independent sequencing runs
- The dispatcher exits immediately after submitting a workflow job

## Troubleshooting

### Folder locked
**Problem:**
LockException:
Error: Directory cannot be locked. Please make sure that no other Snakemake process is trying to create the same files in the following directory:
/groups/ds/automation/qc_pipeline_test/QC_pre_NextSeq

**Solution:**
`cd /path/to/snakemake/workflow`
`conda activate snakemake_9_slurm`
`snakemake --unlock`

## TBD
- Shall a new sample.csv sheet be created for every run? -> Can we just overwrite sample.csv? -> Yes
- config.yaml run_date: "" has to be overwritten as well. Is it the exactly the same everywhere? -> Shall be overwritten every time
- Is it sufficient to have only one active container per workflow? (Serial instead of parallel processing) -> Yes
- Base sm environment to start the container -> See shared user
- The containers use the unpacked DBs on ds/groups -> Whats the maximum size here? -> 140 GB
- What happens if the same workflow starts for two different sequencer outputs? Will that happen? One Workflow container per sequencer? -> One container is sufficient
- Can multiple users controll one cron job? Automation user that can be used from different people? -> Ask Marcel
- Clean up -> move results to "output" folder and delete everything else? -> Not needed

## ToDo
- Remove hard coded conda env from workflow_dispatcher.py
- Add test
