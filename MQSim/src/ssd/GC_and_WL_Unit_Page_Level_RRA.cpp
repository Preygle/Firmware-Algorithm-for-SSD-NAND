/*
 * GC_and_WL_Unit_Page_Level_RRA.cpp
 * ===================================
 * RRA-FTL v2: Reliability-Remaining Adaptive GC & Wear-Leveling Unit
 *
 * v2 improvements over v1:
 *   [NEW-1] Hot/Cold tracking — per-block write counter, hot blocks get +δ GC priority
 *   [NEW-2] Migration-cost penalty (β term) — avoids choosing blocks with many valid pages
 *   [NEW-3] Adaptive GC threshold — rises under write pressure and as drive ages
 *   [NEW-4] Wear-leveling write frontier — lowest-erase block picked for new writes
 *   v1 features retained: Weibull scoring, block quarantine, Pareto adaptive tuning,
 *                         adaptive erase latency
 */

#include "GC_and_WL_Unit_Page_Level_RRA.h"
#include "../sim/Sim_Defs.h"
#include "NVM_Transaction_Flash_ER.h"
#include "NVM_Transaction_Flash_RD.h"
#include "NVM_Transaction_Flash_WR.h"
#include "Flash_Block_Manager_Base.h"
#include "Stats.h"
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
    double  initial_gamma,
    double  initial_delta)
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
    , m_delta(initial_delta)
    , m_ema_waf(1.0)
    , m_ema_variance(0.0)
    , m_gc_epoch_counter(0)
    , m_total_adaptive_erase_ns(0.0)
    // Adaptive threshold [NEW]
    , m_base_gc_threshold(gc_threshold)
    , m_adaptive_gc_threshold(gc_threshold)
    , m_recent_write_count(0)
    , m_threshold_update_interval(1000)   // recalculate every 1000 writes
{
    Build_weibull_lut();
}

// ─────────────────────────────────────────────────────────────────────────────
// Build_weibull_lut: pre-computes 157 Q10 entries so the hot scoring path
// never does floating-point exponentiation.
// ─────────────────────────────────────────────────────────────────────────────
void GC_and_WL_Unit_Page_Level_RRA::Build_weibull_lut()
{
    for (int i = 0; i < RRA_LUT_SIZE; ++i) {
        double ec  = static_cast<double>(i * RRA_LUT_BUCKET);
        double x   = ec / m_pe_endurance;
        double val = std::exp(-(x * x));               // Weibull k=2
        int q10    = static_cast<int>(val * 1024.0 + 0.5);
        if (q10 < 0)    q10 = 0;
        if (q10 > 1024) q10 = 1024;
        m_weibull_lut[i] = static_cast<uint16_t>(q10);
    }
}

// ─────────────────────────────────────────────────────────────────────────────
// Weibull_score — O(1) LUT lookup, returns [0,1]
// ─────────────────────────────────────────────────────────────────────────────
double GC_and_WL_Unit_Page_Level_RRA::Weibull_score(unsigned int erase_count) const
{
    unsigned int idx = erase_count / static_cast<unsigned int>(RRA_LUT_BUCKET);
    if (idx >= static_cast<unsigned int>(RRA_LUT_SIZE))
        return 0.0;
    return m_weibull_lut[idx] / 1024.0;
}

// ─────────────────────────────────────────────────────────────────────────────
// Adaptive_erase_ns — erase latency scales linearly with wear
// ─────────────────────────────────────────────────────────────────────────────
double GC_and_WL_Unit_Page_Level_RRA::Adaptive_erase_ns(unsigned int erase_count) const
{
    double wear_ratio = static_cast<double>(erase_count) / m_pe_endurance;
    return RRA_T_BASE_NS * (1.0 + RRA_K_AGE * wear_ratio);
}

// ─────────────────────────────────────────────────────────────────────────────
// Compute_wear_variance — population variance of per-block erase counts
// ─────────────────────────────────────────────────────────────────────────────
double GC_and_WL_Unit_Page_Level_RRA::Compute_wear_variance(
    PlaneBookKeepingType* pbk) const
{
    if (!pbk || block_no_per_plane == 0) return 0.0;

    double sum = 0.0;
    for (unsigned int b = 0; b < block_no_per_plane; ++b)
        sum += pbk->Blocks[b].Erase_count;
    double mean = sum / block_no_per_plane;

    double var = 0.0;
    for (unsigned int b = 0; b < block_no_per_plane; ++b) {
        double d = pbk->Blocks[b].Erase_count - mean;
        var += d * d;
    }
    return var / block_no_per_plane;
}

