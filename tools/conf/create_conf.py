# vim: tabstop=4 shiftwidth=4 softtabstop=4

# Copyright 2012 SINA Corporation
# All Rights Reserved.
# Author: Zhongyue Luo <lzyeval@gmail.com>
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

"""Generates a nova.conf file."""

import os
import re
import sys


_PY_EXT = ".py"
_FLAGS = "FLAGS"

_STROPT = "StrOpt"
_BOOLOPT = "BoolOpt"
_INTOPT = "IntOpt"
_FLOATOPT = "FloatOpt"
_LISTOPT = "ListOpt"
_MULTISTROPT = "MultiStrOpt"

_OPTION_CACHE = list()
_OPTION_REGEX = re.compile(r"(%s)" % "|".join([_STROPT, _BOOLOPT, _INTOPT,
                                               _FLOATOPT, _LISTOPT,
                                               _MULTISTROPT]))


def main(srcfiles):

    def mod_prefer(mod_str):
        prefer = ["flags.py", "log.py", "utils.py", "service.py"]
        return prefer.index(mod_str) if mod_str in prefer else ord(mod_str[0])

    def pkg_prefer(pkg_str):
        prefer = ["auth", "api", "vnc", "ipv6", "network", "compute", "virt",
                  "console", "consoleauth", "image"]
        return prefer.index(pkg_str) if pkg_str in prefer else ord(pkg_str[0])

    print '#' * 20 + '\n# nova.conf sample #\n' + '#' * 20
    # NOTE(lzyeval): sort top level modules and packages
    #                to process modules first
    print
    print '[DEFAULT]'
    print
    mods_by_pkg = dict()
    for filepath in srcfiles:
        pkg_name = filepath.split(os.sep)[3]
        mod_str = '.'.join(['.'.join(filepath.split(os.sep)[2:-1]),
                            os.path.basename(filepath).split('.')[0]])
        mods = mods_by_pkg.get(pkg_name, list())
        if not mods:
            mods_by_pkg[pkg_name] = mods
        mods.append(mod_str)
    # NOTE(lzyeval): place top level modules before packages
    pkg_names = filter(lambda x: x.endswith(_PY_EXT), mods_by_pkg.keys())
    pkg_names.sort(key=lambda x: mod_prefer(x))
    ext_names = filter(lambda x: x not in pkg_names, mods_by_pkg.keys())
    ext_names.sort(key=lambda x: pkg_prefer(x))
    pkg_names.extend(ext_names)
    for pkg_name in pkg_names:
        mods = mods_by_pkg.get(pkg_name)
        mods.sort()
        for mod_str in mods:
            print_module(mod_str)


def print_module(mod_str):
    opts = list()
    flags = None
    if mod_str.endswith('.__init__'):
        mod_str = mod_str[:mod_str.rfind(".")]
    try:
        __import__(mod_str)
        flags = getattr(sys.modules[mod_str], _FLAGS)
    except (ValueError, AttributeError), err:
        return
    except ImportError, ie:
        sys.stderr.write("%s\n" % str(ie))
        return
    except Exception, e:
        return
    for opt_name in sorted(flags.keys()):
        # check if option was processed
        if opt_name in _OPTION_CACHE:
            continue
        opt_dict = flags._get_opt_info(opt_name)
        opts.append(opt_dict['opt'])
        _OPTION_CACHE.append(opt_name)
    # return if flags has no unique options
    if not opts:
        return
    # print out module info
    print '######### defined in %s #########' % mod_str
    print
    for opt in opts:
        print_opt(opt)
    print


def print_opt(opt):
    opt_type = None
    try:
        opt_type = _OPTION_REGEX.search(str(type(opt))).group(0)
    except (ValueError, AttributeError), err:
        sys.stderr.write("%s\n" % str(err))
        sys.exit(1)
    # print out option info
    print "######", "".join(["(", opt_type, ")"]), opt.help
    if opt.default is None:
        print '# %s=<None>' % opt.name
    else:
        if opt_type == 'StrOpt':
            print '# %s="%s"' % (opt.name, opt.default)
        elif opt_type == 'ListOpt':
            print '# %s="%s"' % (opt.name, ','.join(opt.default))
        elif opt_type == 'MultiStrOpt':
            for default in opt.default:
                print '# %s="%s"' % (opt.name, default)
        elif opt_type == 'BoolOpt':
            print '# %s=%s' % (opt.name, str(opt.default).lower())
        else:
            print '# %s=%s' % (opt.name, opt.default)


if __name__ == '__main__':
    if len(sys.argv) < 2:
        print "usage: python %s [srcfile]...\n" % sys.argv[0]
        sys.exit(0)
    main(sys.argv[1:])
    print "#", "Total option count: %d" % len(_OPTION_CACHE)
