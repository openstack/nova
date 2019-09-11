#    Copyright 2013 IBM Corp.
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

# NOTE(comstud): You may scratch your head as you see code that imports
# this module and then accesses attributes for objects such as Instance,
# etc, yet you do not see these attributes in here. Never fear, there is
# a little bit of magic. When objects are registered, an attribute is set
# on this module automatically, pointing to the newest/latest version of
# the object.


def register_all():
    # NOTE(danms): You must make sure your object gets imported in this
    # function in order for it to be registered by services that may
    # need to receive it via RPC.
    __import__('nova.objects.agent')
    __import__('nova.objects.aggregate')
    __import__('nova.objects.bandwidth_usage')
    __import__('nova.objects.block_device')
    __import__('nova.objects.build_request')
    __import__('nova.objects.cell_mapping')
    __import__('nova.objects.compute_node')
    __import__('nova.objects.diagnostics')
    __import__('nova.objects.console_auth_token')
    __import__('nova.objects.dns_domain')
    __import__('nova.objects.ec2')
    __import__('nova.objects.external_event')
    __import__('nova.objects.fixed_ip')
    __import__('nova.objects.flavor')
    __import__('nova.objects.floating_ip')
    __import__('nova.objects.host_mapping')
    __import__('nova.objects.hv_spec')
    __import__('nova.objects.image_meta')
    __import__('nova.objects.instance')
    __import__('nova.objects.instance_action')
    __import__('nova.objects.instance_fault')
    __import__('nova.objects.instance_group')
    __import__('nova.objects.instance_info_cache')
    __import__('nova.objects.instance_mapping')
    __import__('nova.objects.instance_numa')
    __import__('nova.objects.instance_pci_requests')
    __import__('nova.objects.keypair')
    __import__('nova.objects.migrate_data')
    __import__('nova.objects.virt_device_metadata')
    __import__('nova.objects.migration')
    __import__('nova.objects.migration_context')
    __import__('nova.objects.monitor_metric')
    __import__('nova.objects.network')
    __import__('nova.objects.network_metadata')
    __import__('nova.objects.network_request')
    __import__('nova.objects.numa')
    __import__('nova.objects.pci_device')
    __import__('nova.objects.pci_device_pool')
    __import__('nova.objects.request_spec')
    __import__('nova.objects.tag')
    __import__('nova.objects.quotas')
    __import__('nova.objects.resource')
    __import__('nova.objects.security_group')
    __import__('nova.objects.security_group_rule')
    __import__('nova.objects.selection')
    __import__('nova.objects.service')
    __import__('nova.objects.task_log')
    __import__('nova.objects.trusted_certs')
    __import__('nova.objects.vcpu_model')
    __import__('nova.objects.virt_cpu_topology')
    __import__('nova.objects.virtual_interface')
    __import__('nova.objects.volume_usage')
