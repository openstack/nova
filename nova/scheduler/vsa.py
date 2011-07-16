# vim: tabstop=4 shiftwidth=4 softtabstop=4

# Copyright (c) 2011 Zadara Storage Inc.
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
VSA Simple Scheduler
"""

from nova import context
from nova import rpc
from nova import db
from nova import flags
from nova import utils
from nova.volume import api as volume_api
from nova.scheduler import driver
from nova.scheduler import simple
from nova import log as logging

LOG = logging.getLogger('nova.scheduler.vsa')

FLAGS = flags.FLAGS
flags.DEFINE_integer('gb_to_bytes_shift', 30,
                    'Conversion shift between GB and bytes')
flags.DEFINE_integer('drive_type_approx_capacity_percent', 10,
                    'The percentage range for capacity comparison')
flags.DEFINE_integer('vsa_unique_hosts_per_alloc', 10,
                    'The number of unique hosts per storage allocation')
flags.DEFINE_boolean('vsa_select_unique_drives', True,
                     'Allow selection of same host for multiple drives')


class VsaScheduler(simple.SimpleScheduler):
    """Implements Naive Scheduler that tries to find least loaded host."""

    def __init__(self, *args, **kwargs):
        super(VsaScheduler, self).__init__(*args, **kwargs)
        self._notify_all_volume_hosts("startup")

    def _notify_all_volume_hosts(self, event):
        rpc.cast(context.get_admin_context(),
                 FLAGS.volume_topic,
                 {"method": "notification",
                  "args": {"event": event}})

    def _compare_names(self, str1, str2):
        result = str1.lower() == str2.lower()
        # LOG.debug(_("Comparing %(str1)s and %(str2)s. "\
        #            "Result %(result)s"), locals())
        return result

    def _compare_sizes_exact_match(self, cap_capacity, size_gb):
        cap_capacity = int(cap_capacity) >> FLAGS.gb_to_bytes_shift
        size_gb = int(size_gb)
        result = cap_capacity == size_gb
        # LOG.debug(_("Comparing %(cap_capacity)d and %(size_gb)d. "\
        #            "Result %(result)s"), locals())
        return result

    def _compare_sizes_approxim(self, cap_capacity, size_gb):
        cap_capacity = int(cap_capacity) >> FLAGS.gb_to_bytes_shift
        size_gb = int(size_gb)
        size_perc = size_gb * FLAGS.drive_type_approx_capacity_percent / 100

        result = cap_capacity >= size_gb - size_perc and \
                 cap_capacity <= size_gb + size_perc
        # LOG.debug(_("Comparing %(cap_capacity)d and %(size_gb)d. "\
        #            "Result %(result)s"), locals())
        return result

    def _qosgrp_match(self, drive_type, qos_values):

        # Add more entries for additional comparisons
        compare_list = [{'cap1': 'DriveType',
                         'cap2': 'type',
                         'cmp_func': self._compare_names},
                        {'cap1': 'DriveCapacity',
                         'cap2': 'size_gb',
                         'cmp_func': self._compare_sizes_approxim}]

        for cap in compare_list:
            if cap['cap1'] in qos_values.keys() and \
               cap['cap2'] in drive_type.keys() and \
               cap['cmp_func'] is not None and \
               cap['cmp_func'](qos_values[cap['cap1']],
                               drive_type[cap['cap2']]):
                # LOG.debug(_("One of required capabilities found: %s:%s"),
                #            cap['cap1'], drive_type[cap['cap2']])
                pass
            else:
                return False
        return True

    def _filter_hosts(self, topic, request_spec, host_list=None):

        drive_type = request_spec['drive_type']
        LOG.debug(_("Filter hosts for drive type %(drive_type)s") % locals())

        if host_list is None:
            host_list = self.zone_manager.service_states.iteritems()

        filtered_hosts = []     # returns list of (hostname, capability_dict)
        for host, host_dict in host_list:
            for service_name, service_dict in host_dict.iteritems():
                if service_name != topic:
                    continue

                gos_info = service_dict.get('drive_qos_info', {})
                for qosgrp, qos_values in gos_info.iteritems():
                    if self._qosgrp_match(drive_type, qos_values):
                        if qos_values['AvailableCapacity'] > 0:
                            LOG.debug(_("Adding host %s to the list"), host)
                            filtered_hosts.append((host, gos_info))
                        else:
                            LOG.debug(_("Host %s has no free capacity. Skip"),
                                        host)
                        break

        LOG.debug(_("Found hosts %(filtered_hosts)s") % locals())
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

    def _alg_least_used_host(self, request_spec, all_hosts, selected_hosts):
        size = request_spec['size']
        drive_type = request_spec['drive_type']
        best_host = None
        best_qoscap = None
        best_cap = None
        min_used = 0

        LOG.debug(_("Selecting best host for %(size)sGB volume of type "\
                    "%(drive_type)s from %(all_hosts)s"), locals())

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
            self._add_hostcap_to_list(selected_hosts, host, best_cap)
            LOG.debug(_("Best host found: %(best_host)s. "\
                        "(used capacity %(min_used)s)"), locals())
        return (best_host, best_qoscap)

    def _alg_most_avail_capacity(self, request_spec, all_hosts,
                                selected_hosts, unique):
        size = request_spec['size']
        drive_type = request_spec['drive_type']
        best_host = None
        best_qoscap = None
        best_cap = None
        max_avail = 0

        LOG.debug(_("Selecting best host for %(size)sGB volume of type "\
                    "%(drive_type)s from %(all_hosts)s"), locals())

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
            self._add_hostcap_to_list(selected_hosts, host, best_cap)
            LOG.debug(_("Best host found: %(best_host)s. "\
                        "(available capacity %(max_avail)s)"), locals())

        return (best_host, best_qoscap)

    def _select_hosts(self, request_spec, all_hosts, selected_hosts=None):

        #self._alg_most_avail_capacity(request_spec, all_hosts, selected_hosts)

        if selected_hosts is None:
            selected_hosts = []

        host = None
        if len(selected_hosts) >= FLAGS.vsa_unique_hosts_per_alloc:
            # try to select from already selected hosts only
            LOG.debug(_("Maximum number of hosts selected (%d)"),
                        len(selected_hosts))
            unique = False
            (host, qos_cap) = self._alg_most_avail_capacity(request_spec,
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
            (host, qos_cap) = self._alg_most_avail_capacity(request_spec,
                                                            all_hosts,
                                                            selected_hosts,
                                                            unique)
            LOG.debug(_("Selected host %(host)s"), locals())

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
            'to_vsa_id': vsa_id,
            'drive_type_id': vol['drive_ref']['id'],
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

    def _check_host_enforcement(self, availability_zone):
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

        prev_drive_type_id = None
        selected_hosts = []

        LOG.debug(_("volume_params %(volume_params)s") % locals())

        for vol in volume_params:
            LOG.debug(_("Assigning host to volume %s") % vol['name'])

            if forced_host:
                vol['host'] = forced_host
                vol['capabilities'] = None
                continue

            drive_type = vol['drive_ref']
            request_spec = {'size': vol['size'],
                            'drive_type': dict(drive_type)}

            if prev_drive_type_id != drive_type['id']:
                # generate list of hosts for this drive type
                all_hosts = self._filter_hosts("volume", request_spec)
                prev_drive_type_id = drive_type['id']

            (host, qos_cap) = self._select_hosts(request_spec,
                                    all_hosts, selected_hosts)
            vol['host'] = host
            vol['capabilities'] = qos_cap
            self._consume_resource(qos_cap, vol['size'], -1)

            LOG.debug(_("Assigned host %(host)s, capabilities %(qos_cap)s"),
                        locals())

        LOG.debug(_("END: volume_params %(volume_params)s") % locals())

    def schedule_create_volumes(self, context, request_spec,
                                availability_zone, *_args, **_kwargs):
        """Picks hosts for hosting multiple volumes."""

        num_volumes = request_spec.get('num_volumes')
        LOG.debug(_("Attempting to spawn %(num_volumes)d volume(s)") %
                locals())

        LOG.debug(_("Service states BEFORE %s"),
                    self.zone_manager.service_states)

        vsa_id = request_spec.get('vsa_id')
        volume_params = request_spec.get('volumes')

        host = self._check_host_enforcement(availability_zone)

        try:
            self._assign_hosts_to_volumes(context, volume_params, host)

            for vol in volume_params:
                self._provision_volume(context, vol, vsa_id, availability_zone)

            LOG.debug(_("Service states AFTER %s"),
                        self.zone_manager.service_states)

        except:
            if vsa_id:
                db.vsa_update(context, vsa_id,
                    dict(status=FLAGS.vsa_status_failed))

            for vol in volume_params:
                if 'capabilities' in vol:
                    self._consume_resource(vol['capabilities'],
                                           vol['size'], 1)
            LOG.debug(_("Service states AFTER %s"),
                        self.zone_manager.service_states)
            raise

        return None

    def schedule_create_volume(self, context, volume_id, *_args, **_kwargs):
        """Picks the best host based on requested drive type capability."""
        volume_ref = db.volume_get(context, volume_id)

        host = self._check_host_enforcement(volume_ref['availability_zone'])
        if host:
            now = utils.utcnow()
            db.volume_update(context, volume_id, {'host': host,
                                                  'scheduled_at': now})
            return host

        drive_type = volume_ref['drive_type']
        if drive_type is None:
            LOG.debug(_("Non-VSA volume %d"), volume_ref['id'])
            return super(VsaScheduler, self).schedule_create_volume(context,
                        volume_id, *_args, **_kwargs)
        drive_type = dict(drive_type)

        # otherwise - drive type is loaded
        LOG.debug(_("Spawning volume %d with drive type %s"),
                    volume_ref['id'], drive_type)

        LOG.debug(_("Service states BEFORE %s"),
                    self.zone_manager.service_states)

        request_spec = {'size': volume_ref['size'],
                        'drive_type': drive_type}
        hosts = self._filter_hosts("volume", request_spec)

        try:
            (host, qos_cap) = self._select_hosts(request_spec, all_hosts=hosts)
        except:
            if volume_ref['to_vsa_id']:
                db.vsa_update(context, volume_ref['to_vsa_id'],
                                dict(status=FLAGS.vsa_status_failed))
            raise
            #return super(VsaScheduler, self).schedule_create_volume(context,
            #            volume_id, *_args, **_kwargs)

        if host:
            now = utils.utcnow()
            db.volume_update(context, volume_id, {'host': host,
                                                  'scheduled_at': now})
            self._consume_resource(qos_cap, volume_ref['size'], -1)

            LOG.debug(_("Service states AFTER %s"),
                        self.zone_manager.service_states)
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
            qos_values['AvailableCapacity'] += direction * \
                                        (size << FLAGS.gb_to_bytes_shift)
            self._consume_partition(qos_values,
                                    size << FLAGS.gb_to_bytes_shift,
                                    direction)
        return