// ─────────────────────────────────────────────────────────────────────────────
// [NEW] Record_page_write — call this from FTL write path to track hot blocks
// Marks the block as Hot_block when it crosses the threshold.
// ─────────────────────────────────────────────────────────────────────────────
void GC_and_WL_Unit_Page_Level_RRA::Record_page_write(flash_block_ID_type block_id)
{
    unsigned int& cnt = m_block_write_counts[block_id];
    ++cnt;
    ++m_recent_write_count;
}

// ─────────────────────────────────────────────────────────────────────────────
// [NEW] Update_adaptive_threshold
//
//   threshold = base * (1 + pressure_K * write_pressure)
//                    * (1 + age_K     * avg_wear_ratio)
//
// write_pressure = recent writes per block relative to page count
// avg_wear_ratio = mean erase_count / PE_endurance across all blocks
// ─────────────────────────────────────────────────────────────────────────────
void GC_and_WL_Unit_Page_Level_RRA::Update_adaptive_threshold(
    PlaneBookKeepingType* pbk)
{
    if (!pbk || block_no_per_plane == 0) return;

    // Write pressure: ratio of recent writes to a "neutral" level
    double neutral_writes    = static_cast<double>(pages_no_per_block * block_no_per_plane);
    double write_pressure    = static_cast<double>(m_recent_write_count) / neutral_writes;
    m_recent_write_count     = 0;

    // Average wear ratio
    double sum_ec = 0.0;
    for (unsigned int b = 0; b < block_no_per_plane; ++b)
        sum_ec += pbk->Blocks[b].Erase_count;
    double avg_wear_ratio = (sum_ec / block_no_per_plane) / m_pe_endurance;

    m_adaptive_gc_threshold = m_base_gc_threshold
        * (1.0 + RRA_ADAPTIVE_PRESSURE_K * write_pressure)
        * (1.0 + RRA_ADAPTIVE_AGE_K      * avg_wear_ratio);

    // Clamp so we don't over-aggressively GC or under-GC
    double max_threshold = m_base_gc_threshold * 4.0;
    if (m_adaptive_gc_threshold > max_threshold)
        m_adaptive_gc_threshold = max_threshold;
    if (m_adaptive_gc_threshold < m_base_gc_threshold)
        m_adaptive_gc_threshold = m_base_gc_threshold;
}

// ─────────────────────────────────────────────────────────────────────────────
// [NEW] Get_wl_write_frontier
// Returns the block ID with the LOWEST erase count among blocks in the free pool.
// Called instead of arbitrary free block selection to reduce wear variance.
// ─────────────────────────────────────────────────────────────────────────────
flash_block_ID_type GC_and_WL_Unit_Page_Level_RRA::Get_wl_write_frontier(
    PlaneBookKeepingType* pbk) const
{
    flash_block_ID_type best_id  = 0;
    unsigned int        min_ec   = UINT32_MAX;
    bool                found    = false;

    for (unsigned int b = 0; b < block_no_per_plane; ++b) {
        Block_Pool_Slot_Type& blk = pbk->Blocks[b];
        // A free block: no valid pages, no ongoing erases, Current_page_write_index == 0
        if (blk.Current_page_write_index == 0 && blk.Invalid_page_count == 0) {
            if (pbk->Ongoing_erase_operations.find(b) != pbk->Ongoing_erase_operations.end())
                continue;
            if (blk.Erase_count < min_ec) {
                min_ec   = blk.Erase_count;
                best_id  = b;
                found    = true;
            }
        }
    }
    // Fallback: just return 0 (caller will handle errors as before)
    return found ? best_id : 0;
}

