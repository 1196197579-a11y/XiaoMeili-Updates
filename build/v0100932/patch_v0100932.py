# -*- coding: utf-8 -*-
from pathlib import Path
import py_compile, sys

root = Path(sys.argv[1]).resolve()
src = root / 'app' / 'src'
main = src / 'main.py'
diag_old = src / 'resource_diagnostic_v0100931.py'
diag_new = src / 'resource_diagnostic_v0100932.py'


def rd(p): return p.read_text(encoding='utf-8-sig')
def wr(p, s): p.write_text(s, encoding='utf-8', newline='\n')
def rep(s, a, b, name, count=1):
    if a not in s:
        raise RuntimeError(f'missing patch anchor: {name}')
    return s.replace(a, b, count)

# ---------- main.py ----------
s = rd(main)
if 'APP_VERSION = "0.10.0.9.3.1"' not in s:
    raise RuntimeError('V0.10.0.9.3.1 baseline required')
s = rep(s,
        'from resource_diagnostic_v0100931 import ResourceDiagnosticRunnerV2',
        'from resource_diagnostic_v0100932 import ResourceDiagnosticRunnerV2',
        'resource diagnostic import')
s = rep(s,
        'APP_NAME = "小美丽 V0.10.0.9.3.1｜Automatic Resource Diagnostic 2.0 Fix"',
        'APP_NAME = "小美丽 V0.10.0.9.3.2｜Automatic Resource Diagnostic 2.0 WAV Fix"',
        'app name')
s = rep(s, 'APP_VERSION = "0.10.0.9.3.1"', 'APP_VERSION = "0.10.0.9.3.2"', 'app version')
s = rep(s, 'APP_UPDATE_VERSION = "0.10.0.9.3.1"', 'APP_UPDATE_VERSION = "0.10.0.9.3.2"', 'update version')
s = s.replace('cfg["config_version"] = max(33, int(cfg.get("config_version", 0) or 0))',
              'cfg["config_version"] = max(34, int(cfg.get("config_version", 0) or 0))')
s = s.replace('cfg["config_version"] = 33', 'cfg["config_version"] = 34')
wr(main, s)

# ---------- diagnostic ----------
if not diag_old.is_file():
    raise RuntimeError('V0.10.0.9.3.1 diagnostic module missing')
d = rd(diag_old)
d = d.replace('XiaoMeili V0.10.0.9.3.1 fully automatic resource diagnostic 2.0 fix.',
              'XiaoMeili V0.10.0.9.3.2 fully automatic resource diagnostic 2.0 WAV fix.')
d = d.replace('app_version="0.10.0.9.3.1"', 'app_version="0.10.0.9.3.2"')

# The wave module only accepts r/rb/w/wb. Preserve no-overwrite semantics by
# explicitly refusing an existing path, then create with wb and verify it.
old = '''    def _make_test_wav(self, path):
        sample_rate = 16000
        seconds = 5.2
        pcm = array("h")
        for i in range(int(sample_rate * seconds)):
            t = i / sample_rate
            if t < 0.55 or t > 4.65:
                value = 0.0
            else:
                local = t - 0.55
                syllable = int(local / 0.34)
                f0 = 135.0 + (syllable % 5) * 17.0
                env = max(0.0, math.sin(math.pi * ((local % 0.34) / 0.34)))
                voiced = 0.55 * math.sin(2 * math.pi * f0 * t) + 0.24 * math.sin(2 * math.pi * f0 * 2 * t) + 0.12 * math.sin(2 * math.pi * (520 + 35 * (syllable % 4)) * t)
                value = 0.27 * env * voiced
            pcm.append(int(max(-1.0, min(1.0, value)) * 32767))
        with wave.open(str(path), "xb") as wf:
            wf.setnchannels(1); wf.setsampwidth(2); wf.setframerate(sample_rate); wf.writeframes(pcm.tobytes())
        return path
'''
new = '''    def _make_test_wav(self, path):
        path = Path(path)
        if path.exists():
            raise FileExistsError(f"诊断测试音频已存在，拒绝覆盖: {path.name}")
        sample_rate = 16000
        seconds = 5.2
        pcm = array("h")
        for i in range(int(sample_rate * seconds)):
            t = i / sample_rate
            if t < 0.55 or t > 4.65:
                value = 0.0
            else:
                local = t - 0.55
                syllable = int(local / 0.34)
                f0 = 135.0 + (syllable % 5) * 17.0
                env = max(0.0, math.sin(math.pi * ((local % 0.34) / 0.34)))
                voiced = 0.55 * math.sin(2 * math.pi * f0 * t) + 0.24 * math.sin(2 * math.pi * f0 * 2 * t) + 0.12 * math.sin(2 * math.pi * (520 + 35 * (syllable % 4)) * t)
                value = 0.27 * env * voiced
            pcm.append(int(max(-1.0, min(1.0, value)) * 32767))
        with wave.open(str(path), "wb") as wf:
            wf.setnchannels(1)
            wf.setsampwidth(2)
            wf.setframerate(sample_rate)
            wf.writeframes(pcm.tobytes())
        with wave.open(str(path), "rb") as wf:
            if wf.getnchannels() != 1 or wf.getsampwidth() != 2 or wf.getframerate() != sample_rate or wf.getnframes() <= 0:
                raise RuntimeError("诊断测试音频自检失败")
        self._event("wav_probe_pass", rate=sample_rate, channels=1, sample_width=2, frames=len(pcm))
        return path
'''
d = rep(d, old, new, 'safe WAV creation')

