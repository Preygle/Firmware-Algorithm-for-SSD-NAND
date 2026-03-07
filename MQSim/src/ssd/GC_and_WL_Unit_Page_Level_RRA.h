#ifndef GC_AND_WL_UNIT_PAGE_LEVEL_RRA_H
#define GC_AND_WL_UNIT_PAGE_LEVEL_RRA_H

/*
 * GC_and_WL_Unit_Page_Level_RRA.h
 * ================================
 * RRA-FTL v2: Reliability-Remaining Adaptive GC & Wear-Leveling Unit
 *
 * IMPROVEMENTS IN v2
 * -------------------
 * [1] COMPOSITE VICTIM SCORE (upgraded)
 *       Score(b) = α * Efficiency(b)          ← invalid page ratio
 *                - β * MigrationCost(b)        ← valid page ratio penalty  [NEW]
 *                + γ * RemainingBudget(b)      ← Weibull wear-health term
 *                + δ * HotBlockBonus(b)        ← GC hot data first         [NEW]
 *
 * [2] ADAPTIVE GC THRESHOLD                                                 [NEW]
 *       threshold = base * (1 + write_pressure_factor)
 *                        * (1 + avg_wear / max_PE_cycles)
 *     Raises urgency under write bursts and as the drive ages.
 *
 * [3] WEAR-LEVELING WRITE FRONTIER                                          [NEW]
 *     Every time a new write frontier block is needed we scan the free pool
 *     and pick the block with the LOWEST erase count instead of any block.
 *
 * [4] HOT/COLD TRACKING                                                     [NEW]
 *     Maintains a per-block write-access counter.  Blocks above
 *     HOT_WRITE_THRESHOLD are marked Hot and receive +δ GC bonus.
 *
 * [5] WEIBULL VICTIM SCORING (unchanged from v1)
 *     RemainingBudget(b) = exp(-(EraseCount / PE_Endurance)^k),  k=2
 *
 * [6] ADAPTIVE ERASE LATENCY (unchanged from v1)
 *     EraseTime(b) = T_base_ns * (1 + K_age * EraseCount / PE_Endurance)
 *
 * [7] GC-EPOCH PARETO ADAPTIVE TUNING (unchanged from v1)
 *     α/β/γ recalibrated every TUNE_EVERY_N_GC GC passes using
 *     Pareto dominance + EMA damping + dead-band.
 *
 * [8] BLOCK QUARANTINE (unchanged from v1)
 *     Blocks with RemainingBudget < QUARANTINE_THRESHOLD are skipped.
 */

#include "GC_and_WL_Unit_Page_Level.h"
#include <cmath>
#include <deque>
#include <vector>
#include <limits>
#include <unordered_map>

namespace SSD_Components {

// ── Physical constants ──────────────────────────────────────────────────────
constexpr double RRA_PE_ENDURANCE_DEFAULT   = 10000.0;
constexpr double RRA_WEIBULL_K              = 2.0;
constexpr double RRA_QUARANTINE_THRESHOLD   = 0.05;    // ~95% worn → quarantine
constexpr double RRA_T_BASE_NS              = 1500000.0;
constexpr double RRA_K_AGE                  = 1.0;
constexpr double RRA_P_BASE_ERR             = 1e-6;
constexpr double RRA_K_ERR                  = 3.0;

// ── v2 scoring weights ──────────────────────────────────────────────────────
constexpr double RRA_DEFAULT_ALPHA          = 1.0;   // efficiency weight
constexpr double RRA_DEFAULT_BETA           = 2.0;   // migration cost penalty [INCREASED vs v1]
constexpr double RRA_DEFAULT_GAMMA          = 1.0;   // Weibull remaining-budget weight
constexpr double RRA_DEFAULT_DELTA          = 0.5;   // hot-block GC bonus     [NEW]

// ── Adaptive GC threshold factors ──────────────────────────────────────────
constexpr double RRA_ADAPTIVE_PRESSURE_K    = 2.0;   // write pressure multiplier [NEW]
constexpr double RRA_ADAPTIVE_AGE_K         = 0.5;   // age multiplier            [NEW]

// ── Hot/cold classification ─────────────────────────────────────────────────
constexpr unsigned int RRA_HOT_WRITE_THRESHOLD = 4;  // writes/block → "hot"  [NEW]

// ── Pareto / EMA tuning constants ──────────────────────────────────────────
constexpr double RRA_EMA_LAMBDA             = 0.1;
constexpr int    RRA_PARETO_WINDOW_SIZE     = 10;
constexpr int    RRA_TUNE_EVERY_N_GC        = 5;
constexpr double RRA_DEAD_BAND_WAF          = 0.05;
constexpr double RRA_DEAD_BAND_VAR          = 1.0;
constexpr double RRA_TARGET_WAF             = 2.0;
constexpr double RRA_TARGET_VAR             = 10.0;
constexpr double RRA_WAF_RUNAWAY_THRESHOLD  = 6.0;

// ── Weibull LUT ─────────────────────────────────────────────────────────────
constexpr int    RRA_LUT_SIZE               = 157;
constexpr int    RRA_LUT_BUCKET             = 64;

struct RRA_ParetoPoint {
    double waf;
    double variance;
    double alpha, beta, gamma;
};

struct RRA_Metrics {
    double  mean_remaining_budget   = 1.0;
    double  total_adaptive_erase_ns = 0.0;
    double  ema_waf                 = 1.0;
    double  ema_variance            = 0.0;
    double  alpha                   = 1.0;
    double  beta                    = 1.0;
    double  gamma                   = 1.0;
    double  delta                   = 0.5;   // [NEW]
    double  adaptive_threshold      = 0.05;  // [NEW]
    unsigned int gc_epoch           = 0;
    RRA_Metrics() {}
    RRA_Metrics(double mrb, double t, double ew, double ev,
                double a, double b, double g, double d, double thr, unsigned int ge)
        : mean_remaining_budget(mrb), total_adaptive_erase_ns(t),
          ema_waf(ew), ema_variance(ev),
          alpha(a), beta(b), gamma(g), delta(d),
          adaptive_threshold(thr), gc_epoch(ge) {}
};

// ─────────────────────────────────────────────────────────────────────────────
class GC_and_WL_Unit_Page_Level_RRA : public GC_and_WL_Unit_Page_Level
{
public:
    GC_and_WL_Unit_Page_Level_RRA(
        const sim_object_id_type&       id,
        Address_Mapping_Unit_Base*      address_mapping_unit,
        Flash_Block_Manager_Base*       block_manager,
        TSU_Base*                       tsu,
        NVM_PHY_ONFI*                   flash_controller,
        GC_Block_Selection_Policy_Type  gc_policy,
        double  gc_threshold,
        bool    preemptible_gc_enabled,
        double  gc_hard_threshold,
        unsigned int channel_count,
        unsigned int chip_count,
        unsigned int die_count,
        unsigned int plane_count,
        unsigned int block_count,
        unsigned int page_count,
        unsigned int sectors_per_page,
        bool    copy_back_enabled,
        double  wl_threshold,
        double  pe_endurance        = RRA_PE_ENDURANCE_DEFAULT,
        double  initial_alpha       = RRA_DEFAULT_ALPHA,
        double  initial_beta        = RRA_DEFAULT_BETA,
        double  initial_gamma       = RRA_DEFAULT_GAMMA,
        double  initial_delta       = RRA_DEFAULT_DELTA
    );

