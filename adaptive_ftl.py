"""
adaptive_ftl.py  —  RRA-FTL: Reliability-Remaining Adaptive FTL
================================================================
Three novel contributions over the original AdaptiveFTL:

1. WEIBULL VICTIM SCORING
   Replaces  WearScore = 1 - (erase_count / max_erase)  with
   Remaining_Budget = exp( -(erase_count / PE_endurance)^2 )
   This is a physics-grounded non-linear remaining-life signal,
   not a normalized usage counter.

2. GC-EPOCH PARETO ADAPTIVE TUNING
   Parameters (alpha, beta, gamma) are only recalibrated after a
   complete GC pass, not on a fixed write-count timer.
   Recalibration uses Pareto dominance: weights only shift when
   the current (WAF, WearVariance) operating point is dominated
   by a point in the recent epoch window.
   EMA damping prevents oscillation from short-term WAF spikes.

3. BLOCK QUARANTINE
   Blocks whose Weibull remaining_budget < QUARANTINE_THRESHOLD
   (default 0.05, i.e., ~95% worn) are excluded from GC victim
   selection. They retire gracefully holding cold data only.
"""

from ftl  import BaseFTL
from nand import PageState, PE_ENDURANCE

# ── Tuning constants ──────────────────────────────────────────────────────────
WEIBULL_K           = 2.0    # shape parameter for Weibull model
QUARANTINE_THRESHOLD = 0.05  # remaining_budget below which a block is quarantined
EMA_LAMBDA          = 0.1    # smoothing factor for WAF EMA (0.1 = slow/stable)
PARETO_WINDOW       = 10     # number of GC epochs tracked for Pareto dominance
TUNE_EVERY_N_GC     = 5      # recalibrate after every N GC epochs
DEAD_BAND_WAF       = 0.05   # minimum EMA_WAF deviation before adjusting alpha/gamma
DEAD_BAND_VAR       = 1.0    # minimum EMA_VAR deviation before adjusting beta


class AdaptiveFTL(BaseFTL):
    def __init__(self, nand_flash):
        super().__init__(nand_flash)

        self.pe_endurance = getattr(nand_flash, 'pe_endurance', PE_ENDURANCE)

        # Scoring weights
        self.alpha = 1.0   # Efficiency weight
        self.beta  = 1.0   # Remaining Budget (Weibull) weight
        self.gamma = 1.0   # Migration cost penalty weight

        # EMA signals
        self.ema_waf      = 1.0
        self.ema_variance = 0.0

        # Targets
        self.target_waf      = 2.0
        self.target_variance = 10.0

        # GC-epoch Pareto tracker
        self.gc_epoch_counter = 0
        self.pareto_window    = []   # list of (WAF, variance, alpha, beta, gamma)

        # LBA access tracking (for hot/cold awareness)
        self.lba_access_count = {}

    # ── Write path ────────────────────────────────────────────────────────────

    def write(self, logical_address: int):
        self.lba_access_count[logical_address] = (
            self.lba_access_count.get(logical_address, 0) + 1
        )
        super().write(logical_address)

    # ── Page allocation ───────────────────────────────────────────────────────

    def allocate_page(self):
        """Prefer blocks with the highest remaining_budget (freshest silicon)."""
        best_block = None
        best_budget = -1.0
        for block in self.nand.blocks:
            if block.free_pages > 0:
                rb = block.remaining_budget
                if rb > best_budget:
                    best_budget = rb
                    best_block  = block
        if best_block is None:
            return None, None
        return best_block.block_id, best_block.next_free_page_index

    # ── Garbage collection ────────────────────────────────────────────────────

    def garbage_collect(self):
        """
        RRA-FTL GC:
          1. Skip quarantined blocks (remaining_budget < threshold).
          2. Score candidates using Weibull-based Total Score.
          3. After GC completes, run Pareto-epoch adaptation.
        """
        self.gc_count        += 1
        self.gc_epoch_counter += 1

        victim_block  = None
        highest_score = -float('inf')

        for block in self.nand.blocks:
            if block.invalid_pages == 0:
                continue

            # Block quarantine — protect near-end-of-life blocks
            if block.remaining_budget < QUARANTINE_THRESHOLD:
                continue

            total_pages   = block.pages_per_block
            efficiency    = block.invalid_pages / total_pages
            migration     = block.valid_pages   / total_pages
            rem_budget    = block.remaining_budget   # Weibull score

            score = (
                self.alpha * efficiency
                - self.gamma * migration
                + self.beta  * rem_budget
            )

            if score > highest_score:
                highest_score = score
                victim_block  = block

        if not victim_block:
            return

        # Migrate valid pages to freshest available block
        for page in victim_block.pages:
            if page.state == PageState.VALID:
                lba = page.logical_address
                new_block_id, _ = self.allocate_page()
                if new_block_id is None:
                    break
                success, final_idx = self.nand.get_block(new_block_id).write_page(lba)
                if success:
                    self.l2p_map[lba] = (new_block_id, final_idx)
                    self.total_writes += 1

        victim_block.erase()

        # Pareto-epoch parameter adaptation (every TUNE_EVERY_N_GC epochs)
        if self.gc_epoch_counter % TUNE_EVERY_N_GC == 0:
            self._pareto_adapt()

    # ── Pareto-epoch adaptation ───────────────────────────────────────────────

    def _pareto_adapt(self):
        """
        GC-epoch Pareto Adaptive Tuning:
          1. Update EMA signals (damped, stable).
          2. Add current operating point to Pareto window.
          3. Check Pareto dominance — only adapt if dominated.
          4. Apply dead-band to prevent micro-thrashing.
        """
        raw_waf = self.get_waf()
        raw_var = self.get_wear_variance()

        # EMA update
        self.ema_waf      = EMA_LAMBDA * raw_waf      + (1 - EMA_LAMBDA) * self.ema_waf
        self.ema_variance = EMA_LAMBDA * raw_var      + (1 - EMA_LAMBDA) * self.ema_variance

        current_point = (self.ema_waf, self.ema_variance,
                         self.alpha, self.beta, self.gamma)
        self.pareto_window.append(current_point)

        # Keep window bounded
        if len(self.pareto_window) > PARETO_WINDOW:
            self.pareto_window.pop(0)

        # Check if current point is Pareto-dominated by any point in window
        dominated = False
        best_params = None
        for p in self.pareto_window[:-1]:   # compare against all but current
            if p[0] <= self.ema_waf and p[1] <= self.ema_variance:
                dominated  = True
                best_params = p  # drive toward the dominating point's weights
                break

        if not dominated:
            return  # on or near Pareto front — no adaptation needed

        # Dead-band checks before adjusting
        waf_deviation = self.ema_waf - self.target_waf
        var_deviation = self.ema_variance - self.target_variance

        delta       = 0.05
        delta_small = 0.01

        # Emergency override: WAF runaway
        if self.ema_waf > 6.0:
            self.alpha = 1.5
            self.gamma = 1.5
            self.beta  = 0.5
        else:
            if waf_deviation > DEAD_BAND_WAF:
                self.alpha += delta
                self.gamma += delta
                self.beta  -= delta_small

            if var_deviation > DEAD_BAND_VAR:
                self.beta  += delta
                self.alpha -= delta_small

        # Clamp weights
        self.alpha = max(0.1, min(self.alpha, 2.0))
        self.beta  = max(0.1, min(self.beta,  2.0))
        self.gamma = max(0.1, min(self.gamma, 2.0))
