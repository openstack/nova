from nova import test
from nova.scheduler import least_cost

MB = 1024 * 1024

class FakeHost(object):
    def __init__(self, host_id, free_ram, io):
        self.id = host_id
        self.free_ram = free_ram
        self.io = io

class WeightedSumTest(test.TestCase):
    def test_empty_domain(self):
        domain = []
        weighted_fns = []
        result = least_cost.weighted_sum(domain, weighted_fns)
        expected = []
        self.assertEqual(expected, result)

    def test_basic_costing(self):
        hosts = [
            FakeHost(1, 512 * MB, 100),
            FakeHost(2, 256 * MB, 400),
            FakeHost(3, 512 * MB, 100)
        ]

        weighted_fns = [
            (1, lambda h: h.free_ram),  # Fill-first, free_ram is a *cost*
            (2, lambda h: h.io),  # Avoid high I/O
        ]

        costs = least_cost.weighted_sum(domain=hosts, weighted_fns=weighted_fns)

        # Each 256 MB unit of free-ram contributes 0.5 points by way of:
        #   cost = weight * (score/max_score) = 1 * (256/512) = 0.5
        # Each 100 iops of IO adds 0.5 points by way of:
        #   cost = 2 * (100/400) = 2 * 0.25 = 0.5
        expected = [1.5, 2.5, 1.5]
        self.assertEqual(expected, costs) 
