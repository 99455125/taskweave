"""Installed entry points and strict declarations for optional devops plugins."""
from importlib.metadata import entry_points
import unittest
from taskweave.core.validation import TaskError, validate
from taskweave.plugins.registry import Registry


class DevopsDiscoveryTests(unittest.TestCase):
    def test_process_entry_point_and_contract(self):
        entries = list(entry_points(group='taskweave.plugins'))
        if not any(entry.name=='process' for entry in entries):
            self.skipTest('process extra not installed')
        factory = next(entry.load() for entry in entries if entry.name == 'process')
        plugin = factory()
        registry = Registry([plugin])
        self.assertEqual(registry.versions, {'process': '0.1.0'})
        self.assertEqual(set(registry.actions), {'process.check_environment', 'process.run', 'process.collect_artifacts'})
        self.assertFalse(registry.providers)
        self.assertIn('process.file', registry.handlers)
        self.assertIn('process.command_failure', registry.handlers)
        self.assertEqual(registry.actions['process.run'].spec.effect, 'WRITE')
        self.assertFalse(registry.actions['process.run'].spec.retry_safe)
        self.assertGreaterEqual(registry.actions['process.run'].spec.timeout_ms, 1800000)
        registry.contributions(list(registry.actions))
        for action in registry.actions.values():
            with self.subTest(action=action.spec.id), self.assertRaises(TaskError):
                validate({'unexpected': True}, action.spec.input_schema)
        self.assertIn('process.environment', plugin.authoring(list(registry.actions)).context_provider_ids)

    def test_ssh_entry_point_and_contract(self):
        entries=list(entry_points(group='taskweave.plugins'))
        if not any(entry.name=='ssh' for entry in entries):
            self.skipTest('ssh extra is not installed; use --extra ssh for its discovery check')
        factory=next(entry.load() for entry in entries if entry.name=='ssh')
        plugin=factory()
        registry=Registry([plugin])
        self.assertEqual(registry.versions,{'ssh':'0.1.0'})
        self.assertEqual(set(registry.actions),{'ssh.'+name for name in ('check_connection','exec','run_script','stat','list_directory','read_file','read_logs','checksum','upload','download','mkdir','move','remove')})
        self.assertEqual(set(registry.providers),{'ssh.connection'})
        self.assertEqual(set(registry.handlers),{'ssh.file','ssh.command_failure','ssh.transfer_failure'})
        self.assertEqual(set(registry.tools),{'ssh.inspect_server'})
        registry.contributions(list(registry.actions))
        for name,action in registry.actions.items():
            with self.subTest(action=name),self.assertRaises(TaskError):
                validate({'unexpected':True},action.spec.input_schema)
            self.assertEqual(action.spec.resource_ids,('ssh.connection',))
            if name in ('ssh.exec','ssh.run_script','ssh.upload','ssh.mkdir','ssh.move','ssh.remove'):
                self.assertEqual(action.spec.effect,'WRITE'); self.assertFalse(action.spec.retry_safe)
        self.assertIn('ssh.server',plugin.authoring(list(registry.actions)).context_provider_ids)

    def test_baota_entry_point_and_contract(self):
        entries=list(entry_points(group='taskweave.plugins'))
        if not any(entry.name=='baota_dashboard' for entry in entries):
            self.skipTest('baota_dashboard extra not installed')
        plugin=next(entry.load() for entry in entries if entry.name=='baota_dashboard')()
        registry=Registry([plugin])
        self.assertEqual(registry.versions,{'baota_dashboard':'0.1.0'})
        self.assertEqual(len(registry.actions),33)
        self.assertEqual(set(registry.providers),{'baota_dashboard.connection'})
        self.assertEqual(set(registry.handlers),{'baota_dashboard.json','baota_dashboard.operation_failure'})
        self.assertEqual(set(registry.tools),{'baota_dashboard.inspect_sites'})
        registry.contributions(list(registry.actions))
        for action in registry.actions.values():
            self.assertEqual(action.spec.resource_ids,('baota_dashboard.connection',))
            with self.assertRaises(TaskError): validate({'unexpected':True},action.spec.input_schema)
            if action.spec.effect=='WRITE': self.assertFalse(action.spec.retry_safe)
        self.assertIn('baota_dashboard.site',plugin.authoring(list(registry.actions)).context_provider_ids)

    def test_wordpress_entry_point_and_contract(self):
        entries=list(entry_points(group='taskweave.plugins'))
        if not any(entry.name=='wordpress' for entry in entries):
            self.skipTest('wordpress extra not installed')
        plugin=next(entry.load() for entry in entries if entry.name=='wordpress')()
        registry=Registry([plugin])
        self.assertEqual(registry.versions,{'wordpress':'0.1.0'})
        self.assertEqual(len(registry.actions),53)
        self.assertEqual(set(registry.providers),{'wordpress.site'})
        self.assertEqual(set(registry.handlers),{'wordpress.file','wordpress.json','wordpress.operation_failure'})
        registry.contributions(list(registry.actions))
        for action in registry.actions.values():
            self.assertEqual(action.spec.resource_ids,('wordpress.site',))
            with self.assertRaises(TaskError): validate({'unexpected':True},action.spec.input_schema)
            if action.spec.effect=='WRITE': self.assertFalse(action.spec.retry_safe)

    def test_uniapp_entry_point_and_contract(self):
        entries=list(entry_points(group='taskweave.plugins'))
        self.assertTrue(any(entry.name=='uniapp' for entry in entries),'Install uniapp extra for scoped discovery')
        plugin=next(entry.load() for entry in entries if entry.name=='uniapp')();registry=Registry([plugin])
        self.assertEqual(registry.versions,{'uniapp':'0.1.0'})
        self.assertEqual(set(registry.actions),{'uniapp.'+n for n in ('inspect','build','check_artifact','run_tests','collect_report')})
        self.assertEqual(set(registry.providers),{'uniapp.project'});self.assertEqual(set(registry.handlers),{'uniapp.file','uniapp.json','uniapp.operation_failure'})
        registry.contributions(list(registry.actions))
        for name,action in registry.actions.items():
            self.assertEqual(action.spec.resource_ids,('uniapp.project',))
            with self.assertRaises(TaskError):validate({'unexpected':True},action.spec.input_schema)
            if name in ('uniapp.build','uniapp.run_tests'):self.assertEqual(action.spec.effect,'WRITE');self.assertFalse(action.spec.retry_safe)
        self.assertIn('uniapp.project',plugin.authoring(list(registry.actions)).context_provider_ids)

    def test_wechat_entry_point_and_contract(self):
        entries=list(entry_points(group='taskweave.plugins'))
        plugin=next(entry.load() for entry in entries if entry.name=='wechat_dev')()
        registry=Registry([plugin])
        from tests.test_wechat_dev import NAMES,MINIMUM,RELEASE_NAMES
        self.assertEqual(registry.versions,{'wechat_dev':'0.1.0'})
        self.assertEqual(set(registry.actions),{'wechat_dev.'+name for name in NAMES+RELEASE_NAMES})
        self.assertEqual(set(registry.providers),{'wechat_dev.simulator'})
        self.assertEqual(set(registry.handlers),{'wechat_dev.file','wechat_dev.image','wechat_dev.json','wechat_dev.operation_failure'})
        self.assertIn('wechat_dev.screenshot',registry.views)
        registry.contributions(list(registry.actions))
        for action in registry.actions.values():
            valid=MINIMUM[action.name];validate(valid,action.spec.input_schema)
            with self.subTest(action=action.spec.id),self.assertRaises(TaskError):validate({**valid,'unexpected':True},action.spec.input_schema)
            if action.spec.effect=='WRITE':self.assertFalse(action.spec.retry_safe)

