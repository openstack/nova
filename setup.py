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

import gettext
import glob
import os
import subprocess
import sys

from setuptools import find_packages
from setuptools.command.sdist import sdist

# In order to run the i18n commands for compiling and
# installing message catalogs, we use DistUtilsExtra.
# Don't make this a hard requirement, but warn that
# i18n commands won't be available if DistUtilsExtra is
# not installed...
try:
    from DistUtilsExtra.auto import setup
except ImportError:
    from setuptools import setup
    print "Warning: DistUtilsExtra required to use i18n builders. "
    print "To build nova with support for message catalogs, you need "
    print "  https://launchpad.net/python-distutils-extra >= 2.18"

gettext.install('nova', unicode=1)

from nova.utils import parse_mailmap, str_dict_replace
from nova import version

if os.path.isdir('.bzr'):
    with open("nova/vcsversion.py", 'w') as version_file:
        vcs_cmd = subprocess.Popen(["bzr", "version-info", "--python"],
                                   stdout=subprocess.PIPE)
        vcsversion = vcs_cmd.communicate()[0]
        version_file.write(vcsversion)


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
nova_cmdclass = {'sdist': local_sdist}


try:
    from sphinx.setup_command import BuildDoc

    class local_BuildDoc(BuildDoc):
        def run(self):
            for builder in ['html', 'man']:
                self.builder = builder
                self.finalize_options()
                BuildDoc.run(self)
    nova_cmdclass['build_sphinx'] = local_BuildDoc

except:
    pass


try:
    from babel.messages import frontend as babel
    nova_cmdclass['compile_catalog'] = babel.compile_catalog
    nova_cmdclass['extract_messages'] = babel.extract_messages
    nova_cmdclass['init_catalog'] = babel.init_catalog
    nova_cmdclass['update_catalog'] = babel.update_catalog
except:
    pass


def find_data_files(destdir, srcdir):
    package_data = []
    files = []
    for d in glob.glob('%s/*' % (srcdir, )):
        if os.path.isdir(d):
            package_data += find_data_files(
                                 os.path.join(destdir, os.path.basename(d)), d)
        else:
            files += [d]
    package_data += [(destdir, files)]
    return package_data

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
      data_files=find_data_files('share/nova', 'tools'),
      scripts=['bin/nova-ajax-console-proxy',
               'bin/nova-api',
               'bin/nova-compute',
               'bin/nova-console',
               'bin/nova-dhcpbridge',
               'bin/nova-direct-api',
               'bin/nova-logspool',
               'bin/nova-manage',
               'bin/nova-network',
               'bin/nova-objectstore',
               'bin/nova-scheduler',
               'bin/nova-spoolsentry',
               'bin/stack',
               'bin/nova-volume',
               'bin/nova-vncproxy',
               'tools/nova-debug'],
        py_modules=[])
