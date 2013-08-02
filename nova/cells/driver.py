# Copyright (c) 2012 Rackspace Hosting
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
Base Cells Communication Driver
"""


class BaseCellsDriver(object):
    """The base class for cells communication.

    One instance of this class will be created for every neighbor cell
    that we find in the DB and it will be associated with the cell in
    its CellState.

    One instance is also created by the cells manager for setting up
    the consumers.
    """
    def start_servers(self, msg_runner):
        """Start any messaging servers the driver may need."""
        raise NotImplementedError()

    def stop_servers(self):
        """Stop accepting messages."""
        raise NotImplementedError()

    def send_message_to_cell(self, cell_state, message):
        """Send a message to a cell."""
        raise NotImplementedError()
