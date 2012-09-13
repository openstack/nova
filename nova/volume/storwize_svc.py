# vim: tabstop=4 shiftwidth=4 softtabstop=4

# Copyright (c) 2012 IBM, Inc.
# Copyright (c) 2012 OpenStack LLC.
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
# Authors:
#   Ronen Kat <ronenkat@il.ibm.com>
#   Avishay Traeger <avishay@il.ibm.com>

"""
Volume driver for IBM Storwize V7000 and SVC storage systems.

Notes:
1. If you specify both a password and a key file, this driver will use the
   key file only.
2. When using a key file for authentication, it is up to the user or
   system administrator to store the private key in a safe manner.
3. The defaults for creating volumes are "-rsize 2% -autoexpand
   -grainsize 256 -warning 0".  These can be changed in the configuration
   file or by using volume types(recommended only for advanced users).

Limitations:
1. The driver was not tested with SVC or clustered configurations of Storwize
   V7000.
2. The driver expects CLI output in English, error messages may be in a
   localized format.
"""

import random
import re
import string
import time

from nova import exception
from nova import flags
from nova.openstack.common import cfg
from nova.openstack.common import excutils
from nova.openstack.common import log as logging
from nova.volume import san

LOG = logging.getLogger(__name__)

storwize_svc_opts = [
    cfg.StrOpt('storwize_svc_volpool_name',
               default='volpool',
               help='Storage system storage pool for volumes'),
    cfg.StrOpt('storwize_svc_vol_rsize',
               default='2%',
               help='Storage system space-efficiency parameter for volumes'),
    cfg.StrOpt('storwize_svc_vol_warning',
               default='0',
               help='Storage system threshold for volume capacity warnings'),
    cfg.BoolOpt('storwize_svc_vol_autoexpand',
               default=True,
               help='Storage system autoexpand parameter for volumes '
                    '(True/False)'),
    cfg.StrOpt('storwize_svc_vol_grainsize',
               default='256',
               help='Storage system grain size parameter for volumes '
                    '(32/64/128/256)'),
    cfg.BoolOpt('storwize_svc_vol_compression',
               default=False,
               help='Storage system compression option for volumes'),
    cfg.BoolOpt('storwize_svc_vol_easytier',
               default=True,
               help='Enable Easy Tier for volumes'),
    cfg.StrOpt('storwize_svc_flashcopy_timeout',
               default='120',
               help='Maximum number of seconds to wait for FlashCopy to be '
                    'prepared. Maximum value is 600 seconds (10 minutes).'),
]

FLAGS = flags.FLAGS
FLAGS.register_opts(storwize_svc_opts)


