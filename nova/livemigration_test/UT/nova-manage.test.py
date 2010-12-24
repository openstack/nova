#!/usr/bin/python
# -*- coding: UTF-8 -*-

NOVA_DIR='/opt/nova-2010.4'

import sys
import os
import unittest
import commands
import re

from mock import Mock

# getting /nova-inst-dir
NOVA_DIR = os.path.abspath(sys.argv[0])
for i in range(4):
    NOVA_DIR = os.path.dirname(NOVA_DIR)


try : 
    print
    print 'Testing %s/bin/nova-manage, set the NOVA_DIR properly..' % NOVA_DIR
    print

    sys.path.append(NOVA_DIR)

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

class tmpStderr(tmpStdout):
    def write(self, arg):
        self.buffer += arg
    def flush(self):
        pass
    def realFlush(self):
        self.buffer = ''


class NovaManageTestFunctions(unittest.TestCase):

    stdout = None
    stdoutBak = None
    stderr = None
    stderrBak = None

    hostCmds = None
    
    # 共通の初期化処理
    def setUp(self):
        """common init method. """

        commands.getstatusoutput('cp -f %s/bin/nova-manage %s' % ( NOVA_DIR, self.getNovaManageCopyPath() ))
        commands.getstatusoutput('touch  %s' % self.getInitpyPath() )
        try : 
            import bin.novamanagetest
        except: 
            print 'Fail to import nova-manage . check bin/nova-manage exists'
            raise

        # replace stdout for checking nova-manage output
        if self.stdout is None : 
            self.__class__.stdout = tmpStdout()
        self.stdoutBak = sys.stdout
        sys.stdout = self.stdout

        # replace stderr for checking nova-manage output
        if self.stderr is None:
            self.__class__.stderr = tmpStderr()
        self.stderrBak = sys.stderr
        sys.stderr = self.stderr

        # prepare test data
        self.setTestData()


    def setTestData(self):  
        import bin.novamanagetest

        if self.hostCmds is None : 
            self.__class__.hostCmds = bin.novamanagetest.HostCommands()
        self.instanceCmds = bin.novamanagetest.InstanceCommands()

        self.host1 = Host()
        self.host1.__setitem__('name', 'host1')

        self.host2 = Host()
        self.host2.__setitem__('name', 'host2')

        self.instance1 = Instance()
        self.instance1.__setitem__('id', 1)
        self.instance1.__setitem__('host', 'host1')
        self.instance1.__setitem__('hostname', 'i-12345')
        self.instance1.__setitem__('state', power_state.NOSTATE)
        self.instance1.__setitem__('state_description', 'running')

        self.instance2 = Instance()
        self.instance2.__setitem__('id', 2)
        self.instance2.__setitem__('host', 'host1')
        self.instance2.__setitem__('hostname', 'i-12345')
        self.instance2.__setitem__('state', power_state.RUNNING)
        self.instance2.__setitem__('state_description', 'pending')

        self.instance3 = Instance()
        self.instance3.__setitem__('id', 3)
        self.instance3.__setitem__('host', 'host1')
        self.instance3.__setitem__('hostname', 'i-12345')
        self.instance3.__setitem__('state', power_state.RUNNING)
        self.instance3.__setitem__('state_description', 'running')

        db.host_get_all = Mock(return_value=[self.host1, self.host2])

    def getInitpyPath(self): 
        return '%s/bin/__init__.py' % NOVA_DIR

    def getNovaManageCopyPath(self):
        return '%s/bin/novamanagetest.py' % NOVA_DIR

    # -----> Test for nova-manage host list 

    def test01(self):
        """01: Got some host lists. """

        self.hostCmds.list()

        c1 = (2 == self.stdout.buffer.count('\n'))
        c2 = (0 <= self.stdout.buffer.find('host1'))
        c3 = (0 <= self.stdout.buffer.find('host2'))
        self.assertEqual(c1 and c2 and c3, True)

    def test02(self):
        """02: Got empty lsit. """

        db.host_get_all = Mock(return_value=[])
        self.hostCmds.list()

        # result should be empty
        c = (0 == len(self.stdout.buffer) )
        self.assertEqual(c, True)
        
    def test03(self):
        """03: Got notFound  """

        db.host_get_all = Mock(side_effect=exception.NotFound("ERR"))
        self.assertRaises(exception.NotFound, self.hostCmds.list)

    # --------> Test For nova-manage host show

    def test04(self):
        """04: args are not enough(nova-manage host show) """
        self.assertRaises(TypeError, self.hostCmds.show )


    def test05(self):
        """05: nova-manage host show not-registered-host, and got an error"""

        rpc.call = Mock(return_value={'ret' : False, 'msg': 'ERR'} )
        self.hostCmds.show('host1')
        self.assertEqual( self.stdout.buffer[:3]=='ERR', True )


    def test06(self):
        """06: nova-manage host show registerd-host, and no project uses the host"""

        dic = {'ret': True, 
               'phy_resource': {'vcpus':1, 'memory_mb':2, 'local_gb':3}, 
               'usage': {}}
        
        rpc.call = Mock(return_value=dic )
        self.hostCmds.show('host1')

        # result should be :
        # HOST            PROJECT         cpu     mem(mb) disk(gb)
        # host1                           1       2       3 
        line = self.stdout.buffer.split('\n')[1]
        line = re.compile('\t+').sub(' ', line).strip()
        c1 = ( 'host1 1 2 3' == line )
        c2 = ( self.stdout.buffer.count('\n') == 2 )
     
        self.assertEqual( c1 and c2, True )

    def test07(self):
        """07: nova-manage host show registerd-host, 
           and some projects use the host
        """
        dic = {'ret': True, 
               'phy_resource': {'vcpus':1, 'memory_mb':2, 'local_gb':3}, 
               'usage': {'p1': {'vcpus':1, 'memory_mb':2, 'local_gb':3},
                         'p2': {'vcpus':1, 'memory_mb':2, 'local_gb':3} }}
        
        rpc.call = Mock(return_value=dic )
        self.hostCmds.show('host1')

        # result should be :
        # HOST            PROJECT         cpu     mem(mb) disk(gb)
        # host1                           1       2       3
        # host1           p1              1       2       3 
        # host1           p2              4       5       6
        line = self.stdout.buffer.split('\n')[1]
        ret = re.compile('\t+').sub(' ', line).strip()
        c1 = ( 'host1 1 2 3' == ret )
        
        line = self.stdout.buffer.split('\n')[2]
        line = re.compile('\t+').sub(' ', line).strip()
        c2 = ( 'host1 p1 1 2 3' == line ) or ( 'host1 p2 1 2 3' == line )

        line = self.stdout.buffer.split('\n')[3]
        ret = re.compile('\t+').sub(' ', line).strip()
        c3 = ( 'host1 p1 1 2 3' == ret ) or ( 'host1 p2 1 2 3' == ret )

        self.assertEqual( c1 and c2 and c3, True )

    def test08(self): 
        """08: nova-manage host show registerd-host, and rpc.call returns None
           (unexpected error)
        """
        rpc.call = Mock(return_value=None )
        self.hostCmds.show('host1')
        c1 = ( 0 <=  self.stdout.buffer.find('Unexpected error') )
        self.assertEqual( c1,  True )

    # ----------> Test for bin/nova-manage instance live_migration

    def test09(self):
        """09: arguments are not enough(nova-manage instances live_migration)
        """
        self.assertRaises(TypeError, self.instanceCmds.live_migration )

    def test10(self):
        """10: arguments are not enough(nova-manage instances live_migration ec2_id)
        """
        self.assertRaises(TypeError, self.instanceCmds.live_migration, 'i-xxx' )

    def test11(self):
        """11: nova-manage instances live_migration ec2_id host, 
           where hostname is invalid
        """
        db.host_get_by_name = Mock( side_effect=exception.NotFound('ERR') )
        self.assertRaises(exception.NotFound, self.instanceCmds.live_migration, 'i-xxx', 'host1' )

    def test12(self):
        """12: nova-manage instances live_migration ec2_id(invalid id) host"""

        db.host_get_by_name = Mock(return_value = self.host1)
        db.instance_get_by_internal_id = Mock( side_effect=exception.NotFound('ERR') )

        self.assertRaises(exception.NotFound, self.instanceCmds.live_migration, 'i-xxx', 'host1' )

    def test13(self):
        """13: nova-manage instances live_migration ec2_id host, 
           but instance specifed by ec2 id is not running (state is not power_state.RUNNING)
        """
        db.host_get_by_name = Mock(return_value = self.host1)
        db.instance_get_by_internal_id = Mock( return_value = self.instance1 )
        try : 
            self.instanceCmds.live_migration('i-12345', 'host1')
        except exception.Invalid, e: 
            c1 = (0 < e.message.find('is not running') )
            self.assertTrue(c1, True)
        return False


    def test14(self):
        """14: nova-manage instances live_migration ec2_id host, 
           but instance specifed by ec2 id is not running (state_description is not running)
        """
        db.host_get_by_name = Mock(return_value = self.host2)
        db.instance_get_by_internal_id = Mock( return_value = self.instance1 )
        try : 
            self.instanceCmds.live_migration('i-12345', 'host2')
        except exception.Invalid, e: 
            c1 = (0 < e.message.find('is not running') )
            self.assertTrue(c1, True)
        return False

    def test15(self):
        """15: nova-manage instances live_migration ec2_id host, 
           but instance is running at the same host specifed above, so err should be occured.
        """
        db.host_get_by_name = Mock(return_value = self.host1)
        db.instance_get_by_internal_id = Mock( return_value = self.instance3 )
        try : 
            self.instanceCmds.live_migration('i-12345', 'host1')
        except exception.Invalid, e: 
            c1 = ( 0 <= e.message.find('is running now') )
            self.assertTrue(c1, True)
        return False


    def test16(self):
        """16: nova-manage instances live_migration ec2_id host, 
           rpc.call raises RemoteError because destination doesnt have enough resource.
        """
        db.host_get_by_name = Mock(return_value = self.host1)
        db.instance_get_by_internal_id = Mock( return_value = self.instance3 )
        rpc.call = Mock(return_value = rpc.RemoteError(TypeError, 'val', 'traceback'))
        self.assertRaises(rpc.RemoteError, self.instanceCmds.live_migration, 'i-xxx', 'host2' )
        

    def test17(self):
        """17: nova-manage instances live_migration ec2_id host, 
           everything goes well, ang gets success messages.
        """
        db.host_get_by_name = Mock(return_value = self.host1)
        db.instance_get_by_internal_id = Mock( return_value = self.instance3 )
        rpc.call = Mock(return_value = None)

        self.instanceCmds.live_migration('i-12345', 'host2')
        c1 = (0 <= self.stdout.buffer.find('Finished all procedure') )
        self.assertEqual( c1, True )
        

    def tearDown(self):
        """common terminating method. """
        commands.getstatusoutput('rm -rf %s' % self.getInitpyPath() )
        commands.getstatusoutput('rm -rf %s' % self.getNovaManageCopyPath() )
        sys.stdout.flush()
        sys.stdout = self.stdoutBak
        self.stderr.realFlush()
        sys.stderr = self.stderrBak

if __name__ == '__main__':
    #unittest.main()
    suite = unittest.TestLoader().loadTestsFromTestCase(NovaManageTestFunctions)
    unittest.TextTestRunner(verbosity=3).run(suite)


