# -*- coding: utf-8 -*-
from pathlib import Path
import base64
import py_compile
import sys

if len(sys.argv) != 3:
    raise SystemExit("usage: patch_v0100.py <source_root> <repo_root>")

root=Path(sys.argv[1]).resolve()
repo=Path(sys.argv[2]).resolve()
main=root/"app/src/main.py"
speech=root/"app/src/speech_input.py"
version_file=root/"app/assets/VERSION.txt"
assets=root/"app/assets"
s=main.read_text(encoding="utf-8")

if 'APP_VERSION = "0.9.2.8"' not in s:
    raise RuntimeError("V0.10.0 expected V0.9.2.8 base")

# Bundle only the two small, self-contained V0.10.0 visual resources.
# They are build assets, never written into user-data directories.
# The ability-form PNG uses a verified hex payload so a malformed Base64 file
# can never silently reach the release package.
ability_hex=repo/"build/v0100/assets/ability_form.png.hex"
if not ability_hex.is_file():
    raise RuntimeError(f"V0.10.0 ability-form asset source missing: {ability_hex}")
hex_text="".join(ability_hex.read_text(encoding="ascii").split())
if len(hex_text) % 2:
    raise RuntimeError("V0.10.0 ability-form hex payload has odd length")
try:
    ability_raw=bytes.fromhex(hex_text)
except ValueError as exc:
    raise RuntimeError(f"V0.10.0 ability-form hex payload invalid: {exc}") from exc
if not ability_raw.startswith(b"\\x89PNG\\r\\n\\x1a\\n") or len(ability_raw) < 2000:
    raise RuntimeError("V0.10.0 ability-form PNG payload failed signature/size validation")
(assets/"ability_form.png").write_bytes(ability_raw)

font_src=repo/"build/v0100/assets/MaokenAbilitySubset.otf.b64"
if not font_src.is_file():
    raise RuntimeError(f"V0.10.0 font source missing: {font_src}")
font_text="".join(font_src.read_text(encoding="ascii").split())
try:
    font_raw=base64.b64decode(font_text, validate=True)
except Exception as exc:
    raise RuntimeError(f"V0.10.0 font Base64 payload invalid: {exc}") from exc
if len(font_raw) < 4000 or not font_raw.startswith(b"OTTO"):
    raise RuntimeError("V0.10.0 font payload failed signature/size validation")
(assets/"MaokenAbilitySubset.otf").write_bytes(font_raw)

# Version.
s=s.replace('APP_VERSION = "0.9.2.8"','APP_VERSION = "0.10.0"',1)
s=s.replace('APP_NAME = "小美丽 V0.9.2.8｜Voice Interaction"','APP_NAME = "小美丽 V0.10.0｜美丽能力侧栏"',1)
s=s.replace("自动存储清理已禁用：V0.9.2.8 不会自动删除任何文件。","自动存储清理已禁用：V0.10.0 不会自动删除任何文件。",1)

# Dedicated imports are intentionally explicit so the sidebar remains isolated
# from the existing pet / vision / speech implementation.
import_anchor="from pathlib import Path"
extra_imports='''from PySide6.QtCore import QVariantAnimation, QRectF, QPointF, QEasingCurve
from PySide6.QtGui import QPen, QBrush, QFont, QColor, QFontDatabase, QPainter, QPixmap
'''
if extra_imports.strip() not in s:
    if import_anchor not in s:
        raise RuntimeError("V0.10.0 import anchor missing")
    s=s.replace(import_anchor,import_anchor+"\n"+extra_imports,1)

pet_anchor="class PetWindow(QWidget):"
if pet_anchor not in s:
    raise RuntimeError("V0.10.0 PetWindow anchor missing")

