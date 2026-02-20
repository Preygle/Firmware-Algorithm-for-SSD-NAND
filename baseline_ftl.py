from ftl import BaseFTL
from nand import PageState

class BaselineFTL(BaseFTL):
    def __init__(self, nand_flash):
        super().__init__(nand_flash)
        self.active_block_id = 0

    def allocate_page(self):
        """
        First-fit allocation. Finds the first block with free pages.
        """
        start_block = self.active_block_id
        for _ in range(self.nand.total_blocks):
            block = self.nand.get_block(self.active_block_id)
            if block.free_pages > 0:
                # Still has space
                return self.active_block_id, block.next_free_page_index
            self.active_block_id = (self.active_block_id + 1) % self.nand.total_blocks
            
        return None, None # Complete fill

    def garbage_collect(self):
        """
        Baseline GC: 
        1. Select block with the most invalid pages.
        2. Move valid pages to a new block.
        3. Erase the victim block.
        """
        self.gc_count += 1
        
        # 1. Select victim block
        victim_block = None
        max_invalid = -1
        
        for block in self.nand.blocks:
            # Don't GC the block we are currently allocating from if possible
            if block.block_id == self.active_block_id and block.free_pages > 0:
                continue
                
            if block.invalid_pages > max_invalid:
                max_invalid = block.invalid_pages
                victim_block = block
                
        if not victim_block or max_invalid == 0:
             # Can't reclaim any space
             return
             
        # Find a destination block for valid pages
        # This is a bit simplified, normally SSDs reserve blocks just for GC.
        dest_block_id = None
        for block in self.nand.blocks:
            if block.block_id != victim_block.block_id and block.free_pages >= victim_block.valid_pages:
               dest_block_id = block.block_id
               break
               
        if dest_block_id is None:
            # Very fragmented, can't find a single block, would need more complex GC
            # For this simulation, we try to use the standard allocation
             pass # Will fall back to standard allocation below
            
        
        # 2. Move valid pages
        for page_index, page in enumerate(victim_block.pages):
            if page.state == PageState.VALID:
                lba = page.logical_address
                # Allocate new page for the LBA
                
                new_block_id, new_page_idx = self.allocate_page()
                if new_block_id is None:
                   # This shouldn't happen if we reserved space, but for pure simulation:
                   break 
                   
                # Write to new location
                success, final_idx = self.nand.get_block(new_block_id).write_page(lba)
                if success:
                    # Update mapping
                    self.l2p_map[lba] = (new_block_id, final_idx)
                    self.total_writes += 1
                    
        # 3. Erase victim block
        victim_block.erase()
