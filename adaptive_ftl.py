from ftl import BaseFTL
from nand import PageState

class AdaptiveFTL(BaseFTL):
    def __init__(self, nand_flash):
        super().__init__(nand_flash)
        
        # dynamic hot/cold separation
        self.lba_access_count = {}
        
        # dynamic adaptive weights
        self.alpha = 1.0  # Efficiency weight
        self.beta = 1.0   # Wear Leveling weight
        self.gamma = 1.0  # Migration penalty weight
        
        # moving averages for adaptability
        self.moving_waf = 1.0
        self.moving_variance = 0.0
        
        # Targets for runtime tuning
        self.target_waf = 4.0
        self.target_variance = 20.0

    def write(self, logical_address: int):
        self.lba_access_count[logical_address] = self.lba_access_count.get(logical_address, 0) + 1
        super().write(logical_address)
        
        # Periodically adapt weights
        if self.host_writes % 1000 == 0:
            self._adapt_weights()

    def _adapt_weights(self):
        """
        Dynamically adjusts Alpha, Beta, and Gamma based on current system stress.
        """
        current_waf = self.get_waf()
        current_variance = self.get_wear_variance()
        
        self.moving_waf = (0.9 * self.moving_waf) + (0.1 * current_waf)
        self.moving_variance = (0.9 * self.moving_variance) + (0.1 * current_variance)
        
        delta = 0.05
        delta_small = 0.01
        
        # Optional WAF Stabilization Rule to prevent runaway amplification
        if self.moving_waf > 6.0:
            self.alpha = 1.5
            self.gamma = 1.5
            self.beta = 0.5
            return
            
        # Standard Tuning
        if self.moving_waf > self.target_waf:
            self.alpha += delta
            self.gamma += delta
            self.beta -= delta_small
            
        if self.moving_variance > self.target_variance:
            self.beta += delta
            self.alpha -= delta_small
            
        # Clamp weights to valid range
        self.alpha = max(0.1, min(self.alpha, 2.0))
        self.beta = max(0.1, min(self.beta, 2.0))
        self.gamma = max(0.1, min(self.gamma, 2.0))

    def allocate_page(self):
        for block in self.nand.blocks:
            if block.free_pages > 0:
                return block.block_id, block.next_free_page_index
        return None, None

    def garbage_collect(self):
        self.gc_count += 1
        
        victim_block = None
        highest_score = -float('inf')
        
        erase_counts = self.nand.get_erase_counts()
        current_max_erase = max(erase_counts) if erase_counts and max(erase_counts) > 0 else 1
        
        for block in self.nand.blocks:
            if block.invalid_pages == 0:
                continue 
                
            TotalPages = block.pages_per_block
            InvalidPages = block.invalid_pages
            ValidPages = block.valid_pages
            EraseCount = block.erase_count

            # Re-implemented Scoring Model
            EfficiencyScore = InvalidPages / TotalPages
            MigrationCost = ValidPages / TotalPages
            WearScore = 1.0 - (EraseCount / current_max_erase)
            
            total_score = (self.alpha * EfficiencyScore) - (self.gamma * MigrationCost) + (self.beta * WearScore)
                 
            if total_score > highest_score:
                highest_score = total_score
                victim_block = block
                     
        if not victim_block:
             return
             
        for page_index, page in enumerate(victim_block.pages):
            if page.state == PageState.VALID:
                lba = page.logical_address
                new_block_id, new_page_idx = self.allocate_page()
                if new_block_id is None:
                   break 
                
                success, final_idx = self.nand.get_block(new_block_id).write_page(lba)
                if success:
                    self.l2p_map[lba] = (new_block_id, final_idx)
                    self.total_writes += 1
                    
        victim_block.erase()
