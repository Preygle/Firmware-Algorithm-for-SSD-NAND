from abc import ABC, abstractmethod
from typing import Dict, Tuple

class BaseFTL(ABC):
    def __init__(self, nand_flash):
        self.nand = nand_flash
        # Map: Logical Page Number (LPN) -> (Block ID, Page Index)
        self.l2p_map: Dict[int, Tuple[int, int]] = {}
        self.total_writes = 0
        self.host_writes = 0
        self.gc_count = 0

    def write(self, logical_address: int):
        """
        Handles host write requests.
        """
        self.host_writes += 1
        
        # Adaptive GC Trigger logic
        min_free_blocks = self.nand.pages_per_block
        current_waf = self.get_waf()
        wear_variance = self.get_wear_variance()
        
        # dynamic threshold calculation based on user formula
        base_threshold = 0.20 # Trigger when 20% invalid globally
        k1 = 0.05
        k2 = 0.01
        dynamic_threshold = base_threshold + (k1 * current_waf) - (k2 * wear_variance)
        global_invalid_ratio = self.nand.get_total_invalid_pages() / (self.nand.total_blocks * self.nand.pages_per_block)

        # Trigger GC proactively if free space is critically low OR invalid pages exceed dynamic threshold
        if self.nand.get_total_free_pages() <= min_free_blocks or global_invalid_ratio > dynamic_threshold:
            self.garbage_collect()

        # Check if updating existing LBA
        if logical_address in self.l2p_map:
            old_block_id, old_page_index = self.l2p_map[logical_address]
            self.nand.get_block(old_block_id).invalidate_page(old_page_index)
            
        # Allocate new page
        block_id, page_index = self.allocate_page()
        
        # If allocation fails, trigger GC
        if block_id is None:
            self.garbage_collect()
            block_id, page_index = self.allocate_page()
            
            # If still fails, storage is completely full
            if block_id is None:
                raise Exception("SSD is completely full. Cannot allocate page even after GC.")

        # Write data to the new physical page
        success, final_page_index = self.nand.get_block(block_id).write_page(logical_address)
        if not success:
            raise Exception("Allocation logic failed to provide a valid free page.")
            
        # Update Mapping Table
        self.l2p_map[logical_address] = (block_id, final_page_index)
        self.total_writes += 1

    @abstractmethod
    def allocate_page(self) -> Tuple[int, int]:
        """
        Must be implemented by subclasses.
        Returns a (block_id, page_index) or (None, None) if none available.
        """
        pass

    @abstractmethod
    def garbage_collect(self):
        """
        Must be implemented by subclasses.
        Selects a victim block, moves valid pages to a new block, and erases the victim.
        """
        pass

    def get_waf(self) -> float:
        """
        Calculates Write Amplification Factor = Total Flash Writes / Host Writes
        """
        if self.host_writes == 0:
            return 1.0
        return self.total_writes / self.host_writes
        
    def get_wear_variance(self) -> float:
        """
        Calculates variance of erase counts across all blocks to measure wear leveling effectiveness.
        """
        erase_counts = self.nand.get_erase_counts()
        if not erase_counts:
            return 0.0
        mean = sum(erase_counts) / len(erase_counts)
        variance = sum((x - mean) ** 2 for x in erase_counts) / len(erase_counts)
        return variance
