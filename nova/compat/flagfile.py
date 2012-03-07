# vim: tabstop=4 shiftwidth=4 softtabstop=4

# Copyright (c) 2012 Red Hat, Inc.
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

import contextlib
import os
import shutil
import tempfile

'''
Compatibility code for handling the deprecated --flagfile option.

gflags style configuration files are deprecated and will be removed in future.

The code in this module transles --flagfile options into --config-file and can
be removed when support for --flagfile is removed.
'''


def _get_flagfile(argp):
    '''Parse the filename from a --flagfile argument.

    The current and next arguments are passed as a 2 item list. If the
    flagfile filename is in the next argument, the two arguments are
    joined into the first item while the second item is set to None.
    '''
    i = argp[0].find('-flagfile')
    if i < 0:
        return None

    # Accept -flagfile or -flagfile
    if i != 0 and (i != 1 or argp[0][i] != '-'):
        return None

    i += len('-flagfile')
    if i == len(argp[0]):  # Accept [-]-flagfile foo
        argp[0] += '=' + argp[1]
        argp[1] = None

    if argp[0][i] != '=':  # Accept [-]-flagfile=foo
        return None

    return argp[0][i + 1:]


def _open_file_for_reading(path):
    '''Helper method which test code may stub out.'''
    return open(path, 'r')


def _open_fd_for_writing(fd, _path):
    '''Helper method which test code may stub out.'''
    return os.fdopen(fd, 'w')


def _read_lines(flagfile):
    '''Read a flag file, returning all lines with comments stripped.'''
    with _open_file_for_reading(flagfile) as f:
        lines = f.readlines()
    ret = []
    for l in lines:
        if l.isspace() or l.startswith('#') or l.startswith('//'):
            continue
        ret.append(l.strip())
    return ret


def _read_flagfile(arg, next_arg, tempdir=None):
    '''Convert a --flagfile argument to --config-file.

    If the supplied argument is a --flagfile argument, read the contents
    of the file and convert it to a .ini format config file. Return a
    --config-file argument with the converted file.

    If the flag file contains more --flagfile arguments, multiple
    --config-file arguments will be returned.

    The returned argument list may also contain None values which should
    be filtered out later.
    '''
    argp = [arg, next_arg]
    flagfile = _get_flagfile(argp)
    if not flagfile:
        return argp

    args = _read_lines(flagfile)

    if args and not args[0].startswith('--'):
        # This is a config file, not a flagfile, so return it.
        return ['--config-file=' + flagfile] + argp[1:]

    #
    # We're recursing here to convert any --flagfile arguments
    # read from this flagfile into --config-file arguments
    #
    # We don't actually include those --config-file arguments
    # in the generated config file; instead we include all those
    # --config-file args in the final command line
    #
    args = _iterate_args(args, _read_flagfile, tempdir=tempdir)

    config_file_args = []

    (fd, tmpconf) = tempfile.mkstemp(suffix='.conf', dir=tempdir)

    with _open_fd_for_writing(fd, tmpconf) as f:
        f.write('[DEFAULT]\n')
        for arg in args:
            if arg.startswith('--config-file='):
                config_file_args.append(arg)
                continue
            if '=' in arg:
                f.write(arg[2:] + '\n')
            elif arg[2:].startswith('no'):
                f.write(arg[4:] + '=false\n')
            else:
                f.write(arg[2:] + '=true\n')

    return ['--config-file=' + tmpconf] + argp[1:] + config_file_args


def _iterate_args(args, iterator, **kwargs):
    '''Run an iterator function on the supplied args list.

    The iterator is passed the current arg and next arg and returns a
    list of args. The returned args replace the suppied args in the
    resulting args list.

    The iterator will be passed None for the next arg when processing
    the last arg.
    '''
    args.append(None)

    ret = []
    for i in range(len(args)):
        if args[i] is None:  # last item, or consumed file name
            continue

        modified = iterator(args[i], args[i + 1], **kwargs)
        args[i], args[i + 1] = modified[:2]

        ret.extend(modified[:1] + modified[2:])  # don't append next arg

    return filter(None, ret)


def handle_flagfiles(args, tempdir=None):
    '''Replace --flagfile arguments with --config-file arguments.

    Replace any --flagfile argument in the supplied list with a --config-file
    argument containing a temporary config file with the contents of the flag
    file translated to .ini format.

    The tempdir argument is a directory which will be used to create temporary
    files.
    '''
    return _iterate_args(args[:], _read_flagfile, tempdir=tempdir)


@contextlib.contextmanager
def handle_flagfiles_managed(args):
    '''A context manager for handle_flagfiles() which removes temp files.

    For use with the 'with' statement, i.e.::

        with handle_flagfiles_managed(args) as args:
             # Do stuff
        # Any temporary fils have been removed
    '''
    # NOTE(johannes): Would be nice to use utils.tempdir(), but it
    # causes an import loop
    tempdir = tempfile.mkdtemp(prefix='nova-conf-')
    try:
        yield handle_flagfiles(args, tempdir=tempdir)
    finally:
        shutil.rmtree(tempdir)
