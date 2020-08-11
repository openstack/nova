{
    "server": {
        "config_drive": "",
        "OS-DCF:diskConfig": "AUTO",
        "OS-EXT-AZ:availability_zone": "us-west",
        "OS-EXT-SRV-ATTR:host": "%(compute_host)s",
        "OS-EXT-SRV-ATTR:hypervisor_hostname": "%(hypervisor_hostname)s",
        "OS-EXT-SRV-ATTR:instance_name": "%(instance_name)s",
        "OS-EXT-SRV-ATTR:hostname": "new-server-test",
        "OS-EXT-SRV-ATTR:launch_index": 0,
        "OS-EXT-SRV-ATTR:reservation_id": "%(reservation_id)s",
        "OS-EXT-SRV-ATTR:root_device_name": "/dev/sda",
        "OS-EXT-SRV-ATTR:kernel_id": null,
        "OS-EXT-SRV-ATTR:ramdisk_id": null,
        "OS-EXT-SRV-ATTR:user_data": "%(user_data)s",
        "OS-EXT-STS:power_state": 1,
        "OS-EXT-STS:task_state": null,
        "OS-EXT-STS:vm_state": "active",
        "os-extended-volumes:volumes_attached": [
            {"id": "volume_id1", "delete_on_termination": false},
            {"id": "volume_id2", "delete_on_termination": false}
        ],
        "OS-SRV-USG:launched_at": "%(strtime)s",
        "OS-SRV-USG:terminated_at": null,
        "security_groups": [
            {
                "name": "default"
            }
        ],
        "locked": false,
        "accessIPv4": "%(access_ip_v4)s",
        "accessIPv6": "%(access_ip_v6)s",
        "updated": "%(isotime)s",
        "created": "%(isotime)s",
        "addresses": {
            "private": [
                {
                    "addr": "%(ip)s",
                    "version": 4,
                    "OS-EXT-IPS-MAC:mac_addr": "00:0c:29:0d:11:74",
                    "OS-EXT-IPS:type": "fixed"
                }
            ]
        },
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
        "progress": 0,
        "status": "ACTIVE",
        "host_status": "UP",
        "tenant_id": "6f70656e737461636b20342065766572",
        "user_id": "admin",
        "key_name": null
    }
}
