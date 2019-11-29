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

from oslo_utils import units

from nova.objects.fields import Architecture
from nova.virt.libvirt import config


def fake_kvm_guest():
    obj = config.LibvirtConfigGuest()
    obj.virt_type = "kvm"
    obj.memory = 100 * units.Mi
    obj.vcpus = 2
    obj.cpuset = set([0, 1, 3, 4, 5])

    obj.cputune = config.LibvirtConfigGuestCPUTune()
    obj.cputune.shares = 100
    obj.cputune.quota = 50000
    obj.cputune.period = 25000

    obj.membacking = config.LibvirtConfigGuestMemoryBacking()
    page1 = config.LibvirtConfigGuestMemoryBackingPage()
    page1.size_kb = 2048
    page1.nodeset = [0, 1, 2, 3, 5]
    page2 = config.LibvirtConfigGuestMemoryBackingPage()
    page2.size_kb = 1048576
    page2.nodeset = [4]
    obj.membacking.hugepages.append(page1)
    obj.membacking.hugepages.append(page2)

    obj.memtune = config.LibvirtConfigGuestMemoryTune()
    obj.memtune.hard_limit = 496
    obj.memtune.soft_limit = 672
    obj.memtune.swap_hard_limit = 1638
    obj.memtune.min_guarantee = 2970

    obj.numatune = config.LibvirtConfigGuestNUMATune()

    numamemory = config.LibvirtConfigGuestNUMATuneMemory()
    numamemory.mode = "preferred"
    numamemory.nodeset = [0, 1, 2, 3, 8]

    obj.numatune.memory = numamemory

    numamemnode0 = config.LibvirtConfigGuestNUMATuneMemNode()
    numamemnode0.cellid = 0
    numamemnode0.mode = "preferred"
    numamemnode0.nodeset = [0, 1]

    numamemnode1 = config.LibvirtConfigGuestNUMATuneMemNode()
    numamemnode1.cellid = 1
    numamemnode1.mode = "preferred"
    numamemnode1.nodeset = [2, 3]

    numamemnode2 = config.LibvirtConfigGuestNUMATuneMemNode()
    numamemnode2.cellid = 2
    numamemnode2.mode = "preferred"
    numamemnode2.nodeset = [8]

    obj.numatune.memnodes.extend([numamemnode0,
                                  numamemnode1,
                                  numamemnode2])

    obj.name = "demo"
    obj.uuid = "b38a3f43-4be2-4046-897f-b67c2f5e0147"
    obj.os_type = "linux"
    obj.os_boot_dev = ["hd", "cdrom", "fd"]
    obj.os_smbios = config.LibvirtConfigGuestSMBIOS()
    obj.features = [
        config.LibvirtConfigGuestFeatureACPI(),
        config.LibvirtConfigGuestFeatureAPIC(),
        config.LibvirtConfigGuestFeaturePAE(),
        config.LibvirtConfigGuestFeatureKvmHidden()
    ]

    obj.sysinfo = config.LibvirtConfigGuestSysinfo()
    obj.sysinfo.bios_vendor = "Acme"
    obj.sysinfo.system_version = "1.0.0"

    # obj.devices[0]
    disk = config.LibvirtConfigGuestDisk()
    disk.source_type = "file"
    disk.source_path = "/tmp/disk-img"
    disk.target_dev = "vda"
    disk.target_bus = "virtio"
    obj.add_device(disk)

    # obj.devices[1]
    disk = config.LibvirtConfigGuestDisk()
    disk.source_device = "cdrom"
    disk.source_type = "file"
    disk.source_path = "/tmp/cdrom-img"
    disk.target_dev = "sda"
    disk.target_bus = "sata"
    obj.add_device(disk)

    # obj.devices[2]
    intf = config.LibvirtConfigGuestInterface()
    intf.net_type = "network"
    intf.mac_addr = "52:54:00:f6:35:8f"
    intf.model = "virtio"
    intf.source_dev = "virbr0"
    obj.add_device(intf)

    # obj.devices[3]
    balloon = config.LibvirtConfigMemoryBalloon()
    balloon.model = 'virtio'
    balloon.period = 11
    obj.add_device(balloon)

    # obj.devices[4]
    mouse = config.LibvirtConfigGuestInput()
    mouse.type = "mouse"
    mouse.bus = "virtio"
    obj.add_device(mouse)

    # obj.devices[5]
    gfx = config.LibvirtConfigGuestGraphics()
    gfx.type = "vnc"
    gfx.autoport = True
    gfx.keymap = "en_US"
    gfx.listen = "127.0.0.1"
    obj.add_device(gfx)

    # obj.devices[6]
    video = config.LibvirtConfigGuestVideo()
    video.type = 'virtio'
    obj.add_device(video)

    # obj.devices[7]
    serial = config.LibvirtConfigGuestSerial()
    serial.type = "file"
    serial.source_path = "/tmp/vm.log"
    obj.add_device(serial)

    # obj.devices[8]
    rng = config.LibvirtConfigGuestRng()
    rng.backend = '/dev/urandom'
    rng.rate_period = '12'
    rng.rate_bytes = '34'
    obj.add_device(rng)

    # obj.devices[9]
    controller = config.LibvirtConfigGuestController()
    controller.type = 'scsi'
    controller.model = 'virtio-scsi'  # usually set from image meta
    controller.index = 0
    obj.add_device(controller)

    return obj


