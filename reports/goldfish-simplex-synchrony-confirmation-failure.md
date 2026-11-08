# Breaking Available and Safe Confirmation Permanence Under Synchrony

## 1. Problem Setting and Goal

In an ebb-and-flow consensus protocol (and in Decoupled Consensus specifically), **confirmation** is the mechanism that bridges the fast, optimistic available chain (Goldfish) and the slower, full-validator-set stabilization and finality gadgets (TSQ and Simplex):
- **External guarantee (Available Confirmation):** Under network synchrony ($\Delta = 25\%$ of a slot) and an honest majority ($< 1/2$ adversarial weight in the available committee, $< 1/3$ globally), once an honest node confirms a block $B$, $B$ should remain permanently in the canonical chain (**permanence** / no confirmation reorgs under synchrony).
- **Internal guarantee (Safe Confirmation):** Before any validator casts a full-set finality vote for a checkpoint target, it checks that the target is an ancestor of its **safe-confirmed head**—defined as the deepest available-confirmed block that is also **$G_0$-clear** (no conflicting branch holds $\ge 1/3$ of live full-validator-set head votes $D$).

During a **network partition** (asynchrony), available confirmations on the minority side are expected to break, because Goldfish is memoryless and prioritizes liveness during partitions. However, **under strict network synchrony ($\Delta = 25\%$ of a slot)**—where every honest message arrives within $\ll \Delta$ and the adversary controls $\le 25\%$ of the stake—**neither available confirmation nor safe confirmation should ever confirm a block that gets orphaned on the canonical chain.**

This document shows why **both** guarantees break under synchrony when a single slot has a malicious proposer, **even without any equivocation (zero double-proposals and zero double-votes)**, and reproduces the failure against the executable specification (`fradamt/consensus-specs@simplex-healing`).

---

## 2. Relevant Protocol Mechanics in the Specification

### 2.1 The Four In-Slot Deadlines (in Basis Points of a Slot)

Let slot duration be $T_{\text{slot}}$ ($12\text{ s}$ on mainnet, $6\text{ s}$ in the minimal preset) and maximum synchronous network delay be $\Delta = 25\%$ of a slot ($3\text{ s}$ on mainnet, $1.5\text{ s}$ in minimal):

| Slot Fraction | Spec Constant | Time (minimal) | Protocol Action |
|---|---|---|---|
| **$0\%$ ($0\Delta$)** | Slot start | $0\text{ ms}$ | Proposer of slot $s$ computes its head using slot $s-1$ votes and broadcasts block $B_s$. |
| **$25\%$ ($1\Delta$)** | `AVAILABLE_ATTESTATION_DUE_BPS = 2500` | $1500\text{ ms}$ | The 512-seat available committee for slot $s$ computes `get_head(store)` and broadcasts slot-$s$ available votes. Simultaneously, the $1/R$ cohort of validators assigned to slot $s$ casts its round finality attestation carrying `head = get_head(store)`. |
| **$50\%$ ($2\Delta$)** | `AVAILABLE_CONFIRMATION_DUE_BPS = 5000` | $3000\text{ ms}$ | Each node runs `freeze_available_votes(store, s)` to immutably freeze the slot-$s$ confirmation snapshot, and then runs `update_confirmation_heads(store)`. |
| **$75\%$ ($3\Delta$)** | `VIEW_FREEZE_DUE_BPS = 7500` | $4500\text{ ms}$ | Each node closes its live Goldfish view (`store.view_freeze_slots.add(s)`) so wire available votes arriving after $75\%$ are ignored. |

### 2.2 How the Head Walk (`get_head`) Scores Slot-$s$ Votes in Slot $s + 1$

When a node runs `get_head(store)` during slot $s + 1$ (both at $0\%$ when the slot-$(s+1)$ proposer chooses a parent block, and at $25\%$ when the slot-$(s+1)$ committee votes), Goldfish descends from the current round's `stable_root` using **all non-equivocating slot-$s$ available votes received before the $75\%$ view-freeze deadline** (`store.available_votes[s]`):