# Approved design action tables: process39-41/ssh51-56/baota66-71/WP85-94/uniapp106-110/wechat120-127.
APPROVED_DEVOPS_ACTIONS = {'process': ['process.check_environment', 'process.run', 'process.collect_artifacts'],
 'ssh': ['ssh.check_connection',
         'ssh.exec',
         'ssh.run_script',
         'ssh.stat',
         'ssh.list_directory',
         'ssh.read_file',
         'ssh.read_logs',
         'ssh.checksum',
         'ssh.upload',
         'ssh.download',
         'ssh.mkdir',
         'ssh.move',
         'ssh.remove'],
 'baota_dashboard': ['baota_dashboard.check_connection',
                     'baota_dashboard.system_status',
                     'baota_dashboard.list_software',
                     'baota_dashboard.list_php_versions',
                     'baota_dashboard.list_sites',
                     'baota_dashboard.create_site',
                     'baota_dashboard.configure_site',
                     'baota_dashboard.set_site_status',
                     'baota_dashboard.list_domains',
                     'baota_dashboard.add_domain',
                     'baota_dashboard.remove_domain',
                     'baota_dashboard.get_site_config',
                     'baota_dashboard.set_site_config',
                     'baota_dashboard.get_rewrite',
                     'baota_dashboard.set_rewrite',
                     'baota_dashboard.set_php_version',
                     'baota_dashboard.check_config',
                     'baota_dashboard.reload_service',
                     'baota_dashboard.list_databases',
                     'baota_dashboard.create_database',
                     'baota_dashboard.set_database_credentials',
                     'baota_dashboard.set_database_access',
                     'baota_dashboard.delete_database',
                     'baota_dashboard.get_certificate',
                     'baota_dashboard.deploy_certificate',
                     'baota_dashboard.request_certificate',
                     'baota_dashboard.renew_certificate',
                     'baota_dashboard.set_https',
                     'baota_dashboard.create_backup',
                     'baota_dashboard.list_backups',
                     'baota_dashboard.restore_backup',
                     'baota_dashboard.task_status',
                     'baota_dashboard.read_logs'],
 'wordpress': ['wordpress.check_environment',
               'wordpress.is_installed',
               'wordpress.core_download',
               'wordpress.core_install',
               'wordpress.core_update',
               'wordpress.verify_checksums',
               'wordpress.config_create',
               'wordpress.config_get',
               'wordpress.config_set',
               'wordpress.option_get',
               'wordpress.option_set',
               'wordpress.set_permalink_structure',
               'wordpress.list_themes',
               'wordpress.install_theme',
               'wordpress.activate_theme',
               'wordpress.update_theme',
               'wordpress.delete_theme',
               'wordpress.list_plugins',
               'wordpress.install_plugin',
               'wordpress.activate_plugin',
               'wordpress.deactivate_plugin',
               'wordpress.update_plugin',
               'wordpress.delete_plugin',
               'wordpress.list_posts',
               'wordpress.create_post',
               'wordpress.update_post',
               'wordpress.delete_post',
               'wordpress.list_terms',
               'wordpress.create_term',
               'wordpress.update_term',
               'wordpress.delete_term',
               'wordpress.list_menus',
               'wordpress.create_menu',
               'wordpress.delete_menu',
               'wordpress.add_menu_item',
               'wordpress.update_menu_item',
               'wordpress.delete_menu_item',
               'wordpress.list_media',
               'wordpress.import_media',
               'wordpress.update_media',
               'wordpress.delete_media',
               'wordpress.list_users',
               'wordpress.create_user',
               'wordpress.set_user_role',
               'wordpress.set_user_password',
               'wordpress.delete_user',
               'wordpress.db_export',
               'wordpress.db_import',
               'wordpress.backup',
               'wordpress.restore',
               'wordpress.search_replace',
               'wordpress.cache_flush',
               'wordpress.set_maintenance_mode'],
 'uniapp': ['uniapp.inspect',
            'uniapp.build',
            'uniapp.check_artifact',
            'uniapp.run_tests',
            'uniapp.collect_report'],
 'wechat_dev': ['wechat_dev.check_environment',
                'wechat_dev.connect',
                'wechat_dev.disconnect',
                'wechat_dev.current_page',
                'wechat_dev.page_stack',
                'wechat_dev.navigate',
                'wechat_dev.observe',
                'wechat_dev.get_element',
                'wechat_dev.get_page_data',
                'wechat_dev.tap',
                'wechat_dev.input',
                'wechat_dev.scroll',
                'wechat_dev.touch',
                'wechat_dev.call_component_method',
                'wechat_dev.assert_page',
                'wechat_dev.assert_element',
                'wechat_dev.assert_page_data',
                'wechat_dev.wait_for',
                'wechat_dev.get_storage',
                'wechat_dev.set_storage',
                'wechat_dev.remove_storage',
                'wechat_dev.clear_storage',
                'wechat_dev.mock_method',
                'wechat_dev.restore_mock',
                'wechat_dev.screenshot',
                'wechat_dev.read_logs', 'wechat_dev.preview', 'wechat_dev.upload']}

