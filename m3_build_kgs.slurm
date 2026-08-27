#!/bin/bash
#SBATCH --job-name=build-kgs
#SBATCH --partition=comp
#SBATCH --time=6:00:00
#SBATCH --cpus-per-task=16
#SBATCH --mem=32G
#SBATCH --output=build-kgs-%j.out

# Runs scripts/build_kgs_for_instances.py + scripts/build_kg_prompts.py
# directly on M3, no GitHub Actions involved. Same two scripts the
# build-kg-prompts.yml workflow runs on GitHub-hosted compute, just run
# here for more CPU cores (RepoASTParser's ProcessPoolExecutor benefits
# directly) and no GitHub-hosted runner time/disk limits.
#
# Configure via env vars, same pattern as m3_run_inference.slurm:
#
#   INSTANCES="django__django-10390-15718,sympy__sympy-11400-17079" \
#   DATASET="kjain14/testgeneval" DEPTH="2" \
#     sbatch m3_build_kgs.slurm
#
# INSTANCES empty (default) builds every row in DATASET.
#
# Submit this from a checkout under scratch space (e.g.
# ~/al49_scratch/.../repo-kg-construction), not $HOME -- RepoManager's
# bare git clones land in ./repo_cache, relative to wherever this runs
# from, and django/sympy's real clone sizes would otherwise eat $HOME's
# small quota the same way HF_HOME/HF_DATASETS_CACHE would below.

set -euo pipefail
cd "$SLURM_SUBMIT_DIR"

INSTANCES="${INSTANCES:-}"
DATASET="${DATASET:-kjain14/testgenevallite}"
DEPTH="${DEPTH:-2}"

# $HOME has its own small, easy-to-exhaust quota on M3 (confirmed real
# this session on the testgeneval side, same load_dataset default cache
# location applies here). Point both at scratch space.
export HF_HOME="${HF_HOME:-$HOME/al49_scratch/$USER/hf-cache}"
export HF_DATASETS_CACHE="${HF_DATASETS_CACHE:-$HOME/al49_scratch/$USER/hf-datasets-cache}"

module load miniforge3

# First run on this account: create the env once, reused on every
# subsequent submission. requires-python is >=3.10 (see pyproject.toml).
if ! conda env list | grep -q "^pycodekg "; then
  echo "---- Creating pycodekg conda env (first run) ----"
  conda create -y -n pycodekg python=3.11
  source activate pycodekg
  pip install -e ".[datasets]"
else
  source activate pycodekg
fi

echo "---- Building KGs ----"
PYTHONPATH=src python3 scripts/build_kgs_for_instances.py \
  --instances "$INSTANCES" \
  --dataset "$DATASET"

echo "---- Saving dataset to disk ----"
python3 -c "
from datasets import load_dataset
ds = load_dataset('$DATASET')
ds.save_to_disk('dataset_on_disk')
"

echo "---- Building kg_only prompts ----"
PYTHONPATH=src python3 scripts/build_kg_prompts.py \
  --kg-dir kg_output \
  --dataset-path dataset_on_disk \
  --output kg_prompts.json \
  --depth "$DEPTH"

echo "Done. kg_output/ and kg_prompts.json are in $SLURM_SUBMIT_DIR"
