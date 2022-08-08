# Copyright (c) 2013 VMware, Inc.
# All Rights Reserved.
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


from oslo_log import log as logging
from oslo_vmware import vim_util as vutil

from nova import exception
from nova.i18n import _
from nova import utils

LOG = logging.getLogger(__name__)


def reconfigure_cluster(session, cluster, config_spec):
    reconfig_task = session._call_method(
        session.vim, "ReconfigureComputeResource_Task",
        cluster, spec=config_spec,
        modify=True)
    session.wait_for_task(reconfig_task)


def _create_vm_group_spec(client_factory, group_info, vm_refs,
                          operation="add", group=None):
    group = group or client_factory.create('ns0:ClusterVmGroup')
    group.name = group_info.uuid

    # On vCenter UI, it is not possible to create VM group without
    # VMs attached to it. But, using APIs, it is possible to create
    # VM group without VMs attached. Therefore, check for existence
    # of vm attribute in the group to avoid exceptions
    if hasattr(group, 'vm'):
        group.vm += vm_refs
    else:
        group.vm = vm_refs

    group_spec = client_factory.create('ns0:ClusterGroupSpec')
    group_spec.operation = operation
    group_spec.info = group
    return [group_spec]


def _create_host_group_spec(client_factory, name, host_refs, operation="add",
                            group=None):
    group = group or client_factory.create('ns0:ClusterHostGroup')
    group.name = name

    if hasattr(group, 'host'):
        group.host += host_refs
    else:
        group.host = host_refs

    group_spec = client_factory.create('ns0:ClusterGroupSpec')
    group_spec.operation = operation
    group_spec.info = group
    return group_spec


def _get_vm_group(cluster_config, group_info):
    if not hasattr(cluster_config, 'group'):
        return
    for group in cluster_config.group:
        if group.name == group_info.uuid:
            return group


def validate_vm_group(session, vm_ref):
    max_objects = 1
    vim = session.vim
    property_collector = vim.service_content.propertyCollector

    traversal_spec = vutil.build_traversal_spec(
        vim.client.factory,
        "v_to_r",
        "VirtualMachine",
        "resourcePool",
        False,
        [vutil.build_traversal_spec(vim.client.factory,
                                    "r_to_c",
                                    "ResourcePool",
                                    "parent",
                                    False,
                                    [])])

    object_spec = vutil.build_object_spec(
        vim.client.factory,
        vm_ref,
        [traversal_spec])
    property_spec = vutil.build_property_spec(
        vim.client.factory,
        "ClusterComputeResource",
        ["configurationEx"])

    property_filter_spec = vutil.build_property_filter_spec(
        vim.client.factory,
        [property_spec],
        [object_spec])
    options = vim.client.factory.create('ns0:RetrieveOptions')
    options.maxObjects = max_objects

    pc_result = vim.RetrievePropertiesEx(property_collector,
        specSet=[property_filter_spec], options=options)
    result = None
    """ Retrieving needed hardware properties from ESX hosts """
    with vutil.WithRetrieval(vim, pc_result) as pc_objects:
        for objContent in pc_objects:
            LOG.debug("Retrieving cluster: %s", objContent)
            result = objContent
            break

    return result


def delete_vm_group(session, cluster, vm_group):
    """Add delete impl fro removing group if deleted vm is the
       last vm in a vm group
    """
    client_factory = session.vim.client.factory
    group_spec = client_factory.create('ns0:ClusterGroupSpec')
    groups = []

    group_spec.info = vm_group
    group_spec.operation = "remove"
    group_spec.removeKey = vm_group.name
    groups.append(group_spec)

    config_spec = client_factory.create('ns0:ClusterConfigSpecEx')
    config_spec.groupSpec = groups
    reconfigure_cluster(session, cluster, config_spec)


