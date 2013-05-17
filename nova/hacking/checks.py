# Copyright (c) 2012, Cloudscaling
# All Rights Reserved.
#
# Licensed under the Apache License, Version 2.0 (the "License"); you may
# not use this file except in compliance with the License. You may obtain
# a copy of the License at
#
#      http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
# WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
# License for the specific language governing permissions and limitations
# under the License.


def import_no_db_in_virt(logical_line, filename):
    """Check for db calls from nova/virt

    As of grizzly-2 all the database calls have been removed from
    nova/virt, and we want to keep it that way.

    N307
    """
    if "nova/virt" in filename and not filename.endswith("fake.py"):
        if logical_line.startswith("from nova import db"):
            yield (0, "N307: nova.db import not allowed in nova/virt/*")


def except_python3x_compatible(logical_line, filename):
    """Check for except statements to be Python 3.x compatible

    As of Python 3.x, the construct "except x,y:" has been removed.

    N308
    """

    def is_old_style_except(logical_line):
        # Should match:
        #     except ProcessExecutionError, exn:
        # Should not match:
        #     except UncodeError:
        #     except (x,y):
        return (',' in logical_line
                and ')' not in logical_line.rpartition(',')[2])

    if ("except " in logical_line
            and logical_line.endswith(':')
            and is_old_style_except(logical_line)):
        yield(0, "N308: Python 3.x incompatible 'except x,y:' construct")


def factory(register):
    register(import_no_db_in_virt)
    register(except_python3x_compatible)
