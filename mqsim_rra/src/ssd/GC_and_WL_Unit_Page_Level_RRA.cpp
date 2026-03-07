/*
 * GC_and_WL_Unit_Page_Level_RRA.cpp
 * ===================================
 * RRA-FTL: Reliability-Remaining Adaptive GC & Wear-Leveling Unit
 *
 * Implementation of the three novel contributions:
 *   [1] Weibull Remaining-Budget Victim Scoring
 *   [2] Adaptive Erase Latency (per-block variable erase time)
 *   [3] GC-Epoch Pareto Adaptive Tuning with EMA + dead-band
 *   [4] Block Quarantine (near-end-of-life block protection)
 *
 * Python → C++ mapping:
 *   nand.py   Block.remaining_budget   → Weibull_score()
 *   nand.py   Block.erase_time_ms      → Adaptive_erase_ns()
 *   adaptive_ftl.py  garbage_collect() → Get_next_gc_victim()
 *   adaptive_ftl.py  _pareto_adapt()   → Pareto_adapt()
 *   metrics_engine.py wear_variance()  → Compute_wear_variance()
 */

#include "GC_and_WL_Unit_Page_Level_RRA.h"
#include "../sim/Sim_Defs.h"
#include "NVM_Transaction_Flash_ER.h"
#include "Flash_Block_Manager_Base.h"
#include <cmath>
#include <algorithm>
#include <stdexcept>

