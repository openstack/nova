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

import os
import subprocess

from setuptools import setup, find_packages
from setuptools.command.sdist import sdist
from sphinx.setup_command import BuildDoc

from nova.utils import parse_mailmap, str_dict_replace
from nova import version

if os.path.isdir('.bzr'):
    with open("nova/vcsversion.py", 'w') as version_file:
        vcs_cmd = subprocess.Popen(["bzr", "version-info", "--python"],
                                   stdout=subprocess.PIPE)
        vcsversion = vcs_cmd.communicate()[0]
        version_file.write(vcsversion)



class local_BuildDoc(BuildDoc):
    def run(self):
        for builder in ['html', 'man']:
            self.builder = builder
            self.finalize_options()
            BuildDoc.run(self)

class local_sdist(sdist):
    """Customized sdist hook - builds the ChangeLog file from VC first"""

    def run(self):
        if os.path.isdir('.bzr'):
            # We're in a bzr branch
            env = os.environ.copy()
            env['BZR_PLUGIN_PATH'] = os.path.abspath('./bzrplugins')
            log_cmd = subprocess.Popen(["bzr", "log", "--novalog"],
                                       stdout=subprocess.PIPE, env=env)
            changelog = log_cmd.communicate()[0]
            mailmap = parse_mailmap()
            with open("ChangeLog", "w") as changelog_file:
                changelog_file.write(str_dict_replace(changelog, mailmap))
        sdist.run(self)

nova_cmdclass= { 'sdist': local_sdist,
                 'build_sphinx' : local_BuildDoc }

try:
  from babel.messages import frontend as babel
  nova_cmdclass['compile_catalog'] = babel.compile_catalog
  nova_cmdclass['extract_messages'] = babel.extract_messages
  nova_cmdclass['init_catalog'] = babel.init_catalog
  nova_cmdclass['update_catalog'] = babel.update_catalog
except:
  pass

setup(name='nova',
      version=version.canonical_version_string(),
      description='cloud computing fabric controller',
      author='OpenStack',
      author_email='nova@lists.launchpad.net',
      url='http://www.openstack.org/',
      cmdclass=nova_cmdclass,
      packages=find_packages(exclude=['bin', 'smoketests']),
      include_package_data=True,
      test_suite='nose.collector',
      scripts=['bin/nova-api',
               'bin/nova-compute',
               'bin/nova-dhcpbridge',
               'bin/nova-import-canonical-imagestore',
               'bin/nova-instancemonitor',
               'bin/nova-logspool',
               'bin/nova-manage',
               'bin/nova-network',
               'bin/nova-objectstore',
               'bin/nova-scheduler',
               'bin/nova-spoolsentry',
               'bin/nova-volume',
               'tools/nova-debug'])