FAKE_KVM_GUEST = """
  <domain type="kvm">
    <uuid>b38a3f43-4be2-4046-897f-b67c2f5e0147</uuid>
    <name>demo</name>
    <memory>104857600</memory>
    <memoryBacking>
      <hugepages>
        <page size="2048" unit="KiB" nodeset="0-3,5"/>
        <page size="1048576" unit="KiB" nodeset="4"/>
      </hugepages>
    </memoryBacking>
    <memtune>
      <hard_limit unit="KiB">496</hard_limit>
      <soft_limit unit="KiB">672</soft_limit>
      <swap_hard_limit unit="KiB">1638</swap_hard_limit>
      <min_guarantee unit="KiB">2970</min_guarantee>
    </memtune>
    <numatune>
      <memory mode="preferred" nodeset="0-3,8"/>
      <memnode cellid="0" mode="preferred" nodeset="0-1"/>
      <memnode cellid="1" mode="preferred" nodeset="2-3"/>
      <memnode cellid="2" mode="preferred" nodeset="8"/>
    </numatune>
    <vcpu cpuset="0-1,3-5">2</vcpu>
    <sysinfo type='smbios'>
       <bios>
         <entry name="vendor">Acme</entry>
       </bios>
       <system>
         <entry name="version">1.0.0</entry>
       </system>
    </sysinfo>
    <os>
      <type>linux</type>
      <boot dev="hd"/>
      <boot dev="cdrom"/>
      <boot dev="fd"/>
      <smbios mode="sysinfo"/>
    </os>
    <features>
      <acpi/>
      <apic/>
      <pae/>
      <kvm>
        <hidden state='on'/>
      </kvm>
    </features>
    <cputune>
      <shares>100</shares>
      <quota>50000</quota>
      <period>25000</period>
    </cputune>
    <devices>
      <disk type="file" device="disk">
        <source file="/tmp/disk-img"/>
        <target bus="virtio" dev="vda"/>
      </disk>
      <disk type="file" device="cdrom">
        <source file="/tmp/cdrom-img"/>
        <target bus="sata" dev="sda"/>
      </disk>
      <interface type='network'>
        <mac address='52:54:00:f6:35:8f'/>
        <model type='virtio'/>
        <source bridge='virbr0'/>
      </interface>
      <memballoon model='virtio'>
        <stats period='11'/>
      </memballoon>
      <input type="mouse" bus="virtio"/>
      <graphics type="vnc" autoport="yes" keymap="en_US" listen="127.0.0.1"/>
      <video>
        <model type='virtio'/>
      </video>
      <serial type="file">
        <source path="/tmp/vm.log"/>
      </serial>
      <rng model='virtio'>
          <rate period='12' bytes='34'/>
          <backend model='random'>/dev/urandom</backend>
      </rng>
      <controller type='scsi' index='0' model='virtio-scsi'>
      </controller>
    </devices>
    <launchSecurity type="sev">
      <policy>0x0033</policy>
      <cbitpos>47</cbitpos>
      <reducedPhysBits>1</reducedPhysBits>
    </launchSecurity>
  </domain>"""


CAPABILITIES_HOST_TEMPLATE = '''
  <host>
    <uuid>cef19ce0-0ca2-11df-855d-b19fbce37686</uuid>
    <cpu>
      <arch>x86_64</arch>
      <model>Penryn</model>
      <vendor>Intel</vendor>
      <topology sockets='%(sockets)s' cores='%(cores)s' threads='%(threads)s'/>
      <feature name='xtpr'/>
      <feature name='tm2'/>
      <feature name='est'/>
      <feature name='vmx'/>
      <feature name='ds_cpl'/>
      <feature name='monitor'/>
      <feature name='pbe'/>
      <feature name='tm'/>
      <feature name='ht'/>
      <feature name='ss'/>
      <feature name='acpi'/>
      <feature name='ds'/>
      <feature name='vme'/>
    </cpu>
    <migration_features>
      <live/>
      <uri_transports>
        <uri_transport>tcp</uri_transport>
      </uri_transports>
    </migration_features>
    %(topology)s
    <secmodel>
      <model>apparmor</model>
      <doi>0</doi>
    </secmodel>
  </host>'''

