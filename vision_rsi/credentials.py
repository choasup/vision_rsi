"""Read credentials locally without copying them into configuration or reports."""
import os


def _windows_user_key(name):
    if os.name!='nt':return None
    import winreg
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER,'Environment') as registry:
            value,_=winreg.QueryValueEx(registry,name)
            return value if isinstance(value,str) and value else None
    except OSError:return None


def read_key(name):
    if not isinstance(name,str) or not name or len(name)>256 or '\x00' in name:
        return None,'missing'
    value=os.environ.get(name)
    if value:return value,'process_environment'
    value=_windows_user_key(name)
    return (value,'windows_user_environment') if value else (None,'missing')
