<<<<<<< TREE
#!/usr/bin/python
# -*- coding: UTF-8 -*-

NOVA_DIR='/opt/nova-2010.4'

import sys
import unittest
import commands
import re
import logging
import libvirt

from mock import Mock
import twisted

try : 
    print
    print 'checking %s/bin/nova-manage exists, set the NOVA_DIR properly..' % NOVA_DIR
    print

    sys.path.append(NOVA_DIR)

    from nova.compute.manager import ComputeManager
    from nova.virt import libvirt_conn

    from nova import context
    from nova import db
    from nova import exception
    from nova import flags
    from nova import quota
    from nova import utils
    from nova import process
    from nova.auth import manager
    from nova.cloudpipe import pipelib
    from nova import rpc
    from nova.api.ec2 import cloud
    from nova.compute import power_state

    from nova.db.sqlalchemy.models import *


except: 
    print 'set PYTHONPATH to nova-install-dir'
    raise 


class tmpStdout:
    def __init__(self):
        self.buffer = ""
    def write(self,arg):
        self.buffer += arg
    def writelines(self, arg): 
        self.buffer += arg
    def flush(self):
        print 'flush'
        self.buffer = ''

class tmpStderr(tmpStdout):
    def write(self,arg):
        self.buffer += arg
    def flush(self):
        pass
    def realFlush(self):
        self.buffer = ''

class DummyLibvirtConn(object):
    nwfilterLookupByName = None
    def __init__(self): 
        pass