# NOTE(aspiers): HostTestCase has tests which assert that for any
# given (arch, domain) listed in the guest capabilities here, all
# canonical machine types (e.g. 'pc' or 'q35') must be a substring of
# the expanded machine type returned in the <machine> element of the
# corresponding fake getDomainCapabilities response for that (arch,
# domain, canonical_machine_type) combination.  Those responses are
# defined by the DOMCAPABILITIES_* variables below.  While
# DOMCAPABILITIES_X86_64_TEMPLATE can return multiple values for the
# <machine> element, DOMCAPABILITIES_I686 is fixed to fake a response
# of the 'pc-i440fx-2.11' machine type, therefore
# CAPABILITIES_GUEST['i686'] should return 'pc' as the only canonical
# machine type.
#
# CAPABILITIES_GUEST does not include canonical machine types for
# other non-x86 architectures, so these test assertions on apply to
# x86.
CAPABILITIES_GUEST = {
    'i686': '''
        <guest>
           <os_type>hvm</os_type>
           <arch name='i686'>
             <wordsize>32</wordsize>
             <emulator>/usr/bin/qemu-system-i386</emulator>
             <machine maxCpus='255'>pc-i440fx-2.11</machine>
             <machine canonical='pc-i440fx-2.11' maxCpus='255'>pc</machine>
             <machine maxCpus='1'>isapc</machine>
             <machine maxCpus='255'>pc-1.1</machine>
             <machine maxCpus='255'>pc-1.2</machine>
             <machine maxCpus='255'>pc-1.3</machine>
             <machine maxCpus='255'>pc-i440fx-2.8</machine>
             <machine maxCpus='255'>pc-1.0</machine>
             <machine maxCpus='255'>pc-i440fx-2.9</machine>
             <machine maxCpus='255'>pc-i440fx-2.6</machine>
             <machine maxCpus='255'>pc-i440fx-2.7</machine>
             <machine maxCpus='128'>xenfv</machine>
             <machine maxCpus='255'>pc-i440fx-2.3</machine>
             <machine maxCpus='255'>pc-i440fx-2.4</machine>
             <machine maxCpus='255'>pc-i440fx-2.5</machine>
             <machine maxCpus='255'>pc-i440fx-2.1</machine>
             <machine maxCpus='255'>pc-i440fx-2.2</machine>
             <machine maxCpus='255'>pc-i440fx-2.0</machine>
             <machine maxCpus='288'>pc-q35-2.11</machine>
             <machine maxCpus='288'>q35</machine>
             <machine maxCpus='1'>xenpv</machine>
             <machine maxCpus='288'>pc-q35-2.10</machine>
             <machine maxCpus='255'>pc-i440fx-1.7</machine>
             <machine maxCpus='288'>pc-q35-2.9</machine>
             <machine maxCpus='255'>pc-0.15</machine>
             <machine maxCpus='255'>pc-i440fx-1.5</machine>
             <machine maxCpus='255'>pc-q35-2.7</machine>
             <machine maxCpus='255'>pc-i440fx-1.6</machine>
             <machine maxCpus='288'>pc-q35-2.8</machine>
             <machine maxCpus='255'>pc-0.13</machine>
             <machine maxCpus='255'>pc-0.14</machine>
             <machine maxCpus='255'>pc-q35-2.4</machine>
             <machine maxCpus='255'>pc-q35-2.5</machine>
             <machine maxCpus='255'>pc-q35-2.6</machine>
             <machine maxCpus='255'>pc-i440fx-1.4</machine>
             <machine maxCpus='255'>pc-i440fx-2.10</machine>
             <machine maxCpus='255'>pc-0.11</machine>
             <machine maxCpus='255'>pc-0.12</machine>
             <machine maxCpus='255'>pc-0.10</machine>
             <domain type='qemu'/>
             <domain type='kvm'>
               <emulator>/usr/bin/qemu-kvm</emulator>
               <machine maxCpus='255'>pc-i440fx-2.11</machine>
               <machine canonical='pc-i440fx-2.11' maxCpus='255'>pc</machine>
               <machine maxCpus='1'>isapc</machine>
               <machine maxCpus='255'>pc-1.1</machine>
               <machine maxCpus='255'>pc-1.2</machine>
               <machine maxCpus='255'>pc-1.3</machine>
               <machine maxCpus='255'>pc-i440fx-2.8</machine>
               <machine maxCpus='255'>pc-1.0</machine>
               <machine maxCpus='255'>pc-i440fx-2.9</machine>
               <machine maxCpus='255'>pc-i440fx-2.6</machine>
               <machine maxCpus='255'>pc-i440fx-2.7</machine>
               <machine maxCpus='128'>xenfv</machine>
               <machine maxCpus='255'>pc-i440fx-2.3</machine>
               <machine maxCpus='255'>pc-i440fx-2.4</machine>
               <machine maxCpus='255'>pc-i440fx-2.5</machine>
               <machine maxCpus='255'>pc-i440fx-2.1</machine>
               <machine maxCpus='255'>pc-i440fx-2.2</machine>
               <machine maxCpus='255'>pc-i440fx-2.0</machine>
               <machine maxCpus='288'>pc-q35-2.11</machine>
               <machine maxCpus='288'>q35</machine>
               <machine maxCpus='1'>xenpv</machine>
               <machine maxCpus='288'>pc-q35-2.10</machine>
               <machine maxCpus='255'>pc-i440fx-1.7</machine>
               <machine maxCpus='288'>pc-q35-2.9</machine>
               <machine maxCpus='255'>pc-0.15</machine>
               <machine maxCpus='255'>pc-i440fx-1.5</machine>
               <machine maxCpus='255'>pc-q35-2.7</machine>
               <machine maxCpus='255'>pc-i440fx-1.6</machine>
               <machine maxCpus='288'>pc-q35-2.8</machine>
               <machine maxCpus='255'>pc-0.13</machine>
               <machine maxCpus='255'>pc-0.14</machine>
               <machine maxCpus='255'>pc-q35-2.4</machine>
               <machine maxCpus='255'>pc-q35-2.5</machine>
               <machine maxCpus='255'>pc-q35-2.6</machine>
               <machine maxCpus='255'>pc-i440fx-1.4</machine>
               <machine maxCpus='255'>pc-i440fx-2.10</machine>
               <machine maxCpus='255'>pc-0.11</machine>
               <machine maxCpus='255'>pc-0.12</machine>
               <machine maxCpus='255'>pc-0.10</machine>
             </domain>
           </arch>
           <features>
             <cpuselection/>
             <deviceboot/>
             <disksnapshot default='on' toggle='no'/>
             <acpi default='on' toggle='yes'/>
             <apic default='on' toggle='no'/>
             <pae/>
             <nonpae/>
           </features>
         </guest>''',

    'x86_64': '''
        <guest>
          <os_type>hvm</os_type>
          <arch name='x86_64'>
            <wordsize>64</wordsize>
            <emulator>/usr/bin/qemu-system-x86_64</emulator>
            <machine maxCpus='255'>pc-i440fx-2.11</machine>
            <machine canonical='pc-i440fx-2.11' maxCpus='255'>pc</machine>
            <machine maxCpus='1'>isapc</machine>
            <machine maxCpus='255'>pc-1.1</machine>
            <machine maxCpus='255'>pc-1.2</machine>
            <machine maxCpus='255'>pc-1.3</machine>
            <machine maxCpus='255'>pc-i440fx-2.8</machine>
            <machine maxCpus='255'>pc-1.0</machine>
            <machine maxCpus='255'>pc-i440fx-2.9</machine>
            <machine maxCpus='255'>pc-i440fx-2.6</machine>
            <machine maxCpus='255'>pc-i440fx-2.7</machine>
            <machine maxCpus='128'>xenfv</machine>
            <machine maxCpus='255'>pc-i440fx-2.3</machine>
            <machine maxCpus='255'>pc-i440fx-2.4</machine>
            <machine maxCpus='255'>pc-i440fx-2.5</machine>
            <machine maxCpus='255'>pc-i440fx-2.1</machine>
            <machine maxCpus='255'>pc-i440fx-2.2</machine>
            <machine maxCpus='255'>pc-i440fx-2.0</machine>
            <machine maxCpus='288'>pc-q35-2.11</machine>
            <machine canonical='pc-q35-2.11' maxCpus='288'>q35</machine>
            <machine maxCpus='1'>xenpv</machine>
            <machine maxCpus='288'>pc-q35-2.10</machine>
            <machine maxCpus='255'>pc-i440fx-1.7</machine>
            <machine maxCpus='288'>pc-q35-2.9</machine>
            <machine maxCpus='255'>pc-0.15</machine>
            <machine maxCpus='255'>pc-i440fx-1.5</machine>
            <machine maxCpus='255'>pc-q35-2.7</machine>
            <machine maxCpus='255'>pc-i440fx-1.6</machine>
            <machine maxCpus='288'>pc-q35-2.8</machine>
            <machine maxCpus='255'>pc-0.13</machine>
            <machine maxCpus='255'>pc-0.14</machine>
            <machine maxCpus='255'>pc-q35-2.4</machine>
            <machine maxCpus='255'>pc-q35-2.5</machine>
            <machine maxCpus='255'>pc-q35-2.6</machine>
            <machine maxCpus='255'>pc-i440fx-1.4</machine>
            <machine maxCpus='255'>pc-i440fx-2.10</machine>
            <machine maxCpus='255'>pc-0.11</machine>
            <machine maxCpus='255'>pc-0.12</machine>
            <machine maxCpus='255'>pc-0.10</machine>
            <domain type='qemu'/>
            <domain type='kvm'>
              <emulator>/usr/bin/qemu-kvm</emulator>
              <machine maxCpus='255'>pc-i440fx-2.11</machine>
              <machine canonical='pc-i440fx-2.11' maxCpus='255'>pc</machine>
              <machine maxCpus='1'>isapc</machine>
              <machine maxCpus='255'>pc-1.1</machine>
              <machine maxCpus='255'>pc-1.2</machine>
              <machine maxCpus='255'>pc-1.3</machine>
              <machine maxCpus='255'>pc-i440fx-2.8</machine>
              <machine maxCpus='255'>pc-1.0</machine>
              <machine maxCpus='255'>pc-i440fx-2.9</machine>
              <machine maxCpus='255'>pc-i440fx-2.6</machine>
              <machine maxCpus='255'>pc-i440fx-2.7</machine>
              <machine maxCpus='128'>xenfv</machine>
              <machine maxCpus='255'>pc-i440fx-2.3</machine>
              <machine maxCpus='255'>pc-i440fx-2.4</machine>
              <machine maxCpus='255'>pc-i440fx-2.5</machine>
              <machine maxCpus='255'>pc-i440fx-2.1</machine>
              <machine maxCpus='255'>pc-i440fx-2.2</machine>
              <machine maxCpus='255'>pc-i440fx-2.0</machine>
              <machine maxCpus='288'>pc-q35-2.11</machine>
              <machine canonical='pc-q35-2.11' maxCpus='288'>q35</machine>
              <machine maxCpus='1'>xenpv</machine>
              <machine maxCpus='288'>pc-q35-2.10</machine>
              <machine maxCpus='255'>pc-i440fx-1.7</machine>
              <machine maxCpus='288'>pc-q35-2.9</machine>
              <machine maxCpus='255'>pc-0.15</machine>
              <machine maxCpus='255'>pc-i440fx-1.5</machine>
              <machine maxCpus='255'>pc-q35-2.7</machine>
              <machine maxCpus='255'>pc-i440fx-1.6</machine>
              <machine maxCpus='288'>pc-q35-2.8</machine>
              <machine maxCpus='255'>pc-0.13</machine>
              <machine maxCpus='255'>pc-0.14</machine>
              <machine maxCpus='255'>pc-q35-2.4</machine>
              <machine maxCpus='255'>pc-q35-2.5</machine>
              <machine maxCpus='255'>pc-q35-2.6</machine>
              <machine maxCpus='255'>pc-i440fx-1.4</machine>
              <machine maxCpus='255'>pc-i440fx-2.10</machine>
              <machine maxCpus='255'>pc-0.11</machine>
              <machine maxCpus='255'>pc-0.12</machine>
              <machine maxCpus='255'>pc-0.10</machine>
            </domain>
          </arch>
          <features>
            <cpuselection/>
            <deviceboot/>
            <disksnapshot default='on' toggle='no'/>
            <acpi default='on' toggle='yes'/>
            <apic default='on' toggle='no'/>
          </features>
        </guest>''',

    'armv7l': '''
        <guest>
          <os_type>hvm</os_type>
          <arch name='armv7l'>
            <wordsize>32</wordsize>
            <emulator>/usr/bin/qemu-system-arm</emulator>
            <machine>integratorcp</machine>
            <machine>vexpress-a9</machine>
            <machine>syborg</machine>
            <machine>musicpal</machine>
            <machine>mainstone</machine>
            <machine>n800</machine>
            <machine>n810</machine>
            <machine>n900</machine>
            <machine>cheetah</machine>
            <machine>sx1</machine>
            <machine>sx1-v1</machine>
            <machine>beagle</machine>
            <machine>beaglexm</machine>
            <machine>tosa</machine>
            <machine>akita</machine>
            <machine>spitz</machine>
            <machine>borzoi</machine>
            <machine>terrier</machine>
            <machine>connex</machine>
            <machine>verdex</machine>
            <machine>lm3s811evb</machine>
            <machine>lm3s6965evb</machine>
            <machine>realview-eb</machine>
            <machine>realview-eb-mpcore</machine>
            <machine>realview-pb-a8</machine>
            <machine>realview-pbx-a9</machine>
            <machine>versatilepb</machine>
            <machine>versatileab</machine>
            <domain type='qemu'>
            </domain>
          </arch>
          <features>
            <deviceboot/>
          </features>
        </guest>''',

    'mips': '''
        <guest>
          <os_type>hvm</os_type>
          <arch name='mips'>
            <wordsize>32</wordsize>
            <emulator>/usr/bin/qemu-system-mips</emulator>
            <machine>malta</machine>
            <machine>mipssim</machine>
            <machine>magnum</machine>
            <machine>pica61</machine>
            <machine>mips</machine>
            <domain type='qemu'>
            </domain>
          </arch>
          <features>
            <deviceboot/>
          </features>
        </guest>''',

    'mipsel': '''
        <guest>
          <os_type>hvm</os_type>
          <arch name='mipsel'>
            <wordsize>32</wordsize>
            <emulator>/usr/bin/qemu-system-mipsel</emulator>
            <machine>malta</machine>
            <machine>mipssim</machine>
            <machine>magnum</machine>
            <machine>pica61</machine>
            <machine>mips</machine>
            <domain type='qemu'>
            </domain>
          </arch>
          <features>
            <deviceboot/>
          </features>
        </guest>''',

    'sparc': '''
        <guest>
          <os_type>hvm</os_type>
          <arch name='sparc'>
            <wordsize>32</wordsize>
            <emulator>/usr/bin/qemu-system-sparc</emulator>
            <machine>SS-5</machine>
            <machine>leon3_generic</machine>
            <machine>SS-10</machine>
            <machine>SS-600MP</machine>
            <machine>SS-20</machine>
            <machine>Voyager</machine>
            <machine>LX</machine>
            <machine>SS-4</machine>
            <machine>SPARCClassic</machine>
            <machine>SPARCbook</machine>
            <machine>SS-1000</machine>
            <machine>SS-2000</machine>
            <machine>SS-2</machine>
            <domain type='qemu'>
            </domain>
          </arch>
        </guest>''',

    'ppc': '''
        <guest>
          <os_type>hvm</os_type>
          <arch name='ppc'>
            <wordsize>32</wordsize>
            <emulator>/usr/bin/qemu-system-ppc</emulator>
            <machine>g3beige</machine>
            <machine>virtex-ml507</machine>
            <machine>mpc8544ds</machine>
            <machine>bamboo-0.13</machine>
            <machine>bamboo-0.12</machine>
            <machine>ref405ep</machine>
            <machine>taihu</machine>
            <machine>mac99</machine>
            <machine>prep</machine>
            <domain type='qemu'>
            </domain>
          </arch>
          <features>
            <deviceboot/>
          </features>
        </guest>'''
}