- **Live Goldfish denominator (`get_available_majority_threshold`):**
  Let $M_s^{\text{75\%}}$ be the total number of seats in the slot-$s$ committee whose votes arrived before the **$75\%$ ($3\Delta$)** view-freeze deadline. The strict-majority threshold is:
  $$\tau_{\text{head}}(s) = \left\lfloor \frac{M_s^{\text{75\%}}}{2} \right\rfloor.$$
- **Live Goldfish numerator (`get_available_attestation_score`):**
  Let $C_s^{\text{75\%}}(B)$ be the number of seats in `store.available_votes[s]` whose vote supports block $B$ (i.e., names $B$ or a descendant of $B$, plus any equivocating seats).
- **Viability condition (`is_available_attestation_viable`):**
  A block $B_s$ from slot $s$ is viable in slot $s + 1$'s head walk if and only if:
  $$C_s^{\text{75\%}}(B_s) > \left\lfloor \frac{M_s^{\text{75\%}}}{2} \right\rfloor.$$
  If this inequality fails ($C_s^{\text{75\%}}(B_s) \le \lfloor M_s^{\text{75\%}} / 2 \rfloor$), `get_head(store)` in slot $s + 1$ **rejects $B_s$**, stops at its parent $B_{s-1}$, and the honest slot-$(s+1)$ proposer builds $B_{s+1}$ as a sibling of $B_s$ directly on top of $B_{s-1}$.

### 2.3 How Delayed Available Confirmation Scores Slot-$s$ Votes in Slot $s + 1$

At **$50\%$ ($2\Delta$) of slot $s$**, `freeze_available_votes(store, s)` captures a separate, immutable snapshot `store.frozen_available_votes[s]` containing only the slot-$s$ available votes received at or before **$50\%$ ($2\Delta$)**.

One slot later—at **$50\%$ ($2\Delta$) of slot $s + 1$**—`update_confirmation_heads(store)` calls `get_available_confirmation_head(store)`, which walks the block tree from the finalized root using that frozen **$50\%$ snapshot from slot $s$**:

- **Frozen $50\%$ denominator (`get_available_confirmation_majority_threshold`):**
  Let $m_s^{\text{50\%}}$ be the number of seats in `store.frozen_available_votes[s]` (votes received by $50\%$ of slot $s$). The confirmation threshold is:
  $$\tau_{\text{conf}}(s) = \left\lfloor \frac{m_s^{\text{50\%}}}{2} \right\rfloor.$$
- **Frozen $50\%$ numerator (`get_available_confirmation_score`):**
  Let $c_s^{\text{50\%}}(B)$ be the number of seats in `store.frozen_available_votes[s]` whose vote supports $B$.
- **Confirmation condition (`is_available_confirmation_viable`):**
  Block $B_s$ is confirmed at $50\%$ of slot $s + 1$ if and only if:
  $$c_s^{\text{50\%}}(B_s) > \left\lfloor \frac{m_s^{\text{50\%}}}{2} \right\rfloor.$$

When this condition holds at $50\%$ of slot $s + 1$, `update_confirmation_heads(store)` sets:
1. `store.live_confirmed_head = (B_s, s + 1)` (the replaceable internal candidate), and
2. `store.latest_confirmed_head = update_confirmed_head(store, store.latest_confirmed_head, B_s)` (the user-facing monotonic confirmation log).

### 2.4 How Safe Confirmation Filters `live_confirmed_head` via $G_0$-Clearance

`get_safe_confirmed_head(store)` starts at `store.live_confirmed_head[0]` and walks up parent pointers until it finds a block $B$ that is **$G_0$-clear** (`is_g0_clear(store, B)`):
$$\text{is\_g0\_clear}(B) \iff \forall X \text{ conflicting with } B: \quad 3 \cdot S(X) < D,$$
where $D$ is the total stake of all active validators with an unexpired ($\le 128$-slot-old) finality-attestation head vote, and $S(X)$ is the stake of validators whose latest finality-attestation head vote supports $X$.

