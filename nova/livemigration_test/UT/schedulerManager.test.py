#!/usr/bin/python
# -*- coding: UTF-8 -*-


import sys
import os
import unittest
import commands
import re
import libvirt

from mock import Mock

# getting /nova-inst-dir
NOVA_DIR = os.path.abspath(sys.argv[0])
for i in range(4): 
    NOVA_DIR = os.path.dirname(NOVA_DIR)

try : 
    print
    print 'Checking %s/bin/nova-manage exists, set the NOVA_DIR properly..' % NOVA_DIR
    print

    sys.path.append(NOVA_DIR)

    from nova.scheduler.manager import SchedulerManager

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
    def flush(self):
        self.buffer = ''


class SchedulerTestFunctions(unittest.TestCase):

    manager = None

    # 共通の初期化処理
    def setUp(self):
        """common init method. """

        self.host = 'openstack2-api'
        if self.manager is None: 
            self.manager = SchedulerManager(host=self.host)

        self.setTestData()
        self.setMocks()

    def setTestData(self):  

        self.host1 = Host()
        self.host1.__setitem__('name',    'host1')
        self.host1.__setitem__('vcpus', 5)
        self.host1.__setitem__('memory_mb', 20480)
        self.host1.__setitem__('local_gb', 876)
        self.host1.__setitem__('cpu_info', 1)

        self.host2 = Host()
        self.host2.__setitem__('name', 'host2')
        self.host2.__setitem__('vcpus', 5)
        self.host2.__setitem__('memory_mb', 20480)
        self.host2.__setitem__('local_gb', 876)
        self.host2.__setitem__('hypervisor_type', 'QEMU')
        self.host2.__setitem__('hypervisor_version', 12003)
        xml="<cpu><arch>x86_64</arch><model>Nehalem</model><vendor>Intel</vendor><topology sockets='2' cores='4' threads='2'/><feature name='rdtscp'/><feature name='dca'/><feature name='xtpr'/><feature name='tm2'/><feature name='est'/><feature name='vmx'/><feature name='ds_cpl'/><feature name='monitor'/><feature name='pbe'/><feature name='tm'/><feature name='ht'/><feature name='ss'/><feature name='acpi'/><feature name='ds'/><feature name='vme'/></cpu>"
        self.host2.__setitem__('cpu_info', xml)

        self.instance1 = Instance()
        for key, val in [ ('id', 1), ('host', 'host1'),   ('hostname', 'i-12345'), 
                          ('state', power_state.RUNNING), ('project_id', 'testPJ'),
                          ('vcpus', 3), ('memory_mb', 1024), ('local_gb', 5) ]:
            self.instance1.__setitem__(key, val)


        self.instance2 = Instance()
        for key, val in [ ('id', 2), ('host', 'host1'),   ('hostname', 'i-12345'), 
                          ('state', power_state.RUNNING), ('project_id', 'testPJ'),
                          ('vcpus', 3), ('memory_mb', 1024), ('local_gb', 5) ]:
            self.instance2.__setitem__(key, val)


        self.instance3 = Instance()
        for key, val in [ ('id', 3), ('host', 'host1'),   ('hostname', 'i-12345'), 
                          ('state', power_state.RUNNING), ('project_id', 'testPJ2'),
                          ('vcpus', 1), ('memory_mb', 1024), ('local_gb', 5),
                          ('internal_id', 123456), ('state', 1), 
                          ('state_description', 'running') ]:
            self.instance3.__setitem__(key, val)

        self.instance4 = Instance()
        for key, val in [ ('id', 4), ('host', 'host2'),   ('hostname', 'i-12345'), 
                          ('state', power_state.RUNNING), ('project_id', 'testPJ2'),
                          ('vcpus', 1), ('memory_mb', 1024), ('local_gb', 5),
                          ('internal_id', 123456), ('state', 0),
                          ('state_description', 'running') ]:
            self.instance4.__setitem__(key, val)

        self.instance5 = Instance()
        for key, val in [ ('id', 5), ('host', 'host2'),   ('hostname', 'i-12345'), 
                          ('state', power_state.RUNNING), ('project_id', 'testPJ2'),
                          ('vcpus', 1), ('memory_mb', 1024), ('local_gb', 5),
                          ('internal_id', 123456), ('state', 1),
                          ('state_description', 'migrating') ]:
            self.instance5.__setitem__(key, val)

        self.instance6 = Instance()
        for key, val in [ ('id', 6), ('host', 'host2'),   ('hostname', 'i-12345'), 
                          ('state', power_state.RUNNING), ('project_id', 'testPJ2'),
                          ('vcpus', 3), ('memory_mb', 1024), ('local_gb', 5) ]:
            self.instance6.__setitem__(key, val)

        self.instance7 = Instance()
        for key, val in [ ('id', 7), ('host', 'host1'),   ('hostname', 'i-12345'), 
                          ('state', power_state.RUNNING), ('project_id', 'testPJ2'),
                          ('vcpus', 1), ('memory_mb', 18432), ('local_gb', 5) ]:
            self.instance7.__setitem__(key, val)

        self.instance8 = Instance()
        for key, val in [ ('id', 8), ('host', 'host1'),   ('hostname', 'i-12345'), 
                          ('state', power_state.RUNNING), 
                          ('state_description', 'running'),('project_id', 'testPJ2'),
                          ('vcpus', 1), ('memory_mb', 1024), ('local_gb', 866) ]:
            self.instance8.__setitem__(key, val)

        self.service1 = Service()
        for key, val in [ ('id', 1), ('host', 'host1'),  ('binary', 'nova-compute'), 
                          ('topic', 'compute')]:
            self.service1.__setitem__(key, val)

        self.service2 = Service()
        for key, val in [ ('id', 2), ('host', 'host2'),  ('binary', 'nova-compute'), 
                          ('topic', 'compute')]:
            self.service1.__setitem__(key, val)

    def setMocks(self): 
        self.ctxt = context.get_admin_context()
        # Mocks for has_enough_resource()
        db.instance_get = Mock(return_value = self.instance3)
        db.host_get_by_name = Mock(return_value = self.host2)
        db.instance_get_all_by_host = Mock(return_value = [self.instance4, self.instance5] )

        # Mocks for live_migration
        db.service_get_all_by_topic = Mock(return_value = [self.service1] )
        self.manager.service_ip_up = Mock(return_value = True)
        rpc.call = Mock(return_value=1)
        db.instance_set_state = Mock(return_value = True)
        self.manager.driver.service_is_up = Mock(return_value = True)

    def check_format(self, val): 
        """check result format of show_host_resource """

        if dict != type(val) : 
            sys.stderr.write('return value is not dict')
            return False 

        if not val.has_key('ret'): 
            sys.stderr.write('invalid format(missing "ret"). ')
            return False 

        if not val['ret'] : 
            if not val.has_key('msg') :
                sys.stderr.write( 'invalid format(missing "msg").' )
                return False 
            
        else : 
            if  not val.has_key('phy_resource') : 
                sys.stderr.write('invalid format(missing "phy_resource"). ')
                return False 

            if not val.has_key('usage'):
                sys.stderr.write('invalid format(missing "usage"). ')
                return False 
        
            if not self._check_format(val['phy_resource']):
                return False

            for key, dic in val['usage'].items() : 
                if not self._check_format(dic):
                    return False
            return True
 
    def _check_format(self, val): 
        if dict != type(val) : 
            sys.stderr.write('return value is not dict')
            return False 

        for key in ['vcpus', 'memory_mb', 'local_gb']: 
            if not val.has_key(key) :
                sys.stderr.write('invalid format(missing "%s"). ' % key )
                return False 

        return True 


    # ---> test for nova.scheduler.manager.show_host_resource()

    def test01(self):
        """01: get NotFound exception when dest host not found on DB """

        db.host_get_by_name = Mock( side_effect=exception.NotFound('ERR') )
        result = self.manager.show_host_resource(self.ctxt, 'not-registered-host')
        c1 = ( not result['ret'] )
        c2 = ( 0 == result['msg'].find('No such') )
        self.assertEqual(c1 and c2, True)

    def test02(self):
        """02: get other exception if unexpected err. """

        db.host_get_by_name = Mock( side_effect=TypeError('ERR') )
        self.assertRaises(TypeError, self.manager.show_host_resource, self.ctxt, 'host1' )

    def test03(self):
        """03: no instance found on dest host. """

        db.host_get_by_name = Mock( return_value = self.host1 )
        db.instance_get_all_by_host = Mock( return_value=[])
        ret= self.manager.show_host_resource(self.ctxt, 'host1') 

        c1 = self.check_format(ret)
        v = ret['phy_resource']
        c2 = ( (5 == v['vcpus']) and (20480 == v['memory_mb']) and (876 == v['local_gb']))
        c3 = ( 0 == len(ret['usage']) )
        
        self.assertEqual(c1 and c2 and c3, True)

    def test04(self):
        """04: some instance found on dest host. """

        db.host_get_by_name = Mock( return_value = self.host1 )
        db.instance_get_all_by_host = Mock( return_value=[ self.instance1, 
                                                           self.instance2, 
                                                           self.instance3] )

        db.instance_get_vcpu_sum_by_host_and_project = Mock(return_value=3)
        db.instance_get_memory_sum_by_host_and_project = Mock(return_value=1024)
        db.instance_get_disk_sum_by_host_and_project = Mock(return_value=5)
        
        ret= self.manager.show_host_resource(self.ctxt, 'host1') 

        c1 = self.check_format(ret)
        v = ret['phy_resource']
        c2 = ( (5 == v['vcpus']) and (20480 == v['memory_mb']) and (876 == v['local_gb']))
        c3 = ( 2 == len(ret['usage']) )
        c4 = ( self.instance1['project_id'] in ret['usage'].keys())
        c5 = ( self.instance3['project_id'] in ret['usage'].keys())
        
        self.assertEqual(c1 and c2 and c3 and c4 and c5, True)


    # ---> test for nova.scheduler.manager.has_enough_resource()
    def test05(self):
        """05: when cpu is exccded some instance found on dest host. """

        db.instance_get = Mock(return_value = self.instance6)
        try :
            self.manager.driver.has_enough_resource(self.ctxt, 'i-12345', 'host1') 
        except exception.NotEmpty, e:
            # dont do e.message.find(), because the below message is occured.
            # DeprecationWarning: BaseException.message has been deprecated 
            # as of Python 2.6
            c1 = ( 0 < str(e.args).find('doesnt have enough resource') )
            self.assertTrue(c1, True)
        return False

     
    def test06(self):
        """06: when memory is exccded some instance found on dest host. """

        db.instance_get = Mock(return_value = self.instance7)
        try :
            self.manager.driver.has_enough_resource(self.ctxt, 'i-12345', 'host1') 
        except exception.NotEmpty, e:
            c1 = ( 0 <= str(e.args).find('doesnt have enough resource') )
            self.assertTrue(c1, True)
        return False

    def test07(self):
        """07: when hdd is exccded some instance found on dest host. """

        db.instance_get = Mock(return_value = self.instance8)
        try :
            self.manager.driver.has_enough_resource(self.ctxt, 'i-12345', 'host1') 
        except exception.NotEmpty, e:
            c1 = ( 0 <= str(e.args).find('doesnt have enough resource') )
            self.assertTrue(c1, True)
        return False


    def test08(self):
        """08: everything goes well. (instance_get_all_by_host returns list)"""

        ret= self.manager.driver.has_enough_resource(self.ctxt, 'i-12345', 'host1') 
        self.assertEqual(ret, None)


    def test09(self):
        """09: everything goes well(instance_get_all_by_host returns[]). """

        db.instance_get_all_by_host = Mock(return_value = [] )
        ret= self.manager.driver.has_enough_resource(self.ctxt, 'i-12345', 'host1') 
        self.assertEqual(ret, None)


    # ---> test for nova.scheduler.manager.live_migration()


    def test10(self):
        """10: instance_get issues NotFound. """

        db.instance_get = Mock(side_effect=exception.NotFound("ERR"))
        self.assertRaises(exception.NotFound,
                     self.manager.driver.schedule_live_migration,
                     self.ctxt, 
                     'i-12345', 
                     'host1') 

    def test11(self):
        """11: instance_get issues Unexpected error. """

        db.instance_get = Mock(side_effect=TypeError("ERR"))
        self.assertRaises(TypeError,
                     self.manager.driver.schedule_live_migration,
                     self.ctxt, 
                     'i-12345', 
                     'host1') 

    def test12(self):
        """12: instance state is not power_state.RUNNING. """

        db.instance_get = Mock(return_value=self.instance4)
        try : 
            self.manager.driver.schedule_live_migration(self.ctxt, 'i-12345', 'host1')
        except exception.Invalid, e:
            c1 = (0 <= str(e.args).find('is not running')) 
            self.assertTrue(c1, True)
        return False

    def test13(self):
        """13: instance state_description is not running. """

        db.instance_get = Mock(return_value=self.instance5)
        try : 
            self.manager.driver.schedule_live_migration(self.ctxt, 'i-12345', 'host1')
        except exception.Invalid, e:
            c1 = (0 <= str(e.args).find('is not running')) 
            self.assertTrue(c1, True)
        return False

    def test14(self):
        """14: dest is not compute node.
           (dest is not included in the result of db.service_get_all_by_topic)
        """
        try : 
            self.manager.driver.schedule_live_migration(self.ctxt, 'i-12345', 'host2')
        except exception.Invalid, e:
            c1 = (0 <= str(e.args).find('must be compute node')) 
            self.assertTrue(c1, True)
        return False

    def test15(self):
        """ 15: dest is not alive.(service_is up returns False) """

        self.manager.driver.service_is_up = Mock(return_value=False)
        try : 
            self.manager.driver.schedule_live_migration(self.ctxt, 'i-12345', 'host2')
        except exception.Invalid, e:
            c1 = (0 <= str(e.args).find('is not alive')) 
            self.assertTrue(c1, True)
        return False

    # Cannot test the case of hypervisor type difference and hypervisor 
    # version difference, since we cannot set different mocks to same method..
 
    def test16(self):
        """ 16: stored "cpuinfo" is not string """

        try : 
            self.manager.driver.schedule_live_migration(self.ctxt, 'i-12345', 'host2')
        except exception.Invalid, e:
            c1 = (0 <= str(e.args).find('Unexpected err') )
            self.assertTrue(c1, True)
        return False


    def test17(self):
        """17: rpc.call raises RemoteError(Unexpected error occurs when executing compareCPU) """
        rpc.call = Mock(return_value = rpc.RemoteError(libvirt.libvirtError, 'val', 'traceback'))
        self.assertRaises(rpc.RemoteError,
                     self.manager.driver.schedule_live_migration,
                     self.ctxt, 
                     'i-12345', 
                     'host2') 

    def test18(self):
        """18: rpc.call returns 0 (cpu is not compatible between src and dest) """
        rpc.call = Mock(return_value = 0)
        try : 
            self.manager.driver.schedule_live_migration(self.ctxt, 'i-12345', 'host2') 
        except exception.Invalid, e:
            c1 =  ( 0 <= str(e.args).find('doesnt have compatibility to'))
            self.assertTrue(c1, True)
        return False

    def test19(self):
        """19: raise NotEmpty if host doesnt have enough resource. """

        db.instance_get = Mock(return_value = self.instance8)
        try :
            self.manager.driver.schedule_live_migration(self.ctxt, 'i-12345', 'host2') 
        except exception.NotEmpty, e:
            c1 = ( 0 <= str(e.args).find('doesnt have enough resource') )
            self.assertTrue(c1, True)
        return False


    def test20(self):
        """20: everything goes well. """

        #db.instance_get = Mock(return_value = self.instance8)
        ret= self.manager.driver.schedule_live_migration(self.ctxt, 'i-12345', 'host2') 
        self.assertEqual(ret, self.instance8['host'])


    def tearDown(self):
        """common terminating method. """
        #sys.stdout = self.stdoutBak
        pass

if __name__ == '__main__':
    #unittest.main()
    suite = unittest.TestLoader().loadTestsFromTestCase(SchedulerTestFunctions)
    unittest.TextTestRunner(verbosity=3).run(suite)


