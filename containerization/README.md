# Containerize your workflow

All steps must be completed with your own workflow. Copy the  `containerization` folder from this repository into your own snakemake workflow.

## Generate Container

### Build snakemake envs

All envs that shall run in the container must have been created prior to containerization

If not already build create only the envs via `--conda-create-envs-only` snakemake flag

### Create Dockerfile
  
`snakemake --containerize > containerization/Dockerfile`

### Generate .def

`python containerization/dockerfile_to_singularity.py containerization/Dockerfile --output containerization/my_container.def`

### Generate .sif

`apptainer build containerization/my_container.sif containerization/my_container.def`

## Execute workflow with container

### Bind container to workflow

Make sure your `Snakefile` links to the container via:
`containerized: "containerization/my_container.sif"`

## Run workflow with container

Activate env with snakemake 9
`snakemake --cores all --software-deployment-method conda apptainer --singularity-args "--bind /groups/ds/databases_refGenomes/databases"`

Run via slurm
`nice snakemake --cores all --software-deployment-method conda apptainer --singularity-args "--bind /groups/ds/databases_refGenomes/databases" --jobs 2 -n`

### Mount Database
The --singularity-args option allows passing additional arguments to the container runtime (Apptainer/Singularity). In this case, `--bind /groups/ds/databases_refGenomes/databases` mounts a host directory into the container so that reference databases are accessible during execution.

If your databases are stored in a different location, you must adjust this path accordingly. The general format is `--bind <host_path>:<container_path>`, where `<host_path>` is the directory on your system and `<container_path>` is the path inside the container (if omitted, the same path is used inside the container).
## Further information

https://snakemake.readthedocs.io/en/stable/snakefiles/deployment.html#containerization-of-conda-based-workflows 

Example workflow: https://github.com/IKIM-Essen/QC_pre_NextSeq/tree/sm_9_automation
