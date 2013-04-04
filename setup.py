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
import setuptools

from nova.openstack.common import setup as common_setup

requires = common_setup.parse_requirements()
depend_links = common_setup.parse_dependency_links()
project = 'nova'


setuptools.setup(
      name=project,
      version=common_setup.get_version(project, '2013.2'),
      description='cloud computing fabric controller',
      author='OpenStack',
      author_email='nova@lists.launchpad.net',
      url='http://www.openstack.org/',
      classifiers=[
          'Environment :: OpenStack',
          'Intended Audience :: Information Technology',
          'Intended Audience :: System Administrators',
          'License :: OSI Approved :: Apache Software License',
          'Operating System :: POSIX :: Linux',
          'Programming Language :: Python',
          'Programming Language :: Python :: 2',
          'Programming Language :: Python :: 2.7',
          ],
      cmdclass=common_setup.get_cmdclass(),
      packages=setuptools.find_packages(exclude=['bin', 'smoketests']),
      install_requires=requires,
      dependency_links=depend_links,
      include_package_data=True,
      test_suite='nose.collector',
      setup_requires=['setuptools_git>=0.4'],
      entry_points={
          'console_scripts': [
              'nova-all = nova.cmd.all:main',
              'nova-api = nova.cmd.api:main',
              'nova-api-ec2 = nova.cmd.api_ec2:main',
              'nova-api-metadata = nova.cmd.api_metadata:main',
              'nova-api-os-compute = nova.cmd.api_os_compute:main',
              'nova-baremetal-deploy-helper'
              ' = nova.cmd.baremetal_deploy_helper:main',
              'nova-baremetal-manage = nova.cmd.baremetal_manage:main',
              'nova-rpc-zmq-receiver = nova.cmd.rpc_zmq_receiver:main',
              'nova-cells = nova.cmd.cells:main',
              'nova-cert = nova.cmd.cert:main',
              'nova-clear-rabbit-queues = nova.cmd.clear_rabbit_queues:main',
              'nova-compute = nova.cmd.compute:main',
              'nova-conductor = nova.cmd.conductor:main',
              'nova-console = nova.cmd.console:main',
              'nova-consoleauth = nova.cmd.consoleauth:main',
              'nova-dhcpbridge = nova.cmd.dhcpbridge:main',
              'nova-manage = nova.cmd.manage:main',
              'nova-network = nova.cmd.network:main',
              'nova-novncproxy = nova.cmd.novncproxy:main',
              'nova-objectstore = nova.cmd.objectstore:main',
              'nova-rootwrap = nova.cmd.rootwrap:main',
              'nova-scheduler = nova.cmd.scheduler:main',
              'nova-spicehtml5proxy = nova.cmd.spicehtml5proxy:main',
              'nova-xvpvncproxy = nova.cmd.xvpvncproxy:main'
          ]
      },
      py_modules=[])
