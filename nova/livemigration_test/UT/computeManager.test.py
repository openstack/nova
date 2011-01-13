#!/usr/bin/python
# -*- coding: UTF-8 -*-


import sys
import os
import unittest
import commands
import re
import logging

from mock import Mock
import twisted

# getting /nova-inst-dir
NOVA_DIR = os.path.abspath(sys.argv[0])
for i in range(4):
    NOVA_DIR = os.path.dirname(NOVA_DIR)

try:
    print
    print 'checking %s/bin/nova-manage exists, set the NOVA_DIR properly..' \
            % NOVA_DIR
    print

    sys.path.append(NOVA_DIR)

    from nova.compute.manager import ComputeManager
    from nova.virt.libvirt_conn import LibvirtConnection

    from nova import context
    from nova import db
    from nova import exception
    from nova import flags
    from nova import quota
    from nova import utils
    from nova.auth import manager
    from nova.cloudpipe import pipelib
    from nova import rpc
    from nova.api.ec2 import cloud
    from nova.compute import power_state

    from nova.db.sqlalchemy.models import *


except:
    print 'set correct NOVA_DIR in this script. '
    raise


class tmpStdout:
    def __init__(self):
        self.buffer = ""

    def write(self, arg):
        self.buffer += arg

    def writelines(self, arg):
        self.buffer += arg

    def flush(self):
        print 'flush'
        self.buffer = ''


class tmpStderr(tmpStdout):
    def write(self, arg):
        self.buffer += arg

    def flush(self):
        pass

    def realFlush(self):
        self.buffer = ''

dummyCallReturnValue={ 0:True }
dummyCallCount=0
def dummyCall(context, topic, method): 
    global dummyCallReturnValue, dummyCallCount
    if dummyCallCount in dummyCallReturnValue.keys() : 
        ret = dummyCallReturnValue[ dummyCallCount ]
        dummyCallCount += 1
        return ret
    else : 
        dummyCallCount += 1
        return False