ability_classes=r'''
# ---------------------------------------------------------------------------
# V0.10.0 美丽能力侧栏
#
# Pure desktop-pet UI.  It does not inspect VALORANT memory, inject code,
# synthesize input, or alter the existing vision pipeline.
# ---------------------------------------------------------------------------
ABILITY_ITEMS = [
    ("ability_lock", "01", "美丽锁定"),
    ("ability_insight", "02", "美丽洞察"),
    ("ability_power2", "03", "二成功力"),
    ("ability_power5", "04", "五成功力"),
    ("ability_god", "05", "美丽之神"),
]


class AbilityFormOverlay(QWidget):
    """Static transparent ability-form art displayed only while the sidebar is open."""
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self._pix = QPixmap(resource("assets/ability_form.png"))
        self.hide()

    def paintEvent(self, event):
        if self._pix.isNull():
            return
        p=QPainter(self)
        p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)
        margin=max(2,int(round(self.width()*0.02)))
        target=QRectF(margin,margin,max(1,self.width()-2*margin),max(1,self.height()-2*margin))
        src=QRectF(self._pix.rect())
        sw=max(1.0,src.width()); sh=max(1.0,src.height())
        scale=min(target.width()/sw,target.height()/sh)
        dw,dh=sw*scale,sh*scale
        x=target.center().x()-dw/2
        y=target.bottom()-dh
        p.drawPixmap(QRectF(x,y,dw,dh),self._pix,src)
        p.end()


class AbilityNodeButton(QPushButton):
    def __init__(self, parent=None):
        super().__init__("", parent)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setToolTip("美丽能力")
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.setStyleSheet("background:transparent;border:none;")
        self._hover=False

    def enterEvent(self,event):
        self._hover=True; self.update(); super().enterEvent(event)

    def leaveEvent(self,event):
        self._hover=False; self.update(); super().leaveEvent(event)

    def paintEvent(self,event):
        p=QPainter(self); p.setRenderHint(QPainter.RenderHint.Antialiasing,True)
        c=self.rect().center(); r=max(5,min(self.width(),self.height())//2-4)
        glow=QColor(48,255,235,55 if not self._hover else 90)
        p.setPen(QPen(glow,6)); p.setBrush(Qt.BrushStyle.NoBrush); p.drawEllipse(c,r,r)
        p.setPen(QPen(QColor(113,255,244,235),2)); p.setBrush(QBrush(QColor(16,92,92,225))); p.drawEllipse(c,r,r)
        p.setPen(Qt.PenStyle.NoPen); p.setBrush(QBrush(QColor(193,255,250,255))); p.drawEllipse(c,max(2,r//3),max(2,r//3))
        p.end()


class AbilitySidebarWindow(QWidget):
    """Small neon side panel attached to the pet. No background polling when closed."""
    def __init__(self,cfg,pet):
        super().__init__(None)
        self.cfg=cfg
        self.pet=pet
        self.is_open=False
        self._closing=False
        self._reveal=0.0
        self._side="left"
        self._switch=[0.0]*len(ABILITY_ITEMS)
        self._switch_anims=[None]*len(ABILITY_ITEMS)
        self._row_rects=[]
        self._full_w=306
        self._full_h=382
        self.setWindowFlags(
            Qt.WindowType.Tool |
            Qt.WindowType.FramelessWindowHint |
            Qt.WindowType.WindowStaysOnTopHint
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground,True)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating,True)
        self.setMouseTracking(True)
        self._anim=QVariantAnimation(self)
        self._anim.valueChanged.connect(self._on_reveal)
        self._anim.finished.connect(self._on_anim_finished)
        self._follow=QTimer(self)
        self._follow.setInterval(40)
        self._follow.timeout.connect(self.sync_geometry)
        self._font_family="Microsoft YaHei UI"
        try:
            fid=QFontDatabase.addApplicationFont(resource("assets/MaokenAbilitySubset.otf"))
            if fid>=0:
                fam=QFontDatabase.applicationFontFamilies(fid)
                if fam: self._font_family=fam[0]
        except Exception:
            LOGGER.warning("V0.10.0 美丽能力字体加载失败，使用系统字体",exc_info=True)
        self.hide()

    def _scale(self):
        try: return max(0.82,min(1.32,float(self.pet.width())/280.0))
        except Exception: return 1.0

    def _metrics(self):
        sc=self._scale()
        return int(round(self._full_w*sc)),int(round(self._full_h*sc)),sc

    def _choose_side(self,full_w):
        screen=QApplication.screenAt(self.pet.frameGeometry().center()) or QApplication.primaryScreen()
        if not screen: return "left"
        area=screen.availableGeometry()
        left_space=self.pet.x()-area.left()
        right_space=area.right()-(self.pet.x()+self.pet.width())
        need=full_w+8
        if left_space>=need: return "left"
        if right_space>=need: return "right"
        return "left" if left_space>=right_space else "right"

    def sync_geometry(self):
        if not self.isVisible() and not self.is_open:
            return
        full_w,full_h,sc=self._metrics()
        self._side=self._choose_side(full_w)
        try:self.pet._ability_position_node(self._side)
        except Exception:pass
        x=self.pet.x()-full_w+12 if self._side=="left" else self.pet.x()+self.pet.width()-12
        y=int(round(self.pet.y()+self.pet.height()/2-full_h/2))
        screen=QApplication.screenAt(self.pet.frameGeometry().center()) or QApplication.primaryScreen()
        if screen:
            area=screen.availableGeometry()
            y=max(area.top()+2,min(y,area.bottom()-full_h-2))
        self.setGeometry(x,y,full_w,full_h)

    def open_panel(self):
        if self.is_open or not bool(self.cfg.get("ability_sidebar",{}).get("enabled",True)):
            return
        if bool(self.cfg.get("lock_position",False) or self.cfg.get("click_through",False)):
            return
        self.is_open=True; self._closing=False
        self._switch=[0.0]*len(ABILITY_ITEMS)
        self.sync_geometry()
        self._reveal=0.0
        self.show(); self.raise_()
        self._follow.start()
        try:self.pet._ability_apply_form_if_possible()
        except Exception:pass
        self._anim.stop(); self._anim.setDuration(260)
        self._anim.setStartValue(0.0); self._anim.setEndValue(1.0)
        self._anim.setEasingCurve(QEasingCurve.Type.InOutCubic); self._anim.start()

    def close_panel(self):
        if not self.is_open and not self.isVisible():
            return
        self.is_open=False; self._closing=True
        self._anim.stop(); self._anim.setDuration(210)
        self._anim.setStartValue(float(self._reveal)); self._anim.setEndValue(0.0)
        self._anim.setEasingCurve(QEasingCurve.Type.InOutCubic); self._anim.start()
        try:self.pet._ability_set_form_visible(False)
        except Exception:pass

    def toggle_panel(self):
        self.close_panel() if self.is_open else self.open_panel()

    def _on_reveal(self,value):
        self._reveal=max(0.0,min(1.0,float(value)))
        self.sync_geometry(); self.update()

    def _on_anim_finished(self):
        if self._closing and self._reveal<=0.001:
            self._closing=False
            self._follow.stop(); self.hide()
            try:self.pet._ability_restore_base_visuals()
            except Exception:pass

    def _body_rect(self):
        w,h=self.width(),self.height(); _,_,sc=self._metrics()
        connector=int(round(48*sc)); pad=int(round(7*sc))
        if self._side=="left":
            return QRectF(pad,pad,max(1,w-connector-pad),max(1,h-2*pad))
        return QRectF(connector,pad,max(1,w-connector-pad),max(1,h-2*pad))

    def _visible_clip(self):
        w=float(self.width()); h=float(self.height()); r=float(self._reveal)
        if self._side=="left":
            return QRectF(w*(1-r),0,w*r,h)
        return QRectF(0,0,w*r,h)

    def _draw_round_glow(self,p,rect,radius,on=False):
        glow=QColor(52,255,238,72 if on else 44)
        p.setBrush(Qt.BrushStyle.NoBrush)
        for width,alpha in ((8,22),(5,36),(2,190)):
            c=QColor(glow); c.setAlpha(alpha if not on else min(255,alpha+30))
            p.setPen(QPen(c,width))
            p.drawRoundedRect(rect,radius,radius)

    def paintEvent(self,event):
        p=QPainter(self); p.setRenderHint(QPainter.RenderHint.Antialiasing,True)
        p.setClipRect(self._visible_clip())
        body=self._body_rect(); _,_,sc=self._metrics()
        god=self._switch[4]>0.55
        self._draw_round_glow(p,body,24*sc,god)
        p.setPen(QPen(QColor(136,255,249,150),1.25*sc))
        p.setBrush(QBrush(QColor(8,64,76,195)))
        p.drawRoundedRect(body,24*sc,24*sc)

        # very restrained glass highlight
        hi=QRectF(body.left()+2,body.top()+2,body.width()-4,max(18,body.height()*0.12))
        p.setPen(Qt.PenStyle.NoPen); p.setBrush(QBrush(QColor(188,255,255,18)))
        p.drawRoundedRect(hi,20*sc,20*sc)

        # static connector: no moving light, no pulse
        mid=body.center().y()
        p.setPen(QPen(QColor(107,255,244,220),2.2*sc))
        if self._side=="left":
            a=QPointF(body.right(),mid); b=QPointF(self.width()-7*sc,mid)
        else:
            a=QPointF(body.left(),mid); b=QPointF(7*sc,mid)
        p.drawLine(a,b)
        p.setBrush(QBrush(QColor(34,112,111,240))); p.setPen(QPen(QColor(160,255,250,245),2*sc))
        p.drawEllipse(b,7*sc,7*sc)

        margin=18*sc; top=28*sc; gap=10*sc
        row_h=(body.height()-top*2-gap*4)/5.0
        self._row_rects=[]
        num_font=QFont(self._font_family); num_font.setPixelSize(max(12,int(round(18*sc))))
        text_font=QFont(self._font_family); text_font.setPixelSize(max(15,int(round(23*sc))))
        for idx,(key,num,label) in enumerate(ABILITY_ITEMS):
            y=body.top()+top+idx*(row_h+gap)
            rr=QRectF(body.left()+margin,y,body.width()-2*margin,row_h)
            self._row_rects.append(rr)
            on=self._switch[idx]
            if on>0.02:
                p.setPen(QPen(QColor(64,255,236,int(95+110*on)),1.7*sc))
                p.setBrush(QBrush(QColor(15,119,120,int(58+52*on))))
            else:
                p.setPen(QPen(QColor(190,255,252,115),1.2*sc))
                p.setBrush(QBrush(QColor(3,37,49,155)))
            p.drawRoundedRect(rr,15*sc,15*sc)

            p.setFont(num_font); p.setPen(QColor(187,249,247,235))
            p.drawText(QRectF(rr.left()+16*sc,rr.top(),42*sc,rr.height()),Qt.AlignmentFlag.AlignVCenter|Qt.AlignmentFlag.AlignLeft,num)
            p.setFont(text_font); p.setPen(QColor(248,255,255,248))
            p.drawText(QRectF(rr.left()+66*sc,rr.top(),rr.width()-148*sc,rr.height()),Qt.AlignmentFlag.AlignVCenter|Qt.AlignmentFlag.AlignLeft,label)

            sw_w=62*sc; sw_h=30*sc
            sr=QRectF(rr.right()-sw_w-14*sc,rr.center().y()-sw_h/2,sw_w,sw_h)
            if on>0.02:
                glowrect=sr.adjusted(-3*sc,-3*sc,3*sc,3*sc)
                p.setPen(QPen(QColor(40,255,236,int(55+85*on)),5*sc)); p.setBrush(Qt.BrushStyle.NoBrush)
                p.drawRoundedRect(glowrect,sw_h/2,sw_h/2)
                p.setPen(QPen(QColor(71,255,239,235),1.6*sc)); p.setBrush(QBrush(QColor(0,154,151,int(120+75*on))))
            else:
                p.setPen(QPen(QColor(190,231,232,120),1.3*sc)); p.setBrush(QBrush(QColor(13,34,42,220)))
            p.drawRoundedRect(sr,sw_h/2,sw_h/2)
            kr=sw_h*0.38
            kx=sr.left()+sw_h/2 + on*(sw_w-sw_h)
            kc=QPointF(kx,sr.center().y())
            if on>0.02:
                p.setPen(QPen(QColor(255,255,255,245),1)); p.setBrush(QBrush(QColor(246,255,254,255)))
            else:
                p.setPen(QPen(QColor(225,235,235,240),1)); p.setBrush(QBrush(QColor(232,240,240,250)))
            p.drawEllipse(kc,kr,kr)
        p.end()

    def mousePressEvent(self,event):
        if event.button()!=Qt.MouseButton.LeftButton or self._reveal<0.92:
            return super().mousePressEvent(event)
        pt=QPointF(event.position())
        for idx,rr in enumerate(self._row_rects):
            if rr.contains(pt):
                self._toggle(idx)
                event.accept(); return
        super().mousePressEvent(event)

    def _toggle(self,idx):
        target=0.0 if self._switch[idx]>0.5 else 1.0
        anim=self._switch_anims[idx]
        if anim is not None:
            try:anim.stop()
            except Exception:pass
        anim=QVariantAnimation(self)
        anim.setDuration(165)
        anim.setStartValue(float(self._switch[idx])); anim.setEndValue(target)
        anim.setEasingCurve(QEasingCurve.Type.InOutCubic)
        anim.valueChanged.connect(lambda v,i=idx:self._set_switch(i,float(v)))
        anim.finished.connect(lambda i=idx:self._ability_event(i))
        self._switch_anims[idx]=anim; anim.start()

    def _set_switch(self,idx,value):
        self._switch[idx]=max(0.0,min(1.0,float(value))); self.update()

    def _ability_event(self,idx):
        key=ABILITY_ITEMS[idx][0]
        enabled=self._switch[idx]>0.5
        # Future per-switch voice hooks intentionally terminate here. V0.10.0
        # only supplies the event name + state and the visual response.
        try:
            self.pet.setProperty("last_ability_event",f"{key}_{'on' if enabled else 'off'}")
        except Exception:
            pass
        LOGGER.info("[ABILITY] %s=%s",key,"ON" if enabled else "OFF")


'''
s=s.replace(pet_anchor,ability_classes+"\n"+pet_anchor,1)

