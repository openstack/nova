# vim: tabstop=4 shiftwidth=4 softtabstop=4

# Copyright 2010 United States Government as represented by the
# Administrator of the National Aeronautics and Space Administration.
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
Instance Monitoring:

    Optionally may be run on each compute node. Provides RRD
    based statistics and graphs and makes them internally available
    in the object store.
"""

import datetime
import os
import time

import boto
import boto.s3
import rrdtool
from twisted.internet import task
from twisted.application import service

from nova import flags
from nova import log as logging
from nova.virt import connection as virt_connection


FLAGS = flags.FLAGS
flags.DEFINE_integer('monitoring_instances_delay', 5,
                     'Sleep time between updates')
flags.DEFINE_integer('monitoring_instances_step', 300,
                     'Interval of RRD updates')
flags.DEFINE_string('monitoring_rrd_path', '$state_path/monitor/instances',
                    'Location of RRD files')


RRD_VALUES = {
    'cpu': [
        'DS:cpu:GAUGE:600:0:100',
        'RRA:AVERAGE:0.5:1:800',
        'RRA:AVERAGE:0.5:6:800',
        'RRA:AVERAGE:0.5:24:800',
        'RRA:AVERAGE:0.5:288:800',
        'RRA:MAX:0.5:1:800',
        'RRA:MAX:0.5:6:800',
        'RRA:MAX:0.5:24:800',
        'RRA:MAX:0.5:288:800',
        ],
    'net': [
        'DS:rx:COUNTER:600:0:1250000',
        'DS:tx:COUNTER:600:0:1250000',
        'RRA:AVERAGE:0.5:1:800',
        'RRA:AVERAGE:0.5:6:800',
        'RRA:AVERAGE:0.5:24:800',
        'RRA:AVERAGE:0.5:288:800',
        'RRA:MAX:0.5:1:800',
        'RRA:MAX:0.5:6:800',
        'RRA:MAX:0.5:24:800',
        'RRA:MAX:0.5:288:800',
        ],
    'disk': [
        'DS:rd:COUNTER:600:U:U',
        'DS:wr:COUNTER:600:U:U',
        'RRA:AVERAGE:0.5:1:800',
        'RRA:AVERAGE:0.5:6:800',
        'RRA:AVERAGE:0.5:24:800',
        'RRA:AVERAGE:0.5:288:800',
        'RRA:MAX:0.5:1:800',
        'RRA:MAX:0.5:6:800',
        'RRA:MAX:0.5:24:800',
        'RRA:MAX:0.5:444:800',
        ]}


utcnow = datetime.datetime.utcnow


LOG = logging.getLogger('nova.compute.monitor')


def update_rrd(instance, name, data):
    """
    Updates the specified RRD file.
    """
    filename = os.path.join(instance.get_rrd_path(), '%s.rrd' % name)

    if not os.path.exists(filename):
        init_rrd(instance, name)

    timestamp = int(time.mktime(utcnow().timetuple()))
    rrdtool.update(filename, '%d:%s' % (timestamp, data))


def init_rrd(instance, name):
    """
    Initializes the specified RRD file.
    """
    path = os.path.join(FLAGS.monitoring_rrd_path, instance.instance_id)

    if not os.path.exists(path):
        os.makedirs(path)

    filename = os.path.join(path, '%s.rrd' % name)

    if not os.path.exists(filename):
        rrdtool.create(
            filename,
            '--step', '%d' % FLAGS.monitoring_instances_step,
            '--start', '0',
            *RRD_VALUES[name])


def graph_cpu(instance, duration):
    """
    Creates a graph of cpu usage for the specified instance and duration.
    """
    path = instance.get_rrd_path()
    filename = os.path.join(path, 'cpu-%s.png' % duration)

    rrdtool.graph(
        filename,
        '--disable-rrdtool-tag',
        '--imgformat', 'PNG',
        '--width', '400',
        '--height', '120',
        '--start', 'now-%s' % duration,
        '--vertical-label', '% cpu used',
        '-l', '0',
        '-u', '100',
        'DEF:cpu=%s:cpu:AVERAGE' % os.path.join(path, 'cpu.rrd'),
        'AREA:cpu#eacc00:% CPU',)

    store_graph(instance.instance_id, filename)


def graph_net(instance, duration):
    """
    Creates a graph of network usage for the specified instance and duration.
    """
    path = instance.get_rrd_path()
    filename = os.path.join(path, 'net-%s.png' % duration)

    rrdtool.graph(
        filename,
        '--disable-rrdtool-tag',
        '--imgformat', 'PNG',
        '--width', '400',
        '--height', '120',
        '--start', 'now-%s' % duration,
        '--vertical-label', 'bytes/s',
        '--logarithmic',
        '--units', 'si',
        '--lower-limit', '1000',
        '--rigid',
        'DEF:rx=%s:rx:AVERAGE' % os.path.join(path, 'net.rrd'),
        'DEF:tx=%s:tx:AVERAGE' % os.path.join(path, 'net.rrd'),
        'AREA:rx#00FF00:In traffic',
        'LINE1:tx#0000FF:Out traffic',)

    store_graph(instance.instance_id, filename)


def graph_disk(instance, duration):
    """
    Creates a graph of disk usage for the specified duration.
    """
    path = instance.get_rrd_path()
    filename = os.path.join(path, 'disk-%s.png' % duration)

    rrdtool.graph(
        filename,
        '--disable-rrdtool-tag',
        '--imgformat', 'PNG',
        '--width', '400',
        '--height', '120',
        '--start', 'now-%s' % duration,
        '--vertical-label', 'bytes/s',
        '--logarithmic',
        '--units', 'si',
        '--lower-limit', '1000',
        '--rigid',
        'DEF:rd=%s:rd:AVERAGE' % os.path.join(path, 'disk.rrd'),
        'DEF:wr=%s:wr:AVERAGE' % os.path.join(path, 'disk.rrd'),
        'AREA:rd#00FF00:Read',
        'LINE1:wr#0000FF:Write',)

    store_graph(instance.instance_id, filename)


def store_graph(instance_id, filename):
    """
    Transmits the specified graph file to internal object store on cloud
    controller.
    """
    # TODO(devcamcar): Need to use an asynchronous method to make this
    #       connection. If boto has some separate method that generates
    #       the request it would like to make and another method to parse
    #       the response we can make our own client that does the actual
    #       request and hands it off to the response parser.
    s3 = boto.s3.connection.S3Connection(
        aws_access_key_id=FLAGS.aws_access_key_id,
        aws_secret_access_key=FLAGS.aws_secret_access_key,
        is_secure=False,
        calling_format=boto.s3.connection.OrdinaryCallingFormat(),
        port=FLAGS.s3_port,
        host=FLAGS.s3_host)
    bucket_name = '_%s.monitor' % instance_id

    # Object store isn't creating the bucket like it should currently
    # when it is first requested, so have to catch and create manually.
    try:
        bucket = s3.get_bucket(bucket_name)
    except Exception:
        bucket = s3.create_bucket(bucket_name)

    key = boto.s3.Key(bucket)
    key.key = os.path.basename(filename)
    key.set_contents_from_filename(filename)


class Instance(object):
    def __init__(self, conn, instance_id):
        self.conn = conn
        self.instance_id = instance_id
        self.last_updated = datetime.datetime.min
        self.cputime = 0
        self.cputime_last_updated = None

        init_rrd(self, 'cpu')
        init_rrd(self, 'net')
        init_rrd(self, 'disk')

    def needs_update(self):
        """
        Indicates whether this instance is due to have its statistics updated.
        """
        delta = utcnow() - self.last_updated
        return delta.seconds >= FLAGS.monitoring_instances_step

    def update(self):
        """
        Updates the instances statistics and stores the resulting graphs
        in the internal object store on the cloud controller.
        """
        LOG.debug(_('updating %s...'), self.instance_id)

        try:
            data = self.fetch_cpu_stats()
            if data is not None:
                LOG.debug('CPU: %s', data)
                update_rrd(self, 'cpu', data)

            data = self.fetch_net_stats()
            LOG.debug('NET: %s', data)
            update_rrd(self, 'net', data)

            data = self.fetch_disk_stats()
            LOG.debug('DISK: %s', data)
            update_rrd(self, 'disk', data)

            # TODO(devcamcar): Turn these into pool.ProcessPool.execute() calls
            # and make the methods @defer.inlineCallbacks.
            graph_cpu(self, '1d')
            graph_cpu(self, '1w')
            graph_cpu(self, '1m')

            graph_net(self, '1d')
            graph_net(self, '1w')
            graph_net(self, '1m')

            graph_disk(self, '1d')
            graph_disk(self, '1w')
            graph_disk(self, '1m')
        except Exception:
            LOG.exception(_('unexpected error during update'))

        self.last_updated = utcnow()

    def get_rrd_path(self):
        """
        Returns the path to where RRD files are stored.
        """
        return os.path.join(FLAGS.monitoring_rrd_path, self.instance_id)

    def fetch_cpu_stats(self):
        """
        Returns cpu usage statistics for this instance.
        """
        info = self.conn.get_info(self.instance_id)

        # Get the previous values.
        cputime_last = self.cputime
        cputime_last_updated = self.cputime_last_updated

        # Get the raw CPU time used in nanoseconds.
        self.cputime = float(info['cpu_time'])
        self.cputime_last_updated = utcnow()

        LOG.debug('CPU: %d', self.cputime)

        # Skip calculation on first pass. Need delta to get a meaningful value.
        if cputime_last_updated == None:
            return None

        # Calculate the number of seconds between samples.
        d = self.cputime_last_updated - cputime_last_updated
        t = d.days * 86400 + d.seconds

        LOG.debug('t = %d', t)

        # Calculate change over time in number of nanoseconds of CPU time used.
        cputime_delta = self.cputime - cputime_last

        LOG.debug('cputime_delta = %s', cputime_delta)

        # Get the number of virtual cpus in this domain.
        vcpus = int(info['num_cpu'])

        LOG.debug('vcpus = %d', vcpus)

        # Calculate CPU % used and cap at 100.
        return min(cputime_delta / (t * vcpus * 1.0e9) * 100, 100)

    def fetch_disk_stats(self):
        """
        Returns disk usage statistics for this instance.
        """
        rd = 0
        wr = 0

        disks = self.conn.get_disks(self.instance_id)

        # Aggregate the read and write totals.
        for disk in disks:
            try:
                rd_req, rd_bytes, wr_req, wr_bytes, errs = \
                    self.conn.block_stats(self.instance_id, disk)
                rd += rd_bytes
                wr += wr_bytes
            except TypeError:
                iid = self.instance_id
                LOG.error(_('Cannot get blockstats for "%(disk)s"'
                        ' on "%(iid)s"') % locals())
                raise

        return '%d:%d' % (rd, wr)

    def fetch_net_stats(self):
        """
        Returns network usage statistics for this instance.
        """
        rx = 0
        tx = 0

        interfaces = self.conn.get_interfaces(self.instance_id)

        # Aggregate the in and out totals.
        for interface in interfaces:
            try:
                stats = self.conn.interface_stats(self.instance_id, interface)
                rx += stats[0]
                tx += stats[4]
            except TypeError:
                iid = self.instance_id
                LOG.error(_('Cannot get ifstats for "%(interface)s"'
                        ' on "%(iid)s"') % locals())
                raise

        return '%d:%d' % (rx, tx)


class InstanceMonitor(object, service.Service):
    """
    Monitors the running instances of the current machine.
    """

    def __init__(self):
        """
        Initialize the monitoring loop.
        """
        self._instances = {}
        self._loop = task.LoopingCall(self.updateInstances)

    def startService(self):
        self._instances = {}
        self._loop.start(interval=FLAGS.monitoring_instances_delay)
        service.Service.startService(self)

    def stopService(self):
        self._loop.stop()
        service.Service.stopService(self)

    def updateInstances(self):
        """
        Update resource usage for all running instances.
        """
        try:
            conn = virt_connection.get_connection(read_only=True)
        except Exception, exn:
            LOG.exception(_('unexpected exception getting connection'))
            time.sleep(FLAGS.monitoring_instances_delay)
            return

        domain_ids = conn.list_instances()
        try:
            self.updateInstances_(conn, domain_ids)
        except Exception, exn:
            LOG.exception('updateInstances_')

    def updateInstances_(self, conn, domain_ids):
        for domain_id in domain_ids:
            if not domain_id in self._instances:
                instance = Instance(conn, domain_id)
                self._instances[domain_id] = instance
                LOG.debug(_('Found instance: %s'), domain_id)

        for key in self._instances.keys():
            instance = self._instances[key]
            if instance.needs_update():
                instance.update()
