# Copyright (c) 2013 The Johns Hopkins University/Applied Physics Laboratory
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

from nova.volume.encryptors import base


class NoOpEncryptor(base.VolumeEncryptor):
    """A VolumeEncryptor that does nothing.

    This class exists solely to wrap regular (i.e., unencrypted) volumes so
    that they do not require special handling with respect to an encrypted
    volume. This implementation performs no action when a volume is attached
    or detached.
    """
    def __init__(self, connection_info, **kwargs):
        super(NoOpEncryptor, self).__init__(connection_info, **kwargs)

    def attach_volume(self, context):
        pass

    def detach_volume(self):
        pass