# PetWindow construction: add the two child visuals without touching existing
# media layers or user-data paths.
ctor_anchor='''        self.dialogue_indicator = DialogueIndicator(self)
'''
ctor_new=ctor_anchor+'''        self.ability_form_overlay=AbilityFormOverlay(self)
        self.ability_sidebar=AbilitySidebarWindow(self.cfg,self)
        self.ability_node=AbilityNodeButton(self)
        self.ability_node.clicked.connect(self.toggle_ability_sidebar)
        self.ability_node.hide()
'''
if ctor_anchor not in s:
    raise RuntimeError("V0.10.0 dialogue-indicator constructor anchor missing")
s=s.replace(ctor_anchor,ctor_new,1)

# Resize / position the ability overlay and tiny anchor node with the pet.
resize_anchor='''        if hasattr(self, "dialogue_indicator"):
            lamp = max(22, int(round(w * 0.105)))
            self.dialogue_indicator.setGeometry(max(0, w-lamp-5), 5, lamp, lamp)
            self.dialogue_indicator.raise_()
'''
resize_new=resize_anchor+'''        if hasattr(self, "ability_form_overlay"):
            self.ability_form_overlay.setGeometry(0,0,w,h)
        if hasattr(self, "ability_node"):
            node=max(22,int(round(w*0.09)))
            self.ability_node.setFixedSize(node,node)
            self._ability_position_node(getattr(getattr(self,"ability_sidebar",None),"_side","left"))
            self.ability_node.raise_()
'''
if resize_anchor not in s:
    raise RuntimeError("V0.10.0 resize anchor missing")
