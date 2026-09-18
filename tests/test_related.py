import unittest
from unittest.mock import Mock
from urllib.parse import parse_qs,urlsplit
from test_auth import load_plugin


def block(feature, title, id):
    return {'analytics': {'tealium': {'from':feature,'block_title':title}},
            'content': {'items':[{'itemContent': {'title':id,'action':{'target':{'type':'layout','value_layout':{'type':'program','id':id}}}}}]}}


class RelatedTests(unittest.TestCase):
    def test_recommendations_exclude_episodes_ads_trailers_and_continue(self):
        plugin=load_plugin()
        plugin.ADDON.getLocalizedString.return_value="Others also watch"
        data={'blocks':[
            block('feature.recommended_programs_by_program','Anderen kijken ook','similar'),
            block('feature.videos_by_program','Afleveringen','episode'),
            block('feature.trailers_by_program','Trailers','trailer'),
            block('feature.advertising_by_program','Advertisement','ad'),
            block('feature.recommended_videos_by_user','Verder kijken','continue')]}
        for local in (False, True):
            plugin.local_history=lambda: local
            rows=plugin._build_rows(data,recommendations_only=True)
            self.assertEqual([r[1]['id'] for r in rows],['similar'])

    def test_context_opens_parent_and_encodes_title(self):
        plugin=load_plugin()
        plugin.ADDON.getLocalizedString.return_value="Others also watch"
        plugin.add=Mock()
        plugin._render_rows([({'title':'Episode (1), & more'},
            {'id':'clip_12','type':'video','parent':{'id':'34','seo':'series'}},'video',{})])
        command=plugin.add.call_args.kwargs['context_menu'][0][1]
        self.assertTrue(command.startswith('Container.Update('))
        params=parse_qs(urlsplit(command[len('Container.Update('):-1]).query)
        self.assertEqual(params['entity_id'],['34'])
        self.assertEqual(params['kind'],['program'])
        self.assertEqual(params['title'],['Episode (1), & more'])

    def test_related_fetches_all_recommendations_and_renders_directory(self):
        plugin=load_plugin()
        plugin.ADDON.getLocalizedString.return_value="Others also watch"
        client=Mock()
        client.layout.return_value={'blocks':[block('feature.recommended_programs_by_program','Anderen kijken ook','42')]}
        plugin.api=lambda:client
        plugin.ensure_login=Mock(return_value={})
        plugin.ensure_profile=Mock()
        plugin._render_rows=Mock()
        plugin.show_related('program','34','series','Series')
        options=client.layout.call_args.kwargs
        self.assertTrue(options['complete'])
        self.assertTrue(options['block_filter'](client.layout.return_value['blocks'][0]))
        self.assertFalse(options['block_filter'](block('feature.videos_by_program','Episodes','x')))
        self.assertEqual(plugin._render_rows.call_args.args[0][0][1]['id'],'42')
        plugin.xbmcplugin.endOfDirectory.assert_called_once_with(plugin.HANDLE,cacheToDisc=False)

    def test_empty_result_has_professional_message(self):
        plugin=load_plugin()
        plugin.ADDON.getLocalizedString.return_value="Others also watch"
        plugin.api=Mock()
        plugin.api.return_value.layout.return_value={}
        plugin.ensure_login=Mock()
        plugin.ensure_profile=Mock()
        plugin._render_rows=Mock()
        plugin.show_related('program','34')
        plugin.xbmcgui.Dialog.return_value.ok.assert_called_once()
