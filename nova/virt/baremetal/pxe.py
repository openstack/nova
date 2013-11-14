# vim: tabstop=4 shiftwidth=4 softtabstop=4

# Copyright 2012 Hewlett-Packard Development Company, L.P.
# Copyright (c) 2012 NTT DOCOMO, INC.
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

"""
Class for PXE bare-metal nodes.
"""

import datetime
import os

import jinja2
from oslo.config import cfg

from nova.compute import flavors
from nova import exception
from nova.openstack.common.db import exception as db_exc
from nova.openstack.common import fileutils
from nova.openstack.common.gettextutils import _
from nova.openstack.common import log as logging
from nova.openstack.common import loopingcall
from nova.openstack.common import timeutils
from nova.virt.baremetal import baremetal_states
from nova.virt.baremetal import base
from nova.virt.baremetal import db
from nova.virt.baremetal import utils as bm_utils

pxe_opts = [
    cfg.StrOpt('deploy_kernel',
               help='Default kernel image ID used in deployment phase'),
    cfg.StrOpt('deploy_ramdisk',
               help='Default ramdisk image ID used in deployment phase'),
    cfg.StrOpt('net_config_template',
               default='$pybasedir/nova/virt/baremetal/'
                            'net-dhcp.ubuntu.template',
               help='Template file for injected network config'),
    cfg.StrOpt('pxe_append_params',
               default='nofb nomodeset vga=normal',
               help='additional append parameters for baremetal PXE boot'),
    cfg.StrOpt('pxe_config_template',
               default='$pybasedir/nova/virt/baremetal/pxe_config.template',
               help='Template file for PXE configuration'),
    cfg.BoolOpt('use_file_injection',
                help='If True, enable file injection for network info, '
                'files and admin password',
                default=True),
    cfg.IntOpt('pxe_deploy_timeout',
                help='Timeout for PXE deployments. Default: 0 (unlimited)',
                default=0),
    cfg.BoolOpt('pxe_network_config',
                help='If set, pass the network configuration details to the '
                'initramfs via cmdline.',
                default=False),
    cfg.StrOpt('pxe_bootfile_name',
               help='This gets passed to Neutron as the bootfile dhcp '
               'parameter when the dhcp_options_enabled is set.',
               default='pxelinux.0'),
    ]

LOG = logging.getLogger(__name__)

baremetal_group = cfg.OptGroup(name='baremetal',
                               title='Baremetal Options')

CONF = cfg.CONF
CONF.register_group(baremetal_group)
CONF.register_opts(pxe_opts, baremetal_group)
CONF.import_opt('use_ipv6', 'nova.netconf')


def build_pxe_network_config(network_info):
    interfaces = bm_utils.map_network_interfaces(network_info, CONF.use_ipv6)
    template = None
    if not CONF.use_ipv6:
        template = "ip=%(address)s::%(gateway)s:%(netmask)s::%(name)s:off"
    else:
        template = ("ip=[%(address_v6)s]::[%(gateway_v6)s]:"
                    "[%(netmask_v6)s]::%(name)s:off")

    net_config = [template % iface for iface in interfaces]
    return ' '.join(net_config)


def build_pxe_config(deployment_id, deployment_key, deployment_iscsi_iqn,
                      deployment_aki_path, deployment_ari_path,
                      aki_path, ari_path, network_info):
    """Build the PXE config file for a node

    This method builds the PXE boot configuration file for a node,
    given all the required parameters.

    The resulting file has both a "deploy" and "boot" label, which correspond
    to the two phases of booting. This may be extended later.

    """
    LOG.debug(_("Building PXE config for deployment %s.") % deployment_id)

    network_config = None
    if network_info and CONF.baremetal.pxe_network_config:
        network_config = build_pxe_network_config(network_info)

    pxe_options = {
            'deployment_id': deployment_id,
            'deployment_key': deployment_key,
            'deployment_iscsi_iqn': deployment_iscsi_iqn,
            'deployment_aki_path': deployment_aki_path,
            'deployment_ari_path': deployment_ari_path,
            'aki_path': aki_path,
            'ari_path': ari_path,
            'pxe_append_params': CONF.baremetal.pxe_append_params,
            'pxe_network_config': network_config,
            }
    tmpl_path, tmpl_file = os.path.split(CONF.baremetal.pxe_config_template)
    env = jinja2.Environment(loader=jinja2.FileSystemLoader(tmpl_path))
    template = env.get_template(tmpl_file)
    return template.render({'pxe_options': pxe_options,
                            'ROOT': '${ROOT}'})


