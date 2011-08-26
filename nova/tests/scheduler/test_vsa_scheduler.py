# Copyright 2011 OpenStack LLC.
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

import stubout

import nova

from nova import context
from nova import db
from nova import exception
from nova import flags
from nova import log as logging
from nova import test
from nova import utils
from nova.volume import volume_types

from nova.scheduler import vsa as vsa_sched
from nova.scheduler import driver

FLAGS = flags.FLAGS
LOG = logging.getLogger('nova.tests.scheduler.vsa')

scheduled_volumes = []
scheduled_volume = {}
global_volume = {}


class FakeVsaLeastUsedScheduler(
                vsa_sched.VsaSchedulerLeastUsedHost):
    # No need to stub anything at the moment
    pass


class FakeVsaMostAvailCapacityScheduler(
                vsa_sched.VsaSchedulerMostAvailCapacity):
    # No need to stub anything at the moment
    pass


class VsaSchedulerTestCase(test.TestCase):

    def _get_vol_creation_request(self, num_vols, drive_ix, size=0):
        volume_params = []
        for i in range(num_vols):

            name = 'name_' + str(i)
            try:
                volume_types.create(self.context, name,
                            extra_specs={'type': 'vsa_drive',
                                         'drive_name': name,
                                         'drive_type': 'type_' + str(drive_ix),
                                         'drive_size': 1 + 100 * (drive_ix)})
                self.created_types_lst.append(name)
            except exception.ApiError:
                # type is already created
                pass

            volume_type = volume_types.get_volume_type_by_name(self.context,
                                                                name)
            volume = {'size': size,
                      'snapshot_id': None,
                      'name': 'vol_' + str(i),
                      'description': None,
                      'volume_type_id': volume_type['id']}
            volume_params.append(volume)

        return {'num_volumes': len(volume_params),
                'vsa_id': 123,
                'volumes': volume_params}

    def _generate_default_service_states(self):
        service_states = {}
        for i in range(self.host_num):
            host = {}
            hostname = 'host_' + str(i)
            if hostname in self.exclude_host_list:
                continue

            host['volume'] = {'timestamp': utils.utcnow(),
                              'drive_qos_info': {}}

            for j in range(self.drive_type_start_ix,
                           self.drive_type_start_ix + self.drive_type_num):
                dtype = {}
                dtype['Name'] = 'name_' + str(j)
                dtype['DriveType'] = 'type_' + str(j)
                dtype['TotalDrives'] = 2 * (self.init_num_drives + i)
                dtype['DriveCapacity'] = vsa_sched.GB_TO_BYTES(1 + 100 * j)
                dtype['TotalCapacity'] = dtype['TotalDrives'] * \
                                            dtype['DriveCapacity']
                dtype['AvailableCapacity'] = (dtype['TotalDrives'] - i) * \
                                            dtype['DriveCapacity']
                dtype['DriveRpm'] = 7200
                dtype['DifCapable'] = 0
                dtype['SedCapable'] = 0
                dtype['PartitionDrive'] = {
                            'PartitionSize': 0,
                            'NumOccupiedPartitions': 0,
                            'NumFreePartitions': 0}
                dtype['FullDrive'] = {
                            'NumFreeDrives': dtype['TotalDrives'] - i,
                            'NumOccupiedDrives': i}
                host['volume']['drive_qos_info'][dtype['Name']] = dtype

            service_states[hostname] = host

        return service_states

    def _print_service_states(self):
        for host, host_val in self.service_states.iteritems():
            LOG.info(_("Host %s"), host)
            total_used = 0
            total_available = 0
            qos = host_val['volume']['drive_qos_info']

            for k, d in qos.iteritems():
                LOG.info("\t%s: type %s: drives (used %2d, total %2d) "\
                    "size %3d, total %4d, used %4d, avail %d",
                    k, d['DriveType'],
                    d['FullDrive']['NumOccupiedDrives'], d['TotalDrives'],
                    vsa_sched.BYTES_TO_GB(d['DriveCapacity']),
                    vsa_sched.BYTES_TO_GB(d['TotalCapacity']),
                    vsa_sched.BYTES_TO_GB(d['TotalCapacity'] - \
                        d['AvailableCapacity']),
                    vsa_sched.BYTES_TO_GB(d['AvailableCapacity']))

                total_used += vsa_sched.BYTES_TO_GB(d['TotalCapacity'] - \
                                    d['AvailableCapacity'])
                total_available += vsa_sched.BYTES_TO_GB(
                                        d['AvailableCapacity'])
            LOG.info("Host %s: used %d, avail %d",
                     host, total_used, total_available)

    def _set_service_states(self, host_num,
                            drive_type_start_ix, drive_type_num,
                            init_num_drives=10,
                            exclude_host_list=[]):
        self.host_num = host_num
        self.drive_type_start_ix = drive_type_start_ix
        self.drive_type_num = drive_type_num
        self.exclude_host_list = exclude_host_list
        self.init_num_drives = init_num_drives
        self.service_states = self._generate_default_service_states()

    def _get_service_states(self):
        return self.service_states

    def _fake_get_service_states(self):
        return self._get_service_states()

    def _fake_provision_volume(self, context, vol, vsa_id, availability_zone):
        global scheduled_volumes
        scheduled_volumes.append(dict(vol=vol,
                                      vsa_id=vsa_id,
                                      az=availability_zone))
        name = vol['name']
        host = vol['host']
        LOG.debug(_("Test: provision vol %(name)s on host %(host)s"),
                    locals())
        LOG.debug(_("\t vol=%(vol)s"), locals())
        pass

    def _fake_vsa_update(self, context, vsa_id, values):
        LOG.debug(_("Test: VSA update request: vsa_id=%(vsa_id)s "\
                    "values=%(values)s"), locals())
        pass

    def _fake_volume_create(self, context, options):
        LOG.debug(_("Test: Volume create: %s"), options)
        options['id'] = 123
        global global_volume
        global_volume = options
        return options

    def _fake_volume_get(self, context, volume_id):
        LOG.debug(_("Test: Volume get request: id=%(volume_id)s"), locals())
        global global_volume
        global_volume['id'] = volume_id
        global_volume['availability_zone'] = None
        return global_volume

    def _fake_volume_update(self, context, volume_id, values):
        LOG.debug(_("Test: Volume update request: id=%(volume_id)s "\
                    "values=%(values)s"), locals())
        global scheduled_volume
        scheduled_volume = {'id': volume_id, 'host': values['host']}
        pass

    def _fake_service_get_by_args(self, context, host, binary):
        return "service"

    def _fake_service_is_up_True(self, service):
        return True

    def _fake_service_is_up_False(self, service):
        return False

    def setUp(self, sched_class=None):
        super(VsaSchedulerTestCase, self).setUp()
        self.stubs = stubout.StubOutForTesting()
        self.context = context.get_admin_context()

        if sched_class is None:
            self.sched = FakeVsaLeastUsedScheduler()
        else:
            self.sched = sched_class

        self.host_num = 10
        self.drive_type_num = 5

        self.stubs.Set(self.sched,
                        '_get_service_states', self._fake_get_service_states)
        self.stubs.Set(self.sched,
                        '_provision_volume', self._fake_provision_volume)
        self.stubs.Set(nova.db, 'vsa_update', self._fake_vsa_update)

        self.stubs.Set(nova.db, 'volume_get', self._fake_volume_get)
        self.stubs.Set(nova.db, 'volume_update', self._fake_volume_update)

        self.created_types_lst = []

    def tearDown(self):
        for name in self.created_types_lst:
            volume_types.purge(self.context, name)

        self.stubs.UnsetAll()
        super(VsaSchedulerTestCase, self).tearDown()

    def test_vsa_sched_create_volumes_simple(self):
        global scheduled_volumes
        scheduled_volumes = []
        self._set_service_states(host_num=10,
                                 drive_type_start_ix=0,
                                 drive_type_num=5,
                                 init_num_drives=10,
                                 exclude_host_list=['host_1', 'host_3'])
        prev = self._generate_default_service_states()
        request_spec = self._get_vol_creation_request(num_vols=3, drive_ix=2)

        self.sched.schedule_create_volumes(self.context,
                                           request_spec,
                                           availability_zone=None)

        self.assertEqual(len(scheduled_volumes), 3)
        self.assertEqual(scheduled_volumes[0]['vol']['host'], 'host_0')
        self.assertEqual(scheduled_volumes[1]['vol']['host'], 'host_2')
        self.assertEqual(scheduled_volumes[2]['vol']['host'], 'host_4')

        cur = self._get_service_states()
        for host in ['host_0', 'host_2', 'host_4']:
            cur_dtype = cur[host]['volume']['drive_qos_info']['name_2']
            prev_dtype = prev[host]['volume']['drive_qos_info']['name_2']
            self.assertEqual(cur_dtype['DriveType'], prev_dtype['DriveType'])
            self.assertEqual(cur_dtype['FullDrive']['NumFreeDrives'],
                             prev_dtype['FullDrive']['NumFreeDrives'] - 1)
            self.assertEqual(cur_dtype['FullDrive']['NumOccupiedDrives'],
                             prev_dtype['FullDrive']['NumOccupiedDrives'] + 1)

    def test_vsa_sched_no_drive_type(self):
        self._set_service_states(host_num=10,
                                 drive_type_start_ix=0,
                                 drive_type_num=5,
                                 init_num_drives=1)
        request_spec = self._get_vol_creation_request(num_vols=1, drive_ix=6)
        self.assertRaises(driver.WillNotSchedule,
                          self.sched.schedule_create_volumes,
                                self.context,
                                request_spec,
                                availability_zone=None)

    def test_vsa_sched_no_enough_drives(self):
        global scheduled_volumes
        scheduled_volumes = []

        self._set_service_states(host_num=3,
                                 drive_type_start_ix=0,
                                 drive_type_num=1,
                                 init_num_drives=0)
        prev = self._generate_default_service_states()
        request_spec = self._get_vol_creation_request(num_vols=3, drive_ix=0)

        self.assertRaises(driver.WillNotSchedule,
                          self.sched.schedule_create_volumes,
                                self.context,
                                request_spec,
                                availability_zone=None)

        # check that everything was returned back
        cur = self._get_service_states()
        for k, v in prev.iteritems():
            self.assertEqual(prev[k]['volume']['drive_qos_info'],
                              cur[k]['volume']['drive_qos_info'])

    def test_vsa_sched_wrong_topic(self):
        self._set_service_states(host_num=1,
                                 drive_type_start_ix=0,
                                 drive_type_num=5,
                                 init_num_drives=1)
        states = self._get_service_states()
        new_states = {}
        new_states['host_0'] = {'compute': states['host_0']['volume']}
        self.service_states = new_states
        request_spec = self._get_vol_creation_request(num_vols=1, drive_ix=0)

        self.assertRaises(driver.WillNotSchedule,
                          self.sched.schedule_create_volumes,
                                self.context,
                                request_spec,
                                availability_zone=None)

    def test_vsa_sched_provision_volume(self):
        global global_volume
        global_volume = {}
        self._set_service_states(host_num=1,
                                 drive_type_start_ix=0,
                                 drive_type_num=1,
                                 init_num_drives=1)
        request_spec = self._get_vol_creation_request(num_vols=1, drive_ix=0)

        self.stubs.UnsetAll()
        self.stubs.Set(self.sched,
                        '_get_service_states', self._fake_get_service_states)
        self.stubs.Set(nova.db, 'volume_create', self._fake_volume_create)

        self.sched.schedule_create_volumes(self.context,
                                           request_spec,
                                           availability_zone=None)

        self.assertEqual(request_spec['volumes'][0]['name'],
                         global_volume['display_name'])

    def test_vsa_sched_no_free_drives(self):
        self._set_service_states(host_num=1,
                                 drive_type_start_ix=0,
                                 drive_type_num=1,
                                 init_num_drives=1)
        request_spec = self._get_vol_creation_request(num_vols=1, drive_ix=0)

        self.sched.schedule_create_volumes(self.context,
                                           request_spec,
                                           availability_zone=None)

        cur = self._get_service_states()
        cur_dtype = cur['host_0']['volume']['drive_qos_info']['name_0']
        self.assertEqual(cur_dtype['FullDrive']['NumFreeDrives'], 1)

        new_request = self._get_vol_creation_request(num_vols=1, drive_ix=0)

        self.sched.schedule_create_volumes(self.context,
                                           request_spec,
                                           availability_zone=None)
        self._print_service_states()

        self.assertRaises(driver.WillNotSchedule,
                          self.sched.schedule_create_volumes,
                                self.context,
                                new_request,
                                availability_zone=None)

    def test_vsa_sched_forced_host(self):
        global scheduled_volumes
        scheduled_volumes = []

        self._set_service_states(host_num=10,
                                 drive_type_start_ix=0,
                                 drive_type_num=5,
                                 init_num_drives=10)

        request_spec = self._get_vol_creation_request(num_vols=3, drive_ix=2)

        self.assertRaises(exception.HostBinaryNotFound,
                          self.sched.schedule_create_volumes,
                                self.context,
                                request_spec,
                                availability_zone="nova:host_5")

        self.stubs.Set(nova.db,
                        'service_get_by_args', self._fake_service_get_by_args)
        self.stubs.Set(self.sched,
                        'service_is_up', self._fake_service_is_up_False)

        self.assertRaises(driver.WillNotSchedule,
                          self.sched.schedule_create_volumes,
                                self.context,
                                request_spec,
                                availability_zone="nova:host_5")

        self.stubs.Set(self.sched,
                        'service_is_up', self._fake_service_is_up_True)

        self.sched.schedule_create_volumes(self.context,
                                           request_spec,
                                           availability_zone="nova:host_5")

        self.assertEqual(len(scheduled_volumes), 3)
        self.assertEqual(scheduled_volumes[0]['vol']['host'], 'host_5')
        self.assertEqual(scheduled_volumes[1]['vol']['host'], 'host_5')
        self.assertEqual(scheduled_volumes[2]['vol']['host'], 'host_5')

    def test_vsa_sched_create_volumes_partition(self):
        global scheduled_volumes
        scheduled_volumes = []
        self._set_service_states(host_num=5,
                                 drive_type_start_ix=0,
                                 drive_type_num=5,
                                 init_num_drives=1,
                                 exclude_host_list=['host_0', 'host_2'])
        prev = self._generate_default_service_states()
        request_spec = self._get_vol_creation_request(num_vols=3,
                                                      drive_ix=3,
                                                      size=50)
        self.sched.schedule_create_volumes(self.context,
                                           request_spec,
                                           availability_zone=None)

        self.assertEqual(len(scheduled_volumes), 3)
        self.assertEqual(scheduled_volumes[0]['vol']['host'], 'host_1')
        self.assertEqual(scheduled_volumes[1]['vol']['host'], 'host_3')
        self.assertEqual(scheduled_volumes[2]['vol']['host'], 'host_4')

        cur = self._get_service_states()
        for host in ['host_1', 'host_3', 'host_4']:
            cur_dtype = cur[host]['volume']['drive_qos_info']['name_3']
            prev_dtype = prev[host]['volume']['drive_qos_info']['name_3']

            self.assertEqual(cur_dtype['DriveType'], prev_dtype['DriveType'])
            self.assertEqual(cur_dtype['FullDrive']['NumFreeDrives'],
                             prev_dtype['FullDrive']['NumFreeDrives'] - 1)
            self.assertEqual(cur_dtype['FullDrive']['NumOccupiedDrives'],
                             prev_dtype['FullDrive']['NumOccupiedDrives'] + 1)

            self.assertEqual(prev_dtype['PartitionDrive']
                                            ['NumOccupiedPartitions'], 0)
            self.assertEqual(cur_dtype['PartitionDrive']
                                            ['NumOccupiedPartitions'], 1)
            self.assertEqual(cur_dtype['PartitionDrive']
                                            ['NumFreePartitions'], 5)

            self.assertEqual(prev_dtype['PartitionDrive']
                                            ['NumFreePartitions'], 0)
            self.assertEqual(prev_dtype['PartitionDrive']
                                            ['PartitionSize'], 0)

    def test_vsa_sched_create_single_volume_az(self):
        global scheduled_volume
        scheduled_volume = {}

        def _fake_volume_get_az(context, volume_id):
            LOG.debug(_("Test: Volume get: id=%(volume_id)s"), locals())
            return {'id': volume_id, 'availability_zone': 'nova:host_3'}

        self.stubs.Set(nova.db, 'volume_get', _fake_volume_get_az)
        self.stubs.Set(nova.db,
                        'service_get_by_args', self._fake_service_get_by_args)
        self.stubs.Set(self.sched,
                        'service_is_up', self._fake_service_is_up_True)

        host = self.sched.schedule_create_volume(self.context,
                                                 123, availability_zone=None)

        self.assertEqual(host, 'host_3')
        self.assertEqual(scheduled_volume['id'], 123)
        self.assertEqual(scheduled_volume['host'], 'host_3')

    def test_vsa_sched_create_single_non_vsa_volume(self):
        global scheduled_volume
        scheduled_volume = {}

        global global_volume
        global_volume = {}
        global_volume['volume_type_id'] = None

        self.assertRaises(driver.NoValidHost,
                          self.sched.schedule_create_volume,
                                self.context,
                                123,
                                availability_zone=None)

    def test_vsa_sched_create_single_volume(self):
        global scheduled_volume
        scheduled_volume = {}
        self._set_service_states(host_num=10,
                                 drive_type_start_ix=0,
                                 drive_type_num=5,
                                 init_num_drives=10,
                                 exclude_host_list=['host_0', 'host_1'])
        prev = self._generate_default_service_states()

        global global_volume
        global_volume = {}

        drive_ix = 2
        name = 'name_' + str(drive_ix)
        volume_types.create(self.context, name,
                    extra_specs={'type': 'vsa_drive',
                                 'drive_name': name,
                                 'drive_type': 'type_' + str(drive_ix),
                                 'drive_size': 1 + 100 * (drive_ix)})
        self.created_types_lst.append(name)
        volume_type = volume_types.get_volume_type_by_name(self.context, name)

        global_volume['volume_type_id'] = volume_type['id']
        global_volume['size'] = 0

        host = self.sched.schedule_create_volume(self.context,
                                                 123, availability_zone=None)

        self.assertEqual(host, 'host_2')
        self.assertEqual(scheduled_volume['id'], 123)
        self.assertEqual(scheduled_volume['host'], 'host_2')


