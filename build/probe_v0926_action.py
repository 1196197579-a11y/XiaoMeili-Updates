from pathlib import Path
import re,sys
p=Path(sys.argv[1])/"app/src/main.py"
s=p.read_text(encoding="utf-8")
terms=['QPushButton("测试")',"QPushButton('测试')","测试状态","def _test","def test_","restore_defaults","全部清空","移除选中"]
for term in terms:
    print("\n===TERM",term,"===")
    pos=0
    count=0
    while True:
        i=s.find(term,pos)
        if i<0 or count>=20: break
        print("---",i,"---")
        print(s[max(0,i-1800):i+4500])
        pos=i+len(term); count+=1