s=s.replace(resize_anchor,resize_new,1)

# Add isolated ability helpers before the existing native click-through method.
method_anchor='''    def apply_clickthrough_native(self):
'''
ability_methods=r'''    def _ability_cfg(self):
        cfg=self.cfg.setdefault("ability_sidebar",{})
        changed=False
        for key,value in (("enabled",True),("voice_enabled",True),("voice_command_enabled",True)):
            if key not in cfg:
                cfg[key]=value; changed=True
        if changed:
            try:save_config(self.cfg)
            except Exception:pass
        return cfg

    def _ability_position_node(self,side="left"):
        if not hasattr(self,"ability_node"):
            return
        node=self.ability_node.width() or max(22,int(round(self.width()*0.09)))
        x=2 if str(side)!="right" else max(2,self.width()-node-2)
        y=max(2,int(round(self.height()*0.53-node/2)))
        self.ability_node.move(x,y)

    def _ability_refresh_node(self,force=False):
        if not hasattr(self,"ability_node"):
            return
        enabled=bool(self._ability_cfg().get("enabled",True))
        locked=bool(self.cfg.get("lock_position",False) or self.cfg.get("click_through",False))
        opened=bool(getattr(getattr(self,"ability_sidebar",None),"is_open",False))
        if enabled and not locked and (force or opened or self.underMouse()):
            self.ability_node.show(); self.ability_node.raise_()
        else:
            self.ability_node.hide()

    def _ability_hide_node_if_outside(self):
        if getattr(getattr(self,"ability_sidebar",None),"is_open",False):
            return
        if not self.underMouse():
            self._ability_refresh_node(False)

    def _ability_set_form_visible(self,visible):
        if not hasattr(self,"ability_form_overlay"):
            return
        if visible:
            for lab in self.labels:
                lab.hide()
            if hasattr(self,"mouse_layer"): self.mouse_layer.hide()
            if hasattr(self,"drag_layer"): self.drag_layer.hide()
            self.ability_form_overlay.show(); self.ability_form_overlay.raise_()
            if hasattr(self,"dialogue_indicator") and self.dialogue_indicator.isVisible(): self.dialogue_indicator.raise_()
            if hasattr(self,"ability_node"): self.ability_node.raise_()
        else:
            self.ability_form_overlay.hide()

    def _ability_restore_base_visuals(self):
        self._ability_set_form_visible(False)
        if self.report_active or self.dialogue_board_active or self.drag_visual_active or self.mouse_interaction_active:
            return
        for lab in self.labels:
            lab.show()

    def _ability_apply_form_if_possible(self):
        opened=bool(getattr(getattr(self,"ability_sidebar",None),"is_open",False))
        if not opened:
            return
        if self.report_active or self.dialogue_board_active or self.drag_visual_active or self.mouse_interaction_active:
            self._ability_set_form_visible(False); return
        if self.current_state=="idle":
            self._ability_set_form_visible(True)
        else:
            self._ability_set_form_visible(False)

    def toggle_ability_sidebar(self):
        if not hasattr(self,"ability_sidebar"):
            return
        if bool(self.cfg.get("lock_position",False) or self.cfg.get("click_through",False)):
            self.ability_sidebar.close_panel(); self._ability_refresh_node(False); return
        self.ability_sidebar.toggle_panel()
        self._ability_refresh_node(True)

    def refresh_ability_sidebar_config(self):
        if not hasattr(self,"ability_sidebar"):
            return
        if not bool(self._ability_cfg().get("enabled",True)):
            self.ability_sidebar.close_panel()
        self._ability_refresh_node(False)

    def enterEvent(self,event):
        try:self._ability_refresh_node(True)
        except Exception:pass
        super().enterEvent(event)

    def leaveEvent(self,event):
        super().leaveEvent(event)
        QTimer.singleShot(180,self._ability_hide_node_if_outside)

'''
if method_anchor not in s:
    raise RuntimeError("V0.10.0 clickthrough method anchor missing")
