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

"""
System-level utilities and helper functions.
"""

import datetime
import inspect
import logging
import os
import random
import subprocess
import socket
import sys

from twisted.internet.threads import deferToThread

from nova import exception
from nova import flags
from nova.exception import ProcessExecutionError


FLAGS = flags.FLAGS
TIME_FORMAT = "%Y-%m-%dT%H:%M:%SZ"


def import_class(import_str):
    """Returns a class from a string including module and class"""
    mod_str, _sep, class_str = import_str.rpartition('.')
    try:
        __import__(mod_str)
        return getattr(sys.modules[mod_str], class_str)
    except (ImportError, ValueError, AttributeError):
        raise exception.NotFound('Class %s cannot be found' % class_str)


def import_object(import_str):
    """Returns an object including a module or module and class"""
    try:
        __import__(import_str)
        return sys.modules[import_str]
    except ImportError:
        cls = import_class(import_str)
        return cls()


def fetchfile(url, target):
    logging.debug("Fetching %s" % url)
#    c = pycurl.Curl()
#    fp = open(target, "wb")
#    c.setopt(c.URL, url)
#    c.setopt(c.WRITEDATA, fp)
#    c.perform()
#    c.close()
#    fp.close()
    execute("curl --fail %s -o %s" % (url, target))


def execute(cmd, process_input=None, addl_env=None, check_exit_code=True):
    logging.debug("Running cmd: %s", cmd)
    env = os.environ.copy()
    if addl_env:
        env.update(addl_env)
    obj = subprocess.Popen(cmd, shell=True, stdin=subprocess.PIPE,
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=env)
    result = None
    if process_input != None:
        result = obj.communicate(process_input)
    else:
        result = obj.communicate()
    obj.stdin.close()
    if obj.returncode:
        logging.debug("Result was %s" % (obj.returncode))
        if check_exit_code and obj.returncode != 0:
            (stdout, stderr) = result
            raise ProcessExecutionError(exit_code=obj.returncode,
                                        stdout=stdout,
                                        stderr=stderr,
                                        cmd=cmd)
    return result


def abspath(s):
    return os.path.join(os.path.dirname(__file__), s)


def novadir(s):
    return os.path.abspath(nova.__file__).split('nova/__init__.pyc')[0]


def default_flagfile(filename='nova.conf'):
    for arg in sys.argv:
        if arg.find('flagfile') != -1:
            break
    else:
        if not os.path.isabs(filename):
            # turn relative filename into an absolute path
            script_dir = os.path.dirname(inspect.stack()[-1][1])
            filename = os.path.abspath(os.path.join(script_dir, filename))
        if os.path.exists(filename):
            flagfile = ['--flagfile=%s' % filename]
            sys.argv = sys.argv[:1] + flagfile + sys.argv[1:]


def debug(arg):
    logging.debug('debug in callback: %s', arg)
    return arg


def runthis(prompt, cmd, check_exit_code=True):
    logging.debug("Running %s" % (cmd))
    exit_code = subprocess.call(cmd.split(" "))
    logging.debug(prompt % (exit_code))
    if check_exit_code and exit_code != 0:
        raise ProcessExecutionError(exit_code=exit_code,
                                    stdout=None,
                                    stderr=None,
                                    cmd=cmd)


def generate_uid(topic, size=8):
    if topic == "i":
        # Instances have integer internal ids.
        return random.randint(0, 2 ** 32 - 1)
    else:
        characters = '01234567890abcdefghijklmnopqrstuvwxyz'
        choices = [random.choice(characters) for x in xrange(size)]
        return '%s-%s' % (topic, ''.join(choices))


def generate_mac():
    mac = [0x02, 0x16, 0x3e,
           random.randint(0x00, 0x7f),
           random.randint(0x00, 0xff),
           random.randint(0x00, 0xff)]
    return ':'.join(map(lambda x: "%02x" % x, mac))


def last_octet(address):
    return int(address.split(".")[-1])


def get_my_ip():
    """Returns the actual ip of the local machine."""
    if getattr(FLAGS, 'fake_tests', None):
        return '127.0.0.1'
    try:
        csock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        csock.connect(('www.google.com', 80))
        (addr, port) = csock.getsockname()
        csock.close()
        return addr
    except socket.gaierror as ex:
        logging.warn("Couldn't get IP, using 127.0.0.1 %s", ex)
        return "127.0.0.1"


def isotime(at=None):
    if not at:
        at = datetime.datetime.utcnow()
    return at.strftime(TIME_FORMAT)


def parse_isotime(timestr):
    return datetime.datetime.strptime(timestr, TIME_FORMAT)


class LazyPluggable(object):
    """A pluggable backend loaded lazily based on some value."""

    def __init__(self, pivot, **backends):
        self.__backends = backends
        self.__pivot = pivot
        self.__backend = None

    def __get_backend(self):
        if not self.__backend:
            backend_name = self.__pivot.value
            if backend_name not in self.__backends:
                raise exception.Error('Invalid backend: %s' % backend_name)

            backend = self.__backends[backend_name]
            if type(backend) == type(tuple()):
                name = backend[0]
                fromlist = backend[1]
            else:
                name = backend
                fromlist = backend

            self.__backend = __import__(name, None, None, fromlist)
            logging.info('backend %s', self.__backend)
        return self.__backend

    def __getattr__(self, key):
        backend = self.__get_backend()
        return getattr(backend, key)


def deferredToThread(f):
    def g(*args, **kwargs):
        return deferToThread(f, *args, **kwargs)
    return g
