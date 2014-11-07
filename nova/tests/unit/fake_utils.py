# Copyright (c) 2013 Rackspace Hosting
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

"""This modules stubs out functions in nova.utils."""

from nova import utils


def stub_out_utils_spawn_n(stubs):
    """Stubs out spawn_n with a blocking version.

    This aids testing async processes by blocking until they're done.
    """
    def no_spawn(func, *args, **kwargs):
        try:
            return func(*args, **kwargs)
        except Exception:
            # NOTE(danms): This is supposed to simulate spawning
            # of a thread, which would run separate from the parent,
            # and die silently on error. If we don't catch and discard
            # any exceptions here, we're not honoring the usual
            # behavior.
            pass

    stubs.Set(utils, 'spawn_n', no_spawn)
