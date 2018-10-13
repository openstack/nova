{
    "server" : {
        "name" : "bfv-server-with-volume-type",
        "flavorRef" : "%(host)s/flavors/1",
        "networks" : [{
            "uuid" : "ff608d40-75e9-48cb-b745-77bb55b5eaf2",
            "tag": "nic1"
        }],
        "block_device_mapping_v2": [{
            "uuid": "%(image_id)s",
            "source_type": "image",
            "destination_type": "volume",
            "boot_index": 0,
            "volume_size": "1",
            "tag": "disk1",
            "volume_type": "lvm-1"
        }]
    }
}
