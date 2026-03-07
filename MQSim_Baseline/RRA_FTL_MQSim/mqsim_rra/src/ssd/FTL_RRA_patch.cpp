/*
 * FTL_RRA_patch.cpp
 * ==================
 * This file is NOT a standalone source file.
 * It shows the EXACT changes to make inside MQSim's src/ssd/FTL.cpp
 * to activate RRA-FTL.  Everything else in FTL.cpp stays unchanged.
 *
 * STEP 1 — Add include at top of FTL.cpp
 * ========================================
 * Find the existing includes block (around line 1-10) and add:
 *
 *     #include "GC_and_WL_Unit_Page_Level_RRA.h"     // ← ADD THIS LINE
 *
 *
 * STEP 2 — Replace GC unit instantiation
 * ========================================
 * Search FTL.cpp for the block that creates GC_and_WL_Unit_Page_Level.
 * It looks like this (the exact constructor args may vary slightly
 * across MQSim versions, but the pattern is always the same):
 *
 *   BEFORE (vanilla MQSim):
 *   ─────────────────────────────────────────────────────────────────
 *   GC_and_WL_Unit = new GC_and_WL_Unit_Page_Level(
 *       id + ".GC_WL",
 *       Address_Mapping_Unit,
 *       block_manager,
 *       tsu,
 *       flash_controller,
 *       gc_and_wl_unit_params->GC_Block_Selection_Policy,
 *       gc_and_wl_unit_params->GC_Exect_Threshold,
 *       gc_and_wl_unit_params->Preemptible_GC_Enabled,
 *       gc_and_wl_unit_params->GC_Hard_Threshold,
 *       channel_count, chip_no_per_channel, die_no_per_chip,
 *       plane_no_per_die, block_no_per_plane, page_no_per_block,
 *       sector_no_per_page,
 *       gc_and_wl_unit_params->Use_Copyback_for_GC,
 *       gc_and_wl_unit_params->Static_Wearleveling_Threshold
 *   );
 *   ─────────────────────────────────────────────────────────────────
 *
 *   AFTER (RRA-FTL):
 *   ─────────────────────────────────────────────────────────────────
 *   GC_and_WL_Unit = new SSD_Components::GC_and_WL_Unit_Page_Level_RRA(
 *       id + ".GC_WL",
 *       Address_Mapping_Unit,
 *       block_manager,
 *       tsu,
 *       flash_controller,
 *       gc_and_wl_unit_params->GC_Block_Selection_Policy,
 *       gc_and_wl_unit_params->GC_Exect_Threshold,
 *       gc_and_wl_unit_params->Preemptible_GC_Enabled,
 *       gc_and_wl_unit_params->GC_Hard_Threshold,
 *       channel_count, chip_no_per_channel, die_no_per_chip,
 *       plane_no_per_die, block_no_per_plane, page_no_per_block,
 *       sector_no_per_page,
 *       gc_and_wl_unit_params->Use_Copyback_for_GC,
 *       gc_and_wl_unit_params->Static_Wearleveling_Threshold,
 *       // RRA-FTL extra params (with safe defaults):
 *       10000.0,   // PE endurance (matches ssdconfig.xml Max_PE_Cycles)
 *       1.0,       // initial alpha (efficiency weight)
 *       1.0,       // initial beta  (Weibull wear weight)
 *       1.0        // initial gamma (migration cost weight)
 *   );
 *   ─────────────────────────────────────────────────────────────────
 *
 * THAT IS THE COMPLETE CHANGE TO FTL.cpp — 1 include + 1 constructor swap.
 *
 *
 * STEP 3 — Optional: expose WAF for more accurate Pareto_adapt()
 * ===============================================================
 * For the cleanest WAF signal in Pareto_adapt(), expose this getter
 * in FTL.h (add to the public section):
 *
 *     double Get_WAF() const {
 *         return (host_write_count > 0)
 *             ? static_cast<double>(total_flash_write_count) / host_write_count
 *             : 1.0;
 *     }
 *
 * And update GC_and_WL_Unit_Page_Level_RRA.cpp's Pareto_adapt() to call:
 *     double raw_waf = ftl->Get_WAF();
 *
 * This is optional — the current implementation derives a WAF proxy from
 * plane bookkeeping stats, which is sufficient for the Pareto trigger logic.
 *
 *
 * STEP 4 — Rebuild
 * =================
 * Linux:   make -j$(nproc)
 * Windows: rebuild MQSim.vcxproj in Visual Studio (Release config)
 *
 *
 * STEP 5 — Run with provided configs
 * ====================================
 * Linux:
 *   ./MQSim -i ssdconfig_rra.xml -w workloads/workload_sequential.xml
 *   ./MQSim -i ssdconfig_rra.xml -w workloads/workload_random.xml
 *   ./MQSim -i ssdconfig_rra.xml -w workloads/workload_hotspot.xml
 *
 * Windows:
 *   MQSim.exe -i ssdconfig_rra.xml -w workloads\workload_hotspot.xml
 *
 * Output XML files appear in the same directory as the workload XML.
 * Open in Excel or parse with parse_mqsim_output.py.
 */

// ── Minimal FTL.cpp diff (unified diff format) ───────────────────────────────
/*
--- a/src/ssd/FTL.cpp
+++ b/src/ssd/FTL.cpp
@@ -1,6 +1,7 @@
 #include "FTL.h"
 #include "GC_and_WL_Unit_Page_Level.h"
+#include "GC_and_WL_Unit_Page_Level_RRA.h"   // RRA-FTL
 #include "Address_Mapping_Unit_Page_Level.h"
 ...

@@ -NNN,7 +NNN,12 @@
-    GC_and_WL_Unit = new GC_and_WL_Unit_Page_Level(
+    GC_and_WL_Unit = new SSD_Components::GC_and_WL_Unit_Page_Level_RRA(
         id + ".GC_WL", Address_Mapping_Unit, block_manager,
         tsu, flash_controller,
         gc_and_wl_unit_params->GC_Block_Selection_Policy,
         gc_and_wl_unit_params->GC_Exect_Threshold,
         gc_and_wl_unit_params->Preemptible_GC_Enabled,
         gc_and_wl_unit_params->GC_Hard_Threshold,
         channel_count, chip_no_per_channel, die_no_per_chip,
         plane_no_per_die, block_no_per_plane, page_no_per_block,
         sector_no_per_page,
         gc_and_wl_unit_params->Use_Copyback_for_GC,
-        gc_and_wl_unit_params->Static_Wearleveling_Threshold
+        gc_and_wl_unit_params->Static_Wearleveling_Threshold,
+        10000.0, 1.0, 1.0, 1.0    // pe_endurance, alpha, beta, gamma
     );
*/