class VsaSchedulerTestCaseMostAvail(VsaSchedulerTestCase):

    def setUp(self):
        super(VsaSchedulerTestCaseMostAvail, self).setUp(
                    FakeVsaMostAvailCapacityScheduler())

    def tearDown(self):
        self.stubs.UnsetAll()
        super(VsaSchedulerTestCaseMostAvail, self).tearDown()

    def test_vsa_sched_create_single_volume(self):
        global scheduled_volume
        scheduled_volume = {}
        self._set_service_states(host_num=10,
                                 drive_type_start_ix=0,
                                 drive_type_num=5,
                                 init_num_drives=10,
                                 exclude_host_list=['host_0', 'host_1'])
        prev = self._generate_default_service_states()

        global global_volume
        global_volume = {}

        drive_ix = 2
        name = 'name_' + str(drive_ix)
        volume_types.create(self.context, name,
                    extra_specs={'type': 'vsa_drive',
                                 'drive_name': name,
                                 'drive_type': 'type_' + str(drive_ix),
                                 'drive_size': 1 + 100 * (drive_ix)})
        self.created_types_lst.append(name)
        volume_type = volume_types.get_volume_type_by_name(self.context, name)

        global_volume['volume_type_id'] = volume_type['id']
        global_volume['size'] = 0

        host = self.sched.schedule_create_volume(self.context,
                                                 123, availability_zone=None)

        self.assertEqual(host, 'host_9')
        self.assertEqual(scheduled_volume['id'], 123)
        self.assertEqual(scheduled_volume['host'], 'host_9')

    def test_vsa_sched_create_volumes_simple(self):
        global scheduled_volumes
        scheduled_volumes = []
        self._set_service_states(host_num=10,
                                 drive_type_start_ix=0,
                                 drive_type_num=5,
                                 init_num_drives=10,
                                 exclude_host_list=['host_1', 'host_3'])
        prev = self._generate_default_service_states()
        request_spec = self._get_vol_creation_request(num_vols=3, drive_ix=2)

        self._print_service_states()

        self.sched.schedule_create_volumes(self.context,
                                           request_spec,
                                           availability_zone=None)

        self.assertEqual(len(scheduled_volumes), 3)
        self.assertEqual(scheduled_volumes[0]['vol']['host'], 'host_9')
        self.assertEqual(scheduled_volumes[1]['vol']['host'], 'host_8')
        self.assertEqual(scheduled_volumes[2]['vol']['host'], 'host_7')

        cur = self._get_service_states()
        for host in ['host_9', 'host_8', 'host_7']:
            cur_dtype = cur[host]['volume']['drive_qos_info']['name_2']
            prev_dtype = prev[host]['volume']['drive_qos_info']['name_2']
            self.assertEqual(cur_dtype['DriveType'], prev_dtype['DriveType'])
            self.assertEqual(cur_dtype['FullDrive']['NumFreeDrives'],
                             prev_dtype['FullDrive']['NumFreeDrives'] - 1)
            self.assertEqual(cur_dtype['FullDrive']['NumOccupiedDrives'],
                             prev_dtype['FullDrive']['NumOccupiedDrives'] + 1)

    def test_vsa_sched_create_volumes_partition(self):
        global scheduled_volumes
        scheduled_volumes = []
        self._set_service_states(host_num=5,
                                 drive_type_start_ix=0,
                                 drive_type_num=5,
                                 init_num_drives=1,
                                 exclude_host_list=['host_0', 'host_2'])
        prev = self._generate_default_service_states()
        request_spec = self._get_vol_creation_request(num_vols=3,
                                                      drive_ix=3,
                                                      size=50)
        self.sched.schedule_create_volumes(self.context,
                                           request_spec,
                                           availability_zone=None)

        self.assertEqual(len(scheduled_volumes), 3)
        self.assertEqual(scheduled_volumes[0]['vol']['host'], 'host_4')
        self.assertEqual(scheduled_volumes[1]['vol']['host'], 'host_3')
        self.assertEqual(scheduled_volumes[2]['vol']['host'], 'host_1')

        cur = self._get_service_states()
        for host in ['host_1', 'host_3', 'host_4']:
            cur_dtype = cur[host]['volume']['drive_qos_info']['name_3']
            prev_dtype = prev[host]['volume']['drive_qos_info']['name_3']

            self.assertEqual(cur_dtype['DriveType'], prev_dtype['DriveType'])
            self.assertEqual(cur_dtype['FullDrive']['NumFreeDrives'],
                             prev_dtype['FullDrive']['NumFreeDrives'] - 1)
            self.assertEqual(cur_dtype['FullDrive']['NumOccupiedDrives'],
                             prev_dtype['FullDrive']['NumOccupiedDrives'] + 1)

            self.assertEqual(prev_dtype['PartitionDrive']
                                            ['NumOccupiedPartitions'], 0)
            self.assertEqual(cur_dtype['PartitionDrive']
                                            ['NumOccupiedPartitions'], 1)
            self.assertEqual(cur_dtype['PartitionDrive']
                                            ['NumFreePartitions'], 5)
            self.assertEqual(prev_dtype['PartitionDrive']
                                            ['NumFreePartitions'], 0)
            self.assertEqual(prev_dtype['PartitionDrive']
                                            ['PartitionSize'], 0)