class ComputeTestFunctions(unittest.TestCase):

    stdout = None
    stdoutBak = None
    stderr = None
    stderrBak = None
    manager = None

    # 共通の初期化処理
    def setUp(self):
        """common init method. """

        #if self.stdout is None:
        #    self.__class__.stdout = tmpStdout()
        #self.stdoutBak = sys.stdout
        #sys.stdout = self.stdout
        if self.stderr is None:
            self.__class__.stderr = tmpStderr()
        self.stderrBak = sys.stderr
        sys.stderr = self.stderr

        self.host = 'openstack2-api'
        if self.manager is None:
            self.__class__.manager = ComputeManager(host=self.host)

        self.setTestData()
        self.setMocks()

    def setTestData(self):

        self.host1 = Host()
        for key, val in [('name', 'host1'), ('cpu', 5),
                ('memory_mb', 20480), ('hdd_gb', 876)]:
            self.host1.__setitem__(key, val)

        self.host2 = Host()
        for key, val in [('name', 'host2'), ('cpu', 5),
                ('memory_mb', 20480), ('hdd_gb', 876)]:
            self.host2.__setitem__(key, val)

        self.instance1 = Instance()
        for key, val in [('id', 1), ('host', 'host1'),
                ('hostname', 'i-12345'), ('state', power_state.RUNNING),
                ('project_id', 'testPJ'), ('vcpus', 3), ('memory_mb', 1024),
                ('hdd_gb', 5), ('internal_id', 12345)]:
            self.instance1.__setitem__(key, val)

        self.instance2 = Instance()
        for key, val in [('id', 2), ('host', 'host1'),
                ('hostname', 'i-12345'), ('state', power_state.RUNNING),
                ('project_id', 'testPJ'), ('vcpus', 3), ('memory_mb', 1024),
                ('hdd_gb', 5)]:
            self.instance2.__setitem__(key, val)

        self.fixed_ip1 = FixedIp()
        for key, val in [('id', 1), ('address', '1.1.1.1'),
                ('network_id', '1'), ('instance_id', 1)]:
            self.fixed_ip1.__setitem__(key, val)

        self.vol1 = Volume()
        for key, val in [('id', 1), ('ec2_id', 'vol-qijjuc7e'),
                ('availability_zone', 'nova'), ('host', 'host1')]:
            self.vol1.__setitem__(key, val)

        self.vol2 = Volume()
        for key, val in [('id', 2), ('ec2_id', 'vol-qi22222'),
                ('availability_zone', 'nova'), ('host', 'host1')]:
            self.vol2.__setitem__(key, val)

        self.secgrp1 = Volume()
        for key, val in [('id', 1), ('ec2_id', 'default')]:
            self.secgrp1.__setitem__(key, val)

        self.secgrp2 = Volume()
        for key, val in [('id', 2), ('ec2_id', 'def2')]:
            self.secgrp2.__setitem__(key, val)

        self.netref1 = Network()

    def setMocks(self):

        # mocks for pre_live_migration
        self.ctxt = context.get_admin_context()
        db.instance_get = Mock(return_value=self.instance1)
        db.instance_get_fixed_address = Mock(return_value = self.fixed_ip1)
        db.volume_get_all_by_instance \
            = Mock(return_value=[self.vol1, self.vol2])
        db.volume_get_shelf_and_blade = Mock(return_value=(3, 4))
        db.instance_get_fixed_address = Mock(return_value=self.fixed_ip1)
        db.security_group_get_by_instance \
            = Mock(return_value=[self.secgrp1, self.secgrp2])
        self.manager.driver.ensure_filtering_rules_for_instance \
            = Mock(return_value=None)
        self.manager.driver.nwfilter_for_instance_exists = Mock(return_value=None)
        self.manager.network_manager.setup_compute_network \
            = Mock(return_value=None)
        # mocks for live_migration_
        rpc.call = Mock(return_value=True)
        db.instance_set_state = Mock(return_value=True)
        

    # ---> test for nova.compute.manager.pre_live_migration()
    def test01(self):
        """01: NotFound error occurs on finding instance on DB. """

        db.instance_get = Mock(side_effect=exception.NotFound('ERR'))

        self.assertRaises(exception.NotFound,
                         self.manager.pre_live_migration,
                         self.ctxt,
                         'dummy_ec2_id',
                         'host2')

    def test02(self):
        """02: Unknown error occurs on finding instance on DB. """

        db.instance_get = Mock(side_effect=TypeError('ERR'))

        self.assertRaises(TypeError,
                         self.manager.pre_live_migration,
                         self.ctxt,
                         'dummy_ec2_id',
                         'host2')

    # the case of no fixed ip found on DB( instance_get_fixed_address 
    # returns unknown error) is ommited because it is same as test02

    def test03(self):
        """03: no fixed ip found on DB,  """

        db.instance_get_fixed_address = Mock(return_value=None)

        try : 
            self.manager.pre_live_migration(self.ctxt, 'dummy_ec2_id', 'host2')
        except exception.NotFound, e:
            c1 = ( 0 < e.message.find('doesnt have fixed_ip'))
            self.assertTrue(c1, True)
        return False


    def test04(self):
        """04: no fixed_ip found on DB. """

        db.instance_get_fixed_address \
            = Mock(side_effect=exception.NotFound('ERR'))

        self.assertRaises(exception.NotFound,
                         self.manager.pre_live_migration,
                         self.ctxt,
                         'dummy_ec2_id',
                         'host2')

    def test05(self):
        """05: NotAuthrized occurs on finding volume on DB. """

        db.volume_get_all_by_instance \
            = Mock(side_effect=exception.NotAuthorized('ERR'))

        self.assertRaises(exception.NotAuthorized,
                         self.manager.pre_live_migration,
                         self.ctxt,
                         'dummy_ec2_id',
                         'host2')

    def test06(self):
        """06: Unexpected exception occurs on finding volume on DB. """

        db.volume_get_all_by_instance = Mock(side_effect=TypeError('ERR'))

        self.assertRaises(TypeError,
                         self.manager.pre_live_migration,
                         self.ctxt,
                         'dummy_ec2_id',
                         'host2')

    def test07(self):
        """07: self.network_manager.setup_compute_network causes ProcessExecutionError. """
        self.manager.network_manager.setup_compute_network \
            = Mock(side_effect=exception.ProcessExecutionError("ERR"))

        self.assertRaises(exception.ProcessExecutionError,
                         self.manager.pre_live_migration,
                         self.ctxt,
                         'dummy_ec2_id',
                         'host2')


    def test08(self):
        """08: self.manager.network_manager.setup_compute_network
        exception.NotFound. """
        self.manager.network_manager.setup_compute_network \
            = Mock(side_effect=exception.NotFound("ERR"))

        self.assertRaises(exception.NotFound,
                         self.manager.pre_live_migration,
                         self.ctxt,
                         'dummy_ec2_id',
                         'host2')

    # ensure_filtering_rules_for_instance mainly access to libvirt.
    # Therefore, exception may be libvirt-related one, but cannot expect.
    # so, for test cases, just expect unkonwn exception( TypeError is just a case)
    def test09(self):
        """09: self.driver.ensure_filtering_rules_for_instance raises unexpected exception. """
        self.manager.driver.ensure_filtering_rules_for_instance \
            = Mock(side_effect=TypeError('ERR'))

        self.assertRaises(TypeError,
                         self.manager.pre_live_migration,
                         self.ctxt,
                         'dummy_ec2_id',
                         'host2')

    def test10(self):
        """10: volume/fixed_ip found on DB, all procedure finish
        successfully.. """

        result = self.manager.pre_live_migration(self.ctxt, 'dummy_ec2_id',
            'host2')
        self.assertEqual(result, None)

    # ---> test for nova.compute.manager.live_migration()

    def test11(self):
        """11: if db_instance_get issues NotFound.
        """
        db.instance_get = Mock(side_effect=exception.NotFound("ERR"))

        self.assertRaises(exception.NotFound,
                         self.manager.live_migration,
                         self.ctxt,
                         'dummy_ec2_id',
                         'host2')

    def test12(self):
        """12: if db_instance_get issues Unexpected Error.
        """
        db.instance_get = Mock(side_effect=TypeError("ERR"))

        self.assertRaises(TypeError,
                         self.manager.live_migration,
                         self.ctxt,
                         'dummy_ec2_id',
                         'host2')

    def test13(self):
        """13: if rpc.call returns rpc.RemoteError. """

        rpc.call = Mock(return_value=rpc.RemoteError(None, None, None))
        db.instance_set_state = Mock(return_value=True)
        try : 
            self.manager.live_migration(self.ctxt, 'dummy_ec2_id','host2')
        except rpc.RemoteError, e: 
            c1 = ( 0 < e.message.find('Pre live migration for'))
            self.assertTrue(c1, True)
        return False

    def test14(self):
        """14: if rpc.call returns rpc.RemoteError and instance_set_state
           also ends up err. (then , unexpected err occurs, in this case
           TypeError)
        """
        rpc.call = Mock(return_value=rpc.RemoteError(None, None, None))
        db.instance_set_state = Mock(side_effect=TypeError("ERR"))

        try : 
            self.manager.live_migration(self.ctxt, 'dummy_ec2_id','host2')
        except TypeError, e: 
            c1 = ( 0 < e.message.find('Pre live migration for'))
            self.assertTrue(c1, True)
        return False


    def test15(self):
        """15: if rpc.call returns rpc.RemoteError and volume_get_all_by_instance
           also ends up err. (then , unexpected err occurs, in this case
           TypeError)
        """
        rpc.call = Mock(return_value=rpc.RemoteError(None, None, None))
        db.volume_get_all_by_instance = Mock(side_effect=exception.NotAuthorized("ERR"))

        try : 
            self.manager.live_migration(self.ctxt, 'dummy_ec2_id','host2')
        except exception.NotAuthorized, e: 
            c1 = ( 0 < e.message.find('Pre live migration for'))
            self.assertTrue(c1, True)
        return False


    def test16(self):
        """16: if rpc.call finish successfully, e, and live_migration raises
        TypeError(Unexpected error), which means unexpected libvirt-related one. """
        rpc.call = Mock(return_value=None)
        ret = self.manager.driver.live_migration \
            = Mock(side_effect=TypeError("ERR"))

        self.assertRaises(TypeError,
                         self.manager.live_migration,
                         self.ctxt,
                         'dummy_ec2_id',
                         'host2')

    def test17(self):
        """17: everything goes well. """
        self.manager.driver.live_migration = Mock(return_value=True)
        ret = self.manager.live_migration(self.ctxt, 'i-12345', 'host1')
        self.assertEqual(ret, None)

    def tearDown(self):
        """common terminating method. """
        self.stderr.realFlush()
        sys.stderr = self.stderrBak
        #sys.stdout = self.stdoutBak

if __name__ == '__main__':
    logging.getLogger().setLevel(logging.DEBUG)
    #unittest.main()

    suite = unittest.TestLoader().loadTestsFromTestCase(ComputeTestFunctions)
    unittest.TextTestRunner(verbosity=2).run(suite)

    #suite = unittest.TestSuite()
    #suite.addTest(ComputeTestFunctions("test15"))
    #suite.addTest(ComputeTestFunctions("test16"))
    #unittest.TextTestRunner(verbosity=2).run(suite)