---

## 3. Why the Protocol Logic Is Unsafe Under Synchrony

There are **two compounding vulnerabilities** in the interaction of the rules above:

### Vulnerability 1: Bare Relative Majority at $50\%$ Has Zero Buffer Against Votes Arriving in $(50\%, 75\%]$

Compare **Fast Confirmation** (at $50\%$ of slot $s$) with **Delayed Available Confirmation** (frozen at $50\%$ of slot $s$, evaluated at $50\%$ of slot $s + 1$):
- **Why $3/4$ Fast Confirmation is safe:** Fast confirmation requires $c_s^{\text{50\%}}(B_s) \ge \frac{3}{4} N$ ($384/512$ seats). Because every vote seen by an honest node at $50\%$ ($2\Delta$) arrives at all honest nodes by $75\%$ ($3\Delta$), $B_s$ is guaranteed at least $\frac{3}{4} N - e$ votes in every honest node's $75\%$ view, while at most $\frac{1}{4} N$ remaining seats can appear between $50\%$ and $75\%$. For any adversary fraction $< 1/2$, $\frac{3}{4} N$ cannot be overturned between $50\%$ and $75\%$.
- **Why $> 1/2$ Delayed Confirmation is NOT safe:** Delayed confirmation uses a **bare relative majority ($c_s^{\text{50\%}}(B_s) > m_s^{\text{50\%}} / 2$)** over the $50\%$ snapshot, while the actual fork-choice head walk in slot $s + 1$ uses a bare relative majority ($C_s^{\text{75\%}}(B_s) > M_s^{\text{75\%}} / 2$) over the **$75\%$ view**!
  - Any vote that arrives in the window $(50\%, 75\%]$ is **excluded** from the confirmation snapshot $(m_s^{\text{50\%}}, c_s^{\text{50\%}})$, **but included** in the head-selection view $(M_s^{\text{75\%}}, C_s^{\text{75\%}})$!
  - Crucially, **not voting for $B_s$ does not require a conflicting block in slot $s$**: any slot-$s$ committee member that votes for the *parent block* $B_{s-1}$ adds $+1$ to the denominator $M_s^{\text{75\%}}$ while adding $0$ to the numerator $C_s^{\text{75\%}}(B_s)$!
  - Therefore, if a malicious proposer in slot $s$ delays its block $B_s$ within the synchronous bound so that honest voters at $25\%$ split between voting for $B_s$ (say $60\%$ of honest voters) and voting for the parent $B_{s-1}$ ($40\%$ of honest voters), then:
    1. At $50\%$ of slot $s$, only the honest votes have arrived: $B_s$ has $60\% > 50\%$ of $m_s^{\text{50\%}}$, so the $50\%$ confirmation snapshot **locks in a confirmation for $B_s$**.
    2. Between $50\%$ and $75\%$ of slot $s$, the adversary releases its own ($\le 25\%$) committee votes for the parent $B_{s-1}$. Those votes enter `store.available_votes[s]` before $75\%$, inflating the denominator $M_s^{\text{75\%}}$ so that $B_s$'s support drops **below $50\%$** ($C_s^{\text{75\%}}(B_s) \le M_s^{\text{75\%}} / 2$)!

### Vulnerability 2: $G_0$-Clearance Is Blind to Fresh Splits Because Only $1/R$ of Validators Vote Per Slot

When the honest proposer of slot $s + 1$ sees $C_s^{\text{75\%}}(B_s) \le M_s^{\text{75\%}} / 2$, it builds block $B_{s+1}$ on top of $B_{s-1}$ (orphaning $B_s$). At $25\%$ of slot $s + 1$, all honest voters vote for $B_{s+1}$.

Then, at **$50\%$ of slot $s + 1$**, `update_confirmation_heads(store)` evaluates the frozen $50\%$ snapshot from slot $s$ and sets `live_confirmed_head = B_s` and `latest_confirmed_head = B_s`.

