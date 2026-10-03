from pathlib import Path
import sys
p=Path(sys.argv[1])/"app"/"src"/"main.py"
s=p.read_text(encoding="utf-8-sig")
old='''    def _speech_state(self, code, label):\n        try: self.speech_service._emit_state(str(code), str(label))\n        except Exception: pass\n'''
new='''    def _speech_state(self, code, label):\n        code,label=str(code),str(label)\n        try:\n            if tuple(self.speech_service.current_state() or ())==(code,label): return False\n            self.speech_service._emit_state(code,label); return True\n        except Exception: return False\n'''
if old not in s: raise RuntimeError('state anchor')
s=s.replace(old,new,1)
s=s.replace('if self._speech_waiting_brain:\n                QTimer.singleShot(0,lambda:self._speech_state("thinking","小美丽正在想"))','if self._speech_waiting_brain and str(code or "")!="thinking":\n                QTimer.singleShot(0,lambda:self._speech_state("thinking","小美丽正在想"))',1)
p.write_text(s,encoding="utf-8",newline="\n")
