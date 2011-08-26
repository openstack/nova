# vim: tabstop=4 shiftwidth=4 softtabstop=4

# Copyright (c) 2011 Zadara Storage Inc.
# Copyright (c) 2011 OpenStack LLC.
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
VSA Simple Scheduler
"""

from nova import context
from nova import db
from nova import flags
from nova import log as logging
from nova import rpc
from nova import utils
from nova.scheduler import driver
from nova.scheduler import simple
from nova.vsa.api import VsaState
from nova.volume import volume_types

LOG = logging.getLogger('nova.scheduler.vsa')

FLAGS = flags.FLAGS
flags.DEFINE_integer('drive_type_approx_capacity_percent', 10,
                    'The percentage range for capacity comparison')
flags.DEFINE_integer('vsa_unique_hosts_per_alloc', 10,
                    'The number of unique hosts per storage allocation')
flags.DEFINE_boolean('vsa_select_unique_drives', True,
                     'Allow selection of same host for multiple drives')


def BYTES_TO_GB(bytes):
    return bytes >> 30


def GB_TO_BYTES(gb):
    return gb << 30


class VsaScheduler(simple.SimpleScheduler):
    """Implements Scheduler for volume placement."""

    def __init__(self, *args, **kwargs):
        super(VsaScheduler, self).__init__(*args, **kwargs)
        self._notify_all_volume_hosts("startup")

    def _notify_all_volume_hosts(self, event):
        rpc.fanout_cast(context.get_admin_context(),
                 FLAGS.volume_topic,
                 {"method": "notification",
                  "args": {"event": event}})

    def _qosgrp_match(self, drive_type, qos_values):

        def _compare_names(str1, str2):
            return str1.lower() == str2.lower()

        def _compare_sizes_approxim(cap_capacity, size):
            cap_capacity = BYTES_TO_GB(int(cap_capacity))
            size = int(size)
            size_perc = size * \
                FLAGS.drive_type_approx_capacity_percent / 100

            return cap_capacity >= size - size_perc and \
                   cap_capacity <= size + size_perc

        # Add more entries for additional comparisons
        compare_list = [{'cap1': 'DriveType',
                         'cap2': 'type',
                         'cmp_func': _compare_names},
                        {'cap1': 'DriveCapacity',
                         'cap2': 'size',
                         'cmp_func': _compare_sizes_approxim}]

        for cap in compare_list:
            if cap['cap1'] in qos_values.keys() and \
               cap['cap2'] in drive_type.keys() and \
               cap['cmp_func'] is not None and \
               cap['cmp_func'](qos_values[cap['cap1']],
                               drive_type[cap['cap2']]):
                pass
            else:
                return False
        return True

    def _get_service_states(self):
        return self.zone_manager.service_states

    def _filter_hosts(self, topic, request_spec, host_list=None):

        LOG.debug(_("_filter_hosts: %(request_spec)s"), locals())

        drive_type = request_spec['drive_type']
        LOG.debug(_("Filter hosts for drive type %s"), drive_type['name'])

        if host_list is None:
            host_list = self._get_service_states().iteritems()

        filtered_hosts = []     # returns list of (hostname, capability_dict)
        for host, host_dict in host_list:
            for service_name, service_dict in host_dict.iteritems():
                if service_name != topic:
                    continue

                gos_info = service_dict.get('drive_qos_info', {})
                for qosgrp, qos_values in gos_info.iteritems():
                    if self._qosgrp_match(drive_type, qos_values):
                        if qos_values['AvailableCapacity'] > 0:
                            filtered_hosts.append((host, gos_info))
                        else:
                            LOG.debug(_("Host %s has no free capacity. Skip"),
                                        host)
                        break

        host_names = [item[0] for item in filtered_hosts]
        LOG.debug(_("Filter hosts: %s"), host_names)
        return filtered_hosts

    def _allowed_to_use_host(self, host, selected_hosts, unique):
        if unique == False or \
           host not in [item[0] for item in selected_hosts]:
            return True
        else:
            return False

    def _add_hostcap_to_list(self, selected_hosts, host, cap):
        if host not in [item[0] for item in selected_hosts]:
            selected_hosts.append((host, cap))

    def host_selection_algorithm(self, request_spec, all_hosts,
                                selected_hosts, unique):
        """Must override this method for VSA scheduler to work."""
        raise NotImplementedError(_("Must implement host selection mechanism"))

    def _select_hosts(self, request_spec, all_hosts, selected_hosts=None):

        if selected_hosts is None:
            selected_hosts = []

        host = None
        if len(selected_hosts) >= FLAGS.vsa_unique_hosts_per_alloc:
            # try to select from already selected hosts only
            LOG.debug(_("Maximum number of hosts selected (%d)"),
                        len(selected_hosts))
            unique = False
            (host, qos_cap) = self.host_selection_algorithm(request_spec,
                                                            selected_hosts,
                                                            selected_hosts,
                                                            unique)

            LOG.debug(_("Selected excessive host %(host)s"), locals())
        else:
            unique = FLAGS.vsa_select_unique_drives

        if host is None:
            # if we've not tried yet (# of sel hosts < max) - unique=True
            # or failed to select from selected_hosts - unique=False
            # select from all hosts
            (host, qos_cap) = self.host_selection_algorithm(request_spec,
                                                            all_hosts,
                                                            selected_hosts,
                                                            unique)
        if host is None:
            raise driver.WillNotSchedule(_("No available hosts"))

        return (host, qos_cap)

    def _provision_volume(self, context, vol, vsa_id, availability_zone):

        if availability_zone is None:
            availability_zone = FLAGS.storage_availability_zone

        now = utils.utcnow()
        options = {
            'size': vol['size'],
            'user_id': context.user_id,
            'project_id': context.project_id,
            'snapshot_id': None,
            'availability_zone': availability_zone,
            'status': "creating",
            'attach_status': "detached",
            'display_name': vol['name'],
            'display_description': vol['description'],
            'volume_type_id': vol['volume_type_id'],
            'metadata': dict(to_vsa_id=vsa_id),
            'host': vol['host'],
            'scheduled_at': now
            }

        size = vol['size']
        host = vol['host']
        name = vol['name']
        LOG.debug(_("Provision volume %(name)s of size %(size)s GB on "\
                    "host %(host)s"), locals())

        volume_ref = db.volume_create(context, options)
        rpc.cast(context,
                 db.queue_get_for(context, "volume", vol['host']),
                 {"method": "create_volume",
                  "args": {"volume_id": volume_ref['id'],
                           "snapshot_id": None}})

    def _check_host_enforcement(self, context, availability_zone):
        if (availability_zone
            and ':' in availability_zone
            and context.is_admin):
            zone, _x, host = availability_zone.partition(':')
            service = db.service_get_by_args(context.elevated(), host,
                                             'nova-volume')
            if not self.service_is_up(service):
                raise driver.WillNotSchedule(_("Host %s not available") % host)

            return host
        else:
            return None

    def _assign_hosts_to_volumes(self, context, volume_params, forced_host):

        prev_volume_type_id = None
        request_spec = {}
        selected_hosts = []

        LOG.debug(_("volume_params %(volume_params)s") % locals())

        i = 1
        for vol in volume_params:
            name = vol['name']
            LOG.debug(_("%(i)d: Volume %(name)s"), locals())
            i += 1

            if forced_host:
                vol['host'] = forced_host
                vol['capabilities'] = None
                continue

            volume_type_id = vol['volume_type_id']
            request_spec['size'] = vol['size']

            if prev_volume_type_id is None or\
               prev_volume_type_id != volume_type_id:
                # generate list of hosts for this drive type

                volume_type = volume_types.get_volume_type(context,
                                                volume_type_id)
                drive_type = {
                    'name': volume_type['extra_specs'].get('drive_name'),
                    'type': volume_type['extra_specs'].get('drive_type'),
                    'size': int(volume_type['extra_specs'].get('drive_size')),
                    'rpm': volume_type['extra_specs'].get('drive_rpm'),
                    }
                request_spec['drive_type'] = drive_type

                all_hosts = self._filter_hosts("volume", request_spec)
                prev_volume_type_id = volume_type_id

            (host, qos_cap) = self._select_hosts(request_spec,
                                    all_hosts, selected_hosts)
            vol['host'] = host
            vol['capabilities'] = qos_cap
            self._consume_resource(qos_cap, vol['size'], -1)

    def schedule_create_volumes(self, context, request_spec,
                                availability_zone=None, *_args, **_kwargs):
        """Picks hosts for hosting multiple volumes."""

        num_volumes = request_spec.get('num_volumes')
        LOG.debug(_("Attempting to spawn %(num_volumes)d volume(s)") %
                locals())

        vsa_id = request_spec.get('vsa_id')
        volume_params = request_spec.get('volumes')

        host = self._check_host_enforcement(context, availability_zone)

        try:
            self._print_capabilities_info()

            self._assign_hosts_to_volumes(context, volume_params, host)

            for vol in volume_params:
                self._provision_volume(context, vol, vsa_id, availability_zone)
        except:
            if vsa_id:
                db.vsa_update(context, vsa_id, dict(status=VsaState.FAILED))

            for vol in volume_params:
                if 'capabilities' in vol:
                    self._consume_resource(vol['capabilities'],
                                           vol['size'], 1)
            raise

        return None

    def schedule_create_volume(self, context, volume_id, *_args, **_kwargs):
        """Picks the best host based on requested drive type capability."""
        volume_ref = db.volume_get(context, volume_id)

        host = self._check_host_enforcement(context,
                                            volume_ref['availability_zone'])
        if host:
            now = utils.utcnow()
            db.volume_update(context, volume_id, {'host': host,
                                                  'scheduled_at': now})
            return host

        volume_type_id = volume_ref['volume_type_id']
        if volume_type_id:
            volume_type = volume_types.get_volume_type(context, volume_type_id)

        if volume_type_id is None or\
           volume_types.is_vsa_volume(volume_type_id, volume_type):

            LOG.debug(_("Non-VSA volume %d"), volume_ref['id'])
            return super(VsaScheduler, self).schedule_create_volume(context,
                        volume_id, *_args, **_kwargs)

        self._print_capabilities_info()

        drive_type = {
            'name': volume_type['extra_specs'].get('drive_name'),
            'type': volume_type['extra_specs'].get('drive_type'),
            'size': int(volume_type['extra_specs'].get('drive_size')),
            'rpm': volume_type['extra_specs'].get('drive_rpm'),
            }

        LOG.debug(_("Spawning volume %(volume_id)s with drive type "\
                    "%(drive_type)s"), locals())

        request_spec = {'size': volume_ref['size'],
                        'drive_type': drive_type}
        hosts = self._filter_hosts("volume", request_spec)

        try:
            (host, qos_cap) = self._select_hosts(request_spec, all_hosts=hosts)
        except:
            if volume_ref['to_vsa_id']:
                db.vsa_update(context, volume_ref['to_vsa_id'],
                                dict(status=VsaState.FAILED))
            raise

        if host:
            now = utils.utcnow()
            db.volume_update(context, volume_id, {'host': host,
                                                  'scheduled_at': now})
            self._consume_resource(qos_cap, volume_ref['size'], -1)
            return host

    def _consume_full_drive(self, qos_values, direction):
        qos_values['FullDrive']['NumFreeDrives'] += direction
        qos_values['FullDrive']['NumOccupiedDrives'] -= direction

    def _consume_partition(self, qos_values, size, direction):

        if qos_values['PartitionDrive']['PartitionSize'] != 0:
            partition_size = qos_values['PartitionDrive']['PartitionSize']
        else:
            partition_size = size
        part_per_drive = qos_values['DriveCapacity'] / partition_size

        if direction == -1 and \
           qos_values['PartitionDrive']['NumFreePartitions'] == 0:

            self._consume_full_drive(qos_values, direction)
            qos_values['PartitionDrive']['NumFreePartitions'] += \
                                                        part_per_drive

        qos_values['PartitionDrive']['NumFreePartitions'] += direction
        qos_values['PartitionDrive']['NumOccupiedPartitions'] -= direction

        if direction == 1 and \
           qos_values['PartitionDrive']['NumFreePartitions'] >= \
                                                        part_per_drive:

            self._consume_full_drive(qos_values, direction)
            qos_values['PartitionDrive']['NumFreePartitions'] -= \
                                                        part_per_drive

    def _consume_resource(self, qos_values, size, direction):
        if qos_values is None:
            LOG.debug(_("No capability selected for volume of size %(size)s"),
                        locals())
            return

        if size == 0:   # full drive match
            qos_values['AvailableCapacity'] += direction * \
                                        qos_values['DriveCapacity']
            self._consume_full_drive(qos_values, direction)
        else:
            qos_values['AvailableCapacity'] += direction * GB_TO_BYTES(size)
            self._consume_partition(qos_values, GB_TO_BYTES(size), direction)
        return

    def _print_capabilities_info(self):
        host_list = self._get_service_states().iteritems()
        for host, host_dict in host_list:
            for service_name, service_dict in host_dict.iteritems():
                if service_name != "volume":
                    continue

                LOG.info(_("Host %s:"), host)

                gos_info = service_dict.get('drive_qos_info', {})
                for qosgrp, qos_values in gos_info.iteritems():
                    total = qos_values['TotalDrives']
                    used = qos_values['FullDrive']['NumOccupiedDrives']
                    free = qos_values['FullDrive']['NumFreeDrives']
                    avail = BYTES_TO_GB(qos_values['AvailableCapacity'])

                    LOG.info(_("\tDrive %(qosgrp)-25s: total %(total)2s, "\
                               "used %(used)2s, free %(free)2s. Available "\
                               "capacity %(avail)-5s"), locals())


class VsaSchedulerLeastUsedHost(VsaScheduler):
    """
    Implements VSA scheduler to select the host with least used capacity
    of particular type.
    """

    def __init__(self, *args, **kwargs):
        super(VsaSchedulerLeastUsedHost, self).__init__(*args, **kwargs)

    def host_selection_algorithm(self, request_spec, all_hosts,
                                selected_hosts, unique):
        size = request_spec['size']
        drive_type = request_spec['drive_type']
        best_host = None
        best_qoscap = None
        best_cap = None
        min_used = 0

        for (host, capabilities) in all_hosts:

            has_enough_capacity = False
            used_capacity = 0
            for qosgrp, qos_values in capabilities.iteritems():

                used_capacity = used_capacity + qos_values['TotalCapacity'] \
                                - qos_values['AvailableCapacity']

                if self._qosgrp_match(drive_type, qos_values):
                    # we found required qosgroup

                    if size == 0:   # full drive match
                        if qos_values['FullDrive']['NumFreeDrives'] > 0:
                            has_enough_capacity = True
                            matched_qos = qos_values
                        else:
                            break
                    else:
                        if qos_values['AvailableCapacity'] >= size and \
                           (qos_values['PartitionDrive'][
                                            'NumFreePartitions'] > 0 or \
                            qos_values['FullDrive']['NumFreeDrives'] > 0):
                            has_enough_capacity = True
                            matched_qos = qos_values
                        else:
                            break

            if has_enough_capacity and \
               self._allowed_to_use_host(host,
                                         selected_hosts,
                                         unique) and \
               (best_host is None or used_capacity < min_used):

                min_used = used_capacity
                best_host = host
                best_qoscap = matched_qos
                best_cap = capabilities

        if best_host:
            self._add_hostcap_to_list(selected_hosts, best_host, best_cap)
            min_used = BYTES_TO_GB(min_used)
            LOG.debug(_("\t LeastUsedHost: Best host: %(best_host)s. "\
                        "(used capacity %(min_used)s)"), locals())
        return (best_host, best_qoscap)


class VsaSchedulerMostAvailCapacity(VsaScheduler):
    """
    Implements VSA scheduler to select the host with most available capacity
    of one particular type.
    """

    def __init__(self, *args, **kwargs):
        super(VsaSchedulerMostAvailCapacity, self).__init__(*args, **kwargs)

    def host_selection_algorithm(self, request_spec, all_hosts,
                                selected_hosts, unique):
        size = request_spec['size']
        drive_type = request_spec['drive_type']
        best_host = None
        best_qoscap = None
        best_cap = None
        max_avail = 0

        for (host, capabilities) in all_hosts:
            for qosgrp, qos_values in capabilities.iteritems():
                if self._qosgrp_match(drive_type, qos_values):
                    # we found required qosgroup

                    if size == 0:   # full drive match
                        available = qos_values['FullDrive']['NumFreeDrives']
                    else:
                        available = qos_values['AvailableCapacity']

                    if available > max_avail and \
                       self._allowed_to_use_host(host,
                                                 selected_hosts,
                                                 unique):
                        max_avail = available
                        best_host = host
                        best_qoscap = qos_values
                        best_cap = capabilities
                    break   # go to the next host

        if best_host:
            self._add_hostcap_to_list(selected_hosts, best_host, best_cap)
            type_str = "drives" if size == 0 else "bytes"
            LOG.debug(_("\t MostAvailCap: Best host: %(best_host)s. "\
                        "(available %(max_avail)s %(type_str)s)"), locals())

        return (best_host, best_qoscap)