Does the stabilization layer's **$G_0$-clear filter** (`is_g0_clear(store, B_s)`) catch that $B_s$ now conflicts with the canonical head $B_{s+1}$ and veto `get_safe_confirmed_head(store)`?
- **No!** Because `D` (`get_total_active_voting_weight`) is the sum of unexpired latest finality-attestation head votes across all $R$ cohorts of the round ($100\%$ of active stake $W$), while only **one cohort ($1/R$ of the validator set)** casts a finality attestation in slot $s + 1$!
- Even if $100\%$ of the slot-$(s+1)$ cohort votes for $B_{s+1}$ at $25\%$ of slot $s + 1$, the conflicting branch $B_{s+1}$ has weight:
  $$S(B_{s+1}) = \frac{1}{R} D = \begin{cases} \frac{1}{8} D = 12.5\% \cdot D < \frac{1}{3} D & (\text{minimal preset, } R = 8), \\[4pt] \frac{1}{32} D = 3.125\% \cdot D < \frac{1}{3} D & (\text{mainnet preset, } R = 32). \end{cases}$$
- Because $S(B_{s+1}) < \frac{1}{3} D$, **`is_g0_clear(store, B_s)` returns `True`!**
- Consequently, at $50\%$ of slot $s + 1$, **`get_safe_confirmed_head(store)` advances to the already-orphaned block $B_s$**, and then at $50\%$ of slot $s + 2$ it **reverses** onto $B_{s+1}$!

---

## 4. Step-by-Step Theoretical Scenario Under Synchrony

Consider a synchronous network with slot duration $T_{\text{slot}} = 6000\text{ ms}$, synchronous bound $\Delta = 1500\text{ ms}$ ($25\%$), normal honest-to-honest latency $200\text{ ms} \ll \Delta$, $N = 64$ validators across $4$ nodes:
- **Honest nodes (Nodes 0, 1, 2):** Control $75\%$ of the stake ($48/64$ validators, ~384 of the 512 available-committee seats).
  - Node 0 and Node 1 ("Early Honest", $50\%$ of total stake = 32 validators)
  - Node 2 ("Late Honest", $25\%$ of total stake = 16 validators)
- **Adversarial node (Node 3):** Controls $25\%$ of the stake ($16/64$ validators, ~128 of the 512 available-committee seats) and happens to be the proposer in a mid-round slot $s$ (e.g., slot $s = 10$).

### Timeline of the Attack (Slot $s$ to Slot $s + 2$)

1. **Slot $s$, $t = 200\text{ ms}$ (Adversarial Proposal Delivery within $\Delta = 1500\text{ ms}$):**
   - The adversarial proposer (Node 3) builds a single valid block $B_s$ extending $B_{s-1}$.
   - Node 3 sends $B_s$ so that it arrives at **Nodes 0 and 1** at $t = 1400\text{ ms}$ (just *before* the $1500\text{ ms}$ attestation deadline; delay $= 1200\text{ ms} < \Delta$) and at **Node 2** at $t = 1600\text{ ms}$ (just *after* the $1500\text{ ms}$ attestation deadline; delay $= 1400\text{ ms} < \Delta$).

2. **Slot $s$, $t = 1500\text{ ms}$ ($25\%$ — Attestation Deadline):**
   - **Nodes 0 and 1** (32 honest validators, $\approx 256$ committee seats) have received $B_s$, so their `get_head(store)` is **$B_s$**. They broadcast available votes for **$B_s$**.
   - **Node 2** (16 honest validators, $\approx 128$ committee seats) has not yet received $B_s$, so its `get_head(store)` is **$B_{s-1}$**. It broadcasts available votes for **$B_{s-1}$**.
   - **Node 3** (16 adversarial validators, $\approx 128$ committee seats) **withholds** its available votes for $B_{s-1}$ until after $t = 3000\text{ ms}$.
   - By $t = 1700\text{ ms}$, all honest nodes have received $B_s$ and all honest available votes ($\approx 256$ seats for $B_s$ and $\approx 128$ seats for $B_{s-1}$).