CAPABILITIES_TEMPLATE = (
    "<capabilities>\n" +
    CAPABILITIES_HOST_TEMPLATE +
    CAPABILITIES_GUEST['i686'] +
    CAPABILITIES_GUEST['x86_64'] +
    CAPABILITIES_GUEST['armv7l'] +
    CAPABILITIES_GUEST['mips'] +
    CAPABILITIES_GUEST['mipsel'] +
    CAPABILITIES_GUEST['sparc'] +
    CAPABILITIES_GUEST['ppc'] +
    "</capabilities>\n"
)


DOMCAPABILITIES_SPARC = """
<domainCapabilities>
  <path>/usr/bin/qemu-system-sparc</path>
  <domain>qemu</domain>
  <machine>SS-5</machine>
  <arch>sparc</arch>
  <vcpu max='1'/>
  <os supported='yes'>
    <loader supported='yes'>
      <enum name='type'>
        <value>rom</value>
        <value>pflash</value>
      </enum>
      <enum name='readonly'>
        <value>yes</value>
        <value>no</value>
      </enum>
    </loader>
  </os>
  <cpu>
    <mode name='host-passthrough' supported='no'/>
    <mode name='host-model' supported='no'/>
    <mode name='custom' supported='no'/>
  </cpu>
  <devices>
    <disk supported='yes'>
      <enum name='diskDevice'>
        <value>disk</value>
        <value>cdrom</value>
        <value>floppy</value>
        <value>lun</value>
      </enum>
      <enum name='bus'>
        <value>fdc</value>
        <value>scsi</value>
        <value>virtio</value>
      </enum>
    </disk>
    <graphics supported='yes'>
      <enum name='type'>
        <value>sdl</value>
        <value>vnc</value>
        <value>spice</value>
      </enum>
    </graphics>
    <video supported='yes'>
      <enum name='modelType'/>
    </video>
    <hostdev supported='yes'>
      <enum name='mode'>
        <value>subsystem</value>
      </enum>
      <enum name='startupPolicy'>
        <value>default</value>
        <value>mandatory</value>
        <value>requisite</value>
        <value>optional</value>
      </enum>
      <enum name='subsysType'>
        <value>usb</value>
        <value>pci</value>
        <value>scsi</value>
      </enum>
      <enum name='capsType'/>
      <enum name='pciBackend'/>
    </hostdev>
  </devices>
  <features>
    <gic supported='no'/>
  </features>
</domainCapabilities>
"""

