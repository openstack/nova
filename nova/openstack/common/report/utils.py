# Copyright 2013 Red Hat, Inc.
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

"""Various utilities for report generation

This module includes various utilities
used in generating reports.
"""

import gc


class StringWithAttrs(str):
    """A String that can have arbitrary attributes
    """

    pass


def _find_objects(t):
    """Find Objects in the GC State

    This horribly hackish method locates objects of a
    given class in the current python instance's garbage
    collection state.  In case you couldn't tell, this is
    horribly hackish, but is necessary for locating all
    green threads, since they don't keep track of themselves
    like normal threads do in python.

    :param class t: the class of object to locate
    :rtype: list
    :returns: a list of objects of the given type
    """

    return [o for o in gc.get_objects() if isinstance(o, t)]