    ~GC_and_WL_Unit_Page_Level_RRA() = default;

    // ── Main override: victim selection + GC dispatch ─────────────────────
    void Check_gc_required(
        const unsigned int free_block_pool_size,
        const NVM::FlashMemory::Physical_Page_Address& plane_address) override;

    // ── Victim selection (called from Check_gc_required) ─────────────────
    Block_Pool_Slot_Type* Get_next_gc_victim(
        PlaneBookKeepingType* plane_bookkeeping,
        const NVM::FlashMemory::Physical_Page_Address& plane_address);

    // ── Adaptive erase latency injection ─────────────────────────────────
    void Set_erase_transaction_time(
        NVM_Transaction_Flash_ER* erase_tr,
        Block_Pool_Slot_Type*     victim_block);

    // ── Hot/cold write counter update (call on every page write) ─────────
    void Record_page_write(flash_block_ID_type block_id);   // [NEW]

    // ── Metrics accessors ────────────────────────────────────────────────
    RRA_Metrics Get_rra_metrics() const;

private:
    // ── RRA algorithm state ───────────────────────────────────────────────
    double       m_pe_endurance;
    double       m_alpha, m_beta, m_gamma, m_delta;   // m_delta [NEW]
    double       m_ema_waf, m_ema_variance;
    unsigned int m_gc_epoch_counter;
    double       m_total_adaptive_erase_ns;

    // ── Adaptive GC threshold state [NEW] ─────────────────────────────────
    double       m_base_gc_threshold;          // from ssdconfig GC_Exec_Threshold
    double       m_adaptive_gc_threshold;      // current effective threshold
    unsigned int m_recent_write_count;         // writes since last threshold update
    unsigned int m_threshold_update_interval;  // update every N writes

    // ── Hot/cold tracking [NEW] ──────────────────────────────────────────
    // block_id → write access count (per-plane, reset per GC epoch)
    std::unordered_map<flash_block_ID_type, unsigned int> m_block_write_counts;

    std::deque<RRA_ParetoPoint> m_pareto_window;

    // Weibull LUT (Q10 fixed-point)
    uint16_t m_weibull_lut[RRA_LUT_SIZE];

    // ── Internal helpers ──────────────────────────────────────────────────
    void   Build_weibull_lut();
    double Weibull_score(unsigned int erase_count) const;
    double Adaptive_erase_ns(unsigned int erase_count) const;
    double Compute_wear_variance(PlaneBookKeepingType* pbk) const;
    void   Pareto_adapt(PlaneBookKeepingType* pbk);

    // [NEW] Adaptive threshold update
    void   Update_adaptive_threshold(PlaneBookKeepingType* pbk);

    // [NEW] Wear-leveling: pick lowest-erase free block as write frontier
    flash_block_ID_type Get_wl_write_frontier(PlaneBookKeepingType* pbk) const;
};

} // namespace SSD_Components

#endif // GC_AND_WL_UNIT_PAGE_LEVEL_RRA_H