3. **Slot $s$, $t = 3000\text{ ms}$ ($50\%$ — Confirmation Freeze Deadline):**
   - Every honest node runs `freeze_available_votes(store, s)`:
     - Frozen denominator: $m_s^{\text{50\%}} \approx 256 + 128 = 384$ seats; majority threshold $\tau_{\text{conf}}(s) = 192$.
     - Frozen support for $B_s$: $c_s^{\text{50\%}}(B_s) \approx 256 > 192$ ($66.7\% > 50\%$).
     - Note that $256 < 384$ ($3/4$ of 512), so $B_s$ is *not* fast-confirmed in slot $s$, but its $> 50\%$ frozen snapshot is now **immutably armed** to trigger delayed confirmation in slot $s + 1$.

4. **Slot $s$, $t = 3200\text{ ms}$ (Adversarial Vote Release in $(50\%, 75\%]$):**
   - Node 3 broadcasts its $\approx 128$ available votes for **$B_{s-1}$**, which arrive at all honest nodes at $t = 3400\text{ ms}$ (well before the $4500\text{ ms}$ view-freeze deadline).
   - Every honest node adds Node 3's votes to `store.available_votes[s]`.
   - Now, in `store.available_votes[s]`:
     - Live denominator: $M_s^{\text{75\%}} = 512$ seats; majority threshold $\tau_{\text{head}}(s) = 256$.
     - Live support for $B_s$: $C_s^{\text{75\%}}(B_s) \approx 256 \not> 256$ (or if Early Honest had $\le 256$ seats, $C_s^{\text{75\%}}(B_s) \le \lfloor M_s^{\text{75\%}} / 2 \rfloor$)!

5. **Slot $s + 1$, $t = 0\text{ ms}$ and $t = 1500\text{ ms}$ (Canonical Chain Orphans $B_s$):**
   - At $t = 0\text{ ms}$ of slot $s + 1$, the honest proposer of slot $s + 1$ calls `get_head(store)`. Because $C_s^{\text{75\%}}(B_s) \le \lfloor M_s^{\text{75\%}} / 2 \rfloor$, `is_available_attestation_viable(store, B_s)` is **`False`**.
   - `get_head(store)` returns **$B_{s-1}$**, so the honest slot-$(s+1)$ proposer builds block **$B_{s+1}$ with parent $B_{s-1}$**, forking off $B_s$!
   - At $t = 1500\text{ ms}$ ($25\%$) of slot $s + 1$, all honest nodes see $B_{s+1}$ as the unique viable child of $B_{s-1}$ and cast their slot-$(s+1)$ available and finality votes for **$B_{s+1}$**.

6. **Slot $s + 1$, $t = 3000\text{ ms}$ ($50\%$ — Confirmation Permanence Breaks!):**
   - Every honest node runs `update_confirmation_heads(store)`:
     - `get_available_confirmation_head(store)` reads `store.frozen_available_votes[s]` (from $50\%$ of slot $s$), where $c_s^{\text{50\%}}(B_s) \approx 256 > 192$, and returns **$B_s$**!
     - `store.live_confirmed_head` is set to **$(B_s, s + 1)$**.
     - `store.latest_confirmed_head` advances to **$(B_s, s + 1)$**—**confirming a block $B_s$ that has already been orphaned by the canonical chain!**
     - `get_safe_confirmed_head(store)` checks `is_g0_clear(store, B_s)`. Because only slot $(s+1)$'s cohort ($\le 1/8 = 12.5\% < 1/3$ of $D$) has voted for $B_{s+1}$, `is_g0_clear(store, B_s)` is **`True`**, so **`get_safe_confirmed_head(store)` also confirms the orphaned block $B_s$!**

