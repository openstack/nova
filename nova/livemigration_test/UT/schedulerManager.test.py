#!/usr/bin/python
# -*- coding: UTF-8 -*-

NOVA_DIR='/opt/nova-2010.2'

import sys
import unittest
import commands
import re

from mock import Mock

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
    print 'set PYTHONPATH to nova-install-dir'
    raise 


class tmpStdout:
    def __init__(self):
        self.buffer = ""
    def write(self,arg):
        self.buffer += arg
    def flush(self):
        self.buffer = ''


class SchedulerTestFunctions(unittest.TestCase):

    # 共通の初期化処理
    def setUp(self):
        """common init method. """

        self.host = 'openstack2-api'
        self.manager = SchedulerManager(host=self.host)

        self.setTestData()

    def setTestData(self):  

        self.host1 = Host()
        self.host1.__setitem__('name',    'host1')
        self.host1.__setitem__('cpu', 5)
        self.host1.__setitem__('memory_mb', 20480)
        self.host1.__setitem__('hdd_gb', 876)

        self.host2 = Host()
        self.host2.__setitem__('name', 'host2')
        self.host2.__setitem__('cpu', 5)
        self.host2.__setitem__('memory_mb', 20480)
        self.host2.__setitem__('hdd_gb', 876)

        self.instance1 = Instance()
        for key, val in [ ('id', 1), ('host', 'host1'),   ('hostname', 'i-12345'), 
                          ('state', power_state.RUNNING), ('project_id', 'testPJ'),
                          ('vcpus', 3), ('memory_mb', 1024), ('hdd_gb', 5) ]:
            self.instance1.__setitem__(key, val)


        self.instance2 = Instance()
        for key, val in [ ('id', 2), ('host', 'host1'),   ('hostname', 'i-12345'), 
                          ('state', power_state.RUNNING), ('project_id', 'testPJ'),
                          ('vcpus', 3), ('memory_mb', 1024), ('hdd_gb', 5) ]:
            self.instance2.__setitem__(key, val)


        self.instance3 = Instance()
        for key, val in [ ('id', 3), ('host', 'host1'),   ('hostname', 'i-12345'), 
                          ('state', power_state.RUNNING), ('project_id', 'testPJ2'),
                          ('vcpus', 1), ('memory_mb', 1024), ('hdd_gb', 5) ]:
            self.instance3.__setitem__(key, val)

        self.instance4 = Instance()
        for key, val in [ ('id', 4), ('host', 'host2'),   ('hostname', 'i-12345'), 
                          ('state', power_state.RUNNING), ('project_id', 'testPJ2'),
                          ('vcpus', 1), ('memory_mb', 1024), ('local_gb', 5) ]:
            self.instance4.__setitem__(key, val)

        self.instance5 = Instance()
        for key, val in [ ('id', 5), ('host', 'host2'),   ('hostname', 'i-12345'), 
                          ('state', power_state.RUNNING), ('project_id', 'testPJ2'),
                          ('vcpus', 1), ('memory_mb', 1024), ('local_gb', 5) ]:
            self.instance5.__setitem__(key, val)

        self.instance6 = Instance()
        for key, val in [ ('id', 6), ('host', 'host1'),   ('hostname', 'i-12345'), 
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
                          ('state', power_state.RUNNING), ('project_id', 'testPJ2'),
                          ('vcpus', 1), ('memory_mb', 1024), ('local_gb', 866) ]:
            self.instance8.__setitem__(key, val)



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

        for key in ['cpu', 'memory_mb', 'hdd_gb']: 
            if not val.has_key(key) :
                sys.stderr.write('invalid format(missing "%s"). ' % key )
                return False 

        return True 

    # ---> test for nova.scheduler.manager.show_host_resource()

    def test01(self):
        """01: get NotFound exception when dest host not found on DB """

        ctxt = context.get_admin_context()
        db.host_get_by_name = Mock( side_effect=exception.NotFound('ERR') )
        result = self.manager.show_host_resource(ctxt, 'not-registered-host')
        c1 = ( not result['ret'] )
        c2 = ( 0 == result['msg'].find('No such') )
        self.assertEqual(c1 and c2, True)

    def test02(self):
        """02: get other exception if unexpected err. """

        ctxt = context.get_admin_context()
        db.host_get_by_name = Mock( side_effect=TypeError('ERR') )
        self.assertRaises(TypeError, self.manager.show_host_resource, ctxt, 'host1' )

    def test03(self):
        """03: no instance found on dest host. """

        ctxt = context.get_admin_context()
        db.host_get_by_name = Mock( return_value = self.host1 )
        db.instance_get_all_by_host = Mock( return_value=[])
        ret= self.manager.show_host_resource(ctxt, 'host1') 

        c1 = self.check_format(ret)
        v = ret['phy_resource']
        c2 = ( (5 == v['cpu']) and (20480 == v['memory_mb']) and (876 == v['hdd_gb']))
        c3 = ( 0 == len(ret['usage']) )
        
        self.assertEqual(c1 and c2 and c3, True)

    def test04(self):
        """04: some instance found on dest host. """

        ctxt = context.get_admin_context()
        db.host_get_by_name = Mock( return_value = self.host1 )
        db.instance_get_all_by_host = Mock( return_value=[ self.instance1, 
                                                           self.instance2, 
                                                           self.instance3] )

        db.instance_get_vcpu_sum_by_host_and_project = Mock(return_value=3)
        db.instance_get_memory_sum_by_host_and_project = Mock(return_value=1024)
        db.instance_get_disk_sum_by_host_and_project = Mock(return_value=5)
        
        ret= self.manager.show_host_resource(ctxt, 'host1') 

        c1 = self.check_format(ret)
        v = ret['phy_resource']
        c2 = ( (5 == v['cpu']) and (20480 == v['memory_mb']) and (876 == v['hdd_gb']))
        c3 = ( 2 == len(ret['usage']) )
        c4 = ( self.instance1['project_id'] in ret['usage'].keys())
        c5 = ( self.instance3['project_id'] in ret['usage'].keys())
        
        self.assertEqual(c1 and c2 and c3 and c4 and c5, True)


    # ---> test for nova.scheduler.manager.has_enough_resource()
    def test05(self):
        """05: when cpu is exccded some instance found on dest host. """

        ctxt = context.get_admin_context()
        db.instance_get = Mock(return_value = self.instance6)
        db.host_get_by_name = Mock(return_value = self.host2)
        db.instance_get_all_by_host = Mock(return_value = [self.instance4, self.instance5] )

        ret= self.manager.has_enough_resource(ctxt, 'i-12345', 'host1') 
        self.assertEqual(ret, False)
     
    def test06(self):
        """06: when memory is exccded some instance found on dest host. """

        ctxt = context.get_admin_context()
        db.instance_get = Mock(return_value = self.instance7)
        db.host_get_by_name = Mock(return_value = self.host2)
        db.instance_get_all_by_host = Mock(return_value = [self.instance4, self.instance5] )

        ret= self.manager.has_enough_resource(ctxt, 'i-12345', 'host1') 
        self.assertEqual(ret, False)

    def test07(self):
        """07: when hdd is exccded some instance found on dest host. """

        ctxt = context.get_admin_context()
        db.instance_get = Mock(return_value = self.instance8)
        db.host_get_by_name = Mock(return_value = self.host2)
        db.instance_get_all_by_host = Mock(return_value = [self.instance4, self.instance5] )

        ret= self.manager.has_enough_resource(ctxt, 'i-12345', 'host1') 
        self.assertEqual(ret, False)

    def test08(self):
        """08: everything goes well. (instance_get_all_by_host returns list)"""

        ctxt = context.get_admin_context()
        db.instance_get = Mock(return_value = self.instance3)
        db.host_get_by_name = Mock(return_value = self.host2)
        db.instance_get_all_by_host = Mock(return_value = [self.instance4, self.instance5] )

        ret= self.manager.has_enough_resource(ctxt, 'i-12345', 'host1') 
        self.assertEqual(ret, True)


    def test09(self):
        """09: everything goes well(instance_get_all_by_host returns[]). """

        ctxt = context.get_admin_context()
        db.instance_get = Mock(return_value = self.instance3)
        db.host_get_by_name = Mock(return_value = self.host2)
        db.instance_get_all_by_host = Mock(return_value = [] )

        ret= self.manager.has_enough_resource(ctxt, 'i-12345', 'host1') 
        self.assertEqual(ret, True)


    # ---> test for nova.scheduler.manager.live_migration()


    def test10(self):
        """10: instance_get_by_internal_id issue NotFound. """
        # Mocks for has_enough_resource()
        ctxt = context.get_admin_context()
        db.instance_get = Mock(return_value = self.instance8)
        db.host_get_by_name = Mock(return_value = self.host2)
        db.instance_get_all_by_host = Mock(return_value = [self.instance4, self.instance5] )

        # Mocks for live_migration()db.instance_get_by_internal_id
        # (any Mock is ok here. important mock is all above)
        db.instance_get_by_internal_id = Mock(side_effect=exception.NotFound("ERR"))
 
        self.assertRaises(exception.NotFound,
                     self.manager.live_migration,
                     ctxt, 
                     'i-12345', 
                     'host1') 


    def test11(self):
        """11: return False if host doesnt have enough resource. """

        # Mocks for has_enough_resource()
        ctxt = context.get_admin_context()
        db.instance_get = Mock(return_value = self.instance8)
        db.host_get_by_name = Mock(return_value = self.host2)
        db.instance_get_all_by_host = Mock(return_value = [self.instance4, self.instance5] )

        # Mocks for live_migration()db.instance_get_by_internal_id
        # (any Mock is ok here. important mock is all above)
        db.instance_get_by_internal_id = Mock(return_value = self.instance8)
        db.instance_set_state = Mock(return_value = True)
        rpc_cast = Mock(return_value = True)
 
        ret= self.manager.live_migration(ctxt, 'i-12345', 'host1') 
        self.assertEqual(ret, False)



    def test12(self):
        """12: everything goes well. """

        # Mocks for has_enough_resource()
        ctxt = context.get_admin_context()
        db.instance_get = Mock(return_value = self.instance3)
        db.host_get_by_name = Mock(return_value = self.host2)
        db.instance_get_all_by_host = Mock(return_value = [self.instance4, self.instance5] )

        # Mocks for live_migration()db.instance_get_by_internal_id
        # (any Mock is ok here. important mock is all above)
        db.instance_get_by_internal_id = Mock(return_value = self.instance8)
        db.instance_set_state = Mock(return_value = True)
        rpc.cast = Mock(return_value = True)

        ret= self.manager.live_migration(ctxt, 'i-12345', 'host1') 
        self.assertEqual(ret, True)


    def tearDown(self):
        """common terminating method. """
        #sys.stdout = self.stdoutBak
        pass

if __name__ == '__main__':
    #unittest.main()
    suite = unittest.TestLoader().loadTestsFromTestCase(SchedulerTestFunctions)
    unittest.TextTestRunner(verbosity=3).run(suite)


