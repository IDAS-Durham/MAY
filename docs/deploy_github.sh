#!/bin/bash
conda run -n MISC mkdocs gh-deploy --remote-branch gavin_docs --remote-name june_collab --config-file mkdocs.yml
