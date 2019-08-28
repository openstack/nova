{
    "flavors": [
        {
            "OS-FLV-DISABLED:disabled": false,
            "disk": 1,
            "OS-FLV-EXT-DATA:ephemeral": 0,
            "id": "1",
            "links": [
                {
                    "href": "%(versioned_compute_endpoint)s/flavors/1",
                    "rel": "self"
                },
                {
                    "href": "%(compute_endpoint)s/flavors/1",
                    "rel": "bookmark"
                }
            ],
            "name": "m1.tiny",
            "os-flavor-access:is_public": true,
            "ram": 512,
            "swap": "",
            "vcpus": 1,
            "rxtx_factor": 1.0,
            "description": null,
            "extra_specs": {}
        },
        {
            "OS-FLV-DISABLED:disabled": false,
            "disk": 20,
            "OS-FLV-EXT-DATA:ephemeral": 0,
            "id": "2",
            "links": [
                {
                    "href": "%(versioned_compute_endpoint)s/flavors/2",
                    "rel": "self"
                },
                {
                    "href": "%(compute_endpoint)s/flavors/2",
                    "rel": "bookmark"
                }
            ],
            "name": "m1.small",
            "os-flavor-access:is_public": true,
            "ram": 2048,
            "swap": "",
            "vcpus": 1,
            "rxtx_factor": 1.0,
            "description": null,
            "extra_specs": {}
        },
        {
            "OS-FLV-DISABLED:disabled": false,
            "disk": 40,
            "OS-FLV-EXT-DATA:ephemeral": 0,
            "id": "3",
            "links": [
                {
                    "href": "%(versioned_compute_endpoint)s/flavors/3",
                    "rel": "self"
                },
                {
                    "href": "%(compute_endpoint)s/flavors/3",
                    "rel": "bookmark"
                }
            ],
            "name": "m1.medium",
            "os-flavor-access:is_public": true,
            "ram": 4096,
            "swap": "",
            "vcpus": 2,
            "rxtx_factor": 1.0,
            "description": null,
            "extra_specs": {}
        },
        {
            "OS-FLV-DISABLED:disabled": false,
            "disk": 80,
            "OS-FLV-EXT-DATA:ephemeral": 0,
            "id": "4",
            "links": [
                {
                    "href": "%(versioned_compute_endpoint)s/flavors/4",
                    "rel": "self"
                },
                {
                    "href": "%(compute_endpoint)s/flavors/4",
                    "rel": "bookmark"
                }
            ],
            "name": "m1.large",
            "os-flavor-access:is_public": true,
            "ram": 8192,
            "swap": "",
            "vcpus": 4,
            "rxtx_factor": 1.0,
            "description": null,
            "extra_specs": {}
        },
        {
            "OS-FLV-DISABLED:disabled": false,
            "disk": 160,
            "OS-FLV-EXT-DATA:ephemeral": 0,
            "id": "5",
            "links": [
                {
                    "href": "%(versioned_compute_endpoint)s/flavors/5",
                    "rel": "self"
                },
                {
                    "href": "%(compute_endpoint)s/flavors/5",
                    "rel": "bookmark"
                }
            ],
            "name": "m1.xlarge",
            "os-flavor-access:is_public": true,
            "ram": 16384,
            "swap": "",
            "vcpus": 8,
            "rxtx_factor": 1.0,
            "description": null,
            "extra_specs": {}
        },
        {
            "OS-FLV-DISABLED:disabled": false,
            "disk": 1,
            "OS-FLV-EXT-DATA:ephemeral": 0,
            "id": "6",
            "links": [
                {
                    "href": "%(versioned_compute_endpoint)s/flavors/6",
                    "rel": "self"
                },
                {
                    "href": "%(compute_endpoint)s/flavors/6",
                    "rel": "bookmark"
                }
            ],
            "name": "m1.tiny.specs",
            "os-flavor-access:is_public": true,
            "ram": 512,
            "swap": "",
            "vcpus": 1,
            "rxtx_factor": 1.0,
            "description": null,
            "extra_specs": {
                "hw:numa_nodes": "1"
            }
        },
        {
            "OS-FLV-DISABLED:disabled": false,
            "disk": 20,
            "OS-FLV-EXT-DATA:ephemeral": 0,
            "id": "%(flavorid)s",
            "links": [
                {
                    "href": "%(versioned_compute_endpoint)s/flavors/%(flavorid)s",
                    "rel": "self"
                },
                {
                    "href": "%(compute_endpoint)s/flavors/%(flavorid)s",
                    "rel": "bookmark"
                }
            ],
            "name": "m1.small.description",
            "os-flavor-access:is_public": true,
            "ram": 2048,
            "swap": "",
            "vcpus": 1,
            "rxtx_factor": 1.0,
            "description": "test description",
            "extra_specs": {
                "key1": "value1",
                "key2": "value2"
            }
        }
    ]
}