s=s.replace(method_anchor,ability_methods+method_anchor,1)

# State animations keep priority. The ability art disappears for any non-idle
# reaction and automatically returns after the state returns to idle.
play_anchor='''    def play_state(self, state, immediate=False, force_new_clip=False, asset_override=None):
        if self.dialogue_board_active:
'''
play_new='''    def play_state(self, state, immediate=False, force_new_clip=False, asset_override=None):
        try:
            if hasattr(self,"ability_sidebar") and self.ability_sidebar.is_open and state != "idle":
                self._ability_set_form_visible(False)
                for lab in self.labels: lab.show()
        except Exception:
            pass
        if self.dialogue_board_active:
'''
if play_anchor not in s:
    raise RuntimeError("V0.10.0 play_state anchor missing")
s=s.replace(play_anchor,play_new,1)

play_tail='''            self.current_state = state
            self.cfg["last_state"] = state
            save_config(self.cfg)
            LOGGER.info("切换状态 -> %s | 素材=%s", STATE_NAMES[state], Path(path).name)
'''
play_tail_new=play_tail+'''            if state == "idle" and hasattr(self,"ability_sidebar") and self.ability_sidebar.is_open:
                QTimer.singleShot(0,self._ability_apply_form_if_possible)
'''
if play_tail not in s:
    raise RuntimeError("V0.10.0 play_state completion anchor missing")