7. **Slot $s + 2$, $t = 3000\text{ ms}$ ($50\%$ — Safe Confirmation Reverses, Available Confirmation Remains Orphaned):**
   - At $50\%$ of slot $s + 2$, `get_available_confirmation_head(store)` reads `store.frozen_available_votes[s + 1]`, where all honest nodes voted for $B_{s+1}$, and returns **$B_{s+1}$**.
   - `store.live_confirmed_head` switches from $B_s$ to **$B_{s+1}$**.
   - `get_safe_confirmed_head(store)` **reverses** from $B_s$ to **$B_{s+1}$**!
   - `store.latest_confirmed_head` remains **stuck on the orphaned block $B_s$** until a later finalized checkpoint eventually overrides it.

---

## 5. Empirical Reproduction Against the Executable Spec

The script [`simulator/goldfish-simplex/synchrony_break_run.py`](../simulator/goldfish-simplex/synchrony_break_run.py) reproduces this failure directly on the unmodified `fradamt/consensus-specs@simplex-healing` (`minimal` preset) with **Seed 0** at **Slot 13**:

```bash
export SPECS=$HOME/Projects/consensus-specs
PYTHONPATH=$SPECS:$SPECS/tests/core/pyspec $SPECS/.venv/bin/python simulator/goldfish-simplex/synchrony_break_run.py
```

### 5.1 Parameters and Committee Split (Seed 0, Slot 13)

- **Validators & Stake:** $64$ equal-stake validators across $4$ nodes ($16$ validators $= 25\%$ stake per node).
  - **Nodes 0, 1 (Early Honest, $50\%$ stake):** Receive block `s13(ff24)` at $t = 1400\text{ ms} < \Delta = 1500\text{ ms}$ and vote for `s13(ff24)` at $t = 1500\text{ ms}$.
  - **Node 2 (Late Honest, $25\%$ stake):** Receives block `s13(ff24)` at $t = 1600\text{ ms}$ (emitted at $200\text{ ms}$, delay $= 1400\text{ ms} < \Delta = 1500\text{ ms}$) and therefore votes for parent `s12(e31f)` at $t = 1500\text{ ms}$.
  - **Node 3 (Adversary, $25\%$ stake):** Scheduled proposer in Slot 13 (validator 56); broadcasts its available vote for `s12(e31f)` at $t = 3200\text{ ms}$ (arriving at $3400\text{ ms}$, delay $= 200\text{ ms} \ll \Delta$).
- **Slot 13 Available Committee ($512$ seats):**
  - Early Honest (Nodes 0, 1): **$243$ seats** (vote for `s13(ff24)`)
  - Late Honest (Node 2): **$146$ seats** (vote for `s12(e31f)`)
  - Adversary (Node 3): **$123$ seats** (vote for `s12(e31f)`, arriving at $3400\text{ ms}$)
- **Snapshot vs. Live View Comparison:**
  - **At $50\%$ freeze ($3000\text{ ms}$):** `s13(ff24)` has **$243 / 389$ seats** ($62.5\% > 50\%$, threshold $194$) $\implies$ **Armed for delayed confirmation!**
  - **At $75\%$ freeze ($4500\text{ ms}$):** `s13(ff24)` has **$243 / 512$ seats** ($47.5\% \le 50\%$, threshold $256$) $\implies$ **Fails Goldfish head walk!**

### 5.2Observed Slot-by-Slot Trace

