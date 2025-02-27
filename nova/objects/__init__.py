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

import typing as ty

if ty.TYPE_CHECKING:
    from nova.objects.aggregate import *  # noqa
    from nova.objects.block_device import *  # noqa
    from nova.objects.build_request import *  # noqa
    from nova.objects.cell_mapping import *  # noqa
    from nova.objects.compute_node import *  # noqa
    from nova.objects.diagnostics import *  # noqa
    from nova.objects.console_auth_token import *  # noqa
    from nova.objects.ec2 import *  # noqa
    from nova.objects.external_event import *  # noqa
    from nova.objects.flavor import *  # noqa
    from nova.objects.host_mapping import *  # noqa
    from nova.objects.hv_spec import *  # noqa
    from nova.objects.image_meta import *  # noqa
    from nova.objects.instance import *  # noqa
    from nova.objects.instance_action import *  # noqa
    from nova.objects.instance_fault import *  # noqa
    from nova.objects.instance_group import *  # noqa
    from nova.objects.instance_info_cache import *  # noqa
    from nova.objects.instance_mapping import *  # noqa
    from nova.objects.instance_numa import *  # noqa
    from nova.objects.instance_pci_requests import *  # noqa
    from nova.objects.keypair import *  # noqa
    from nova.objects.migrate_data import *  # noqa
    from nova.objects.virt_device_metadata import *  # noqa
    from nova.objects.migration import *  # noqa
    from nova.objects.migration_context import *  # noqa
    from nova.objects.monitor_metric import *  # noqa
    from nova.objects.network_metadata import *  # noqa
    from nova.objects.network_request import *  # noqa
    from nova.objects.numa import *  # noqa
    from nova.objects.pci_device import *  # noqa
    from nova.objects.pci_device_pool import *  # noqa
    from nova.objects.request_spec import *  # noqa
    from nova.objects.tag import *  # noqa
    from nova.objects.quotas import *  # noqa
    from nova.objects.resource import *  # noqa
    from nova.objects.security_group import *  # noqa
    from nova.objects.selection import *  # noqa
    from nova.objects.service import *  # noqa
    from nova.objects.task_log import *  # noqa
    from nova.objects.trusted_certs import *  # noqa
    from nova.objects.vcpu_model import *  # noqa
    from nova.objects.virt_cpu_topology import *  # noqa
    from nova.objects.virtual_interface import *  # noqa
    from nova.objects.volume_usage import *  # noqa
    from nova.objects.share_mapping import *  # noqa


def register_all():
    # NOTE(danms): You must make sure your object gets imported in this
    # function in order for it to be registered by services that may
    # need to receive it via RPC.
    __import__('nova.objects.aggregate')
    __import__('nova.objects.block_device')
    __import__('nova.objects.build_request')
    __import__('nova.objects.cell_mapping')
    __import__('nova.objects.compute_node')
    __import__('nova.objects.diagnostics')
    __import__('nova.objects.console_auth_token')
    __import__('nova.objects.ec2')
    __import__('nova.objects.external_event')
    __import__('nova.objects.flavor')
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
    __import__('nova.objects.selection')
    __import__('nova.objects.service')
    __import__('nova.objects.task_log')
    __import__('nova.objects.trusted_certs')
    __import__('nova.objects.vcpu_model')
    __import__('nova.objects.virt_cpu_topology')
    __import__('nova.objects.virtual_interface')
    __import__('nova.objects.volume_usage')
    __import__('nova.objects.share_mapping')
