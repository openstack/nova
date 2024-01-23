REMOTE_HOST=$1

NOVA_ROOT=/opt/stack/nova/nova

echo 'uploading files...'

#scp -r ./compute/resource_tracker.py stack@$REMOTE_HOST:$NOVA_ROOT/compute/
#scp -r ./conf/compute.py stack@$REMOTE_HOST:$NOVA_ROOT/conf/
#scp -r ./objects/compute_node.py stack@$REMOTE_HOST:$NOVA_ROOT/objects/
#scp -r ./objects/numa.py stack@$REMOTE_HOST:$NOVA_ROOT/objects/
#scp -r ./scheduler/host_manager.py stack@$REMOTE_HOST:$NOVA_ROOT/scheduler/host_manager.py
#scp -r ./virt/hardware.py stack@$REMOTE_HOST:$NOVA_ROOT/virt/
#scp -r ./virt/libvirt/driver.py stack@$REMOTE_HOST:$NOVA_ROOT/virt/libvirt/
#scp -r ./virt/libvirt/host.py stack@$REMOTE_HOST:$NOVA_ROOT/virt/libvirt/

scp -r ./scheduler/filters/compute_filter.py stack@$REMOTE_HOST:$NOVA_ROOT/scheduler/filters/
scp -r ./scheduler/weights/cpu.py stack@$REMOTE_HOST:$NOVA_ROOT/scheduler/weights/
scp -r ./scheduler/manager.py stack@$REMOTE_HOST:$NOVA_ROOT/scheduler/

echo 'restarting devstack services...'
ssh stack@$REMOTE_HOST 'sudo systemctl restart devstack@*'