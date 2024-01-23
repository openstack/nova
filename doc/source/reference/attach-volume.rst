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

=================
Attaching Volumes
=================

The following sequence diagram outlines the current flow when attaching a
volume to an instance using the ``os-volume_attachments`` API. This diagram
uses the ``libvirt`` driver as an example virt driver to additionally document
the optional interactions with the ``os-brick`` library on the compute hosts
during the request.

.. note:: ``os-brick`` is not always used to connect volumes to the host, most
           notably when connecting an instance natively to ceph ``rbd`` volumes

The diagram also outlines the various locks taken on the compute during the
attach volume flow. In this example these include locks against the
``instance.uuid``, ``cinder_backend.uuid`` orchestrated for ``nova-compute`` by
``os-brick`` and the generic ``connect_volume`` lock taken within os-brick
itself. This final ``connect_volume`` lock also being held when detaching and
disconnecting a volume from the host by ``os-brick``.

.. image:: /_static/images/attach_volume.svg
   :alt: Attach volume workflow