// ─────────────────────────────────────────────────────────────────────────────
// Get_next_gc_victim  — CORE UPGRADE (v2)
//
//   Full composite score:
//     Score(b) = α * Efficiency(b)       [invalid_pages / total_pages]
//              - β * MigrationCost(b)    [valid_pages   / total_pages]  [NEW β term]
//              + γ * RemainingBudget(b)  [Weibull health score]
//              + δ * HotBonus(b)         [+1 if hot block, else 0]       [NEW δ term]
//
//   Quarantine: blocks with RemainingBudget < 0.05 are skipped.
//   Fallback:   if quarantine excludes everything → plain GREEDY.
// ─────────────────────────────────────────────────────────────────────────────
Block_Pool_Slot_Type*
GC_and_WL_Unit_Page_Level_RRA::Get_next_gc_victim(
    PlaneBookKeepingType* pbk,
    const NVM::FlashMemory::Physical_Page_Address& /*plane_address*/)
{
    ++m_gc_epoch_counter;

    Block_Pool_Slot_Type* victim     = nullptr;
    double                best_score = -std::numeric_limits<double>::infinity();

    const double total_pages_d = static_cast<double>(pages_no_per_block);

    // Update hot_block flags from write counts
    for (auto& kv : m_block_write_counts) {
        if (kv.first < block_no_per_plane)
            pbk->Blocks[kv.first].Hot_block = (kv.second >= RRA_HOT_WRITE_THRESHOLD);
    }

    for (unsigned int b = 0; b < block_no_per_plane; ++b) {
        Block_Pool_Slot_Type& blk = pbk->Blocks[b];

        // Must have something to reclaim and must be fully written
        if (blk.Invalid_page_count == 0) continue;
        if (blk.Current_page_write_index < pages_no_per_block) continue;

        // Skip blocks currently being erased
        if (pbk->Ongoing_erase_operations.find(b) != pbk->Ongoing_erase_operations.end())
            continue;

        // [8] Quarantine — protect near-end-of-life blocks
        double rem_budget = Weibull_score(blk.Erase_count);
        if (rem_budget < RRA_QUARANTINE_THRESHOLD) continue;

        // Composite score:
        double efficiency      = static_cast<double>(blk.Invalid_page_count)  / total_pages_d;
        double migration_cost  = static_cast<double>(pages_no_per_block - blk.Invalid_page_count) / total_pages_d;  // [NEW β]
        double hot_bonus       = blk.Hot_block ? 1.0 : 0.0;  // [NEW δ]

        double score = m_alpha * efficiency
                     - m_beta  * migration_cost   // [NEW: was absent in v1]
                     + m_gamma * rem_budget
                     + m_delta * hot_bonus;        // [NEW]

        if (score > best_score) {
            best_score = score;
            victim     = &blk;
        }
    }

    // Quarantine fallback: GREEDY without quarantine restriction
    if (!victim) {
        for (unsigned int b = 0; b < block_no_per_plane; ++b) {
            Block_Pool_Slot_Type& blk = pbk->Blocks[b];
            if (blk.Invalid_page_count == 0) continue;
            if (pbk->Ongoing_erase_operations.find(b) != pbk->Ongoing_erase_operations.end())
                continue;
            if (!victim || blk.Invalid_page_count > victim->Invalid_page_count)
                victim = &blk;
        }
    }

    // Pareto-epoch adaptive tuning
    if (m_gc_epoch_counter % RRA_TUNE_EVERY_N_GC == 0)
        Pareto_adapt(pbk);

    // Reset hot/cold counters every GC epoch to track recent activity only
    if (m_gc_epoch_counter % (RRA_TUNE_EVERY_N_GC * 4) == 0)
        m_block_write_counts.clear();

    return victim;
}

// ─────────────────────────────────────────────────────────────────────────────
// Set_erase_transaction_time — inject per-block adaptive erase latency
// ─────────────────────────────────────────────────────────────────────────────
void GC_and_WL_Unit_Page_Level_RRA::Set_erase_transaction_time(
    NVM_Transaction_Flash_ER* erase_tr,
    Block_Pool_Slot_Type*     victim_block)
{
    if (!erase_tr || !victim_block) return;
    double adaptive_ns = Adaptive_erase_ns(victim_block->Erase_count);
    m_total_adaptive_erase_ns += adaptive_ns;
    // Note: Time_to_transfer_die override requires TSU internals; tracked in metrics only.
}

