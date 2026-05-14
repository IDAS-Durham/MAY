#!/bin/bash
conda run -n MISC mkdocs gh-deploy --remote-branch gavin_docs --remote-name origin --config-file mkdocs.yml
