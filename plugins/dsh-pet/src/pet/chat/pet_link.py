from __future__ import annotations

import logging


class PetChatLink:
    def __init__(self, pet_window=None):
        self.pet_window = pet_window

    def set_window(self, w):
        self.pet_window = w

    def _notify(self, state, text=''):
        if self.pet_window and hasattr(self.pet_window, 'set_chat_status'):
            self.pet_window.set_chat_status(state, text)

    def thinking(self, text='正在想怎么回答…'):
        self._notify('thinking', text)

    def streaming(self, text):
        self._notify('streaming', text[:60])

    def success(self):
        self._notify('success', '')

    def error(self, text):
        self._notify('error', text[:80])

    def act(self, cue):
        """模型在回复里点的演出：交给桌宠窗口的导演闸门判该不该演。

        窗口可能是无界面的壳（多窗/覆盖层）或已经拆掉：拿不到 ``request_act``
        时静默略过。表演失败绝不影响聊天——它只是锦上添花。
        """
        request = getattr(self.pet_window, 'request_act', None)
        if not callable(request):
            return False
        try:
            return bool(request(cue))
        except Exception:
            logging.getLogger(__name__).exception('桌宠演出请求失败（已略过）')
            return False
