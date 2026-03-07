#ifndef GC_AND_WL_UNIT_PAGE_LEVEL_RRA_H
#define GC_AND_WL_UNIT_PAGE_LEVEL_RRA_H

/*
 * GC_and_WL_Unit_Page_Level_RRA.h
 * ================================
 * RRA-FTL: Reliability-Remaining Adaptive GC & Wear-Leveling Unit
 *
 * HOW THIS PLUGS INTO MQSIM
 * --------------------------
 * MQSim's class hierarchy for GC:
 *
 *   GC_and_WL_Unit_Base          (MQSim — handles scheduling, erase dispatch)
 *     └── GC_and_WL_Unit_Page_Level   (MQSim — GREEDY/RGA/RANDOM/FIFO policy)
 *           └── GC_and_WL_Unit_Page_Level_RRA   ← THIS FILE
 *
 * We override exactly ONE virtual function:
 *   Block_Pool_Slot_Type* GC_and_WL_Unit_Page_Level::Get_next_gc_victim()
 *
 * Everything else (erase dispatch, transaction management, plane FSM,
 * preemptible GC, copyback) remains 100% vanilla MQSim — we do not touch it.
 *
 * To activate in FTL.cpp, in the section that creates GC_and_WL_Unit:
 *   BEFORE:
 *     GC_and_WL_Unit = new GC_and_WL_Unit_Page_Level(...)
 *   AFTER:
 *     GC_and_WL_Unit = new GC_and_WL_Unit_Page_Level_RRA(...)
 * See FTL_RRA_patch.cpp for the exact diff.
 *
 * v2 IMPROVEMENTS
 * -----------------
 * [1] COMPOSITE VICTIM SCORE (upgraded)
 *       Score(b) = α * Efficiency(b)         ← invalid ratio
 *                - β * MigrationCost(b)       ← valid ratio penalty   [STRONGER β]
 *                + γ * RemainingBudget(b)     ← Weibull health
 *                + δ * HotBlockBonus(b)       ← +1 if hot block       [NEW]
 *
 * [2] ADAPTIVE GC THRESHOLD                                            [NEW]
 *       threshold = base * (1 + pressure_K * write_pressure)
 *                        * (1 + age_K     * avg_wear_ratio)
 *
 * [3] HOT/COLD TRACKING                                                [NEW]
 *     Per-block write counter — blocks over HOT_WRITE_THRESHOLD
 *     get the δ bonus, making GC prefer cycling hot data blocks.
 *
 * [4] WEIBULL VICTIM SCORING (v1, retained)
 * [5] ADAPTIVE ERASE LATENCY (v1, retained)
 * [6] GC-EPOCH PARETO ADAPTIVE TUNING (v1, retained)
 * [7] BLOCK QUARANTINE (v1, retained)
 */

#include "GC_and_WL_Unit_Page_Level.h"
#include <cmath>
#include <deque>
#include <vector>
#include <limits>
#include <unordered_map>

namespace SSD_Components {

// ── Physical constants (MLC NAND defaults) ────────────────────────────────────
constexpr double RRA_PE_ENDURANCE_DEFAULT   = 10000.0;
constexpr double RRA_WEIBULL_K              = 2.0;
constexpr double RRA_QUARANTINE_THRESHOLD   = 0.05;
constexpr double RRA_T_BASE_NS              = 1500000.0;
constexpr double RRA_K_AGE                  = 1.0;
constexpr double RRA_P_BASE_ERR             = 1e-6;
constexpr double RRA_K_ERR                  = 3.0;

// ── v2 scoring weights ──────────────────────────────────────────────────────
constexpr double RRA_DEFAULT_ALPHA          = 1.0;
constexpr double RRA_DEFAULT_BETA           = 2.0;   // stronger migration penalty [v2]
constexpr double RRA_DEFAULT_GAMMA          = 1.0;
constexpr double RRA_DEFAULT_DELTA          = 0.5;   // hot-block bonus            [NEW]

// ── Adaptive GC threshold [NEW] ─────────────────────────────────────────────
constexpr double RRA_ADAPTIVE_PRESSURE_K    = 2.0;
constexpr double RRA_ADAPTIVE_AGE_K         = 0.5;

// ── Hot/cold classification [NEW] ──────────────────────────────────────────
constexpr unsigned int RRA_HOT_WRITE_THRESHOLD = 4;

// ── Pareto / EMA tuning constants ────────────────────────────────────────────
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

// ── Metrics snapshot ─────────────────────────────────────────────────────────
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
        GC_Block_Selection_Policy_Type  gc_policy,   // pass RRA_WEIBULL from FTL
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
        // RRA-FTL specific — all have defaults so existing call-sites compile
        double  pe_endurance        = RRA_PE_ENDURANCE_DEFAULT,
        double  initial_alpha       = RRA_DEFAULT_ALPHA,
        double  initial_beta        = RRA_DEFAULT_BETA,
        double  initial_gamma       = RRA_DEFAULT_GAMMA,
        double  initial_delta       = RRA_DEFAULT_DELTA   // [NEW]
    );

    ~GC_and_WL_Unit_Page_Level_RRA() = default;

    // ── THE ONE FUNCTION WE OVERRIDE ─────────────────────────────────────────
    // MQSim calls this inside Check_gc_required() / Execute_gc_for_one_plane()
    // to decide which block to erase next.
    Block_Pool_Slot_Type* Get_next_gc_victim(
        PlaneBookKeepingType* plane_bookkeeping,
        const NVM::FlashMemory::Physical_Page_Address& plane_address);

    // ── Adaptive erase latency injection ─────────────────────────────────────
    // Called from GC_and_WL_Unit_Base::Execute_gc_for_one_plane just before
    // dispatching the erase transaction to the TSU.  We override it to patch
    // the transaction's Time_to_transfer_die field with the per-block latency.
    void Set_erase_transaction_time(
        NVM_Transaction_Flash_ER* erase_tr,
        Block_Pool_Slot_Type*     victim_block);

    // ── Metrics accessors (for custom output reporter) ────────────────────────
    RRA_Metrics Get_rra_metrics() const;

private:
    // ── RRA-FTL algorithm state ───────────────────────────────────────────────
    double       m_pe_endurance;
    double       m_alpha, m_beta, m_gamma, m_delta;   // m_delta [NEW]
    double       m_ema_waf, m_ema_variance;
    unsigned int m_gc_epoch_counter;
    double       m_total_adaptive_erase_ns;

    // ── Adaptive GC threshold [NEW] ───────────────────────────────────────────
    double       m_base_gc_threshold;
    double       m_adaptive_gc_threshold;
    unsigned int m_recent_write_count;

    // ── Hot/cold tracking [NEW] ───────────────────────────────────────────────
    std::unordered_map<flash_block_ID_type, unsigned int> m_block_write_counts;

    std::deque<RRA_ParetoPoint> m_pareto_window;

    // Weibull LUT (Q10 fixed-point: value/1024.0 = double score)
    uint16_t m_weibull_lut[RRA_LUT_SIZE];

    // ── Internal helpers ──────────────────────────────────────────────────────
    void   Build_weibull_lut();
    double Weibull_score(unsigned int erase_count) const;
    double Adaptive_erase_ns(unsigned int erase_count) const;
    double Compute_wear_variance(PlaneBookKeepingType* pbk) const;
    void   Pareto_adapt(PlaneBookKeepingType* pbk);
    void   Update_adaptive_threshold(PlaneBookKeepingType* pbk);  // [NEW]
};

} // namespace SSD_Components

#endif // GC_AND_WL_UNIT_PAGE_LEVEL_RRA_H