class LibvirtConnectionTestFunctions(unittest.TestCase):

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
            self.__class__.manager = libvirt_conn.get_connection(False)

        self.setTestData()
        self.setMocks()

    def setTestData(self):  

        self.host1 = Host()
        for key, val in [ ('name', 'host1'), ('cpu', 5), ('memory_mb', 20480), ('hdd_gb', 876) ]:
            self.host1.__setitem__(key, val)

        self.instance1 = Instance()
        for key, val in [ ('id', 1), ('host', 'host1'),   ('hostname', 'i-12345'), 
                          ('state', power_state.RUNNING), ('project_id', 'testPJ'),
                          ('vcpus', 3), ('memory_mb', 1024), ('hdd_gb', 5), ('internal_id',12345) ]:
            self.instance1.__setitem__(key, val)


        self.instance2 = Instance()
        for key, val in [ ('id', 2), ('host', 'host1'),   ('hostname', 'i-12345'), 
                          ('state', power_state.RUNNING), ('project_id', 'testPJ'),
                          ('vcpus', 3), ('memory_mb', 1024), ('hdd_gb', 5) ]:
            self.instance2.__setitem__(key, val)


        self.fixed_ip1 = FixedIp()
        for key, val in [ ('id', 1), ('address', '1.1.1.1'),   ('network_id', '1'), 
                          ('instance_id', 1)]:
            self.fixed_ip1.__setitem__(key, val)

        self.floating_ip1 = FloatingIp()
        for key, val in [ ('id', 1), ('address', '1.1.1.200') ]:
            self.floating_ip1.__setitem__(key, val)

        self.netref1 = Network()
        for key, val in [ ('id', 1) ]:
            self.netref1.__setitem__(key, val)


    def setMocks(self):  

        self.ctxt = context.get_admin_context()
        db.instance_get_fixed_address = Mock(return_value = '1.1.1.1')
        db.fixed_ip_update =  Mock(return_value = None)
        db.fixed_ip_get_network = Mock(return_value = self.netref1)
        db.network_update = Mock(return_value = None)
        db.instance_get_floating_address = Mock(return_value = '1.1.1.200')
        db.floating_ip_get_by_address = Mock(return_value = self.floating_ip1)
        db.floating_ip_update = Mock(return_value = None)
        db.instance_update = Mock(return_value = None)


    # ---> test for nova.virt.libvirt_conn.nwfilter_for_instance_exists()

    def test01(self):
        """01: libvirt.libvirtError occurs.  """

        self.manager._wrapped_conn = DummyLibvirtConn()
        self.manager._test_connection = Mock(return_value=True)
        self.manager._conn.nwfilterLookupByName = \
            Mock(side_effect=libvirt.libvirtError("ERR")) 
        ret = self.manager.nwfilter_for_instance_exists(self.instance1)
        self.assertEqual(ret, False)

    def test02(self):
        """02: libvirt.libvirtError not occurs.  """

        self.manager._wrapped_conn = DummyLibvirtConn()
        self.manager._test_connection = Mock(return_value=True)
        self.manager._conn.nwfilterLookupByName = \
            Mock(return_value=True) 
        ret = self.manager.nwfilter_for_instance_exists(self.instance1)
        self.assertEqual(ret, True)

    # ---> test for nova.virt.libvirt_conn.live_migraiton()

    def test03(self):
        """03: Unexpected exception occurs on finding volume on DB. """

        utils.execute = Mock( side_effect=process.ProcessExecutionError('ERR') )

        self.assertRaises(process.ProcessExecutionError,
                         self.manager.live_migration,
                         self.instance1,
                         'host2')

    # ---> other case cannot be tested because live_migraiton
    #      is synchronized/asynchronized method are mixed together


    # ---> test for nova.virt.libvirt_conn._post_live_migraiton

    def test04(self):
        """04: instance_ref is not nova.db.sqlalchemy.models.Instances"""

        self.assertRaises(TypeError,
                         self.manager._post_live_migration,
                         "dummy string",
                         'host2')

    def test05(self): 
        """05: db.instance_get_fixed_address return None"""

        db.instance_get_fixed_address  = Mock( return_value=None )
        ret = self.manager._post_live_migration(self.instance1, 'host1')
        c1 = (ret == None)
        c2 = (0 <= sys.stderr.buffer.find('fixed_ip is not found'))
        self.assertEqual(c1 and c2, True)

    def test06(self):
        """06: db.instance_get_fixed_address raises NotFound"""

        db.instance_get_fixed_address  = Mock( side_effect=exception.NotFound('ERR') )
        self.assertRaises(exception.NotFound,
                         self.manager._post_live_migration,
                         self.instance1,
                         'host2')

    def test07(self):
        """07: db.instance_get_fixed_address raises Unknown exception"""

        db.instance_get_fixed_address  = Mock( side_effect=TypeError('ERR') )
        self.assertRaises(TypeError,
                         self.manager._post_live_migration,
                         self.instance1,
                         'host1')

    def test08(self):
        """08: db.fixed_ip_update return NotFound. """

        db.fixed_ip_update =  Mock( side_effect=exception.NotFound('ERR') )
        self.assertRaises(exception.NotFound,
                         self.manager._post_live_migration,
                         self.instance1,
                         'host1')
        
    def test09(self):
        """09: db.fixed_ip_update return NotAuthorized. """
        db.fixed_ip_update =  Mock( side_effect=exception.NotAuthorized('ERR') )
        self.assertRaises(exception.NotAuthorized,
                         self.manager._post_live_migration,
                         self.instance1,
                         'host1')

    def test10(self):
        """10: db.fixed_ip_update return Unknown exception. """
        db.fixed_ip_update =  Mock( side_effect=TypeError('ERR') )
        self.assertRaises(TypeError,
                         self.manager._post_live_migration,
                         self.instance1,
                         'host1')
    
    def test11(self):
        """11: db.fixed_ip_get_network causes NotFound. """

        db.fixed_ip_get_network =  Mock( side_effect=exception.NotFound('ERR') )
        self.assertRaises(exception.NotFound,
                         self.manager._post_live_migration,
                         self.instance1,
                         'host1')
        
    # not tested db.fixed_ip_get_network raises NotAuthorized
    # because same test has been done at previous test.

    def test12(self):
        """12: db.fixed_ip_get_network causes Unknown exception. """

        db.fixed_ip_get_network =  Mock( side_effect=TypeError('ERR') )
        self.assertRaises(TypeError,
                         self.manager._post_live_migration,
                         self.instance1,
                         'host1')

    def test13(self):
        """13: db.network_update raises Unknown exception. """
        db.network_update =  Mock( side_effect=TypeError('ERR') )
        self.assertRaises(TypeError,
                         self.manager._post_live_migration,
                         self.instance1,
                         'host1')

    def test14(self):
        """14: db.instance_get_floating_address raises NotFound. """
        db.instance_get_floating_address = Mock(side_effect=exception.NotFound("ERR"))
        ret = self.manager._post_live_migration(self.instance1, 'host1')
        c1 = (ret == None)
        c2 = (0 <= sys.stderr.buffer.find('doesnt have floating_ip'))
        self.assertEqual(c1 and c2, True)


    def test15(self):
        """15: db.instance_get_floating_address returns None. """

        db.instance_get_floating_address = Mock( return_value=None )
        ret = self.manager._post_live_migration(self.instance1, 'host1')
        c1 = (ret == None)
        c2 = (0 <= sys.stderr.buffer.find('floating_ip is not found'))
        self.assertEqual(c1 and c2, True)

    def test16(self):
        """16:  db.instance_get_floating_address raises NotFound. """

        db.instance_get_floating_address = Mock(side_effect=exception.NotFound("ERR"))
        ret = self.manager._post_live_migration(self.instance1, 'host1')
        c1 = (ret == None)
        c2 = (0 <= sys.stderr.buffer.find('doesnt have floating_ip'))
        self.assertEqual(c1 and c2, True)

    def test17(self):
        """17:  db.instance_get_floating_address raises Unknown exception. """
        db.instance_get_floating_address = Mock(side_effect=TypeError("ERR"))
        ret = self.manager._post_live_migration(self.instance1, 'host1')
        c1 = (ret == None)
        c2 = (0 <= sys.stderr.buffer.find('Live migration: Unexpected error'))
        self.assertEqual(c1 and c2, True)


    def test18(self):
        """18: db.floating_ip_get_by_address raises NotFound """

        db.floating_ip_get_by_address = Mock(side_effect=exception.NotFound("ERR"))
        ret = self.manager._post_live_migration(self.instance1, 'host1')
        c1 = (ret == None)
        c2 = (0 <= sys.stderr.buffer.find('doesnt have floating_ip'))
        self.assertEqual(c1 and c2, True)

    def test19(self):
        """19:  db.floating_ip_get_by_address raises Unknown exception. """
        db.floating_ip_get_by_address = Mock(side_effect=TypeError("ERR"))
        ret = self.manager._post_live_migration(self.instance1, 'host1')
        c1 = (ret == None)
        c2 = (0 <= sys.stderr.buffer.find('Live migration: Unexpected error'))
        self.assertEqual(c1 and c2, True)


    def test20(self):
        """20: db.floating_ip_update raises Unknown exception. 
        """
        db.floating_ip_update = Mock(side_effect=TypeError("ERR"))
        ret = self.manager._post_live_migration(self.instance1, 'host1')
        c1 = (ret == None)
        c2 = (0 <= sys.stderr.buffer.find('Live migration: Unexpected error'))
        self.assertEqual(c1 and c2, True)

    def test21(self):
        """21: db.instance_update raises unknown  exception. """

        db.instance_update = Mock(side_effect=TypeError("ERR"))
        self.assertRaises(TypeError,
                         self.manager._post_live_migration,
                         self.instance1,
                         'host1')

    def tearDown(self):
        """common terminating method. """
        self.stderr.realFlush()
        sys.stderr = self.stderrBak
        #sys.stdout = self.stdoutBak

