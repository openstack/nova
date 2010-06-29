# vim: tabstop=4 shiftwidth=4 softtabstop=4
# Copyright [2010] [Anso Labs, LLC]
#
#    Licensed under the Apache License, Version 2.0 (the "License");
#    you may not use this file except in compliance with the License.
#    You may obtain a copy of the License at
#
#        http://www.apache.org/licenses/LICENSE-2.0
#
#    Unless required by applicable law or agreed to in writing, software
#    distributed under the License is distributed on an "AS IS" BASIS,
#    WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
#    See the License for the specific language governing permissions and
#    limitations under the License.

"""
Instance Monitoring:

    Optionally may be run on each compute node. Provides RRD
    based statistics and graphs and makes them internally available
    in the object store.
"""

import datetime
import logging
import os
import sys
import time

try:
    import libvirt
except Exception, err:
    logging.warning('no libvirt found')

from nova import flags
from nova import vendor
import boto
import boto.s3
import libxml2
import rrdtool
from twisted.internet import defer
from twisted.internet import task
from twisted.application import service

FLAGS = flags.FLAGS
flags.DEFINE_integer(
    'monitoring_instances_delay', 5, 'Sleep time between updates')
flags.DEFINE_integer(
    'monitoring_instances_step', 300, 'Interval of RRD updates')
flags.DEFINE_string(
    'monitoring_rrd_path', '/var/nova/monitor/instances',
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
    ]
}


utcnow = datetime.datetime.utcnow

def update_rrd(instance, name, data):
    """
    Updates the specified RRD file.
    """
    filename = os.path.join(instance.get_rrd_path(), '%s.rrd' % name)
    
    if not os.path.exists(filename):
        init_rrd(instance, name)
    
    timestamp = int(time.mktime(utcnow().timetuple()))
    rrdtool.update (
        filename,
        '%d:%s' % (timestamp, data)
    )

def init_rrd(instance, name):
    """
    Initializes the specified RRD file.
    """
    path = os.path.join(FLAGS.monitoring_rrd_path, instance.instance_id)
    
    if not os.path.exists(path):
        os.makedirs(path)
    
    filename = os.path.join(path, '%s.rrd' % name)
    
    if not os.path.exists(filename):
        rrdtool.create (
            filename,
            '--step', '%d' % FLAGS.monitoring_instances_step,
            '--start', '0',
            *RRD_VALUES[name]
        )
        
def get_disks(domain):
    """
    Returns a list of all block devices for this domain.
    """
    # TODO(devcamcar): Replace libxml2 with etree.
    xml = domain.XMLDesc(0)
    doc = None

    try:
        doc = libxml2.parseDoc(xml)
    except:
        return []

    ctx = doc.xpathNewContext()
    disks = []

    try:
        ret = ctx.xpathEval('/domain/devices/disk')
    
        for node in ret:
            devdst = None
        
            for child in node.children:
                if child.name == 'target':
                    devdst = child.prop('dev')
        
            if devdst == None:
                continue
        
            disks.append(devdst)
    finally:
        if ctx != None:
            ctx.xpathFreeContext()
        if doc != None:
            doc.freeDoc()
    
    return disks

def get_interfaces(domain):
    """
    Returns a list of all network interfaces for this instance.
    """
    # TODO(devcamcar): Replace libxml2 with etree.
    xml = domain.XMLDesc(0)
    doc = None

    try:
        doc = libxml2.parseDoc(xml)
    except:
        return []

    ctx = doc.xpathNewContext()
    interfaces = []

    try:
        ret = ctx.xpathEval('/domain/devices/interface')
    
        for node in ret:
            devdst = None
        
            for child in node.children:
                if child.name == 'target':
                    devdst = child.prop('dev')
        
            if devdst == None:
                continue
        
            interfaces.append(devdst)
    finally:
        if ctx != None:
            ctx.xpathFreeContext()
        if doc != None:
            doc.freeDoc()

    return interfaces

        
def graph_cpu(instance, duration):
    """
    Creates a graph of cpu usage for the specified instance and duration.
    """
    path = instance.get_rrd_path()
    filename = os.path.join(path, 'cpu-%s.png' % duration)
    
    rrdtool.graph (
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
        'AREA:cpu#eacc00:% CPU',
    )
    
    store_graph(instance.instance_id, filename)

