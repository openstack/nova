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


def run_command(cmd, redirect_output=True, check_exit_code=True):
  # Useful for debugging:
  #print >>sys.stderr, ' '.join(cmd)
  if redirect_output:
    stdout = subprocess.PIPE
  else:
    stdout = None

  proc = subprocess.Popen(cmd, stdout=stdout)
  output = proc.communicate()[0]
  if check_exit_code and proc.returncode != 0:
    die('Command "%s" failed.\n%s', ' '.join(cmd), output)
  return output


def check_dependencies():
  """Make sure pip and virtualenv are on the path."""
  # Perl also has a pip program.  Hopefully the user has installed the right one!
  print 'Checking for pip...',
  if not run_command(['which', 'pip'], check_exit_code=False).strip():
    die('ERROR: pip not found.\n\nNova development requires pip,'
        ' please install it using your favorite package management tool '
        ' (e.g. "sudo apt-get install python-pip")')
  print 'done.'

  print 'Checking for virtualenv...',
  if not run_command(['which', 'virtualenv'], check_exit_code=False).strip():
    die('ERROR: virtualenv not found.\n\nNova development requires virtualenv,'
        ' please install it using your favorite package management tool '
        ' (e.g. "sudo easy_install virtualenv")')
  print 'done.'


def create_virtualenv(venv=VENV):
  print 'Creating venv...',
  run_command(['virtualenv', '-q', '--no-site-packages', VENV])
  print 'done.'


def install_dependencies(venv=VENV):
  print 'Installing dependencies with pip (this can take a while)...'
  run_command(['pip', 'install', '-E', venv, '-r', PIP_REQUIRES],
              redirect_output=False)
  run_command(['pip', 'install', '-E', venv, TWISTED_NOVA],
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
