"""The Netease Lyrics integration."""

import logging
import voluptuous as vol

import homeassistant.helpers.config_validation as cv
from homeassistant.helpers.discovery import async_load_platform
from homeassistant.components.media_player import (
    ATTR_MEDIA_ARTIST,
    ATTR_MEDIA_TITLE,
    ATTR_MEDIA_POSITION,
)
from homeassistant.const import (
    CONF_URL,
    CONF_ENTITIES,
    CONF_ENTITY_ID,
    EVENT_HOMEASSISTANT_START,
)

from .const import (
    ATTR_MEDIA_LYRICS,
    ATTR_MEDIA_LYRICS_CURRENT,
    ATTR_MEDIA_STATE_TIME,
    DOMAIN,
    SERVICE_SEARCH_LYRICS,
)

_LOGGER = logging.getLogger(__name__)

CONFIG_SCHEMA = vol.Schema({
    DOMAIN: vol.Schema({
        vol.Required(CONF_URL): cv.string,
        vol.Optional(CONF_ENTITIES): vol.Any(cv.entity_ids, None),
    })
}, extra=vol.ALLOW_EXTRA)

SERVICE_SCHEMA = vol.Schema({
    DOMAIN: vol.Schema({
        vol.Required(ATTR_MEDIA_ARTIST): cv.string,
        vol.Required(ATTR_MEDIA_TITLE): cv.string,
        vol.Required(ATTR_MEDIA_POSITION): cv.string,
        vol.Required(ATTR_MEDIA_LYRICS_CURRENT): cv.string,
        vol.Required(ATTR_MEDIA_LYRICS): cv.string,
        vol.Required(CONF_ENTITY_ID): vol.Any(cv.entity_id, None),
    })
}, extra=vol.ALLOW_EXTRA)


async def async_setup(hass, config):
    """Setup is called when Home Assistant is loading our component."""
    netease_api_base = config[DOMAIN][CONF_URL]

    @callable
    def search_lyrics(call):
        """Handles searching song lyrics."""
        data = call.data
        artist = data[ATTR_MEDIA_ARTIST]
        title = data[ATTR_MEDIA_TITLE]
        genius.position = data[ATTR_MEDIA_POSITION]
        entity_id = data.get(CONF_ENTITY_ID)
        state = data.get('state')

        # validate entity_id
        if hass.states.get(entity_id) is None:
            _LOGGER.error(f"entity_id {entity_id} does not exist")
            return False

        # preserve entity's current state
        old_state = hass.states.get(entity_id)
        if old_state:
            attrs = old_state.attributes
        else:
            attrs = {}

        # fetch lyrics
        from .sensor import NeteaseLyrics
        genius = NeteaseLyrics(netease_api_base)
        genius.fetch_lyrics(artist, title)
        attrs.update({
            ATTR_MEDIA_ARTIST: genius.artist,
            ATTR_MEDIA_TITLE: genius.title,
            ATTR_MEDIA_POSITION: genius.position,
            ATTR_MEDIA_LYRICS_CURRENT: genius.lyrics_current,
            ATTR_MEDIA_LYRICS: genius.lyrics,
            ATTR_MEDIA_STATE_TIME: genius.state_time,
        })

        # set attributes
        hass.states.async_set(entity_id, state, attrs)

    # register service
    hass.services.async_register(DOMAIN, SERVICE_SEARCH_LYRICS, search_lyrics, SERVICE_SCHEMA)

    # load sensor platform after Home Assistant is started.
    # we need media_player component to be loaded, however, waiting for the
    # media_player component alone may cause problems with entities not existing yet.
    async def load_sensors(event):
        _LOGGER.info(f"Home Assistant is setup, loading sensors")

        # setup platform(s)
        sensor_config = {
            CONF_URL: netease_api_base,
            CONF_ENTITIES: config[DOMAIN][CONF_ENTITIES]
        }
        hass.async_create_task(async_load_platform(hass, 'sensor', DOMAIN, sensor_config, config))

    if config[DOMAIN][CONF_ENTITIES] is not None:
        _LOGGER.info(f"Waiting for HomeAssistant to start before loading sensors")
        hass.bus.async_listen(EVENT_HOMEASSISTANT_START, load_sensors)

    # Return boolean to indicate that initialization was successfully.
    return True
