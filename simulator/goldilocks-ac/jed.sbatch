#!/bin/bash
# One sweep of this folder on a Jed node (EPFL SCITAS). Pass the sweep's command line:
#   sbatch jed.sbatch adv_sweep.py --seeds 4
# The script runs from the job's submit directory (simulator/goldilocks-ac on Jed), with the 72 cores
# of one node; the sweeps size their process pools to the cores they see.
#SBATCH --job-name=goldilocks-ac
#SBATCH --account=master
#SBATCH --partition=academic
#SBATCH --qos=academic
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=72
#SBATCH --mem=64G
#SBATCH --time=02:00:00
#SBATCH --output=slurm-%j.out
set -euo pipefail
PY="$HOME/.local/share/uv/python/cpython-3.12-linux-x86_64-gnu/bin/python3.12"
echo "job $SLURM_JOB_ID on $(hostname), $(nproc) cores: $*"
cd "$SLURM_SUBMIT_DIR"
srun --cpu-bind=none "$PY" "$@"
