# workflow_automation

## Run

- python workflow_dispatcher.py

## ToDo
- Rewrite run date?
- Scan whole sequencing folder with subfolder and not only subfolder
- What is going on with unchanged run dates? 
- Add logger
- Instructions how to add pipeline
- Instructions ho to run pipeline in container?
- Add env.yml
- Add test

## TBD
- Shall a new sample.csv sheet with be created for every run? -> Can we just overwrite sample.csv?
- config.yaml run_date: "" has to be overwritten as well. Is it the exactly the same everywhere?
- Base sm environment to start the container
- What happens if the same workflow starts for two different sequencer outputs? Will that happen? One Workflow container per sequencer?
- Can multiple users controll one cron job? Automation user that can be used from different people?
