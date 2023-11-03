"""Sensor platform for the Netease Lyrics integration."""

import logging
import requests
import pylrc
from datetime import datetime

import voluptuous as vol
from homeassistant.helpers.config_validation import entities_domain, split_entity_id
from homeassistant.helpers.entity import Entity
from homeassistant.helpers.event import async_track_state_change
from homeassistant.const import (
    CONF_URL,
    CONF_ENTITIES,
    STATE_ON,
    STATE_OFF,
    STATE_PLAYING,
    STATE_PAUSED,
    STATE_BUFFERING,
)
from homeassistant.components.media_player import (
    ATTR_MEDIA_CONTENT_TYPE,
    ATTR_MEDIA_POSITION,
    ATTR_MEDIA_DURATION,
    ATTR_MEDIA_TITLE,
    ATTR_MEDIA_ARTIST,
)
from homeassistant.components.media_player.const import MEDIA_TYPE_MUSIC

from .const import (
    ATTR_MEDIA_LYRICS,
    ATTR_MEDIA_LYRICS_CURRENT,
    ATTR_MEDIA_STATE_TIME
)

from .helpers import (
    entities_exist,
)

_LOGGER = logging.getLogger(__name__)

async def async_setup_platform(hass, config, async_add_entities, discovery_info=None):
    """Set up the sensor platform."""
    if discovery_info is None:
        return

    api_base = discovery_info.get(CONF_URL)
    conf_entities = discovery_info.get(CONF_ENTITIES)

    # validate the entities exist
    monitored_entities = entities_exist(hass, conf_entities)

    # ensure we've got at least one entity to monitor
    if not len(monitored_entities):
        _LOGGER.error("No valid entities to monitor")
        return False

    # validate entities are part of media_player domain
    try:
        validate_entities = entities_domain('media_player')
        validate_entities(conf_entities)
    except vol.Invalid as e:
        _LOGGER.error(e)
        return False
    else:
        _LOGGER.debug(f"Monitoring media players: {monitored_entities}")

    # create sensors, one for each monitored entity
    genius = NeteaseLyrics(api_base)
    sensors = []
    for media_player in monitored_entities:
        # create sensor
        genius_sensor = NeteaseLyricsSensor(hass, genius, media_player)
        # hook media_player to sensor
        async_track_state_change(hass, media_player, genius_sensor.handle_state_change)
        # add new sensor to list
        sensors.append(genius_sensor)

    # add new sensors
    async_add_entities(sensors)

    # platform setup successfully
    return True

class NeteaseLyricsSensor(Entity):
    """Representation of a Sensor."""

    def __init__(self, hass, genius, media_entity_id):
        """Initialize the sensor"""
        self._genius = genius
        self._artist = None
        self._title = None
        self._media_player_id = media_entity_id
        self._name = f'{split_entity_id(media_entity_id)[1]} Lyrics'
        self._state = STATE_OFF

        _LOGGER.debug(f"Creating sensor: {self.name}")

    @property
    def name(self):
        """Return the name of the sensor."""
        return self._name

    @property
    def state(self):
        """Return the state of the sensor."""
        return self._state

    @property
    def extra_state_attributes(self):
        state_attrs = {
            ATTR_MEDIA_ARTIST: self._genius.artist,
            ATTR_MEDIA_TITLE: self._genius.title,
            ATTR_MEDIA_POSITION: self._genius.position,
            ATTR_MEDIA_STATE_TIME: self._genius.state_time,
            ATTR_MEDIA_LYRICS_CURRENT: self._genius.lyrics_current,
            ATTR_MEDIA_LYRICS: self._genius.lyrics,
            # TODO: add URL, Album Art
        }
        return state_attrs

    @property
    def should_poll(self) -> bool:
        return False

    def update(self):
        """Fetch new state data for the sensor"""
        self._genius.fetch_lyrics(self._artist, self._title)

    def handle_state_change(self, entity_id, old_state, new_state):
        # ensure tracking entity_id
        if entity_id != self._media_player_id:
            return

        if new_state.state not in [STATE_PLAYING]: # , STATE_PAUSED, STATE_BUFFERING]:
            self._genius.reset()
            self._state = STATE_OFF
            self.async_schedule_update_ha_state(True)
            return

        # must have music content type and something queued
        if new_state.attributes.get(ATTR_MEDIA_CONTENT_TYPE) != MEDIA_TYPE_MUSIC \
                and new_state.attributes.get(ATTR_MEDIA_DURATION):
            return
        
        # always update position and duration
        self._genius.position = new_state.attributes.get(ATTR_MEDIA_POSITION)
        self._genius.duration = new_state.attributes.get(ATTR_MEDIA_DURATION)
        
        # all checks out
        self._artist = new_state.attributes.get(ATTR_MEDIA_ARTIST)
        self._title = new_state.attributes.get(ATTR_MEDIA_TITLE)
        self._state = STATE_ON

        # trigger update
        self.async_schedule_update_ha_state(True)