```text
slot | phase   | n0: head / live_conf / avail_conf / safe_conf (G0-clear?) | all honest heads
--------------------------------------------------------------------------------------------------
  12 | 50% conf |  s12(e31f) /  s11(5fce) /  s11(5fce) /  s11(5fce) (G0=True ) | ['s12(e31f)', 's12(e31f)', 's12(e31f)']
  13 | 0% start |  s12(e31f) /  s11(5fce) /  s11(5fce) /  s11(5fce) (G0=True ) | ['s12(e31f)', 's12(e31f)', 's12(e31f)']
  13 | 25% att  |  s13(ff24) /  s11(5fce) /  s11(5fce) /  s11(5fce) (G0=True ) | ['s13(ff24)', 's13(ff24)', 's12(e31f)']
  13 | 50% conf |  s13(ff24) /  s12(e31f) /  s12(e31f) /  s12(e31f) (G0=True ) | ['s13(ff24)', 's13(ff24)', 's13(ff24)']
  13 | 75% frz  |  s13(ff24) /  s12(e31f) /  s12(e31f) /  s12(e31f) (G0=True ) | ['s13(ff24)', 's13(ff24)', 's13(ff24)']
  14 | 0% start |  s14(3c49) /  s12(e31f) /  s12(e31f) /  s12(e31f) (G0=True ) | ['s14(3c49)', 's12(e31f)', 's12(e31f)']
  14 | 25% att  |  s14(3c49) /  s12(e31f) /  s12(e31f) /  s12(e31f) (G0=True ) | ['s14(3c49)', 's14(3c49)', 's14(3c49)']
  14 | 50% conf |  s14(3c49) /  s13(ff24) /  s13(ff24) /  s13(ff24) (G0=True ) | ['s14(3c49)', 's14(3c49)', 's14(3c49)']
  14 | 75% frz  |  s14(3c49) /  s13(ff24) /  s13(ff24) /  s13(ff24) (G0=True ) | ['s14(3c49)', 's14(3c49)', 's14(3c49)']
  15 | 25% att  |  s15(ff37) /  s13(ff24) /  s13(ff24) /  s13(ff24) (G0=True ) | ['s15(ff37)', 's15(ff37)', 's15(ff37)']
  15 | 50% conf |  s15(ff37) /  s14(3c49) /  s13(ff24) /  s14(3c49) (G0=True ) | ['s15(ff37)', 's15(ff37)', 's15(ff37)']
  16 | 50% conf |  s16(df4d) /  s15(ff37) /  s13(ff24) /  s15(ff37) (G0=True ) | ['s16(df4d)', 's16(df4d)', 's16(df4d)']
--------------------------------------------------------------------------------------------------
Max message delay observed across entire run: 1400 ms (synchronous bound Delta = 1500 ms)

=== SUMMARY FOR HONEST NODES (0, 1, 2) ===
Honest Node 0: orphaned available-confirmed blocks = [13] | orphaned safe-confirmed blocks = [13] | safe-confirmation reversals = [(15, 13)] | reorgs = [(14, 1, 12)]
Honest Node 1: orphaned available-confirmed blocks = [13] | orphaned safe-confirmed blocks = [13] | safe-confirmation reversals = [(15, 13)] | reorgs = [(14, 1, 12)]
Honest Node 2: orphaned available-confirmed blocks = [13] | orphaned safe-confirmed blocks = [13] | safe-confirmation reversals = [(15, 13)] | reorgs = [(14, 1, 12)]
```

### 5.3 Key Takeaways from the Trace

1. **At `14 | 0% start` and `14 | 25% att`:** Block `s13(ff24)` is **already orphaned**—the honest proposer of Slot 14 builds `s14(3c49)` on top of `s12(e31f)`, and by $25\%$ of Slot 14 every honest node's head is `s14(3c49)`.
2. **At `14 | 50% conf`:** Despite `s13(ff24)` already being off the canonical chain, `update_confirmation_heads` reads the frozen $50\%$ snapshot from Slot 13 and **confirms the orphaned block `s13(ff24)` across all three confirmation notions** (`live_conf`, `avail_conf`, and `safe_conf`, because `is_g0_clear(s13)` is `True`).
3. **At `15 | 50% conf`:** `live_conf` and `safe_conf` jump from `s13(ff24)` to the sibling branch `s14(3c49)` (a **safe-confirmation reversal** on every honest node), while user-facing `avail_conf` (`latest_confirmed_head`) remains stuck on the orphaned block `s13(ff24)`.
