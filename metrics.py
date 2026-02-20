class Metrics:
    def __init__(self, ftl_instance, name, max_erase_limit=10000):
        self.ftl = ftl_instance
        self.name = name
        self.max_erase_limit = max_erase_limit

    def get_summary(self):
        waf = self.ftl.get_waf()
        variance = self.ftl.get_wear_variance()
        gc_count = self.ftl.gc_count
        
        erase_counts = self.ftl.nand.get_erase_counts()
        max_erase = max(erase_counts) if erase_counts else 1
        min_erase = min(erase_counts) if erase_counts else 0
        
        # Elite Upgrade: Lifetime Projection
        # Assume max observed rate across the host writes denotes the speed the drive dies
        # Lifetime is proportional to how many writes it takes for the max erase count to hit the limit
        if max_erase > 0:
            projected_lifetime_writes = (self.max_erase_limit / max_erase) * self.ftl.host_writes
        else:
            projected_lifetime_writes = float('inf')
        
        return {
            "Strategy": self.name,
            "Host Writes": self.ftl.host_writes,
            "Total NAND Writes": self.ftl.total_writes,
            "Write Amplifi. Factor (WAF)": round(waf, 3),
            "Garbage Collection Count": gc_count,
            "Wear Variance": round(variance, 3),
            "Max Erase Count": max_erase,
            "Min Erase Count": min_erase,
            "Proj. Lifetime (Host Writes)": int(projected_lifetime_writes) if projected_lifetime_writes != float('inf') else "Unlimited"
        }

    def print_summary(self):
        summary = self.get_summary()
        print(f"--- Metrics for {self.name} ---")
        for k, v in summary.items():
            if k == "Proj. Lifetime (Host Writes)" and isinstance(v, int):
                # Format with commas for readability of massive numbers
                print(f"{k}: {v:,}")
            else:
                print(f"{k}: {v}")
                
        # Also print final adapter weights if it's the adaptive FTL
        if hasattr(self.ftl, 'alpha'):
             print(f"Final Tuned Alpha (Efficiency): {self.ftl.alpha:.2f}")
             print(f"Final Tuned Beta (Wear Leveling): {self.ftl.beta:.2f}")
             
        print("-" * 30)

