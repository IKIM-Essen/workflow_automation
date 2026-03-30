# workflow_automation

## Run

- python workflow_dispatcher.py

## ToDo
- Add logger
- Add workflow description
- Instructions how to add pipeline
- Instructions ho to run pipeline in container?
- Overwrite config.yaml run_date
- Add env.yml
- Add test

## How to use

- `conda activate workflow_dispatcher`
- `python workflow_dispatcher.py`

## Workflow logic (summary)
- Workflow configurations are loaded from CSV files in workflows/.
- Each configuration specifies:
    - input_data_path → root folder containing runs
    - data_regex → pattern to match FASTQ files
    - workflow_path → location of workflow scripts/config
    - command → command to execute the workflow
- Run detection:
    - All subfolders under input_data_path are scanned recursively (rglob("*")).
    - Folders named workflow_status are skipped.
- FASTQ pairing:
    - All FASTQ files in a run folder matching data_regex are collected.
    - _R1 and _R2 in filenames are removed to determine sample names.
    - Only complete R1/R2 pairs are kept.
- Sample sheet creation:
    - For each run, a CSV file samples.csv is written in workflow_path/config/pep.
- Workflow status handling:
    - A workflow_status folder may exist in the run folder (not automatically created).
    - .run and .done flags indicate whether a workflow is running or completed.
    - If another workflow is running in a different run folder, submission is skipped.
- Workflow submission:
    - Each run is submitted as a Slurm job.
    - On job start, a .run flag is created; on success, .done is created; on failure, .failed is created.
- Execution order:
    - Only one workflow is submitted at a time per configuration.
    - Subfolders are treated as separate runs, independent from each other.

## TBD
- Shall a new sample.csv sheet be created for every run? -> Can we just overwrite sample.csv? -> Yes
- config.yaml run_date: "" has to be overwritten as well. Is it the exactly the same everywhere? -> Shall be overwritten every time
- Is it sufficient to have only one active container per workflow? (Serial instead of parallel processing) -> Yes
- Base sm environment to start the container -> See shared user
- The containers use the unpacked DBs on ds/groups -> Whats the maximum size here? -> 140 GB
- What happens if the same workflow starts for two different sequencer outputs? Will that happen? One Workflow container per sequencer? -> One container is sufficient
- Can multiple users controll one cron job? Automation user that can be used from different people? -> Ask Marcel
- Clean up -> move results to "output" folder and delete everything else? -> Not needed
