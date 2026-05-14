# Attributes

Each file assigns one property to agents. Attributes are run in the order they appear in the `timeline.steps` list; earlier attributes are available as dependencies for later ones.

| File | Assigns | Dependencies |
|---|---|---|
| [`attribute_assignment.yaml`](attribute-assignment.md) | `ethnicity` — per household structure using geo-based distributions and inheritance rules | none |
| [`comorbidity_assignment.yaml`](comorbidity-assignment.md) | `comorbidities` — list of health conditions by sex × age band × ethnicity × region | `ethnicity` |
| [`workplace_assignment.yaml`](workplace-assignment.md) | `workplace_location` (LGU) and `work_mode` — from commuting flow matrices | none |
| [`workplace_sgu_assignment.yaml`](workplace-sgu-assignment.md) | `workplace_sgu` — fine-grained SGU within the workplace LGU | `workplace_location` |
| [`work_sector_assignment.yaml`](work-sector-assignment.md) | `work_sector` — industry sector code (A–Q) | `workplace_location`, `workplace_sgu` |
