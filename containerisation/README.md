# Containerise your workflow

All steps must be completed with your own workflow. Copy the  `containerisation` folder from this repository into your own snakemake workflow.

## Generate Container

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

## Further information

https://snakemake.readthedocs.io/en/stable/snakefiles/deployment.html#containerization-of-conda-based-workflows 

Example workflow: https://github.com/IKIM-Essen/QC_pre_NextSeq/tree/sm_9_automation