// ─────────────────────────────────────────────────────────────────────────────
// Pareto_adapt — GC-epoch weight tuning using EMA + Pareto dominance
// ─────────────────────────────────────────────────────────────────────────────
void GC_and_WL_Unit_Page_Level_RRA::Pareto_adapt(PlaneBookKeepingType* pbk)
{
    double raw_waf = 1.0;
    if (m_gc_epoch_counter > 1) {
        double total_erases = 0, max_ec = 0;
        for (unsigned int b = 0; b < block_no_per_plane; ++b) {
            total_erases += pbk->Blocks[b].Erase_count;
            if (pbk->Blocks[b].Erase_count > max_ec)
                max_ec = pbk->Blocks[b].Erase_count;
        }
        if (total_erases > 0 && block_no_per_plane > 0)
            raw_waf = max_ec / (total_erases / static_cast<double>(block_no_per_plane));
    }

    double raw_var = Compute_wear_variance(pbk);

    m_ema_waf      = RRA_EMA_LAMBDA * raw_waf + (1.0 - RRA_EMA_LAMBDA) * m_ema_waf;
    m_ema_variance = RRA_EMA_LAMBDA * raw_var + (1.0 - RRA_EMA_LAMBDA) * m_ema_variance;

    m_pareto_window.push_back({m_ema_waf, m_ema_variance, m_alpha, m_beta, m_gamma});
    if (static_cast<int>(m_pareto_window.size()) > RRA_PARETO_WINDOW_SIZE)
        m_pareto_window.pop_front();

    bool dominated = false;
    for (int i = 0; i < static_cast<int>(m_pareto_window.size()) - 1; ++i) {
        const auto& p = m_pareto_window[i];
        if (p.waf <= m_ema_waf && p.variance <= m_ema_variance) {
            dominated = true;
            break;
        }
    }
    if (!dominated) return;

    constexpr double DELTA       = 0.05;
    constexpr double DELTA_SMALL = 0.01;

    if (m_ema_waf > RRA_WAF_RUNAWAY_THRESHOLD) {
        // Emergency: maximize efficiency weight, minimize migration cost
        m_alpha = 1.5;
        m_beta  = 1.5;
        m_gamma = 0.5;
    } else {
        double waf_dev = m_ema_waf      - RRA_TARGET_WAF;
        double var_dev = m_ema_variance - RRA_TARGET_VAR;

        if (waf_dev > RRA_DEAD_BAND_WAF) {
            m_alpha += DELTA;
            m_beta  += DELTA;       // also increase migration cost penalty
            m_gamma -= DELTA_SMALL;
        }
        if (var_dev > RRA_DEAD_BAND_VAR) {
            m_gamma += DELTA;       // favor healthier blocks
            m_alpha -= DELTA_SMALL;
        }
    }

    auto clamp = [](double v){ return std::max(0.1, std::min(2.0, v)); };
    m_alpha = clamp(m_alpha);
    m_beta  = clamp(m_beta);
    m_gamma = clamp(m_gamma);
    m_delta = clamp(m_delta);
}

