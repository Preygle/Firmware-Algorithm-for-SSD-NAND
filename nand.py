class PageState:
    FREE = 0
    VALID = 1
    INVALID = 2

class Page:
    def __init__(self, logical_address=None):
        self.state = PageState.FREE
        self.logical_address = logical_address  # Tracks which LBA this maps to

class Block:
    def __init__(self, block_id, pages_per_block):
        self.block_id = block_id
        self.pages_per_block = pages_per_block
        self.erase_count = 0
        self.pages = [Page() for _ in range(pages_per_block)]
        self.free_pages = pages_per_block
        self.valid_pages = 0
        self.invalid_pages = 0
        self.next_free_page_index = 0

    def write_page(self, logical_address):
        """Writes to next free page. Simulates erase-before-write constraint."""
        if self.next_free_page_index >= self.pages_per_block:
            return False, "Block is full"
        page = self.pages[self.next_free_page_index]
        page.state = PageState.VALID
        page.logical_address = logical_address
        self.free_pages -= 1
        self.valid_pages += 1
        self.next_free_page_index += 1
        return True, self.next_free_page_index - 1

    def invalidate_page(self, page_index):
        """Marks a page as invalid. Does not free it."""
        if 0 <= page_index < self.pages_per_block:
            page = self.pages[page_index]
            if page.state == PageState.VALID:
                page.state = PageState.INVALID
                self.valid_pages -= 1
                self.invalid_pages += 1
                page.logical_address = None

    def erase(self):
        """Erases the block, resetting all pages."""
        self.erase_count += 1
        self.pages = [Page() for _ in range(self.pages_per_block)]
        self.free_pages = self.pages_per_block
        self.valid_pages = 0
        self.invalid_pages = 0
        self.next_free_page_index = 0
        
    def get_invalid_ratio(self):
        return self.invalid_pages / self.pages_per_block if self.pages_per_block > 0 else 0


class NANDFlash:
    def __init__(self, total_blocks, pages_per_block, op_ratio=0.10):
        self.total_blocks = total_blocks
        self.pages_per_block = pages_per_block
        
        # Over-Provisioning modeling
        self.op_ratio = op_ratio
        self.reserved_blocks_count = int(total_blocks * op_ratio)
        self.logical_blocks_count = total_blocks - self.reserved_blocks_count
        
        self.blocks = [Block(i, pages_per_block) for i in range(total_blocks)]

    def get_block(self, block_id):
        return self.blocks[block_id]
        
    def get_total_free_pages(self):
        return sum(b.free_pages for b in self.blocks)
        
    def get_total_valid_pages(self):
        return sum(b.valid_pages for b in self.blocks)
        
    def get_total_invalid_pages(self):
        return sum(b.invalid_pages for b in self.blocks)

    def get_erase_counts(self):
        return [b.erase_count for b in self.blocks]
