# vim: tabstop=4 shiftwidth=4 softtabstop=4

# Copyright 2012 IBM Corp.
#
#    Licensed under the Apache License, Version 2.0 (the "License"); you may
#    not use this file except in compliance with the License. You may obtain
#    a copy of the License at
#
#         http://www.apache.org/licenses/LICENSE-2.0
#
#    Unless required by applicable law or agreed to in writing, software
#    distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
#    WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
#    License for the specific language governing permissions and limitations
#    under the License.

"""PowerVM Logical Partition (LPAR)

PowerVM LPAR configuration attributes.
"""

import shlex

from nova.openstack.common.gettextutils import _
from nova.openstack.common import log as logging
from nova.virt.powervm import exception

LOG = logging.getLogger(__name__)


def load_from_conf_data(conf_data):
    """LPAR configuration data parser.

    The configuration data is a string representation of
    the attributes of a Logical Partition. The attributes
    consists of name/value pairs, which are in command separated
    value format.
    Example format: name=lpar_name,lpar_id=1,lpar_env=aixlinux

    :param conf_data: string containing the LPAR configuration data.
    :returns: LPAR -- LPAR object.
    """
    # config_data can contain comma separated values within
    # double quotes, example: virtual_serial_adapters
    # and virtual_scsi_adapters attributes. So can't simply
    # split them by ','.
    cf_splitter = shlex.shlex(conf_data, posix=True)
    cf_splitter.whitespace = ','
    cf_splitter.whitespace_split = True
    attribs = dict(item.split("=") for item in list(cf_splitter))
    lpar = LPAR()
    for (key, value) in attribs.items():
        try:
            lpar[key] = value
        except exception.PowerVMLPARAttributeNotFound:
            LOG.info(_('Encountered unknown LPAR attribute: %s\n'
                       'Continuing without storing') % key)
    return lpar


class LPAR(object):

    """
    Simple class representing a logical partition and the attributes
    for the partition and/or its selected profile.
    """

    # Attributes for all logical partitions
    LPAR_ATTRS = (
        'name',
        'lpar_id',
        'lpar_env',
        'state',
        'resource_config',
        'os_version',
        'logical_serial_num',
        'default_profile',
        'profile_name',
        'curr_profile',
        'work_group_id',
        'allow_perf_collection',
        'power_ctrl_lpar_ids',
        'boot_mode',
        'lpar_keylock',
        'auto_start',
        'uptime',
        'lpar_avail_priority',
        'desired_lpar_proc_compat_mode',
        'curr_lpar_proc_compat_mode',
        'virtual_eth_mac_base_value',
        'rmc_ipaddr'
    )

    # Logical partitions may contain one or more profiles, which
    # may have the following attributes
    LPAR_PROFILE_ATTRS = (
        'name',
        'lpar_name',
        'lpar_id',
        'os_type',
        'all_resources',
        'mem_mode',
        'min_mem',
        'desired_mem',
        'max_mem',
        'proc_mode',
        'min_proc_units',
        'desired_proc_units',
        'max_proc_units',
        'min_procs',
        'desired_procs',
        'max_procs',
        'sharing_mode',
        'uncap_weight',
        'io_slots',
        'lpar_io_pool_ids',
        'max_virtual_slots',
        'virtual_serial_adapters',
        'virtual_scsi_adapters',
        'virtual_eth_adapters',
        'boot_mode',
        'conn_monitoring',
        'auto_start',
        'power_ctrl_lpar_ids',
        'lhea_logical_ports',
        'lhea_capabilities',
        'lpar_proc_compat_mode',
        'virtual_fc_adapters'
    )

    def __init__(self, **kwargs):
        self.attributes = dict([k, None] for k in self.LPAR_ATTRS)
        self.profile_attributes = dict([k, None] for k
                                       in self.LPAR_PROFILE_ATTRS)
        self.attributes.update(kwargs)
        self.profile_attributes.update(kwargs)
        self.all_attrs = dict(self.attributes.items()
                              + self.profile_attributes.items())

    def __getitem__(self, key):
        if key not in self.all_attrs.keys():
            raise exception.PowerVMLPARAttributeNotFound(key)
        return self.all_attrs.get(key)

    def __setitem__(self, key, value):
        if key not in self.all_attrs.keys():
            raise exception.PowerVMLPARAttributeNotFound(key)
        self.all_attrs[key] = value

    def __delitem__(self, key):
        if key not in self.all_attrs.keys():
            raise exception.PowerVMLPARAttributeNotFound(key)
        # We set to None instead of removing the key...
        self.all_attrs[key] = None

    def to_string(self, exclude_attribs=[]):
        conf_data = []
        for (key, value) in self.all_attrs.items():
            if key in exclude_attribs or value is None:
                continue
            conf_data.append('%s=%s' % (key, value))

        return ','.join(conf_data)