if __name__ == '__main__':
    logging.getLogger().setLevel(logging.DEBUG)
    #unittest.main()

    suite = unittest.TestLoader().loadTestsFromTestCase(LibvirtConnectionTestFunctions)
    unittest.TextTestRunner(verbosity=2).run(suite)

    #suite = unittest.TestSuite()
    #suite.addTest(LibvirtConnectionTestFunctions("test14"))
    #suite.addTest(LibvirtConnectionTestFunctions("test16"))
    #unittest.TextTestRunner(verbosity=2).run(suite)

    
=======
#!/usr/bin/python
# -*- coding: UTF-8 -*-


import sys
import os
import unittest
import commands
import re
import logging
import libvirt

from mock import Mock
import twisted

# getting /nova-inst-dir
NOVA_DIR = os.path.abspath(sys.argv[0])
for i in range(4):
    NOVA_DIR = os.path.dirname(NOVA_DIR)


try : 
    print
    print 'checking %s/bin/nova-manage exists, set the NOVA_DIR properly..' % NOVA_DIR
    print

    sys.path.append(NOVA_DIR)

    from nova.compute.manager import ComputeManager
    from nova.virt import libvirt_conn

    from nova import context
    from nova import db
    from nova import exception
    from nova import flags
    from nova import quota
    from nova import utils
    from nova import process
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
    def write(self,arg):
        self.buffer += arg
    def writelines(self, arg): 
        self.buffer += arg
    def flush(self):
        print 'flush'
        self.buffer = ''

