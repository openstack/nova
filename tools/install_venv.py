# vim: tabstop=4 shiftwidth=4 softtabstop=4

# Copyright 2010 United States Government as represented by the
# Administrator of the National Aeronautics and Space Administration.
# All Rights Reserved.
#
# Copyright 2010 OpenStack, LLC
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

"""
Installation script for Nova's development virtualenv
"""

import os
import subprocess
import sys


ROOT = os.path.dirname(os.path.dirname(__file__))
VENV = os.path.join(ROOT, '.nova-venv')
PIP_REQUIRES = os.path.join(ROOT, 'tools', 'pip-requires')
TWISTED_NOVA='http://nova.openstack.org/Twisted-10.0.0Nova.tar.gz'

def die(message, *args):
  print >>sys.stderr, message % args
  sys.exit(1)


def run_command(cmd, redirect_output=True, error_ok=False):
  """Runs a command in an out-of-process shell, returning the
  output of that command
  """
  if redirect_output:
    stdout = subprocess.PIPE
  else:
    stdout = None

  proc = subprocess.Popen(cmd, stdout=stdout)
  output = proc.communicate()[0]
  if not error_ok and proc.returncode != 0:
    die('Command "%s" failed.\n%s', ' '.join(cmd), output)
  return output


HAS_EASY_INSTALL = bool(run_command(['which', 'easy_install']).strip())
HAS_VIRTUALENV = bool(run_command(['which', 'virtualenv']).strip())


def check_dependencies():
  """Make sure virtualenv is in the path."""

  print 'Checking for virtualenv...',
  if not HAS_VIRTUALENV:
    print 'not found.'
    # Try installing it via easy_install...
    if HAS_EASY_INSTALL:
      print 'Installing virtualenv via easy_install...',
      if not run_command(['which', 'easy_install']):
        die('ERROR: virtualenv not found.\n\nNova development requires virtualenv,'
            ' please install it using your favorite package management tool')
      print 'done.'
  print 'done.'


def create_virtualenv(venv=VENV):
  """Creates the virtual environment and installs PIP only into the
  virtual environment
  """
  print 'Creating venv...',
  run_command(['virtualenv', '-q', '--no-site-packages', VENV])
  print 'done.'
  print 'Installing pip in virtualenv...',
  if not run_command(['tools/with_venv.sh', 'easy_install', 'pip']).strip():
    die("Failed to install pip.")
  print 'done.'


def install_dependencies(venv=VENV):
  print 'Installing dependencies with pip (this can take a while)...'
  run_command(['tools/with_venv.sh', 'pip', 'install', '-E', venv, '-r', PIP_REQUIRES],
              redirect_output=False)
  run_command(['tools/with_venv.sh', 'pip', 'install', '-E', venv, TWISTED_NOVA],
              redirect_output=False)


def print_help():
  help = """
 Nova development environment setup is complete.

 Nova development uses virtualenv to track and manage Python dependencies
 while in development and testing.

 To activate the Nova virtualenv for the extent of your current shell session
 you can run:

 $ source .nova-venv/bin/activate 

 Or, if you prefer, you can run commands in the virtualenv on a case by case
 basis by running:

 $ tools/with_venv.sh <your command>

 Also, make test will automatically use the virtualenv.
  """
  print help


def main(argv):
  check_dependencies()
  create_virtualenv()
  install_dependencies()
  print_help()

if __name__ == '__main__':
  main(sys.argv)