class StorwizeSVCDriver(san.SanISCSIDriver):
    """IBM Storwize V7000 and SVC iSCSI volume driver."""

    def __init__(self, *args, **kwargs):
        super(StorwizeSVCDriver, self).__init__(*args, **kwargs)
        self.iscsi_ipv4_conf = None
        self.iscsi_ipv6_conf = None

        # Build cleanup transaltion tables for hosts names to follow valid
        # host names for Storwizew V7000 and SVC storage systems.
        invalid_ch_in_host = ''
        for num in range(0, 128):
            ch = chr(num)
            if ((not ch.isalnum()) and (ch != ' ') and (ch != '.')
                    and (ch != '-') and (ch != '_')):
                invalid_ch_in_host = invalid_ch_in_host + ch
        self._string_host_name_filter = string.maketrans(invalid_ch_in_host,
                                                '-' * len(invalid_ch_in_host))

        self._unicode_host_name_filter = dict((ord(unicode(char)), u'-')
                                         for char in invalid_ch_in_host)

    def _get_hdr_dic(self, header, row, delim):
        """Return CLI row data as a dictionary indexed by names from header.

        Create a dictionary object from the data row string using the header
        string. The strings are converted to columns using the delimiter in
        delim.
        """

        attributes = header.split(delim)
        values = row.split(delim)
        self._driver_assert(len(values) == len(attributes),
            _('_get_hdr_dic: attribute headers and values do not match.\n '
              'Headers: %(header)s\n Values: %(row)s')
                % {'header': str(header),
                   'row': str(row)})
        dic = {}
        for attribute, value in map(None, attributes, values):
            dic[attribute] = value
        return dic

    def _driver_assert(self, assert_condition, exception_message):
        """Internal assertion mechanism for CLI output."""
        if not assert_condition:
            LOG.error(exception_message)
            raise exception.VolumeBackendAPIException(data=exception_message)

    def check_for_setup_error(self):
        """Check that we have all configuration details from the storage."""

        LOG.debug(_('enter: check_for_setup_error'))

        # Validate that the pool exists
        ssh_cmd = 'lsmdiskgrp -delim ! -nohdr'
        out, err = self._run_ssh(ssh_cmd)
        self._driver_assert(len(out) > 0,
            _('check_for_setup_error: failed with unexpected CLI output.\n '
              'Command: %(cmd)s\n stdout: %(out)s\n stderr: %(err)s')
                % {'cmd': ssh_cmd,
                   'out': str(out),
                   'err': str(err)})
        search_text = '!%s!' % FLAGS.storwize_svc_volpool_name
        if search_text not in out:
            raise exception.InvalidInput(
                    reason=(_('pool %s doesn\'t exist')
                        % FLAGS.storwize_svc_volpool_name))

        storage_nodes = {}
        # Get the iSCSI names of the Storwize/SVC nodes
        ssh_cmd = 'svcinfo lsnode -delim !'
        out, err = self._run_ssh(ssh_cmd)
        self._driver_assert(len(out) > 0,
            _('check_for_setup_error: failed with unexpected CLI output.\n '
              'Command: %(cmd)s\n stdout: %(out)s\n stderr: %(err)s')
                % {'cmd': ssh_cmd,
                   'out': str(out),
                   'err': str(err)})

        nodes = out.strip().split('\n')
        self._driver_assert(len(nodes) > 0,
            _('check_for_setup_error: failed with unexpected CLI output.\n '
              'Command: %(cmd)s\n stdout: %(out)s\n stderr: %(err)s')
                % {'cmd': ssh_cmd,
                   'out': str(out),
                   'err': str(err)})
        header = nodes.pop(0)
        for node_line in nodes:
            try:
                node_data = self._get_hdr_dic(header, node_line, '!')
            except exception.VolumeBackendAPIException as e:
                with excutils.save_and_reraise_exception():
                    LOG.error(_('check_for_setup_error: '
                                'failed with unexpected CLI output.\n '
                                'Command: %(cmd)s\n '
                                'stdout: %(out)s\n stderr: %(err)s\n')
                              % {'cmd': ssh_cmd,
                                 'out': str(out),
                                 'err': str(err)})
            node = {}
            try:
                node['id'] = node_data['id']
                node['name'] = node_data['name']
                node['iscsi_name'] = node_data['iscsi_name']
                node['status'] = node_data['status']
                node['ipv4'] = []
                node['ipv6'] = []
                if node['iscsi_name'] != '':
                    storage_nodes[node['id']] = node
            except KeyError as e:
                LOG.error(_('Did not find expected column name in '
                            'svcinfo lsnode: %s') % str(e))
                exception_message = (
                    _('check_for_setup_error: Unexpected CLI output.\n '
                      'Details: %(msg)s\n'
                      'Command: %(cmd)s\n '
                      'stdout: %(out)s\n stderr: %(err)s')
                            % {'msg': str(e),
                               'cmd': ssh_cmd,
                               'out': str(out),
                               'err': str(err)})
                raise exception.VolumeBackendAPIException(
                        data=exception_message)

        # Get the iSCSI IP addresses of the Storwize/SVC nodes
        ssh_cmd = 'lsportip -delim !'
        out, err = self._run_ssh(ssh_cmd)
        self._driver_assert(len(out) > 0,
            _('check_for_setup_error: failed with unexpected CLI output.\n '
              'Command: %(cmd)s\n '
              'stdout: %(out)s\n stderr: %(err)s')
                            % {'cmd': ssh_cmd,
                               'out': str(out),
                               'err': str(err)})

        portips = out.strip().split('\n')
        self._driver_assert(len(portips) > 0,
            _('check_for_setup_error: failed with unexpected CLI output.\n '
              'Command: %(cmd)s\n stdout: %(out)s\n stderr: %(err)s')
                % {'cmd': ssh_cmd,
                   'out': str(out),
                   'err': str(err)})
        header = portips.pop(0)
        for portip_line in portips:
            try:
                port_data = self._get_hdr_dic(header, portip_line, '!')
            except exception.VolumeBackendAPIException as e:
                with excutils.save_and_reraise_exception():
                    LOG.error(_('check_for_setup_error: '
                                'failed with unexpected CLI output.\n '
                                'Command: %(cmd)s\n '
                                'stdout: %(out)s\n stderr: %(err)s\n')
                              % {'cmd': ssh_cmd,
                                 'out': str(out),
                                 'err': str(err)})
            try:
                port_node_id = port_data['node_id']
                port_ipv4 = port_data['IP_address']
                port_ipv6 = port_data['IP_address_6']
            except KeyError as e:
                LOG.error(_('Did not find expected column name in '
                            'lsportip: %s') % str(e))
                exception_message = (
                    _('check_for_setup_error: Unexpected CLI output.\n '
                      'Details: %(msg)s\n'
                      'Command: %(cmd)s\n '
                      'stdout: %(out)s\n stderr: %(err)s')
                            % {'msg': str(e),
                               'cmd': ssh_cmd,
                               'out': str(out),
                               'err': str(err)})
                raise exception.VolumeBackendAPIException(
                        data=exception_message)

            if port_node_id in storage_nodes:
                node = storage_nodes[port_node_id]
                if len(port_ipv4) > 0:
                    node['ipv4'].append(port_ipv4)
                if len(port_ipv6) > 0:
                    node['ipv6'].append(port_ipv6)
            else:
                raise exception.VolumeBackendAPIException(
                        data=_('check_for_setup_error: '
                               'fail to storage configuration: unknown '
                               'storage node %(node_id)s from CLI output.\n '
                                'stdout: %(out)s\n stderr: %(err)s\n')
                              % {'node_id': port_node_id,
                                 'out': str(out),
                                 'err': str(err)})

        iscsi_ipv4_conf = []
        iscsi_ipv6_conf = []
        for node_key in storage_nodes:
            node = storage_nodes[node_key]
            if 'ipv4' in node and len(node['iscsi_name']) > 0:
                iscsi_ipv4_conf.append({'iscsi_name': node['iscsi_name'],
                                        'ip': node['ipv4'],
                                        'node_id': node['id']})
            if 'ipv6' in node and len(node['iscsi_name']) > 0:
                iscsi_ipv6_conf.append({'iscsi_name': node['iscsi_name'],
                                        'ip': node['ipv6'],
                                        'node_id': node['id']})
            if (len(node['ipv4']) == 0) and (len(node['ipv6']) == 0):
                raise exception.VolumeBackendAPIException(
                        data=_('check_for_setup_error: '
                                'fail to storage configuration: storage '
                                'node %s has no IP addresses configured')
                                % node['id'])

        # Make sure we have at least one IPv4 address with a iSCSI name
        # TODO(ronenkat) need to expand this to support IPv6
        self._driver_assert(len(iscsi_ipv4_conf) > 0,
            _('could not obtain IP address and iSCSI name from the storage. '
              'Please verify that the storage is configured for iSCSI.\n '
              'Storage nodes: %(nodes)s\n portips: %(portips)s')
                % {'nodes': nodes, 'portips': portips})

        self.iscsi_ipv4_conf = iscsi_ipv4_conf
        self.iscsi_ipv6_conf = iscsi_ipv6_conf

        LOG.debug(_('leave: check_for_setup_error'))

    def _check_num_perc(self, value):
        """Return True if value is either a number or a percentage."""
        if value.endswith('%'):
            value = value[0:-1]
        return value.isdigit()

    def _check_flags(self):
        """Ensure that the flags are set properly."""

        required_flags = ['san_ip', 'san_ssh_port', 'san_login',
                          'storwize_svc_volpool_name']
        for flag in required_flags:
            if not getattr(FLAGS, flag, None):
                raise exception.InvalidInput(
                        reason=_('%s is not set') % flag)

        # Ensure that either password or keyfile were set
        if not (FLAGS.san_password or FLAGS.san_private_key):
            raise exception.InvalidInput(
                reason=_('Password or SSH private key is required for '
                         'authentication: set either san_password or '
                         'san_private_key option'))

        # Check that rsize is a number or percentage
        rsize = FLAGS.storwize_svc_vol_rsize
        if not self._check_num_perc(rsize) and (rsize != '-1'):
            raise exception.InvalidInput(
                reason=_('Illegal value specified for storwize_svc_vol_rsize: '
                         'set to either a number or a percentage'))

        # Check that warning is a number or percentage
        warning = FLAGS.storwize_svc_vol_warning
        if not self._check_num_perc(warning):
            raise exception.InvalidInput(
                reason=_('Illegal value specified for '
                         'storwize_svc_vol_warning: '
                         'set to either a number or a percentage'))

        # Check that grainsize is 32/64/128/256
        grainsize = FLAGS.storwize_svc_vol_grainsize
        if grainsize not in ['32', '64', '128', '256']:
            raise exception.InvalidInput(
                reason=_('Illegal value specified for '
                         'storwize_svc_vol_grainsize: set to either '
                         '\'32\', \'64\', \'128\', or \'256\''))

        # Check that flashcopy_timeout is numeric and 32/64/128/256
        flashcopy_timeout = FLAGS.storwize_svc_flashcopy_timeout
        if not (flashcopy_timeout.isdigit() and int(flashcopy_timeout) > 0 and
            int(flashcopy_timeout) <= 600):
            raise exception.InvalidInput(
                reason=_('Illegal value %s specified for '
                         'storwize_svc_flashcopy_timeout: '
                         'valid values are between 0 and 600')
                                         % flashcopy_timeout)

        # Check that rsize is set
        volume_compression = FLAGS.storwize_svc_vol_compression
        if ((volume_compression == True) and
                (FLAGS.storwize_svc_vol_rsize == '-1')):
            raise exception.InvalidInput(
                reason=_('If compression is set to True, rsize must '
                         'also be set (not equal to -1)'))

    def do_setup(self, context):
        """Validate the flags."""
        LOG.debug(_('enter: do_setup'))
        self._check_flags()
        LOG.debug(_('leave: do_setup'))

    def create_volume(self, volume):
        """Create a new volume - uses the internal method."""
        return self._create_volume(volume, units='gb')

    def _create_volume(self, volume, units='gb'):
        """Create a new volume."""

        name = volume['name']
        model_update = None

        LOG.debug(_('enter: create_volume: volume %s ') % name)

        size = int(volume['size'])

        if FLAGS.storwize_svc_vol_autoexpand == True:
            autoex = '-autoexpand'
        else:
            autoex = ''

        if FLAGS.storwize_svc_vol_easytier == True:
            easytier = '-easytier on'
        else:
            easytier = '-easytier off'

        # Set space-efficient options
        if FLAGS.storwize_svc_vol_rsize.strip() == '-1':
            ssh_cmd_se_opt = ''
        else:
            ssh_cmd_se_opt = ('-rsize %(rsize)s %(autoex)s -warning %(warn)s' %
                        {'rsize': FLAGS.storwize_svc_vol_rsize,
                         'autoex': autoex,
                         'warn': FLAGS.storwize_svc_vol_warning})
            if FLAGS.storwize_svc_vol_compression:
                ssh_cmd_se_opt = ssh_cmd_se_opt + ' -compressed'
            else:
                ssh_cmd_se_opt = ssh_cmd_se_opt + (' -grainsize %(grain)s' %
                       {'grain': FLAGS.storwize_svc_vol_grainsize})

        ssh_cmd = ('mkvdisk -name %(name)s -mdiskgrp %(mdiskgrp)s '
                    '-iogrp 0 -size %(size)s -unit '
                    '%(unit)s %(easytier)s %(ssh_cmd_se_opt)s'
                    % {'name': name,
                    'mdiskgrp': FLAGS.storwize_svc_volpool_name,
                    'size': size, 'unit': units, 'easytier': easytier,
                    'ssh_cmd_se_opt': ssh_cmd_se_opt})
        out, err = self._run_ssh(ssh_cmd)
        self._driver_assert(len(out.strip()) > 0,
            _('create volume %(name)s - did not find '
              'success message in CLI output.\n '
              'stdout: %(out)s\n stderr: %(err)s')
                % {'name': name, 'out': str(out), 'err': str(err)})

        # Ensure that the output is as expected
        match_obj = re.search('Virtual Disk, id \[([0-9]+)\], '
                                'successfully created', out)
        # Make sure we got a "successfully created" message with vdisk id
        self._driver_assert(match_obj is not None,
            _('create volume %(name)s - did not find '
              'success message in CLI output.\n '
              'stdout: %(out)s\n stderr: %(err)s')
                % {'name': name, 'out': str(out), 'err': str(err)})

        LOG.debug(_('leave: create_volume: volume %(name)s ') % {'name': name})

    def delete_volume(self, volume):
        self._delete_volume(volume, False)

    def _delete_volume(self, volume, force_opt):
        """Driver entry point for destroying existing volumes."""

        name = volume['name']
        LOG.debug(_('enter: delete_volume: volume %(name)s ') % {'name': name})

        if force_opt:
            force_flag = '-force'
        else:
            force_flag = ''

        volume_defined = self._is_volume_defined(name)
        # Try to delete volume only if found on the storage
        if volume_defined:
            out, err = self._run_ssh('rmvdisk %(force)s %(name)s'
                                    % {'force': force_flag,
                                       'name': name})
            # No output should be returned from rmvdisk
            self._driver_assert(len(out.strip()) == 0,
                _('delete volume %(name)s - non empty output from CLI.\n '
                  'stdout: %(out)s\n stderr: %(err)s')
                                % {'name': name,
                                   'out': str(out),
                                   'err': str(err)})
        else:
            # Log that volume does not exist
            LOG.info(_('warning: tried to delete volume %(name)s but '
                       'it does not exist.') % {'name': name})

        LOG.debug(_('leave: delete_volume: volume %(name)s ') % {'name': name})

    def ensure_export(self, context, volume):
        """Check that the volume exists on the storage.

        The system does not "export" volumes as a Linux iSCSI target does,
        and therefore we just check that the volume exists on the storage.
        """
        volume_defined = self._is_volume_defined(volume['name'])
        if not volume_defined:
            LOG.error(_('ensure_export: volume %s not found on storage')
                       % volume['name'])

    def create_export(self, context, volume):
        model_update = None
        return model_update

    def remove_export(self, context, volume):
        pass

    def check_for_export(self, context, volume_id):
        raise NotImplementedError()

    def initialize_connection(self, volume, connector):
        """Perform the necessary work so that an iSCSI connection can be made.

        To be able to create an iSCSI connection from a given iSCSI name to a
        volume, we must:
        1. Translate the given iSCSI name to a host name
        2. Create new host on the storage system if it does not yet exist
        2. Map the volume to the host if it is not already done
        3. Return iSCSI properties, including the IP address of the preferred
           node for this volume and the LUN number.
        """
        LOG.debug(_('enter: initialize_connection: volume %(vol)s with '
                    'connector %(conn)s') % {'vol': str(volume),
                    'conn': str(connector)})

        initiator_name = connector['initiator']
        volume_name = volume['name']

        host_name = self._get_host_from_iscsiname(initiator_name)
        # Check if a host is defined for the iSCSI initiator name
        if host_name is None:
            # Host does not exist - add a new host to Storwize/SVC
            host_name = self._create_new_host('host%s' % initiator_name,
                                               initiator_name)
            # Verify that create_new_host succeeded
            self._driver_assert(host_name is not None,
                _('_create_new_host failed to return the host name.'))

        lun_id = self._map_vol_to_host(volume_name, host_name)

        # Get preferred path
        # Only IPv4 for now because lack of OpenStack support
        # TODO(ronenkat): Add support for IPv6
        volume_attributes = self._get_volume_attributes(volume_name)
        if (volume_attributes is not None and
            'preferred_node_id' in volume_attributes):
            preferred_node = volume_attributes['preferred_node_id']
            preferred_node_entry = None
            for node in self.iscsi_ipv4_conf:
                if node['node_id'] == preferred_node:
                    preferred_node_entry = node
                    break
            if preferred_node_entry is None:
                preferred_node_entry = self.iscsi_ipv4_conf[0]
                LOG.error(_('initialize_connection: did not find preferred '
                            'node %(node)s for volume %(vol)s in iSCSI '
                            'configuration') % {'node': preferred_node,
                            'vol': volume_name})
        else:
            # Get 1st node
            preferred_node_entry = self.iscsi_ipv4_conf[0]
            LOG.error(
                _('initialize_connection: did not find a preferred node '
                  'for volume %s in iSCSI configuration') % volume_name)

        properties = {}
        # We didn't use iSCSI discover, as in server-based iSCSI
        properties['target_discovered'] = False
        # We take the first IP address for now. Ideally, OpenStack will
        # support multipath for improved performance.
        properties['target_portal'] = ('%s:%s' %
                (preferred_node_entry['ip'][0], '3260'))
        properties['target_iqn'] = preferred_node_entry['iscsi_name']
        properties['target_lun'] = lun_id
        properties['volume_id'] = volume['id']

        LOG.debug(_('leave: initialize_connection:\n volume: %(vol)s\n '
                    'connector %(conn)s\n properties: %(prop)s')
                  % {'vol': str(volume),
                    'conn': str(connector),
                    'prop': str(properties)})

        return {'driver_volume_type': 'iscsi', 'data': properties, }

    def terminate_connection(self, volume, connector):
        """Cleanup after an iSCSI connection has been terminated.

        When we clean up a terminated connection between a given iSCSI name
        and volume, we:
        1. Translate the given iSCSI name to a host name
        2. Remove the volume-to-host mapping if it exists
        3. Delete the host if it has no more mappings (hosts are created
           automatically by this driver when mappings are created)
        """
        LOG.debug(_('enter: terminate_connection: volume %(vol)s with '
                    'connector %(conn)s') % {'vol': str(volume),
                    'conn': str(connector)})

        vol_name = volume['name']
        initiator_name = connector['initiator']
        host_name = self._get_host_from_iscsiname(initiator_name)
        # Verify that _get_host_from_iscsiname returned the host.
        # This should always succeed as we terminate an existing connection.
        self._driver_assert(host_name is not None,
            _('_get_host_from_iscsiname failed to return the host name '
              'for iscsi name %s') % initiator_name)

        # Check if vdisk-host mapping exists, remove if it does
        mapping_data = self._get_hostvdisk_mappings(host_name)
        if vol_name in mapping_data:
            out, err = self._run_ssh('rmvdiskhostmap -host %s %s'
                                     % (host_name, vol_name))
            # Verify CLI behaviour - no output is returned from
            # rmvdiskhostmap
            self._driver_assert(len(out.strip()) == 0,
                _('delete mapping of volume %(vol)s to host %(host)s '
                  '- non empty output from CLI.\n '
                  'stdout: %(out)s\n stderr: %(err)s')
                                 % {'vol': vol_name,
                                    'host': host_name,
                                    'out': str(out),
                                    'err': str(err)})
            del mapping_data[vol_name]
        else:
            LOG.error(_('terminate_connection: no mapping of volume '
                        '%(vol)s to host %(host)s found') %
                        {'vol': vol_name, 'host': host_name})

        # If this host has no more mappings, delete it
        if not mapping_data:
            self._delete_host(host_name)

        LOG.debug(_('leave: terminate_connection: volume %(vol)s with '
                    'connector %(conn)s') % {'vol': str(volume),
                    'conn': str(connector)})

    def _flashcopy_cleanup(self, fc_map_id, source, target):
        """Clean up a failed FlashCopy operation."""

        try:
            out, err = self._run_ssh('stopfcmap -force %s' % fc_map_id)
            out, err = self._run_ssh('rmfcmap -force %s' % fc_map_id)
        except exception.ProcessExecutionError as e:
            LOG.error(_('_run_flashcopy: fail to cleanup failed FlashCopy '
                        'mapping %(fc_map_id)% '
                        'from %(source)s to %(target)s.\n'
                        'stdout: %(out)s\n stderr: %(err)s')
                        % {'fc_map_id': fc_map_id,
                           'source': source,
                           'target': target,
                           'out': e.stdout,
                           'err': e.stderr})

    def _run_flashcopy(self, source, target):
        """Create a FlashCopy mapping from the source to the target."""

        LOG.debug(
            _('enter: _run_flashcopy: execute FlashCopy from source '
              '%(source)s to target %(target)s') % {'source': source,
              'target': target})

        fc_map_cli_cmd = ('mkfcmap -source %s -target %s -autodelete '
                            '-cleanrate 0' % (source, target))
        out, err = self._run_ssh(fc_map_cli_cmd)
        self._driver_assert(len(out.strip()) > 0,
            _('create FC mapping from %(source)s to %(target)s - '
              'did not find success message in CLI output.\n'
              ' stdout: %(out)s\n stderr: %(err)s\n')
                            % {'source': source,
                                'target': target,
                                'out': str(out),
                                'err': str(err)})

        # Ensure that the output is as expected
        match_obj = re.search('FlashCopy Mapping, id \[([0-9]+)\], '
                                'successfully created', out)
        # Make sure we got a "successfully created" message with vdisk id
        self._driver_assert(match_obj is not None,
            _('create FC mapping from %(source)s to %(target)s - '
              'did not find success message in CLI output.\n'
              ' stdout: %(out)s\n stderr: %(err)s\n')
                            % {'source': source,
                               'target': target,
                               'out': str(out),
                               'err': str(err)})

        try:
            fc_map_id = match_obj.group(1)
            self._driver_assert(fc_map_id is not None,
                _('create FC mapping from %(source)s to %(target)s - '
                  'did not find mapping id in CLI output.\n'
                  ' stdout: %(out)s\n stderr: %(err)s\n')
                            % {'source': source,
                               'target': target,
                               'out': str(out),
                               'err': str(err)})
        except IndexError:
            self._driver_assert(False,
                _('create FC mapping from %(source)s to %(target)s - '
                  'did not find mapping id in CLI output.\n'
                  ' stdout: %(out)s\n stderr: %(err)s\n')
                            % {'source': source,
                               'target': target,
                               'out': str(out),
                               'err': str(err)})
        try:
            out, err = self._run_ssh('prestartfcmap %s' % fc_map_id)
        except exception.ProcessExecutionError as e:
            with excutils.save_and_reraise_exception():
                LOG.error(_('_run_flashcopy: fail to prepare FlashCopy '
                            'from %(source)s to %(target)s.\n'
                            'stdout: %(out)s\n stderr: %(err)s')
                            % {'source': source,
                               'target': target,
                               'out': e.stdout,
                               'err': e.stderr})
                self._flashcopy_cleanup(fc_map_id, source, target)

        mapping_ready = False
        wait_time = 5
        # Allow waiting of up to timeout (set as parameter)
        max_retries = (int(FLAGS.storwize_svc_flashcopy_timeout)
                        / wait_time) + 1
        for try_number in range(1, max_retries):
            mapping_attributes = self._get_flashcopy_mapping_attributes(
                                                            fc_map_id)
            if (mapping_attributes is None or
                    'status' not in mapping_attributes):
                break
            if mapping_attributes['status'] == 'prepared':
                mapping_ready = True
                break
            elif mapping_attributes['status'] != 'preparing':
                # Unexpected mapping status
                exception_msg = (_('unexecpted mapping status %(status)s '
                                   'for mapping %(id)s. Attributes: '
                                   '%(attr)s')
                                 % {'status': mapping_attributes['status'],
                                    'id': fc_map_id,
                                    'attr': mapping_attributes})
                raise exception.VolumeBackendAPIException(
                        data=exception_msg)
            # Need to wait for mapping to be prepared, wait a few seconds
            time.sleep(wait_time)

        if not mapping_ready:
            exception_msg = (_('mapping %(id)s prepare failed to complete '
                               'within the alloted %(to)s seconds timeout. '
                               'Terminating') % {'id': fc_map_id,
                               'to': FLAGS.storwize_svc_flashcopy_timeout})
            LOG.error(_('_run_flashcopy: fail to start FlashCopy '
                        'from %(source)s to %(target)s with '
                        'exception %(ex)s')
                        % {'source': source,
                           'target': target,
                           'ex': exception_msg})
            self._flashcopy_cleanup(fc_map_id, source, target)
            raise exception.InvalidSnapshot(
                reason=_('_run_flashcopy: %s') % exception_msg)

        try:
            out, err = self._run_ssh('startfcmap %s' % fc_map_id)
        except exception.ProcessExecutionError as e:
            with excutils.save_and_reraise_exception():
                LOG.error(_('_run_flashcopy: fail to start FlashCopy '
                            'from %(source)s to %(target)s.\n'
                            'stdout: %(out)s\n stderr: %(err)s')
                            % {'source': source,
                               'target': target,
                               'out': e.stdout,
                               'err': e.stderr})
                self._flashcopy_cleanup(fc_map_id, source, target)

        LOG.debug(_('leave: _run_flashcopy: FlashCopy started from '
                    '%(source)s to %(target)s') % {'source': source,
                    'target': target})

    def create_volume_from_snapshot(self, volume, snapshot):
        """Create a new snapshot from volume."""

        source_volume = snapshot['name']
        tgt_volume = volume['name']

        LOG.debug(_('enter: create_volume_from_snapshot: snapshot %(tgt)s '
                    'from volume %(src)s') % {'tgt': tgt_volume,
                    'src': source_volume})

        src_volume_attributes = self._get_volume_attributes(source_volume)
        if src_volume_attributes is None:
            exception_msg = (_('create_volume_from_snapshot: source volume %s '
                               'does not exist') % source_volume)
            LOG.error(exception_msg)
            raise exception.SnapshotNotFound(exception_msg,
                                           volume_id=source_volume)

        self._driver_assert('capacity' in src_volume_attributes,
                _('create_volume_from_snapshot: cannot get source '
                  'volume %(src)s capacity from volume attributes '
                  '%(attr)s') % {'src': source_volume,
                                 'attr': src_volume_attributes})
        src_volume_size = src_volume_attributes['capacity']

        tgt_volume_attributes = self._get_volume_attributes(tgt_volume)
        # Does the snapshot target exist?
        if tgt_volume_attributes is not None:
            exception_msg = (_('create_volume_from_snapshot: target volume %s '
                               'already exists, cannot create') % tgt_volume)
            LOG.error(exception_msg)
            raise exception.InvalidSnapshot(reason=exception_msg)

        snapshot_volume = {}
        snapshot_volume['name'] = tgt_volume
        snapshot_volume['size'] = src_volume_size

        self._create_volume(snapshot_volume, units='b')

        try:
            self._run_flashcopy(source_volume, tgt_volume)
        except Exception:
            with excutils.save_and_reraise_exception():
                # Clean up newly-created snapshot if the FlashCopy failed
                self._delete_volume(snapshot_volume, True)

        LOG.debug(
            _('leave: create_volume_from_snapshot: %s created successfully')
            % tgt_volume)

    def create_snapshot(self, snapshot):
        """Create a new snapshot using FlashCopy."""

        src_volume = snapshot['volume_name']
        tgt_volume = snapshot['name']

        # Flag to keep track of created volumes in case FlashCopy
        tgt_volume_created = False

        LOG.debug(_('enter: create_snapshot: snapshot %(tgt)s from '
                    'volume %(src)s') % {'tgt': tgt_volume,
                    'src': src_volume})

        src_volume_attributes = self._get_volume_attributes(src_volume)
        if src_volume_attributes is None:
            exception_msg = (
                _('create_snapshot: source volume %s does not exist')
                % src_volume)
            LOG.error(exception_msg)
            raise exception.VolumeNotFound(exception_msg,
                                           volume_id=src_volume)

        self._driver_assert('capacity' in src_volume_attributes,
                _('create_volume_from_snapshot: cannot get source '
                  'volume %(src)s capacity from volume attributes '
                  '%(attr)s') % {'src': src_volume,
                                 'attr': src_volume_attributes})

        source_volume_size = src_volume_attributes['capacity']

        tgt_volume_attributes = self._get_volume_attributes(tgt_volume)
        # Does the snapshot target exist?
        snapshot_volume = {}
        if tgt_volume_attributes is None:
            # No, create a new snapshot volume
            snapshot_volume['name'] = tgt_volume
            snapshot_volume['size'] = source_volume_size
            self._create_volume(snapshot_volume, units='b')
            tgt_volume_created = True
        else:
            # Yes, target exists, verify exact same size as source
            self._driver_assert('capacity' in tgt_volume_attributes,
                    _('create_volume_from_snapshot: cannot get source '
                      'volume %(src)s capacity from volume attributes '
                      '%(attr)s') % {'src': tgt_volume,
                                     'attr': tgt_volume_attributes})
            target_volume_size = tgt_volume_attributes['capacity']
            if target_volume_size != source_volume_size:
                exception_msg = (
                    _('create_snapshot: source %(src)s and target '
                      'volume %(tgt)s have different capacities '
                      '(source:%(ssize)s target:%(tsize)s)') %
                        {'src': src_volume,
                         'tgt': tgt_volume,
                         'ssize': source_volume_size,
                         'tsize': target_volume_size})
                LOG.error(exception_msg)
                raise exception.InvalidSnapshot(reason=exception_msg)

        try:
            self._run_flashcopy(src_volume, tgt_volume)
        except exception.InvalidSnapshot:
            with excutils.save_and_reraise_exception():
                # Clean up newly-created snapshot if the FlashCopy failed
                if tgt_volume_created:
                    self._delete_volume(snapshot_volume, True)

        LOG.debug(_('leave: create_snapshot: %s created successfully')
                  % tgt_volume)

    def delete_snapshot(self, snapshot):
        self._delete_snapshot(snapshot, False)

    def _delete_snapshot(self, snapshot, force_opt):
        """Delete a snapshot from the storage."""
        LOG.debug(_('enter: delete_snapshot: snapshot %s') % snapshot)

        snapshot_defined = self._is_volume_defined(snapshot['name'])
        if snapshot_defined:
            if force_opt:
                self._delete_volume(snapshot, force_opt)
            else:
                self.delete_volume(snapshot)

        LOG.debug(_('leave: delete_snapshot: snapshot %s') % snapshot)

    def _get_host_from_iscsiname(self, iscsi_name):
        """List the hosts defined in the storage.

        Return the host name with the given iSCSI name, or None if there is
        no host name with that iSCSI name.
        """

        LOG.debug(_('enter: _get_host_from_iscsiname: iSCSI initiator %s')
                   % iscsi_name)

        # Get list of host in the storage
        ssh_cmd = 'lshost -delim !'
        out, err = self._run_ssh(ssh_cmd)

        if (len(out.strip()) == 0):
            return None

        err_msg = _('_get_host_from_iscsiname: '
              'failed with unexpected CLI output.\n'
              ' command: %(cmd)s\n stdout: %(out)s\n '
              'stderr: %(err)s') % {'cmd': ssh_cmd,
                                    'out': str(out),
                                    'err': str(err)}
        host_lines = out.strip().split('\n')
        self._driver_assert(len(host_lines) > 0, err_msg)
        header = host_lines.pop(0).split('!')
        self._driver_assert('name' in header, err_msg)
        name_index = header.index('name')

        hosts = map(lambda x: x.split('!')[name_index], host_lines)
        hostname = None

        # For each host, get its details and check for its iSCSI name
        for host in hosts:
            ssh_cmd = 'lshost -delim ! %s' % host
            out, err = self._run_ssh(ssh_cmd)
            self._driver_assert(len(out) > 0,
                    _('_get_host_from_iscsiname: '
                      'Unexpected response from CLI output. '
                      'Command: %(cmd)s\n stdout: %(out)s\n stderr: %(err)s')
                        % {'cmd': ssh_cmd,
                           'out': str(out),
                           'err': str(err)})
            for attrib_line in out.split('\n'):
                # If '!' not found, return the string and two empty strings
                attrib_name, foo, attrib_value = attrib_line.partition('!')
                if attrib_name == 'iscsi_name':
                    if iscsi_name == attrib_value:
                        hostname = host
                        break
            if hostname is not None:
                break

        LOG.debug(_('leave: _get_host_from_iscsiname: iSCSI initiator %s')
                   % iscsi_name)

        return hostname

    def _create_new_host(self, host_name, initiator_name):
        """Create a new host on the storage system.

        We modify the given host name, replace any invalid characters and
        adding a random suffix to avoid conflicts due to the translation. The
        host is associated with the given iSCSI initiator name.
        """

        LOG.debug(_('enter: _create_new_host: host %(name)s with iSCSI '
                    'initiator %(init)s') % {'name': host_name,
                    'init': initiator_name})

        if isinstance(host_name, unicode):
            host_name = host_name.translate(self._unicode_host_name_filter)
        elif isinstance(host_name, str):
            host_name = host_name.translate(self._string_host_name_filter)
        else:
            msg = _('_create_new_host: cannot clean host name. Host name '
                    'is not unicode or string')
            LOG.error(msg)
            raise exception.NoValidHost(reason=msg)

        # Add 5 digit random suffix to the host name to avoid
        # conflicts in host names after removing invalid characters
        # for Storwize/SVC names
        host_name = '%s_%s' % (host_name, random.randint(10000, 99999))
        out, err = self._run_ssh('mkhost -name "%s" -iscsiname "%s"'
                                 % (host_name, initiator_name))
        self._driver_assert(len(out.strip()) > 0 and
                            'successfully created' in out,
                _('create host %(name)s with iSCSI initiator %(init)s - '
                  'did not find success message in CLI output.\n '
                  'stdout: %(out)s\n stderr: %(err)s\n')
                  % {'name': host_name,
                     'init': initiator_name,
                     'out': str(out),
                     'err': str(err)})

        LOG.debug(_('leave: _create_new_host: host %(host)s with iSCSI '
                    'initiator %(init)s') % {'host': host_name,
                    'init': initiator_name})

        return host_name

    def _delete_host(self, host_name):
        """Delete a host and associated iSCSI initiator name."""

        LOG.debug(_('enter: _delete_host: host %s ') % host_name)

        # Check if host exists on system, expect to find the host
        is_defined = self._is_host_defined(host_name)
        if is_defined:
            # Delete host
            out, err = self._run_ssh('rmhost %s ' % host_name)
        else:
            LOG.info(_('warning: tried to delete host %(name)s but '
                       'it does not exist.') % {'name': host_name})

        LOG.debug(_('leave: _delete_host: host %s ') % host_name)

    def _is_volume_defined(self, volume_name):
        """Check if volume is defined."""
        LOG.debug(_('enter: _is_volume_defined: volume %s ') % volume_name)
        volume_attributes = self._get_volume_attributes(volume_name)
        LOG.debug(_('leave: _is_volume_defined: volume %(vol)s with %(str)s ')
                   % {'vol': volume_name,
                   'str': volume_attributes is not None})
        if volume_attributes is None:
            return False
        else:
            return True

    def _is_host_defined(self, host_name):
        """Check if a host is defined on the storage."""

        LOG.debug(_('enter: _is_host_defined: host %s ') % host_name)

        # Get list of hosts with the name %host_name%
        # We expect zero or one line if host does not exist,
        # two lines if it does exist, otherwise error
        out, err = self._run_ssh('lshost -filtervalue name=%s -delim !'
                                % host_name)
        if len(out.strip()) == 0:
            return False

        lines = out.strip().split('\n')
        self._driver_assert(len(lines) <= 2,
                _('_is_host_defined: Unexpected response from CLI output.\n '
                  'stdout: %(out)s\n stderr: %(err)s\n')
                % {'out': str(out),
                   'err': str(err)})

        if len(lines) == 2:
            host_info = self._get_hdr_dic(lines[0], lines[1], '!')
            host_name_from_storage = host_info['name']
            # Make sure we got the data for the right host
            self._driver_assert(host_name_from_storage == host_name,
                    _('Data received for host %(host1)s instead of host '
                      '%(host2)s.\n '
                      'stdout: %(out)s\n stderr: %(err)s\n')
                      % {'host1': host_name_from_storage,
                         'host2': host_name,
                         'out': str(out),
                         'err': str(err)})
        else:  # 0 or 1 lines
            host_name_from_storage = None

        LOG.debug(_('leave: _is_host_defined: host %(host)s with %(str)s ') % {
                   'host': host_name,
                   'str': host_name_from_storage is not None})

        if host_name_from_storage is None:
            return False
        else:
            return True

    def _get_hostvdisk_mappings(self, host_name):
        """Return the defined storage mappings for a host."""

        return_data = {}
        ssh_cmd = 'lshostvdiskmap -delim ! %s' % host_name
        out, err = self._run_ssh(ssh_cmd)

        mappings = out.strip().split('\n')
        if len(mappings) > 0:
            header = mappings.pop(0)
            for mapping_line in mappings:
                mapping_data = self._get_hdr_dic(header, mapping_line, '!')
                return_data[mapping_data['vdisk_name']] = mapping_data

        return return_data

    def _map_vol_to_host(self, volume_name, host_name):
        """Create a mapping between a volume to a host."""

        LOG.debug(_('enter: _map_vol_to_host: volume %(vol)s to '
                    'host %(host)s') % {'vol': volume_name,
                    'host': host_name})

        # Check if this volume is already mapped to this host
        mapping_data = self._get_hostvdisk_mappings(host_name)

        mapped_flag = False
        result_lun = '-1'
        if volume_name in mapping_data:
            mapped_flag = True
            result_lun = mapping_data[volume_name]['SCSI_id']
        else:
            lun_used = []
            for k, v in mapping_data.iteritems():
                lun_used.append(int(v['SCSI_id']))
            lun_used.sort()
            # Assume all luns are taken to this point, and then try to find
            # an unused one
            result_lun = str(len(lun_used))
            for index, n in enumerate(lun_used):
                if n > index:
                    result_lun = str(index)

        # Volume is not mapped to host, create a new LUN
        if not mapped_flag:
            out, err = self._run_ssh('mkvdiskhostmap -host %s -scsi %s %s'
                                    % (host_name, result_lun, volume_name))
            self._driver_assert(len(out.strip()) > 0 and
                                'successfully created' in out,
                    _('_map_vol_to_host: mapping host %(host)s to '
                      'volume %(vol)s with LUN '
                      '%(lun)s - did not find success message in CLI output. '
                      'stdout: %(out)s\n stderr: %(err)s\n')
                    % {'host': host_name,
                      'vol': volume_name,
                      'lun': result_lun,
                      'out': str(out),
                      'err': str(err)})

        LOG.debug(_('leave: _map_vol_to_host: LUN %(lun)s, volume %(vol)s, '
                    'host %(host)s') % {'lun': result_lun, 'vol': volume_name,
                    'host': host_name})

        return result_lun

    def _get_flashcopy_mapping_attributes(self, fc_map_id):
        """Return the attributes of a FlashCopy mapping.

        Returns the attributes for the specified FlashCopy mapping, or
        None if the mapping does not exist.
        An exception is raised if the information from system can not
        be parsed or matched to a single FlashCopy mapping (this case
        should not happen under normal conditions).
        """

        LOG.debug(_('enter: _get_flashcopy_mapping_attributes: mapping %s')
                   % fc_map_id)
        # Get the lunid to be used

        fc_ls_map_cmd = ('lsfcmap -filtervalue id=%s -delim !' % fc_map_id)
        out, err = self._run_ssh(fc_ls_map_cmd)
        self._driver_assert(len(out) > 0,
            _('_get_flashcopy_mapping_attributes: '
              'Unexpected response from CLI output. '
              'Command: %(cmd)s\n stdout: %(out)s\n stderr: %(err)s')
                % {'cmd': fc_ls_map_cmd,
                   'out': str(out),
                   'err': str(err)})

        # Get list of FlashCopy mappings
        # We expect zero or one line if mapping does not exist,
        # two lines if it does exist, otherwise error
        lines = out.strip().split('\n')
        self._driver_assert(len(lines) <= 2,
                 _('_get_flashcopy_mapping_attributes: '
                   'Unexpected response from CLI output. '
                   'Command: %(cmd)s\n stdout: %(out)s\n stderr: %(err)s')
                            % {'cmd': fc_ls_map_cmd,
                               'out': str(out),
                               'err': str(err)})

        if len(lines) == 2:
            attributes = self._get_hdr_dic(lines[0], lines[1], '!')
        else:  # 0 or 1 lines
            attributes = None

        LOG.debug(_('leave: _get_flashcopy_mapping_attributes: mapping '
                    '%(id)s, attributes %(attr)s') %
                   {'id': fc_map_id,
                    'attr': attributes})

        return attributes

    def _get_volume_attributes(self, volume_name):
        """Return volume attributes, or None if volume does not exist

        Exception is raised if the information from system can not be
        parsed/matched to a single volume.
        """

        LOG.debug(_('enter: _get_volume_attributes: volume %s')
                   % volume_name)
        # Get the lunid to be used

        try:
            ssh_cmd = 'lsvdisk -bytes -delim ! %s ' % volume_name
            out, err = self._run_ssh(ssh_cmd)
        except exception.ProcessExecutionError as e:
            # Didn't get details from the storage, return None
            LOG.error(_('CLI Exception output:\n command: %(cmd)s\n '
                        'stdout: %(out)s\n stderr: %(err)s') %
                      {'cmd': ssh_cmd,
                       'out': e.stdout,
                       'err': e.stderr})
            return None

        self._driver_assert(len(out) > 0,
                    ('_get_volume_attributes: '
                      'Unexpected response from CLI output. '
                      'Command: %(cmd)s\n stdout: %(out)s\n stderr: %(err)s')
                        % {'cmd': ssh_cmd,
                           'out': str(out),
                           'err': str(err)})
        attributes = {}
        for attrib_line in out.split('\n'):
            # If '!' not found, return the string and two empty strings
            attrib_name, foo, attrib_value = attrib_line.partition('!')
            if attrib_name is not None and attrib_name.strip() > 0:
                attributes[attrib_name] = attrib_value

        LOG.debug(_('leave: _get_volume_attributes:\n volume %(vol)s\n '
                    'attributes: %(attr)s')
                  % {'vol': volume_name,
                     'attr': str(attributes)})

        return attributes