// ─────────────────────────────────────────────────────────────────────────────
// Check_gc_required — main GC entry point with ADAPTIVE THRESHOLD [NEW]
// ─────────────────────────────────────────────────────────────────────────────
void GC_and_WL_Unit_Page_Level_RRA::Check_gc_required(
    const unsigned int free_block_pool_size,
    const NVM::FlashMemory::Physical_Page_Address& plane_address)
{
    PlaneBookKeepingType* pbke = block_manager->Get_plane_bookkeeping_entry(plane_address);

    // [NEW] Adaptively update threshold periodically
    if (m_recent_write_count >= m_threshold_update_interval)
        Update_adaptive_threshold(pbke);

    // Compute adaptive threshold as an absolute free-block count
    // block_pool_gc_threshold is the base count from the parent class
    unsigned int adaptive_threshold_blocks = static_cast<unsigned int>(
        m_adaptive_gc_threshold * static_cast<double>(block_no_per_plane));
    if (adaptive_threshold_blocks < block_pool_gc_threshold)
        adaptive_threshold_blocks = block_pool_gc_threshold;

    if (free_block_pool_size >= adaptive_threshold_blocks)
        return;  // enough free space — no GC needed

    if (pbke->Ongoing_erase_operations.size() >= max_ongoing_gc_reqs_per_plane)
        return;

    Block_Pool_Slot_Type* victim = Get_next_gc_victim(pbke, plane_address);
    if (!victim) return;

    flash_block_ID_type gc_candidate_block_id = victim->BlockID;

    if (pbke->Ongoing_erase_operations.find(gc_candidate_block_id) !=
        pbke->Ongoing_erase_operations.end())
        return;

    NVM::FlashMemory::Physical_Page_Address gc_candidate_address(plane_address);
    gc_candidate_address.BlockID = gc_candidate_block_id;
    Block_Pool_Slot_Type* block  = &pbke->Blocks[gc_candidate_block_id];

    if (block->Current_page_write_index == 0 || block->Invalid_page_count == 0)
        return;

    block_manager->GC_WL_started(gc_candidate_address);
    pbke->Ongoing_erase_operations.insert(gc_candidate_block_id);
    address_mapping_unit->Set_barrier_for_accessing_physical_block(gc_candidate_address);

    if (block_manager->Can_execute_gc_wl(gc_candidate_address)) {
        Stats::Total_gc_executions++;
        tsu->Prepare_for_transaction_submit();

        NVM_Transaction_Flash_ER* gc_erase_tr = new NVM_Transaction_Flash_ER(
            Transaction_Source_Type::GC_WL,
            pbke->Blocks[gc_candidate_block_id].Stream_id,
            gc_candidate_address);

        Set_erase_transaction_time(gc_erase_tr, block);

        if (block->Current_page_write_index - block->Invalid_page_count > 0) {
            NVM_Transaction_Flash_RD* gc_read  = NULL;
            NVM_Transaction_Flash_WR* gc_write = NULL;
            for (flash_page_ID_type pageID = 0; pageID < block->Current_page_write_index; pageID++) {
                if (block_manager->Is_page_valid(block, pageID)) {
                    Stats::Total_page_movements_for_gc++;
                    gc_candidate_address.PageID = pageID;
                    if (use_copyback) {
                        gc_write = new NVM_Transaction_Flash_WR(
                            Transaction_Source_Type::GC_WL, block->Stream_id,
                            sector_no_per_page * SECTOR_SIZE_IN_BYTE,
                            NO_LPA, address_mapping_unit->Convert_address_to_ppa(gc_candidate_address),
                            NULL, 0, NULL, 0, INVALID_TIME_STAMP);
                        gc_write->ExecutionMode = WriteExecutionModeType::COPYBACK;
                        tsu->Submit_transaction(gc_write);
                    } else {
                        gc_read = new NVM_Transaction_Flash_RD(
                            Transaction_Source_Type::GC_WL, block->Stream_id,
                            sector_no_per_page * SECTOR_SIZE_IN_BYTE,
                            NO_LPA, address_mapping_unit->Convert_address_to_ppa(gc_candidate_address),
                            gc_candidate_address, NULL, 0, NULL, 0, INVALID_TIME_STAMP);
                        gc_write = new NVM_Transaction_Flash_WR(
                            Transaction_Source_Type::GC_WL, block->Stream_id,
                            sector_no_per_page * SECTOR_SIZE_IN_BYTE,
                            NO_LPA, NO_PPA, gc_candidate_address,
                            NULL, 0, gc_read, 0, INVALID_TIME_STAMP);
                        gc_write->ExecutionMode  = WriteExecutionModeType::SIMPLE;
                        gc_write->RelatedErase   = gc_erase_tr;
                        gc_read->RelatedWrite    = gc_write;
                        tsu->Submit_transaction(gc_read);
                    }
                    gc_erase_tr->Page_movement_activities.push_back(gc_write);
                }
            }
        }
        block->Erase_transaction = gc_erase_tr;
        tsu->Submit_transaction(gc_erase_tr);
        tsu->Schedule();
    }
}

// ─────────────────────────────────────────────────────────────────────────────
// Get_rra_metrics
// ─────────────────────────────────────────────────────────────────────────────
RRA_Metrics GC_and_WL_Unit_Page_Level_RRA::Get_rra_metrics() const
{
    return RRA_Metrics(
        0.0,                          // mean_remaining_budget (computed per-plane)
        m_total_adaptive_erase_ns,
        m_ema_waf,
        m_ema_variance,
        m_alpha,
        m_beta,
        m_gamma,
        m_delta,
        m_adaptive_gc_threshold,
        m_gc_epoch_counter
    );
}

} // namespace SSD_Components
