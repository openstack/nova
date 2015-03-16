
from nova.virt.vcloud import driver

# VMwareESXDriver is deprecated in Juno. This property definition
# allows those configurations to work which reference it while
# logging a deprecation warning
VMwareVcloudDriver = driver.VMwareVcloudDriver