s=s.replace(play_tail,play_tail_new,1)

# Right-click fallback entry. Main entry remains the small body-side node.
menu_anchor='''        menu = QMenu(self)
        lock_action = menu.addAction("锁定小美丽（游戏防误触）")
        menu.addSeparator()
        showhide = menu.addAction("显示/隐藏")
        settings = menu.addAction("设置")
'''
menu_new='''        menu = QMenu(self)
        lock_action = menu.addAction("锁定小美丽（游戏防误触）")
        ability_action = menu.addAction("美丽能力侧栏")
        ability_action.setCheckable(True)
        ability_action.setChecked(bool(getattr(getattr(self,"ability_sidebar",None),"is_open",False)))
        menu.addSeparator()
        showhide = menu.addAction("显示/隐藏")
        settings = menu.addAction("设置")
'''
if menu_anchor not in s:
    raise RuntimeError("V0.10.0 context menu anchor missing")
s=s.replace(menu_anchor,menu_new,1)

choose_anchor='''        if chosen == lock_action:
            self.set_interaction_lock(True)
        elif chosen == showhide:
'''
choose_new='''        if chosen == lock_action:
            self.set_interaction_lock(True)
        elif chosen == ability_action:
            self.toggle_ability_sidebar()
        elif chosen == showhide:
'''
if choose_anchor not in s:
    raise RuntimeError("V0.10.0 context choice anchor missing")
