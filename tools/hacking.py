# vim: tabstop=4 shiftwidth=4 softtabstop=4

# Copyright (c) 2012, Cloudscaling
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

"""nova HACKING file compliance testing

built on top of pep8.py
"""

import inspect
import os
import re
import sys
import traceback

import pep8

#N1xx comments
#N2xx except
#N3xx imports
#N4xx docstrings
#N5xx dictionaries/lists
#N6xx Calling methods


def nova_todo_format(physical_line):
    """
    nova HACKING guide recommendation for TODO:
    Include your name with TODOs as in "#TODO(termie)"
    N101
    """
    pos = physical_line.find('TODO')
    pos1 = physical_line.find('TODO(')
    pos2 = physical_line.find('#')  # make sure its a comment
    if (pos != pos1 and pos2 >= 0 and pos2 < pos):
        return pos, "NOVA N101: Use TODO(NAME)"


def nova_except_format(logical_line):
    """
    nova HACKING guide recommends not using except:
    Do not write "except:", use "except Exception:" at the very least
    N201
    """
    if logical_line.startswith("except:"):
        return 6, "NOVA N201: no 'except:' at least use 'except Exception:'"


def nova_except_format(logical_line):
    """
    nova HACKING guide recommends not using assertRaises(Exception...):
    Do not use overly broad Exception type
    N202
    """
    if logical_line.startswith("self.assertRaises(Exception"):
        return 1, "NOVA N202: assertRaises Exception too broad"


def nova_one_import_per_line(logical_line):
    """
    nova HACKING guide recommends one import per line:
    Do not import more than one module per line

    Examples:
    BAD: from nova.rpc.common import RemoteError, LOG
    BAD: from sqlalchemy import MetaData, Table
    N301
    """
    pos = logical_line.find(',')
    if (pos > -1 and (logical_line.startswith("import ") or
       (logical_line.startswith("from ") and
       logical_line.split()[2] == "import"))):
        return pos, "NOVA N301: one import per line"


def nova_import_module_only(logical_line):
    """
    nova HACKING guide recommends importing only modules:
    Do not import objects, only modules
    N302 import only modules
    N303 Invalid Import
    N304 Relative Import
    """
    def importModuleCheck(mod, parent=None, added=False):
        """
        If can't find module on first try, recursively check for relative
        imports
        """
        current_path = os.path.dirname(pep8.current_file)
        try:
            valid = True
            if parent:
                parent_mod = __import__(parent, globals(), locals(), [mod], -1)
                valid = inspect.ismodule(getattr(parent_mod, mod))
            else:
                __import__(mod, globals(), locals(), [], -1)
                valid = inspect.ismodule(sys.modules[mod])
            if not valid:
                if added:
                    sys.path.pop()
                    added = False
                    return logical_line.find(mod), ("NOVA N304: No relative "
                        "imports. '%s' is a relative import" % logical_line)

                return logical_line.find(mod), ("NOVA N302: import only "
                    "modules. '%s' does not import a module" % logical_line)

        except (ImportError, NameError):
            if not added:
                added = True
                sys.path.append(current_path)
                return importModuleCheck(mod, parent, added)
            else:
                print >> sys.stderr, ("ERROR: import '%s' failed, couldn't "
                    "find module" % logical_line)
                added = False
                sys.path.pop()
                return

        except AttributeError:
            # Invalid import
            return logical_line.find(mod), ("NOVA N303: Invalid import, "
                "AttributeError raised")

    split_line = logical_line.split()

    # handle "import x"
    # handle "import x as y"
    if (logical_line.startswith("import ") and "," not in logical_line and
            (len(split_line) == 2 or
            (len(split_line) == 4 and split_line[2] == "as"))):
        mod = split_line[1]
        return importModuleCheck(mod)

    # handle "from x import y"
    # handle "from x import y as z"
    elif (logical_line.startswith("from ") and "," not in logical_line and
           split_line[2] == "import" and split_line[3] != "*" and
           (len(split_line) == 4 or
           (len(split_line) == 6  and split_line[4] == "as"))):
        mod = split_line[3]
        return importModuleCheck(mod, split_line[1])

    # TODO(jogo) handle "from x import *"

#TODO(jogo) Dict and list objects

current_file = ""


def readlines(filename):
    """
    record the current file being tested
    """
    pep8.current_file = filename
    return open(filename).readlines()


def add_nova():
    """
    Look for functions that start with nova_  and have arguments
    and add them to pep8 module
    Assumes you know how to write pep8.py checks
    """
    for name, function in globals().items():
        if not inspect.isfunction(function):
            continue
        args = inspect.getargspec(function)[0]
        if args and name.startswith("nova"):
            exec("pep8.%s = %s" % (name, name))

if __name__ == "__main__":
    #include nova path
    sys.path.append(os.getcwd())
    #NOVA error codes start with an N
    pep8.ERRORCODE_REGEX = re.compile(r'[EWN]\d{3}')
    add_nova()
    pep8.current_file = current_file
    pep8.readlines = readlines
    pep8._main()
