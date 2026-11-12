# Simulators

Multi-node simulators of the two protocols: honest nodes exchange blocks and votes over a simulated
network with per-message delays, partitions, sleep and restarts, and an adversary can control a
fraction of the validators. Each run checks the protocol's safety and liveness claims slot by
slot. Each folder's README has the commands, the model and its simplifications.

| Folder | Protocol | Contents |
|---|---|---|
| `goldilocks/` | Goldilocks (FGSA spec of 22 Oct 2026) | No executable fork choice exists upstream, so `model.py` transcribes the spec figure by figure in standard-library Python. Around it: the network driver (`sim.py`), partition and sleep scenarios, sweeps against the healing claim, a Byzantine adversary with targeted attacks and random fuzzing (`adversary.py`, including the finalization-hiding attacks), batch drivers, and the explorer pages. No dependencies |
| `goldilocks-live/` | Goldilocks, live spec (`ethlabs-org/eth-consensus-lean` at `4a63033e`, 10 Nov 2026) | The same harness on a transcription of the live spec: forwarding of every accepted object, an FG update after every tick, early votes on a ready proposal, optimistic confirmation, graded fast locks, and the FG's previous-height gate. Partition and sleep scenarios, and a timeout-delay sweep. No adversary yet. No dependencies |
| `goldfish-simplex/` | Goldfish + stabilization gadget + Simplex finality (`fradamt/consensus-specs@simplex-healing`) | A harness that drives the executable pyspec itself as N nodes: honest and partitioned runs, an adversary, stability and margin analyses, and the run that breaks confirmation under synchrony. Needs a local build of that pyspec (see its README) |
