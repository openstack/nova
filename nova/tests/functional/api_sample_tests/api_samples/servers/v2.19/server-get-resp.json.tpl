{
    "server": {
        "accessIPv4": "%(access_ip_v4)s",
        "accessIPv6": "%(access_ip_v6)s",
        "addresses": {
            "private": [
                {
                    "addr": "%(ip)s",
                    "OS-EXT-IPS-MAC:mac_addr": "aa:bb:cc:dd:ee:ff",
                    "OS-EXT-IPS:type": "fixed",
                    "version": 4
                }
            ]
        },
        "created": "%(isotime)s",
        "flavor": {
            "id": "1",
            "links": [
                {
                    "href": "%(compute_endpoint)s/flavors/1",
                    "rel": "bookmark"
                }
            ]
        },
        "hostId": "%(hostid)s",
        "id": "%(id)s",
        "image": {
            "id": "%(uuid)s",
            "links": [
                {
                    "href": "%(compute_endpoint)s/images/%(uuid)s",
                    "rel": "bookmark"
                }
            ]
        },
        "key_name": null,
        "links": [
            {
                "href": "%(versioned_compute_endpoint)s/servers/%(uuid)s",
                "rel": "self"
            },
            {
                "href": "%(compute_endpoint)s/servers/%(uuid)s",
                "rel": "bookmark"
            }
        ],
        "metadata": {
            "My Server Name": "Apache1"
        },
        "name": "new-server-test",
        "description": "new-server-description",
        "config_drive": "",
        "OS-DCF:diskConfig": "AUTO",
        "OS-EXT-AZ:availability_zone": "nova",
        "OS-EXT-SRV-ATTR:host": "%(compute_host)s",
        "OS-EXT-SRV-ATTR:hypervisor_hostname": "%(hypervisor_hostname)s",
        "OS-EXT-SRV-ATTR:instance_name": "%(instance_name)s",
        "OS-EXT-SRV-ATTR:reservation_id": "%(reservation_id)s",
        "OS-EXT-SRV-ATTR:launch_index": 0,
        "OS-EXT-SRV-ATTR:kernel_id": "",
        "OS-EXT-SRV-ATTR:ramdisk_id": "",
        "OS-EXT-SRV-ATTR:hostname": "%(hostname)s",
        "OS-EXT-SRV-ATTR:root_device_name": "/dev/sda",
        "OS-EXT-SRV-ATTR:user_data": "",
        "OS-EXT-STS:power_state": 1,
        "OS-EXT-STS:task_state": null,
        "OS-EXT-STS:vm_state": "active",
        "os-extended-volumes:volumes_attached": [
            {"id": "volume_id1", "delete_on_termination": false},
            {"id": "volume_id2", "delete_on_termination": false}
        ],
        "OS-SRV-USG:launched_at": "%(strtime)s",
        "OS-SRV-USG:terminated_at": null,
        "progress": 0,
        "security_groups": [
            {
                "name": "default"
            }
        ],
        "host_status": "UP",
        "status": "ACTIVE",
        "tenant_id": "6f70656e737461636b20342065766572",
        "updated": "%(isotime)s",
        "user_id": "fake",
        "locked": false
    }
}
