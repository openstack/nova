# vim: tabstop=4 shiftwidth=4 softtabstop=4

# Copyright 2013 OpenStack Foundation
# Copyright 2013 IBM Corp.
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

"""Provides methods needed by installation script for OpenStack development
virtual environments.

Since this script is used to bootstrap a virtualenv from the system's Python
environment, it should be kept strictly compatible with Python 2.6.

Synced in from openstack-common
"""

from __future__ import print_function

import optparse
import os
import subprocess
import sys


class InstallVenv(object):

    def __init__(self, root, venv, requirements,
                 test_requirements, py_version,
                 project):
        self.root = root
        self.venv = venv
        self.requirements = requirements
        self.test_requirements = test_requirements
        self.py_version = py_version
        self.project = project

    def die(self, message, *args):
        print(message % args, file=sys.stderr)
        sys.exit(1)

    def check_python_version(self):
        if sys.version_info < (2, 6):
            self.die("Need Python Version >= 2.6")

    def run_command_with_code(self, cmd, redirect_output=True,
                              check_exit_code=True):
        """Runs a command in an out-of-process shell.

        Returns the output of that command. Working directory is self.root.
        """
        if redirect_output:
            stdout = subprocess.PIPE
        else:
            stdout = None

        proc = subprocess.Popen(cmd, cwd=self.root, stdout=stdout)
        output = proc.communicate()[0]
        if check_exit_code and proc.returncode != 0:
            self.die('Command "%s" failed.\n%s', ' '.join(cmd), output)
        return (output, proc.returncode)

    def run_command(self, cmd, redirect_output=True, check_exit_code=True):
        return self.run_command_with_code(cmd, redirect_output,
                                          check_exit_code)[0]

    def get_distro(self):
        if (os.path.exists('/etc/fedora-release') or
                os.path.exists('/etc/redhat-release')):
            return Fedora(
                self.root, self.venv, self.requirements,
                self.test_requirements, self.py_version, self.project)
        else:
            return Distro(
                self.root, self.venv, self.requirements,
                self.test_requirements, self.py_version, self.project)

    def check_dependencies(self):
        self.get_distro().install_virtualenv()

    def create_virtualenv(self, no_site_packages=True):
        """Creates the virtual environment and installs PIP.

        Creates the virtual environment and installs PIP only into the
        virtual environment.
        """
        if not os.path.isdir(self.venv):
            print('Creating venv...', end=' ')
            if no_site_packages:
                self.run_command(['virtualenv', '-q', '--no-site-packages',
                                 self.venv])
            else:
                self.run_command(['virtualenv', '-q', self.venv])
            print('done.')
        else:
            print("venv already exists...")
            pass

    def pip_install(self, *args):
        self.run_command(['tools/with_venv.sh',
                         'pip', 'install', '--upgrade'] + list(args),
                         redirect_output=False)

    def install_dependencies(self):
        print('Installing dependencies with pip (this can take a while)...')

        # First things first, make sure our venv has the latest pip and
        # setuptools.
        self.pip_install('pip>=1.3')
        self.pip_install('setuptools')

        self.pip_install('-r', self.requirements)
        self.pip_install('-r', self.test_requirements)

    def post_process(self):
        self.get_distro().post_process()

    def parse_args(self, argv):
        """Parses command-line arguments."""
        parser = optparse.OptionParser()
        parser.add_option('-n', '--no-site-packages',
                          action='store_true',
                          help="Do not inherit packages from global Python "
                               "install")
        return parser.parse_args(argv[1:])[0]


class Distro(InstallVenv):

    def check_cmd(self, cmd):
        return bool(self.run_command(['which', cmd],
                    check_exit_code=False).strip())

    def install_virtualenv(self):
        if self.check_cmd('virtualenv'):
            return

        if self.check_cmd('easy_install'):
            print('Installing virtualenv via easy_install...', end=' ')
            if self.run_command(['easy_install', 'virtualenv']):
                print('Succeeded')
                return
            else:
                print('Failed')

        self.die('ERROR: virtualenv not found.\n\n%s development'
                 ' requires virtualenv, please install it using your'
                 ' favorite package management tool' % self.project)

    def post_process(self):
        """Any distribution-specific post-processing gets done here.

        In particular, this is useful for applying patches to code inside
        the venv.
        """
        pass


class Fedora(Distro):
    """This covers all Fedora-based distributions.

    Includes: Fedora, RHEL, CentOS, Scientific Linux
    """

    def check_pkg(self, pkg):
        return self.run_command_with_code(['rpm', '-q', pkg],
                                          check_exit_code=False)[1] == 0

    def apply_patch(self, originalfile, patchfile):
        self.run_command(['patch', '-N', originalfile, patchfile],
                         check_exit_code=False)

    def install_virtualenv(self):
        if self.check_cmd('virtualenv'):
            return

        if not self.check_pkg('python-virtualenv'):
            self.die("Please install 'python-virtualenv'.")

        super(Fedora, self).install_virtualenv()

    def post_process(self):
        """Workaround for a bug in eventlet.

        This currently affects RHEL6.1, but the fix can safely be
        applied to all RHEL and Fedora distributions.

        This can be removed when the fix is applied upstream.

        Nova: https://bugs.launchpad.net/nova/+bug/884915
        Upstream: https://bitbucket.org/eventlet/eventlet/issue/89
        RHEL: https://bugzilla.redhat.com/958868
        """

        # Install "patch" program if it's not there
        if not self.check_pkg('patch'):
            self.die("Please install 'patch'.")

        # Apply the eventlet patch
        self.apply_patch(os.path.join(self.venv, 'lib', self.py_version,
                                      'site-packages',
                                      'eventlet/green/subprocess.py'),
                         'contrib/redhat-eventlet.patch')
