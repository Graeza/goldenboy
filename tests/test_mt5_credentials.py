import unittest
from unittest.mock import Mock, patch

from core.mt5_credentials import get_mt5_credentials
from core.provider import ProviderError


class CredentialTests(unittest.TestCase):
    def read(self, profile='DEMO', values=('12345', 'Broker', 'test-secret')):
        backend = Mock()
        backend.get_password.side_effect = values
        return backend

    def test_tradlab_services_and_entries(self):
        for profile, service in [('DEMO', 'mt5'), ('LIVE', 'mt5_live')]:
            backend = self.read()
            with patch('core.mt5_credentials.settings.MT5_ACCOUNT_PROFILE', profile), patch('core.mt5_credentials.importlib.import_module', return_value=backend):
                self.assertEqual(get_mt5_credentials(), (12345, 'Broker', 'test-secret', profile))
            self.assertEqual([call.args for call in backend.get_password.call_args_list],
                             [(service, 'login'), (service, 'server'), (service, 'password')])

    def test_missing_entries_and_invalid_login(self):
        for values in [(None, 'Broker', 'secret'), ('123', None, 'secret'), ('123', 'Broker', None), ('invalid', 'Broker', 'secret'), ('0', 'Broker', 'secret')]:
            with self.subTest(values=values), patch('core.mt5_credentials.settings.MT5_ACCOUNT_PROFILE', 'DEMO'), patch('core.mt5_credentials.importlib.import_module', return_value=self.read(values=values)):
                with self.assertRaises(ProviderError):
                    get_mt5_credentials()

    def test_backend_error_does_not_expose_details(self):
        backend = self.read()
        backend.get_password.side_effect = RuntimeError('private-backend-details')
        with patch('core.mt5_credentials.settings.MT5_ACCOUNT_PROFILE', 'DEMO'), patch('core.mt5_credentials.importlib.import_module', return_value=backend):
            with self.assertRaises(ProviderError) as caught:
                get_mt5_credentials()
            self.assertNotIn('private-backend-details', str(caught.exception))
            self.assertTrue(caught.exception.__suppress_context__)

    def test_invalid_profile_never_reads_keyring(self):
        with patch('core.mt5_credentials.settings.MT5_ACCOUNT_PROFILE', 'OTHER'), patch('core.mt5_credentials.importlib.import_module') as loader:
            with self.assertRaises(ProviderError):
                get_mt5_credentials()
            loader.assert_not_called()

    def test_missing_package_has_setup_message(self):
        with patch('core.mt5_credentials.settings.MT5_ACCOUNT_PROFILE', 'DEMO'), patch('core.mt5_credentials.importlib.import_module', side_effect=ImportError):
            with self.assertRaisesRegex(ProviderError, 'requirements-mt5'):
                get_mt5_credentials()
