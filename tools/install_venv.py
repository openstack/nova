# vim: tabstop=4 shiftwidth=4 softtabstop=4

# Copyright 2010 United States Government as represented by the
# Administrator of the National Aeronautics and Space Administration.
# All Rights Reserved.
#
# Copyright 2010 OpenStack Foundation
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

import os
import sys

import install_venv_common as install_venv


def print_help(venv, root):
    help = """
    Nova development environment setup is complete.

    Nova development uses virtualenv to track and manage Python dependencies
    while in development and testing.

    To activate the Nova virtualenv for the extent of your current shell
    session you can run:

    $ source %s/bin/activate

    Or, if you prefer, you can run commands in the virtualenv on a case by case
    basis by running:

    $ %s/tools/with_venv.sh <your command>

    Also, make test will automatically use the virtualenv.
    """
    print help % (venv, root)


def main(argv):
    root = os.path.dirname(os.path.dirname(os.path.realpath(__file__)))

    if os.environ.get('tools_path'):
        root = os.environ['tools_path']
    venv = os.path.join(root, '.venv')
    if os.environ.get('venv'):
        venv = os.environ['venv']

    pip_requires = os.path.join(root, 'requirements.txt')
    test_requires = os.path.join(root, 'test-requirements.txt')
    py_version = "python%s.%s" % (sys.version_info[0], sys.version_info[1])
    project = 'Nova'
    install = install_venv.InstallVenv(root, venv, pip_requires, test_requires,
                             py_version, project)
    options = install.parse_args(argv)
    install.check_python_version()
    install.check_dependencies()
    install.create_virtualenv(no_site_packages=options.no_site_packages)
    install.install_dependencies()
    install.post_process()
    print_help(venv, root)

if __name__ == '__main__':
    main(sys.argv)
