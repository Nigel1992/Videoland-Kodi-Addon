import importlib.util
import io
import os
import sys
import tempfile
import unittest
from unittest.mock import MagicMock, patch
from urllib.error import HTTPError
from urllib.parse import parse_qsl, urlsplit
from xml.etree import ElementTree

from resources.lib.api import ApiError, AuthError, VideolandApi


def load_plugin():
    modules = {name: MagicMock() for name in
               ('xbmc', 'xbmcaddon', 'xbmcgui', 'xbmcplugin', 'xbmcvfs')}
    spec = importlib.util.spec_from_file_location(
        'resources.lib.auth_test_plugin',
        os.path.join(os.path.dirname(__file__), '../resources/lib/plugin.py'))
    plugin = importlib.util.module_from_spec(spec)
    with patch.dict(sys.modules, modules), patch.object(sys, 'argv', ['plugin://test', '1']):
        spec.loader.exec_module(plugin)
    return plugin


class AuthenticationTests(unittest.TestCase):
    def test_playback_stops_before_api_calls_when_drm_setup_is_cancelled(self):
        plugin = load_plugin()
        plugin.api = MagicMock()
        helper_module = MagicMock()
        helper_module.Helper.return_value.check_inputstream.return_value = False
        with patch.dict(sys.modules, {'inputstreamhelper': helper_module}):
            plugin.play('123')
        helper_module.Helper.assert_called_once_with('mpd', drm='com.widevine.alpha')
        plugin.api.assert_not_called()
        plugin.xbmcplugin.setResolvedUrl.assert_called_once_with(
            plugin.HANDLE, False, plugin.xbmcgui.ListItem.return_value)

    def test_playback_checks_drm_before_requesting_credentials(self):
        plugin = load_plugin()
        helper_module = MagicMock()
        helper = helper_module.Helper.return_value
        helper.inputstream_addon = 'inputstream.adaptive'
        helper.check_inputstream.return_value = True
        client = MagicMock()
        def make_client():
            helper.check_inputstream.assert_called_once_with()
            return client
        plugin.api = make_client
        plugin.ensure_login = MagicMock(return_value={'uid': 'user'})
        plugin.ensure_profile = MagicMock()
        plugin.video_assets = MagicMock(return_value=[{
            'format': 'dash', 'path': 'https://example.invalid/video.mpd'}])
        client.upfront_token.return_value = 'token'
        client.LICENSE_URL = 'https://example.invalid/license'
        with patch.dict(sys.modules, {'inputstreamhelper': helper_module}):
            plugin.play('123')
        client.upfront_token.assert_called_once_with('user', '123')
        plugin.xbmcgui.ListItem.return_value.setProperty.assert_any_call(
            'inputstream', 'inputstream.adaptive')
        plugin.xbmcplugin.setResolvedUrl.assert_called_once_with(
            plugin.HANDLE, True, plugin.xbmcgui.ListItem.return_value)

    def test_settings_clear_cache_action_removes_cache_without_refresh(self):
        settings = ElementTree.parse(os.path.join(os.path.dirname(__file__), '../resources/settings.xml'))
        button = settings.find(".//setting[@id='clear_cache']")
        action = button.findtext('data')
        self.assertTrue(action.startswith('RunPlugin('))
        self.assertEqual(button.findtext('control/close'), 'false')
        params = dict(parse_qsl(urlsplit(action[len('RunPlugin('):-1]).query))
        plugin = load_plugin()
        with tempfile.TemporaryDirectory() as directory:
            plugin.cache_dir = lambda: directory
            for name in ('cache_one.json', 'cache_two.json', 'keep.txt'):
                with open(os.path.join(directory, name), 'w') as file:
                    file.write('{}')
            plugin.dispatch(params)
            self.assertEqual(os.listdir(directory), ['keep.txt'])
            plugin.xbmc.executebuiltin.assert_not_called()
            plugin.xbmcgui.Dialog().notification.assert_called_with(
                'Videoland', 'Cache gewist (2)', time=3000)
            plugin.dispatch(params)
            plugin.xbmcgui.Dialog().notification.assert_called_with(
                'Videoland', 'Cache gewist (0)', time=3000)

    def test_genre_link_opens_complete_title_list_without_submenu(self):
        plugin = load_plugin()
        plugin.add = MagicMock()
        plugin._render_rows([
            ({"title": "Drama"}, {"id": "2", "seo": "main-films-6"},
             "folder", {"block_title": "Genres"})
        ])
        route = dict(parse_qsl(urlsplit(plugin.add.call_args.args[1]).query))
        self.assertEqual(route["group"], "genre")
        self.assertEqual(route["entity_id"], "2")
        client = MagicMock()
        client.layout.return_value = {"blocks": []}
        plugin.api = lambda: client
        plugin.ensure_login = MagicMock(return_value={})
        plugin.ensure_profile = MagicMock()
        plugin.show_items = MagicMock()
        plugin.show_layout("folder", "2", group="genre")
        self.assertFalse(plugin.show_items.call_args.kwargs["grouped_catalog"])
        options = client.layout.call_args.kwargs
        self.assertTrue(options["complete"])
        self.assertTrue(options["block_filter"]({"analytics": {"tealium": {
            "block_title": "Drama", "from": "feature.programs_by_tags"}}}))

    def test_browsing_completes_genres_selected_collections_and_episodes(self):
        plugin = load_plugin()
        client = MagicMock()
        client.layout.return_value = {"blocks": []}
        plugin.api = lambda: client
        plugin.ensure_login = MagicMock(return_value={})
        plugin.ensure_profile = MagicMock()
        plugin.show_items = MagicMock()
        def block(title, feature="feature.programs_by_tags"):
            return {"analytics": {"tealium": {"block_title": title, "from": feature}}}
        plugin.show_layout("folder", "581")
        options = client.layout.call_args.kwargs
        self.assertTrue(options["complete"])
        self.assertTrue(options["block_filter"](block("Genres")))
        self.assertFalse(options["block_filter"](block("Drama")))
        plugin.show_layout("folder", "2", section="Drama", group="collection")
        select = client.layout.call_args.kwargs["block_filter"]
        self.assertTrue(select(block("Drama")))
        self.assertFalse(select(block("Other collection")))
        plugin.show_layout("program", "1", season=1)
        select = client.layout.call_args.kwargs["block_filter"]
        self.assertTrue(select(block("Seizoen 1", "feature.videos_by_season_by_program")))
        self.assertFalse(select(block("Anderen kijken ook", "feature.recommended_programs_by_program")))

    def test_http_authentication_errors(self):
        for status in (401, 403, 498, 500):
            with self.subTest(status=status):
                error = HTTPError('https://example.invalid', status, 'error', {},
                                  io.BytesIO(b'{"message":"token invalid or expired"}'))
                with patch('resources.lib.api.urlopen', side_effect=error):
                    with self.assertRaises(ApiError) as caught:
                        VideolandApi()._request('https://example.invalid')
                self.assertEqual(isinstance(caught.exception, AuthError), status != 500)
                error.close()

    def test_startup_renews_repeatedly_using_encrypted_saved_credentials(self):
        plugin = load_plugin()
        with tempfile.TemporaryDirectory() as directory:
            settings = {'profile_id': 'saved-profile'}
            plugin.data_dir = lambda: directory
            plugin.setting = lambda key, default='': settings.get(key, default)
            plugin.save = lambda key, value: settings.__setitem__(key, value)
            plugin.store_credentials('test@example.invalid', 'test-password')
            plugin.store_auth({'uid': 'user', 'signature': 'expired', 'timestamp': '1'})
            encrypted_credentials = settings['secret_json']
            client = MagicMock()
            client.login.return_value = {'uid': 'user', 'signature': 'fresh', 'timestamp': '2'}
            plugin.api = lambda: client
            plugin.add = MagicMock()
            for failure in ('jwt', 'navigation'):
                with self.subTest(failure=failure):
                    client.jwt.side_effect = [AuthError('expired'), None, None] if failure == 'jwt' else None
                    client.navigation.side_effect = [AuthError('expired'), []] if failure == 'navigation' else None
                    client.navigation.return_value = []
                    plugin._dispatch_with_retry({})
                    client.login.assert_called_with('test@example.invalid', 'test-password')
                    self.assertEqual(plugin.auth_data(), client.login.return_value)
                    self.assertEqual(settings['secret_json'], encrypted_credentials)
                    self.assertNotIn('test-password', encrypted_credentials)
                    self.assertNotIn('fresh', settings['auth_json'])
            self.assertEqual(client.login.call_count, 2)
            plugin.xbmcgui.Dialog.assert_not_called()

    def test_missing_credentials_prompt_and_save_for_future_refresh(self):
        plugin = load_plugin()
        plugin.credentials_data = lambda: (None, None)
        plugin.api = MagicMock()
        plugin.store_auth = MagicMock()
        plugin.store_credentials = MagicMock()
        plugin._resolve_profile = MagicMock(return_value='profile')
        plugin.save = MagicMock()
        plugin.xbmcgui.Dialog().input.side_effect = ['test@example.invalid', 'test-password']
        plugin.refresh_session()
        plugin.api().login.assert_called_once_with('test@example.invalid', 'test-password')
        plugin.store_credentials.assert_called_once_with('test@example.invalid', 'test-password')

    def test_cancel_missing_credentials_does_not_prompt_again(self):
        plugin = load_plugin()
        plugin.auth_data = lambda: {}
        plugin.credentials_data = lambda: (None, None)
        plugin.api = MagicMock()
        plugin.xbmcgui.Dialog().input.return_value = ''
        with self.assertRaises(ApiError):
            plugin.ensure_login()
        plugin.xbmcgui.Dialog().input.assert_called_once()
        plugin.api().login.assert_not_called()

    def test_rejected_retry_does_not_loop(self):
        plugin = load_plugin()
        plugin.dispatch = MagicMock(side_effect=AuthError('expired'))
        plugin.refresh_session = MagicMock(return_value=(None, None, None))
        with self.assertRaises(AuthError):
            plugin._dispatch_with_retry({})
        self.assertEqual(plugin.dispatch.call_count, 2)
        plugin.refresh_session.assert_called_once()

    def test_non_authentication_error_does_not_login(self):
        plugin = load_plugin()
        plugin.dispatch = MagicMock(side_effect=ApiError('network unavailable'))
        plugin.refresh_session = MagicMock()
        with self.assertRaises(ApiError):
            plugin._dispatch_with_retry({})
        plugin.refresh_session.assert_not_called()

    def test_parallel_program_lookup_propagates_expired_token(self):
        plugin = load_plugin()
        plugin._play_target = MagicMock(side_effect=AuthError('expired'))
        plugin.add = MagicMock()
        with self.assertRaises(AuthError):
            plugin._render_rows([({}, {'id': 'program-1'}, 'program', {})], MagicMock())
        plugin.add.assert_not_called()

    def test_background_comes_from_title_hero_not_catalogue_card(self):
        plugin = load_plugin()
        card = {'id': 'poster', 'ratio': '16:9', 'idsByRatio': {'16:9': 'card-wide'}}
        hero = {'id': 'hero-wide', 'ratio': '16:9'}
        data = {'blocks': [
            {'content': {'contentTemplateId': 'PortraitList', 'items': [{'itemContent': {'image': card}}]}},
            {'content': {'contentTemplateId': 'Jumbotron', 'items': [{'itemContent': {'image': hero}}]}},
        ]}
        self.assertNotIn('fanart', plugin.content_art(card))
        self.assertTrue(plugin.hero_art(data)['fanart'].endswith('/hero-wide/raw'))
        client = MagicMock()
        client.layout.return_value = data
        plugin.add = MagicMock()
        plugin._render_rows([({'title': 'Title', 'image': card}, {'id': '123'}, 'program', {})], client)
        artwork = plugin.add.call_args.args[3]
        self.assertTrue(artwork['thumb'].endswith('/poster/raw'))
        self.assertTrue(artwork['fanart'].endswith('/hero-wide/raw'))

    def test_missing_hero_does_not_reuse_thumbnail(self):
        plugin = load_plugin()
        self.assertEqual(plugin.hero_art({'blocks': []}), {})

    def test_grouped_catalog_only_appear_inside_genres_folder(self):
        plugin = load_plugin()
        genres = [({'image': {'caption': name.title()}}, {'id': str(index)}, 'folder', {})
                  for index, name in enumerate(sorted(plugin.GENRES))]
        movie = ({'title': 'Drama'}, {'id': 'movie'}, 'program', {})
        other = ({'title': 'Nieuw'}, {'id': 'new'}, 'folder', {})
        plugin._build_rows = lambda data, **kwargs: genres + [movie, other]
        plugin._render_rows = MagicMock()
        plugin.add = MagicMock()
        plugin.show_items({}, grouped_catalog=True)
        self.assertEqual([call.args[0] for call in plugin.add.call_args_list], ['Genres', 'Uitgelicht'])
        plugin._render_rows.assert_not_called()
        plugin.show_items({}, grouped_catalog=True, collection_section='')
        self.assertEqual(plugin._render_rows.call_args.args[0], [movie, other])
        plugin.add.reset_mock()
        plugin.show_items({}, grouped_catalog=True, genres_only=True)
        self.assertEqual(plugin._render_rows.call_args.args[0], genres)
        plugin.add.assert_not_called()
        plugin.show_items({})
        self.assertEqual(plugin._render_rows.call_args.args[0], genres + [movie, other])

    def test_nested_routes_keep_display_labels_and_request_parameters(self):
        plugin = load_plugin()
        plugin.menu_icon = lambda key: None
        for label in ('Films', 'Mysterie', 'Titel & naam / deel 2', 'Seizoen 1'):
            route = plugin.url(action='layout', kind='folder', entity_id='15', seo='main-film-15')
            plugin.add(label, route)
            actual_route = plugin.xbmcplugin.addDirectoryItem.call_args.args[1]
            params = dict(parse_qsl(urlsplit(actual_route).query))
            self.assertEqual(params['seo'], 'main-film-15')
            self.assertEqual(params['entity_id'], '15')
            plugin.show_layout = MagicMock()
            plugin.dispatch(params)
        self.assertEqual(plugin.BREADCRUMB,
                         ['Videoland', 'Films', 'Mysterie', 'Titel & naam / deel 2', 'Seizoen 1'])
        plugin.xbmcplugin.setPluginCategory.assert_called_with(
            plugin.HANDLE, 'Films / Mysterie / Titel & naam / deel 2 / Seizoen 1')

    def test_movie_collections_preserve_shared_titles_and_order(self):
        plugin = load_plugin()
        item = {'title': 'Shared movie', 'action': {'target': {
            'type': 'layout', 'value_layout': {'type': 'program', 'id': '123'}}}}
        titles = ["Top 10 films en docu's van vandaag", 'Romantische komedies']
        data = {'blocks': [{'blockId': str(index), 'analytics': {'tealium': {
            'from': 'feature.list', 'block_title': title}},
            'content': {'items': [{'itemContent': item}]}}
            for index, title in enumerate(titles)]}
        plugin.add = MagicMock()
        plugin._render_rows = MagicMock()
        plugin.show_items(data, grouped_catalog=True)
        self.assertEqual([call.args[0] for call in plugin.add.call_args_list],
                         ['Top 10', 'Romantische komedies'])
        plugin._render_rows.assert_not_called()
        for title in titles:
            plugin.show_items(data, grouped_catalog=True, collection_section=title)
            rows = plugin._render_rows.call_args.args[0]
            self.assertEqual(len(rows), 1)
            self.assertEqual(rows[0][0]['title'], 'Shared movie')
            self.assertEqual(rows[0][3]['block_title'], title)

    def test_root_category_does_not_repeat_addon_name(self):
        plugin = load_plugin()
        plugin.set_breadcrumb(['Videoland'])
        plugin.xbmcplugin.setPluginCategory.assert_called_with(plugin.HANDLE, '')

    def test_breadcrumb_is_restored_from_route_when_going_back(self):
        plugin = load_plugin()
        plugin.show_layout = MagicMock()
        plugin.set_breadcrumb(['Videoland', 'Films', 'Mysterie'])
        plugin.dispatch({'action': 'layout', 'breadcrumb': '["Videoland", "Films"]'})
        self.assertEqual(plugin.BREADCRUMB, ['Videoland', 'Films'])

    def test_invalid_breadcrumb_falls_back_without_crashing(self):
        plugin = load_plugin()
        for value in (None, 'broken', '{}', '["Videoland", null]', '["wrong"]'):
            self.assertEqual(plugin.read_breadcrumb(value), [])

    def test_rotating_collections_have_neutral_icons(self):
        plugin = load_plugin()
        for title in ('Eén nacht verandert alles', 'Vriendschap met een dodelijke bijsmaak',
                      'Een hartstochtelijke herfst', 'Nieuwe romantische avonturen'):
            self.assertEqual(plugin.collection_icon(title), 'collection')
        self.assertEqual(plugin.collection_icon('Top 10 series'), 'top10')
        self.assertEqual(plugin.collection_icon('Onlangs toegevoegde series'), 'recent')

    def test_all_catalog_sections_keep_their_own_source(self):
        plugin = load_plugin()
        rows = [({'title': 'Fantasy'}, {'id': '78'}, 'folder', {'block_title': 'Genres'}),
                ({'title': 'Example'}, {'id': '123'}, 'program', {'block_title': 'Top 10'})]
        plugin._build_rows = lambda data, **kwargs: rows
        plugin._render_rows = MagicMock()
        plugin.add = MagicMock()
        for kind, entity_id in [('folder', '580'), ('folder', '581'), ('folder', '582'),
                                ('folder', '583'), ('folder', '25'), ('alias', 'home'),
                                ('folder', 'future-category')]:
            with self.subTest(kind=kind, entity_id=entity_id):
                plugin.add.reset_mock()
                plugin.show_items({}, grouped_catalog=True,
                                  catalog_route={'kind': kind, 'entity_id': entity_id})
                self.assertEqual([call.args[0] for call in plugin.add.call_args_list], ['Genres', 'Top 10'])
                for call in plugin.add.call_args_list:
                    params = dict(parse_qsl(urlsplit(call.args[1]).query))
                    self.assertEqual(params['kind'], kind)
                    self.assertEqual(params['entity_id'], entity_id)
        plugin._render_rows.assert_not_called()

    def test_recurring_functions_and_editorial_banners_have_distinct_icons(self):
        plugin = load_plugin()
        cases = [('Verder kijken', {}, 'continue'),
                 ('Aanbevolen voor jou', {}, 'recommended'),
                 ('Vooruitkijken', {}, 'preview'),
                 ('Nieuw bij Videoland', {}, 'recent'),
                 ('Wat wil je kijken?', {}, 'genres'),
                 ('Populair bij kids en tieners', {'feature': 'feature.list'}, 'top10'),
                 ('Nieuw bij Videoland', {'template': 'Banner'}, 'collection'),
                 ('Top 10 verrassingen', {'template': 'Banner'}, 'collection'),
                 ('Andere naam', {'feature': 'feature.recommended_videos_by_user'}, 'continue'),
                 ('Actiefilms', {'feature': 'feature.programs_by_segment'}, 'collection'),
                 ('Romantische komedies', {'feature': 'feature.programs_by_tags'}, 'collection')]
        for title, block, expected in cases:
            with self.subTest(title=title, block=block):
                self.assertEqual(plugin.collection_icon(title, block), expected)

    def test_clean_episode_label_strips_number_marker_only(self):
        plugin = load_plugin()
        for raw, expected in [
            ('1. Extreme Gebedsgenezers', 'Extreme Gebedsgenezers'),
            ('2. Bevroren Om Te Overleven', 'Bevroren Om Te Overleven'),
            ('12) - Aflevering 1', 'Aflevering 1'),
            ('3 - De Dood', 'De Dood'),
            ('5: In De Dodencel', 'In De Dodencel'),
            ('Extreme Gebedsgenezers', 'Extreme Gebedsgenezers'),
            ('100% NL', '100% NL'),
            ('Seizoen 5', 'Seizoen 5'),
            ('123', '123'),
            ('', ''),
            (None, ''),
        ]:
            with self.subTest(raw=raw):
                self.assertEqual(plugin._clean_episode_label(raw), expected)

    def test_video_location_matches_play_url(self):
        plugin = load_plugin()
        target = {'id': 'clip_98152', 'seo': 'aflevering-1',
                  'parent': {'id': '1637', 'seo': 'ewout', 'type': 'program'}}
        self.assertEqual(plugin.video_location(target),
                         'https://v2.videoland.com/ewout-p_1637/aflevering-1-c_98152')
        self.assertEqual(plugin.video_location({'id': 'clip_5'}), 'https://v2.videoland.com/')

    def test_episode_details_reads_title_and_player_synopsis(self):
        plugin = load_plugin()
        layout = {'entity': {'id': 'clip_98152', 'type': 'video',
                             'metadata': {'code': 'aflevering-1', 'title': 'Extreme Gebedsgenezers'}},
                  'seo': {'title': 'Extreme Gebedsgenezers'},
                  'blocks': [{'blockId': 'b1', 'type': 'bffPaginated',
                              'analytics': {'tealium': {'from': 'feature.videos_for_player',
                                                        'block_title': 'Live TV'}},
                              'content': {'contentTemplateId': 'Player', 'items': [
                                  {'itemContent': {'title': 'Ewout:', 'extraTitle': '1. Extreme Gebedsgenezers',
                                                   'description': 'Gebedsgenezers worden steeds populairder.'}}]}}]}
        title, plot = plugin._episode_details(layout)
        self.assertEqual(title, 'Extreme Gebedsgenezers')
        self.assertEqual(plot, 'Gebedsgenezers worden steeds populairder.')

    def test_episode_rows_recover_title_and_description_from_video_layout(self):
        plugin = load_plugin()
        card = {'title': None, 'name': None, 'extraTitle': '1. Extreme Gebedsgenezers',
                'description': None, 'image': {'id': '568768', 'caption': 'Extreme Gebedsgenezers',
                                               'ratio': '16:9'},
                'action': {'target': {'type': 'layout', 'value_layout': {
                    'type': 'video', 'id': 'clip_98152', 'seo': 'aflevering-1',
                    'parent': {'id': '1637', 'type': 'program', 'seo': 'ewout'}}}}}
        video_layout = {'entity': {'id': 'clip_98152', 'type': 'video',
                                   'metadata': {'code': 'aflevering-1', 'title': 'Extreme Gebedsgenezers'}},
                        'seo': {'title': 'Extreme Gebedsgenezers'},
                        'blocks': [{'blockId': 'b1', 'type': 'bffPaginated',
                                    'analytics': {'tealium': {'from': 'feature.videos_for_player',
                                                              'block_title': 'Live TV'}},
                                    'content': {'contentTemplateId': 'Player', 'items': [
                                        {'itemContent': {'title': 'Ewout:', 'extraTitle': '1. Extreme Gebedsgenezers',
                                                         'description': 'Gebedsgenezers worden in Nederland steeds populairder.'}}]}}]}
        client = MagicMock()
        client.layout.side_effect = lambda kind, entity_id, location=None: video_layout
        plugin._play_target = lambda c, item, target, k, **kw: target
        plugin.add = MagicMock()
        target = card['action']['target']['value_layout']
        plugin._render_rows([(card, target, 'video', {'block_title': 'Seizoen 5'})], client,
                            {'fanart': 'https://example.invalid/hero/raw'})
        label, route, folder, art, info = plugin.add.call_args.args
        self.assertEqual(plugin.add.call_args.kwargs['playable'], True)
        self.assertEqual(label, 'Extreme Gebedsgenezers')
        self.assertEqual(info['title'], 'Extreme Gebedsgenezers')
        self.assertEqual(info['plot'], 'Gebedsgenezers worden in Nederland steeds populairder.')
        self.assertEqual(info['episode'], 1)
        self.assertEqual(info['season'], 5)
        client.layout.assert_called_once()

    def test_episode_without_artwork_gets_clean_title_from_video_detail(self):
        plugin = load_plugin()
        card = {'title': None, 'name': None, 'extraTitle': '2. Bevroren Om Te Overleven',
                'description': None, 'image': None,
                'action': {'target': {'type': 'layout', 'value_layout': {
                    'type': 'video', 'id': 'clip_98151', 'seo': 'aflevering-2',
                    'parent': {'id': '1637', 'type': 'program', 'seo': 'ewout'}}}}}
        client = MagicMock()
        client.layout.side_effect = lambda kind, entity_id, location=None: {
            'entity': {'metadata': {'title': 'Bevroren Om Te Overleven'}},
            'seo': {'title': 'Bevroren Om Te Overleven'}, 'blocks': []}
        plugin._play_target = lambda c, item, target, k, **kw: target
        plugin.add = MagicMock()
        target = card['action']['target']['value_layout']
        plugin._render_rows([(card, target, 'video', {})], client)
        label, route, folder, art, info = plugin.add.call_args.args
        self.assertEqual(plugin.add.call_args.kwargs['playable'], True)
        self.assertEqual(label, 'Bevroren Om Te Overleven')
        self.assertEqual(info['title'], 'Bevroren Om Te Overleven')

    def test_hero_jumbotron_does_not_shadow_the_real_episode_card(self):
        plugin = load_plugin()
        card = lambda extra_title, vid: {
            'title': None, 'name': None, 'extraTitle': extra_title,
            'image': {'id': 'img', 'caption': extra_title.split('. ', 1)[-1], 'ratio': '16:9'},
            'action': {'target': {'type': 'layout', 'value_layout': {
                'type': 'video', 'id': vid, 'seo': 'aflevering-1',
                'parent': {'id': 'p1', 'type': 'program', 'seo': 'ewout'}}}}}
        block = lambda template, feature, title, item: {
            'blockId': template + '-b', 'type': 'bffPaginated',
            'analytics': {'tealium': {'from': feature, 'block_title': title if title else None}},
            'content': {'contentTemplateId': template,
                        'items': [{'itemContent': item}]}}
        layout = {'blocks': [
            block('Jumbotron', 'feature.info_by_program', '',
                  card('Laatste aflevering', 'clip_9')),
            block('CardM', 'feature.videos_by_season_by_program', 'Seizoen 1',
                  card('1. Extreme Gebedsgenezers', 'clip_9')),
        ]}
        rows = plugin._build_rows(layout)
        self.assertEqual(len(rows), 1)
        item, target, kind, blk = rows[0]
        self.assertEqual(target['id'], 'clip_9')
        self.assertEqual(item['extraTitle'], '1. Extreme Gebedsgenezers')
        self.assertEqual(plugin.block_season(blk), 1)
        self.assertFalse(plugin.is_hero_block(blk))


if __name__ == '__main__':
    unittest.main()