DOMCAPABILITIES_ARMV7L = """
<domainCapabilities>
  <path>/usr/bin/qemu-system-arm</path>
  <domain>qemu</domain>
  <machine>virt-2.11</machine>
  <arch>armv7l</arch>
  <vcpu max='255'/>
  <os supported='yes'>
    <loader supported='yes'>
      <enum name='type'>
        <value>rom</value>
        <value>pflash</value>
      </enum>
      <enum name='readonly'>
        <value>yes</value>
        <value>no</value>
      </enum>
    </loader>
  </os>
  <cpu>
    <mode name='host-passthrough' supported='no'/>
    <mode name='host-model' supported='no'/>
    <mode name='custom' supported='yes'>
      <model usable='unknown'>pxa262</model>
      <model usable='unknown'>pxa270-a0</model>
      <model usable='unknown'>arm1136</model>
      <model usable='unknown'>cortex-a15</model>
      <model usable='unknown'>pxa260</model>
      <model usable='unknown'>arm1136-r2</model>
      <model usable='unknown'>pxa261</model>
      <model usable='unknown'>pxa255</model>
      <model usable='unknown'>arm926</model>
      <model usable='unknown'>arm11mpcore</model>
      <model usable='unknown'>pxa250</model>
      <model usable='unknown'>ti925t</model>
      <model usable='unknown'>sa1110</model>
      <model usable='unknown'>arm1176</model>
      <model usable='unknown'>sa1100</model>
      <model usable='unknown'>pxa270-c5</model>
      <model usable='unknown'>cortex-a9</model>
      <model usable='unknown'>cortex-a8</model>
      <model usable='unknown'>pxa270-c0</model>
      <model usable='unknown'>cortex-a7</model>
      <model usable='unknown'>arm1026</model>
      <model usable='unknown'>pxa270-b1</model>
      <model usable='unknown'>cortex-m3</model>
      <model usable='unknown'>cortex-m4</model>
      <model usable='unknown'>pxa270-b0</model>
      <model usable='unknown'>arm946</model>
      <model usable='unknown'>cortex-r5</model>
      <model usable='unknown'>pxa270-a1</model>
      <model usable='unknown'>pxa270</model>
    </mode>
  </cpu>
  <devices>
    <disk supported='yes'>
      <enum name='diskDevice'>
        <value>disk</value>
        <value>cdrom</value>
        <value>floppy</value>
        <value>lun</value>
      </enum>
      <enum name='bus'>
        <value>fdc</value>
        <value>scsi</value>
        <value>virtio</value>
        <value>usb</value>
        <value>sata</value>
      </enum>
    </disk>
    <graphics supported='yes'>
      <enum name='type'>
        <value>sdl</value>
        <value>vnc</value>
        <value>spice</value>
      </enum>
    </graphics>
    <video supported='yes'>
      <enum name='modelType'>
        <value>vga</value>
        <value>virtio</value>
      </enum>
    </video>
    <hostdev supported='yes'>
      <enum name='mode'>
        <value>subsystem</value>
      </enum>
      <enum name='startupPolicy'>
        <value>default</value>
        <value>mandatory</value>
        <value>requisite</value>
        <value>optional</value>
      </enum>
      <enum name='subsysType'>
        <value>usb</value>
        <value>pci</value>
        <value>scsi</value>
      </enum>
      <enum name='capsType'/>
      <enum name='pciBackend'/>
    </hostdev>
  </devices>
  <features>
    <gic supported='yes'>
      <enum name='version'>
        <value>2</value>
        <value>3</value>
      </enum>
    </gic>
  </features>
</domainCapabilities>
"""

