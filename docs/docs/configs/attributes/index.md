# Attributes

Each file assigns one property to agents. Attributes are run in the order they appear in the `timeline.steps` list; earlier attributes are available as dependencies for later ones.

| Config file(s) | Assigns | Dependencies |
|---|---|---|
| [`attribute_assignment.yaml`, `comorbidity_assignment.yaml`](attribute-assignment.md) | `ethnicity` (household structure + inheritance); `comorbidities` (list of health conditions by sex × age × ethnicity × region) | `comorbidity_assignment` depends on `ethnicity` |
| [`workplace_assignment.yaml`, `workplace_sgu_assignment.yaml`, `work_sector_assignment.yaml`](workplace-assignment.md) | `workplace_location` + `work_mode`; `workplace_sgu`; `work_sector` | each step depends on the previous |
