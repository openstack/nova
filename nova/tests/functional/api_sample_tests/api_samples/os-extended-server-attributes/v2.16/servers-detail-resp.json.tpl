{
    "servers": [
        {
            "OS-EXT-SRV-ATTR:host": "%(compute_host)s",
            "OS-EXT-SRV-ATTR:hypervisor_hostname": "%(hypervisor_hostname)s",
            "OS-EXT-SRV-ATTR:instance_name": "%(instance_name)s",
	        "OS-EXT-SRV-ATTR:hostname": "new-server-test",
	        "OS-EXT-SRV-ATTR:launch_index": "0",
	        "OS-EXT-SRV-ATTR:reservation_id": "%(reservation_id)s",
	        "OS-EXT-SRV-ATTR:root_device_name": "/dev/sda",
	        "OS-EXT-SRV-ATTR:kernel_id": null,
	        "OS-EXT-SRV-ATTR:ramdisk_id": null,
	        "OS-EXT-SRV-ATTR:user_data": null,
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
                        "OS-EXT-IPS-MAC:mac_addr": "aa:bb:cc:dd:ee:ff",
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
            "id": "%(uuid)s",
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
                    "href": "%(versioned_compute_endpoint)s/servers/%(id)s",
                    "rel": "self"
                },
                {
                    "href": "%(compute_endpoint)s/servers/%(id)s",
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
            "tenant_id": "openstack",
            "user_id": "fake",
            "key_name": null
        }
    ]
}
