"""
Lights on Zigbee Home Automation networks.
For more details on this platform, please refer to the documentation
at https://home-assistant.io/components/light.zha/
"""
import asyncio
import logging

from homeassistant.components import light
from homeassistant.util.color import color_RGB_to_xy
from homeassistant.const import STATE_UNKNOWN
from custom_components import zha_new
from importlib import import_module

_LOGGER = logging.getLogger(__name__)
""" change to ZHA-new for use in home-dir """
DEPENDENCIES = ['zha_new']

DEFAULT_DURATION = 0.5


@asyncio.coroutine
def async_setup_platform(hass, config, async_add_devices, discovery_info=None):
    """Set up the Zigbee Home Automation lights."""
    discovery_info = zha_new.get_discovery_info(hass, discovery_info)
    if discovery_info is None:
        return

    endpoint = discovery_info['endpoint']
    try:
        discovery_info['color_capabilities'] \
            = yield from endpoint.light_color['color_capabilities']
        _LOGGER.debug("Request for color_capabilities: %s",discovery_info['color_capabilities'])
    except AttributeError as e:
        _LOGGER.debug("No color cluster: %s", e.args)
    except KeyError as e:
        _LOGGER.debug("Request for color_capabilities failed: %s", e.args)  
    except Exception as e:
        _LOGGER.debug("Request for color_capabilities, other error: %s", e.args)
    entity = Light(**discovery_info)
    
    if hass.states.get(entity.entity_id):
        _LOGGER.debug("entity exist,remove it: %s",  dir (hass.states.get(entity.entity_id)))
        
    async_add_devices([entity], update_before_add=True)


class Light(zha_new.Entity, light.Light):
    """Representation of a ZHA or ZLL light."""

    _domain = light.DOMAIN

    def __init__(self, **kwargs):
        """Initialize the ZHA light."""
        super().__init__(**kwargs)
        self._supported_features = 0
        self._color_temp = None
        self._xy_color = None
        self._brightness = None

        import zigpy.zigbee.zcl.clusters as zcl_clusters
        if zcl_clusters.general.LevelControl.cluster_id in self._in_clusters:
            self._supported_features |= light.SUPPORT_BRIGHTNESS
            self._supported_features |= light.SUPPORT_TRANSITION
            self._brightness = 0
        if zcl_clusters.lighting.Color.cluster_id in self._in_clusters:
            color_capabilities = kwargs.get('color_capabilities', 0x10)
            if color_capabilities & 0x10:
                self._supported_features |= light.SUPPORT_COLOR_TEMP

            if color_capabilities & 0x08:
                self._supported_features |= light.SUPPORT_XY_COLOR
                self._supported_features |= light.SUPPORT_RGB_COLOR
                self._xy_color = (1.0, 1.0)

    @property
    def is_on(self) -> bool:
        """Return true if entity is on."""
        if self._state == STATE_UNKNOWN:
            return False
        return bool(self._state)

    @asyncio.coroutine
    def async_turn_on(self, **kwargs):
        """Turn the entity on."""
        duration = kwargs.get(light.ATTR_TRANSITION, DEFAULT_DURATION)
        duration = duration * 10  # tenths of s
        if light.ATTR_COLOR_TEMP in kwargs:
            temperature = kwargs[light.ATTR_COLOR_TEMP]
            yield from self._endpoint.light_color.move_to_color_temp(
                temperature, duration)
            self._color_temp = temperature

        if light.ATTR_XY_COLOR in kwargs:
            self._xy_color = kwargs[light.ATTR_XY_COLOR]
        elif light.ATTR_RGB_COLOR in kwargs:
            xyb = color_RGB_to_xy(
                *(int(val) for val in kwargs[light.ATTR_RGB_COLOR]))
            self._xy_color = (xyb[0], xyb[1])
            self._brightness = xyb[2]
        if light.ATTR_XY_COLOR in kwargs or light.ATTR_RGB_COLOR in kwargs:
            yield from self._endpoint.light_color.move_to_color(
                int(self._xy_color[0] * 65535),
                int(self._xy_color[1] * 65535),
                duration,
            )

        if self._brightness is not None:
            brightness = kwargs.get(
                light.ATTR_BRIGHTNESS, self._brightness or 255)
            self._brightness = brightness
            # Move to level with on/off:
            _LOGGER.debug("Turn_on %s: Brightness %s", self.entity_id, brightness) 
            yield from self._endpoint.level.move_to_level_with_on_off(
                brightness,
                duration
            )
            self._state = 1
            self.async_schedule_update_ha_state()
            return

        yield from self._endpoint.on_off.on()
        self._state = 1
        self.async_schedule_update_ha_state()

    @asyncio.coroutine
    def async_turn_off(self, **kwargs):
        """Turn the entity off."""
        yield from self._endpoint.on_off.off()
        self._state = 0
        self.async_schedule_update_ha_state()

    @property
    def brightness(self):
        """Return the brightness of this light between 0..255."""
        return self._brightness

    @property
    def xy_color(self):
        """Return the XY color value [float, float]."""
        return self._xy_color

    @property
    def color_temp(self):
        """Return the CT color value in mireds."""
        return self._color_temp

    @property
    def supported_features(self):
        """Flag supported features."""
        return self._supported_features

    @asyncio.coroutine
    def async_update(self):
        """Retrieve latest state."""
        _LOGGER.debug("%s async_update", self.entity_id)

        @asyncio.coroutine
        def safe_read(cluster, attributes):
            """Swallow all exceptions from network read.
            If we throw during initialization, setup fails. Rather have an
            entity that exists, but is in a maybe wrong state, than no entity.
            """
            try:
                result, _ = yield from cluster.read_attributes(
                    attributes,
                    allow_cache=False,
                )
                return result
            except Exception:  # pylint: disable=broad-except
                return {}
       
        #yield from self._endpoint.on_off.discover_attributes(0,4)
        result = yield from safe_read(self._endpoint.on_off, ['on_off'])
        self._state = result.get('on_off', self._state)
        if not self._state:
            return

        if self._supported_features & light.SUPPORT_BRIGHTNESS:
            result = yield from safe_read(self._endpoint.level,
                                          ['current_level'])
            self._brightness = result.get('current_level', self._brightness)

        if self._supported_features & light.SUPPORT_COLOR_TEMP:
            result = yield from safe_read(self._endpoint.light_color,
                                          ['color_temperature'])
            self._color_temp = result.get('color_temperature',
                                          self._color_temp)

        if self._supported_features & light.SUPPORT_XY_COLOR:
            result = yield from safe_read(self._endpoint.light_color,
                                          ['current_x', 'current_y'])
            if 'current_x' in result and 'current_y' in result:
                self._xy_color = (result['current_x'], result['current_y'])

    @property
    def should_poll(self) -> bool:
        """Return True if entity has to be polled for state.
        False if entity pushes its state to HA.
        """
        return True
    
    def cluster_command(self, aps_frame, tsn, command_id, args):
        try:
            dev_func= self._model.replace(".","_").replace(" ","_")
            _custom_cluster_command = getattr(
                import_module("custom_components.device." + dev_func),
                "_custom_cluster_command"
                )
            _custom_cluster_command(self, aps_frame, tsn, command_id, args)
        except ImportError as e:
            _LOGGER.debug("Import DH %s failed: %s", dev_func, e.args)
        except Exception as e:
            _LOGGER.info("Excecution of DH %s failed: %s", dev_func, e.args)
        