@utils.synchronized('vmware-vm-group-policy')
def update_placement(session, cluster, vm_ref, group_infos):
    """Updates cluster for vm placement using DRS"""
    cluster_config = session._call_method(
        vutil, "get_object_property", cluster, "configurationEx")

    client_factory = session.vim.client.factory
    config_spec = client_factory.create('ns0:ClusterConfigSpecEx')
    config_spec.groupSpec = []
    for group_info in group_infos:
        group = _get_vm_group(cluster_config, group_info)

        if not group:
            """Creating group"""
            group_spec = _create_vm_group_spec(
                client_factory, group_info, [vm_ref], operation="add",
                group=group)
            config_spec.groupSpec.append(group_spec)

        if group:
            # VM group exists on the cluster which is assumed to be
            # created by VC admin. Add instance to this vm group and let
            # the placement policy defined by the VC admin take over
            group_spec = _create_vm_group_spec(
                client_factory, group_info, [vm_ref], operation="edit",
                group=group)
            config_spec.groupSpec.append(group_spec)

        # If server group policies are defined (by tenants), then
        # create/edit affinity/anti-affinity rules on cluster.
        # Note that this might be add-on to the existing vm group
        # (mentioned above) policy defined by VC admin i.e if VC admin has
        # restricted placement of VMs to a specific group of hosts, then
        # the server group policy from nova might further restrict to
        # individual hosts on a cluster
        if group_info.policies:
            # VM group does not exist on cluster
            policy = group_info.policies[0]
            if policy != 'soft-affinity':
                rule_name = "%s-%s" % (group_info.uuid, policy)
                rule = _get_rule(cluster_config, rule_name)
                operation = "edit" if rule else "add"
                rules_spec = _create_cluster_rules_spec(
                    client_factory, rule_name, [vm_ref], policy=policy,
                    operation=operation, rule=rule)
                if config_spec.rulesSpec is None:
                    config_spec.rulesSpec = [rules_spec]
                else:
                    config_spec.rulesSpec.append(rules_spec)

    reconfigure_cluster(session, cluster, config_spec)


def _create_cluster_rules_spec(client_factory, name, vm_refs,
                               policy='affinity', operation="add",
                               rule=None):

    rules_spec = client_factory.create('ns0:ClusterRuleSpec')
    rules_spec.operation = operation
    if policy == 'affinity' or policy == 'soft-affinity':
        policy_class = 'ns0:ClusterAffinityRuleSpec'
    elif policy == 'anti-affinity' or policy == 'soft-anti-affinity':
        policy_class = 'ns0:ClusterAntiAffinityRuleSpec'
    else:
        msg = _('%s policy is not supported.') % policy
        raise exception.Invalid(msg)

    rules_info = client_factory.create(policy_class)
    rules_info.name = name
    rules_info.enabled = True
    rules_info.mandatory = True
    if operation == "edit":
        rules_info.vm = rule.vm + vm_refs
        rules_info.key = rule.key
        rules_info.ruleUuid = rule.ruleUuid
    else:
        rules_info.vm = vm_refs

    rules_spec.info = rules_info
    return rules_spec


def _get_rule(cluster_config, rule_name):
    if not hasattr(cluster_config, 'rule'):
        return
    for rule in cluster_config.rule:
        if rule.name == rule_name:
            return rule


def _is_drs_enabled(session, cluster):
    """Check if DRS is enabled on a given cluster"""
    drs_config = session._call_method(vutil, "get_object_property", cluster,
                                      "configuration.drsConfig")
    if drs_config and hasattr(drs_config, 'enabled'):
        return drs_config.enabled

    return False


def update_cluster_drs_vm_override(session, cluster, vm_ref, behavior,
                                   enabled=True):
    """Add/Update `ClusterDrsVmConfigSpec` for a VM.

    `behavior` can be any `DrsBehaviour` as string.
    """
    client_factory = session.vim.client.factory

    drs_vm_info = client_factory.create('ns0:ClusterDrsVmConfigInfo')
    drs_vm_info.behavior = behavior
    drs_vm_info.enabled = enabled
    drs_vm_info.key = vm_ref

    drs_vm_spec = client_factory.create('ns0:ClusterDrsVmConfigSpec')
    drs_vm_spec.info = drs_vm_info
    drs_vm_spec.operation = 'add'

    config_spec = client_factory.create('ns0:ClusterConfigSpecEx')
    config_spec.drsVmConfigSpec = [drs_vm_spec]

    reconfigure_cluster(session, cluster, config_spec)
