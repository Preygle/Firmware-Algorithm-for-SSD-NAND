"""
ftl_layer.py
Engineer 1 – FTL & Logical Mapping Layer

Responsibilities:
- Maintain Logical-to-Physical (L2P) mapping
- Handle overwrites (invalidate old physical pages)
- Maintain free page list
- Interface with NAND API
- Remain independent from GC decision logic

This layer does NOT:
- Decide when GC happens
- Select victim blocks
- Implement wear-leveling
"""

from collections import deque


class FTLLayer:
    """
    Flash Translation Layer (Mapping Layer)

    This class translates logical block addresses (LBA)
    to physical NAND addresses (block_id, page_id).
    """

    # --------------------------------------------------
    # Initialization
    # --------------------------------------------------

    def __init__(self, nand):
        """
        :param nand: Instance of NANDFlash (real or mock)
        """
        self.nand = nand

        # Logical to Physical mapping
        # { lba: (block_id, page_id) }
        self.l2p = {}

        # Queue of free physical pages
        # deque for efficient pop from left
        self.free_pages = deque()

        self._initialize_free_pages()

    def _initialize_free_pages(self):
        """
        Scan NAND at startup and collect all FREE pages.
        """
        for block in self.nand.blocks:
            for page in block.pages:
                if page.state == "FREE":
                    self.free_pages.append((block.block_id, page.page_id))

    # --------------------------------------------------
    # Public API
    # --------------------------------------------------

    def write(self, lba, data):
        """
        Write data to a logical block address.

        Handles:
        - Overwrite invalidation
        - Allocation of new physical page
        - L2P update

        :raises RuntimeError: if no free pages available
        """

        # Step 1: Invalidate old physical page if overwrite
        if lba in self.l2p:
            old_block, old_page = self.l2p[lba]
            self.nand.invalidate_page(old_block, old_page)

        # Step 2: Allocate free physical page
        if not self.free_pages:
            raise RuntimeError("No free pages available. Garbage Collection required.")

        block_id, page_id = self.free_pages.popleft()

        # Step 3: Write to NAND
        self.nand.write_page(block_id, page_id, data)

        # Step 4: Update L2P mapping
        self.l2p[lba] = (block_id, page_id)

    def read(self, lba):
        """
        Read data from a logical block address.

        :raises KeyError: if LBA not mapped
        """
        if lba not in self.l2p:
            raise KeyError(f"LBA {lba} not mapped.")

        block_id, page_id = self.l2p[lba]
        return self.nand.read_page(block_id, page_id)

    # --------------------------------------------------
    # Garbage Collection Support (Called by Firmware)
    # --------------------------------------------------

    def notify_block_erased(self, block_id):
        """
        Must be called by firmware AFTER it erases a block.

        This refreshes free page pool for that block.
        """
        block = self.nand.blocks[block_id]

        for page in block.pages:
            self.free_pages.append((block.block_id, page.page_id))

    # --------------------------------------------------
    # Utility Methods (For Firmware / Metrics)
    # --------------------------------------------------

    def get_free_page_count(self):
        """
        Returns number of free physical pages.
        """
        return len(self.free_pages)

    def get_mapping_table(self):
        """
        Returns L2P mapping dictionary.
        """
        return self.l2p.copy()

    def is_lba_mapped(self, lba):
        """
        Check if logical address exists.
        """
        return lba in self.l2p

    def physical_address(self, lba):
        """
        Returns physical address for given LBA.
        """
        if lba not in self.l2p:
            raise KeyError(f"LBA {lba} not mapped.")
        return self.l2p[lba]