class ApprovedDevopsSetTests(unittest.TestCase):
    def test_all_declared_capabilities_are_registered_and_valid(self):
        from jsonschema import Draft202012Validator
        entries={entry.name:entry for entry in entry_points(group="taskweave.plugins")}
        self.assertTrue(set(APPROVED_DEVOPS_ACTIONS)<=set(entries),"all six extras are required; no skips")
        registry=Registry([entries[name].load()() for name in APPROVED_DEVOPS_ACTIONS])
        expected={action for names in APPROVED_DEVOPS_ACTIONS.values() for action in names}
        self.assertEqual(set(registry.actions),expected)
        self.assertEqual(len(expected),135)
        self.assertEqual(registry.versions,{name:"0.1.0" for name in APPROVED_DEVOPS_ACTIONS})
        for name,action in registry.actions.items():
            with self.subTest(action=name):
                self.assertEqual(action.spec.id,name);Draft202012Validator.check_schema(action.spec.input_schema);Draft202012Validator.check_schema(action.spec.output_schema)
                self.assertEqual(action.spec.input_schema.get("additionalProperties"),False)
                self.assertTrue(set(action.spec.resource_ids)<=set(registry.providers))
        registry.contributions(sorted(expected))
        for handler in registry.handlers.values():
            self.assertEqual(handler.schema()["version"],1)
        self.assertEqual(set(registry.providers),{"ssh.connection","baota_dashboard.connection","wordpress.site","uniapp.project","wechat_dev.simulator"})
        for plugin in registry.plugins:
            self.assertTrue(plugin.authoring(sorted(expected)).instructions)