DOMCAPABILITIES_PPC = """
<domainCapabilities>
  <path>/usr/bin/qemu-system-ppc</path>
  <domain>qemu</domain>
  <machine>g3beige</machine>
  <arch>ppc</arch>
  <vcpu max='1'/>
  <os supported='yes'>
    <loader supported='yes'>
      <enum name='type'>
        <value>rom</value>
        <value>pflash</value>
      </enum>
      <enum name='readonly'>
        <value>yes</value>
        <value>no</value>
      </enum>
    </loader>
  </os>
  <cpu>
    <mode name='host-passthrough' supported='no'/>
    <mode name='host-model' supported='no'/>
    <mode name='custom' supported='no'/>
  </cpu>
  <devices>
    <disk supported='yes'>
      <enum name='diskDevice'>
        <value>disk</value>
        <value>cdrom</value>
        <value>floppy</value>
        <value>lun</value>
      </enum>
      <enum name='bus'>
        <value>ide</value>
        <value>fdc</value>
        <value>scsi</value>
        <value>virtio</value>
        <value>usb</value>
        <value>sata</value>
      </enum>
    </disk>
    <graphics supported='yes'>
      <enum name='type'>
        <value>sdl</value>
        <value>vnc</value>
        <value>spice</value>
      </enum>
    </graphics>
    <video supported='yes'>
      <enum name='modelType'>
        <value>vga</value>
        <value>virtio</value>
      </enum>
    </video>
    <hostdev supported='yes'>
      <enum name='mode'>
        <value>subsystem</value>
      </enum>
      <enum name='startupPolicy'>
        <value>default</value>
        <value>mandatory</value>
        <value>requisite</value>
        <value>optional</value>
      </enum>
      <enum name='subsysType'>
        <value>usb</value>
        <value>pci</value>
        <value>scsi</value>
      </enum>
      <enum name='capsType'/>
      <enum name='pciBackend'/>
    </hostdev>
  </devices>
  <features>
    <gic supported='no'/>
  </features>
</domainCapabilities>
"""

DOMCAPABILITIES_MIPS = """
<domainCapabilities>
  <path>/usr/bin/qemu-system-mips</path>
  <domain>qemu</domain>
  <machine>malta</machine>
  <arch>mips</arch>
  <vcpu max='16'/>
  <os supported='yes'>
    <loader supported='yes'>
      <enum name='type'>
        <value>rom</value>
        <value>pflash</value>
      </enum>
      <enum name='readonly'>
        <value>yes</value>
        <value>no</value>
      </enum>
    </loader>
  </os>
  <cpu>
    <mode name='host-passthrough' supported='no'/>
    <mode name='host-model' supported='no'/>
    <mode name='custom' supported='no'/>
  </cpu>
  <devices>
    <disk supported='yes'>
      <enum name='diskDevice'>
        <value>disk</value>
        <value>cdrom</value>
        <value>floppy</value>
        <value>lun</value>
      </enum>
      <enum name='bus'>
        <value>ide</value>
        <value>fdc</value>
        <value>scsi</value>
        <value>virtio</value>
        <value>usb</value>
        <value>sata</value>
      </enum>
    </disk>
    <graphics supported='yes'>
      <enum name='type'>
        <value>sdl</value>
        <value>vnc</value>
        <value>spice</value>
      </enum>
    </graphics>
    <video supported='yes'>
      <enum name='modelType'>
        <value>vga</value>
        <value>cirrus</value>
        <value>vmvga</value>
        <value>virtio</value>
      </enum>
    </video>
    <hostdev supported='yes'>
      <enum name='mode'>
        <value>subsystem</value>
      </enum>
      <enum name='startupPolicy'>
        <value>default</value>
        <value>mandatory</value>
        <value>requisite</value>
        <value>optional</value>
      </enum>
      <enum name='subsysType'>
        <value>usb</value>
        <value>pci</value>
        <value>scsi</value>
      </enum>
      <enum name='capsType'/>
      <enum name='pciBackend'/>
    </hostdev>
  </devices>
  <features>
    <gic supported='no'/>
  </features>
</domainCapabilities>
"""

