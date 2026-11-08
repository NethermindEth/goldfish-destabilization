# Reports

Write-ups of the attacks we found, one per protocol. Each states the protocol version it targets,
the claim it breaks, the attack step by step, and how to reproduce it with the simulators in
`../simulator/`.

| Document | Protocol | Contents |
|---|---|---|
| `goldilocks-finalization-hiding/finalization_hiding.pdf` | Goldilocks (FGSA spec of 22 Oct 2026) | **Finalization hiding.** Under synchrony and with at most a third of the stake faulty, the adversary makes 3 of 4 honest nodes confirm and fast-lock a block that is then orphaned. It recaps the previous protocol's synchrony attack and how Goldilocks' locks were meant to prevent it. It then gives the attack with proposer equivocation, what changes with a fast test of > n/2, the variant without equivocation (three consecutive adversary slots, the block shown as confirmed for 22.5 s), the honest proposals it orphans, the fix, and an appendix on the premise of the Lean proof that the attack violates. The folder also holds the Typst sources and figures; build with `typst compile finalization_hiding.typ` |
| `goldfish-simplex-synchrony-confirmation-failure.md` | Goldfish + stabilization gadget + Simplex (`fradamt/consensus-specs@simplex-healing`) | **Confirmation broken under synchrony.** One malicious proposer, with no equivocation, makes honest nodes confirm (available and safe confirmation) a block that is later orphaned. It explains the in-slot deadlines, how the head walk and the confirmation rules count votes, the two weaknesses (a bare 50% majority with no buffer against late votes, and a G0-clearance check that misses fresh splits), and the run that reproduces it on the unmodified pyspec (`../simulator/goldfish-simplex/synchrony_break_run.py`) |

The Goldilocks report targets the 22 Oct 2026 spec. The live spec (`ethlabs-org/eth-consensus-lean`)
requires honest nodes to forward the votes carried by every block they accept, which is one of
the two fixes the report proposes and closes the attack.
