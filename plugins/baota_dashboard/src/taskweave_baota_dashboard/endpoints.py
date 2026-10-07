"""Chinese LinuxPanel-11.7.0 fixed profile; no caller-provided routes or operations."""
from dataclasses import dataclass, field
from typing import Mapping

PROFILE = 'bt-linux-11.7.0'
SUPPORTED_VERSION = '11.7.0'

@dataclass(frozen=True)
class EndpointSpec:
    path: str
    action: str
    fields: tuple[str, ...] = ()
    response_kind: str = 'object'
    fixed_params: Mapping[str, str] = field(default_factory=dict)
    method: str = 'POST'
    profile: str = PROFILE


def endpoint(path,action,fields='',kind='object',**fixed):
    return EndpointSpec('/'+path,action,tuple(fields.split()),kind,fixed)

ENDPOINTS = {
    'system': endpoint('system','GetSystemTotal'),
    'environment': endpoint('system','GetConcifInfo'),
    'software': endpoint('ajax','GetSoftList',kind='array'),
    'plugins': endpoint('plugin','get_soft_list','p row query',type='-1'),
    'php_versions': endpoint('site','GetPHPVersion','all s_type',kind='array'),
    'sites': endpoint('data','getData','p limit search',table='sites',type='-1'),
    'create_site': endpoint('site','AddSite','webname path type version port type_id ps ftp sql ftp_username ftp_password datauser datapassword codeing'),
    'site_path': endpoint('site','SetPath','id path'),
    'run_path': endpoint('site','SetSiteRunPath','id runPath'),
    'site_run_path': endpoint('site','GetSiteRunPath','id'),
    'index': endpoint('site','SetIndex','id Index'),
    'remark': endpoint('data','setPs','id ps',table='sites'),
    'start_site': endpoint('site','SiteStart','id name'),
    'stop_site': endpoint('site','SiteStop','id name'),
    'domains': endpoint('data','getData','p limit search',table='domain'),
    'add_domain': endpoint('site','AddDomain','id webname domain'),
    'remove_domain': endpoint('site','DelDomain','id webname domain port'),
    'file': endpoint('files','GetFileBody','path'),
    'save_file': endpoint('files','SaveFileBody','path data encoding st_mtime'),
    'set_php': endpoint('site','SetPHPVersion','siteName version'),
    'site_php': endpoint('site','GetSitePHPVersion','siteName'),
    'service': endpoint('system','ServiceAdmin','name type'),
    'databases': endpoint('data','getData','p limit search sid',table='databases'),
    'create_database': endpoint('database','AddDatabase','sid name db_user password address codeing ps pid'),
    'database_password': endpoint('database','ResDatabasePassword','id name data_name password'),
    'database_access': endpoint('database','GetDatabaseAccess','name'),
    'set_database_access': endpoint('database','SetDatabaseAccess','name access'),
    'delete_database': endpoint('database','DeleteDatabase','id name'),
    'certificate': endpoint('site','GetSSL','siteName'),
    'deploy_certificate': endpoint('site','SetSSL','siteName key csr'),
    'request_certificate': endpoint('acme','apply_cert_api','id domains auth_type auth_to auto_wildcard ca'),
    'renew_certificate': endpoint('acme','renew_cert','index'),
    'https_on': endpoint('site','SetSSLConf','siteName'),
    'https_off': endpoint('site','CloseSSLConf','siteName'),
    'redirect_on': endpoint('site','HttpToHttps','siteName'),
    'redirect_off': endpoint('site','CloseToHttps','siteName'),
    'site_backup': endpoint('site','ToBackup','id'),
    'database_backup': endpoint('database','ToBackup','id'),
    'site_backups': endpoint('data','getData','search p limit',table='backup',type='0'),
    'database_backups': endpoint('database','GetBackup','p limit search'),
    'restore_site': endpoint('files','UnZip','sfile dfile'),
    'restore_database': endpoint('database','InputSql','name file'),
    'database_info': endpoint('database','GetInfo','db_name'),
    'tasks': endpoint('task','get_task_lists','task_id num status',kind='array'),
    'access_log': endpoint('site','GetSiteLogs','siteName'),
    'error_log': endpoint('site','get_site_errlog','siteName'),
    'file_attributes': endpoint('files','get_file_attribute','filename'),
    'directory': endpoint('files','GetDirNew','path p showRow search'),
}
# Primary source route only allows GET. Authentication uses common.local/get_input
# (request.args included). Signed query tokens are ephemeral; api secret never in URL.
DOWNLOAD = EndpointSpec('/download','',('filename',),'binary',method='GET')