class tmpStderr(tmpStdout):
    def write(self,arg):
        self.buffer += arg
    def flush(self):
        pass
    def realFlush(self):
        self.buffer = ''

class DummyLibvirtConn(object):
    nwfilterLookupByName = None
    def __init__(self): 
        pass


class LibvirtConnectionTestFunctions(unittest.TestCase):

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
            self.__class__.manager = libvirt_conn.get_connection(False)

        self.setTestData()
        self.setMocks()

    def setTestData(self):  

        self.host1 = Host()
        for key, val in [ ('name', 'host1'), ('cpu', 5), ('memory_mb', 20480), ('hdd_gb', 876) ]:
            self.host1.__setitem__(key, val)

        self.instance1 = Instance()
        for key, val in [ ('id', 1), ('host', 'host1'),   ('hostname', 'i-12345'), 
                          ('state', power_state.RUNNING), ('project_id', 'testPJ'),
                          ('vcpus', 3), ('memory_mb', 1024), ('hdd_gb', 5), ('internal_id',12345) ]:
            self.instance1.__setitem__(key, val)


        self.instance2 = Instance()
        for key, val in [ ('id', 2), ('host', 'host1'),   ('hostname', 'i-12345'), 
                          ('state', power_state.RUNNING), ('project_id', 'testPJ'),
                          ('vcpus', 3), ('memory_mb', 1024), ('hdd_gb', 5) ]:
            self.instance2.__setitem__(key, val)


        self.fixed_ip1 = FixedIp()
        for key, val in [ ('id', 1), ('address', '1.1.1.1'),   ('network_id', '1'), 
                          ('instance_id', 1)]:
            self.fixed_ip1.__setitem__(key, val)

        self.floating_ip1 = FloatingIp()
        for key, val in [ ('id', 1), ('address', '1.1.1.200') ]:
            self.floating_ip1.__setitem__(key, val)

        self.netref1 = Network()
        for key, val in [ ('id', 1) ]:
            self.netref1.__setitem__(key, val)


    def setMocks(self):  

        self.ctxt = context.get_admin_context()
        db.instance_get_fixed_address = Mock(return_value = '1.1.1.1')
        db.fixed_ip_update =  Mock(return_value = None)
        db.fixed_ip_get_network = Mock(return_value = self.netref1)
        db.network_update = Mock(return_value = None)
        db.instance_get_floating_address = Mock(return_value = '1.1.1.200')
        db.floating_ip_get_by_address = Mock(return_value = self.floating_ip1)
        db.floating_ip_update = Mock(return_value = None)
        db.instance_update = Mock(return_value = None)


    # ---> test for nova.virt.libvirt_conn.nwfilter_for_instance_exists()

    def test01(self):
        """01: libvirt.libvirtError occurs.  """

        self.manager._wrapped_conn = DummyLibvirtConn()
        self.manager._test_connection = Mock(return_value=True)
        self.manager._conn.nwfilterLookupByName = \
            Mock(side_effect=libvirt.libvirtError("ERR")) 
        ret = self.manager.nwfilter_for_instance_exists(self.instance1)
        self.assertEqual(ret, False)

    def test02(self):
        """02: libvirt.libvirtError not occurs.  """

        self.manager._wrapped_conn = DummyLibvirtConn()
        self.manager._test_connection = Mock(return_value=True)
        self.manager._conn.nwfilterLookupByName = \
            Mock(return_value=True) 
        ret = self.manager.nwfilter_for_instance_exists(self.instance1)
        self.assertEqual(ret, True)

    # ---> test for nova.virt.libvirt_conn.live_migraiton()

    def test03(self):
        """03: Unexpected exception occurs on finding volume on DB. """

        utils.execute = Mock( side_effect=process.ProcessExecutionError('ERR') )

        self.assertRaises(process.ProcessExecutionError,
                         self.manager.live_migration,
                         self.instance1,
                         'host2')

    # ---> other case cannot be tested because live_migraiton
    #      is synchronized/asynchronized method are mixed together


    # ---> test for nova.virt.libvirt_conn._post_live_migraiton

    def test04(self):
        """04: instance_ref is not nova.db.sqlalchemy.models.Instances"""

        self.assertRaises(TypeError,
                         self.manager._post_live_migration,
                         "dummy string",
                         'host2')

    def test05(self): 
        """05: db.instance_get_fixed_address return None"""

        db.instance_get_fixed_address  = Mock( return_value=None )
        ret = self.manager._post_live_migration(self.instance1, 'host1')
        c1 = (ret == None)
        c2 = (0 <= sys.stderr.buffer.find('fixed_ip is not found'))
        self.assertEqual(c1 and c2, True)

    def test06(self):
        """06: db.instance_get_fixed_address raises NotFound"""

        db.instance_get_fixed_address  = Mock( side_effect=exception.NotFound('ERR') )
        self.assertRaises(exception.NotFound,
                         self.manager._post_live_migration,
                         self.instance1,
                         'host2')

    def test07(self):
        """07: db.instance_get_fixed_address raises Unknown exception"""

        db.instance_get_fixed_address  = Mock( side_effect=TypeError('ERR') )
        self.assertRaises(TypeError,
                         self.manager._post_live_migration,
                         self.instance1,
                         'host1')

    def test08(self):
        """08: db.fixed_ip_update return NotFound. """

        db.fixed_ip_update =  Mock( side_effect=exception.NotFound('ERR') )
        self.assertRaises(exception.NotFound,
                         self.manager._post_live_migration,
                         self.instance1,
                         'host1')
        
    def test09(self):
        """09: db.fixed_ip_update return NotAuthorized. """
        db.fixed_ip_update =  Mock( side_effect=exception.NotAuthorized('ERR') )
        self.assertRaises(exception.NotAuthorized,
                         self.manager._post_live_migration,
                         self.instance1,
                         'host1')

    def test10(self):
        """10: db.fixed_ip_update return Unknown exception. """
        db.fixed_ip_update =  Mock( side_effect=TypeError('ERR') )
        self.assertRaises(TypeError,
                         self.manager._post_live_migration,
                         self.instance1,
                         'host1')
    
    def test11(self):
        """11: db.fixed_ip_get_network causes NotFound. """

        db.fixed_ip_get_network =  Mock( side_effect=exception.NotFound('ERR') )
        self.assertRaises(exception.NotFound,
                         self.manager._post_live_migration,
                         self.instance1,
                         'host1')
        
    # not tested db.fixed_ip_get_network raises NotAuthorized
    # because same test has been done at previous test.

    def test12(self):
        """12: db.fixed_ip_get_network causes Unknown exception. """

        db.fixed_ip_get_network =  Mock( side_effect=TypeError('ERR') )
        self.assertRaises(TypeError,
                         self.manager._post_live_migration,
                         self.instance1,
                         'host1')

    def test13(self):
        """13: db.network_update raises Unknown exception. """
        db.network_update =  Mock( side_effect=TypeError('ERR') )
        self.assertRaises(TypeError,
                         self.manager._post_live_migration,
                         self.instance1,
                         'host1')

    def test14(self):
        """14: db.instance_get_floating_address raises NotFound. """
        db.instance_get_floating_address = Mock(side_effect=exception.NotFound("ERR"))
        ret = self.manager._post_live_migration(self.instance1, 'host1')
        c1 = (ret == None)
        c2 = (0 <= sys.stderr.buffer.find('doesnt have floating_ip'))
        self.assertEqual(c1 and c2, True)


    def test15(self):
        """15: db.instance_get_floating_address returns None. """

        db.instance_get_floating_address = Mock( return_value=None )
        ret = self.manager._post_live_migration(self.instance1, 'host1')
        c1 = (ret == None)
        c2 = (0 <= sys.stderr.buffer.find('floating_ip is not found'))
        self.assertEqual(c1 and c2, True)

    def test16(self):
        """16:  db.instance_get_floating_address raises NotFound. """

        db.instance_get_floating_address = Mock(side_effect=exception.NotFound("ERR"))
        ret = self.manager._post_live_migration(self.instance1, 'host1')
        c1 = (ret == None)
        c2 = (0 <= sys.stderr.buffer.find('doesnt have floating_ip'))
        self.assertEqual(c1 and c2, True)

    def test17(self):
        """17:  db.instance_get_floating_address raises Unknown exception. """
        db.instance_get_floating_address = Mock(side_effect=TypeError("ERR"))
        ret = self.manager._post_live_migration(self.instance1, 'host1')
        c1 = (ret == None)
        c2 = (0 <= sys.stderr.buffer.find('Live migration: Unexpected error'))
        self.assertEqual(c1 and c2, True)


    def test18(self):
        """18: db.floating_ip_get_by_address raises NotFound """

        db.floating_ip_get_by_address = Mock(side_effect=exception.NotFound("ERR"))
        ret = self.manager._post_live_migration(self.instance1, 'host1')
        c1 = (ret == None)
        c2 = (0 <= sys.stderr.buffer.find('doesnt have floating_ip'))
        self.assertEqual(c1 and c2, True)

    def test19(self):
        """19:  db.floating_ip_get_by_address raises Unknown exception. """
        db.floating_ip_get_by_address = Mock(side_effect=TypeError("ERR"))
        ret = self.manager._post_live_migration(self.instance1, 'host1')
        c1 = (ret == None)
        c2 = (0 <= sys.stderr.buffer.find('Live migration: Unexpected error'))
        self.assertEqual(c1 and c2, True)


    def test20(self):
        """20: db.floating_ip_update raises Unknown exception. 
        """
        db.floating_ip_update = Mock(side_effect=TypeError("ERR"))
        ret = self.manager._post_live_migration(self.instance1, 'host1')
        c1 = (ret == None)
        c2 = (0 <= sys.stderr.buffer.find('Live migration: Unexpected error'))
        self.assertEqual(c1 and c2, True)

    def test21(self):
        """21: db.instance_update raises unknown  exception. """

        db.instance_update = Mock(side_effect=TypeError("ERR"))
        self.assertRaises(TypeError,
                         self.manager._post_live_migration,
                         self.instance1,
                         'host1')

    def tearDown(self):
        """common terminating method. """
        self.stderr.realFlush()
        sys.stderr = self.stderrBak
        #sys.stdout = self.stdoutBak

if __name__ == '__main__':
    logging.getLogger().setLevel(logging.DEBUG)
    #unittest.main()

    suite = unittest.TestLoader().loadTestsFromTestCase(LibvirtConnectionTestFunctions)
    unittest.TextTestRunner(verbosity=2).run(suite)

    #suite = unittest.TestSuite()
    #suite.addTest(LibvirtConnectionTestFunctions("test14"))
    #suite.addTest(LibvirtConnectionTestFunctions("test16"))
    #unittest.TextTestRunner(verbosity=2).run(suite)

    
>>>>>>> MERGE-SOURCE
