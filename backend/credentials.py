"""Windows Credential Manager; JSON contains references, never raw API keys."""
from __future__ import annotations
import ctypes
from ctypes import wintypes
import os
import re


class WindowsVault:
    def __init__(self, namespace):
        self.namespace = namespace

    def _target(self, provider):
        if provider not in ('openai', 'anthropic', 'google'):
            raise ValueError('지원하지 않는 AI 제공사입니다.')
        return f'AIDC-ATLAS:{self.namespace}:{provider}'

    def _api(self):
        if os.name != 'nt':
            raise ValueError('이 PC에서는 환경변수 참조 연결을 사용하세요. Windows 보안 저장소는 Windows에서만 지원됩니다.')
        class Credential(ctypes.Structure):
            _fields_ = [('Flags', wintypes.DWORD), ('Type', wintypes.DWORD),
                        ('TargetName', wintypes.LPWSTR), ('Comment', wintypes.LPWSTR),
                        ('LastWritten', wintypes.FILETIME), ('CredentialBlobSize', wintypes.DWORD),
                        ('CredentialBlob', ctypes.POINTER(ctypes.c_ubyte)), ('Persist', wintypes.DWORD),
                        ('AttributeCount', wintypes.DWORD), ('Attributes', ctypes.c_void_p),
                        ('TargetAlias', wintypes.LPWSTR), ('UserName', wintypes.LPWSTR)]
        api = ctypes.WinDLL('Advapi32.dll', use_last_error=True)
        api.CredWriteW.argtypes = [ctypes.POINTER(Credential), wintypes.DWORD]
        api.CredWriteW.restype = wintypes.BOOL
        api.CredReadW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD, ctypes.POINTER(ctypes.POINTER(Credential))]
        api.CredReadW.restype = wintypes.BOOL
        api.CredDeleteW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD]
        api.CredDeleteW.restype = wintypes.BOOL
        api.CredFree.argtypes = [ctypes.c_void_p]
        return api, Credential

    def write(self, provider, secret):
        api, Credential = self._api()
        encoded = secret.encode('utf-16-le')
        if len(encoded) > 2560:
            raise ValueError('API 키 길이가 Windows 보안 저장소 한도를 초과했습니다.')
        blob = (ctypes.c_ubyte * len(encoded)).from_buffer_copy(encoded)
        record = Credential(Type=1, TargetName=self._target(provider), CredentialBlobSize=len(encoded),
                            CredentialBlob=blob, Persist=2, UserName='AIDC ATLAS')
        if not api.CredWriteW(ctypes.byref(record), 0):
            raise ValueError('Windows 자격 증명 저장에 실패했습니다. 이 PC의 보안 정책을 확인하세요.')

    def read(self, provider):
        api, Credential = self._api()
        pointer = ctypes.POINTER(Credential)()
        if not api.CredReadW(self._target(provider), 1, 0, ctypes.byref(pointer)):
            if ctypes.get_last_error() == 1168:  # ERROR_NOT_FOUND
                return None
            raise ValueError('Windows 자격 증명을 읽지 못했습니다. 이 PC의 보안 정책과 사용자 로그인을 확인하세요.')
        try:
            record = pointer.contents
            return ctypes.string_at(record.CredentialBlob, record.CredentialBlobSize).decode('utf-16-le')
        finally:
            api.CredFree(pointer)

    def delete(self, provider):
        api, _ = self._api()
        if not api.CredDeleteW(self._target(provider), 1, 0) and ctypes.get_last_error() != 1168:
            raise ValueError('Windows 자격 증명 삭제에 실패했습니다.')


def env_name(reference):
    if not isinstance(reference, str) or not re.fullmatch(r'env:ATLAS_AI_(OPENAI|ANTHROPIC|GOOGLE)_KEY', reference):
        raise ValueError('AI 환경변수는 env:ATLAS_AI_OPENAI_KEY 등 전용 참조만 허용합니다.')
    return reference[4:]


def delete_environment(reference):
    """Explicit action: only the selected app-specific process/HKCU variable.

    Does not edit .env files, machine variables, shell profiles or other apps.
    """
    name = env_name(reference)
    persistent = False
    if os.name == 'nt':
        import winreg
        try:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, 'Environment', 0, winreg.KEY_SET_VALUE) as key:
                try:
                    winreg.DeleteValue(key, name)
                    persistent = True
                except FileNotFoundError:
                    pass
        except FileNotFoundError:
            pass
    process = os.environ.pop(name, None) is not None
    return {'process_variable_deleted': process, 'user_variable_deleted': persistent,
            'other_processes_may_retain_copy': True, 'provider_key_revoked': False}
