import unittest
from unittest.mock import MagicMock
from test_auth import load_plugin


class ProfileSwitchTests(unittest.TestCase):
    def setup_plugin(self, profiles):
        plugin = load_plugin()
        client = MagicMock()
        client.profiles.return_value = profiles
        plugin.api = lambda: client
        plugin.ensure_login = MagicMock(return_value={'uid': 'user'})
        plugin.save = MagicMock()
        plugin.cache_dir = MagicMock(return_value="/nonexistent/videoland-cache")
        strings = {31050: 'Profiel wisselen',
                   31051: 'Dit account heeft één profiel: {0}. Je kunt daarom niet naar een ander profiel wisselen.',
                   31052: 'Gekozen profiel: {0}', 31053: 'Profiel {0}'}
        plugin.ADDON.getLocalizedString.side_effect = strings.__getitem__
        return plugin, client

    def test_one_profile_displays_name_without_resetting_selection(self):
        plugin, client = self.setup_plugin([{'uid': 'one', 'username': 'Nigel'}])
        plugin.dispatch({'action': 'profiles'})
        plugin.xbmcgui.Dialog.return_value.ok.assert_called_once_with(
            'Profiel wisselen', 'Dit account heeft één profiel: Nigel. Je kunt daarom niet naar een ander profiel wisselen.')
        plugin.xbmcgui.Dialog.return_value.select.assert_not_called()
        plugin.xbmcgui.Dialog.return_value.notification.assert_not_called()
        plugin.save.assert_not_called()
        client.jwt.assert_called_once_with({'uid': 'user'})

    def test_cancel_preserves_selected_profile(self):
        plugin, _ = self.setup_plugin([{'uid': 'one'}, {'uid': 'two'}])
        plugin.xbmcgui.Dialog.return_value.select.return_value = -1
        plugin.choose_profile()
        plugin.save.assert_not_called()
        plugin.xbmcgui.Dialog.return_value.notification.assert_not_called()

    def test_multiple_profiles_still_switch(self):
        plugin, client = self.setup_plugin([{'uid': 'one'}, {'uid': 'two', 'username': 'Kids'}])
        plugin.xbmcgui.Dialog.return_value.select.return_value = 1
        plugin.choose_profile()
        client.jwt.assert_called_with({'uid': 'user'}, 'two')
        plugin.save.assert_any_call('profile_id', 'two')
        plugin.save.assert_any_call('profile_name', 'Kids')
        plugin.xbmcgui.Dialog.return_value.notification.assert_called_once_with('Videoland', 'Gekozen profiel: Kids')