def build_network_config(network_info):
    interfaces = bm_utils.map_network_interfaces(network_info, CONF.use_ipv6)
    tmpl_path, tmpl_file = os.path.split(CONF.baremetal.net_config_template)
    env = jinja2.Environment(loader=jinja2.FileSystemLoader(tmpl_path))
    template = env.get_template(tmpl_file)
    return template.render({'interfaces': interfaces,
                            'use_ipv6': CONF.use_ipv6})


def get_deploy_aki_id(instance_type):
    return instance_type.get('extra_specs', {}).\
            get('baremetal:deploy_kernel_id', CONF.baremetal.deploy_kernel)


def get_deploy_ari_id(instance_type):
    return instance_type.get('extra_specs', {}).\
            get('baremetal:deploy_ramdisk_id', CONF.baremetal.deploy_ramdisk)


def get_image_dir_path(instance):
    """Generate the dir for an instances disk."""
    return os.path.join(CONF.instances_path, instance['name'])


def get_image_file_path(instance):
    """Generate the full path for an instances disk."""
    return os.path.join(CONF.instances_path, instance['name'], 'disk')


def get_pxe_config_file_path(instance):
    """Generate the path for an instances PXE config file."""
    return os.path.join(CONF.baremetal.tftp_root, instance['uuid'], 'config')


def get_pxe_bootfile_name(instance):
    """Returns the pxe_bootfile_name option."""
    return CONF.baremetal.pxe_bootfile_name


def get_partition_sizes(instance):
    instance_type = flavors.extract_flavor(instance)
    root_mb = instance_type['root_gb'] * 1024
    swap_mb = instance_type['swap']
    ephemeral_mb = instance_type['ephemeral_gb'] * 1024

    # NOTE(deva): For simpler code paths on the deployment side,
    #             we always create a swap partition. If the flavor
    #             does not specify any swap, we default to 1MB
    if swap_mb < 1:
        swap_mb = 1

    return (root_mb, swap_mb, ephemeral_mb)


def get_pxe_mac_path(mac):
    """Convert a MAC address into a PXE config file name."""
    return os.path.join(
            CONF.baremetal.tftp_root,
            'pxelinux.cfg',
            "01-" + mac.replace(":", "-").lower()
        )


def get_tftp_image_info(instance, instance_type):
    """Generate the paths for tftp files for this instance

    Raises NovaException if
    - instance does not contain kernel_id or ramdisk_id
    - deploy_kernel_id or deploy_ramdisk_id can not be read from
      instance_type['extra_specs'] and defaults are not set

    """
    image_info = {
            'kernel': [None, None],
            'ramdisk': [None, None],
            'deploy_kernel': [None, None],
            'deploy_ramdisk': [None, None],
            }
    try:
        image_info['kernel'][0] = str(instance['kernel_id'])
        image_info['ramdisk'][0] = str(instance['ramdisk_id'])
        image_info['deploy_kernel'][0] = get_deploy_aki_id(instance_type)
        image_info['deploy_ramdisk'][0] = get_deploy_ari_id(instance_type)
    except KeyError:
        pass

    missing_labels = []
    for label in image_info.keys():
        (uuid, path) = image_info[label]
        if not uuid:
            missing_labels.append(label)
        else:
            image_info[label][1] = os.path.join(CONF.baremetal.tftp_root,
                            instance['uuid'], label)
    if missing_labels:
        raise exception.NovaException(_(
            "Can not activate PXE bootloader. The following boot parameters "
            "were not passed to baremetal driver: %s") % missing_labels)
    return image_info