s=s.replace(choose_anchor,choose_new,1)

# Add a compact ability card to the existing Interaction page.
interaction_anchor='''        card, _ = self._v774_card("拖拽互动", "悬挂姿态 + 惯性回弹", "动态眼球、身体、马尾和耳环继续沿用 V0.7.7.2 稳定逻辑。", control=self.v774_drag_cb)
        int_cards.append(card)

        card, _ = self._v774_card("主动互动", "尚未启用", "未来用于游戏事件主动吐槽、闲置主动动作等。")
'''
interaction_new='''        card, _ = self._v774_card("拖拽互动", "悬挂姿态 + 惯性回弹", "动态眼球、身体、马尾和耳环继续沿用 V0.7.7.2 稳定逻辑。", control=self.v774_drag_cb)
        int_cards.append(card)

        self.v0100_ability_cb = QCheckBox("开启")
        self.v0100_ability_cb.setChecked(bool(self.cfg.get("ability_sidebar",{}).get("enabled",True)))
        self.v0100_ability_cb.toggled.connect(self._v774_schedule_apply)
        card, _ = self._v774_card("美丽能力侧栏", "贴身展开 · 纯视觉娱乐", "五个能力开关只改变侧栏视觉；语音接口已预留，不读取或控制游戏。", control=self.v0100_ability_cb)
        int_cards.append(card)

        card, _ = self._v774_card("主动互动", "尚未启用", "未来用于游戏事件主动吐槽、闲置主动动作等。")
'''
if interaction_anchor not in s:
    raise RuntimeError("V0.10.0 interaction card anchor missing")
