<?xml version='1.0' encoding='UTF-8'?>
<hypervisors xmlns:os-pci="http://docs.openstack.org/compute/ext/os-pci/api/v3">
  <hypervisor vcpus_used="0" hypervisor_type="fake" local_gb_used="0" hypervisor_hostname="fake-mini" memory_mb_used="512" memory_mb="8192" current_workload="0" vcpus="1" cpu_info="?" running_vms="0" free_disk_gb="1028" hypervisor_version="1" disk_available_least="0" local_gb="1028" free_ram_mb="7680" id="1">
    <service host="043b3cacf6f34c90a7245151fc8ebcda" id="2"/>
    <os-pci:pci_stats xmlns:os-pci="os-pci">
      <os-pci:pci_stat>
        <count>5</count>
        <keya>valuea</keya>
        <vendor_id>8086</vendor_id>
        <product_id>1520</product_id>
        <extra_info>
          <key1>value1</key1>
          <phys_function>[["0x0000", "0x04", "0x00", "0x1"]]</phys_function>
        </extra_info>
      </os-pci:pci_stat>
    </os-pci:pci_stats>
  </hypervisor>
</hypervisors>