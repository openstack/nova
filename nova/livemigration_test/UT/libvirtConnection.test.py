#!/usr/bin/python
# -*- coding: UTF-8 -*-


import sys
import os
import unittest
import commands
import re
import logging
import libvirt
import libxml2

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

class testDomain(object): 
    def __init__(self): 
        pass
    def migrateToURI(self, a, b, c, d): 
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

        self.xml="<cpu><arch>x86_64</arch><model>Nehalem</model><vendor>Intel</vendor><topology sockets='2' cores='4' threads='2'/><feature name='rdtscp'/><feature name='dca'/><feature name='xtpr'/><feature name='tm2'/><feature name='est'/><feature name='vmx'/><feature name='ds_cpl'/><feature name='monitor'/><feature name='pbe'/><feature name='tm'/><feature name='ht'/><feature name='ss'/><feature name='acpi'/><feature name='ds'/><feature name='vme'/></cpu>"

        self.xml2="<cccccpu><arch>x86_64</arch><model>Nehalem</model><vendor>Intel</vendor><topology sockets='2' cores='4' threads='2'/><feature name='rdtscp'/><feature name='dca'/><feature name='xtpr'/><feature name='tm2'/><feature name='est'/><feature name='vmx'/><feature name='ds_cpl'/><feature name='monitor'/><feature name='pbe'/><feature name='tm'/><feature name='ht'/><feature name='ss'/><feature name='acpi'/><feature name='ds'/><feature name='vme'/></cccccpu>"

        self.conn = libvirt.virConnect()
        self.tmpDomain = testDomain()

    def setMocks(self):  

        self.ctxt = context.get_admin_context()
        # mocks for get_cpu_xml
        self.manager._wrapped_conn = self.conn
        self.manager._test_connection = Mock(return_value=True)
        self.manager._conn.getCapabilities = Mock(return_value=self.xml) 
        # mocks for ensure_filtering_rules_for_instance 
        self.manager.nwfilter.setup_basic_filtering = Mock(return_value=None)
        self.manager.firewall_driver.prepare_instance_filter = \
            Mock(return_value=None)
        #self.manager._conn.nwfilterLookupByName = Mock(return_value=None)
        self.conn.nwfilterLookupByName = Mock(return_value=None)
        # mocks for _live_migration
        self.manager.read_only=True
        self.manager._connect = Mock(return_value=self.conn)
        self.conn.lookupByName = Mock(return_value=self.tmpDomain)
        db.instance_set_state =  Mock(return_value=True)
        db.volume_get_all_by_instance =  Mock(return_value=[])
        #self.manager._conn = Mock(return_value=self.tmpDomain)

        db.instance_get_fixed_address = Mock(return_value = '1.1.1.1')
        db.fixed_ip_update =  Mock(return_value = None)
        db.fixed_ip_get_network = Mock(return_value = self.netref1)
        db.network_update = Mock(return_value = None)
        db.instance_get_floating_address = Mock(return_value = '1.1.1.200')
        db.floating_ip_get_by_address = Mock(return_value = self.floating_ip1)
        db.floating_ip_update = Mock(return_value = None)
        db.instance_update = Mock(return_value = None)


    # ---> test for nova.virt.get_cpu_xml()
    def test01(self):
        """01: getCapabilities raises libvirt.libvirtError.  """

        self.manager._conn.getCapabilities = \
            Mock(side_effect=libvirt.libvirtError("ERR")) 
        
        self.assertRaises(libvirt.libvirtError, self.manager.get_cpu_xml)
        return False

    def test02(self):
        """02: libxml2.parseDoc raises libxml2.parserError.  """

        tmp = libxml2.parseDoc
        libxml2.parseDoc =  Mock(side_effect=libxml2.parserError("ERR"))
        try : 
            self.manager.get_cpu_xml()
        except libxml2.parserError, e:
            libxml2.parseDoc = tmp
            return True
        libxml2.parseDoc = tmp
        return False

    # no exception case assumed for xml.xpathEval, so no test case.
    def test03(self):
        """03: xml format is invalid no 2 cpu tag exists).  """

        self.manager._conn.getCapabilities = Mock(return_value=self.xml2) 
        try : 
            self.manager.get_cpu_xml()
        except exception.Invalid, e: 
            c1 = ( 0 <= e.message.find('Unexpected xml format'))
            self.assertTrue(c1, True)
        return False

    def test04(self):
        """04: re.sub raises unexpected exceptioin.  """

        tmp = re.sub
        re.sub =  Mock(side_effect=TypeError("ERR"))
        try : 
            self.manager.get_cpu_xml()
        except TypeError, e:
            re.sub = tmp
            return True
        re.sub = tmp
        return False

    def test05(self):
        """05: everything goes well.  """

        ret = self.manager.get_cpu_xml()
        self.assertTrue(type(ret), str)
        return False

    # ---> test for nova.virt.libvirt_conn.compare_cpu()

    def test06(self):
        """06: compareCPU raises libvirt.libvirtError.  """

        self.manager._conn.compareCPU = \
            Mock(side_effect=libvirt.libvirtError("ERR")) 
        
        self.assertRaises(libvirt.libvirtError, self.manager.compare_cpu, '')
        return False

    def test07(self):
        """07: compareCPU returns 0  """

        self.manager._conn.compareCPU = Mock(return_value=0) 
        try : 
            self.manager.compare_cpu('')
        except exception.Invalid, e:
            c1 = ( 0 <= e.message.find('CPU does not have compativility'))
            self.assertTrue(c1, True)
        return False
            
    def test08(self):
        """08: compare_cpu finished successfully.  """

        self.conn.compareCPU = Mock(return_value=1)
        ret = self.manager.compare_cpu('')
        return ret == None

    # ---> test for nova.virt.libvirt_conn.ensure_filtering_for_instance()
    
    def test09(self):
        """09: setup_basic_filtering raises unexpected exception.  """

        self.manager.nwfilter.setup_basic_filtering = \
            Mock(side_effect=libvirt.libvirtError('ERR'))
        self.assertRaises(libvirt.libvirtError, 
                          self.manager.ensure_filtering_rules_for_instance, 
                          self.instance1)
        return False
      
    def test10(self):
        """10: prepare_instance_filter raises unexpected exception.  """

        self.manager.firewall_driver.prepare_instance_filter = \
            Mock(side_effect=libvirt.libvirtError('ERR'))

        self.assertRaises(libvirt.libvirtError, 
                          self.manager.ensure_filtering_rules_for_instance, 
                          self.instance1)
        return False
      
    def test11(self):
        """11: nwfilterLookupByName raises libvirt.libvirtError.  """

        self.conn.nwfilterLookupByName = \
            Mock(side_effect=libvirt.libvirtError('ERR'))

        try :
            self.manager.ensure_filtering_rules_for_instance(self.instance1)
        except exception.Error, e: 
            c1 = ( 0 <= e.message.find('Timeout migrating for'))
            self.assertTrue(c1, True)
        return False

    def test12(self):
        """12: everything goes well.  """

        ret = self.manager.ensure_filtering_rules_for_instance(self.instance1)
        return ret ==  None


    # ---> test for nova.virt.libvirt_conn.live_migraiton()

    def test13(self):
        """13: self._connect raises libvirt.libvirtError. """

        self.manager._connect = Mock(side_effect=libvirt.libvirtError('ERR'))
        self.assertRaises(libvirt.libvirtError,
                         self.manager._live_migration,
                         self.ctxt,
                         self.instance1,
                         'host2')

    def test14(self):
        """14: lookupByName raises libvirt.libvirtError. """

        self.conn.lookupByName = Mock(side_effect=libvirt.libvirtError('ERR'))
        self.assertRaises(libvirt.libvirtError,
                         self.manager._live_migration,
                         self.ctxt,
                         self.instance1,
                         'host2')

    def test15(self):
        """15: migrateToURI raises libvirt.libvirtError. """

        self.tmpDomain.migrateToURI = Mock(side_effect=libvirt.libvirtError('ERR'))
        self.assertRaises(libvirt.libvirtError,
                         self.manager._live_migration,
                         self.ctxt,
                         self.instance1,
                         'host2')

    def test16(self):
        """16: close raises libvirt.libvirtError. """

        self.conn.close = Mock(side_effect=libvirt.libvirtError('ERR'))
        self.assertRaises(libvirt.libvirtError,
                         self.manager._live_migration,
                         self.ctxt,
                         self.instance1,
                         'host2')

    def test17(self):
        """17: lookupByName raises libvirt.libvirtError(using existing connectioin). """

        self.manager.read_only = False
        self.conn.lookupByName = Mock(side_effect=libvirt.libvirtError('ERR'))
        self.assertRaises(libvirt.libvirtError,
                         self.manager._live_migration,
                         self.ctxt,
                         self.instance1,
                         'host2')

    def test18(self):
        """18: migrateToURI raises libvirt.libvirtError(using existing connectioin). """

        self.manager.read_only = False
        self.tmpDomain.migrateToURI = Mock(side_effect=libvirt.libvirtError('ERR'))
        self.assertRaises(libvirt.libvirtError,
                         self.manager._live_migration,
                         self.ctxt,
                         self.instance1,
                         'host2')

    def test19(self):
        """19: migrateToURI raises libvirt.libvirtError(using existing connectioin), and instance_set_state raises unexpected exception(TypeError here)"""

        self.manager.read_only = False
        self.tmpDomain.migrateToURI = Mock(side_effect=libvirt.libvirtError('ERR'))
        db.instance_set_state = Mock(side_effect=TypeError('ERR'))
        self.assertRaises(TypeError,
                         self.manager._live_migration,
                         self.ctxt,
                         self.instance1,
                         'host2')

    def test20(self):
        """20: migrateToURI raises libvirt.libvirtError(using existing connectioin), and volume_get_all_by_instance raises unexpected exception(TypeError here)"""

        self.manager.read_only = False
        self.tmpDomain.migrateToURI = Mock(side_effect=libvirt.libvirtError('ERR'))
        db.volume_get_all_by_instance = Mock(side_effect=TypeError('ERR'))
        self.assertRaises(TypeError,
                         self.manager._live_migration,
                         self.ctxt,
                         self.instance1,
                         'host2')

    def test21(self):
        """21: migrateToURI raises libvirt.libvirtError(using existing connectioin), and volume_get_all_by_instance raises exception.NotFound"""

        self.manager.read_only = False
        self.tmpDomain.migrateToURI = Mock(side_effect=libvirt.libvirtError('ERR'))
        db.volume_get_all_by_instance = Mock(side_effect=exception.NotFound('ERR'))
        self.assertRaises(libvirt.libvirtError,
                         self.manager._live_migration,
                         self.ctxt,
                         self.instance1,
                         'host2')

    def test22(self):
        """22: everything goes well"""

        self.manager.read_only = False
        ret = self.manager._live_migration(self.ctxt, self.instance1, 'host2')
        return ret == None


    # ---> test for nova.virt.libvirt_conn._post_live_migraiton

    def test23(self):
        """23: instance_ref is not nova.db.sqlalchemy.models.Instances"""

        self.assertRaises(TypeError,
                         self.manager._post_live_migration,
                         self.ctxt,
                         "dummy string",
                         'host2')

    def test24(self): 
        """24: db.instance_get_fixed_address return None"""

        db.instance_get_fixed_address  = Mock( return_value=None )
        ret = self.manager._post_live_migration(self.ctxt, self.instance1, 'host1')
        c1 = (ret == None)
        c2 = (0 <= sys.stderr.buffer.find('fixed_ip is not found'))
        self.assertEqual(c1 and c2, True)

    def test25(self):
        """25: db.instance_get_fixed_address raises NotFound"""

        db.instance_get_fixed_address  = Mock( side_effect=exception.NotFound('ERR') )
        self.assertRaises(exception.NotFound,
                         self.manager._post_live_migration,
                         self.ctxt,
                         self.instance1,
                         'host2')

    def test26(self):
        """26: db.instance_get_fixed_address raises Unknown exception"""

        db.instance_get_fixed_address  = Mock( side_effect=TypeError('ERR') )
        self.assertRaises(TypeError,
                         self.manager._post_live_migration,
                         self.ctxt,
                         self.instance1,
                         'host1')

    def test27(self):
        """27: db.fixed_ip_update return NotFound. """

        db.fixed_ip_update =  Mock( side_effect=exception.NotFound('ERR') )
        self.assertRaises(exception.NotFound,
                         self.manager._post_live_migration,
                         self.ctxt,
                         self.instance1,
                         'host1')
        
    def test28(self):
        """28: db.fixed_ip_update return NotAuthorized. """
        db.fixed_ip_update =  Mock( side_effect=exception.NotAuthorized('ERR') )
        self.assertRaises(exception.NotAuthorized,
                         self.manager._post_live_migration,
                         self.ctxt,
                         self.instance1,
                         'host1')

    def test29(self):
        """10: db.fixed_ip_update return Unknown exception. """
        db.fixed_ip_update =  Mock( side_effect=TypeError('ERR') )
        self.assertRaises(TypeError,
                         self.manager._post_live_migration,
                         self.ctxt,
                         self.instance1,
                         'host1')
    
    def test29(self):
        """11: db.fixed_ip_get_network causes NotFound. """

        db.fixed_ip_get_network =  Mock( side_effect=exception.NotFound('ERR') )
        self.assertRaises(exception.NotFound,
                         self.manager._post_live_migration,
                         self.ctxt,
                         self.instance1,
                         'host1')
        
    # not tested db.fixed_ip_get_network raises NotAuthorized
    # because same test has been done at previous test.

    def test30(self):
        """30: db.fixed_ip_get_network causes Unknown exception. """

        db.fixed_ip_get_network =  Mock( side_effect=TypeError('ERR') )
        self.assertRaises(TypeError,
                         self.manager._post_live_migration,
                         self.ctxt,
                         self.instance1,
                         'host1')

    def test31(self):
        """13: db.network_update raises Unknown exception. """
        db.network_update =  Mock( side_effect=TypeError('ERR') )
        self.assertRaises(TypeError,
                         self.manager._post_live_migration,
                         self.ctxt,
                         self.instance1,
                         'host1')

    def test31(self):
        """14: db.instance_get_floating_address raises NotFound. """
        db.instance_get_floating_address = Mock(side_effect=exception.NotFound("ERR"))
        ret = self.manager._post_live_migration(self.ctxt, self.instance1, 'host1')
        c1 = (ret == None)
        c2 = (0 <= sys.stderr.buffer.find('doesnt have floating_ip'))
        self.assertEqual(c1 and c2, True)


    def test32(self):
        """32: db.instance_get_floating_address returns None. """

        db.instance_get_floating_address = Mock( return_value=None )
        ret = self.manager._post_live_migration(self.ctxt, self.instance1, 'host1')
        c1 = (ret == None)
        c2 = (0 <= sys.stderr.buffer.find('floating_ip is not found'))
        self.assertEqual(c1 and c2, True)

    def test33(self):
        """33:  db.instance_get_floating_address raises NotFound. """

        db.instance_get_floating_address = Mock(side_effect=exception.NotFound("ERR"))
        ret = self.manager._post_live_migration(self.ctxt, self.instance1, 'host1')
        c1 = (ret == None)
        c2 = (0 <= sys.stderr.buffer.find('doesnt have floating_ip'))
        self.assertEqual(c1 and c2, True)

    def test34(self):
        """34:  db.instance_get_floating_address raises Unknown exception. """
        db.instance_get_floating_address = Mock(side_effect=TypeError("ERR"))
        ret = self.manager._post_live_migration(self.ctxt, self.instance1, 'host1')
        c1 = (ret == None)
        c2 = (0 <= sys.stderr.buffer.find('Live migration: Unexpected error'))
        self.assertEqual(c1 and c2, True)


    def test35(self):
        """35: db.floating_ip_get_by_address raises NotFound """

        db.floating_ip_get_by_address = Mock(side_effect=exception.NotFound("ERR"))
        ret = self.manager._post_live_migration(self.ctxt, self.instance1, 'host1')
        c1 = (ret == None)
        c2 = (0 <= sys.stderr.buffer.find('doesnt have floating_ip'))
        self.assertEqual(c1 and c2, True)

    def test36(self):
        """36:  db.floating_ip_get_by_address raises Unknown exception. """
        db.floating_ip_get_by_address = Mock(side_effect=TypeError("ERR"))
        ret = self.manager._post_live_migration(self.ctxt, self.instance1, 'host1')
        c1 = (ret == None)
        c2 = (0 <= sys.stderr.buffer.find('Live migration: Unexpected error'))
        self.assertEqual(c1 and c2, True)


    def test37(self):
        """37: db.floating_ip_update raises Unknown exception. 
        """
        db.floating_ip_update = Mock(side_effect=TypeError("ERR"))
        ret = self.manager._post_live_migration(self.ctxt, self.instance1, 'host1')
        c1 = (ret == None)
        c2 = (0 <= sys.stderr.buffer.find('Live migration: Unexpected error'))
        self.assertEqual(c1 and c2, True)

    def test38(self):
        """38: db.instance_update raises unknown  exception. """

        db.instance_update = Mock(side_effect=TypeError("ERR"))
        self.assertRaises(TypeError,
                         self.manager._post_live_migration,
                         self.ctxt,
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

    
