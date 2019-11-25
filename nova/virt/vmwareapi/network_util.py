# Copyright (c) 2012 VMware, Inc.
# Copyright (c) 2011 Citrix Systems, Inc.
# Copyright 2011 OpenStack Foundation
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

"""
Utility functions for ESX Networking.
"""
import re

from oslo_log import log as logging
from oslo_vmware import vim_util as vutil

from nova.virt.vmwareapi import vim_util
from nova.virt.vmwareapi import vm_util

LOG = logging.getLogger(__name__)

# a virtual wire will have the following format:
# vxw-<dvs-moref>-<virtualwire-moref>-<sid-moref>-<name>
# Examples:
# - vxw-dvs-22-virtualwire-89-sid-5008-NAME
# - vxw-dvs-22-virtualwire-89-sid-5008-UUID
VWIRE_REGEX = re.compile(r'vxw-dvs-(\d+)-virtualwire-(\d+)-sid-(\d+)-(.*)')


def _get_name_from_dvs_name(dvs_name):
    vwire = VWIRE_REGEX.match(dvs_name)
    if not vwire:
        return dvs_name
    return vwire.group(4)


def _get_network_obj(session, network_objects, network_name):
    """Gets the network object for the requested network.

    The network object will be used when creating the VM configuration
    spec. The network object contains the relevant network details for
    the specific network type, for example, a distributed port group.

    The method will search for the network_name in the list of
    network_objects.

    :param session: vCenter soap session
    :param network_objects: group of networks
    :param network_name: the requested network
    :return: network object
    """

    network_obj = {}
    # network_objects is actually a RetrieveResult object from vSphere API call
    for obj_content in network_objects:
        # the propset attribute "need not be set" by returning API
        if not hasattr(obj_content, 'propSet'):
            continue
        prop_dict = vm_util.propset_dict(obj_content.propSet)
        network_refs = prop_dict.get('network')
        if network_refs:
            network_refs = network_refs.ManagedObjectReference
            for network in network_refs:
                # Get network properties
                if network._type == 'DistributedVirtualPortgroup':
                    props = session._call_method(vutil,
                                                 "get_object_property",
                                                 network,
                                                 "config")
                    # NOTE(asomya): This only works on ESXi if the port binding
                    # is set to ephemeral
                    net_name = _get_name_from_dvs_name(props.name)
                    if network_name in net_name:
                        network_obj['type'] = 'DistributedVirtualPortgroup'
                        network_obj['dvpg'] = props.key
                        dvs_props = session._call_method(vutil,
                                        "get_object_property",
                                        props.distributedVirtualSwitch,
                                        "uuid")
                        network_obj['dvsw'] = dvs_props
                        return network_obj
                else:
                    props = session._call_method(vutil,
                                                 "get_object_property",
                                                 network,
                                                 "summary.name")
                    if props == network_name:
                        network_obj['type'] = 'Network'
                        network_obj['name'] = network_name
                        return network_obj


def get_network_with_the_name(session, network_name="vmnet0", cluster=None):
    """Gets reference to the network whose name is passed as the
    argument.
    """
    vm_networks = session._call_method(vim_util,
                                       'get_object_properties',
                                       None, cluster,
                                       'ClusterComputeResource', ['network'])

    with vutil.WithRetrieval(session.vim, vm_networks) as network_objs:
        network_obj = _get_network_obj(session, network_objs, network_name)
        if network_obj:
            return network_obj

    LOG.debug("Network %s not found on cluster!", network_name)
