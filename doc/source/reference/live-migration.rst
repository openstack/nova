..
      Licensed under the Apache License, Version 2.0 (the "License"); you may
      not use this file except in compliance with the License. You may obtain
      a copy of the License at

          http://www.apache.org/licenses/LICENSE-2.0

      Unless required by applicable law or agreed to in writing, software
      distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
      WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
      License for the specific language governing permissions and limitations
      under the License.

================
 Live Migration
================

.. seqdiag::

    seqdiag {
        Conductor; Source; Destination;
        edge_length = 300;
        span_height = 15;
        activation = none;
        default_note_color = white;

        Conductor            ->  Destination [label = "call", note = "check_can_live_migrate_destination"];
                      Source <-  Destination [label = "call", leftnote = "check_can_live_migrate_source"];
                      Source --> Destination;
        Conductor            <-- Destination;

        Conductor ->> Source [label = "cast", note = "live_migrate"];
                      Source ->  Destination [label = "call", note = "pre_live_migration (set up dest)"];
                      Source <-- Destination;

        === driver.live_migration (success) ===

                      Source ->  Source [leftnote = "post_live_migration (clean up source)"];
                      Source ->  Destination [label = "call", note = "post_live_migration_at_destination (finish dest)"];
                      Source <-- Destination;

        === driver.live_migration (failure) ===

                      Source ->  Source [leftnote = "_rollback_live_migration"];
                      Source ->  Destination [label = "call", note = "remove_volume_connections"];
                      Source <-- Destination;
                      Source ->> Destination [label = "cast", note = "rollback_live_migration_at_destination"];
    }