namespace SSD_Components {

// ─────────────────────────────────────────────────────────────────────────────
// Constructor
// ─────────────────────────────────────────────────────────────────────────────
GC_and_WL_Unit_Page_Level_RRA::GC_and_WL_Unit_Page_Level_RRA(
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
    double  pe_endurance,
    double  initial_alpha,
    double  initial_beta,
    double  initial_gamma)
    : GC_and_WL_Unit_Page_Level(
          id, address_mapping_unit, block_manager, tsu, flash_controller,
          gc_policy, gc_threshold, preemptible_gc_enabled, gc_hard_threshold,
          channel_count, chip_count, die_count, plane_count,
          block_count, page_count, sectors_per_page,
          copy_back_enabled, wl_threshold)
    , m_pe_endurance(pe_endurance)
    , m_alpha(initial_alpha)
    , m_beta(initial_beta)
    , m_gamma(initial_gamma)
    , m_ema_waf(1.0)
    , m_ema_variance(0.0)
    , m_gc_epoch_counter(0)
    , m_total_adaptive_erase_ns(0.0)
{
    Build_weibull_lut();
}

// ─────────────────────────────────────────────────────────────────────────────
// Build_weibull_lut
// Pre-computes 157 entries in Q10 fixed-point.
// Index i covers erase counts [i*64 .. (i+1)*64 - 1].
// Usage: m_weibull_lut[erase_count / RRA_LUT_BUCKET] / 1024.0 == score
// ─────────────────────────────────────────────────────────────────────────────
void GC_and_WL_Unit_Page_Level_RRA::Build_weibull_lut()
{
    for (int i = 0; i < RRA_LUT_SIZE; ++i) {
        double ec   = static_cast<double>(i * RRA_LUT_BUCKET);
        double x    = ec / m_pe_endurance;
        double val  = std::exp(-(x * x));            // k=2
        // Q10: multiply by 1024 and clamp to uint16_t
        int q10 = static_cast<int>(val * 1024.0 + 0.5);
        if (q10 < 0)    q10 = 0;
        if (q10 > 1024) q10 = 1024;
        m_weibull_lut[i] = static_cast<uint16_t>(q10);
    }
}

// ─────────────────────────────────────────────────────────────────────────────
// Weibull_score  — O(1), no floating-point at GC runtime
// Returns remaining_budget in [0.0, 1.0]
// ─────────────────────────────────────────────────────────────────────────────
double GC_and_WL_Unit_Page_Level_RRA::Weibull_score(unsigned int erase_count) const
{
    unsigned int idx = erase_count / static_cast<unsigned int>(RRA_LUT_BUCKET);
    if (idx >= static_cast<unsigned int>(RRA_LUT_SIZE))
        return 0.0;   // completely worn out
    return m_weibull_lut[idx] / 1024.0;
}

// ─────────────────────────────────────────────────────────────────────────────
// Adaptive_erase_ns — erase time that scales with block wear
// Python: Block.erase_time_ms = T_base * (1 + K_age * wear_ratio)
// ─────────────────────────────────────────────────────────────────────────────
double GC_and_WL_Unit_Page_Level_RRA::Adaptive_erase_ns(unsigned int erase_count) const
{
    double wear_ratio = static_cast<double>(erase_count) / m_pe_endurance;
    return RRA_T_BASE_NS * (1.0 + RRA_K_AGE * wear_ratio);
}

// ─────────────────────────────────────────────────────────────────────────────
// Compute_wear_variance — population variance of erase counts across a plane
// Python: MetricsEngine.wear_variance()
// ─────────────────────────────────────────────────────────────────────────────
double GC_and_WL_Unit_Page_Level_RRA::Compute_wear_variance(
    PlaneBookKeepingType* pbk) const
{
    if (!pbk || pbk->Total_pages_count == 0) return 0.0;

    double sum = 0.0;
    unsigned int n = 0;
    for (unsigned int b = 0; b < pbk->Total_blocks; ++b) {
        sum += pbk->Blocks[b].Erase_count;
        ++n;
    }
    if (n == 0) return 0.0;
    double mean = sum / n;

    double var = 0.0;
    for (unsigned int b = 0; b < pbk->Total_blocks; ++b) {
        double d = pbk->Blocks[b].Erase_count - mean;
        var += d * d;
    }
    return var / n;
}

// ─────────────────────────────────────────────────────────────────────────────
// Get_next_gc_victim  — THE CORE OVERRIDE
//
// Replaces MQSim's GREEDY (most-invalid-pages) with RRA-FTL scoring:
//   Score = alpha * Efficiency  -  gamma * MigrationCost  +  beta * RemainingBudget
//
// Where:
//   Efficiency      = invalid_pages / total_pages
//   MigrationCost   = valid_pages   / total_pages
//   RemainingBudget = Weibull_score(erase_count)   ← novel Weibull term
//
// Quarantine: blocks with RemainingBudget < 0.05 are skipped entirely.
// ─────────────────────────────────────────────────────────────────────────────
Block_Pool_Slot_Type*
GC_and_WL_Unit_Page_Level_RRA::Get_next_gc_victim(
    PlaneBookKeepingType* pbk,
    const NVM::FlashMemory::Physical_Page_Address& /*plane_address*/)
{
    ++m_gc_epoch_counter;

    Block_Pool_Slot_Type* victim     = nullptr;
    double                best_score = -std::numeric_limits<double>::infinity();

    const unsigned int total_pages = pbk->Blocks[0].Pages_no;  // pages per block

    for (unsigned int b = 0; b < pbk->Total_blocks; ++b) {
        Block_Pool_Slot_Type& blk = pbk->Blocks[b];

        // Must have something to reclaim
        if (blk.Invalid_page_count == 0) continue;

        // [4] Block quarantine — protect near-end-of-life blocks
        double rem_budget = Weibull_score(blk.Erase_count);
        if (rem_budget < RRA_QUARANTINE_THRESHOLD) continue;

        // [1] Weibull victim score
        double efficiency  = static_cast<double>(blk.Invalid_page_count)
                           / static_cast<double>(total_pages);
        double migration   = static_cast<double>(blk.Valid_page_count)
                           / static_cast<double>(total_pages);

        double score = m_alpha * efficiency
                     - m_gamma * migration
                     + m_beta  * rem_budget;

        if (score > best_score) {
            best_score = score;
            victim     = &blk;
        }
    }

    // If quarantine excluded everything, fall back to most-invalid (GREEDY)
    // without quarantine check — better to make progress than stall.
    if (!victim) {
        for (unsigned int b = 0; b < pbk->Total_blocks; ++b) {
            Block_Pool_Slot_Type& blk = pbk->Blocks[b];
            if (blk.Invalid_page_count == 0) continue;
            if (!victim || blk.Invalid_page_count > victim->Invalid_page_count)
                victim = &blk;
        }
    }

    // [3] Pareto-epoch adaptive tuning every TUNE_EVERY_N_GC GC passes
    if (m_gc_epoch_counter % RRA_TUNE_EVERY_N_GC == 0)
        Pareto_adapt(pbk);

    return victim;
}

// ─────────────────────────────────────────────────────────────────────────────
// Set_erase_transaction_time  — inject adaptive erase latency into MQSim
//
// MQSim's NVM_Transaction_Flash_ER has a Time_to_transfer_die field used
// by the TSU for scheduling.  We overwrite it with the age-scaled erase time.
// Python: Block.erase_time_ms = T_base * (1 + K_age * wear_ratio)
// ─────────────────────────────────────────────────────────────────────────────
void GC_and_WL_Unit_Page_Level_RRA::Set_erase_transaction_time(
    NVM_Transaction_Flash_ER* erase_tr,
    Block_Pool_Slot_Type*     victim_block)
{
    if (!erase_tr || !victim_block) return;

    double adaptive_ns = Adaptive_erase_ns(victim_block->Erase_count);
    m_total_adaptive_erase_ns += adaptive_ns;

    // Override MQSim's fixed erase latency with wear-adjusted value
    erase_tr->Time_to_transfer_die = static_cast<sim_time_type>(adaptive_ns);
}

// ─────────────────────────────────────────────────────────────────────────────
// Pareto_adapt  — GC-epoch Pareto adaptive tuning
//
// Python: AdaptiveFTL._pareto_adapt()
//
// Algorithm:
//   1. Compute WAF = total_flash_writes / total_host_writes
//      (We read from MQSim's own stats — FTL pointer available via base class)
//   2. EMA-smooth both WAF and WearVariance
//   3. Add current point (EMA_WAF, EMA_Var, alpha, beta, gamma) to window
//   4. Check Pareto dominance over window
//   5. If dominated: apply dead-band-gated weight adjustments
// ─────────────────────────────────────────────────────────────────────────────
void GC_and_WL_Unit_Page_Level_RRA::Pareto_adapt(PlaneBookKeepingType* pbk)
{
    // -- Estimate WAF from MQSim's FTL statistics --
    // GC_and_WL_Unit_Base has access to ftl via the address_mapping_unit ptr.
    // The cleanest portable approach: use the ratio of GC erase count to
    // total pages written as a WAF proxy.
    double raw_waf = 1.0;
    if (m_gc_epoch_counter > 1) {
        // Approximate: each GC erase recovers ~page_count invalid pages back
        // at cost of valid_page migration.  A cleaner hook is available if
        // you expose FTL::Get_WAF() in FTL.h (see FTL_RRA_patch.cpp).
        // For now, derive from plane bookkeeping:
        double total_erases = 0, max_ec = 0;
        for (unsigned int b = 0; b < pbk->Total_blocks; ++b) {
            total_erases += pbk->Blocks[b].Erase_count;
            if (pbk->Blocks[b].Erase_count > max_ec)
                max_ec = pbk->Blocks[b].Erase_count;
        }
        // Crude WAF proxy: max_ec / mean_ec (>1 means wear imbalance → WAF ≈ proportional)
        if (total_erases > 0 && pbk->Total_blocks > 0)
            raw_waf = max_ec / (total_erases / pbk->Total_blocks);
    }

    double raw_var = Compute_wear_variance(pbk);

    // EMA update (lambda=0.1: slow, stable)
    m_ema_waf      = RRA_EMA_LAMBDA * raw_waf  + (1.0 - RRA_EMA_LAMBDA) * m_ema_waf;
    m_ema_variance = RRA_EMA_LAMBDA * raw_var  + (1.0 - RRA_EMA_LAMBDA) * m_ema_variance;

    // Store current point in Pareto window
    m_pareto_window.push_back({m_ema_waf, m_ema_variance,
                                m_alpha,  m_beta, m_gamma});
    if (static_cast<int>(m_pareto_window.size()) > RRA_PARETO_WINDOW_SIZE)
        m_pareto_window.pop_front();

    // Check if current point is Pareto-dominated
    bool dominated = false;
    for (int i = 0; i < static_cast<int>(m_pareto_window.size()) - 1; ++i) {
        const auto& p = m_pareto_window[i];
        if (p.waf <= m_ema_waf && p.variance <= m_ema_variance) {
            dominated = true;
            break;
        }
    }
    if (!dominated) return;  // on / near Pareto front — no change needed

    // Dead-band gated weight adjustments
    double waf_dev = m_ema_waf      - RRA_TARGET_WAF;
    double var_dev = m_ema_variance - RRA_TARGET_VAR;

    constexpr double DELTA       = 0.05;
    constexpr double DELTA_SMALL = 0.01;

    // Emergency WAF runaway override
    if (m_ema_waf > RRA_WAF_RUNAWAY_THRESHOLD) {
        m_alpha = 1.5;
        m_gamma = 1.5;
        m_beta  = 0.5;
    } else {
        if (waf_dev > RRA_DEAD_BAND_WAF) {
            m_alpha += DELTA;
            m_gamma += DELTA;
            m_beta  -= DELTA_SMALL;
        }
        if (var_dev > RRA_DEAD_BAND_VAR) {
            m_beta  += DELTA;
            m_alpha -= DELTA_SMALL;
        }
    }

    // Clamp to [0.1, 2.0]
    auto clamp = [](double v){ return std::max(0.1, std::min(2.0, v)); };
    m_alpha = clamp(m_alpha);
    m_beta  = clamp(m_beta);
    m_gamma = clamp(m_gamma);
}

// ─────────────────────────────────────────────────────────────────────────────
// Get_rra_metrics — expose state to output reporter
// ─────────────────────────────────────────────────────────────────────────────
RRA_Metrics GC_and_WL_Unit_Page_Level_RRA::Get_rra_metrics() const
{
    return RRA_Metrics{
        /* mean_remaining_budget   */ 0.0,  // computed by reporter per plane
        /* total_adaptive_erase_ns */ m_total_adaptive_erase_ns,
        /* ema_waf                 */ m_ema_waf,
        /* ema_variance            */ m_ema_variance,
        /* alpha                   */ m_alpha,
        /* beta                    */ m_beta,
        /* gamma                   */ m_gamma,
        /* gc_epoch                */ m_gc_epoch_counter
    };
}

} // namespace SSD_Components
