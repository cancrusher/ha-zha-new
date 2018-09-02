""" custom py file for device."""

def _custom_endpoint_init(self, node_config, *argv):
    config = {
        "in_cluster": [0x0000, 0x0006 ],
        "type": "binary_sensor",
        }
    node_config.update(config)