# Generate and validate the ASR fixture during preflight, before the user waits
# through the 60-second baseline. The same verified file is reused in stage 4.
old = '''            self._set_stage("preflight",1,"启动前快速自检：事件、CPU与GPU采样接口")
            self._preflight_self_test()
            gpu_thread.start(); sampler.start(); self._sleep(1.0)
            self._set_stage("baseline",2,f"1/10 纯待机基线：记录 {BASELINE_SECONDS} 秒")
'''
new = '''            self._set_stage("preflight",1,"启动前快速自检：事件、CPU、GPU与ASR测试音频")
            self._preflight_self_test()
            wav_path = self._make_test_wav(self.session_dir / "diagnostic_input.wav")
            gpu_thread.start(); sampler.start(); self._sleep(1.0)
            self._set_stage("baseline",2,f"1/10 纯待机基线：记录 {BASELINE_SECONDS} 秒")
'''
d = rep(d, old, new, 'preflight WAV smoke')

# Do not recreate the already verified WAV later.
d = rep(d,
        '            wav_path=self._make_test_wav(self.session_dir/"diagnostic_input.wav")\n            self._set_stage("asr",27,"4/10 语音输入：FSMN-VAD + Fun-ASR-Nano-2512 自动离线测试")',
        '            self._set_stage("asr",27,"4/10 语音输入：FSMN-VAD + Fun-ASR-Nano-2512 自动离线测试")',
        'reuse preflight WAV')

# Versioned thread/session names make reports unambiguous.
d = d.replace('f"v0100931_{token}"', 'f"v0100932_{token}"')
d = d.replace('XiaoMeiliResourceSamplerV0100931', 'XiaoMeiliResourceSamplerV0100932')
d = d.replace('XiaoMeiliGpuSamplerV0100931', 'XiaoMeiliGpuSamplerV0100932')
wr(diag_new, d)

(root / 'app' / 'assets' / 'VERSION.txt').write_text('0.10.0.9.3.2\n', encoding='ascii')
(root / 'V0100932_CHANGELOG.txt').write_text('''XiaoMeili V0.10.0.9.3.2\n\n- 修复一键深度资源测试生成ASR测试WAV时使用 wave 不支持的 xb 模式而中止的问题。\n- 保留“绝不覆盖现有文件”：若诊断音频路径已存在则直接拒绝，不覆盖；创建时使用 wave 支持的 wb。\n- WAV 创建后立即以 rb 重新打开并验证 16kHz / 单声道 / 16-bit PCM / 有效帧数。\n- WAV 生成与校验提前到60秒待机之前，若异常会在启动预检阶段立即停止，不再让用户等待。\n- CI增加真实WAV往返测试、二次创建拒绝覆盖测试、模拟ASR diag_ready入口测试。\n- 继续保留V0.10.0.9.3.1的NVML无黑框GPU采集、真实CPU采样、250ms稳定采样、失败报告提示以及FullSafe。\n''', encoding='utf-8')

for p in (main, diag_new):
    py_compile.compile(str(p), doraise=True)
combined = rd(main) + rd(diag_new)
for token in [
    'APP_VERSION = "0.10.0.9.3.2"', 'resource_diagnostic_v0100932',
    'wave.open(str(path), "wb")', 'wave.open(str(path), "rb")',
    'raise FileExistsError', 'wav_probe_pass', 'diagnostic_input.wav',
    'XiaoMeiliGpuSamplerV0100932', '测试中止，已生成故障报告'
]:
    if token not in combined:
        raise RuntimeError('contract missing: ' + token)
if 'wave.open(str(path), "xb")' in combined:
    raise RuntimeError('unsupported wave xb mode still present')
print('PATCH_0100932_PASS')