DOMCAPABILITIES_MIPSEL = """
<domainCapabilities>
  <path>/usr/bin/qemu-system-mipsel</path>
  <domain>qemu</domain>
  <machine>malta</machine>
  <arch>mipsel</arch>
  <vcpu max='16'/>
  <os supported='yes'>
    <loader supported='yes'>
      <enum name='type'>
        <value>rom</value>
        <value>pflash</value>
      </enum>
      <enum name='readonly'>
        <value>yes</value>
        <value>no</value>
      </enum>
    </loader>
  </os>
  <cpu>
    <mode name='host-passthrough' supported='no'/>
    <mode name='host-model' supported='no'/>
    <mode name='custom' supported='no'/>
  </cpu>
  <devices>
    <disk supported='yes'>
      <enum name='diskDevice'>
        <value>disk</value>
        <value>cdrom</value>
        <value>floppy</value>
        <value>lun</value>
      </enum>
      <enum name='bus'>
        <value>ide</value>
        <value>fdc</value>
        <value>scsi</value>
        <value>virtio</value>
        <value>usb</value>
        <value>sata</value>
      </enum>
    </disk>
    <graphics supported='yes'>
      <enum name='type'>
        <value>sdl</value>
        <value>vnc</value>
        <value>spice</value>
      </enum>
    </graphics>
    <video supported='yes'>
      <enum name='modelType'>
        <value>vga</value>
        <value>cirrus</value>
        <value>vmvga</value>
        <value>virtio</value>
      </enum>
    </video>
    <hostdev supported='yes'>
      <enum name='mode'>
        <value>subsystem</value>
      </enum>
      <enum name='startupPolicy'>
        <value>default</value>
        <value>mandatory</value>
        <value>requisite</value>
        <value>optional</value>
      </enum>
      <enum name='subsysType'>
        <value>usb</value>
        <value>pci</value>
        <value>scsi</value>
      </enum>
      <enum name='capsType'/>
      <enum name='pciBackend'/>
    </hostdev>
  </devices>
  <features>
    <gic supported='no'/>
  </features>
</domainCapabilities>
"""

# NOTE(sean-k-mooney): yes i686 is actually the i386 emulator
# the qemu-system-i386 binary is used for all 32bit x86
# instruction sets.
DOMCAPABILITIES_I686 = """
<domainCapabilities>
  <path>/usr/bin/qemu-system-i386</path>
  <domain>kvm</domain>
  <machine>pc-i440fx-2.11</machine>
  <arch>i686</arch>
  <vcpu max='255'/>
  <os supported='yes'>
    <loader supported='yes'>
      <enum name='type'>
        <value>rom</value>
        <value>pflash</value>
      </enum>
      <enum name='readonly'>
        <value>yes</value>
        <value>no</value>
      </enum>
    </loader>
  </os>
  <cpu>
    <mode name='host-passthrough' supported='yes'/>
    <mode name='host-model' supported='yes'>
      <model fallback='forbid'>Skylake-Client-IBRS</model>
      <vendor>Intel</vendor>
      <feature policy='require' name='ss'/>
      <feature policy='require' name='vmx'/>
      <feature policy='require' name='hypervisor'/>
      <feature policy='require' name='tsc_adjust'/>
      <feature policy='require' name='clflushopt'/>
      <feature policy='require' name='md-clear'/>
      <feature policy='require' name='ssbd'/>
      <feature policy='require' name='xsaves'/>
      <feature policy='require' name='pdpe1gb'/>
    </mode>
    <mode name='custom' supported='yes'>
      <model usable='no'>qemu64</model>
      <model usable='yes'>qemu32</model>
      <model usable='no'>phenom</model>
      <model usable='yes'>pentium3</model>
      <model usable='yes'>pentium2</model>
      <model usable='yes'>pentium</model>
      <model usable='yes'>n270</model>
      <model usable='yes'>kvm64</model>
      <model usable='yes'>kvm32</model>
      <model usable='yes'>coreduo</model>
      <model usable='yes'>core2duo</model>
      <model usable='no'>athlon</model>
      <model usable='yes'>Westmere</model>
      <model usable='yes'>Westmere-IBRS</model>
      <model usable='no'>Skylake-Server</model>
      <model usable='no'>Skylake-Server-IBRS</model>
      <model usable='yes'>Skylake-Client</model>
      <model usable='yes'>Skylake-Client-IBRS</model>
      <model usable='yes'>SandyBridge</model>
      <model usable='yes'>SandyBridge-IBRS</model>
      <model usable='yes'>Penryn</model>
      <model usable='no'>Opteron_G5</model>
      <model usable='no'>Opteron_G4</model>
      <model usable='no'>Opteron_G3</model>
      <model usable='no'>Opteron_G2</model>
      <model usable='yes'>Opteron_G1</model>
      <model usable='yes'>Nehalem</model>
      <model usable='yes'>Nehalem-IBRS</model>
      <model usable='yes'>IvyBridge</model>
      <model usable='yes'>IvyBridge-IBRS</model>
      <model usable='yes'>Haswell-noTSX</model>
      <model usable='yes'>Haswell-noTSX-IBRS</model>
      <model usable='yes'>Haswell</model>
      <model usable='yes'>Haswell-IBRS</model>
      <model usable='no'>EPYC</model>
      <model usable='no'>EPYC-IBPB</model>
      <model usable='yes'>Conroe</model>
      <model usable='yes'>Broadwell-noTSX</model>
      <model usable='yes'>Broadwell-noTSX-IBRS</model>
      <model usable='yes'>Broadwell</model>
      <model usable='yes'>Broadwell-IBRS</model>
      <model usable='yes'>486</model>
    </mode>
  </cpu>
  <devices>
    <disk supported='yes'>
      <enum name='diskDevice'>
        <value>disk</value>
        <value>cdrom</value>
        <value>floppy</value>
        <value>lun</value>
      </enum>
      <enum name='bus'>
        <value>ide</value>
        <value>fdc</value>
        <value>scsi</value>
        <value>virtio</value>
        <value>usb</value>
        <value>sata</value>
      </enum>
    </disk>
    <graphics supported='yes'>
      <enum name='type'>
        <value>sdl</value>
        <value>vnc</value>
        <value>spice</value>
      </enum>
    </graphics>
    <video supported='yes'>
      <enum name='modelType'>
        <value>vga</value>
        <value>cirrus</value>
        <value>vmvga</value>
        <value>qxl</value>
        <value>virtio</value>
      </enum>
    </video>
    <hostdev supported='yes'>
      <enum name='mode'>
        <value>subsystem</value>
      </enum>
      <enum name='startupPolicy'>
        <value>default</value>
        <value>mandatory</value>
        <value>requisite</value>
        <value>optional</value>
      </enum>
      <enum name='subsysType'>
        <value>usb</value>
        <value>pci</value>
        <value>scsi</value>
      </enum>
      <enum name='capsType'/>
      <enum name='pciBackend'/>
    </hostdev>
  </devices>
  <features>
    <gic supported='no'/>
  </features>
</domainCapabilities>
"""