s=s.replace(interaction_anchor,interaction_new,1)

apply_anchor='''            if hasattr(self, "v774_transition_combo"):
                self.trans_spin.blockSignals(True)
                self.trans_spin.setValue(int(self.v774_transition_combo.currentData() or 200))
                self.trans_spin.blockSignals(False)
            self.apply()
'''
apply_new='''            if hasattr(self, "v774_transition_combo"):
                self.trans_spin.blockSignals(True)
                self.trans_spin.setValue(int(self.v774_transition_combo.currentData() or 200))
                self.trans_spin.blockSignals(False)
            if hasattr(self, "v0100_ability_cb"):
                acfg=self.cfg.setdefault("ability_sidebar",{})
                acfg["enabled"]=bool(self.v0100_ability_cb.isChecked())
                acfg.setdefault("voice_enabled",True)
                acfg.setdefault("voice_command_enabled",True)
            self.apply()
'''
if apply_anchor not in s:
    raise RuntimeError("V0.10.0 V774 apply anchor missing")
s=s.replace(apply_anchor,apply_new,1)

refresh_anchor='''                self.pet.apply_clickthrough_native()
                self.pet.refresh_mouse_interaction_config()
'''
refresh_new='''                self.pet.apply_clickthrough_native()
                self.pet.refresh_mouse_interaction_config()
                self.pet.refresh_ability_sidebar_config()
'''
if refresh_anchor not in s:
    raise RuntimeError("V0.10.0 settings-to-pet refresh anchor missing")
s=s.replace(refresh_anchor,refresh_new,1)

# Runtime self-test additions are deliberately static and side-effect-free.
checks=[
    'APP_VERSION = "0.10.0"',
    'class AbilitySidebarWindow(QWidget):',
    'class AbilityFormOverlay(QWidget):',
    'class AbilityNodeButton(QPushButton):',
    'ABILITY_ITEMS = [',
    'def toggle_ability_sidebar(self):',
    'def refresh_ability_sidebar_config(self):',
    '"美丽能力侧栏"',
    'QVariantAnimation',
    'assets/ability_form.png',
    'assets/MaokenAbilitySubset.otf',
]
for token in checks:
    if token not in s:
        raise RuntimeError("V0.10.0 verification missing: "+token)

# Strong negative safety checks for the new feature block. It must remain UI-only.
a=s.find("# V0.10.0 美丽能力侧栏")
b=s.find("class PetWindow(QWidget):",a)
if a<0 or b<0:
    raise RuntimeError("V0.10.0 ability block boundaries missing")
block=s[a:b]
for forbidden in (
    "ReadProcessMemory","WriteProcessMemory","OpenProcess","CreateRemoteThread",
    "SendInput","mouse_event","keybd_event","pynput","win32api.keybd_event",
    "requests.","urllib.","socket.","subprocess.","os.remove(","unlink(","rmtree("
):
    if forbidden in block:
        raise RuntimeError("V0.10.0 ability block violates UI-only contract: "+forbidden)

main.write_text(s,encoding="utf-8")
py_compile.compile(str(main),doraise=True)

sp=speech.read_text(encoding="utf-8")
sp=sp.replace("小美丽 V0.9.2.8 语音诊断日志","小美丽 V0.10.0 语音诊断日志")
speech.write_text(sp,encoding="utf-8")
py_compile.compile(str(speech),doraise=True)
version_file.write_text("0.10.0\n",encoding="ascii")
print("Patched XiaoMeili source to V0.10.0 ability sidebar")
