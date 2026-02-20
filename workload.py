import random

class WorkloadGenerator:
    def __init__(self, max_lba):
        self.max_lba = max_lba

    def generate_sequential(self, num_writes):
        """Generates sequential LBAs starting from 0."""
        return [i % self.max_lba for i in range(num_writes)]

    def generate_random(self, num_writes):
        """Generates uniformly random LBAs."""
        return [random.randint(0, self.max_lba - 1) for _ in range(num_writes)]

    def generate_hotspot(self, num_writes, hot_ratio=0.8, hot_data_fraction=0.2):
        """
        Generates a hotspot workload.
        hot_ratio: percentage of writes that go to hot data (e.g., 80%)
        hot_data_fraction: percentage of LBAs that are considered hot (e.g., 20%)
        """
        writes = []
        hot_lba_max = int(self.max_lba * hot_data_fraction)
        
        for _ in range(num_writes):
            if random.random() < hot_ratio and hot_lba_max > 0:
                # Write to hot region
                writes.append(random.randint(0, hot_lba_max - 1))
            else:
                # Write to cold region
                writes.append(random.randint(hot_lba_max, self.max_lba - 1))
        return writes

    def generate_mixed(self, num_writes):
        """Mix of sequential and random."""
        writes = []
        seq_lba = 0
        for _ in range(num_writes):
            if random.random() < 0.5:
                writes.append(seq_lba % self.max_lba)
                seq_lba += 1
            else:
                writes.append(random.randint(0, self.max_lba - 1))
        return writes