STATIC_DOMCAPABILITIES = {
    Architecture.ARMV7: DOMCAPABILITIES_ARMV7L,
    Architecture.SPARC: DOMCAPABILITIES_SPARC,
    Architecture.PPC: DOMCAPABILITIES_PPC,
    Architecture.MIPS: DOMCAPABILITIES_MIPS,
    Architecture.MIPSEL: DOMCAPABILITIES_MIPSEL,
    Architecture.I686: DOMCAPABILITIES_I686
}

# NOTE(aspiers): see the above note for CAPABILITIES_GUEST which
# explains why the <machine> element here needs to be parametrised.
#
# The <features> element needs to be parametrised for emulating
# environments with and without the SEV feature.
DOMCAPABILITIES_X86_64_TEMPLATE = """
<domainCapabilities>
  <path>/usr/bin/qemu-kvm</path>
  <domain>kvm</domain>
  <machine>%(mtype)s</machine>
  <arch>x86_64</arch>
  <vcpu max='255'/>
  <os supported='yes'>
    <loader supported='yes'>
      <value>/usr/share/qemu/ovmf-x86_64-ms-4m-code.bin</value>
      <value>/usr/share/qemu/ovmf-x86_64-ms-code.bin</value>
      <enum name='type'>
        <value>rom</value>
        <value>pflash</value>
      </enum>
      <enum name='readonly'>
        <value>yes</value>
        <value>no</value>
      </enum>
    </loader>
  </os>
  <cpu>
    <mode name='host-passthrough' supported='yes'/>
    <mode name='host-model' supported='yes'>
      <model fallback='forbid'>EPYC-IBPB</model>
      <vendor>AMD</vendor>
      <feature policy='require' name='x2apic'/>
      <feature policy='require' name='tsc-deadline'/>
      <feature policy='require' name='hypervisor'/>
      <feature policy='require' name='tsc_adjust'/>
      <feature policy='require' name='cmp_legacy'/>
      <feature policy='require' name='invtsc'/>
      <feature policy='require' name='virt-ssbd'/>
      <feature policy='disable' name='monitor'/>
    </mode>
    <mode name='custom' supported='yes'>
      <model usable='yes'>qemu64</model>
      <model usable='yes'>qemu32</model>
      <model usable='no'>phenom</model>
      <model usable='yes'>pentium3</model>
      <model usable='yes'>pentium2</model>
      <model usable='yes'>pentium</model>
      <model usable='no'>n270</model>
      <model usable='yes'>kvm64</model>
      <model usable='yes'>kvm32</model>
      <model usable='no'>coreduo</model>
      <model usable='no'>core2duo</model>
      <model usable='no'>athlon</model>
      <model usable='yes'>Westmere</model>
      <model usable='no'>Westmere-IBRS</model>
      <model usable='no'>Skylake-Server</model>
      <model usable='no'>Skylake-Server-IBRS</model>
      <model usable='no'>Skylake-Client</model>
      <model usable='no'>Skylake-Client-IBRS</model>
      <model usable='yes'>SandyBridge</model>
      <model usable='no'>SandyBridge-IBRS</model>
      <model usable='yes'>Penryn</model>
      <model usable='no'>Opteron_G5</model>
      <model usable='no'>Opteron_G4</model>
      <model usable='yes'>Opteron_G3</model>
      <model usable='yes'>Opteron_G2</model>
      <model usable='yes'>Opteron_G1</model>
      <model usable='yes'>Nehalem</model>
      <model usable='no'>Nehalem-IBRS</model>
      <model usable='no'>IvyBridge</model>
      <model usable='no'>IvyBridge-IBRS</model>
      <model usable='no'>Haswell</model>
      <model usable='no'>Haswell-noTSX</model>
      <model usable='no'>Haswell-noTSX-IBRS</model>
      <model usable='no'>Haswell-IBRS</model>
      <model usable='yes'>EPYC</model>
      <model usable='yes'>EPYC-IBPB</model>
      <model usable='yes'>Conroe</model>
      <model usable='no'>Broadwell</model>
      <model usable='no'>Broadwell-noTSX</model>
      <model usable='no'>Broadwell-noTSX-IBRS</model>
      <model usable='no'>Broadwell-IBRS</model>
      <model usable='yes'>486</model>
    </mode>
  </cpu>
  <devices>
    <disk supported='yes'>
      <enum name='diskDevice'>
        <value>disk</value>
        <value>cdrom</value>
        <value>floppy</value>
        <value>lun</value>
      </enum>
      <enum name='bus'>
        <value>ide</value>
        <value>fdc</value>
        <value>scsi</value>
        <value>virtio</value>
        <value>usb</value>
        <value>sata</value>
      </enum>
    </disk>
    <graphics supported='yes'>
      <enum name='type'>
        <value>sdl</value>
        <value>vnc</value>
        <value>spice</value>
      </enum>
    </graphics>
    <video supported='yes'>
      <enum name='modelType'>
        <value>vga</value>
        <value>cirrus</value>
        <value>vmvga</value>
        <value>qxl</value>
        <value>virtio</value>
      </enum>
    </video>
    <hostdev supported='yes'>
      <enum name='mode'>
        <value>subsystem</value>
      </enum>
      <enum name='startupPolicy'>
        <value>default</value>
        <value>mandatory</value>
        <value>requisite</value>
        <value>optional</value>
      </enum>
      <enum name='subsysType'>
        <value>usb</value>
        <value>pci</value>
        <value>scsi</value>
      </enum>
      <enum name='capsType'/>
      <enum name='pciBackend'>
        <value>default</value>
        <value>vfio</value>
      </enum>
    </hostdev>
  </devices>
%(features)s
</domainCapabilities>
"""