class PXE(base.NodeDriver):
    """PXE bare metal driver."""

    def __init__(self, virtapi):
        super(PXE, self).__init__(virtapi)

    def _collect_mac_addresses(self, context, node):
        macs = set()
        for nic in db.bm_interface_get_all_by_bm_node_id(context, node['id']):
            if nic['address']:
                macs.add(nic['address'])
        return sorted(macs)

    def _cache_tftp_images(self, context, instance, image_info):
        """Fetch the necessary kernels and ramdisks for the instance."""
        fileutils.ensure_tree(
                os.path.join(CONF.baremetal.tftp_root, instance['uuid']))

        LOG.debug(_("Fetching kernel and ramdisk for instance %s") %
                        instance['name'])
        for label in image_info.keys():
            (uuid, path) = image_info[label]
            bm_utils.cache_image(
                    context=context,
                    target=path,
                    image_id=uuid,
                    user_id=instance['user_id'],
                    project_id=instance['project_id'],
                )

    def _cache_image(self, context, instance, image_meta):
        """Fetch the instance's image from Glance

        This method pulls the relevant AMI and associated kernel and ramdisk,
        and the deploy kernel and ramdisk from Glance, and writes them
        to the appropriate places on local disk.

        Both sets of kernel and ramdisk are needed for PXE booting, so these
        are stored under CONF.baremetal.tftp_root.

        At present, the AMI is cached and certain files are injected.
        Debian/ubuntu-specific assumptions are made regarding the injected
        files. In a future revision, this functionality will be replaced by a
        more scalable and os-agnostic approach: the deployment ramdisk will
        fetch from Glance directly, and write its own last-mile configuration.

        """
        fileutils.ensure_tree(get_image_dir_path(instance))
        image_path = get_image_file_path(instance)

        LOG.debug(_("Fetching image %(ami)s for instance %(name)s") %
                        {'ami': image_meta['id'], 'name': instance['name']})
        bm_utils.cache_image(context=context,
                             target=image_path,
                             image_id=image_meta['id'],
                             user_id=instance['user_id'],
                             project_id=instance['project_id']
                        )

        return [image_meta['id'], image_path]

    def _inject_into_image(self, context, node, instance, network_info,
            injected_files=None, admin_password=None):
        """Inject last-mile configuration into instances image

        Much of this method is a hack around DHCP and cloud-init
        not working together with baremetal provisioning yet.

        """
        # NOTE(deva): We assume that if we're not using a kernel,
        #             then the target partition is the first partition
        partition = None
        if not instance['kernel_id']:
            partition = "1"

        ssh_key = None
        if 'key_data' in instance and instance['key_data']:
            ssh_key = str(instance['key_data'])

        if injected_files is None:
            injected_files = []
        else:
            # NOTE(deva): copy so we dont modify the original
            injected_files = list(injected_files)

        net_config = build_network_config(network_info)

        if instance['hostname']:
            injected_files.append(('/etc/hostname', instance['hostname']))

        LOG.debug(_("Injecting files into image for instance %(name)s") %
                        {'name': instance['name']})

        bm_utils.inject_into_image(
                    image=get_image_file_path(instance),
                    key=ssh_key,
                    net=net_config,
                    metadata=instance['metadata'],
                    admin_password=admin_password,
                    files=injected_files,
                    partition=partition,
                )

    def cache_images(self, context, node, instance,
            admin_password, image_meta, injected_files, network_info):
        """Prepare all the images for this instance."""
        instance_type = self.virtapi.flavor_get(
            context, instance['instance_type_id'])
        tftp_image_info = get_tftp_image_info(instance, instance_type)
        self._cache_tftp_images(context, instance, tftp_image_info)

        self._cache_image(context, instance, image_meta)
        if CONF.baremetal.use_file_injection:
            self._inject_into_image(context, node, instance, network_info,
                   injected_files, admin_password)

    def destroy_images(self, context, node, instance):
        """Delete instance's image file."""
        bm_utils.unlink_without_raise(get_image_file_path(instance))
        bm_utils.rmtree_without_raise(get_image_dir_path(instance))

    def activate_bootloader(self, context, node, instance, network_info):
        """Configure PXE boot loader for an instance

        Kernel and ramdisk images are downloaded by cache_tftp_images,
        and stored in /tftpboot/{uuid}/

        This method writes the instances config file, and then creates
        symlinks for each MAC address in the instance.

        By default, the complete layout looks like this:

        /tftpboot/
            ./{uuid}/
                 kernel
                 ramdisk
                 deploy_kernel
                 deploy_ramdisk
                 config
            ./pxelinux.cfg/
                 {mac} -> ../{uuid}/config
        """
        instance_type = self.virtapi.flavor_get(
            context, instance['instance_type_id'])
        image_info = get_tftp_image_info(instance, instance_type)
        (root_mb, swap_mb, ephemeral_mb) = get_partition_sizes(instance)
        pxe_config_file_path = get_pxe_config_file_path(instance)
        image_file_path = get_image_file_path(instance)

        deployment_key = bm_utils.random_alnum(32)
        deployment_iscsi_iqn = "iqn-%s" % instance['uuid']
        db.bm_node_update(context, node['id'],
                {'deploy_key': deployment_key,
                 'image_path': image_file_path,
                 'pxe_config_path': pxe_config_file_path,
                 'root_mb': root_mb,
                 'swap_mb': swap_mb,
                 'ephemeral_mb': ephemeral_mb})
        pxe_config = build_pxe_config(
                    node['id'],
                    deployment_key,
                    deployment_iscsi_iqn,
                    image_info['deploy_kernel'][1],
                    image_info['deploy_ramdisk'][1],
                    image_info['kernel'][1],
                    image_info['ramdisk'][1],
                    network_info,
                )
        bm_utils.write_to_file(pxe_config_file_path, pxe_config)

        macs = self._collect_mac_addresses(context, node)
        for mac in macs:
            mac_path = get_pxe_mac_path(mac)
            bm_utils.unlink_without_raise(mac_path)
            bm_utils.create_link_without_raise(pxe_config_file_path, mac_path)

    def deactivate_bootloader(self, context, node, instance):
        """Delete PXE bootloader images and config."""
        try:
            db.bm_node_update(context, node['id'],
                    {'deploy_key': None,
                     'image_path': None,
                     'pxe_config_path': None,
                     'root_mb': 0,
                     'swap_mb': 0})
        except exception.NodeNotFound:
            pass

        # NOTE(danms): the instance_type extra_specs do not need to be
        # present/correct at deactivate time, so pass something empty
        # to avoid an extra lookup
        instance_type = dict(extra_specs={
            'baremetal:deploy_ramdisk_id': 'ignore',
            'baremetal:deploy_kernel_id': 'ignore'})
        try:
            image_info = get_tftp_image_info(instance, instance_type)
        except exception.NovaException:
            pass
        else:
            for label in image_info.keys():
                (uuid, path) = image_info[label]
                bm_utils.unlink_without_raise(path)

        bm_utils.unlink_without_raise(get_pxe_config_file_path(instance))
        try:
            macs = self._collect_mac_addresses(context, node)
        except db_exc.DBError:
            pass
        else:
            for mac in macs:
                bm_utils.unlink_without_raise(get_pxe_mac_path(mac))

        bm_utils.rmtree_without_raise(
                os.path.join(CONF.baremetal.tftp_root, instance['uuid']))

    def activate_node(self, context, node, instance):
        """Wait for PXE deployment to complete."""

        locals = {'error': '', 'started': False}

        def _wait_for_deploy():
            """Called at an interval until the deployment completes."""
            try:
                row = db.bm_node_get(context, node['id'])
                if instance['uuid'] != row.get('instance_uuid'):
                    locals['error'] = _("Node associated with another instance"
                                        " while waiting for deploy of %s")
                    raise loopingcall.LoopingCallDone()

                status = row.get('task_state')
                if (status == baremetal_states.DEPLOYING
                        and locals['started'] == False):
                    LOG.info(_("PXE deploy started for instance %s")
                                % instance['uuid'])
                    locals['started'] = True
                elif status in (baremetal_states.DEPLOYDONE,
                                baremetal_states.ACTIVE):
                    LOG.info(_("PXE deploy completed for instance %s")
                                % instance['uuid'])
                    raise loopingcall.LoopingCallDone()
                elif status == baremetal_states.DEPLOYFAIL:
                    locals['error'] = _("PXE deploy failed for instance %s")
            except exception.NodeNotFound:
                locals['error'] = _("Baremetal node deleted while waiting "
                                    "for deployment of instance %s")

            if (CONF.baremetal.pxe_deploy_timeout and
                    timeutils.utcnow() > expiration):
                locals['error'] = _("Timeout reached while waiting for "
                                     "PXE deploy of instance %s")
            if locals['error']:
                raise loopingcall.LoopingCallDone()

        expiration = timeutils.utcnow() + datetime.timedelta(
                            seconds=CONF.baremetal.pxe_deploy_timeout)
        timer = loopingcall.FixedIntervalLoopingCall(_wait_for_deploy)
        timer.start(interval=1).wait()

        if locals['error']:
            raise exception.InstanceDeployFailure(
                    locals['error'] % instance['uuid'])

    def deactivate_node(self, context, node, instance):
        pass