class NeteaseLyrics:
    def __init__(self, api_base):
        self.__artist = None
        self.__title = None
        self.__lyrics = "[00:00.00]搜索歌词中[23:59.59]"
        self.__api_base = api_base
        self.__position = 0
        self.__duration = 0
        self.__state_time = datetime.now()

    @property
    def artist(self):
        return self.__artist

    @artist.setter
    def artist(self, new_artist):
        self.__artist = new_artist
        _LOGGER.debug(f"Artist set to: {self.__artist}")

    @property
    def title(self):
        return self.__title

    @title.setter
    def title(self, new_title):
        self.__title = new_title
        _LOGGER.debug(f"Title set to: {self.__title}")

    @property
    def position(self):
        return self.__position

    @position.setter
    def position(self, new_position):
        if new_position and new_position != self.__position:
            self.__position = new_position
            self.__state_time = datetime.now()
            _LOGGER.debug(f"Position set to: {self.__position}")

    @property
    def duration(self):
        return self.__duration

    @duration.setter
    def duration(self, new_duration):
        self.__duration = new_duration

    @property
    def state_time(self):
        return self.__state_time

    @property
    def lyrics(self):
        return self.__lyrics

    @property
    def lyrics_current(self):
        subs = pylrc.parse(self.__lyrics)
        position = self.__position + (datetime.now() - self.__state_time).seconds
        for i in range(1, len(subs)):
            if subs[i].time >= position:
                return subs[i - 1].text + subs[i].text
        return "无法获取当前歌词"

    def fetch_lyrics(self, artist=None, title=None):
        if self.__artist == artist and self.__title == title:
            return True
        if artist is None or artist is None:
            _LOGGER.debug("Missing artist and/or title")
            return False

        _LOGGER.info(f"Search lyrics for artist='{artist}' and title='{title}'")
        search_url = self.__api_base + f"/search?limit=3&keywords={title} {artist}"
        search_res = requests.get(search_url)
        if search_res.status_code == 200:
            id = search_res.json()['result']['songs'][0]['id']
            _LOGGER.debug(f"Found song: {id}")

            lyric_url = self.__api_base + f"/lyric?id={id}"
            lyric_res = requests.get(lyric_url)
            if lyric_res.status_code == 200:
                _LOGGER.debug(f"Found lyrics: {lyric_res.json()['lrc']['lyric']}")
                self.__lyrics = lyric_res.json()['lrc']['lyric']
                if artist:
                    self.__artist = artist
                if title:
                    self.__title = title
                return True
            else:
                self.__lyrics = "[00:00.00]未找到歌词[23:59.59]"
                return False
        else:
            self.__lyrics = "[00:00.00]未找到歌曲[23:59.59]"
            return False

    def reset(self):
        self.__artist = None
        self.__title = None
        self.__lyrics = "[00:00.00]歌曲信息重置[23:59.59]"
