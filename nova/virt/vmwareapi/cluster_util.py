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


def create_vm_group(client_factory, name, vm_refs, group=None):
    """Create a ClusterVmGroup object

    :param:group: if given, update this ClusterVmGroup object instead of
                  creating a new one
    """
    group = group or client_factory.create('ns0:ClusterVmGroup')
    group.name = name
    group.vm = vm_refs

    return group


def create_host_group(client_factory, name, host_refs, group=None):
    """Create a ClusterHostGroup object

    :param:group: if given, update the ClusterHostGroup object instead of
                  creating a new one
    """
    group = group or client_factory.create('ns0:ClusterHostGroup')
    group.name = name

    if hasattr(group, 'host'):
        group.host += host_refs
    else:
        group.host = host_refs

    return group


def create_group_spec(client_factory, group, operation):
    """Create a ClusterGroupSpec object"""
    if operation not in ('add', 'edit', 'remove'):
        msg = 'Invalid operation for ClusterGroupSpec: {}'.format(operation)
        raise exception.ValidationError(msg)

    group_spec = client_factory.create('ns0:ClusterGroupSpec')
    group_spec.operation = operation
    group_spec.info = group
    if operation == 'remove':
        group_spec.removeKey = group.name

    return group_spec


def _create_vm_group_spec(client_factory, group_info, vm_refs,
                          operation="add", group=None):
    if group:
        # On vCenter UI, it is not possible to create VM group without
        # VMs attached to it. But, using APIs, it is possible to create
        # VM group without VMs attached. Therefore, check for existence
        # of vm attribute in the group to avoid exceptions
        if hasattr(group, 'vm'):
            vm_refs = vm_refs + group.vm

    group = create_vm_group(client_factory, group_info.uuid, vm_refs, group)

    return create_group_spec(client_factory, group, operation)


def _get_vm_group(cluster_config, group_info):
    if not hasattr(cluster_config, 'group'):
        return
    for group in cluster_config.group:
        if group.name == group_info.uuid:
            return group


def delete_vm_group(session, cluster, vm_group):
    """Add delete impl fro removing group if deleted vm is the
       last vm in a vm group
    """
    client_factory = session.vim.client.factory
    groups = []

    group_spec = create_group_spec(client_factory, vm_group, "remove")
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
    config_spec.rulesSpec = []
    for group_info in group_infos:
        group = _get_vm_group(cluster_config, group_info)

        if not group:
            # Creating group
            operation = "add"
        else:
            # VM group exists on the cluster which is assumed to be
            # created by VC admin. Add instance to this vm group and let
            # the placement policy defined by the VC admin take over
            operation = "edit"
        group_spec = _create_vm_group_spec(
            client_factory, group_info, [vm_ref], operation=operation,
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
                config_spec.rulesSpec.append(rules_spec)

    reconfigure_cluster(session, cluster, config_spec)


def create_vm_rule(client_factory, name, vm_refs, policy='affinity',
                   rule=None):
    """Create a ClusterAffinityRuleSpec or ClusterAntiAffinityRuleSpec object

    :param:policy: Defines with of the object types is created. "affinity" and
                   "soft-affinity" map to ClusterAffinityRuleSpec,
                   "anti-affinity" and "soft-anti-affinity" map to
                   ClusterAntiAffinityRuleSpec. Ignored if "rule" is given
    :param:rule: if given, don't create any object, but instead update the
                 given object's attributes. "policy" is ignored here.
    """
    if rule is None:
        if policy in ('affinity', 'soft-affinity'):
            obj_type = 'ns0:ClusterAffinityRuleSpec'
        elif policy in ('anti-affinity', 'soft-anti-affinity'):
            obj_type = 'ns0:ClusterAntiAffinityRuleSpec'
        else:
            msg = 'Policy {} is not supported.'.format(policy)
            raise exception.ValidationError(msg)

        rule = client_factory.create(obj_type)

    rule.name = name
    rule.enabled = True
    rule.vm = vm_refs

    return rule


def create_rule_spec(client_factory, rule, operation='add'):
    """Create a ClusterRuleSpec object"""
    rule_spec = client_factory.create('ns0:ClusterRuleSpec')
    rule_spec.operation = operation
    rule_spec.info = rule
    if operation == 'remove':
        rule_spec.removeKey = rule.key
    return rule_spec


def _create_cluster_rules_spec(client_factory, name, vm_refs,
                               policy='affinity', operation="add",
                               rule=None):
    if operation == 'edit':
        vm_refs = vm_refs + rule.vm
    rule = create_vm_rule(client_factory, name, vm_refs, policy, rule)
    return create_rule_spec(client_factory, rule, operation)


def _create_cluster_group_rules_spec(client_factory, name, vm_group_name,
                                     host_group_name, policy='affinity',
                                     rule=None):
    rules_info = client_factory.create('ns0:ClusterVmHostRuleInfo')
    rules_info.name = name
    rules_info.enabled = True
    rules_info.mandatory = True
    rules_info.vmGroupName = vm_group_name
    if policy == 'affinity':
        rules_info.affineHostGroupName = host_group_name
    elif policy == 'anti-affinity':
        rules_info.antiAffineHostGroupName = host_group_name
    else:
        msg = _('%s policy is not supported.') % policy
        raise exception.ValidationError(msg)

    if rule is not None:
        rules_info.key = rule.key
        rules_info.ruleUuid = rule.ruleUuid

    operation = 'add' if rule is None else 'edit'
    return create_rule_spec(client_factory, rules_info, operation)


def _get_rule(cluster_config, rule_name):
    if not hasattr(cluster_config, 'rule'):
        return
    for rule in cluster_config.rule:
        if rule.name == rule_name:
            return rule


def is_drs_enabled(session, cluster):
    """Check if DRS is enabled on a given cluster"""
    drs_config = session._call_method(vutil, "get_object_property", cluster,
                                      "configuration.drsConfig")
    if drs_config and hasattr(drs_config, 'enabled'):
        return drs_config.enabled

    return False
