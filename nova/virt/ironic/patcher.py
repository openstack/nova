# coding=utf-8
#
# Copyright 2014 Hewlett-Packard Development Company, L.P.
# Copyright 2014 Red Hat, Inc.
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
#
"""
Helper classes for Ironic HTTP PATCH creation.
"""

from oslo_config import cfg

CONF = cfg.CONF
CONF.import_opt('default_ephemeral_format', 'nova.virt.driver')


def create(node):
    """Create an instance of the appropriate DriverFields class.

    :param node: a node object returned from ironicclient
    :returns: GenericDriverFields or a subclass thereof, as appropriate
              for the supplied node.
    """
    if 'pxe' in node.driver:
        return PXEDriverFields(node)
    else:
        return GenericDriverFields(node)


class GenericDriverFields(object):

    def __init__(self, node):
        self.node = node

    def get_deploy_patch(self, instance, image_meta, flavor,
                         preserve_ephemeral=None):
        """Build a patch to add the required fields to deploy a node.

        :param instance: the instance object.
        :param image_meta: the metadata associated with the instance
                           image.
        :param flavor: the flavor object.
        :param preserve_ephemeral: preserve_ephemeral status (bool) to be
                                   specified during rebuild.
        :returns: a json-patch with the fields that needs to be updated.

        """
        patch = []
        patch.append({'path': '/instance_info/image_source', 'op': 'add',
                      'value': image_meta['id']})
        patch.append({'path': '/instance_info/root_gb', 'op': 'add',
                      'value': str(instance.root_gb)})
        patch.append({'path': '/instance_info/swap_mb', 'op': 'add',
                      'value': str(flavor['swap'])})

        if instance.ephemeral_gb:
            patch.append({'path': '/instance_info/ephemeral_gb',
                          'op': 'add',
                          'value': str(instance.ephemeral_gb)})
            if CONF.default_ephemeral_format:
                patch.append({'path': '/instance_info/ephemeral_format',
                              'op': 'add',
                              'value': CONF.default_ephemeral_format})

        if preserve_ephemeral is not None:
            patch.append({'path': '/instance_info/preserve_ephemeral',
                          'op': 'add', 'value': str(preserve_ephemeral)})

        return patch

    def get_cleanup_patch(self, instance, network_info, flavor):
        """Build a patch to clean up the fields.

        :param instance: the instance object.
        :param network_info: the instance network information.
        :param flavor: the flavor object.
        :returns: a json-patch with the fields that needs to be updated.

        """
        return []


class PXEDriverFields(GenericDriverFields):

    def _get_kernel_ramdisk_dict(self, flavor):
        """Get the deploy ramdisk and kernel IDs from the flavor.

        :param flavor: the flavor object.
        :returns: a dict with the pxe options for the deploy ramdisk and
            kernel if the IDs were found in the flavor, otherwise an empty
            dict is returned.

        """
        extra_specs = flavor['extra_specs']
        deploy_kernel = extra_specs.get('baremetal:deploy_kernel_id')
        deploy_ramdisk = extra_specs.get('baremetal:deploy_ramdisk_id')
        deploy_ids = {}
        if deploy_kernel and deploy_ramdisk:
            deploy_ids['pxe_deploy_kernel'] = deploy_kernel
            deploy_ids['pxe_deploy_ramdisk'] = deploy_ramdisk
        return deploy_ids

    def get_deploy_patch(self, instance, image_meta, flavor,
                         preserve_ephemeral=None):
        """Build a patch to add the required fields to deploy a node.

        Build a json-patch to add the required fields to deploy a node
        using the PXE driver.

        :param instance: the instance object.
        :param image_meta: the metadata associated with the instance
                           image.
        :param flavor: the flavor object.
        :param preserve_ephemeral: preserve_ephemeral status (bool) to be
                                   specified during rebuild.
        :returns: a json-patch with the fields that needs to be updated.

        """
        patch = super(PXEDriverFields, self).get_deploy_patch(
                    instance, image_meta, flavor, preserve_ephemeral)

        # TODO(lucasagomes): Remove it in Kilo. This is for backwards
        # compatibility with Icehouse. If flavor contains both ramdisk
        # and kernel ids, use them.
        for key, value in self._get_kernel_ramdisk_dict(flavor).items():
            patch.append({'path': '/driver_info/%s' % key,
                          'op': 'add', 'value': value})

        return patch

    def get_cleanup_patch(self, instance, network_info, flavor):
        """Build a patch to clean up the fields.

        Build a json-patch to remove the fields used to deploy a node
        using the PXE driver. Note that the fields added to the Node's
        instance_info don't need to be removed because they are purged
        during the Node's tear down.

        :param instance: the instance object.
        :param network_info: the instance network information.
        :param flavor: the flavor object.
        :returns: a json-patch with the fields that needs to be updated.

        """
        patch = super(PXEDriverFields, self).get_cleanup_patch(
                    instance, network_info, flavor)

        # TODO(lucasagomes): Remove it in Kilo. This is for backwards
        # compatibility with Icehouse. If flavor contains a ramdisk and
        # kernel id remove it from nodes as part of the tear down process
        for key in self._get_kernel_ramdisk_dict(flavor):
            if key in self.node.driver_info:
                patch.append({'op': 'remove',
                              'path': '/driver_info/%s' % key})
        return patch
