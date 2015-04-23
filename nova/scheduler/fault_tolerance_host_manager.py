from oslo.config import cfg
from nova.scheduler import host_manager
from nova.scheduler import weights

import itertools

CONF = cfg.CONF
CONF.set_default('scheduler_weight_classes',
                 ['nova.scheduler.weights.ft_all_weighers'])


class FaultToleranceHostManager(host_manager.HostManager):

    def __init__(self):
        super(FaultToleranceHostManager, self).__init__()
        self.weight_handler = weights.FaultToleranceHostWeightHandler()
        self.weight_classes = self.weight_handler.get_matching_classes(
                CONF.scheduler_weight_classes)

    def _force_primary_hosts(self, host_combinations, force_hosts,
                             force_nodes):
        """Filter all combinations that include a forced host and make
        the forced host the primary candidate.
        """
        forced_host_combinations = []

        for host_combination in host_combinations:
            for i, host in enumerate(host_combination):
                if force_hosts and host.host not in force_hosts:
                    continue
                if force_nodes and host.nodename not in force_nodes:
                    continue

                # Make forced host the candidate for primary instance
                hosts = list(host_combination)
                hosts.insert(0, hosts.pop(i))
                forced_host_combinations.append(tuple(hosts))
                break

        return forced_host_combinations

    def get_filtered_hosts(self, size, hosts, filter_properties,
                           filter_class_names=None, index=0):
        """Filters the hosts and combines the hosts into sets.

        Forced hosts are promoted to candidates for the primary instance.
        However, secondary instances can be deployed on other hosts that are
        not forced.

        Hostsets that include ignored hosts or are missing forced hosts are
        excluded.
        """
        force_hosts = filter_properties.get('force_hosts', [])
        force_nodes = filter_properties.get('force_nodes', [])

        # Handle forced and ignored host after combining.
        filter_properties['force_hosts'] = []
        filter_properties['force_nodes'] = []

        hosts = super(FaultToleranceHostManager, self).get_filtered_hosts(
                      hosts, filter_properties, filter_class_names, index)

        host_combinations = list(itertools.combinations(hosts, size))

        if force_hosts or force_nodes:
            host_combinations = self._force_primary_hosts(host_combinations,
                                                          force_hosts,
                                                          force_nodes)

        # Reset the filters for muliple instance scheduling
        filter_properties['force_hosts'] = force_hosts
        filter_properties['force_nodes'] = force_nodes

        return (hosts, host_combinations)