def graph_net(instance, duration):
    """
    Creates a graph of network usage for the specified instance and duration.
    """
    path = instance.get_rrd_path()
    filename = os.path.join(path, 'net-%s.png' % duration)
    
    rrdtool.graph (
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
        'LINE1:tx#0000FF:Out traffic',
    )
    
    store_graph(instance.instance_id, filename)
    
def graph_disk(instance, duration):
    """
    Creates a graph of disk usage for the specified duration.
    """        
    path = instance.get_rrd_path()
    filename = os.path.join(path, 'disk-%s.png' % duration)
    
    rrdtool.graph (
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
        'LINE1:wr#0000FF:Write',
    )
    
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
        aws_access_key_id='admin',
        aws_secret_access_key='admin',
        is_secure=False,
        calling_format=boto.s3.connection.OrdinaryCallingFormat(),
        port=FLAGS.s3_port,
        host=FLAGS.s3_host
    )
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
    def __init__(self, conn, domain):
        self.conn = conn
        self.domain = domain
        self.instance_id = domain.name()
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
        logging.debug('updating %s...', self.instance_id)

        try:
            data = self.fetch_cpu_stats()
            if data != None:
                logging.debug('CPU: %s', data)
                update_rrd(self, 'cpu', data)
        
            data = self.fetch_net_stats()
            logging.debug('NET: %s', data)
            update_rrd(self, 'net', data)

            data = self.fetch_disk_stats()
            logging.debug('DISK: %s', data)
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
            logging.exception('unexpected error during update')

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
        info = self.domain.info()

        # Get the previous values.
        cputime_last = self.cputime
        cputime_last_updated = self.cputime_last_updated

        # Get the raw CPU time used in nanoseconds.
        self.cputime = float(info[4])
        self.cputime_last_updated = utcnow()

        logging.debug('CPU: %d', self.cputime)

        # Skip calculation on first pass. Need delta to get a meaningful value.
        if cputime_last_updated == None:
            return None

        # Calculate the number of seconds between samples.
        d = self.cputime_last_updated - cputime_last_updated
        t = d.days * 86400 + d.seconds
        
        logging.debug('t = %d', t)

        # Calculate change over time in number of nanoseconds of CPU time used.
        cputime_delta = self.cputime - cputime_last
        
        logging.debug('cputime_delta = %s', cputime_delta)

        # Get the number of virtual cpus in this domain.
        vcpus = int(info[3])
        
        logging.debug('vcpus = %d', vcpus)

        # Calculate CPU % used and cap at 100.
        return min(cputime_delta / (t * vcpus * 1.0e9) * 100, 100)

    def fetch_disk_stats(self):
        """
        Returns disk usage statistics for this instance.
        """
        rd = 0
        wr = 0
    
        # Get a list of block devices for this instance.
        disks = get_disks(self.domain)
    
        # Aggregate the read and write totals.
        for disk in disks:
            try:
                rd_req, rd_bytes, wr_req, wr_bytes, errs = \
                    self.domain.blockStats(disk)
                rd += rd_bytes
                wr += wr_bytes
            except TypeError:
                logging.error('Cannot get blockstats for "%s" on "%s"',
                              disk, self.instance_id)
                raise
        
        return '%d:%d' % (rd, wr)

    def fetch_net_stats(self):
        """
        Returns network usage statistics for this instance.
        """
        rx = 0
        tx = 0
    
        # Get a list of all network interfaces for this instance.
        interfaces = get_interfaces(self.domain)
    
        # Aggregate the in and out totals.
        for interface in interfaces:
            try:
                stats = self.domain.interfaceStats(interface)
                rx += stats[0]
                tx += stats[4]
            except TypeError:
                logging.error('Cannot get ifstats for "%s" on "%s"',
                              interface, self.instance_id)
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
            conn = libvirt.openReadOnly(None)
        except libvirt.libvirtError:
            logging.exception('unexpected libvirt error')
            time.sleep(FLAGS.monitoring_instances_delay)
            return
    
        domain_ids = conn.listDomainsID()
        
        for domain_id in domain_ids:
            if not domain_id in self._instances:                    
                domain = conn.lookupByID(domain_id)
                instance = Instance(conn, domain)
                self._instances[domain_id] = instance
                logging.debug('Found instance: %s', instance.instance_id)
        
        for key in self._instances.keys():
            instance = self._instances[key]
            if instance.needs_update():
                instance.update()
