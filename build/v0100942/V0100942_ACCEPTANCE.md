# V0.10.0.9.4.2 candidate

This is an unpublished candidate based on the official V0.10.0.9.4.1 source asset.

The 0% failure is reproduced by the installed 2026-10-05 03:53:06 log:
`AttributeError: 'tuple' object has no attribute 'open'` in `_open_live_journals`.
The interrupted-recovery path also called `exists()` on a tuple. Both paths now
use a single Path. Startup exceptions and independent ten-second deadlines
produce failure ZIPs and deliver a terminal failure to the UI.

The settings brain-result callback now ignores diagnostic-owned results, so
the chat page does not start a competing preview TTS task. Diagnostic actions
reject forced TTS abort and synthetic hard-silence ASR.

The packaged acceptance entry is:
`XiaoMeili.exe --resource-e2e <new-empty-run-directory>`
It starts the real AppController, opens SettingsDialog, and invokes the real
resource-test button's click signal. It uses the actual cloud key through a
temporary copy of the DPAPI-protected secret, actual cloud brain/TTS, and actual
installed ASR interpreter/model weights as read inputs. Configuration, caches,
worker scripts and reports are isolated beneath the new run directory. It does
not fabricate service results. Never distribute these private run directories.

The acceptance profile executes preflight, a short idle baseline, six real
animation changes, two whiteboard cycles, four ASR inference runs, one brain
request, natural TTS playback, external resource sampling and report generation.
The user-facing full profile keeps 60-second idle, 30 animations, 12 whiteboards,
ASR, six brain requests, eight TTS rounds, 30 chat rounds, natural playback
recovery, offline vision, combined load and 90-second cooldown.

The final bundle deliberately retains the verified V0.10.0.9.4.1 runtime DLLs
and stable launcher, with rebuilt main and monitor EXEs. The baseline update
SHA-256 is d45cf82691335317fa33e4c5bf635ce869da298787b91249bec3fa414bd73722.
Build with Python 3.12.10 and the accompanying dependency lock.

Publication remains gated on three consecutive packaged-app successes, a
packaged-host crash ZIP, NDM, FullSafe, runtime and settings self-tests, and
public downloads of both candidate assets matching local SHA-256. Public
promotion and latest_safe.json must remain unchanged until those checks pass.
