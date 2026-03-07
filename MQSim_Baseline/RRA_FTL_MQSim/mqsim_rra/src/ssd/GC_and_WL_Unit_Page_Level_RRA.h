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
 * THREE NOVEL CONTRIBUTIONS
 * --------------------------
 * [1] WEIBULL VICTIM SCORING
 *     All existing MQSim policies (GREEDY, RGA, RANDOM, FIFO) use
 *     invalid_page_count as the primary signal. RRA-FTL replaces the
 *     wear term with a physics-grounded Weibull Remaining Budget:
 *
 *       RemainingBudget(b) = exp( -(EraseCount / PE_Endurance)^k )   k=2
 *
 *     Total victim score:
 *       Score(b) = alpha * Efficiency(b)
 *                - gamma * MigrationCost(b)
 *                + beta  * RemainingBudget(b)
 *
 *     At 90% PE wear, RemainingBudget = 0.055 (not 0.10 as linear).
 *     This strongly steers GC away from near-end-of-life blocks.
 *
 * [2] ADAPTIVE ERASE LATENCY
 *     MQSim uses a fixed erase_time_ns from ssdconfig.xml for all
 *     blocks at all ages. RRA-FTL computes per-block erase latency:
 *
 *       EraseTime(b) = T_base_ns * (1 + K_age * EraseCount/PE_Endurance)
 *
 *     This is injected into the NVM_Transaction_Flash_ER that MQSim
 *     dispatches via the TSU, so P99 latency stats in MQSim's output
 *     XML accurately reflect block aging.
 *
 * [3] GC-EPOCH PARETO ADAPTIVE TUNING
 *     Alpha/beta/gamma are recalibrated after every TUNE_EVERY_N_GC
 *     complete GC passes — not on a fixed write-count timer.
 *     Adaptation uses Pareto dominance over a rolling window:
 *     weights only shift when the current (WAF, WearVariance) point
 *     is dominated by a better point seen recently.
 *     EMA damping + dead-band prevent oscillation.
 *
 * [4] BLOCK QUARANTINE
 *     Blocks with RemainingBudget < QUARANTINE_THRESHOLD are skipped
 *     entirely as GC victims. They retire holding cold data only.
 */

#include "GC_and_WL_Unit_Page_Level.h"
#include <cmath>
#include <deque>
#include <vector>
#include <limits>

namespace SSD_Components {

// ── Physical constants (MLC NAND defaults, override via constructor) ──────────
constexpr double RRA_PE_ENDURANCE_DEFAULT   = 10000.0;
constexpr double RRA_WEIBULL_K              = 2.0;
constexpr double RRA_QUARANTINE_THRESHOLD   = 0.05;   // ~95% worn → quarantine
constexpr double RRA_T_BASE_NS              = 1500000.0; // 1.5 ms in nanoseconds
constexpr double RRA_K_AGE                  = 1.0;
constexpr double RRA_P_BASE_ERR             = 1e-6;
constexpr double RRA_K_ERR                  = 3.0;

// ── Pareto / EMA tuning constants ────────────────────────────────────────────
constexpr double RRA_EMA_LAMBDA             = 0.1;
constexpr int    RRA_PARETO_WINDOW_SIZE     = 10;
constexpr int    RRA_TUNE_EVERY_N_GC        = 5;
constexpr double RRA_DEAD_BAND_WAF          = 0.05;
constexpr double RRA_DEAD_BAND_VAR          = 1.0;
constexpr double RRA_TARGET_WAF             = 2.0;
constexpr double RRA_TARGET_VAR             = 10.0;
constexpr double RRA_WAF_RUNAWAY_THRESHOLD  = 6.0;

// ── Weibull LUT: 157 Q10 fixed-point entries, index = erase_count / 64 ───────
// Eliminates all floating-point ops from the hot GC victim-selection path.
constexpr int    RRA_LUT_SIZE               = 157;
constexpr int    RRA_LUT_BUCKET             = 64;

struct RRA_ParetoPoint {
    double waf;
    double variance;
    double alpha, beta, gamma;
};

// ── Metrics snapshot exposed to MQSim output reporting ────────────────────────
struct RRA_Metrics {
    double  mean_remaining_budget   = 1.0;
    double  total_adaptive_erase_ns = 0.0;
    double  ema_waf                 = 1.0;
    double  ema_variance            = 0.0;
    double  alpha                   = 1.0;
    double  beta                    = 1.0;
    double  gamma                   = 1.0;
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
        double  initial_alpha       = 1.0,
        double  initial_beta        = 1.0,
        double  initial_gamma       = 1.0
    );

    ~GC_and_WL_Unit_Page_Level_RRA() override = default;

    // ── THE ONE FUNCTION WE OVERRIDE ─────────────────────────────────────────
    // MQSim calls this inside Check_gc_required() / Execute_gc_for_one_plane()
    // to decide which block to erase next.
    Block_Pool_Slot_Type* Get_next_gc_victim(
        PlaneBookKeepingType* plane_bookkeeping,
        const NVM::FlashMemory::Physical_Page_Address& plane_address) override;

    // ── Adaptive erase latency injection ─────────────────────────────────────
    // Called from GC_and_WL_Unit_Base::Execute_gc_for_one_plane just before
    // dispatching the erase transaction to the TSU.  We override it to patch
    // the transaction's Time_to_transfer_die field with the per-block latency.
    void Set_erase_transaction_time(
        NVM_Transaction_Flash_ER* erase_tr,
        Block_Pool_Slot_Type*     victim_block) override;

    // ── Metrics accessors (for custom output reporter) ────────────────────────
    RRA_Metrics Get_rra_metrics() const;

private:
    // ── RRA-FTL algorithm state ───────────────────────────────────────────────
    double       m_pe_endurance;
    double       m_alpha, m_beta, m_gamma;
    double       m_ema_waf, m_ema_variance;
    unsigned int m_gc_epoch_counter;
    double       m_total_adaptive_erase_ns;

    std::deque<RRA_ParetoPoint> m_pareto_window;

    // Weibull LUT (Q10 fixed-point: value/1024.0 = double score)
    uint16_t m_weibull_lut[RRA_LUT_SIZE];

    // ── Internal helpers ──────────────────────────────────────────────────────
    void   Build_weibull_lut();
    double Weibull_score(unsigned int erase_count) const;
    double Adaptive_erase_ns(unsigned int erase_count) const;
    double Compute_wear_variance(PlaneBookKeepingType* pbk) const;
    void   Pareto_adapt(PlaneBookKeepingType* pbk);
};

} // namespace SSD_Components

#endif // GC_AND_WL_UNIT_PAGE_LEVEL_RRA_H
